import unittest

from geo.collectors import ApiChannel, BrowserChannel, collectors


class TestApiChannel(unittest.TestCase):
    def test_build_request_carries_temperature_zero_and_seed(self):
        ch = ApiChannel("deepseek", "https://api.example.com/v1", "deepseek-v4", "key-A")
        req = ch.build_request("q")
        self.assertEqual(req["payload"]["temperature"], 0.0)
        self.assertEqual(req["payload"]["seed"], 42)
        self.assertTrue(req["url"].endswith("/chat/completions"))

    def test_normalise_uses_server_reported_model(self):
        ch = ApiChannel("deepseek", "https://api.example.com/v1", "declared-model", "key-A")
        ev = ch.normalise({"model": "server-model-v2", "id": "req-1",
                           "choices": [{"message": {"content": "答案"}}]},
                          "q", "2026-11-20T09:30:00+08:00")
        self.assertEqual(ev.model_version, "server-model-v2")
        self.assertEqual(ev.screenshot_kind, "none_api_channel")
        self.assertIsNone(ev.screenshot_sha256)
        ev.validate()

    def test_empty_completion_is_rejected_by_the_envelope(self):
        # fail-closed: an empty answer is not admissible evidence, because a
        # downstream metric would silently read it as "brand not mentioned".
        ch = ApiChannel("deepseek", "https://api.example.com/v1", "m", "key-A")
        ev = ch.normalise({"choices": []}, "q", "2026-11-20T09:30:00+08:00")
        self.assertEqual(ev.raw_answer, "")
        with self.assertRaises(Exception):
            ev.validate()


class TestBrowserChannel(unittest.TestCase):
    def test_context_is_incognito_without_storage_state(self):
        ch = BrowserChannel("yuanbao", "https://yuanbao.example.com", "acct-3")
        spec = ch.context_spec()
        self.assertTrue(spec["incognito"])
        self.assertIsNone(spec["storage_state"])
        self.assertEqual(spec["locale"], "zh-CN")

    def test_browser_row_without_screenshot_fails(self):
        ch = BrowserChannel("yuanbao", "https://yuanbao.example.com", "acct-3")
        with self.assertRaises(Exception):
            ch.normalise({"answer_text": "x"}, "q", "2026-11-20T09:30:00+08:00").validate()

    def test_browser_row_with_screenshot_validates(self):
        ch = BrowserChannel("yuanbao", "https://yuanbao.example.com", "acct-3")
        ev = ch.normalise({"answer_text": "答案", "screenshot_sha256": "a" * 64,
                           "screenshot_path": "shots/1.png", "model_version": "web-2026-11"},
                          "q", "2026-11-20T09:30:00+08:00")
        ev.validate()
        self.assertEqual(ev.channel, "browser")


class TestChannelPlan(unittest.TestCase):
    def test_six_platforms_present(self):
        self.assertEqual(len(collectors()), 6)

    def test_yuanbao_is_browser_only(self):
        self.assertEqual(collectors()["yuanbao"]["primary"], "browser")


if __name__ == "__main__":
    unittest.main()