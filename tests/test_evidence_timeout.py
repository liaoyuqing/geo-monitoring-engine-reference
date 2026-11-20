import unittest

from geo.evidence import Evidence, EvidenceError, account_fingerprint, body_sha256
from geo.timeout import Budget, simulate

BODY_SHA = "b" * 64


class TestEvidence(unittest.TestCase):
    def _api_row(self, **kw):
        base = dict(raw_answer="蓝湾白酒值得推荐",
                    collected_at="2026-11-20T09:30:00+08:00",
                    model_version="svc-2026-11-01",
                    account_fingerprint_hash=account_fingerprint("key-A"),
                    channel="api", screenshot_kind="none_api_channel",
                    response_body_sha256=BODY_SHA,
                    response_request_id="req-1")
        base.update(kw)
        return Evidence(**base)

    def test_api_row_without_screenshot_is_admissible(self):
        e = self._api_row()
        e.validate()
        self.assertIsNone(e.screenshot_sha256)

    def test_api_row_cannot_fabricate_screenshot(self):
        with self.assertRaises(EvidenceError):
            self._api_row(screenshot_sha256="deadbeef").validate()

    def test_api_row_without_body_hash_is_rejected(self):
        # round-2 minor 3: API channel has no screenshot, so the response body
        # hash is the artefact that replaces it. Missing hash = inadmissible.
        with self.assertRaises(EvidenceError):
            self._api_row(response_body_sha256=None).validate()

    def test_api_row_without_request_id_is_rejected(self):
        with self.assertRaises(EvidenceError):
            self._api_row(response_request_id=None).validate()

    def test_body_hash_is_deterministic_and_distinguishes_bodies(self):
        self.assertEqual(body_sha256("{}"), body_sha256(b"{}"))
        self.assertNotEqual(body_sha256("{\"a\":1}"), body_sha256("{\"a\":2}"))
        self.assertEqual(len(body_sha256("{}")), 64)

    def test_unknown_model_version_is_rejected(self):
        with self.assertRaises(EvidenceError):
            self._api_row(model_version="unknown").validate()

    def test_client_declared_model_version_is_rejected(self):
        with self.assertRaises(EvidenceError):
            self._api_row(model_version_source="client").validate()

    def test_browser_row_requires_screenshot(self):
        with self.assertRaises(EvidenceError):
            Evidence(raw_answer="x", collected_at="2026-11-20T09:30:00+08:00",
                     model_version="v1", account_fingerprint_hash="0" * 16,
                     channel="browser").validate()

    def test_missing_timestamp_offset_rejected(self):
        with self.assertRaises(EvidenceError):
            self._api_row(collected_at="2026-11-20T09:30:00").validate()

    def test_missing_account_ref_rejected(self):
        with self.assertRaises(EvidenceError):
            account_fingerprint("")

    def test_fingerprint_is_stable_and_not_time_dependent(self):
        self.assertEqual(account_fingerprint("key-A"), account_fingerprint("key-A"))
        self.assertNotEqual(account_fingerprint("key-A"), account_fingerprint("key-B"))


class TestTimeoutBudget(unittest.TestCase):
    def test_attempt_deadline_shrinks_as_budget_is_consumed(self):
        b = Budget(total_s=60.0, read_s=40.0, max_attempts=2)
        self.assertEqual(b.attempt_deadline(), 40.0)

    def test_two_slow_attempts_cannot_exceed_60s(self):
        b = Budget(total_s=60.0, read_s=40.0, max_attempts=2)
        spent, attempts, ok = simulate(b, [999.0, 999.0])
        self.assertLessEqual(spent, 60.0)
        self.assertEqual(attempts, 2)
        self.assertFalse(ok)

    def test_retry_after_timeout_still_within_budget(self):
        b = Budget(total_s=60.0, read_s=40.0, max_attempts=2)
        spent, attempts, ok = simulate(b, [999.0, 10.0])
        self.assertLessEqual(spent, 60.0)
        self.assertTrue(ok)
        self.assertEqual(attempts, 2)

    def test_fast_first_attempt_short_circuits(self):
        b = Budget(total_s=60.0, read_s=40.0, max_attempts=2)
        spent, attempts, ok = simulate(b, [8.0])
        self.assertEqual((spent, attempts, ok), (8.0, 1, True))


if __name__ == "__main__":
    unittest.main()
