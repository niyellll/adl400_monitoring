"""DEMO dashboard monitoring kWh tenant mall (data SIMULASI).

File mandiri: tidak butuh collector, database, maupun meter asli.
Cocok untuk dipamerkan / di-deploy ke Streamlit Community Cloud.

Jalankan:  streamlit run demo_app.py
Di Streamlit Cloud isi "Main file path" dengan: demo_app.py
"""
import random
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="DEMO Monitoring kWh Tenant", page_icon="⚡", layout="wide")

WIB = timezone(timedelta(hours=7))
STEP_MIN = 5          # resolusi data simulasi (menit)
HISTORY_DAYS = 45     # lama riwayat simulasi

# nama, lokasi, beban puncak kW, beban malam kW, jam puncak, tarif override (None = default)
TENANTS = [
    (1, "Supermarket Sejahtera", "GF-01", 38.0, 9.0, 15.0, None),
    (2, "Resto Nusantara", "GF-12", 22.0, 4.0, 19.0, None),
    (3, "Bioskop XXI", "L3-01", 55.0, 12.0, 20.0, 1500.0),
    (4, "Fitness Prima", "L2-07", 18.0, 3.0, 18.0, None),
    (5, "Toko Elektronik Maju", "L1-05", 12.0, 1.5, 15.0, None),
    (6, "Food Court", "L1-20", 45.0, 6.0, 13.0, 1500.0),
]


def rupiah(x):
    return "-" if x is None or pd.isna(x) else "Rp " + f"{x:,.0f}".replace(",", ".")


@st.cache_data(show_spinner="Membuat data simulasi...")
def build_history(end_key: str) -> pd.DataFrame:
    """Riwayat simulasi semua tenant sampai waktu `end_key` (diganti tiap 5 menit)."""
    end = datetime.fromisoformat(end_key)
    start = (end - timedelta(days=HISTORY_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    idx = pd.date_range(start, end, freq=f"{STEP_MIN}min")
    hours = idx.hour.values + idx.minute.values / 60
    weekend = (idx.dayofweek.values >= 5).astype(float)
    # mall buka 10:00-22:00 dengan transisi halus 30 menit
    open_f = np.clip((hours - 9.5) / 0.5, 0, 1) * np.clip((22.5 - hours) / 0.5, 0, 1)

    frames = []
    for slave, name, lokasi, peak, night, peak_h, _ in TENANTS:
        rng = np.random.default_rng(1000 + slave)
        shape = 0.7 + 0.3 * np.exp(-((hours - peak_h) ** 2) / (2 * 2.5 ** 2))
        kw = night + (peak - night) * open_f * shape * (1 + 0.15 * weekend)
        kw = np.maximum(kw + rng.normal(0, 0.04 * peak, len(idx)), 0.3)
        kwh = 2000 + slave * 700 + np.cumsum(kw * STEP_MIN / 60)
        v = 220 + rng.normal(0, 2.0, len(idx))
        pf = np.clip(rng.normal(0.92, 0.02, len(idx)), 0.8, 0.99)
        i_tot = kw * 1000 / (3 * v * pf)
        frames.append(pd.DataFrame({
            "ts": idx, "slave": slave, "tenant": name, "lokasi": lokasi,
            "kw": kw.round(3), "kwh": kwh.round(2), "v": v.round(1),
            "i": i_tot.round(2), "pf": pf.round(3)}))
    return pd.concat(frames, ignore_index=True)


def history() -> pd.DataFrame:
    now = datetime.now(WIB).replace(tzinfo=None)
    now = now.replace(minute=now.minute // STEP_MIN * STEP_MIN, second=0, microsecond=0)
    return build_history(now.isoformat())


# ------------------------------------------------------------------ SIDEBAR
with st.sidebar:
    st.header("Pengaturan tarif")
    tarif = st.number_input("Tarif (Rp/kWh)", value=1444.70, step=10.0)
    ppj = st.number_input("PPJ (%)", value=3.0, step=0.5)
    admin = st.number_input("Biaya admin / tenant (Rp)", value=50000.0, step=5000.0)
    st.caption("Tenant dengan tarif khusus (Bioskop, Food Court) memakai Rp 1.500/kWh.")
    st.divider()
    st.info("Ini versi DEMO dengan data simulasi. Versi asli membaca meter Acrel ADL400 "
            "lewat RS485/Modbus.")

st.title("⚡ Monitoring kWh Tenant")
st.warning("MODE DEMO: semua angka di halaman ini adalah data simulasi, bukan dari meter asli.")

df_all = history()
tenant_names = {t[0]: f"{t[1]} (slave {t[0]})" for t in TENANTS}
tarif_of = {t[0]: (t[6] or tarif) for t in TENANTS}

tab_live, tab_chart, tab_bill, tab_about = st.tabs(["📡 Live", "📈 Grafik", "🧾 Tagihan", "ℹ️ Tentang"])

# ------------------------------------------------------------------ LIVE
with tab_live:
    @st.fragment(run_every=5)
    def live():
        d = history()
        today0 = pd.Timestamp(datetime.now(WIB).date())
        total_kw, total_cost, cards = 0.0, 0.0, []
        for slave, name, lokasi, *_ in TENANTS:
            g = d[d["slave"] == slave]
            last = g.iloc[-1]
            first_today = g[g["ts"] >= today0].iloc[0]
            today_kwh = max(last["kwh"] - first_today["kwh"], 0)
            kw = last["kw"] * random.uniform(0.97, 1.03)   # sedikit goyang biar terasa "live"
            volt = last["v"] + random.uniform(-0.8, 0.8)
            total_kw += kw
            total_cost += today_kwh * tarif_of[slave]
            cards.append((name, lokasi, slave, kw, last["kwh"], today_kwh, volt, last["i"], last["pf"]))

        c1, c2, c3 = st.columns(3)
        c1.metric("Total beban saat ini", f"{total_kw:,.1f} kW")
        c2.metric("Estimasi biaya hari ini", rupiah(total_cost))
        c3.metric("Meter online", f"{len(cards)} / {len(cards)}")
        st.divider()

        cols = st.columns(3)
        for i, (name, lokasi, slave, kw, kwh, today_kwh, volt, amp, pf) in enumerate(cards):
            with cols[i % 3].container(border=True):
                st.markdown(f"**{name}** &nbsp; 🟢 online")
                st.caption(f"Slave {slave} · {lokasi}")
                a, b = st.columns(2)
                a.metric("Daya", f"{kw:.2f} kW")
                b.metric("Total kWh", f"{kwh:,.2f}")
                a.metric("Hari ini", f"{today_kwh:.2f} kWh")
                b.metric("Biaya hari ini", rupiah(today_kwh * tarif_of[slave]))
                st.caption(f"V: {volt:.0f} V · I total: {amp:.1f} A · PF {pf:.2f}")
                st.caption(f"Update: {datetime.now(WIB):%Y-%m-%d %H:%M:%S}")
    live()

# ------------------------------------------------------------------ GRAFIK
with tab_chart:
    c1, c2, c3 = st.columns([2, 1, 1])
    pick = c1.multiselect("Tenant", list(tenant_names), default=[1, 2, 3],
                          format_func=lambda s: tenant_names[s])
    labels = {"kw": "Daya (kW)", "v": "Tegangan (V)", "i": "Arus total (A)",
              "pf": "Faktor daya", "kwh": "Total kWh"}
    metric = c2.selectbox("Metrik", list(labels), format_func=lambda k: labels[k])
    rentang = c3.selectbox("Rentang", ["6 jam", "24 jam", "7 hari", "30 hari"], index=1)
    delta = {"6 jam": timedelta(hours=6), "24 jam": timedelta(hours=24),
             "7 hari": timedelta(days=7), "30 hari": timedelta(days=30)}[rentang]
    since = df_all["ts"].max() - delta
    if pick:
        g = df_all[(df_all["slave"].isin(pick)) & (df_all["ts"] >= since)].copy()
        g["Tenant"] = g["slave"].map(tenant_names)
        st.line_chart(g.pivot_table(index="ts", columns="Tenant", values=metric))
    else:
        st.info("Pilih minimal satu tenant.")

# ------------------------------------------------------------------ TAGIHAN
with tab_bill:
    st.subheader("Tagihan listrik per tenant")
    today = date.today()
    min_d = df_all["ts"].min().date()
    c1, c2 = st.columns(2)
    d1 = c1.date_input("Dari tanggal", max(today.replace(day=1), min_d), min_value=min_d, max_value=today)
    d2 = c2.date_input("Sampai tanggal", today, min_value=min_d, max_value=today)
    st.caption(f"Tarif default {rupiah(tarif)}/kWh · PPJ {ppj:g}% · Admin {rupiah(admin)}/tenant")

    start = pd.Timestamp(datetime.combine(d1, time.min))
    end = pd.Timestamp(datetime.combine(d2, time.max))
    rows = []
    for slave, name, lokasi, *_ in TENANTS:
        g = df_all[(df_all["slave"] == slave) & (df_all["ts"] >= start) & (df_all["ts"] <= end)]
        if g.empty:
            continue
        used = g["kwh"].iloc[-1] - g["kwh"].iloc[0]
        energi = used * tarif_of[slave]
        pajak = energi * ppj / 100
        rows.append({"Slave": slave, "Tenant": name, "Lokasi": lokasi,
                     "kWh Awal": round(g["kwh"].iloc[0], 2), "kWh Akhir": round(g["kwh"].iloc[-1], 2),
                     "Pemakaian (kWh)": round(used, 2), "Tarif (Rp/kWh)": tarif_of[slave],
                     "Biaya Energi": round(energi), "PPJ": round(pajak),
                     "Biaya Admin": round(admin), "Total (Rp)": round(energi + pajak + admin)})
    if not rows:
        st.info("Tidak ada data pada periode ini.")
    else:
        bill = pd.DataFrame(rows)
        show = bill.copy()
        for col in ["Tarif (Rp/kWh)", "Biaya Energi", "PPJ", "Biaya Admin", "Total (Rp)"]:
            show[col] = show[col].map(rupiah)
        st.dataframe(show, width="stretch", hide_index=True)
        st.metric("Total seluruh tenant", rupiah(bill["Total (Rp)"].sum()))
        st.download_button("⬇️ Unduh CSV", bill.to_csv(index=False).encode("utf-8"),
                           f"demo_tagihan_{d1}_{d2}.csv", "text/csv")

# ------------------------------------------------------------------ TENTANG
with tab_about:
    st.markdown("""
**Tentang sistem ini**

- Meter: Acrel **ADL400** (3 fasa), dibaca lewat **RS485 / Modbus-RTU**.
- Program pengumpul (`collector.py`) membaca semua meter berkala dan menyimpan ke database.
- Dashboard menampilkan data live, grafik, dan tagihan per tenant:
  `(kWh akhir - kWh awal) x tarif + PPJ + biaya admin`.
- Halaman ini hanya **demo** dengan data simulasi untuk memperlihatkan tampilan dan alur hitungnya.
""")
