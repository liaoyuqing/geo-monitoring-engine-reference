"""White-hat guardrails: refuse to emit content that cannot be sourced."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

BANNED_PATTERNS = ("最好", "第一", "顶级", "国家级", "全网最", "绝对", "百分之百", "超级")


class ComplianceError(ValueError):
    pass


@dataclass(frozen=True)
class Claim:
    text: str
    fact_source_ids: Sequence[str]


def check_claims(claims: Sequence[Claim], known_source_ids: Sequence[str]) -> None:
    """Every claim must cite at least one EXISTING source id. No source, no text.

    This is the mechanism behind the promise "never fabricate a citable source":
    the generator is not trusted, the gate is.
    """
    known = set(known_source_ids)
    for c in claims:
        if not c.fact_source_ids:
            raise ComplianceError("claim without fact_source_ids: " + c.text[:30])
        unknown = [s for s in c.fact_source_ids if s not in known]
        if unknown:
            raise ComplianceError("claim cites unknown source ids: " + repr(unknown))
        for pat in BANNED_PATTERNS:
            if pat in c.text:
                raise ComplianceError("advertising-law banned term " + repr(pat) + " in: " + c.text[:30])