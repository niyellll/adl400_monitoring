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
        self.assertEqual(result["kWh LWBP"], 3)
        self.assertEqual(result["kWh WBP"], 1)
        self.assertEqual(result["kWh Belum Teralokasi"], 0)
        self.assertEqual(result["Total (Rp)"], 4500)

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

    def test_per_tenant_modes_override_global(self):
        db.replace_meters([
            {"slave": 31, "tenant": "Tunggal", "lokasi": "GF",
             "tariff_mode": "single", "tarif_override": None, "aktif": True},
            {"slave": 32, "tenant": "Double", "lokasi": "UG",
             "tariff_mode": "double", "tarif_override": None, "aktif": True},
        ])
        for slave in (31, 32):
            for ts, kwh in [("2026-11-09 17:01:00", 10),
                            ("2026-11-09 17:02:00", 12)]:
                db.insert_reading(slave, {"kwh": kwh, "v_a": 230, "v_b": 230, "v_c": 230,
                                          "i_a": 1, "i_b": 1, "i_c": 1,
                                          "kw": 0.1, "pf": 0.9}, ts)
        results = billing.compute("2026-11-09 17:01:00", "2026-11-09 17:02:00")
        a, b = [results.loc[results["Slave"] == slave].iloc[0] for slave in (31, 32)]
        self.assertEqual(a["Jenis Tarif"], "Tarif Tunggal")
        self.assertEqual(a["Total (Rp)"], 2000)
        self.assertEqual(b["Jenis Tarif"], "Double Tarif")
        self.assertEqual(b["kWh WBP"], 2)
        self.assertEqual(b["Total (Rp)"], 3000)
        with db.connect() as con:
            periods = {r["slave"]: (r["period"], r["mode"]) for r in con.execute(
                "SELECT slave, period, mode FROM reading_tariffs WHERE ts='2026-11-09 17:02:00'")}
        self.assertEqual(periods[31], ("WBP", "single"))
        self.assertEqual(periods[32], ("WBP", "double"))

    def test_mode_change_in_period_requires_manual_review(self):
        self.insert("2026-11-09 17:01:00", 10)
        self.insert("2026-11-09 17:02:00", 11)
        db.replace_meters([{"slave": 31, "tenant": "Tenant Tes", "lokasi": "GF",
                            "tariff_mode": "single", "tarif_override": None, "aktif": True}])
        self.insert("2026-11-09 17:03:00", 12)
        result = billing.compute("2026-11-09 17:01:00", "2026-11-09 17:03:00").iloc[0]
        self.assertIsNone(result["Total (Rp)"])
        self.assertIn("Perubahan skema tarif", result["Catatan"])

    def test_double_tariff_overrides_disabled_global(self):
        db.save_settings({"tou_enabled": "False"})
        db.replace_meters([{"slave": 31, "tenant": "Tenant Tes", "lokasi": "GF",
                            "tariff_mode": "double", "tarif_override": None, "aktif": True}])
        self.insert("2026-11-09 17:01:00", 10)
        self.insert("2026-11-09 17:02:00", 11)
        result = billing.compute("2026-11-09 17:01:00", "2026-11-09 17:02:00").iloc[0]
        self.assertEqual(result["Total (Rp)"], 1500)

    def test_migration_keeps_old_readings_and_meter_rows(self):
        db.replace_meters([{"slave": 31, "tenant": "Tenant Tes", "lokasi": "GF",
                            "tariff_mode": "double", "tarif_override": None, "aktif": True}])
        self.insert("2026-11-09 17:01:00", 10)
        db.init()
        self.assertEqual(db.get_meters()[0]["tariff_mode"], "double")
        with db.connect() as con:
            count = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        self.assertEqual(count, 1)

    def test_excel_has_tariff_split_and_mode_columns(self):
        from io import BytesIO
        from openpyxl import load_workbook
        from export_utils import formatted_xlsx
        self.insert("2026-11-09 17:01:00", 10)
        self.insert("2026-11-09 17:02:00", 11)
        frame = billing.compute("2026-11-09 17:01:00", "2026-11-09 17:02:00")
        book = load_workbook(BytesIO(formatted_xlsx(frame, "Tagihan")))
        headers = [cell.value for cell in book["Tagihan"][1]]
        for name in ("Jenis Tarif", "kWh LWBP", "kWh WBP", "Biaya LWBP",
                     "Biaya WBP", "Total (Rp)", "Status Alokasi", "Catatan"):
            self.assertIn(name, headers)

    def test_esp32_real_tenant_mode_snapshots(self):
        db.save_settings({"conn_type": "esp32", "tou_enabled": "False"})
        db.replace_meters([{"slave": 31, "tenant": "Tenant Tes", "lokasi": "GF",
                            "tariff_mode": "double", "tarif_override": None, "aktif": True}])
        db.insert_esp32_real_reading(31, {"kwh": 10}, "2026-11-09 17:01:00")
        db.insert_esp32_real_reading(31, {"kwh": 11}, "2026-11-09 17:02:00")
        result = billing.compute("2026-11-09 17:01:00", "2026-11-09 17:02:00").iloc[0]
        self.assertEqual(result["Total (Rp)"], 1500)

    def test_boundary_at_2200_goes_to_wbp(self):
        self.insert("2026-11-09 21:59:00", 10)
        self.insert("2026-11-09 22:00:00", 11)
        self.insert("2026-11-09 22:01:00", 12)
        row = billing.compute("2026-11-09 21:59:00", "2026-11-09 22:01:00").iloc[0]
        self.assertEqual(row["kWh WBP"], 1)
        self.assertEqual(row["kWh LWBP"], 1)
        self.assertEqual(row["kWh Belum Teralokasi"], 0)
        self.assertEqual(row["Total (Rp)"], 2500)

    def test_straddling_boundary_without_exact_reading_is_not_assumed(self):
        self.insert("2026-11-09 16:59:00", 10)
        self.insert("2026-11-09 17:01:00", 12)
        row = billing.compute("2026-11-09 16:59:00", "2026-11-09 17:01:00").iloc[0]
        self.assertEqual(row["kWh Belum Teralokasi"], 2)
        self.assertIsNone(row["Total (Rp)"])

    def test_long_gap_is_not_allocated(self):
        self.insert("2026-11-09 18:00:00", 10)
        self.insert("2026-11-09 18:10:00", 12)
        row = billing.compute("2026-11-09 18:00:00", "2026-11-09 18:10:00").iloc[0]
        self.assertEqual(row["kWh Belum Teralokasi"], 2)
        self.assertIsNone(row["Total (Rp)"])


if __name__ == "__main__":
    unittest.main()
