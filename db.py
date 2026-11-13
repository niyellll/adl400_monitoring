"""Lapisan database SQLite (dipakai bersama oleh collector.py dan app.py)."""
import os
import sqlite3
from datetime import datetime

import tariff

DB_PATH = os.environ.get("ADL400_DB", "monitoring.db")

DEFAULT_SETTINGS = {
    "conn_type": "serial",      # serial | tcp | esp32"
    "serial_port": "COM3",      # contoh Linux: /dev/ttyUSB0
    "baud": "9600",
    "parity": "N",
    "host": "192.168.1.100",
    "tcp_port": "502",
    "interval": "60",           # detik antar pembacaan
    "tarif": "1444.70",         # Rp per kWh
    "ppj_persen": "0",          # pajak penerangan jalan (%)
    "biaya_admin": "0",
    "tou_enabled": "False",
    "wbp_start": "17:00",
    "wbp_end": "22:00",
    "wbp_multiplier": "1",
    "current_alert_a": "100",         # Rp per tenant per bulan
}


def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init():
    with connect() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS meters (
            slave INTEGER PRIMARY KEY,
            tenant TEXT NOT NULL,
            lokasi TEXT DEFAULT '',
            tarif_override REAL,
            aktif INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS readings (
            ts TEXT NOT NULL,
            slave INTEGER NOT NULL,
            kwh REAL, v_a REAL, v_b REAL, v_c REAL,
            i_a REAL, i_b REAL, i_c REAL, kw REAL, pf REAL
        );
        CREATE INDEX IF NOT EXISTS idx_readings ON readings (slave, ts);
        CREATE TABLE IF NOT EXISTS esp32_real_readings (
            ts TEXT NOT NULL, slave INTEGER NOT NULL,
            kwh REAL NOT NULL, v_a REAL, v_b REAL, v_c REAL,
            i_a REAL, i_b REAL, i_c REAL, kw REAL, pf REAL
        );
        CREATE INDEX IF NOT EXISTS idx_esp32_real_readings
            ON esp32_real_readings (slave, ts);
        CREATE TABLE IF NOT EXISTS reading_tariffs (
            slave INTEGER NOT NULL, ts TEXT NOT NULL, source TEXT NOT NULL,
            period TEXT NOT NULL, rate REAL NOT NULL,
            delta_kwh REAL, estimated_energy_cost REAL,
            note TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(slave, ts, source)
        );
        CREATE INDEX IF NOT EXISTS idx_reading_tariffs_ts
            ON reading_tariffs (ts, source);
        CREATE TABLE IF NOT EXISTS meter_poll_status (
            slave INTEGER NOT NULL,
            source TEXT NOT NULL,
            last_attempt TEXT NOT NULL,
            last_success TEXT,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            PRIMARY KEY (slave, source)
        );
        """)
        # Forward-only migration: no existing readings or tariff history is removed.
        meter_columns = {r["name"] for r in con.execute("PRAGMA table_info(meters)")}
        if "tariff_mode" not in meter_columns:
            con.execute("ALTER TABLE meters ADD COLUMN tariff_mode TEXT")
        if "meter_model" not in meter_columns:
            # Preserve existing COM10 ADL400-D setup and historical readings.
            con.execute("ALTER TABLE meters ADD COLUMN meter_model TEXT NOT NULL DEFAULT 'ADL400-D'")
        ledger_columns = {r["name"] for r in con.execute("PRAGMA table_info(reading_tariffs)")}
        if "mode" not in ledger_columns:
            con.execute("ALTER TABLE reading_tariffs ADD COLUMN mode TEXT")
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, v))


def get_settings():
    with connect() as con:
        return {r["key"]: r["value"] for r in con.execute("SELECT * FROM settings")}


def save_settings(d):
    with connect() as con:
        for k, v in d.items():
            con.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (k, str(v)))


def get_meters(only_active=False):
    q = "SELECT * FROM meters" + (" WHERE aktif=1" if only_active else "") + " ORDER BY slave"
    with connect() as con:
        return [dict(r) for r in con.execute(q)]


def replace_meters(rows):
    with connect() as con:
        con.execute("DELETE FROM meters")
        for r in rows:
            mode = r.get("tariff_mode")
            if mode not in (None, "single", "double"):
                raise ValueError("Jenis tarif tidak valid (single/double/ikuti global)")
            # Imported lazily to keep SQLite layer independent of serial connections.
            from modbus import METER_MODELS
            model = r.get("meter_model") or "ADL400-D"
            if model not in METER_MODELS:
                raise ValueError(f"Model meter tidak didukung: {model}")
            con.execute(
                "INSERT INTO meters (slave, tenant, lokasi, tarif_override, aktif, tariff_mode, meter_model) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (int(r["slave"]), r["tenant"], r.get("lokasi") or "",
                 r.get("tarif_override"), 1 if r.get("aktif", True) else 0, mode, model))


def active_readings_table():
    """Return a trusted table name; never interpolate user-supplied values."""
    return "esp32_real_readings" if get_settings().get("conn_type") == "esp32" else "readings"


def _snapshot_tariff(con, slave, ts, kwh, source):
    """Store per-sample tariff using the contract settings at collection time."""
    settings = get_settings()
    meter = con.execute("SELECT tarif_override, tariff_mode FROM meters WHERE slave=?", (slave,)).fetchone()
    override = meter["tarif_override"] if meter and meter["tarif_override"] is not None else None
    mode = tariff.effective_mode(meter["tariff_mode"] if meter else None, settings)
    period, rate = tariff.rate_for(ts, settings, override, mode=mode)
    table = "esp32_real_readings" if source == "esp32" else "readings"
    prev = con.execute(
        f"SELECT ts,kwh FROM {table} WHERE slave=? AND ts<? ORDER BY ts DESC LIMIT 1",
        (slave, ts)).fetchone()
    delta, cost, note = None, None, "Pembacaan awal; tidak ada selisih"
    if prev and prev["kwh"] is not None and kwh is not None:
        elapsed = (datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") -
                   datetime.strptime(prev["ts"], "%Y-%m-%d %H:%M:%S")).total_seconds()
        diff = float(kwh) - float(prev["kwh"])
        if diff < 0:
            note = "kWh menurun; periksa reset atau pergantian meter"
        elif elapsed > max(120, float(settings.get("interval", 60)) * 2.5):
            note = "Jeda panjang; alokasi periode tidak pasti"
        else:
            interval_class = tariff.interval_period(prev["ts"], ts, settings)
            if interval_class is None and mode == "double":
                note = "Interval melintasi batas WBP/LWBP tanpa bacaan tepat di batas; alokasi tidak pasti"
            else:
                # A reading exactly at a boundary represents consumption in
                # the preceding half-open interval; use its previous tariff.
                period = interval_class or period
                _, rate = tariff.rate_for(prev["ts"], settings, override, mode=mode)
                delta, cost = diff, diff * rate
                note = "Teralokasi ke interval sebelum timestamp akhir (batas jam tepat)"
    con.execute(
        """INSERT OR REPLACE INTO reading_tariffs
           (slave,ts,source,period,rate,delta_kwh,estimated_energy_cost,note,mode)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (slave, ts, source, period, rate, delta, cost, note, mode))


def insert_esp32_real_reading(slave, data, ts=None):
    ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as con:
        con.execute(
            "INSERT INTO esp32_real_readings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts, slave, data["kwh"], data.get("v_a"), data.get("v_b"), data.get("v_c"),
             data.get("i_a"), data.get("i_b"), data.get("i_c"), data.get("kw"), data.get("pf")))
        _snapshot_tariff(con, slave, ts, data["kwh"], "esp32")


def insert_reading(slave, data, ts=None):
    ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as con:
        con.execute(
            "INSERT INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts, slave, data["kwh"], data["v_a"], data["v_b"], data["v_c"],
             data["i_a"], data["i_b"], data["i_c"], data["kw"], data["pf"]))
        _snapshot_tariff(con, slave, ts, data["kwh"], "serial")


def get_minute_details(slaves, start_ts, end_ts):
    """Return stored samples; never invent missing minute readings."""
    if not slaves:
        return []
    source = "esp32" if get_settings().get("conn_type") == "esp32" else "serial"
    table = active_readings_table()
    marks = ",".join("?" * len(slaves))
    with connect() as con:
        result = con.execute(
            f"""SELECT r.*, t.period, t.rate, t.mode AS tariff_mode, t.delta_kwh,
                       t.estimated_energy_cost, t.note
                FROM {table} r
                LEFT JOIN reading_tariffs t
                  ON t.slave=r.slave AND t.ts=r.ts AND t.source=?
                WHERE r.ts>=? AND r.ts<=? AND r.slave IN ({marks})
                ORDER BY r.ts, r.slave""",
            [source, start_ts, end_ts, *slaves],
        ).fetchall()
    return [dict(r) for r in result]


def last_reading(slave):
    table = active_readings_table()
    with connect() as con:
        r = con.execute(f"SELECT * FROM {table} WHERE slave=? ORDER BY ts DESC LIMIT 1",
                        (slave,)).fetchone()
        return dict(r) if r else None


def record_poll_result(slave, ok, error=None, source="serial", ts=None):
    """Record communication health separately from immutable meter readings."""
    ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as con:
        con.execute(
            """INSERT INTO meter_poll_status
               (slave, source, last_attempt, last_success, consecutive_failures, last_error)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(slave, source) DO UPDATE SET
                 last_attempt=excluded.last_attempt,
                 last_success=CASE WHEN excluded.consecutive_failures=0
                                   THEN excluded.last_success
                                   ELSE meter_poll_status.last_success END,
                 consecutive_failures=CASE WHEN excluded.consecutive_failures=0 THEN 0
                                           ELSE meter_poll_status.consecutive_failures+1 END,
                 last_error=excluded.last_error""",
            (slave, source, ts, ts if ok else None,
             0 if ok else 1, None if ok else str(error or "Tidak ada respons")[:500]),
        )


def get_poll_status(slave, source=None):
    if source is None:
        source = "esp32" if get_settings().get("conn_type") == "esp32" else "serial"
    with connect() as con:
        row = con.execute(
            "SELECT * FROM meter_poll_status WHERE slave=? AND source=?",
            (slave, source)).fetchone()
        return dict(row) if row else None
