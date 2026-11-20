"""Variance and agreement statistics.

Two DIFFERENT quantities were conflated in the first draft. They are now kept
apart because they answer different questions and have different guarantees:

A) repeated_measurement_cv / within_band = per-Prompt repeatability.
   Same Prompt x same channel x same model, 3 runs -> how much does the
   brand-level metric move? This is what the order asks for ("same Prompt
   collected multiple times, variance <= 5%"). Reported per Prompt, then
   summarised as the fraction of Prompts inside the 5% band. It is measured,
   not proven: browser channels cannot pin temperature/seed, so it is a
   measurement with a published distribution, and Prompts that exceed the band
   are listed by id rather than averaged away.

B) sampling_se_pct / icc_1 / design_effect = population-level uncertainty.
   sqrt(p(1-p)/n) over 300 independent samples ~= 2.9 pp, then inflated by the
   design effect deff = 1 + (m-1) * ICC when the 300 samples are really 100
   Prompts x 3 repeats. This is NOT the repeatability of one Prompt and is
   never used to claim A.

Binary-unit note (round-2 requirement)
-------------------------------------
mention_rate is 0/1 per answer. With three repeats the band test
(max-min)/mean <= 5% therefore reduces to "all three repeats identical", i.e.
a 3/3 agreement requirement - a much stricter statement than "5% variance".
That is stated in the proposal instead of being hidden, and the continuous
metrics (mention_share, position_mean, citation_share) are the ones where a
5% band is a genuine tolerance.
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable, Sequence


def mention_rate(answer: str, brand_aliases: Sequence[str]) -> float:
    """1.0 if ANY alias appears, else 0.0. Binary by contract - see module note."""
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
    """A repeat set passes when (max-min)/mean <= band OR all repeats equal.

    For binary metrics (mention_rate) this is equivalent to requiring all
    repeats to agree; `is_binary` lets the report label that Prompts
    differently instead of quoting a meaningless "5%".
    """
    mean = statistics.fmean(samples)
    if mean == 0:
        return max(samples) == 0
    return (max(samples) - min(samples)) / mean <= band


def is_binary_metric(samples: Sequence[float]) -> bool:
    return all(v in (0.0, 1.0) for v in samples)


def sampling_se_pct(p: float, n: int) -> float:
    if n <= 0:
        raise ValueError("n must be positive")
    return 100.0 * math.sqrt(p * (1.0 - p) / n)


def icc_1(groups: Sequence[Sequence[float]]) -> float:
    """ICC(1) - one-way random-effects intraclass correlation.

    Measures how much of the total variance is BETWEEN Prompt groupings:
    high ICC = repeats inside a Prompt agree, Prompts differ. That is exactly
    the quantity that inflates the variance of an aggregate built from
    clustered samples, and the one the proposal promises to report.

    Requires >= 2 groups, >= 2 observations each, balanced by construction
    (we always collect the same number of repeats per Prompt).
    """
    if len(groups) < 2:
        raise ValueError("need >= 2 groups (Prompts)")
    sizes = {len(g) for g in groups}
    if len(sizes) != 1:
        raise ValueError(f"unbalanced groups: sizes {sorted(sizes)}")
    m = sizes.pop()
    if m < 2:
        raise ValueError("need >= 2 observations per group")
    k = len(groups)
    grand = statistics.fmean([v for g in groups for v in g])
    group_means = [statistics.fmean(g) for g in groups]
    ss_between = m * sum((mu - grand) ** 2 for mu in group_means)
    ss_within = sum((v - statistics.fmean(g)) ** 2 for g in groups for v in g)
    ms_between = ss_between / (k - 1)
    ms_within = ss_within / (k * (m - 1))
    denom = ms_between + (m - 1) * ms_within
    if denom == 0:
        return 0.0
    icc = (ms_between - ms_within) / denom
    return max(0.0, icc)


def design_effect(m: int, icc: float) -> float:
    """deff = 1 + (m - 1) * ICC, m = cluster size (repeats per Prompt)."""
    if m < 1:
        raise ValueError("cluster size must be >= 1")
    return 1.0 + (m - 1) * max(0.0, min(1.0, icc))


def clustered_se_pct(p: float, n_clusters: int, m: int, icc: float) -> float:
    """Sampling SE of an aggregate whose samples are clustered in Prompts.

    Effective sample size is n_clusters * m / deff, so clustering can only
    widen the interval - never narrow it.
    """
    if n_clusters <= 0 or m <= 0:
        raise ValueError("n_clusters and m must be positive")
    n_eff = n_clusters * m / design_effect(m, icc)
    return sampling_se_pct(p, max(1, int(round(n_eff))))


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
