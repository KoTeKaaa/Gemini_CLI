import unittest

from gemini_cli.protocol.quotas import Quota, unavailable


class QuotaTests(unittest.TestCase):
    def test_unknown_is_not_zero(self):
        for limit, used in ((None, 1), (10, None), (None, None)):
            self.assertIsNone(Quota("gemini", "project", limit=limit, used=used).remaining)
        self.assertEqual(Quota("tavily", "key", limit=10, used=12).remaining, 0)
        self.assertIsNone(unavailable("gemini", "project", "auth_required")["remaining"])

    def test_invalid_numbers_and_unavailable(self):
        for value in (True, -1, "100", float("nan"), float("inf")):
            self.assertIsNone(Quota("gemini", "project", limit=value).limit)
        self.assertIsNone(Quota("gemini", "project", limit=10, used=1, unavailable=True).remaining)

    def test_windows_models_and_tiers_stay_separate(self):
        rows = [Quota("gemini", "project", model="a", tier=tier,
                      window=window, limit=limit, used=1).wire()
                for tier, window, limit in (("free", "minute", 2),
                                            ("free", "day", 100), ("paid", "minute", 10))]
        self.assertEqual([r["remaining"] for r in rows], [1, 99, 9])
        self.assertEqual([r["tier"] for r in rows], ["free", "free", "paid"])
        row = Quota("gemini", "project", sampled_at=10, fetched_at=160,
                    stale=True, approximate=True).wire()
        self.assertTrue(row["stale"])
        self.assertEqual(row["sampled_at"], 10)
