"""Variance and agreement statistics.

Two DIFFERENT quantities were conflated in the first draft. They are now kept
apart because they answer different questions and have different guarantees:

A) repeated_measurement_cv  = per-Prompt repeatability.
   Same Prompt x same channel x same model, 3 runs -> how much does the
   brand-level metric move? This is what the order asks for ("same Prompt
   collected multiple times, variance <= 5%"). Reported per Prompt, then
   summarised as the fraction of Prompts inside the 5% band. It is measured,
   not proven: browser channels cannot pin temperature/seed, so it is a
   measurement with a published distribution, and Prompts that exceed the band
   are listed by id rather than averaged away.

B) sampling_se_pct = population-level uncertainty of the aggregate.
   sqrt(p(1-p)/n) over 300 independent samples ~= 2.9 pp. This is NOT the
   repeatability of one Prompt and is never used to claim A.
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable, Sequence


def mention_rate(answer: str, brand_aliases: Sequence[str]) -> float:
    low = answer.lower()
    return 1.0 if any(a.lower() in low for a in brand_aliases) else 0.0


def repeated_measurement_cv(samples: Sequence[float]) -> float:
    """Coefficient of variation across repeats of ONE prompt."""
    if len(samples) < 2:
        raise ValueError("need >= 2 repeats")
    mean = statistics.fmean(samples)
    if mean == 0:
        return 0.0 if max(samples) == 0 else float("inf")
    sd = statistics.stdev(samples)
    return sd / mean


def within_band(samples: Sequence[float], band: float = 0.05) -> bool:
    """A repeat set passes when (max-min)/mean <= band OR all repeats equal."""
    mean = statistics.fmean(samples)
    if mean == 0:
        return max(samples) == 0
    return (max(samples) - min(samples)) / mean <= band


def sampling_se_pct(p: float, n: int) -> float:
    if n <= 0:
        raise ValueError("n must be positive")
    return 100.0 * math.sqrt(p * (1.0 - p) / n)


def pass_fraction(per_prompt: Iterable[tuple[str, bool]]) -> tuple[float, list[str]]:
    rows = list(per_prompt)
    if not rows:
        return 0.0, []
    ok = sum(1 for _, v in rows if v)
    return ok / len(rows), [pid for pid, v in rows if not v]


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("two non-empty equal-length label sets required")
    labels = sorted(set(a) | set(b))
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = 0.0
    for lab in labels:
        pa = sum(1 for x in a if x == lab) / n
        pb = sum(1 for y in b if y == lab) / n
        pe += pa * pb
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1.0 - pe)