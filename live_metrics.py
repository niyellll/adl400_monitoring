"""Status koneksi dan estimasi biaya harian dari snapshot tarif yang tersimpan.

Tidak mengubah data historis dan tidak menebak energi yang belum teralokasi.
"""
from datetime import datetime


def connection_state(last, poll, interval, now=None):
    """Return (status, explanation), using actual poll failures when available."""
    now = now or datetime.now()
    if not last:
        return "offline", "Belum ada pembacaan berhasil"
    sample_time = datetime.strptime(last["ts"], "%Y-%m-%d %H:%M:%S")
    age = (now - sample_time).total_seconds()
    if age > max(30, interval * 3 + 10):
        return "offline", "Tidak ada data baru; pembacaan terakhir sudah kedaluwarsa"
    if poll and poll.get("consecutive_failures", 0) >= 2:
        return "offline", f"{poll['consecutive_failures']} kegagalan pembacaan berturut-turut"
    if poll and poll.get("consecutive_failures", 0) >= 1:
        return "gangguan", f"Komunikasi gagal: {poll.get('last_error') or 'tidak ada respons'}"
    return "online", "Pembacaan terbaru berhasil"


def daily_energy_cost(con, slave, source, table, day_start):
    """Compute same-day cost for [first reading, last reading] only.

    Never include the first snapshot's delta (it may span the prior date).
    No guessing across missing tariff snapshots, resets or collection gaps.
    """
    points = con.execute(
        f"SELECT ts,kwh FROM {table} WHERE slave=? AND ts>=? AND kwh IS NOT NULL ORDER BY ts",
        (slave, day_start),
    ).fetchall()
    if not points:
        return {"usage_kwh": None, "allocated_kwh": 0.0, "missing_kwh": 0.0,
                "energy_cost": None, "complete": False, "reason": "Belum ada data hari ini"}
    if len(points) < 2:
        return {"usage_kwh": 0.0, "allocated_kwh": 0.0, "missing_kwh": 0.0,
                "energy_cost": None, "complete": False, "reason": "Butuh dua pembacaan"}
    raw = float(points[-1]["kwh"]) - float(points[0]["kwh"])
    if raw < 0:
        return {"usage_kwh": None, "allocated_kwh": 0.0, "missing_kwh": 0.0,
                "energy_cost": None, "complete": False,
                "reason": "kWh turun; kemungkinan reset/pergantian meter"}
    snapshots = con.execute(
        """SELECT mode,delta_kwh,estimated_energy_cost
           FROM reading_tariffs
           WHERE slave=? AND source=? AND ts>? AND ts<=? ORDER BY ts""",
        (slave, source, points[0]["ts"], points[-1]["ts"]),
    ).fetchall()
    valid = [r for r in snapshots
             if r["mode"] in ("single", "double")
             and r["delta_kwh"] is not None and r["estimated_energy_cost"] is not None
             and float(r["delta_kwh"]) >= 0]
    allocated = sum(float(r["delta_kwh"]) for r in valid)
    cost = sum(float(r["estimated_energy_cost"]) for r in valid)
    missing = max(0.0, raw - allocated)
    tolerance = max(1e-6, abs(raw) * 1e-6)
    mixed = len({r["mode"] for r in valid}) > 1
    complete = abs(raw - allocated) <= tolerance and not mixed and len(valid) == len(points) - 1
    reason = ("Lengkap" if complete else
              "Skema tarif berubah hari ini" if mixed else
              "Ada kWh belum teralokasi atau snapshot tarif tidak lengkap")
    return {"usage_kwh": raw, "allocated_kwh": allocated,
            "missing_kwh": missing, "energy_cost": cost,
            "complete": complete, "reason": reason}
