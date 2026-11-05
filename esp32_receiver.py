"""Local ESP32 Wi-Fi HTTP receiver for verified REAL Acrel ADL400 readings.

Run on the PC that keeps the persistent SQLite database, not on Streamlit Cloud.
Environment:
    ADL400_ESP32_TOKEN = long random secret, shared with firmware
    ADL400_DB = path to monitoring.db used by local Streamlit
    ADL400_HTTP_HOST = bind address, defaults to 0.0.0.0
    ADL400_HTTP_PORT = 5001
Always restrict network access to trusted LAN/VPN. Plain HTTP is not internet-safe.
"""
import hmac
import json
import math
import os
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import db

FIELDS = ("kwh", "kw", "v_a", "v_b", "v_c", "i_a", "i_b", "i_c", "pf")


def validated_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("JSON harus berbentuk objek")
    if payload.get("jenis") != "REAL":
        raise ValueError("Hanya hasil meter REAL diterima; simulasi ditolak")
    raw_slave = payload.get("slave")
    if isinstance(raw_slave, bool) or not isinstance(raw_slave, int) or not 1 <= raw_slave <= 247:
        raise ValueError("slave harus bilangan bulat 1 sampai 247")
    if payload.get("device") != "ESP32":
        raise ValueError("device harus ESP32")
    result = {}
    if "kwh" not in payload or payload["kwh"] is None:
        raise ValueError("kwh wajib diisi dari meter")
    for field in FIELDS:
        value = payload.get(field)
        if value is None:
            result[field] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} harus berupa angka")
        num = float(value)
        if not math.isfinite(num):
            raise ValueError(f"{field} tidak valid")
        result[field] = num
    if not 0 <= result["kwh"] <= 1e12:
        raise ValueError("kwh di luar rentang")
    if result["kw"] is not None and not -1e6 <= result["kw"] <= 1e6:
        raise ValueError("kw di luar rentang")
    if result["pf"] is not None and not -1 <= result["pf"] <= 1:
        raise ValueError("pf di luar rentang")
    return raw_slave, result


class Receiver(BaseHTTPRequestHandler):
    def respond(self, status, message):
        body = json.dumps({"status": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/esp32/readings":
            return self.respond(404, "not_found")
        expected = os.environ["ADL400_ESP32_TOKEN"]
        supplied = self.headers.get("X-Device-Token", "")
        if not hmac.compare_digest(supplied, expected):
            return self.respond(401, "unauthorized")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                return self.respond(400, "invalid_body_length")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            slave, data = validated_payload(payload)
            if db.get_settings().get("conn_type") != "esp32":
                return self.respond(409, "select_esp32_wifi_in_dashboard")
            meters = db.get_meters(only_active=True)
            if slave not in {m["slave"] for m in meters}:
                return self.respond(422, "slave_not_registered_or_inactive")
            db.insert_esp32_real_reading(slave, data)
            print(f"[REAL] slave={slave} kwh={data['kwh']} kw={data['kw']} "
                  f"at {datetime.now():%Y-%m-%d %H:%M:%S}", flush=True)
            return self.respond(200, "saved")
        except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            print(f"[REJECTED] {exc}", flush=True)
            return self.respond(400, "invalid_payload")
        except sqlite3.Error as exc:
            print(f"[DATABASE ERROR] {exc}", flush=True)
            return self.respond(500, "database_error")


if __name__ == "__main__":
    token = os.environ.get("ADL400_ESP32_TOKEN", "")
    if len(token) < 24:
        raise SystemExit("Atur ADL400_ESP32_TOKEN minimal 24 karakter sebelum menjalankan server.")
    db.init()
    host = os.environ.get("ADL400_HTTP_HOST", "0.0.0.0")
    port = int(os.environ.get("ADL400_HTTP_PORT", "5001"))
    server = ThreadingHTTPServer((host, port), Receiver)
    print(f"ESP32 REAL receiver aktif pada {host}:{port}; SQLite={db.DB_PATH}", flush=True)
    print("Endpoint: POST /api/esp32/readings; wajib header X-Device-Token.", flush=True)
    server.serve_forever()
