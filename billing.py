"""Perhitungan tagihan listrik per tenant dari selisih kWh pada suatu periode."""
import pandas as pd

import db


def compute(start_ts: str, end_ts: str) -> pd.DataFrame:
    s = db.get_settings()
    tarif_default = float(s["tarif"])
    ppj = float(s["ppj_persen"]) / 100
    admin = float(s["biaya_admin"])

    rows = []
    with db.connect() as con:
        for m in db.get_meters():
            r = con.execute(
                """SELECT
                     (SELECT kwh FROM readings WHERE slave=? AND ts>=? AND ts<=? ORDER BY ts ASC  LIMIT 1) AS awal,
                     (SELECT kwh FROM readings WHERE slave=? AND ts>=? AND ts<=? ORDER BY ts DESC LIMIT 1) AS akhir,
                     (SELECT COUNT(*) FROM readings WHERE slave=? AND ts>=? AND ts<=?) AS n""",
                (m["slave"], start_ts, end_ts) * 3).fetchone()
            if not r["n"]:
                rows.append({"Slave": m["slave"], "Tenant": m["tenant"], "Lokasi": m["lokasi"],
                             "kWh Awal": None, "kWh Akhir": None, "Pemakaian (kWh)": None,
                             "Tarif (Rp/kWh)": None, "Biaya Energi": None, "PPJ": None,
                             "Biaya Admin": None, "Total (Rp)": None, "Catatan": "tidak ada data"})
                continue
            used = r["akhir"] - r["awal"]
            note = ""
            if used < 0:
                note = "kWh turun (meter di-reset/diganti?) - cek manual"
                used = 0
            tarif = m["tarif_override"] or tarif_default
            energi = used * tarif
            pajak = energi * ppj
            rows.append({"Slave": m["slave"], "Tenant": m["tenant"], "Lokasi": m["lokasi"],
                         "kWh Awal": round(r["awal"], 2), "kWh Akhir": round(r["akhir"], 2),
                         "Pemakaian (kWh)": round(used, 2), "Tarif (Rp/kWh)": tarif,
                         "Biaya Energi": round(energi), "PPJ": round(pajak),
                         "Biaya Admin": round(admin), "Total (Rp)": round(energi + pajak + admin),
                         "Catatan": note})
    return pd.DataFrame(rows)
