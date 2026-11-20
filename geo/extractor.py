"""Deterministic structured extraction over a raw LLM answer.

Design rule: the rule layer is the ONLY layer that decides numeric/positional
fields. An optional LLM judge may only (a) confirm, or (b) flag a segment for
human review; it never rewrites a position or a URL attribution.

Field contract (one row per brand mention):
    brand, position, sentiment, sentiment_evidence, source_url,
    source_url_attribution, negated

Sentiment scoping (round-2 fix)
-------------------------------
A mention's polarity is resolved inside the CLAUSE that contains it. A clause
is the run of text between two sentence/clause delimiters (CLAUSE_SEP: ，,。.
；;！!？? and newlines). Inside that clause the window is further clipped
so it never crosses a neighbouring brand span, then padded with the adjacent
clause only when the current clause carries no polarity word at all.

Why: a negative word that belongs to a competitor used to leak onto the earlier
brand, because the whole 100-char window was scanned for negative words first.
Both of these were wrong before this fix and are asserted now:

    "蓝湾白酒值得推荐，竞品甲一般"  -> 蓝湾 消极 (borrowed 竞品甲's 一般)
    "蓝湾白酒不推荐，竞品甲很优秀" -> 竞品甲 消极 (borrowed 蓝湾's 不推荐)

Both now resolve per clause: 积极/消极 and 消极/积极 respectively.

Known scope limit: only the EARLIEST mention of each brand is scored (one row
per brand per answer). Per-mention rate is a separate metric and is excluded
from this artifact on purpose rather than half-implemented.

Known scope limit: only the EARLIEST mention of each brand is scored (one row
per brand per answer). Per-mention rate is a separate metric and is excluded
from this artifact on purpose rather than half-implemented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Sequence

URL_RE = re.compile(r"https?://[^\s)\]）>,;\"']+")

# negation cues that flip polarity when they sit between the brand and the
# sentiment word (or immediately before it, within NEG_WINDOW chars)
NEG_CUES = ("不", "没", "没有", "无法", "未", "难以", "不太", "不怎么", "不能", "缺乏", "不值得")
POS_WORDS = ("推荐", "值得", "优秀", "出色", "可靠", "满意", "好用", "强")
NEG_WORDS = ("不推荐", "偏贵", "一般", "差", "缺陷", "糊", "不稳定", "不满意")

NEG_WINDOW = 6          # chars scanned left of a sentiment word for a negation cue
URL_ATTRIB_WINDOW = 80  # chars: a URL belongs to the nearest brand inside this window
LEFT_CTX = 40           # chars of left context considered for polarity
RIGHT_CTX = 60          # chars of right context considered for polarity
CLAUSE_SEP = "，,。.；;！!？?\n\r"   # sentence / clause delimiters


@dataclass(frozen=True)
class Mention:
    brand: str
    position: int
    sentiment: str
    sentiment_evidence: str
    source_url: str | None
    source_url_attribution: str   # "brand_window" | "answer_level" | None
    negated: bool


def _find_spans(raw: str, brand_aliases: dict[str, Sequence[str]]) -> dict[str, tuple[int, int]]:
    """Earliest (start, end) span per brand. Case-insensitive for latin aliases."""
    low = raw.lower()
    spans: dict[str, tuple[int, int]] = {}
    for brand, aliases in brand_aliases.items():
        best: tuple[int, int] | None = None
        for a in aliases:
            if not a:
                continue
            i = low.find(a.lower())
            if i >= 0 and (best is None or i < best[0]):
                best = (i, i + len(a))
        if best is not None:
            spans[brand] = best
    return spans


def _clause_bounds(raw: str, pos: int) -> tuple[int, int]:
    """(start, end) of the clause containing offset `pos`."""
    lo = 0
    for i in range(pos - 1, -1, -1):
        if raw[i] in CLAUSE_SEP:
            lo = i + 1
            break
    hi = len(raw)
    for j in range(pos, len(raw)):
        if raw[j] in CLAUSE_SEP:
            hi = j
            break
    return lo, hi


def _has_polarity(seg: str) -> bool:
    return any(w in seg for w in POS_WORDS) or any(w in seg for w in NEG_WORDS)


def _window(raw: str, spans: dict[str, tuple[int, int]], brand: str) -> str:
    """Polarity window for `brand`: its own clause, clipped at neighbour brands.

    If the clause carries no polarity word (e.g. the brand sits in a bare
    subject clause and the verdict lands in the next clause), the window is
    widened by one clause to the right, then one to the left, still without
    crossing another brand mention.
    """
    start, end = spans[brand]
    lo, hi = _clause_bounds(raw, start)
    if _has_polarity(raw[lo:hi]):
        return raw[lo:hi]
    # widen right by one clause
    r_hi = hi
    for j in range(hi + 1, len(raw)):
        if raw[j] in CLAUSE_SEP:
            r_hi = j
            break
    else:
        r_hi = len(raw)
    # widen left by one clause
    l_lo = lo
    for i in range(lo - 2, -1, -1):
        if raw[i] in CLAUSE_SEP:
            l_lo = i + 1
            break
    else:
        l_lo = 0 if lo > 0 else lo

    prev_end = 0
    next_start = len(raw)
    for other, (os_, oe_) in spans.items():
        if other == brand:
            continue
        if oe_ <= start and oe_ > prev_end:
            prev_end = oe_
        if os_ >= end and os_ < next_start:
            next_start = os_

    hi2 = min(r_hi, next_start)
    if _has_polarity(raw[lo:hi2]):
        return raw[lo:hi2]
    lo2 = max(l_lo, prev_end)
    if _has_polarity(raw[lo2:hi2]):
        return raw[lo2:hi2]
    return raw[lo:hi]


def _sentiment(win: str) -> tuple[str, str, bool]:
    """Polarity for a pre-clipped window.

    Negation is resolved BEFORE polarity: a negative cue inside NEG_WINDOW
    chars to the left of the sentiment word flips positive -> negative and
    suppresses a bare negative word being read as positive (e.g. "不推荐"
    must not be matched as "推荐").
    """
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


def _attribute_urls(raw: str, brand_positions: dict[str, int]) -> dict[str, tuple[str | None, str | None]]:
    """Map brand -> (url, attribution). Answer-level URLs are never silently
    attached to a brand: they are returned as ("answer_level") and the caller
    must keep attribution != "brand_window" so the metric layer can exclude them.
    """
    found = list(URL_RE.finditer(raw))
    result: dict[str, tuple[str | None, str | None]] = {}
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
        if brand not in result:
            result[brand] = (found[0].group(0), "answer_level") if found else (None, None)
    return result


def extract(raw: str, brand_aliases: dict[str, Sequence[str]]) -> list[Mention]:
    spans = _find_spans(raw, brand_aliases)
    urls = _attribute_urls(raw, {b: s[0] for b, s in spans.items()})
    rows: list[Mention] = []
    for brand in sorted(spans, key=lambda b: spans[b][0]):
        pos = spans[brand][0]
        senti, ev, neg = _sentiment(_window(raw, spans, brand))
        url, attrib = urls.get(brand, (None, None))
        rows.append(Mention(brand=brand, position=pos, sentiment=senti,
                            sentiment_evidence=ev, source_url=url,
                            source_url_attribution=attrib, negated=neg))
    return rows


def extract_dicts(raw: str, brand_aliases: dict[str, Sequence[str]]) -> list[dict]:
    return [asdict(m) for m in extract(raw, brand_aliases)]
