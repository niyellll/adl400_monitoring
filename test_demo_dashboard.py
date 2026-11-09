"""Checks Demo sample separation and minute resolution without touching Live SQLite."""
import unittest
import pandas as pd
import demo_dashboard


class DemoTests(unittest.TestCase):
    def test_demo_is_minute_resolution(self):
        df = demo_dashboard.sample_data("2026-11-09T11:22:00")
        self.assertEqual(df["slave"].nunique(), len(demo_dashboard.DEMO_METERS))
        self.assertEqual(len(df), 7 * 24 * 60 * len(demo_dashboard.DEMO_METERS))
        first = df[df["slave"] == 1]["ts"].sort_values()
        self.assertTrue(first.diff().dropna().eq(pd.Timedelta(minutes=1)).all())

    def test_all_demo_sample_values_are_pseudodata(self):
        df = demo_dashboard.sample_data("2026-11-09T11:22:00")
        self.assertTrue((df["kwh"] > 0).all())
        self.assertTrue((df[["v_a", "v_b", "v_c"]] > 0).all().all())
        self.assertTrue((df[["i_a", "i_b", "i_c"]] >= 0).all().all())
        self.assertTrue(df.groupby("slave")["kwh"].apply(lambda x: x.is_monotonic_increasing).all())


if __name__ == "__main__":
    unittest.main()
