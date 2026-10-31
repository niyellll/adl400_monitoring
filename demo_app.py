"""DEMO dashboard monitoring kWh tenant mall (data SIMULASI).

File mandiri: tidak butuh collector, database, maupun meter asli.
Dipisah dari aplikasi asli (app.py di folder induk) supaya aman dipamerkan.

Jalankan:  streamlit run demo/demo_app.py
Streamlit Cloud -> Main file path: demo/demo_app.py
"""
import random
from datetime import date, datetime, time, timedelta, timezone

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Demo Monitoring kWh Tenant", page_icon="⚡", layout="wide")

WIB = timezone(timedelta(hours=7))
STEP_MIN = 5
HISTORY_DAYS = 45
PALETTE = ["#38bdf8", "#f59e0b", "#a78bfa", "#34d399", "#f472b6", "#fb7185"]

# slave, nama, lokasi, beban puncak kW, beban malam kW, jam puncak, tarif khusus (None = default)
TENANTS = [
    (1, "Supermarket Sejahtera", "GF-01", 38.0, 9.0, 15.0, None),
    (2, "Resto Nusantara", "GF-12", 22.0, 4.0, 19.0, None),
    (3, "Bioskop XXI", "L3-01", 55.0, 12.0, 20.0, 1500.0),
    (4, "Fitness Prima", "L2-07", 18.0, 3.0, 18.0, None),
    (5, "Toko Elektronik Maju", "L1-05", 12.0, 1.5, 15.0, None),
    (6, "Food Court", "L1-20", 45.0, 6.0, 13.0, 1500.0),
]
NAMES = [t[1] for t in TENANTS]
CAPACITY = {t[0]: t[3] * 1.15 for t in TENANTS}  # kapasitas kontrak (kW)

# ---------------------------------------------------------------- STYLE
st.markdown("""<style>
.block-container{padding-top:1.6rem;max-width:1200px}
.hero{border-radius:20px;padding:26px 30px;margin-bottom:18px;color:#fff;
background:linear-gradient(120deg,#0ea5e9 0%,#6366f1 55%,#8b5cf6 100%);
box-shadow:0 10px 30px rgba(99,102,241,.25)}
.hero h1{margin:0;font-size:2rem;line-height:1.2;color:#fff;padding:0}
.hero p{margin:6px 0 0;opacity:.92;font-size:1rem}
.pill{display:inline-block;background:rgba(255,255,255,.22);border-radius:999px;padding:3px 12px;font-size:.78rem;font-weight:600;margin-bottom:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;margin:6px 0 18px}
.grid4{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:6px 0 18px}
.kpi,.tcard,.inv{border:1px solid rgba(128,128,128,.28);background:rgba(128,128,128,.07);border-radius:16px;padding:16px 18px}
.kpi .ic{font-size:1.4rem}
.kpi .lb{font-size:.82rem;opacity:.75;margin-top:2px}
.kpi .vl{font-size:1.75rem;font-weight:700;line-height:1.25}
.kpi .sub{font-size:.78rem;opacity:.7;margin-top:2px}
.up{color:#f87171}.down{color:#34d399}
.thead{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.tname{font-weight:700;font-size:1.02rem}
.tloc{font-size:.78rem;opacity:.65}
.badge{font-size:.72rem;font-weight:700;padding:3px 10px;border-radius:999px;white-space:nowrap}
.b-ok{background:rgba(52,211,153,.18);color:#10b981}
.b-mid{background:rgba(245,158,11,.2);color:#d97706}
.b-hi{background:rgba(248,113,113,.2);color:#ef4444}
.tpower{font-size:2.1rem;font-weight:800;margin-top:8px;line-height:1.1}
.tpower span{font-size:1rem;font-weight:600;opacity:.6}
.bar{height:9px;border-radius:99px;background:rgba(128,128,128,.22);margin-top:8px;overflow:hidden}
.fill{height:100%;border-radius:99px}
.f-ok{background:#10b981}.f-mid{background:#f59e0b}.f-hi{background:#ef4444}
.barlbl{font-size:.74rem;opacity:.65;margin-top:4px}
.trow{display:flex;gap:18px;margin-top:12px}
.trow b{display:block;font-size:1.05rem}
.trow small{opacity:.65;font-size:.74rem}
.tfoot{margin-top:12px;padding-top:10px;border-top:1px dashed rgba(128,128,128,.35);font-size:.78rem;opacity:.75}
.hint{border-left:4px solid #6366f1;background:rgba(99,102,241,.08);border-radius:8px;padding:10px 14px;font-size:.88rem;margin:4px 0 14px}
.flow{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:10px 0 18px}
.step{border:1px solid rgba(128,128,128,.28);background:rgba(128,128,128,.07);border-radius:16px;padding:16px;text-align:center}
.step .n{width:30px;height:30px;border-radius:50%;background:#6366f1;color:#fff;font-weight:700;display:inline-flex;align-items:center;justify-content:center;margin-bottom:6px}
.step b{display:block}.step small{opacity:.7}
.inv h4{margin:0 0 10px;padding:0}
.irow{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px dashed rgba(128,128,128,.3);font-size:.92rem}
.itot{display:flex;justify-content:space-between;padding-top:12px;font-size:1.25rem;font-weight:800}
</style>""", unsafe_allow_html=True)


def rupiah(x):
    return "-" if x is None or pd.isna(x) else "Rp " + f"{x:,.0f}".replace(",", ".")


def now_wib():
    return datetime.now(WIB).replace(tzinfo=None)


# ---------------------------------------------------------------- DATA SIMULASI
@st.cache_data(show_spinner="Menyiapkan data simulasi...")
def build_history(end_key: str) -> pd.DataFrame:
    end = datetime.fromisoformat(end_key)
    start = (end - timedelta(days=HISTORY_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0)
    idx = pd.date_range(start, end, freq=f"{STEP_MIN}min")
    hours = idx.hour.values + idx.minute.values / 60
    weekend = (idx.dayofweek.values >= 5).astype(float)
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
            "ts": idx, "slave": slave, "Tenant": name, "lokasi": lokasi,
            "kw": kw.round(3), "kwh": kwh.round(2), "v": v.round(1),
            "i": i_tot.round(2), "pf": pf.round(3)}))
    return pd.concat(frames, ignore_index=True)


def history() -> pd.DataFrame:
    n = now_wib()
    n = n.replace(minute=n.minute // STEP_MIN * STEP_MIN, second=0, microsecond=0)
    return build_history(n.isoformat())


def kwh_between(g, a, b):
    s = g[(g["ts"] >= a) & (g["ts"] <= b)]["kwh"]
    return float(s.iloc[-1] - s.iloc[0]) if len(s) > 1 else 0.0


# ---------------------------------------------------------------- SIDEBAR
with st.sidebar:
    st.markdown("### ⚙️ Atur tarif")
    tarif = st.number_input("Tarif listrik (Rp per kWh)", value=1444.70, step=10.0)
    ppj = st.number_input("PPJ / pajak (%)", value=3.0, step=0.5)
    admin = st.number_input("Biaya admin per tenant (Rp)", value=50000.0, step=5000.0)
    st.caption("Bioskop dan Food Court memakai tarif khusus Rp 1.500 per kWh.")
    st.divider()
    st.info("Ini **DEMO** dengan data simulasi. Versi asli membaca meter Acrel ADL400 lewat RS485 / Modbus.")

tarif_of = {t[0]: (t[6] or tarif) for t in TENANTS}
df_all = history()

# ---------------------------------------------------------------- HEADER
st.markdown(f"""<div class="hero">
<span class="pill">🧪 MODE DEMO · DATA SIMULASI</span>
<h1>⚡ Monitoring Listrik Tenant Mall</h1>
<p>Pantau pemakaian listrik tiap tenant secara langsung, lengkap dengan perkiraan biayanya.</p>
</div>""", unsafe_allow_html=True)

tab_live, tab_chart, tab_bill, tab_how = st.tabs(
    ["📡 Pantau Langsung", "📈 Grafik", "🧾 Tagihan", "💡 Cara Kerja"])

# ---------------------------------------------------------------- LIVE
with tab_live:
    @st.fragment(run_every=5)
    def live():
        d = history()
        n = now_wib()
        day0 = pd.Timestamp(n.date())
        yday0 = day0 - pd.Timedelta(days=1)
        yday_now = pd.Timestamp(n) - pd.Timedelta(days=1)

        cards, total_kw, total_kwh, total_cost, yday_kwh = [], 0.0, 0.0, 0.0, 0.0
        for slave, name, lokasi, *_ in TENANTS:
            g = d[d["slave"] == slave]
            last = g.iloc[-1]
            tk = kwh_between(g, day0, pd.Timestamp(n))
            yday_kwh += kwh_between(g, yday0, yday_now)
            kw = max(last["kw"] * random.uniform(0.97, 1.03), 0.1)
            cost = tk * tarif_of[slave]
            total_kw += kw
            total_kwh += tk
            total_cost += cost
            cards.append((slave, name, lokasi, kw, tk, cost,
                          last["v"] + random.uniform(-0.8, 0.8), last["i"], last["pf"]))

        delta = (total_kwh - yday_kwh) / yday_kwh * 100 if yday_kwh else 0
        cls = "up" if delta > 0 else "down"
        arrow = "▲" if delta > 0 else "▼"
        kpis = f"""<div class="grid4">
<div class="kpi"><div class="ic">🔌</div><div class="lb">Beban listrik sekarang</div><div class="vl">{total_kw:,.1f} kW</div><div class="sub">Total semua tenant</div></div>
<div class="kpi"><div class="ic">📊</div><div class="lb">Pemakaian hari ini</div><div class="vl">{total_kwh:,.0f} kWh</div><div class="sub"><span class="{cls}">{arrow} {abs(delta):.0f}%</span> dibanding kemarin jam ini</div></div>
<div class="kpi"><div class="ic">💰</div><div class="lb">Perkiraan biaya hari ini</div><div class="vl">{rupiah(total_cost)}</div><div class="sub">Belum termasuk PPJ dan admin</div></div>
<div class="kpi"><div class="ic">🟢</div><div class="lb">Meter terhubung</div><div class="vl">{len(cards)} dari {len(cards)}</div><div class="sub">Diperbarui {n:%H:%M:%S} WIB</div></div>
</div>"""
        st.markdown(kpis, unsafe_allow_html=True)

        st.markdown('<div class="hint">💡 <b>Cara baca:</b> angka besar di tiap kartu adalah <b>daya yang dipakai saat ini (kW)</b>. '
                    'Bar menunjukkan seberapa dekat dengan batas kapasitas tenant. '
                    'Hijau = aman, kuning = sibuk, merah = hampir penuh.</div>', unsafe_allow_html=True)

        html = ['<div class="grid">']
        for slave, name, lokasi, kw, tk, cost, volt, amp, pf in cards:
            pct = min(kw / CAPACITY[slave] * 100, 100)
            if pct < 55:
                k, label = "ok", "Normal"
            elif pct < 80:
                k, label = "mid", "Sibuk"
            else:
                k, label = "hi", "Beban tinggi"
            html.append(
                f'<div class="tcard"><div class="thead"><div><div class="tname">{name}</div>'
                f'<div class="tloc">{lokasi} · Meter #{slave}</div></div>'
                f'<span class="badge b-{k}">{label}</span></div>'
                f'<div class="tpower">{kw:.1f}<span> kW</span></div>'
                f'<div class="bar"><div class="fill f-{k}" style="width:{pct:.0f}%"></div></div>'
                f'<div class="barlbl">{pct:.0f}% dari kapasitas {CAPACITY[slave]:.0f} kW</div>'
                f'<div class="trow"><div><b>{tk:,.0f} kWh</b><small>dipakai hari ini</small></div>'
                f'<div><b>{rupiah(cost)}</b><small>biaya hari ini</small></div></div>'
                f'<div class="tfoot">Tegangan {volt:.0f} V · Arus {amp:.0f} A · Faktor daya {pf:.2f}</div></div>')
        html.append("</div>")
        st.markdown("".join(html), unsafe_allow_html=True)

        # perbandingan biaya hari ini
        cdf = pd.DataFrame({"Tenant": [c[1] for c in cards], "Biaya (Rp)": [c[5] for c in cards]})
        st.markdown("##### Siapa yang paling boros hari ini?")
        st.altair_chart(
            alt.Chart(cdf).mark_bar(cornerRadiusEnd=6, size=22).encode(
                y=alt.Y("Tenant:N", sort="-x", title=None),
                x=alt.X("Biaya (Rp):Q", title="Perkiraan biaya hari ini (Rp)"),
                color=alt.Color("Tenant:N", scale=alt.Scale(domain=NAMES, range=PALETTE), legend=None),
                tooltip=["Tenant", alt.Tooltip("Biaya (Rp):Q", format=",.0f")]
            ).properties(height=250),
            width="stretch")
    live()

# ---------------------------------------------------------------- GRAFIK
with tab_chart:
    st.markdown('<div class="hint">💡 Grafik ini menunjukkan <b>kapan</b> listrik dipakai. '
                'Naik di jam buka mall, turun saat tutup. Arahkan kursor ke garis untuk melihat angkanya.</div>',
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns([2, 1, 1])
    pick = c1.multiselect("Tenant", NAMES, default=NAMES[:3])
    labels = {"kw": "Daya (kW)", "v": "Tegangan (V)", "i": "Arus (A)", "pf": "Faktor daya"}
    metric = c2.selectbox("Yang ditampilkan", list(labels), format_func=lambda k: labels[k])
    rentang = c3.selectbox("Rentang waktu", ["24 jam", "6 jam", "7 hari"])
    delta_t = {"6 jam": timedelta(hours=6), "24 jam": timedelta(hours=24), "7 hari": timedelta(days=7)}[rentang]
    if pick:
        g = df_all[df_all["Tenant"].isin(pick) & (df_all["ts"] >= df_all["ts"].max() - delta_t)]
        fmt = "%d %b" if rentang == "7 hari" else "%H:%M"
        base = alt.Chart(g).encode(
            x=alt.X("ts:T", title=None, axis=alt.Axis(format=fmt)),
            y=alt.Y(f"{metric}:Q", title=labels[metric], scale=alt.Scale(zero=False)),
            color=alt.Color("Tenant:N", scale=alt.Scale(domain=NAMES, range=PALETTE),
                            legend=alt.Legend(orient="bottom", title=None)),
            tooltip=[alt.Tooltip("ts:T", title="Waktu", format="%d %b %H:%M"), "Tenant",
                     alt.Tooltip(f"{metric}:Q", title=labels[metric], format=".2f")])
        st.altair_chart(
            (base.mark_line(interpolate="monotone", strokeWidth=2.2) +
             base.mark_circle(opacity=0, size=70)).properties(height=360),
            width="stretch")
    else:
        st.info("Pilih minimal satu tenant dulu.")

    st.markdown("##### Total pemakaian per hari (14 hari terakhir)")
    dd = df_all.sort_values(["slave", "ts"]).copy()
    dd["pakai"] = dd.groupby("slave")["kwh"].diff().fillna(0)
    dd["Tanggal"] = dd["ts"].dt.normalize()
    daily = dd.groupby(["Tanggal", "Tenant"], as_index=False)["pakai"].sum()
    daily = daily[daily["Tanggal"] > daily["Tanggal"].max() - pd.Timedelta(days=14)]
    st.altair_chart(
        alt.Chart(daily).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("Tanggal:T", title=None, axis=alt.Axis(format="%d %b")),
            y=alt.Y("pakai:Q", title="kWh per hari"),
            color=alt.Color("Tenant:N", scale=alt.Scale(domain=NAMES, range=PALETTE),
                            legend=alt.Legend(orient="bottom", title=None)),
            tooltip=[alt.Tooltip("Tanggal:T", format="%d %b"), "Tenant",
                     alt.Tooltip("pakai:Q", title="kWh", format=",.0f")]
        ).properties(height=300),
        width="stretch")

# ---------------------------------------------------------------- TAGIHAN
with tab_bill:
    st.markdown('<div class="hint">💡 Tagihan dihitung otomatis: <b>(kWh akhir − kWh awal) × tarif</b>, '
                'ditambah PPJ dan biaya admin. Tarif bisa diubah di panel kiri.</div>', unsafe_allow_html=True)
    periode = st.radio("Periode tagihan", ["Bulan ini", "7 hari terakhir", "30 hari terakhir"], horizontal=True)
    today = date.today()
    d1 = {"Bulan ini": today.replace(day=1), "7 hari terakhir": today - timedelta(days=6),
          "30 hari terakhir": today - timedelta(days=29)}[periode]
    start, end = pd.Timestamp(datetime.combine(d1, time.min)), pd.Timestamp(datetime.combine(today, time.max))
    st.caption(f"Periode: {d1:%d %b %Y} sampai {today:%d %b %Y}")

    rows = []
    for slave, name, lokasi, *_ in TENANTS:
        g = df_all[(df_all["slave"] == slave) & (df_all["ts"] >= start) & (df_all["ts"] <= end)]
        if g.empty:
            continue
        a, b = float(g["kwh"].iloc[0]), float(g["kwh"].iloc[-1])
        used = b - a
        energi = used * tarif_of[slave]
        pajak = energi * ppj / 100
        rows.append({"Tenant": name, "Lokasi": lokasi, "kWh awal": a, "kWh akhir": b, "Pemakaian": used,
                     "Tarif": tarif_of[slave], "Energi": energi, "PPJ": pajak, "Admin": admin,
                     "Total": energi + pajak + admin})
    bill = pd.DataFrame(rows)

    m1, m2, m3 = st.columns(3)
    m1.metric("Total pemakaian", f"{bill['Pemakaian'].sum():,.0f} kWh")
    m2.metric("Total tagihan semua tenant", rupiah(bill["Total"].sum()))
    top = bill.loc[bill["Total"].idxmax()]
    m3.metric("Tagihan terbesar", top["Tenant"], rupiah(top["Total"]), delta_color="off")

    show = pd.DataFrame({
        "Tenant": bill["Tenant"], "Lokasi": bill["Lokasi"],
        "Pemakaian (kWh)": bill["Pemakaian"].map(lambda x: f"{x:,.1f}"),
        "Tarif": bill["Tarif"].map(rupiah), "Biaya energi": bill["Energi"].map(rupiah),
        "PPJ": bill["PPJ"].map(rupiah), "Admin": bill["Admin"].map(rupiah),
        "Total tagihan": bill["Total"].map(rupiah)})
    st.dataframe(show, width="stretch", hide_index=True)
    st.download_button("⬇️ Unduh tabel (CSV)", bill.round(2).to_csv(index=False).encode("utf-8"),
                       f"demo_tagihan_{d1}_{today}.csv", "text/csv")

    st.markdown("##### Contoh lembar tagihan satu tenant")
    pick_t = st.selectbox("Pilih tenant", bill["Tenant"].tolist(), label_visibility="collapsed")
    r = bill[bill["Tenant"] == pick_t].iloc[0]
    st.markdown(f"""<div class="inv"><h4>🧾 {r['Tenant']} <small style="opacity:.6">· {r['Lokasi']}</small></h4>
<div class="irow"><span>Angka meter awal</span><span>{r['kWh awal']:,.1f} kWh</span></div>
<div class="irow"><span>Angka meter akhir</span><span>{r['kWh akhir']:,.1f} kWh</span></div>
<div class="irow"><span>Pemakaian</span><span><b>{r['Pemakaian']:,.1f} kWh</b></span></div>
<div class="irow"><span>Tarif per kWh</span><span>{rupiah(r['Tarif'])}</span></div>
<div class="irow"><span>Biaya energi</span><span>{rupiah(r['Energi'])}</span></div>
<div class="irow"><span>PPJ ({ppj:g}%)</span><span>{rupiah(r['PPJ'])}</span></div>
<div class="irow"><span>Biaya admin</span><span>{rupiah(r['Admin'])}</span></div>
<div class="itot"><span>Total tagihan</span><span>{rupiah(r['Total'])}</span></div></div>""",
                unsafe_allow_html=True)

# ---------------------------------------------------------------- CARA KERJA
with tab_how:
    st.markdown("""<div class="flow">
<div class="step"><div class="n">1</div><b>Meter ADL400</b><small>Terpasang di tiap tenant, mengukur kWh, tegangan, dan arus</small></div>
<div class="step"><div class="n">2</div><b>Kabel RS485</b><small>Semua meter disambung ke satu jalur kabel data</small></div>
<div class="step"><div class="n">3</div><b>Program pembaca</b><small>Membaca semua meter tiap 1 menit dan menyimpannya</small></div>
<div class="step"><div class="n">4</div><b>Dashboard ini</b><small>Menampilkan pemakaian, grafik, dan tagihan</small></div>
</div>""", unsafe_allow_html=True)
    st.markdown("""
##### Istilah yang dipakai
| Istilah | Artinya |
|---|---|
| **kW** (kilowatt) | Daya yang dipakai *saat ini*. Seperti kecepatan mobil di speedometer. |
| **kWh** (kilowatt-jam) | Total energi yang sudah terpakai. Seperti jarak tempuh di odometer. Ini yang ditagihkan. |
| **Tegangan (V)** | Kekuatan listrik yang masuk. Normalnya sekitar 220 V per fasa. |
| **Arus (A)** | Banyaknya aliran listrik yang mengalir ke tenant. |
| **Faktor daya (PF)** | Seberapa efisien listrik dipakai. Makin dekat 1, makin baik. |
| **PPJ** | Pajak Penerangan Jalan, persentase tambahan dari biaya energi. |

##### Yang perlu diketahui
- Semua angka di halaman ini **simulasi**, dibuat untuk memperlihatkan tampilan dan cara hitungnya.
- Versi asli (`app.py`) berjalan di PC yang terhubung ke meter di mall dan datanya benar-benar dari meter.
""")
