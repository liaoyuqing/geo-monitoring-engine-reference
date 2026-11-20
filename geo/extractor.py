"""Deterministic structured extraction over a raw LLM answer.

Design rule: the rule layer is the ONLY layer that decides numeric/positional
fields. An optional LLM judge may only (a) confirm, or (b) flag a segment for
human review; it never rewrites a position or a URL attribution.

Field contract (one row per brand mention):
    brand, position, first_char_window, sentiment, sentiment_evidence,
    source_url, source_url_attribution, negated
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from typing import Sequence

URL_RE = re.compile(r"https?://[^\s)\]）>,;\"']+")
HAN = r"\u4e00-\u9fff"

# negation cues that flip polarity when they sit between the brand and the
# sentiment word (or immediately before it, within NEG_WINDOW chars)
NEG_CUES = ("不", "没", "没有", "无法", "未", "难以", "不太", "不怎么", "不能", "缺乏", "不值得")
POS_WORDS = ("推荐", "值得", "优秀", "出色", "可靠", "满意", "好用", "强")
NEG_WORDS = ("不推荐", "偏贵", "一般", "差", "缺陷", "糊", "不稳定", "不满意")

NEG_WINDOW = 6          # chars scanned left of a sentiment word for a negation cue
URL_ATTRIB_WINDOW = 80  # chars: a URL belongs to the nearest brand inside this window


@dataclass(frozen=True)
class Mention:
    brand: str
    position: int
    sentiment: str
    sentiment_evidence: str
    source_url: str | None
    source_url_attribution: str   # "brand_window" | "answer_level" | None
    negated: bool


def _norm(s: str) -> str:
    return s.strip().lower()


def _find_brand(raw: str, aliases: Sequence[str]) -> int:
    """Earliest index of any alias, case-insensitive for latin aliases."""
    low = raw.lower()
    hits = [low.find(a.lower()) for a in aliases if a and low.find(a.lower()) >= 0]
    return min(hits) if hits else -1


def _sentiment(raw: str, pos: int) -> tuple[str, str, bool]:
    """Polarity for the mention at `pos`, using a bounded context window.

    Negation is resolved BEFORE polarity: a negative cue inside NEG_WINDOW
    chars to the left of the sentiment word flips positive -> negative and
    suppresses a bare negative word being read as positive (e.g.
    "\u4e0d\u63a8\u8350" must not be matched as "\u63a8\u8350").
    """
    start = max(0, pos - 40)
    end = min(len(raw), pos + 60)
    win = raw[start:end]

    # 1) explicit negative phrases first (longest match wins)
    for w in sorted(NEG_WORDS, key=len, reverse=True):
        i = win.find(w)
        if i >= 0:
            return "消极", win[max(0, i - 2): i + len(w) + 2], False

    # 2) positive word, but check for a negation cue just before it
    for w in sorted(POS_WORDS, key=len, reverse=True):
        i = win.find(w)
        if i >= 0:
            pre = win[max(0, i - NEG_WINDOW): i]
            if any(c in pre for c in NEG_CUES):
                return "消极", win[max(0, i - NEG_WINDOW): i + len(w)], True
            return "积极", win[max(0, i - 2): i + len(w) + 2], False

    return "中性", win, False


def _attribute_urls(raw: str, brand_positions: dict[str, int]) -> dict[str, tuple[str, str]]:
    """Map brand -> (url, attribution). Answer-level URLs are never silently
    attached to a brand: they are returned as ("answer_level") and the caller
    must keep attribution != "brand_window" so the metric layer can exclude them.
    """
    found = list(URL_RE.finditer(raw))
    result: dict[str, tuple[str, str]] = {}
    used: set[int] = set()
    for brand, bpos in brand_positions.items():
        best = None
        for idx, m in enumerate(found):
            if idx in used:
                continue
            gap = abs(m.start() - bpos)
            if gap <= URL_ATTRIB_WINDOW and (best is None or gap < best[0]):
                best = (gap, idx, m.group(0))
        if best:
            used.add(best[1])
            result[brand] = (best[2], "brand_window")
    for brand in brand_positions:
        if brand not in result and found:
            result[brand] = (found[0].group(0), "answer_level")
        elif brand not in result:
            result[brand] = (None, None)  # type: ignore[assignment]
    return result


def extract(raw: str, brand_aliases: dict[str, Sequence[str]]) -> list[Mention]:
    positions: dict[str, int] = {}
    for brand, aliases in brand_aliases.items():
        p = _find_brand(raw, aliases)
        if p >= 0:
            positions[brand] = p
    urls = _attribute_urls(raw, positions)
    rows: list[Mention] = []
    for brand in sorted(positions, key=lambda b: positions[b]):
        pos = positions[brand]
        senti, ev, neg = _sentiment(raw, pos)
        url, attrib = urls.get(brand, (None, None))
        rows.append(Mention(brand=brand, position=pos, sentiment=senti,
                            sentiment_evidence=ev, source_url=url,
                            source_url_attribution=attrib, negated=neg))
    return rows


def extract_dicts(raw: str, brand_aliases: dict[str, Sequence[str]]) -> list[dict]:
    return [asdict(m) for m in extract(raw, brand_aliases)]