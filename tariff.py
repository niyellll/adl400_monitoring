"""Snapshot klasifikasi tarif WBP/LWBP per pembacaan.

Periode default adalah asumsi operasional yang HARUS diverifikasi terhadap
kontrak pelanggan. Tarif adalah input pengguna, bukan harga resmi PLN.
"""
from datetime import datetime, time

def classify(ts, settings):
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").time()
    start = time.fromisoformat(settings.get("wbp_start", "17:00"))
    end = time.fromisoformat(settings.get("wbp_end", "22:00"))
    in_peak = (start <= t < end) if start < end else (t >= start or t < end)
    return "WBP" if in_peak else "LWBP"

def rate_for(ts, settings, override=None):
    # Tarif override legacy tetap dikenali; WBP hanya dikenakan apabila
    # fitur diferensiasi aktif. Pengali WBP tidak otomatis berlaku untuk >100 A.
    base = float(override if override is not None else settings.get("tarif", "1444.70"))
    category = classify(ts, settings)
    enabled = str(settings.get("tou_enabled", "False")).lower() == "true"
    multiplier = float(settings.get("wbp_multiplier", "1")) if enabled and category == "WBP" else 1.0
    return category, base * multiplier

def describe_amps(amps, threshold):
    if amps is None:
        return "Tidak ada data arus"
    if float(amps) >= float(threshold):
        return "Melebihi ambang pantau (bukan diagnosis atau tarif otomatis)"
    return "Di bawah ambang pantau"
