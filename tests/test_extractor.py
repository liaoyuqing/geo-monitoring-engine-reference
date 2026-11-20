import unittest

from geo.extractor import extract, extract_dicts

ALIASES = {"蓝湾白酒": ["蓝湾白酒", "蓝湾"], "竞品甲": ["竞品甲"]}


class TestSentiment(unittest.TestCase):
    def test_full_negation_is_negative_not_positive(self):
        # "不推荐" contains "推荐"; a naive substring scan reads it as positive.
        rows = extract("蓝湾白酒不推荐，价格偏贵。", ALIASES)
        self.assertEqual(rows[0].sentiment, "消极")

    def test_prefix_negation_flips_positive(self):
        rows = extract("蓝湾白酒不值得推荐。", ALIASES)
        self.assertEqual(rows[0].sentiment, "消极")
        self.assertTrue(rows[0].negated)

    def test_plain_positive(self):
        rows = extract("蓝湾白酒值得推荐，口感出色。", ALIASES)
        self.assertEqual(rows[0].sentiment, "积极")
        self.assertFalse(rows[0].negated)

    def test_neutral_when_no_polarity_word(self):
        rows = extract("蓝湾白酒是一个品牌。", ALIASES)
        self.assertEqual(rows[0].sentiment, "中性")


class TestUrlAttribution(unittest.TestCase):
    def test_url_belongs_to_nearest_brand(self):
        raw = ("蓝湾白酒值得推荐，详见 https://example.com/lanwan 。"
               "竞品甲一般，详见 https://example.com/jingpin 。")
        rows = {m.brand: m for m in extract(raw, ALIASES)}
        self.assertEqual(rows["蓝湾白酒"].source_url, "https://example.com/lanwan")
        self.assertEqual(rows["蓝湾白酒"].source_url_attribution, "brand_window")
        self.assertEqual(rows["竞品甲"].source_url, "https://example.com/jingpin")

    def test_answer_level_url_is_not_silently_attributed(self):
        # one URL, far away from the brand -> must be flagged answer_level,
        # so the metric layer can exclude it instead of inflating citation share.
        raw = ("蓝湾白酒值得推荐。" + "充字数" * 60 +
               " 参考 https://example.com/far ")
        rows = extract(raw, ALIASES)
        self.assertEqual(rows[0].source_url_attribution, "answer_level")

    def test_no_url_yields_none(self):
        rows = extract("蓝湾白酒值得推荐。", ALIASES)
        self.assertIsNone(rows[0].source_url)


class TestDeterminism(unittest.TestCase):
    SAMPLE = "蓝湾白酒值得推荐，详见 https://example.com/p1 ；竞品甲一般。"

    def test_same_input_same_output(self):
        self.assertEqual(extract_dicts(self.SAMPLE, ALIASES), extract_dicts(self.SAMPLE, ALIASES))

    def test_multi_brand_ordering_by_position(self):
        rows = extract(self.SAMPLE, ALIASES)
        self.assertEqual([r.brand for r in rows], ["蓝湾白酒", "竞品甲"])
        self.assertLess(rows[0].position, rows[1].position)

    def test_alias_matches_short_form(self):
        rows = extract("蓝湾口感出色。", ALIASES)
        self.assertEqual(rows[0].brand, "蓝湾白酒")

    def test_absent_brand_produces_no_row(self):
        rows = extract("只有一个无关品牌。", ALIASES)
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()