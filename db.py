"""Lapisan database SQLite (dipakai bersama oleh collector.py dan app.py)."""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.environ.get("ADL400_DB", "monitoring.db")

DEFAULT_SETTINGS = {
    "conn_type": "serial",      # serial | tcp
    "serial_port": "COM3",      # contoh Linux: /dev/ttyUSB0
    "baud": "9600",
    "parity": "N",
    "host": "192.168.1.100",
    "tcp_port": "502",
    "interval": "60",           # detik antar pembacaan
    "tarif": "1444.70",         # Rp per kWh
    "ppj_persen": "0",          # pajak penerangan jalan (%)
    "biaya_admin": "0",         # Rp per tenant per bulan
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
        """)
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
            con.execute(
                "INSERT INTO meters (slave, tenant, lokasi, tarif_override, aktif) "
                "VALUES (?, ?, ?, ?, ?)",
                (int(r["slave"]), r["tenant"], r.get("lokasi") or "",
                 r.get("tarif_override"), 1 if r.get("aktif", True) else 0))


def insert_reading(slave, data, ts=None):
    ts = ts or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as con:
        con.execute(
            "INSERT INTO readings VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts, slave, data["kwh"], data["v_a"], data["v_b"], data["v_c"],
             data["i_a"], data["i_b"], data["i_c"], data["kw"], data["pf"]))


def last_reading(slave):
    with connect() as con:
        r = con.execute("SELECT * FROM readings WHERE slave=? ORDER BY ts DESC LIMIT 1",
                        (slave,)).fetchone()
        return dict(r) if r else None
