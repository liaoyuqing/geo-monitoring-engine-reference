# GEO monitoring engine — reference implementation (Phase-1 proposal artifact)

Order **#1365** (GEO 智能可见度优化平台), deliverable 5: a **clonable,
publicly readable** artifact that a reviewer can verify right now, without
credentials and without waiting for an NDA.

- Repo: https://github.com/liaoyuqing/geo-monitoring-engine-reference
- Python: 3.10+ , **standard library only** (no pip install needed)
- Tests: `python -m unittest discover -s tests -t .`

```
Ran 64 tests in 0.004s

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
### Round-2 objections (second rework request) - fixed in code, not in prose

| Buyer objection | Fix in code | Proof (all names are real; run the suite) |
|---|---|---|
| multi-brand sentiment: a competitor negative word was scored onto the earlier brand | the polarity window is now the mention own **clause**, clipped at neighbour brand spans, widened by one clause only when the clause holds no polarity word | `TestMultiBrandSentiment.test_later_competitor_negative_does_not_leak_left`, `test_earlier_brand_negative_does_not_leak_right`, `test_reversed_order_gives_the_same_pair`, `test_verdict_in_following_clause_still_reaches_the_subject` |
| API channel cannot produce a screenshot, so what is the artefact? | two mandatory surrogates: `response_body_sha256` (re-hashable) + `response_request_id` (vendor-confirmable); a row without them is rejected | `test_api_row_without_body_hash_is_rejected`, `test_api_row_without_request_id_is_rejected`, `test_body_hash_is_deterministic_and_distinguishes_bodies` |
| browser channel accepted `model_version="unknown"`; API silently fell back to the client-declared model | both channels reject unknown or client-declared model versions; the web product reads its version from an explicit page probe | `test_unknown_model_version_is_rejected`, `test_client_declared_model_version_is_rejected`, `test_missing_server_model_is_not_backfilled_with_the_declared_one`, `test_browser_row_without_model_version_fails` |
| §2.3 claims ICC / design effect, but neither was implemented | `icc_1`, `design_effect`, `clustered_se_pct` implemented and tested; clustering can only widen the interval | `TestClusteredVariance.test_design_effect_formula`, `test_clustered_se_is_never_smaller_than_plain_se`, `test_icc_of_disjoint_groups_is_one`, `test_icc_requires_balanced_groups` |
| binary `mention_rate` makes "5% variance" mean "3 of 3 identical" | stated in the `geo/stats.py` docstring and surfaced by `is_binary_metric`, so the report labels those Prompts instead of quoting a meaningless 5% | `test_binary_metric_band_means_all_repeats_must_agree` |

## Layout

```
geo/
  extractor.py    brand/position/sentiment/URL extraction, clause-scoped polarity
  evidence.py     five-field envelope + API surrogates, fail-closed validation
  timeout.py      total-deadline budget that makes the 60 s ceiling provable
  stats.py        repeatability (CV) vs sampling error (SE vs clustered SE) + ICC
  runner.py       chunked / resumable batch runner, per-platform isolation
  collectors.py   API channel + incognito browser channel skeletons
  compliance.py   fact-source gate (no source -> no text)
tests/            64 unittest cases, zero network, zero credentials
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
- Design effect with 3 repeats per Prompt: `deff = 1 + (3-1) * ICC`. At ICC 0.5
  the effective sample size of 300 clustered samples is 150, so the aggregate
  95 percent half-width goes from 2.89 pp to 4.08 pp. Clustering can only widen
  it: `clustered_se_pct(0.5, 100, 3, 0.0) == sampling_se_pct(0.5, 300)`.
- Multi-brand polarity is clause-scoped. Run the suite and look at
  `TestMultiBrandSentiment`: for the answer "蓝湾白酒值得推荐，竞品甲一般。" the first
  brand is 积极 and the second is 消极. The pre-fix code returned 消极 for both,
  because the negative word list was scanned first over a 100-char window that
  crossed the other brand - that is exactly the bug the buyer found.

## Licence / data

All fixtures are fictional (「蓝湾白酒」 and 「竞品甲」 are invented brands). No
customer name, no real account, no scraped content is included.