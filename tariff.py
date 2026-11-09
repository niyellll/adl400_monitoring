"""Klasifikasi tarif per tenant berdasarkan snapshot waktu dan skema penagihan.

Nilai kontrak, jam WBP/LWBP, pengali dan jam perangkat harus diverifikasi.
"""
from datetime import datetime, time, timedelta


def effective_mode(mode, settings):
    """Resolve legacy/global configuration without rewriting existing tenant rows."""
    if mode == "single":
        return "single"
    if mode == "double":
        return "double"
    return ("double" if str(settings.get("tou_enabled", "False")).lower() == "true"
            else "single")


def classify(ts, settings):
    t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").time()
    start = time.fromisoformat(settings.get("wbp_start", "17:00"))
    end = time.fromisoformat(settings.get("wbp_end", "22:00"))
    in_peak = (start <= t < end) if start < end else (t >= start or t < end)
    return "WBP" if in_peak else "LWBP"


def rate_for(ts, settings, override=None, mode=None):
    base = float(override if override is not None else settings.get("tarif", "1444.70"))
    period = classify(ts, settings)
    if effective_mode(mode, settings) == "single":
        return period, base
    factor = float(settings.get("wbp_multiplier", "1")) if period == "WBP" else 1.0
    return period, base * factor


def describe_amps(amps, threshold):
    if amps is None:
        return "Tidak ada data arus"
    if float(amps) >= float(threshold):
        return "Melebihi ambang pantau (bukan diagnosis atau tarif otomatis)"
    return "Di bawah ambang pantau"

def interval_period(previous_ts, current_ts, settings):
    """Classify energy in [previous_ts, current_ts), without guessing at boundaries.

    Reading at exactly 17:00 represents energy *up to* 17:00 (LWBP).
    Reading at exactly 22:00 represents energy *up to* 22:00 (WBP).
    If an interval straddles a boundary in its interior, return None.
    """
    previous = datetime.strptime(previous_ts, "%Y-%m-%d %H:%M:%S")
    current = datetime.strptime(current_ts, "%Y-%m-%d %H:%M:%S")
    if current <= previous:
        return None
    # Caller additionally validates sampling gaps. This function handles
    # any interval, including days, by checking every crossed calendar date.
    start = time.fromisoformat(settings.get("wbp_start", "17:00"))
    end = time.fromisoformat(settings.get("wbp_end", "22:00"))
    day = previous.date()
    while day <= current.date():
        for boundary in (datetime.combine(day, start), datetime.combine(day, end)):
            if previous < boundary < current:
                return None
        day += timedelta(days=1)
    return classify(previous_ts, settings)
