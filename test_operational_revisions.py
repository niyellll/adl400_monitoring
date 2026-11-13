"""Regression tests for live status, tariffs and inactive-meter billing."""
import os
import tempfile
import unittest
from datetime import datetime

import db
import billing
from live_metrics import connection_state, daily_energy_cost


class OperationalRevisionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self.temp.name, "test.db")
        db.init()
        db.save_settings({"tarif": 2200, "wbp_multiplier": 1.5,
                          "wbp_start": "17:00", "wbp_end": "22:00", "interval": 60})
        db.replace_meters([
            {"slave": 39, "tenant": "UG", "lokasi": "UG", "aktif": True,
             "meter_model": "ADL400", "tariff_mode": "double", "tarif_override": None},
            {"slave": 31, "tenant": "Uji", "lokasi": "Lab", "aktif": False,
             "meter_model": "ADL400-D", "tariff_mode": "single", "tarif_override": None},
        ])

    def tearDown(self):
        db.DB_PATH = self.old_path
        self.temp.cleanup()

    def add_reading(self, slave, ts, kwh):
        data = {"kwh": kwh, "kw": 1.0, "v_a": 230, "v_b": 229, "v_c": 230,
                "i_a": 1, "i_b": 1, "i_c": 1, "pf": 0.9}
        db.insert_reading(slave, data, ts)

    def test_failed_polls_create_gangguan_then_offline_and_recovery(self):
        last = {"ts": "2026-11-13 17:00:00"}
        self.assertEqual(connection_state(last, None, 60, datetime(2026, 11, 13, 17, 1))[0], "online")
        db.record_poll_result(39, False, "slave no response", ts="2026-11-13 17:00:10")
        poll = db.get_poll_status(39)
        self.assertEqual(poll["consecutive_failures"], 1)
        self.assertEqual(connection_state(last, poll, 60, datetime(2026, 11, 13, 17, 1))[0], "gangguan")
        db.record_poll_result(39, False, "port unavailable", ts="2026-11-13 17:01:10")
        poll = db.get_poll_status(39)
        self.assertEqual(poll["consecutive_failures"], 2)
        self.assertEqual(connection_state(last, poll, 60, datetime(2026, 11, 13, 17, 2))[0], "offline")
        db.record_poll_result(39, True, ts="2026-11-13 17:02:10")
        poll = db.get_poll_status(39)
        self.assertEqual(poll["consecutive_failures"], 0)
        self.assertEqual(poll["last_success"], "2026-11-13 17:02:10")
        self.assertEqual(connection_state(last, poll, 60, datetime(2026, 11, 13, 17, 2))[0], "online")
        self.assertEqual(connection_state(last, poll, 60, datetime(2026, 11, 13, 17, 5))[0], "offline")

    def test_billing_active_only_default_and_history_toggle(self):
        self.add_reading(39, "2026-11-13 18:01:00", 100.00)
        self.add_reading(39, "2026-11-13 18:02:00", 100.01)
        self.add_reading(31, "2026-11-13 18:01:00", 5.00)
        self.add_reading(31, "2026-11-13 18:02:00", 5.01)
        active = billing.compute("2026-11-13 00:00:00", "2026-11-13 23:59:59")
        self.assertEqual(active["Slave"].tolist(), [39])
        all_meters = billing.compute("2026-11-13 00:00:00", "2026-11-13 23:59:59", include_inactive=True)
        self.assertEqual(set(all_meters["Slave"].tolist()), {31, 39})
        with db.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 4)

    def test_daily_cost_uses_snapshot_wbp_rate_not_flat_tariff(self):
        self.add_reading(39, "2026-11-13 17:01:00", 50.00)
        self.add_reading(39, "2026-11-13 17:02:00", 50.01)
        with db.connect() as con:
            info = daily_energy_cost(con, 39, "serial", "readings", "2026-11-13 00:00:00")
        self.assertTrue(info["complete"])
        self.assertAlmostEqual(info["usage_kwh"], .01)
        self.assertAlmostEqual(info["energy_cost"], 33.0)

    def test_daily_cost_marks_straddling_boundary_incomplete(self):
        self.add_reading(39, "2026-11-13 16:59:30", 70.00)
        self.add_reading(39, "2026-11-13 17:00:30", 70.01)
        with db.connect() as con:
            info = daily_energy_cost(con, 39, "serial", "readings", "2026-11-13 00:00:00")
        self.assertFalse(info["complete"])
        self.assertAlmostEqual(info["missing_kwh"], .01)
        self.assertAlmostEqual(info["energy_cost"], 0)


if __name__ == "__main__":
    unittest.main()
