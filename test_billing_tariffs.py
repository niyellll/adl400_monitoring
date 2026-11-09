"""Billing tests using disposable SQLite storage; no physical meter required."""
import os
import tempfile
import unittest
from unittest.mock import patch

import billing
import db


class BillingTariffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.tmp.name, "test.db")
        db.init()
        db.replace_meters([{"slave": 31, "tenant": "Tenant Tes", "lokasi": "GF",
                            "tarif_override": None, "aktif": True}])
        db.save_settings({"tou_enabled": "True", "tarif": "1000", "wbp_start": "17:00",
                          "wbp_end": "22:00", "wbp_multiplier": "1.5", "interval": "60",
                          "ppj_persen": "0", "biaya_admin": "0"})

    def tearDown(self):
        db.DB_PATH = self.old_path
        self.tmp.cleanup()

    @staticmethod
    def insert(ts, kwh):
        db.insert_reading(31, {"kwh": kwh, "v_a": 230, "v_b": 230, "v_c": 230,
                               "i_a": 1, "i_b": 1, "i_c": 1, "kw": 0.1, "pf": 0.9}, ts)

    def test_two_tariffs_when_all_intervals_valid(self):
        self.insert("2026-11-09 16:57:00", 10)
        self.insert("2026-11-09 16:58:00", 11)
        self.insert("2026-11-09 16:59:00", 12)
        self.insert("2026-11-09 17:00:00", 13)  # transition deliberately not allocated
        self.insert("2026-11-09 17:01:00", 14)
        result = billing.compute("2026-11-09 16:57:00", "2026-11-09 17:01:00").iloc[0]
        self.assertEqual(result["kWh LWBP"], 2)
        self.assertEqual(result["kWh WBP"], 1)
        self.assertEqual(result["kWh Belum Teralokasi"], 1)
        self.assertTrue(result["Total (Rp)"] is None)

    def test_single_period_complete(self):
        self.insert("2026-11-09 17:01:00", 10)
        self.insert("2026-11-09 17:02:00", 12)
        result = billing.compute("2026-11-09 17:01:00", "2026-11-09 17:02:00").iloc[0]
        self.assertEqual(result["kWh WBP"], 2)
        self.assertEqual(result["Biaya WBP"], 3000)
        self.assertEqual(result["Total (Rp)"], 3000)

    def test_first_snapshot_not_charged_across_start_boundary(self):
        self.insert("2026-11-09 16:58:00", 10)
        self.insert("2026-11-09 16:59:00", 11)
        self.insert("2026-11-09 17:00:00", 12)
        self.insert("2026-11-09 17:01:00", 13)
        self.insert("2026-11-09 17:02:00", 14)
        result = billing.compute("2026-11-09 17:01:00", "2026-11-09 17:02:00").iloc[0]
        self.assertEqual(result["kWh WBP"], 1)
        self.assertEqual(result["Total (Rp)"], 1500)

    def test_history_without_tariff_snapshot_not_billed_as_wbp(self):
        with db.connect() as con:
            con.execute(
                "INSERT INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("2026-11-09 17:01:00", 31, 10, 230, 230, 230, 1, 1, 1, .1, .9))
            con.execute(
                "INSERT INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("2026-11-09 17:02:00", 31, 11, 230, 230, 230, 1, 1, 1, .1, .9))
        result = billing.compute("2026-11-09 17:01:00", "2026-11-09 17:02:00").iloc[0]
        self.assertEqual(result["kWh Belum Teralokasi"], 1)
        self.assertIsNone(result["Total (Rp)"])

    def test_single_tariff_legacy_mode(self):
        db.save_settings({"tou_enabled": "False"})
        self.insert("2026-11-09 17:01:00", 10)
        self.insert("2026-11-09 17:02:00", 12)
        result = billing.compute("2026-11-09 17:01:00", "2026-11-09 17:02:00").iloc[0]
        self.assertEqual(result["Total (Rp)"], 2000)


if __name__ == "__main__":
    unittest.main()
