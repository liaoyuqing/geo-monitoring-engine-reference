"""Evidence envelope: the five mandatory fields plus provenance.

Every MonitorResult row must satisfy this envelope or it is rejected at
ingest time (fail-closed). API-channel rows cannot produce a page screenshot,
so `screenshot_sha256` is None AND `screenshot_kind` records WHY, instead of
pretending a screenshot exists.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

FIVE = ("raw_answer", "collected_at", "model_version", "account_fingerprint_hash", "channel")


class EvidenceError(ValueError):
    pass


def account_fingerprint(account_ref: str) -> str:
    """Stable, non-reversible account fingerprint.

    Hashed from the account identifier only (never from the timestamp), so the
    same account always maps to the same fingerprint and rotating time does
    not create a fake new identity.
    """
    if not account_ref:
        raise EvidenceError("account_ref required: API-key channel uses key_id, browser channel uses account pool id")
    return hashlib.sha256(("acct:" + account_ref).encode("utf-8")).hexdigest()[:16]


def prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16]


@dataclass
class Evidence:
    raw_answer: str
    collected_at: str            # ISO8601 with offset
    model_version: str           # server-reported, never client-declared
    account_fingerprint_hash: str
    channel: str                 # "api" | "browser"
    screenshot_sha256: str | None = None
    screenshot_kind: str | None = None   # "full_page" | "none_api_channel" | "none_browser_failure"
    screenshot_path: str | None = None
    prompt_hash: str | None = None
    response_request_id: str | None = None
    extra: dict[str, Any] | None = None

    def validate(self) -> None:
        for k in FIVE:
            v = getattr(self, k, None)
            if v in (None, ""):
                raise EvidenceError(f"missing evidence field: {k}")
        if not self.collected_at.endswith("Z") and ("+" not in self.collected_at[10:] and "-" not in self.collected_at[10:]):
            raise EvidenceError("collected_at must carry an explicit UTC offset")
        if self.channel == "api":
            if self.screenshot_sha256 is not None:
                raise EvidenceError("api channel cannot carry a screenshot; do not fabricate one")
            if self.screenshot_kind not in (None, "none_api_channel"):
                raise EvidenceError("api channel screenshot_kind must be none_api_channel")
        elif self.channel == "browser":
            if self.screenshot_sha256 is None:
                raise EvidenceError("browser channel row without screenshot is not admissible")
            if self.screenshot_kind != "full_page":
                raise EvidenceError("browser channel screenshot_kind must be full_page")
        else:
            raise EvidenceError(f"unknown channel: {self.channel}")
        if len(self.account_fingerprint_hash) != 16:
            raise EvidenceError("account_fingerprint_hash must be 16 hex chars")

    def as_row(self) -> dict[str, Any]:
        self.validate()
        d = dict(self.__dict__)
        return d