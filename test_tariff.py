"""Unit tests without meter hardware or Streamlit runtime."""
import unittest
import tariff


class TariffTests(unittest.TestCase):
    def setUp(self):
        self.s = {
            "tarif": "1444.70", "wbp_start": "17:00",
            "wbp_end": "22:00", "tou_enabled": "True",
            "wbp_multiplier": "1.5",
        }

    def test_wbp_boundaries(self):
        self.assertEqual(tariff.classify("2026-11-07 16:59:59", self.s), "LWBP")
        self.assertEqual(tariff.classify("2026-11-07 17:00:00", self.s), "WBP")
        self.assertEqual(tariff.classify("2026-11-07 21:59:59", self.s), "WBP")
        self.assertEqual(tariff.classify("2026-11-07 22:00:00", self.s), "LWBP")

    def test_wbp_multiplier_requires_enablement(self):
        self.assertAlmostEqual(
            tariff.rate_for("2026-11-07 17:30:00", self.s)[1], 2167.05)
        self.s["tou_enabled"] = "False"
        self.assertAlmostEqual(
            tariff.rate_for("2026-11-07 17:30:00", self.s)[1], 1444.70)

    def test_override(self):
        self.assertEqual(
            tariff.rate_for("2026-11-07 02:15:00", self.s, 2000),
            ("LWBP", 2000.0))

    def test_current_threshold_is_not_billing(self):
        self.assertIn("ambang pantau", tariff.describe_amps(105, 100).lower())


if __name__ == "__main__":
    unittest.main()
