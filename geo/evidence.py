"""Evidence envelope: the five mandatory fields plus provenance.

Every MonitorResult row must satisfy this envelope or it is rejected at
ingest time (fail-closed).

Surrogates for the screenshot (round-2 fix)
------------------------------------------
The order lists five per-record artefacts: raw answer, screenshot, timestamp,
model version, account fingerprint hash. A pure-API channel can never produce
a page screenshot, so instead of pretending one exists, an API row must carry
two DIFFERENT surrogates and the row is rejected without them:

  * response_body_sha256 - sha256 of the exact response body the server
    returned. This is what a reviewer re-hashes to prove the raw_answer was
    not edited afterwards.
  * response_request_id  - the server-side request id, so the vendor can be
    asked to confirm that the request happened at all.

screenshot_kind records WHY there is no image (none_api_channel /
none_browser_failure) instead of leaving the field silently empty.

model_version provenance (round-2 fix)
-------------------------------------
model_version is only admissible when the SERVER reported it. Falling back to
 the client-declared model string means a row can claim a model that never
answered, so `model_version_source` must be "server" and "unknown" is
rejected outright.
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


def body_sha256(body: bytes | str) -> str:
    """sha256 of the raw response body - the API-channel stand-in for a screenshot."""
    data = body.encode("utf-8") if isinstance(body, str) else body
    return hashlib.sha256(data).hexdigest()


@dataclass
class Evidence:
    raw_answer: str
    collected_at: str            # ISO8601 with offset
    model_version: str           # server-reported, never client-declared
    account_fingerprint_hash: str
    channel: str                 # "api" | "browser"
    model_version_source: str = "server"   # "server" only; anything else is rejected
    screenshot_sha256: str | None = None
    screenshot_kind: str | None = None   # "full_page" | "none_api_channel" | "none_browser_failure"
    screenshot_path: str | None = None
    prompt_hash: str | None = None
    response_body_sha256: str | None = None   # API surrogate #1
    response_request_id: str | None = None    # API surrogate #2
    extra: dict[str, Any] | None = None

    def validate(self) -> None:
        for k in FIVE:
            v = getattr(self, k, None)
            if v in (None, ""):
                raise EvidenceError(f"missing evidence field: {k}")
        if self.model_version_source != "server":
            raise EvidenceError(
                "model_version must be server-reported; client-declared or unknown is not admissible")
        if str(self.model_version).lower() in ("unknown", "none", "-"):
            raise EvidenceError("model_version is unknown: the server did not report it")
        if not self.collected_at.endswith("Z") and ("+" not in self.collected_at[10:] and "-" not in self.collected_at[10:]):
            raise EvidenceError("collected_at must carry an explicit UTC offset")
        if self.channel == "api":
            if self.screenshot_sha256 is not None:
                raise EvidenceError("api channel cannot carry a screenshot; do not fabricate one")
            if self.screenshot_kind not in (None, "none_api_channel"):
                raise EvidenceError("api channel screenshot_kind must be none_api_channel")
            # the two surrogates that replace the screenshot
            if not self.response_body_sha256 or len(self.response_body_sha256) != 64:
                raise EvidenceError(
                    "api row needs response_body_sha256 (64 hex chars) as the screenshot surrogate")
            if not self.response_request_id:
                raise EvidenceError(
                    "api row needs response_request_id so the vendor can confirm the request")
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
        return dict(self.__dict__)
