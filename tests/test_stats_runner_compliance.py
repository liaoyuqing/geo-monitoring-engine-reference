import unittest

from geo.compliance import Claim, ComplianceError, check_claims
from geo.runner import PlatformPolicy, Task, degraded_plan, platform_budget_minutes, run_batch
from geo.stats import cohen_kappa, mention_rate, repeated_measurement_cv, sampling_se_pct, within_band


class TestStats(unittest.TestCase):
    def test_sampling_se_is_not_repeatability(self):
        # 2.9pp is population uncertainty at p=.5, n=300 - documented, not a CV.
        self.assertAlmostEqual(sampling_se_pct(0.5, 300), 2.89, places=1)

    def test_cv_of_identical_repeats_is_zero(self):
        self.assertEqual(repeated_measurement_cv([0.4, 0.4, 0.4]), 0.0)

    def test_within_band_uses_range_over_mean(self):
        self.assertTrue(within_band([0.40, 0.41, 0.39], 0.05))
        self.assertFalse(within_band([0.10, 0.40, 0.70], 0.05))

    def test_mention_rate_binary(self):
        self.assertEqual(mention_rate("蓝湾白酒很好", ["蓝湾"]), 1.0)
        self.assertEqual(mention_rate("无关内容", ["蓝湾"]), 0.0)

    def test_cohen_kappa_bounds(self):
        self.assertAlmostEqual(cohen_kappa(["a", "b", "a"], ["a", "b", "a"]), 1.0)
        self.assertLess(cohen_kappa(["a", "a", "b", "b"], ["b", "b", "a", "a"]), 0.0)


class TestRunner(unittest.TestCase):
    def test_browser_only_platform_breaches_30min_at_low_rate(self):
        pol = PlatformPolicy(platform="yuanbao", channel="browser", max_per_minute=3)
        self.assertAlmostEqual(platform_budget_minutes(pol, 100), 33.33, places=1)
        plan = degraded_plan({"yuanbao": pol}, 100, ceiling_minutes=30.0)
        self.assertIn("yuanbao", plan["_breach"])

    def test_account_pool_fixes_browser_breach(self):
        pol = PlatformPolicy(platform="yuanbao", channel="browser", max_per_minute=3)
        plan = degraded_plan({"yuanbao": pol}, 100, ceiling_minutes=30.0, account_pool=4)
        self.assertAlmostEqual(plan["yuanbao"], 8.33, places=1)
        self.assertEqual(plan["_breach"], [])

    def test_resume_skips_completed_tasks(self):
        tasks = [Task(f"t{i}", "deepseek", f"p{i}", "q") for i in range(4)]
        pol = {"deepseek": PlatformPolicy("deepseek", "api", 60)}
        res = run_batch(tasks, pol, lambda t, b: (True, "ok"), resume_from=["t0", "t1"])
        self.assertEqual(res.done, ["t2", "t3"])
        self.assertFalse(res.partial)

    def test_one_failing_platform_does_not_block_others(self):
        tasks = [Task("a", "deepseek", "p1", "q"), Task("b", "yuanbao", "p1", "q")]
        pol = {"deepseek": PlatformPolicy("deepseek", "api", 60),
               "yuanbao": PlatformPolicy("yuanbao", "browser", 3)}

        def transport(t, b):
            return (t.platform == "deepseek", "fail" if t.platform != "deepseek" else "ok")

        res = run_batch(tasks, pol, transport)
        self.assertEqual(res.done, ["a"])
        self.assertTrue(res.partial)
        self.assertIn("b", res.failed)


class TestCompliance(unittest.TestCase):
    def test_sourced_claim_passes(self):
        check_claims([Claim("参数为 42分贝", ["src-1"])], ["src-1"])

    def test_claim_without_source_is_rejected(self):
        with self.assertRaises(ComplianceError):
            check_claims([Claim("某个无来源的声明", [])], ["src-1"])

    def test_claim_with_unknown_source_is_rejected(self):
        with self.assertRaises(ComplianceError):
            check_claims([Claim("引用不存在的证据", ["src-404"])], ["src-1"])

    def test_ad_law_banned_term_is_rejected(self):
        with self.assertRaises(ComplianceError):
            check_claims([Claim("这是最好的选择", ["src-1"])], ["src-1"])


if __name__ == "__main__":
    unittest.main()