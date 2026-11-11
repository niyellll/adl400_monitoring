"""Hardware-free checks for per-tenant Acrel model decoding and DB migration."""
import os
import tempfile
import unittest

import db
import modbus


class FakeClient:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def read_holding(self, slave, address, count):
        self.calls.append((slave, address, count))
        if (address, count) not in self.values:
            raise AssertionError(f"unexpected register {address:#x}, {count}")
        return self.values[(address, count)]


def encoded_values(fields, values):
    registers = {}
    for name, (addr, count, scale, signed) in fields.items():
        val = int(round(values[name] / scale))
        if signed and val < 0:
            val += 1 << (16 * count)
        registers[(addr, count)] = (
            [(val >> 16) & 0xFFFF, val & 0xFFFF] if count == 2 else [val]
        )
    return registers


class MeterModelTests(unittest.TestCase):
    def test_adl200_reads_only_one_phase_from_verified_map(self):
        readings = {"kwh": 123.45, "v_a": 230, "i_a": 5.25,
                    "kw": 1.050, "pf": 0.910}
        client = FakeClient(encoded_values(modbus.ADL200_FIELDS, readings))
        out = modbus.read_meter(client, 31, "ADL200")
        for name, value in readings.items():
            self.assertAlmostEqual(out[name], value)
        for phase in ("v_b", "v_c", "i_b", "i_c"):
            self.assertIsNone(out[phase])
        self.assertEqual(len(client.calls), 5)

    def test_adl400_and_adl400d_are_three_phase(self):
        data = {"kwh": 3.84, "v_a": 231.3, "v_b": 229.6, "v_c": 230.9,
                "i_a": 4.95, "i_b": 4.10, "i_c": 4.19, "kw": 2.639, "pf": .868}
        for model in ("ADL400", "ADL400-D"):
            client = FakeClient(encoded_values(modbus.FIELDS, data))
            result = modbus.read_meter(client, 31, model)
            for name, value in data.items():
                self.assertAlmostEqual(result[name], value)
            self.assertEqual(len(client.calls), len(modbus.FIELDS))

    def test_legacy_read_meter_defaults_to_adl400d(self):
        data = {"kwh": 3.84, "v_a": 231.3, "v_b": 229.6, "v_c": 230.9,
                "i_a": 4.95, "i_b": 4.10, "i_c": 4.19, "kw": 2.639, "pf": .868}
        result = modbus.read_meter(FakeClient(encoded_values(modbus.FIELDS, data)), 31)
        self.assertAlmostEqual(result["kw"], 2.639)

    def test_unknown_model_does_not_guess(self):
        with self.assertRaises(ValueError):
            modbus.read_meter(FakeClient({}), 1, "OTHER")

    def test_old_db_migrates_and_keeps_readings(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = db.DB_PATH
            try:
                db.DB_PATH = os.path.join(tmp, "legacy.db")
                with db.connect() as con:
                    con.executescript("""
                        CREATE TABLE meters (
                            slave INTEGER PRIMARY KEY, tenant TEXT NOT NULL,
                            lokasi TEXT DEFAULT '', tarif_override REAL,
                            aktif INTEGER DEFAULT 1, tariff_mode TEXT
                        );
                        INSERT INTO meters (slave, tenant, lokasi, aktif)
                        VALUES (31, 'Meter lama', 'GF', 1);
                        CREATE TABLE readings (
                            ts TEXT NOT NULL, slave INTEGER NOT NULL,
                            kwh REAL, v_a REAL, v_b REAL, v_c REAL,
                            i_a REAL, i_b REAL, i_c REAL, kw REAL, pf REAL
                        );
                        INSERT INTO readings (ts,slave,kwh)
                        VALUES ('2026-11-09 15:00:00',31,3.84);
                    """)
                db.init()
                meter = db.get_meters()[0]
                self.assertEqual(meter["meter_model"], "ADL400-D")
                with db.connect() as con:
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 1)
                db.replace_meters([
                    {"slave": 31, "tenant": "Meter lama", "lokasi": "GF",
                     "meter_model": "ADL200", "tariff_mode": "single",
                     "tarif_override": None, "aktif": True}
                ])
                self.assertEqual(db.get_meters()[0]["meter_model"], "ADL200")
                with db.connect() as con:
                    self.assertEqual(con.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 1)
            finally:
                db.DB_PATH = previous


if __name__ == "__main__":
    unittest.main()
