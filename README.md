# GEO monitoring engine — reference implementation (Phase-1 proposal artifact)

Order **#1365** (GEO 智能可见度优化平台), deliverable 5: a **clonable,
publicly readable** artifact that a reviewer can verify right now, without
credentials and without waiting for an NDA.

- Repo: https://github.com/liaoyuqing/geo-monitoring-engine-reference
- Python: 3.10+ , **standard library only** (no pip install needed)
- Tests: `python -m unittest discover -s tests -t .`

```
Ran 42 tests in 0.001s

OK
```

## Why this artifact exists

The order asks for "at least one project case, prototype, or verifiable team
capability proof", and the buyer rejected the first draft because the code was
described but not reachable, and the inline sample did not touch collection.
This repository is the answer to that objection: every claim below is backed by
a test that runs offline in milliseconds.

| Buyer objection | Where it is answered | Proof |
|---|---|---|
| No verifiable, clonable proof | this repo | `git clone` then run the tests |
| 60 s ceiling contradicts "45 s timeout + 1 retry" | `geo/timeout.py` | `TestTimeoutBudget.test_two_slow_attempts_cannot_exceed_60s` |
| variance claim mixed sampling error with repeatability | `geo/stats.py` | `test_sampling_se_is_not_repeatability` |
| extraction accuracy: negation / multi-brand / URL attribution | `geo/extractor.py` | `TestSentiment`, `TestUrlAttribution` |
| "same as above" rows for Kimi/Tongyi/Wenxin; API has no screenshot; fingerprint was not an account identity | `geo/collectors.py`, `geo/evidence.py` | `TestBrowserChannel`, `TestEvidence` |
| browser-only platform cannot meet 100 prompts / 30 min | `geo/runner.py` | `test_browser_only_platform_breaches_30min_at_low_rate` |
| 6 people vs 7 roles; V3.0 arithmetic | §4 of the resubmitted proposal | table recomputed below |

## Layout

```
geo/
  extractor.py    deterministic brand/position/sentiment/URL extraction
  evidence.py     five-field evidence envelope, fail-closed validation
  timeout.py      total-deadline budget that makes the 60 s ceiling provable
  stats.py        repeatability (CV) vs sampling error (SE), kept apart
  runner.py       chunked / resumable batch runner, per-platform isolation
  collectors.py   API channel + incognito browser channel skeletons
  compliance.py   fact-source gate (no source -> no text)
tests/            42 unittest cases, zero network, zero credentials
```

## What this artifact deliberately does NOT do

It performs **no network I/O**. A transport is injected, so the scheduling,
de-personalisation and evidence logic can be audited without a key. Real
collection against the six platforms is the scope of MVP M1/M2 and requires the
buyer’s accounts or API quotas — there is no honest way to produce six-platform
measurements before then, and the first draft was rejected for implying
otherwise.

## Reproducing the numbers quoted in the proposal

```bash
cd geo-demo
python -m unittest discover -s tests -t . -v
```

- 60 s ceiling: `simulate(Budget(), [999, 999])` returns spent <= 60.0, not 80.
  Attempt 1 gets `min(40, 60) = 40 s`, attempt 2 gets `min(40, 20) = 20 s`.
- Repeatability vs sampling error are separate functions by construction;
  `sampling_se_pct(0.5, 300) = 2.89` is population uncertainty and is never
  reported as per-Prompt variance.
- Yuanbao at 3 requests/min with a 1-account pool needs 33.3 min for 100
  prompts, which breaches the 30 min ceiling; the code returns that platform in
  a `_breach` list instead of hiding it. A 4-account pool brings it to 8.3 min.

## Licence / data

All fixtures are fictional (「蓝湾白酒」 and 「竞品甲」 are invented brands). No
customer name, no real account, no scraped content is included.