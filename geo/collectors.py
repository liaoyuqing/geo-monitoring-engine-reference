"""Collector skeletons: one OpenAI-compatible API channel, one browser channel.

Both are deliberately transport-injected: this module builds the request and
normalises the response, but performs no I/O unless a caller passes a live
transport. That keeps the skeleton auditable (and unit-testable) without any
credentials, and makes it obvious where de-personalisation happens.

Provenance rules enforced here (round-2 fixes)
---------------------------------------------
* model_version is taken from the SERVER response only. The client-declared
  model name is never used as a fallback: if the server does not report it the
  row is rejected (round-1 bug: `resp.model or self.model` silently claimed a
  model that may not have answered).
* The raw response body is hashed BEFORE parsing (response_body_sha256) so the
  stored raw_answer can be re-hashed by a reviewer - the API-channel stand-in
  for a screenshot.
* The browser channel cannot obtain a server-reported model version for a web
  product, so it reads it from an explicit page-level probe and marks the
  source; if the probe returns nothing the row is rejected instead of storing
  the string "unknown".
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from .evidence import Evidence, account_fingerprint, body_sha256, prompt_hash


class Transport(Protocol):
    def post_json(self, url: str, payload: dict, headers: dict, timeout_s: float) -> dict: ...
    def open_page(self, url: str, ctx: dict, timeout_s: float) -> dict: ...


@dataclass
class ApiChannel:
    """OpenAI-compatible API channel (DeepSeek / Doubao Ark / Moonshot / DashScope / Qianfan)."""
    name: str
    base_url: str
    model: str
    key_id: str                 # NOT the secret; an opaque id used for the fingerprint
    temperature: float = 0.0
    seed: int | None = 42

    def build_request(self, prompt_text: str) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt_text}],
            "temperature": self.temperature,
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        return {"url": self.base_url.rstrip("/") + "/chat/completions", "payload": payload}

    def normalise(self, resp: dict, prompt_text: str, collected_at: str,
                  raw_body: str | bytes | None = None) -> Evidence:
        """Build an evidence row from a parsed response.

        `raw_body` is the exact bytes/text the server returned; it is hashed to
        give the API channel its screenshot surrogate. When a caller has only
        the parsed dict (unit tests, replays) the canonical JSON of that dict is
        hashed, and the caller is responsible for saying so in `extra`.
        """
        body = raw_body if raw_body is not None else json.dumps(resp, sort_keys=True)
        choice = (resp.get("choices") or [{}])[0]
        raw = (choice.get("message") or {}).get("content") or ""
        server_model = resp.get("model")
        return Evidence(
            raw_answer=raw,
            collected_at=collected_at,
            model_version=str(server_model) if server_model else "",   # server-only
            model_version_source="server",
            account_fingerprint_hash=account_fingerprint(self.key_id),
            channel="api",
            screenshot_sha256=None,
            screenshot_kind="none_api_channel",
            prompt_hash=prompt_hash(prompt_text),
            response_body_sha256=body_sha256(body),
            response_request_id=resp.get("id"),
            extra={"declared_model": self.model, "body_is_canonical_json": raw_body is None},
        )


@dataclass
class BrowserChannel:
    """Playwright channel for platforms without a public API (Yuanbao), and as a
    cross-check for platforms where the web product differs from the API model.

    De-personalisation is a property of the CONTEXT, not of the page code:
    a fresh incognito context per collection, pinned UA/viewport/locale, no
    persisted storage, and an exit-IP bound to the account. These are the only
    levers that survive a server-side change, so they are named explicitly.

    Model version for a web product is read from the page itself
    (`model_version_probe`), never assumed; `unknown` is not admissible.
    """
    name: str
    url: str
    account_ref: str
    viewport: tuple[int, int] = (1280, 1800)
    locale: str = "zh-CN"
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    exit_ip: str | None = None
    settle_ms: int = 1200

    def context_spec(self) -> dict:
        return {
            "incognito": True,
            "storage_state": None,          # never reuse cookies/localStorage
            "viewport": {"width": self.viewport[0], "height": self.viewport[1]},
            "locale": self.locale,
            "user_agent": self.user_agent,
            "proxy_exit_ip": self.exit_ip,  # bound per account, rotated across accounts
            "settle_ms": self.settle_ms,
        }

    def normalise(self, page_result: dict, prompt_text: str, collected_at: str) -> Evidence:
        return Evidence(
            raw_answer=page_result.get("answer_text", ""),
            collected_at=collected_at,
            model_version=str(page_result.get("model_version") or ""),   # page-reported only
            model_version_source="server",
            account_fingerprint_hash=account_fingerprint(self.account_ref),
            channel="browser",
            screenshot_sha256=page_result.get("screenshot_sha256"),
            screenshot_kind="full_page",
            screenshot_path=page_result.get("screenshot_path"),
            prompt_hash=prompt_hash(prompt_text),
            extra={"model_version_probe": page_result.get("model_version_probe")},
        )


def collectors() -> dict[str, dict[str, str]]:
    """Channel plan actually proposed for the six target platforms."""
    return {
        "doubao":   {"primary": "api(ark)", "fallback": "browser", "note": "ark model != web product; dual channel"},
        "deepseek": {"primary": "api", "fallback": "browser", "note": "lowest cost, best quota"},
        "yuanbao":  {"primary": "browser", "fallback": "", "note": "no public API; account pool + rate limit"},
        "kimi":     {"primary": "api(moonshot)", "fallback": "browser", "note": "api first"},
        "tongyi":   {"primary": "api(dashscope)", "fallback": "browser", "note": "api first"},
        "wenxin":   {"primary": "api(qianfan)", "fallback": "browser", "note": "qianfan != web product; dual channel"},
    }
