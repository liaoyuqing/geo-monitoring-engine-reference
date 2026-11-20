"""Batch runner: chunked, resumable, per-platform isolated, degrade-aware.

Does not call any network endpoint. A transport is injected (real API client,
Playwright page, or a fake in tests), so the scheduling and degradation logic
is testable without credentials.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .timeout import Budget


@dataclass
class Task:
    task_id: str
    platform: str
    prompt_id: str
    prompt_text: str


@dataclass
class PlatformPolicy:
    platform: str
    channel: str                  # "api" | "browser"
    max_per_minute: int           # browser channels are 3-5, api by qps
    offline_fallback: bool = False


@dataclass
class BatchResult:
    done: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    partial: bool = False
    skipped_platforms: list[str] = field(default_factory=list)


def platform_budget_minutes(policy: PlatformPolicy, n_prompts: int, concurrency: int = 1) -> float:
    """Lower bound on wall-clock minutes for one platform.

    Browser channels are rate limited by requests-per-minute and cannot be
    parallelised beyond the account pool, so the honest answer for a single
    browser-only platform at 3 r/min is n/3 minutes, which exceeds a 30 min
    ceiling above 90 prompts. The caller must either raise the account pool or
    declare the platform an explicit exception.
    """
    # Both channels scale with the number of independent workers: API by qps,
    # browser by account-pool size (each account has its own session and rate).
    per_min = max(1, policy.max_per_minute * max(1, concurrency))
    return n_prompts / per_min


def run_batch(tasks: Sequence[Task],
              policies: dict[str, PlatformPolicy],
              transport: Callable[[Task, Budget], tuple[bool, str]],
              deadline_minutes: float = 30.0,
              resume_from: Iterable[str] = ()) -> BatchResult:
    """Execute tasks in platform-round-robin order so one slow platform cannot
    starve the others. transport returns (ok, detail)."""
    done_before = set(resume_from)
    result = BatchResult()
    queue = [t for t in tasks if t.task_id not in done_before]
    by_platform: dict[str, list[Task]] = {}
    for t in queue:
        by_platform.setdefault(t.platform, []).append(t)
    order: list[Task] = []
    while any(by_platform.values()):
        for p in list(by_platform):
            if by_platform[p]:
                order.append(by_platform[p].pop(0))
            if not by_platform[p]:
                del by_platform[p]
    for t in order:
        pol = policies.get(t.platform)
        if pol is None:
            result.failed[t.task_id] = "no policy for platform"
            result.skipped_platforms.append(t.platform)
            continue
        budget = Budget()
        ok, detail = transport(t, budget)
        if ok:
            result.done.append(t.task_id)
        else:
            result.failed[t.task_id] = detail
    if result.failed:
        result.partial = True
    return result


def degraded_plan(policies: dict[str, PlatformPolicy], n_prompts: int,
                  ceiling_minutes: float = 30.0, account_pool: int = 1) -> dict[str, object]:
    """Per-platform minutes plus an explicit breach list, so a platform that
    cannot meet the ceiling is declared instead of silently dropped."""
    plan: dict[str, object] = {}
    breach: list[str] = []
    for name, pol in policies.items():
        mins = round(platform_budget_minutes(pol, n_prompts, account_pool), 2)
        plan[name] = mins
        if mins > ceiling_minutes:
            breach.append(name)
    plan["_breach"] = breach
    return plan