"""Demo dashboard matching Live meter interface.

Demo is generated in memory and never calls db.insert*, db.save_settings,
collector or real reading tables. It does not claim physical measurements.
"""
from datetime import datetime, timedelta, time, date
import io

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import tariff
from export_utils import excel_csv, formatted_xlsx

DEMO_METERS = [
    (1, "Uniqlo", "Area contoh 01", 28.0),
    (2, "Matahari", "Area contoh 02", 48.0),
    (3, "The Palace", "Area contoh 03", 11.0),
    (4, "Sport Station", "Area contoh 04", 19.0),
    (5, "Hypermart", "Area contoh 05", 55.0),
    (6, "Solaria", "Area contoh 06", 25.0),
    (7, "A&W", "Area contoh 07", 21.0),
]


def money(value):
    if value is None or pd.isna(value):
        return "—"
    return "Rp " + f"{value:,.0f}".replace(",", ".")


@st.cache_data(ttl=60, show_spinner=False)
def sample_data(rounded_minute):
    """Seven days of per-minute sample readings, intentionally deterministic."""
    end = pd.Timestamp(rounded_minute)
    times = pd.date_range(end=end, periods=7 * 24 * 60, freq="min")
    minutes = times.hour.to_numpy() * 60 + times.minute.to_numpy()
    df_parts = []
    for slave, tenant, lokasi, peak_kw in DEMO_METERS:
        rng = np.random.default_rng(8300 + slave)
        daily = (np.sin(2 * np.pi * (minutes - 420) / 1440) + 1) / 2
        evening = (np.sin(2 * np.pi * (minutes - 920) / 1440) + 1) / 2
        kw = (0.12 + 0.56 * daily + 0.20 * evening) * peak_kw
        kw = np.maximum(kw + rng.normal(0, peak_kw * .018, len(times)), 0)
        # Clearly illustrative one-minute event for drill-down.
        kw = kw.copy()
        kw[-45:-42] += peak_kw * .23
        pf = np.clip(.89 + rng.normal(0, .018, len(times)), .75, .99)
        va = 229 + 2 * np.sin(np.arange(len(times)) / 140) + rng.normal(0, .35, len(times))
        vb = 231 + 2 * np.sin(np.arange(len(times)) / 150) + rng.normal(0, .35, len(times))
        vc = 230 + 2 * np.sin(np.arange(len(times)) / 130) + rng.normal(0, .35, len(times))
        amps = kw * 1000 / (3 * 230 * pf)
        ia = amps * 1.02
        ib = amps * .96
        ic = amps * 1.02
        kwh = np.round(1000 * slave + np.cumsum(kw / 60), 4)
        df_parts.append(pd.DataFrame({
            "ts": times, "slave": slave, "Tenant": tenant, "lokasi": lokasi,
            "kw": np.round(kw, 3), "kwh": kwh,
            "v_a": np.round(va, 1), "v_b": np.round(vb, 1), "v_c": np.round(vc, 1),
            "i_a": np.round(ia, 2), "i_b": np.round(ib, 2), "i_c": np.round(ic, 2),
            "pf": np.round(pf, 3),
        }))
    return pd.concat(df_parts, ignore_index=True)


def render():
    st.markdown("## Monitoring listrik tenant")
    st.caption("Data pembacaan meter Acrel ADL400 · Mode Demo — seluruh angka simulasi")
    st.info("MODE DEMONSTRASI · Semua pembacaan dan tarif di halaman ini merupakan simulasi. "
            "Tidak berasal dari meter fisik, tidak disimpan di SQLite Live, dan bukan dasar tagihan resmi.")

    if "demo_rate" not in st.session_state:
        st.session_state.demo_rate = 1444.70
    if "demo_ppj" not in st.session_state:
        st.session_state.demo_ppj = 3.0
    if "demo_admin" not in st.session_state:
        st.session_state.demo_admin = 50000.0
    if "demo_wbp_factor" not in st.session_state:
        st.session_state.demo_wbp_factor = 1.5
    if "demo_modes" not in st.session_state:
        st.session_state.demo_modes = {
            1: "double", 2: "single", 3: "double", 4: "single",
            5: "double", 6: "single", 7: "single",
        }

    now = pd.Timestamp.now().floor("min")
    data = sample_data(now.isoformat())
    names = {slave: name for slave, name, *_ in DEMO_METERS}
    tariff_settings = {
        "tarif": str(st.session_state.demo_rate),
        "wbp_start": "17:00", "wbp_end": "22:00",
        "wbp_multiplier": str(st.session_state.demo_wbp_factor),
        "tou_enabled": "True",
    }
    tab_live, tab_chart, tab_bill, tab_set = st.tabs(
        ["📡 Live", "📈 Grafik", "🧾 Tagihan", "⚙️ Pengaturan"])

    with tab_live:
        latest = data.groupby("slave", sort=True).tail(1).set_index("slave")
        day_start = now.normalize()
        day_data = data[data["ts"] >= day_start]
        by_day = day_data.groupby("slave")["kwh"].agg(["first", "last"])
        consumption = (by_day["last"] - by_day["first"]).clip(lower=0)
        total_kw = float(latest["kw"].sum())
        total_used = float(consumption.sum())
        a, b, c = st.columns(3)
        a.metric("Total beban saat ini", f"{total_kw:,.2f} kW")
        b.metric("Biaya dasar hari ini (tanpa WBP)", money(total_used * st.session_state.demo_rate))
        st.caption("Biaya dasar pada ringkasan bukan tagihan WBP/LWBP. "
                   "Lihat tab Tagihan untuk pemisahan per tenant dan status alokasi.")
        c.metric("Meter simulasi", f"{len(DEMO_METERS)} / {len(DEMO_METERS)}")
        st.caption(f"Pembacaan contoh terakhir: {now:%d-%m-%Y %H:%M} · diperbarui tiap menit")
        st.divider()
        cols = st.columns(2)
        for idx, (slave, tenant, lokasi, _) in enumerate(DEMO_METERS):
            r = latest.loc[slave]
            used = float(consumption.get(slave, 0))
            with cols[idx % 2].container(border=True):
                st.markdown(f"**{tenant}** · 🔵 simulasi")
                st.caption(f"Slave {slave} · {lokasi} · "
                           f"{'Double Tarif' if st.session_state.demo_modes.get(slave) == 'double' else 'Tarif Tunggal'}")
                left, right = st.columns(2)
                left.metric("Daya", f"{r['kw']:.2f} kW")
                right.metric("Total kWh", f"{r['kwh']:,.2f}")
                left.metric("Hari ini", f"{used:,.2f} kWh")
                right.metric("Biaya dasar hari ini (tanpa WBP)",
                             money(used * st.session_state.demo_rate))
                st.caption(f"V R/S/T: {r['v_a']:.1f} / {r['v_b']:.1f} / {r['v_c']:.1f} V")
                st.caption(f"I L1/L2/L3: {r['i_a']:.2f} / {r['i_b']:.2f} / {r['i_c']:.2f} A · "
                           f"PF {r['pf']:.3f}")
                st.caption(f"Update: {now:%Y-%m-%d %H:%M:%S} · SIMULASI")

    with tab_chart:
        metrics = {"kw": "Daya (kW)", "v_a": "Tegangan R / L1 (V)",
                   "v_b": "Tegangan S / L2 (V)", "v_c": "Tegangan T / L3 (V)",
                   "i_a": "Arus R / L1 (A)", "i_b": "Arus S / L2 (A)",
                   "i_c": "Arus T / L3 (A)", "pf": "Faktor daya",
                   "kwh": "Total kWh"}
        a, b, c = st.columns([2, 1, 1])
        picked = a.multiselect("Tenant", list(names), default=list(names)[:3],
                               format_func=lambda s: names[s], key="demo_tenants_chart")
        metric = b.selectbox("Metrik", list(metrics), format_func=lambda x: metrics[x],
                             key="demo_metric_chart")
        period = c.selectbox("Rentang", ["6 jam", "24 jam", "7 hari"], index=1,
                             key="demo_period_chart")
        hours = {"6 jam": 6, "24 jam": 24, "7 hari": 168}[period]
        if not picked:
            st.info("Pilih minimal satu tenant.")
        else:
            history = data[(data["slave"].isin(picked)) &
                           (data["ts"] >= now - pd.Timedelta(hours=hours))].copy()
            st.caption(f"{len(history):,} sampel simulasi · Resolusi 1 menit · "
                       f"Terakhir: {now:%d-%m-%Y %H:%M}")
            source = history.copy()
            source["val"] = source[metric]
            is_double = source["slave"].map(st.session_state.demo_modes) == "double"
            in_wbp = (source["ts"].dt.hour >= 17) & (source["ts"].dt.hour < 22)
            source["Periode tarif"] = np.where(
                ~is_double, "TUNGGAL", np.where(in_wbp, "WBP", "LWBP"))
            source["Tarif contoh (Rp/kWh)"] = np.where(
                is_double & in_wbp,
                st.session_state.demo_rate * st.session_state.demo_wbp_factor,
                st.session_state.demo_rate)
            source.sort_values(["slave", "ts"], inplace=True)
            source["Selisih daya (kW)"] = source.groupby("slave")["kw"].diff()
            for ph in ("a", "b", "c"):
                source["Selisih arus " + ph.upper() + " (A)"] = (
                    source.groupby("slave")["i_" + ph].diff())
            base = alt.Chart(source).encode(
                x=alt.X("ts:T", title="Waktu", axis=alt.Axis(
                    format="%H:%M" if hours <= 24 else "%d %b", tickCount=7)),
                y=alt.Y("val:Q", title=metrics[metric], scale=alt.Scale(zero=False)),
                color=alt.Color("Tenant:N", title="Tenant"),
                tooltip=[
                    alt.Tooltip("ts:T", title="Waktu", format="%d-%m-%Y %H:%M"),
                    alt.Tooltip("Tenant:N", title="Tenant"),
                    alt.Tooltip("kw:Q", title="Daya total (kW)", format=",.3f"),
                    alt.Tooltip("kwh:Q", title="Energi kumulatif (kWh)", format=",.3f"),
                    alt.Tooltip("v_a:Q", title="Tegangan R/L1 (V)", format=",.1f"),
                    alt.Tooltip("v_b:Q", title="Tegangan S/L2 (V)", format=",.1f"),
                    alt.Tooltip("v_c:Q", title="Tegangan T/L3 (V)", format=",.1f"),
                    alt.Tooltip("i_a:Q", title="Arus R/L1 (A)", format=",.2f"),
                    alt.Tooltip("i_b:Q", title="Arus S/L2 (A)", format=",.2f"),
                    alt.Tooltip("i_c:Q", title="Arus T/L3 (A)", format=",.2f"),
                    alt.Tooltip("pf:Q", title="Faktor daya", format=".3f"),
                    alt.Tooltip("Periode tarif:N", title="WBP/LWBP"),
                    alt.Tooltip("Tarif contoh (Rp/kWh):Q", title="Tarif simulasi (Rp/kWh)", format=",.2f"),
                    alt.Tooltip("Selisih daya (kW):Q", title="Perubahan daya dari menit sebelumnya", format="+.3f"),
                    alt.Tooltip("Selisih arus A (A):Q", title="Perubahan arus L1 (A)", format="+.2f"),
                    alt.Tooltip("Selisih arus B (A):Q", title="Perubahan arus L2 (A)", format="+.2f"),
                    alt.Tooltip("Selisih arus C (A):Q", title="Perubahan arus L3 (A)", format="+.2f"),
                ])
            selection = alt.selection_point(name="demo_point", fields=["ts", "slave"],
                                            on="click", empty=False)
            # Garis saja yang terlihat. Marker sangat transparan tetap menjadi
            # target hover/click di setiap rekaman per menit.
            line = base.mark_line(strokeWidth=1.8)
            hitboxes = base.mark_circle(size=95, opacity=0.001).add_params(selection)
            chart = (line + hitboxes).properties(height=390)
            event = st.altair_chart(chart, width="stretch", on_select="rerun",
                                    selection_mode="demo_point", key="demo_point_chart")
            st.caption("Arahkan kursor ke titik untuk melihat detail lengkap langsung pada grafik: "
                       "daya, energi, R/S/T, arus, PF, tarif, dan perubahan dari menit sebelumnya. "
                       "Klik posisi pada garis untuk memilih rekaman dan melihat keterangan lengkap di bawah grafik. "
                       "Seluruh angka adalah SIMULASI.")
            lookup = history.set_index(["slave", "ts"]).sort_index()
            choices = list(lookup.index)
            chosen_point = None
            try:
                selected = event.selection.get("demo_point", [])
                if selected:
                    pt = selected[0]
                    chosen_point = (int(pt["slave"]), pd.Timestamp(pt["ts"]).tz_localize(None))
            except (KeyError, TypeError, ValueError, IndexError, AttributeError):
                pass
            if chosen_point in lookup.index:
                if st.session_state.get("_last_demo_point") != chosen_point:
                    st.session_state["_last_demo_point"] = chosen_point
                    st.session_state["demo_chosen_sample"] = chosen_point
            if st.session_state.get("demo_chosen_sample") not in lookup.index:
                st.session_state["demo_chosen_sample"] = choices[-1]
            key = st.selectbox("Detail pembacaan per menit", choices,
                               key="demo_chosen_sample",
                               format_func=lambda k: f"{names[k[0]]} · {k[1]:%d-%m-%Y %H:%M}")
            reading = lookup.loc[key]
            st.markdown("#### Detail pembacaan meter — simulasi")
            st.caption(f"Tenant: {names[key[0]]} · Waktu: {key[1]:%Y-%m-%d %H:%M:%S}")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Daya total", f"{reading['kw']:.3f} kW")
            k2.metric("Energi total", f"{reading['kwh']:.3f} kWh")
            k3.metric("PF total", f"{reading['pf']:.3f}")
            category, rate = tariff.rate_for(
                key[1].strftime("%Y-%m-%d %H:%M:%S"), tariff_settings,
                mode=st.session_state.demo_modes.get(key[0], "single"))
            k4.metric("Periode", category)
            st.dataframe(pd.DataFrame([
                {"Fase": label, "Tegangan ke netral (V)": reading["v_" + ph],
                 "Arus (A)": reading["i_" + ph]}
                for ph, label in (("a", "R / L1"), ("b", "S / L2"), ("c", "T / L3"))
            ]), width="stretch", hide_index=True)
            st.caption(f"Tarif contoh pada menit ini: {money(rate)}/kWh ({category}); "
                       "bukan tarif kontrak resmi.")
            earlier = data[(data["slave"] == key[0]) & (data["ts"] < key[1])].tail(1)
            if not earlier.empty:
                prev = earlier.iloc[0]
                changes = []
                for ph, label in (("a", "L1"), ("b", "L2"), ("c", "L3")):
                    old, new = float(prev["i_" + ph]), float(reading["i_" + ph])
                    pct = (new - old) / old * 100 if old else 0
                    changes.append({"Fase": label, "Arus sebelumnya (A)": old,
                                    "Arus dipilih (A)": new, "Perubahan (%)": round(pct, 1)})
                st.markdown("##### Perbandingan dengan menit sebelumnya")
                st.dataframe(pd.DataFrame(changes), width="stretch", hide_index=True)
                if any(r["Perubahan (%)"] >= 30 and r["Arus dipilih (A)"] -
                       r["Arus sebelumnya (A)"] >= 1 for r in changes):
                    st.warning("Terindikasi lonjakan arus pada simulasi ini.")
            st.caption("Tegangan tetap ditampilkan ketika arus nol; R-S/S-T/T-R dan "
                       "tegangan terhadap bumi tidak disimpulkan dari angka fase-netral.")
            with st.expander("Seluruh rekaman simulasi per menit"):
                st.dataframe(history, width="stretch", hide_index=True)
                ex1, ex2 = st.columns(2)
                ex1.download_button("⬇️ Excel rapi (.xlsx)",
                                    formatted_xlsx(history, "Pembacaan Per Menit"),
                                    "simulasi_per_menit.xlsx",
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key="demo_download_graph_xlsx")
                ex2.download_button("⬇️ CSV untuk Excel",
                                    excel_csv(history), "simulasi_per_menit.csv",
                                    "text/csv", key="demo_download_graph")

    with tab_bill:
        st.subheader("Tagihan listrik per tenant — simulasi")
        a, b = st.columns(2)
        today = now.date()
        start_date = a.date_input("Dari tanggal", today - timedelta(days=6),
                                  min_value=today - timedelta(days=6),
                                  max_value=today, key="demo_bill_start")
        end_date = b.date_input("Sampai tanggal", today,
                                min_value=today - timedelta(days=6),
                                max_value=today, key="demo_bill_end")
        if start_date > end_date:
            st.warning("Tanggal awal harus sebelum atau sama dengan tanggal akhir.")
        else:
            start = pd.Timestamp(datetime.combine(start_date, time.min))
            end = pd.Timestamp(datetime.combine(end_date, time.max))
            filtered = data[(data["ts"] >= start) & (data["ts"] <= end)].copy()
            results = []
            tariff_rows = []
            for slave, tenant, lokasi, _ in DEMO_METERS:
                meter_data = filtered[filtered["slave"] == slave].sort_values("ts").copy()
                if len(meter_data) < 2:
                    continue
                used = max(float(meter_data["kwh"].iloc[-1] -
                                 meter_data["kwh"].iloc[0]), 0)
                mode = st.session_state.demo_modes.get(slave, "single")
                meter_data["delta_kwh"] = meter_data["kwh"].diff().clip(lower=0)
                meter_data["Periode"] = np.where(
                    (meter_data["ts"].dt.hour >= 17) &
                    (meter_data["ts"].dt.hour < 22), "WBP", "LWBP")
                meter_data["Jenis Tarif"] = ("Double Tarif" if mode == "double"
                                              else "Tarif Tunggal")
                if mode == "single":
                    meter_data["Periode"] = "TUNGGAL"
                    meter_data["Tarif (Rp/kWh)"] = st.session_state.demo_rate
                    energy = used * st.session_state.demo_rate
                    lw_kwh = wb_kwh = lw_cost = wb_cost = 0.0
                    missing = 0.0
                    note = "Tarif tunggal selama 24 jam"
                    total = energy * (1 + st.session_state.demo_ppj / 100) + st.session_state.demo_admin
                else:
                    meter_data["Tarif (Rp/kWh)"] = np.where(
                        meter_data["Periode"] == "WBP",
                        st.session_state.demo_rate * st.session_state.demo_wbp_factor,
                        st.session_state.demo_rate)
                    crossing = meter_data["Periode"] != meter_data["Periode"].shift(1)
                    eligible = meter_data["delta_kwh"].notna() & ~crossing
                    lw_kwh = float(meter_data.loc[
                        eligible & (meter_data["Periode"] == "LWBP"), "delta_kwh"].sum())
                    wb_kwh = float(meter_data.loc[
                        eligible & (meter_data["Periode"] == "WBP"), "delta_kwh"].sum())
                    lw_cost = lw_kwh * st.session_state.demo_rate
                    wb_cost = wb_kwh * st.session_state.demo_rate * st.session_state.demo_wbp_factor
                    missing = max(0.0, used - lw_kwh - wb_kwh)
                    energy = lw_cost + wb_cost
                    note = ("Lengkap (simulasi)" if missing <= 0.001
                            else "Belum lengkap: interval lintas periode tidak dialokasikan")
                    total = (energy * (1 + st.session_state.demo_ppj / 100)
                             + st.session_state.demo_admin) if missing <= 0.001 else None
                    meter_data.loc[~eligible, "delta_kwh"] = np.nan
                meter_data["Estimasi energi (Rp)"] = (
                    meter_data["delta_kwh"] * meter_data["Tarif (Rp/kWh)"])
                tariff_rows.append(meter_data[["ts", "Tenant", "Jenis Tarif", "Periode",
                                               "Tarif (Rp/kWh)", "delta_kwh",
                                               "Estimasi energi (Rp)"]])
                results.append({
                    "Slave": slave, "Tenant": tenant, "Lokasi": lokasi,
                    "Jenis Tarif": "Double Tarif" if mode == "double" else "Tarif Tunggal",
                    "kWh Awal": meter_data["kwh"].iloc[0],
                    "kWh Akhir": meter_data["kwh"].iloc[-1],
                    "Pemakaian (kWh)": used, "kWh LWBP": lw_kwh if mode == "double" else None,
                    "kWh WBP": wb_kwh if mode == "double" else None,
                    "kWh Belum Teralokasi": missing if mode == "double" else None,
                    "Tarif (Rp/kWh)": st.session_state.demo_rate,
                    "Pengali WBP": (st.session_state.demo_wbp_factor if mode == "double" else 1.0),
                    "Biaya LWBP": lw_cost if mode == "double" else None,
                    "Biaya WBP": wb_cost if mode == "double" else None,
                    "Biaya Energi": energy if total is not None else None,
                    "PPJ": (energy * st.session_state.demo_ppj / 100) if total is not None else None,
                    "Biaya Admin": st.session_state.demo_admin if total is not None else None,
                    "Total (Rp)": total, "Catatan": note,
                })
            if results:
                bill = pd.DataFrame(results)
                st.caption("Simulasi tarif per tenant; data yang melintasi batas WBP/LWBP "
                           "tanpa alokasi pasti diberi catatan dan total dibiarkan kosong.")
                st.dataframe(bill, width="stretch", hide_index=True)
                complete = bill["Total (Rp)"].dropna()
                st.metric("Total simulasi tenant lengkap",
                          money(complete.sum()) if not complete.empty else "—")
                if len(complete) != len(bill):
                    st.warning(f"{len(bill) - len(complete)} tenant belum memiliki "
                               "alokasi lengkap; jangan anggap total parsial sebagai "
                               "tagihan seluruh tenant.")
                left, right = st.columns(2)
                left.download_button("⬇️ Excel rapi (.xlsx)",
                                     formatted_xlsx(bill, "Simulasi Tagihan"),
                                     "simulasi_tagihan.xlsx",
                                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                right.download_button("⬇️ CSV untuk Excel",
                                      excel_csv(bill), "simulasi_tagihan.csv", "text/csv")
                st.subheader("Rincian WBP / LWBP per pembacaan — simulasi")
                ledger = pd.concat(tariff_rows, ignore_index=True)
                ledger.rename(columns={"ts": "Waktu",
                                       "delta_kwh": "Pemakaian (kWh)"}, inplace=True)
                st.dataframe(ledger, width="stretch", hide_index=True)
                ex1, ex2 = st.columns(2)
                ex1.download_button("⬇️ Excel WBP/LWBP (.xlsx)",
                                    formatted_xlsx(ledger, "Tarif Per Menit"),
                                    "simulasi_wbp_lwbp.xlsx",
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                ex2.download_button("⬇️ CSV untuk Excel",
                                    excel_csv(ledger), "simulasi_wbp_lwbp.csv", "text/csv")

    with tab_set:
        st.subheader("Pengaturan tarif simulasi")
        st.caption("Berubah hanya dalam sesi Demo; tidak memodifikasi konfigurasi Live.")
        a, b, c = st.columns(3)
        a.number_input("Tarif energi simulasi (Rp/kWh)", min_value=0.0,
                       step=10.0, key="demo_rate")
        b.number_input("PPJ simulasi (%)", min_value=0.0,
                       max_value=100.0, step=0.5, key="demo_ppj")
        c.number_input("Admin simulasi (Rp)", min_value=0.0,
                       step=1000.0, key="demo_admin")
        st.number_input("Pengali WBP simulasi (17:00–22:00)",
                        min_value=1.0, max_value=5.0, step=0.1,
                        key="demo_wbp_factor")
        st.caption("WBP 17:00–22:00, LWBP 22:00–17:00. Ini skenario contoh "
                   "yang tetap harus disesuaikan dengan ketentuan kontrak.")
        st.subheader("Jenis tarif tiap tenant — simulasi")
        st.caption("Ubah pilihan untuk menguji Excel dan rincian tagihan. "
                   "Pengaturan ini hanya berlaku selama sesi Demo.")
        demo_rows = pd.DataFrame([
            {"Slave": slave, "Tenant": name, "Jenis Tarif": (
                "Double Tarif" if st.session_state.demo_modes.get(slave) == "double"
                else "Tarif Tunggal")}
            for slave, name, _, _ in DEMO_METERS
        ])
        edited_modes = st.data_editor(
            demo_rows, hide_index=True, width="stretch", num_rows="fixed",
            disabled=["Slave", "Tenant"], key="demo_tariff_mode_editor",
            column_config={"Jenis Tarif": st.column_config.SelectboxColumn(
                "Jenis Tarif", options=["Tarif Tunggal", "Double Tarif"], required=True)})
        if st.button("💾 Terapkan jenis tarif simulasi"):
            st.session_state.demo_modes = {
                int(row["Slave"]): ("double" if row["Jenis Tarif"] == "Double Tarif" else "single")
                for row in edited_modes.to_dict("records")
            }
            st.rerun()
        st.info("Untuk konfigurasi port COM10, collector, dan meter nyata, "
                "pindah ke mode Live · meter asli pada sidebar.")
