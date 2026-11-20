"""Single-attempt deadline arithmetic that makes the 60 s ceiling provable.

Claim under audit: "single collection <= 60 s". A per-attempt timeout plus one
retry can reach 2x the attempt timeout, so the budget must be expressed as a
TOTAL deadline, enforced across attempts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time


@dataclass
class Budget:
    total_s: float = 60.0
    connect_s: float = 5.0
    read_s: float = 40.0
    max_attempts: int = 2
    _started: float = field(default_factory=time.monotonic)

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started

    @property
    def remaining(self) -> float:
        return max(0.0, self.total_s - self.elapsed)

    def attempt_deadline(self) -> float:
        """Per-attempt timeout = min(configured read timeout, remaining budget).

        The remaining-budget clamp is what makes the overall ceiling hold:
        attempt 1 = min(40, 60) = 40 s, attempt 2 = min(40, ~20) = 20 s,
        so worst case is 60 s total, not 80 s.
        """
        return max(0.0, min(self.read_s, self.remaining))

    def can_retry(self, attempts_done: int) -> bool:
        return attempts_done < self.max_attempts and self.remaining > 1.0


def simulate(budget: Budget, attempt_costs: list[float]) -> tuple[float, int, bool]:
    """Deterministic simulation used by the tests (no sleeping)."""
    spent = 0.0
    attempts = 0
    ok = False
    for cost in attempt_costs:
        if attempts >= budget.max_attempts:
            break
        allowed = min(budget.read_s, max(0.0, budget.total_s - spent))
        if allowed <= 1.0:
            break
        attempts += 1
        if cost <= allowed:
            spent += cost
            ok = True
            break
        spent += allowed   # attempt timed out at its deadline
    return spent, attempts, ok