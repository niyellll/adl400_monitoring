"""Read-only commissioning tool for PUSR USR-DR164 and Acrel energy meters.

Run ONLY after configuring the gateway as TCP Server + Modbus Protocol
Conversion (Socket A), with serial settings matching the actual meter.
This module never imports db, creates SQLite files or sends HTTP packets.

Examples:
  python usr_dr164_modbus.py --host 192.168.1.80 --port 8899 --slave 39
  python usr_dr164_modbus.py --host 192.168.1.80 --port 8899 --slave 39 --full

Note: the TCP listening port is configurable on the gateway, not always 502.
"""
import argparse
import json
import math
import sys

import modbus


def decode_field(client, slave, field_definition):
    """Decode exactly one field using the repository's meter register map."""
    addr, count, scale, signed = field_definition
    registers = client.read_holding(slave, addr, count)
    if len(registers) != count:
        raise modbus.ModbusError("jumlah register respons tidak sesuai permintaan")
    raw = (registers[0] << 16 | registers[1]) if count == 2 else registers[0]
    if signed and raw >= (1 << (16 * count - 1)):
        raw -= 1 << (16 * count)
    return round(raw * scale, 4), registers


def validate_candidate(data):
    """Reject blatantly impossible numbers; still require a meter-screen check."""
    kwh = data.get("kwh")
    if isinstance(kwh, bool) or not isinstance(kwh, (int, float)):
        raise ValueError("kWh tidak numerik")
    if not math.isfinite(kwh) or not 0 <= kwh <= 1e12:
        raise ValueError(f"kWh di luar rentang: {kwh!r}")
    for key, val in data.items():
        if val is None:
            continue
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            raise ValueError(f"{key} tidak numerik/finite")
    pf = data.get("pf")
    if pf is not None and not -1 <= pf <= 1:
        raise ValueError(f"PF di luar rentang: {pf}")
    for key in ("v_a", "v_b", "v_c"):
        val = data.get(key)
        if val is not None and not 0 <= val <= 1000:
            raise ValueError(f"{key} tidak wajar: {val}")


def run(host, port, slave, model, timeout, full=False):
    """Return candidate values from genuine Modbus response; never save them."""
    client = modbus.TCPClient(host, port, timeout=timeout)
    try:
        if full:
            data = modbus.read_meter(client, slave, model=model)
            raw_registers = None
        else:
            fields = modbus.fields_for(model)
            kwh, raw_kwh = decode_field(client, slave, fields["kwh"])
            va, raw_va = decode_field(client, slave, fields["v_a"])
            data = {"kwh": kwh, "v_a": va}
            raw_registers = {"kwh": raw_kwh, "v_a": raw_va}
        validate_candidate(data)
        return {
            "gateway": "USR-DR164",
            "mode": "full_readonly" if full else "probe_readonly",
            "slave": slave,
            "meter_model": model,
            "candidate": data,
            "registers": raw_registers,
            "saved_to_database": False,
        }
    finally:
        client.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Uji baca kWh asli via USR-DR164 (TANPA menyentuh database)."
    )
    parser.add_argument("--host", required=True, help="IP LAN gateway USR-DR164")
    parser.add_argument("--port", type=int, default=8899,
                        help="Port TCP Server Socket A di gateway (default contoh: 8899)")
    parser.add_argument("--slave", type=int, default=39, help="Slave ID meter (default: 39)")
    parser.add_argument("--model", choices=modbus.METER_MODELS, default="ADL400",
                        help="Model sesuai meter fisik (default: ADL400)")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="Timeout socket, detik (default: 3)")
    parser.add_argument("--full", action="store_true",
                        help="Baca semua field; default hanya kWh dan tegangan A")
    args = parser.parse_args(argv)

    if not 1 <= args.port <= 65535 or not 1 <= args.slave <= 247 or not 0.2 <= args.timeout <= 30:
        parser.error("port 1..65535, slave 1..247, timeout 0.2..30 detik")

    try:
        result = run(args.host, args.port, args.slave, args.model, args.timeout,
                     full=args.full)
    except (modbus.ModbusError, OSError, ValueError, IndexError) as exc:
        print(f"[GAGAL] USR-DR164 / Modbus: {exc}", file=sys.stderr)
        print("[AMAN] Tidak ada perubahan database. Periksa IP, port Socket A, "
              "Protocol Conversion, baud/parity, slave, A/B.", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("[READ-ONLY] Bandingkan kWh/tegangan dengan layar meter sebelum "
          "mengaktifkan collector Live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
