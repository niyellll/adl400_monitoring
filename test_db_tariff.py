"""Integration tests for local SQLite meter readings, using a temporary DB only."""
import os
import tempfile
import unittest
from unittest.mock import patch
import db


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.dir.name, "integration.db")
        db.init()
        db.replace_meters([{"slave": 31, "tenant": "Meter uji", "lokasi": "Test",
                            "tarif_override": None, "aktif": True}])

    def tearDown(self):
        db.DB_PATH = self.old_path
        self.dir.cleanup()

    @staticmethod
    def reading(kwh, amps=0.0, voltage=230.0):
        return {"kwh": kwh, "v_a": voltage, "v_b": voltage, "v_c": voltage,
                "i_a": amps, "i_b": amps, "i_c": amps, "kw": 0, "pf": 0.95}

    def test_new_minute_records_have_tariff_snapshot_and_preserve_voltage(self):
        db.insert_reading(31, self.reading(10, amps=4), "2026-11-07 16:58:00")
        db.insert_reading(31, self.reading(10.03, amps=0), "2026-11-07 16:59:00")
        rows = db.get_minute_details([31], "2026-11-07 16:58:00", "2026-11-07 17:00:00")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["period"], "LWBP")
        self.assertEqual(rows[1]["period"], "LWBP")
        self.assertAlmostEqual(rows[1]["delta_kwh"], 0.03)
        self.assertEqual(rows[1]["v_a"], 230)
        self.assertEqual(rows[1]["i_a"], 0)

    def test_boundary_does_not_falsely_allocate_to_peak_period(self):
        db.insert_reading(31, self.reading(10), "2026-11-07 16:59:00")
        db.insert_reading(31, self.reading(10.05), "2026-11-07 17:00:00")
        rows = db.get_minute_details([31], "2026-11-07 16:59:00", "2026-11-07 17:00:00")
        self.assertEqual(rows[-1]["period"], "LWBP")
        self.assertAlmostEqual(rows[-1]["delta_kwh"], 0.05)
        self.assertAlmostEqual(rows[-1]["estimated_energy_cost"], 0.05 * 1444.7)
        self.assertIn("batas", rows[-1]["note"])

    def test_gap_does_not_become_fake_minute_readings(self):
        db.insert_reading(31, self.reading(20), "2026-11-07 02:10:00")
        db.insert_reading(31, self.reading(20.2), "2026-11-07 02:15:00")
        rows = db.get_minute_details([31], "2026-11-07 02:00:00", "2026-11-07 03:00:00")
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[-1]["estimated_energy_cost"])
        self.assertIn("Jeda", rows[-1]["note"])

    def test_no_esp32_mixed_with_serial(self):
        db.insert_reading(31, self.reading(5), "2026-11-07 17:15:00")
        db.insert_esp32_real_reading(31, self.reading(500),
                                      "2026-11-07 17:15:00")
        rows = db.get_minute_details([31], "2026-11-07 17:00:00", "2026-11-07 18:00:00")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kwh"], 5)
        db.save_settings({"conn_type": "esp32"})
        esp = db.get_minute_details([31], "2026-11-07 17:00:00", "2026-11-07 18:00:00")
        self.assertEqual(len(esp), 1)
        self.assertEqual(esp[0]["kwh"], 500)


if __name__ == "__main__":
    unittest.main()
