"""Pengumpul data: baca semua meter ADL400 berkala lalu simpan ke SQLite.

Jalankan di PC/mini PC yang terhubung ke RS485 (atau gateway):
    python collector.py                # mode normal
    python collector.py --demo         # data simulasi (tanpa alat)
    python collector.py --once         # satu putaran lalu keluar
    python collector.py --probe 1 0 130   # dump register mentah slave 1 (alamat 0, 130 reg)
"""
import argparse
import math
import random
import time

import db
import modbus


def simulate(state, slave):
    """Data palsu yang mirip meter asli, kWh naik terus."""
    last = state.get(slave)
    if last is None:
        prev = db.last_reading(slave)
        last = prev["kwh"] if prev else random.uniform(1000, 5000)
    base_kw = 8 + 6 * math.sin(time.time() / 600 + slave) + random.uniform(-1, 1)
    kw = max(base_kw, 0.5)
    interval = float(db.get_settings()["interval"])
    last += kw * interval / 3600
    state[slave] = last
    v = lambda: round(random.uniform(218, 226), 1)
    i = round(kw * 1000 / (3 * 220 * 0.9), 2)
    return {"kwh": round(last, 2), "v_a": v(), "v_b": v(), "v_c": v(),
            "i_a": i, "i_b": round(i * 0.95, 2), "i_c": round(i * 1.05, 2),
            "kw": round(kw, 3), "pf": round(random.uniform(0.85, 0.97), 3)}


def probe(slave, start, count):
    client = modbus.open_client(db.get_settings())
    try:
        step = 20
        for a in range(start, start + count, step):
            n = min(step, start + count - a)
            try:
                regs = client.read_holding(slave, a, n)
                for k, r in enumerate(regs):
                    print(f"0x{a + k:04X} ({a + k:5d}) = {r:5d}  (0x{r:04X})")
            except modbus.ModbusError as e:
                print(f"0x{a:04X}..+{n}: {e}")
    finally:
        client.close()


def cycle(demo, state):
    s = db.get_settings()
    meters = db.get_meters(only_active=True)
    if not meters:
        print("Belum ada meter. Tambahkan di tab Pengaturan pada dashboard.")
        return
    client = None
    try:
        if not demo:
            client = modbus.open_client(s)
        for m in meters:
            try:
                data = simulate(state, m["slave"]) if demo else modbus.read_meter(client, m["slave"])
                db.insert_reading(m["slave"], data)
                print(f"[OK ] {m['tenant']} (slave {m['slave']}): "
                      f"{data['kwh']} kWh, {data['kw']} kW")
            except Exception as e:  # satu meter gagal tidak boleh menghentikan yang lain
                print(f"[ERR] {m['tenant']} (slave {m['slave']}): {e}")
    except Exception as e:
        print(f"[ERR] koneksi: {e}")
    finally:
        if client:
            client.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--probe", nargs=3, type=int, metavar=("SLAVE", "START", "COUNT"))
    args = ap.parse_args()

    db.init()
    if args.probe:
        probe(*args.probe)
        return
    state = {}
    while True:
        cycle(args.demo, state)
        if args.once:
            break
        time.sleep(max(5, int(db.get_settings()["interval"])))


if __name__ == "__main__":
    main()
