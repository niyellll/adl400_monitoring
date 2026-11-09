"""Estimasi tagihan tenant dengan rincian WBP/LWBP dari snapshot pembacaan asli.

Hanya selisih kWh yang divalidasi saat koleksi masuk ke biaya WBP/LWBP.
Data lama, celah panjang, reset meter dan transisi tarif tidak diestimasi diam-diam.
"""
import pandas as pd

import db
import tariff


def compute(start_ts: str, end_ts: str) -> pd.DataFrame:
    settings = db.get_settings()
    default_rate = float(settings["tarif"])
    ppj_rate = float(settings["ppj_persen"]) / 100
    admin = float(settings["biaya_admin"])
    table = db.active_readings_table()
    source = "esp32" if table == "esp32_real_readings" else "serial"
    output = []

    with db.connect() as con:
        for meter in db.get_meters():
            slave = meter["slave"]
            points = con.execute(
                f"SELECT ts, kwh FROM {table} WHERE slave=? AND ts>=? AND ts<=? "
                "AND kwh IS NOT NULL ORDER BY ts",
                (slave, start_ts, end_ts),
            ).fetchall()
            base = (meter["tarif_override"] if meter["tarif_override"] is not None
                    else default_rate)
            mode = tariff.effective_mode(meter.get("tariff_mode"), settings)
            display_mode = "Double Tarif" if mode == "double" else "Tarif Tunggal"
            row = {
                "Slave": slave, "Tenant": meter["tenant"], "Lokasi": meter["lokasi"],
                "Jenis Tarif": display_mode,
                "kWh Awal": round(float(points[0]["kwh"]), 2) if points else None,
                "kWh Akhir": round(float(points[-1]["kwh"]), 2) if points else None,
                "Pemakaian (kWh)": None, "kWh LWBP": None, "kWh WBP": None,
                "kWh Belum Teralokasi": None,
                "Tarif (Rp/kWh)": float(base),
                "Pengali WBP": float(settings.get("wbp_multiplier", "1")) if mode == "double" else 1.0,
                "Biaya LWBP": None, "Biaya WBP": None,
                "Biaya Energi": None, "PPJ": None, "Biaya Admin": None,
                "Total (Rp)": None, "Catatan": "tidak ada data",
            }
            if not points:
                output.append(row)
                continue
            if len(points) < 2:
                row["Catatan"] = "Perlu minimal dua pembacaan untuk menghitung pemakaian"
                output.append(row)
                continue

            raw_usage = float(points[-1]["kwh"]) - float(points[0]["kwh"])
            if raw_usage < 0:
                row["Catatan"] = "kWh akhir lebih kecil dari awal (reset/ganti meter); periksa manual"
                output.append(row)
                continue

            row["Pemakaian (kWh)"] = round(raw_usage, 2)
            if mode == "single":
                # Legacy flat-rate is safe only if the selected interval has
                # no double-tariff snapshots recorded under an earlier mode.
                mixed = con.execute(
                    """SELECT 1 FROM reading_tariffs WHERE source=? AND slave=?
                       AND ts>? AND ts<=? AND mode='double' LIMIT 1""",
                    (source, slave, points[0]["ts"], points[-1]["ts"]),
                ).fetchone()
                if mixed:
                    row["Catatan"] = (
                        "Perubahan skema tarif dalam periode; pilih periode terpisah. "
                        "Total tidak dihitung."
                    )
                    output.append(row)
                    continue
                energy = raw_usage * float(base)
                row.update({
                    "Biaya Energi": round(energy),
                    "PPJ": round(energy * ppj_rate),
                    "Biaya Admin": round(admin),
                    "Total (Rp)": round(energy * (1 + ppj_rate) + admin),
                    "Catatan": "Tarif tunggal; WBP/LWBP tidak aktif",
                })
                output.append(row)
                continue

            snapshots = con.execute(
                """SELECT period, delta_kwh, estimated_energy_cost, note, mode
                   FROM reading_tariffs
                   WHERE source=? AND slave=? AND ts>=? AND ts<=?
                   ORDER BY ts""",
                (source, slave, start_ts, end_ts),
            ).fetchall()
            lw_kwh = wb_kwh = lw_cost = wb_cost = 0.0
            for sample in snapshots:
                if (sample["mode"] != "double" or sample["delta_kwh"] is None
                        or sample["estimated_energy_cost"] is None):
                    continue
                amount = float(sample["delta_kwh"])
                cost = float(sample["estimated_energy_cost"])
                if amount < 0:
                    continue
                if sample["period"] == "WBP":
                    wb_kwh += amount
                    wb_cost += cost
                elif sample["period"] == "LWBP":
                    lw_kwh += amount
                    lw_cost += cost

            allocated = lw_kwh + wb_kwh
            # Snapshot tarif dibuat saat pencatatan dan mungkin meliputi interval
            # sebelum tanggal awal (pembacaan pertama dalam periode), jadi tidak
            # boleh ikut dihitung dalam rentang invoice ini.
            first_ts = points[0]["ts"]
            first_snapshot = con.execute(
                """SELECT period, delta_kwh, estimated_energy_cost, mode
                   FROM reading_tariffs WHERE source=? AND slave=? AND ts=?""",
                (source, slave, first_ts),
            ).fetchone()
            if (first_snapshot and first_snapshot["mode"] == "double"
                    and first_snapshot["delta_kwh"] is not None):
                amount = float(first_snapshot["delta_kwh"])
                cost = float(first_snapshot["estimated_energy_cost"])
                if first_snapshot["period"] == "WBP":
                    wb_kwh -= amount
                    wb_cost -= cost
                elif first_snapshot["period"] == "LWBP":
                    lw_kwh -= amount
                    lw_cost -= cost
                allocated = lw_kwh + wb_kwh

            # Snapshot dapat kehilangan cakupan karena gap dan pergantian tarif;
            # jangan tagihkan sebagian angka sebagai total tagihan yang lengkap.
            missing = max(0.0, raw_usage - allocated)
            row.update({
                "kWh LWBP": round(max(0, lw_kwh), 3),
                "kWh WBP": round(max(0, wb_kwh), 3),
                "kWh Belum Teralokasi": round(missing, 3),
                "Biaya LWBP": round(lw_cost),
                "Biaya WBP": round(wb_cost),
            })
            tolerance = max(1e-6, abs(raw_usage) * 1e-6)
            if allocated > raw_usage + tolerance:
                row["Catatan"] = "Alokasi tarif melebihi selisih kWh; perlu pemeriksaan manual"
            elif missing > tolerance:
                row["Catatan"] = (
                    "BELUM LENGKAP: ada konsumsi tanpa alokasi tarif (jeda, "
                    "batas WBP/LWBP, atau data historis). Total tidak dihitung."
                )
            else:
                energy = lw_cost + wb_cost
                row.update({
                    "Biaya Energi": round(energy),
                    "PPJ": round(energy * ppj_rate),
                    "Biaya Admin": round(admin),
                    "Total (Rp)": round(energy * (1 + ppj_rate) + admin),
                    "Catatan": "Estimasi WBP/LWBP dari snapshot valid; verifikasi kontrak PLN",
                })
            output.append(row)
    result = pd.DataFrame(output)
    if not result.empty:
        result["Status Alokasi"] = result["Total (Rp)"].apply(
            lambda value: "Lengkap" if pd.notna(value) else "Perlu pemeriksaan")
        # Keep completeness and the reason prominently visible in dashboard/Excel.
        cols = list(result.columns)
        cols.remove("Status Alokasi")
        position = cols.index("Catatan")
        cols.insert(position, "Status Alokasi")
        result = result[cols]
    return result
