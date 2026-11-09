"""Monitoring listrik tenant Acrel ADL400.
Satu aplikasi Streamlit dengan mode demo (simulasi) dan live (meter asli).
Data simulasi tidak ditulis ke database maupun memodifikasi konfigurasi live.
"""
import io
import random
from datetime import date, datetime, time, timedelta, timezone

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import billing
import db
import tariff

st.set_page_config(
    page_title="Monitoring Listrik Tenant", page_icon="⚡",
    layout="wide", initial_sidebar_state="expanded",
)

st.markdown("""<style>
.block-container {max-width: 1500px; padding-top: 1.5rem; padding-bottom: 2.5rem}
h1,h2,h3 {letter-spacing: -.025em}
[data-testid="stMetric"] {padding: 14px 16px; border: 1px solid rgba(128,128,128,.17);
border-radius: 12px; background: rgba(128,128,128,.045)}
[data-testid="stMetricLabel"] {font-size: .86rem; white-space: normal; overflow-wrap: anywhere}
[data-testid="stMetricValue"] {font-size: clamp(1.15rem, 1.8vw, 1.65rem); overflow-wrap: anywhere}
[data-testid="stMetric"] {min-width: 0}
[data-testid="column"] {min-width: 0}
.stTabs [data-baseweb="tab-list"] {gap: 12px}
.stTabs [data-baseweb="tab"] {font-weight: 600}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 14px}
</style>""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚡ Monitoring Energi Tenant")
    st.caption("Lippo Plaza Sidoarjo")
    pilihan_mode = st.radio(
        "Sumber data",
        ["Demo · simulasi", "Live · meter asli"],
        index=0,
        help="Demo memakai data contoh. Live membaca database dari collector ADL400.",
        key="pilihan_mode",
    )
    if pilihan_mode.startswith("Demo"):
        st.info("Mode demonstrasi aktif. Informasi berikut merupakan data simulasi, bukan hasil pengukuran lapangan.")
    else:
        st.warning("Mode operasional membutuhkan koneksi ke sistem pembacaan meter dan database yang aktif.")
    st.divider()


def render_live():
    """Tampilan operasional; tidak pernah menggunakan data demo."""
    db.init()
    def rupiah(x):
        return "-" if x is None or pd.isna(x) else "Rp " + f"{x:,.0f}".replace(",", ".")


    settings = db.get_settings()
    meters = db.get_meters()
    tarif = float(settings["tarif"])
    interval = int(settings["interval"])
    readings_table = db.active_readings_table()

    st.markdown("## Monitoring listrik tenant")
    st.caption("Data pembacaan meter Acrel ADL400 · Mode Live")
    tab_live, tab_chart, tab_bill, tab_set = st.tabs(
        ["📡 Live", "📈 Grafik", "🧾 Tagihan", "⚙️ Pengaturan"])

    # ------------------------------------------------------------------ LIVE
    with tab_live:
        @st.fragment(run_every=10)
        def live():
            ms = db.get_meters(only_active=True)
            if not ms:
                st.info("Belum ada meter. Tambahkan di tab **Pengaturan**.")
                return
            today = datetime.combine(date.today(), time.min).strftime("%Y-%m-%d %H:%M:%S")
            total_kw, total_cost = 0.0, 0.0
            cards = []
            for m in ms:
                last = db.last_reading(m["slave"])
                if not last:
                    cards.append((m, None, None, False))
                    continue
                age = (datetime.now() - datetime.strptime(last["ts"], "%Y-%m-%d %H:%M:%S")).total_seconds()
                online = age <= interval * 3 + 10
                with db.connect() as con:
                    r = con.execute(f"SELECT kwh FROM {readings_table} WHERE slave=? AND ts>=? ORDER BY ts ASC LIMIT 1",
                                    (m["slave"], today)).fetchone()
                today_kwh = max(last["kwh"] - r["kwh"], 0) if r else 0
                cards.append((m, last, today_kwh, online))
                if online:
                    total_kw += (last["kw"] or 0)
                total_cost += today_kwh * (m["tarif_override"] or tarif)

            c1, c2, c3 = st.columns(3)
            c1.metric("Total beban saat ini", f"{total_kw:,.2f} kW")
            c2.metric("Estimasi biaya hari ini", rupiah(total_cost))
            c3.metric("Meter online", f"{sum(1 for c in cards if c[3])} / {len(cards)}")
            st.divider()

            # Satu meter mendapat satu kartu lebar penuh; banyak meter dibagi
            # maksimal dua kolom agar label dan angka tidak terpotong.
            num_columns = min(len(cards), 2)
            cols = st.columns(num_columns)
            for i, (m, last, today_kwh, online) in enumerate(cards):
                with cols[i % num_columns].container(border=True):
                    st.markdown(f"**{m['tenant']}** &nbsp; {'🟢 online' if online else '🔴 offline'}")
                    st.caption(f"Slave {m['slave']} · {m['lokasi'] or '-'}")
                    if not last:
                        st.write("Belum ada data.")
                        continue
                    a, b = st.columns(2)
                    a.metric("Daya", f"{last['kw']:.2f} kW" if last["kw"] is not None else "—")
                    b.metric("Total kWh", f"{last['kwh']:,.2f}")
                    a.metric("Hari ini", f"{today_kwh:.2f} kWh")
                    b.metric("Biaya hari ini", rupiah(today_kwh * (m["tarif_override"] or tarif)))
                    def fmt(value, digits=1):
                        return f"{value:.{digits}f}" if value is not None else "—"
                    st.caption(f"V: {fmt(last['v_a'], 0)}/{fmt(last['v_b'], 0)}/{fmt(last['v_c'], 0)} V · "
                               f"I: {fmt(last['i_a'])}/{fmt(last['i_b'])}/{fmt(last['i_c'])} A · "
                               f"PF {fmt(last['pf'], 2)}")
                    st.caption(f"Update: {last['ts']}")
                    if not online:
                        st.warning("Pembacaan terakhir sudah terlalu lama; tegangan yang ditampilkan "
                                   "merupakan nilai historis, bukan kondisi listrik saat ini.")
        live()

    # ------------------------------------------------------------------ GRAFIK
    with tab_chart:
        if not meters:
            st.info("Belum ada meter.")
        else:
            names = {m["slave"]: f"{m['tenant']} (slave {m['slave']})" for m in meters}
            c1, c2, c3 = st.columns([2, 1, 1])
            pick = c1.multiselect("Tenant", list(names), default=list(names)[:3],
                                  format_func=lambda s: names[s])
            metric = c2.selectbox("Metrik", {"kw": "Daya (kW)", "v_a": "Tegangan A (V)",
                                             "i_a": "Arus A (A)", "pf": "Faktor daya",
                                             "kwh": "Total kWh"}.keys(),
                                  format_func=lambda k: {"kw": "Daya (kW)", "v_a": "Tegangan A (V)",
                                                         "i_a": "Arus A (A)", "pf": "Faktor daya",
                                                         "kwh": "Total kWh"}[k])
            rentang = c3.selectbox("Rentang", ["6 jam", "24 jam", "7 hari", "30 hari"], index=1)
            delta = {"6 jam": timedelta(hours=6), "24 jam": timedelta(hours=24),
                     "7 hari": timedelta(days=7), "30 hari": timedelta(days=30)}[rentang]
            since = (datetime.now() - delta).strftime("%Y-%m-%d %H:%M:%S")
            if pick:
                with db.connect() as con:
                    df = pd.read_sql_query(
                        f"SELECT ts, slave, {metric} AS val FROM {readings_table} "
                        f"WHERE ts>=? AND slave IN ({','.join('?' * len(pick))}) ORDER BY ts",
                        con, params=[since, *pick])
                if df.empty:
                    st.warning("Belum ada data pada rentang ini.")
                else:
                    df["ts"] = pd.to_datetime(df["ts"])
                    df["Tenant"] = df["slave"].map(names)
                    df = df.dropna(subset=["val"]).copy()
                    if df.empty:
                        st.info("Belum ada nilai valid untuk metrik dan periode ini.")
                    else:
                        labels = {"kw": "Daya (kW)", "v_a": "Tegangan A (V)",
                                  "i_a": "Arus A (A)", "pf": "Faktor daya",
                                  "kwh": "Total kWh"}
                        title = labels[metric]
                        st.caption(
                            f"{len(df):,} sampel · Pembacaan terakhir: "
                            f"{df['ts'].max():%d-%m-%Y %H:%M:%S} "
                            "· Grafik menggunakan data Live tersimpan."
                        )
                        time_format = "%d %b %H:%M" if rentang in ("7 hari", "30 hari") else "%H:%M"
                        base = alt.Chart(df).encode(
                            x=alt.X("ts:T", title="Waktu pembacaan",
                                    axis=alt.Axis(format=time_format, labelOverlap=True, tickCount=7)),
                            y=alt.Y("val:Q", title=title, scale=alt.Scale(zero=False)),
                            color=alt.Color("Tenant:N", title="Tenant"),
                            tooltip=[
                                alt.Tooltip("ts:T", title="Waktu", format="%d-%m-%Y %H:%M:%S"),
                                alt.Tooltip("Tenant:N", title="Tenant"),
                                alt.Tooltip("val:Q", title=title, format=",.3f"),
                            ],
                        )
                        point_select = alt.selection_point(
                            name="reading_point", fields=["ts", "slave"],
                            on="click", empty=False)
                        line = base.mark_line(strokeWidth=2)
                        dots = base.mark_circle(size=55).add_params(point_select)
                        chart = (line + dots).properties(height=390)
                        event = st.altair_chart(
                            chart, width="stretch", on_select="rerun",
                            selection_mode="reading_point", key="live_phase_chart")
                        st.caption("Klik sebuah titik grafik untuk membuka seluruh parameter meter "
                                   "pada waktu tersebut. Gunakan daftar waktu apabila seleksi tidak tersedia. "
                                   "Sumbu Y tidak selalu dimulai dari nol.")
                        records = db.get_minute_details(pick, since, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                        if records:
                            rows = {(r["slave"], r["ts"]): r for r in records}
                            selected = None
                            try:
                                points = event.selection.get("reading_point", [])
                                if points:
                                    p = points[0]
                                    pts = pd.to_datetime(p["ts"]).strftime("%Y-%m-%d %H:%M:%S")
                                    selected = rows.get((int(p["slave"]), pts))
                            except (KeyError, TypeError, IndexError, ValueError, AttributeError):
                                pass
                            options = list(rows.keys())
                            if selected:
                                selected_key = (selected["slave"], selected["ts"])
                                if st.session_state.get("_previous_chart_point") != selected_key:
                                    st.session_state["_previous_chart_point"] = selected_key
                                    st.session_state["selected_live_sample"] = selected_key
                            if st.session_state.get("selected_live_sample") not in rows:
                                st.session_state["selected_live_sample"] = options[-1]
                            chosen = st.selectbox(
                                "Detail rekaman (tenant dan jam)", options,
                                format_func=lambda v: f"{names.get(v[0], 'Slave '+str(v[0]))} · {v[1]}",
                                key="selected_live_sample")
                            r = rows[chosen]
                            st.markdown("#### Detail pembacaan meter")
                            st.caption(f"Pembacaan asli: {r['ts']} · Slave {r['slave']}. "
                                       "Tidak ada interpolasi data pada menit yang hilang.")
                            a, b, c, d = st.columns(4)
                            a.metric("Daya total", f"{r['kw']:.3f} kW" if r["kw"] is not None else "—")
                            b.metric("kWh kumulatif", f"{r['kwh']:.2f} kWh" if r["kwh"] is not None else "—")
                            c.metric("PF total", f"{r['pf']:.3f}" if r["pf"] is not None else "—")
                            d.metric("Tarif saat pembacaan", r["period"] or "Belum dicatat")
                            phase_data = []
                            for phase, label in (("a", "R / L1"), ("b", "S / L2"), ("c", "T / L3")):
                                current = r["i_" + phase]
                                voltage = r["v_" + phase]
                                phase_data.append({
                                    "Fase": label,
                                    "Tegangan ke netral (V)": voltage,
                                    "Arus (A)": current,
                                    "Status arus": tariff.describe_amps(current, float(settings.get("current_alert_a", 100))),
                                })
                            st.dataframe(pd.DataFrame(phase_data), hide_index=True, width="stretch")
                            amps = [r["i_a"], r["i_b"], r["i_c"]]
                            if all(v is not None for v in amps):
                                top = max(amps)
                                low = min(amps)
                                st.caption(f"Perbandingan arus fase: tertinggi {top:.2f} A, "
                                           f"terendah {low:.2f} A, selisih {top-low:.2f} A. "
                                           "Ini merupakan arus terukur, bukan nilai primer CT yang belum diverifikasi.")
                                if top >= float(settings.get("current_alert_a", 100)):
                                    st.warning("Arus mencapai ambang pemantauan. Periksa CT, "
                                               "kapasitas, kontrak, dan beban bersama teknisi.")
                            # Bandingkan hanya dengan pembacaan sebelumnya dari slave sama.
                            previous = [item for item in records
                                        if item["slave"] == r["slave"] and item["ts"] < r["ts"]]
                            if previous:
                                prev = previous[-1]
                                st.markdown("##### Analisis perubahan dari pembacaan sebelumnya")
                                st.caption(f"Pembanding: {prev['ts']} → {r['ts']}")
                                for phase, label in (("a", "R / L1"), ("b", "S / L2"), ("c", "T / L3")):
                                    old_a, new_a = prev["i_" + phase], r["i_" + phase]
                                    if old_a is not None and new_a is not None:
                                        change = new_a - old_a
                                        pct = (change / old_a * 100) if old_a > 0 else None
                                        msg = f"{label}: {old_a:.2f} → {new_a:.2f} A ({change:+.2f} A)"
                                        if pct is not None:
                                            msg += f" / {pct:+.1f}%"
                                        st.write(msg)
                                        if (pct is not None and pct >= 30 and change >= 1) or (
                                                old_a == 0 and new_a >= float(settings.get("current_alert_a", 100))):
                                            st.warning(f"Terindikasi lonjakan arus {label} dibanding sampel sebelumnya. "
                                                       "Periksa beban serta interval pencatatan; bukan diagnosis gangguan.")
                                if prev["kw"] is not None and r["kw"] is not None:
                                    st.write(f"Daya total: {prev['kw']:.3f} → {r['kw']:.3f} kW")
                            else:
                                st.caption("Belum ada rekaman pembanding sebelumnya pada rentang ini.")
                            if r["rate"] is not None:
                                st.write(f"Tarif snapshot: Rp {r['rate']:,.2f}/kWh · "
                                         f"kWh antar sampel: {r['delta_kwh'] if r['delta_kwh'] is not None else 'tidak tersedia'} · "
                                         f"Estimasi energi: {rupiah(r['estimated_energy_cost'])}")
                                st.caption(r["note"] or "")
                            else:
                                st.info("Rekaman lama belum memiliki snapshot tarif. "
                                        "Tidak diklaim sebagai tarif historis.")
                            st.caption("Tegangan R/S/T dari rekaman terakhir tetap ditampilkan walaupun arus atau beban nol. "
                                       "R–S, S–T, T–R dan tegangan terhadap bumi tidak dihitung dari "
                                       "tiga nilai tegangan fase-ke-netral; dibutuhkan register/alat terverifikasi.")
                            with st.expander("Semua rekaman per waktu (CSV)"):
                                detail_df = pd.DataFrame(records)
                                st.dataframe(detail_df, width="stretch", hide_index=True)
                                st.download_button(
                                    "Unduh data per pembacaan (CSV)",
                                    detail_df.to_csv(index=False).encode("utf-8-sig"),
                                    "detail_meter_live.csv", "text/csv", key="download_minute_csv")


    # ------------------------------------------------------------------ TAGIHAN
    with tab_bill:
        st.subheader("Tagihan listrik per tenant")
        today = date.today()
        c1, c2 = st.columns(2)
        d1 = c1.date_input("Dari tanggal", today.replace(day=1))
        d2 = c2.date_input("Sampai tanggal", today)
        if d1 > d2:
            st.error("Tanggal awal tidak boleh lebih besar dari tanggal akhir.")
            st.stop()
        start = datetime.combine(d1, time.min).strftime("%Y-%m-%d %H:%M:%S")
        end = datetime.combine(d2, time.max).strftime("%Y-%m-%d %H:%M:%S")
        st.caption(f"Tarif default: {rupiah(tarif)}/kWh · PPJ {settings['ppj_persen']}% · "
                   f"Admin {rupiah(float(settings['biaya_admin']))}/tenant")
        df = billing.compute(start, end)
        if df.empty:
            st.info("Belum ada meter.")
        else:
            show = df.copy()
            for col in ["Tarif (Rp/kWh)", "Biaya Energi", "PPJ", "Biaya Admin", "Total (Rp)"]:
                show[col] = show[col].map(rupiah)
            st.caption("Estimasi berdasarkan pembacaan pertama dan terakhir yang tersedia "
                       "dalam periode terpilih, bukan tagihan resmi satu bulan penuh. "
                       "Geser tabel secara horizontal untuk melihat seluruh kolom.")
            st.dataframe(
                show, width="stretch", hide_index=True, height=360,
                column_config={
                    "Tenant": st.column_config.TextColumn("Tenant", width="medium"),
                    "Lokasi": st.column_config.TextColumn("Lokasi", width="medium"),
                    "Tarif (Rp/kWh)": st.column_config.TextColumn("Tarif (Rp/kWh)", width="medium"),
                    "Biaya Energi": st.column_config.TextColumn("Biaya Energi", width="medium"),
                    "Biaya Admin": st.column_config.TextColumn("Biaya Admin", width="medium"),
                    "Total (Rp)": st.column_config.TextColumn("Total (Rp)", width="medium"),
                },
            )
            st.metric("Total seluruh tenant", rupiah(df["Total (Rp)"].sum()))
            st.subheader("Rincian WBP / LWBP per pembacaan")
            with db.connect() as con:
                from pandas import read_sql_query
                source = "esp32" if settings.get("conn_type") == "esp32" else "serial"
                per_minute = read_sql_query(
                    """SELECT t.ts AS Waktu, t.slave AS Slave, t.period AS Periode,
                              t.rate AS 'Tarif (Rp/kWh)',
                              t.delta_kwh AS 'Pemakaian (kWh)',
                              t.estimated_energy_cost AS 'Estimasi energi (Rp)',
                              t.note AS Catatan
                       FROM reading_tariffs t
                       WHERE t.source=? AND t.ts>=? AND t.ts<=?
                       ORDER BY t.ts ASC, t.slave ASC""",
                    con, params=[source, start, end])
            if per_minute.empty:
                st.info("Belum ada rekaman baru dengan tarif per waktu. Rekaman lama "
                        "tidak direkayasa menjadi tarif historis.")
            else:
                st.caption("Rekaman tarif tersimpan berdasarkan pengaturan saat pencatatan. "
                           "Ini bukan tagihan resmi; selisih kWh pada pergantian periode "
                           "atau celah panjang tidak dialokasikan otomatis.")
                st.dataframe(per_minute, width="stretch", hide_index=True)
                summary = per_minute.groupby("Periode", dropna=False).agg(
                    Jumlah_pembacaan=("Waktu", "count"),
                    kWh_teralokasi=("Pemakaian (kWh)", "sum"),
                    Estimasi_energi_Rp=("Estimasi energi (Rp)", "sum"),
                ).reset_index()
                st.dataframe(summary, width="stretch", hide_index=True)
                st.download_button(
                    "Unduh riwayat tarif per pembacaan (CSV)",
                    per_minute.to_csv(index=False).encode("utf-8-sig"),
                    "tarif_per_pembacaan.csv", "text/csv",
                    key="download_tariff_samples")
            b1, b2 = st.columns(2)
            b1.download_button("⬇️ CSV", df.to_csv(index=False).encode("utf-8"),
                               f"tagihan_{d1}_{d2}.csv", "text/csv")
            buf = io.BytesIO()
            df.to_excel(buf, index=False, sheet_name="Tagihan")
            b2.download_button("⬇️ Excel", buf.getvalue(), f"tagihan_{d1}_{d2}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ------------------------------------------------------------------ PENGATURAN
    with tab_set:
        st.subheader("Tarif")
        c1, c2, c3 = st.columns(3)
        new_tarif = c1.number_input("Tarif (Rp/kWh)", value=float(settings["tarif"]), step=10.0)
        new_ppj = c2.number_input("PPJ (%)", value=float(settings["ppj_persen"]), step=0.5)
        new_admin = c3.number_input("Biaya admin / tenant (Rp)", value=float(settings["biaya_admin"]), step=1000.0)

        st.subheader("Klasifikasi WBP / LWBP")
        st.caption("Periode contoh sesuai kebutuhan operasional: WBP 17:00–22:00 WIB, "
                   "LWBP 22:00–17:00 WIB. Pastikan waktu laptop, zona waktu, "
                   "golongan pelanggan, dan kontrak PLN sebelum aktivasi tarif.")
        tou = st.checkbox("Aktifkan pengali tarif WBP pada rekaman baru",
                          value=settings.get("tou_enabled", "False").lower() == "true")
        t1, t2, t3 = st.columns(3)
        wbp_start = t1.text_input("WBP mulai (HH:MM)", settings.get("wbp_start", "17:00"))
        wbp_end = t2.text_input("WBP selesai (HH:MM)", settings.get("wbp_end", "22:00"))
        wbp_mult = t3.number_input("Pengali tarif WBP", min_value=1.0,
                                   value=float(settings.get("wbp_multiplier", 1)), step=0.1)
        current_alert = st.number_input("Ambang pemantauan arus per fase (A)",
                                         min_value=1.0,
                                         value=float(settings.get("current_alert_a", 100)),
                                         step=5.0)
        st.caption("Ambang 100 A hanya untuk peringatan, bukan aturan otomatis tarif ganda. "
                   "CT ratio dan model meter (ADL200/ADL400/ADL400-D) harus diverifikasi.")
        try:
            from datetime import time as _time
            _time.fromisoformat(wbp_start)
            _time.fromisoformat(wbp_end)
            valid_hours = True
        except ValueError:
            valid_hours = False
            st.error("Format jam harus HH:MM, misalnya 17:00.")

        st.subheader("Koneksi ke meter")
        st.caption("RS485-USB / Modbus TCP menggunakan collector lokal; ESP32 Wi-Fi memakai penerima HTTP di laptop.")
        connection_types = ["serial", "tcp", "esp32"]
        conn = st.radio("Tipe koneksi", connection_types, horizontal=True,
                        index=connection_types.index(settings["conn_type"]) if settings["conn_type"] in connection_types else 0,
                        format_func=lambda x: {"serial": "RS485-USB (serial)", "tcp": "Gateway Modbus TCP",
                                               "esp32": "ESP32 Wi-Fi (HTTP)"}[x])
        if conn == "esp32":
            st.info("ESP32 mengirim pembacaan meter asli melalui HTTP ke server lokal `esp32_receiver.py` "
                    "yang menyimpan data di SQLite. Port COM, IP gateway, dan port TCP di bawah tidak dipakai "
                    "untuk koneksi ini.")
            st.caption("Di laptop: jalankan `python esp32_receiver.py` setelah menetapkan token "
                       "`ADL400_ESP32_TOKEN` dan memastikan `ADL400_DB` menunjuk ke SQLite yang sama "
                       "dengan dashboard. Receiver menggunakan port 5001 secara default.")
            st.warning("Program ESP32 simulasi yang mengirim `123.45` belum membaca ADL400. "
                       "Mode ini hanya menerima payload REAL yang terautentikasi. "
                       "Streamlit Cloud tidak dapat membaca SQLite di laptop secara langsung.")
        serial_port = settings["serial_port"]
        baud = int(settings["baud"])
        parity = settings["parity"]
        host = settings["host"]
        tcp_port = int(settings["tcp_port"])
        if conn == "serial":
            s1, s2, s3 = st.columns(3)
            serial_port = s1.text_input("Port serial", serial_port, help="Windows: COM3, Linux: /dev/ttyUSB0")
            baud_options = [2400, 4800, 9600, 19200]
            baud = s2.selectbox("Baud rate", baud_options, index=baud_options.index(baud) if baud in baud_options else 2)
            parity = s3.selectbox("Parity", ["N", "E", "O"], index=["N", "E", "O"].index(parity))
        elif conn == "tcp":
            t1, t2 = st.columns(2)
            host = t1.text_input("IP gateway", host)
            tcp_port = t2.number_input("Port TCP", value=tcp_port, min_value=1, max_value=65535, step=1)
        else:
            with db.connect() as con:
                state = con.execute(
                    "SELECT COUNT(*) AS n, MAX(ts) AS latest FROM esp32_real_readings"
                ).fetchone()
            c1, c2 = st.columns(2)
            c1.metric("Pembacaan ESP32 REAL tersimpan", int(state["n"]))
            c2.metric("Terakhir diterima", state["latest"] or "Belum ada")
            st.caption("Parameter baud, parity dan alamat Modbus diatur di firmware ESP32, "
                       "mengikuti konfigurasi meter ADL400. Belum ada pembacaan jika perangkat belum teruji.")
        new_interval = st.number_input("Interval baca / batas status (detik)",
                                       value=int(settings["interval"]), min_value=5, step=5,
                                       help="Untuk ESP32, interval pengiriman diatur juga pada firmware. "
                                            "Nilai ini digunakan dashboard untuk status online/offline.")

        if st.button("💾 Simpan pengaturan", type="primary", disabled=not valid_hours):
            db.save_settings({"tarif": new_tarif, "ppj_persen": new_ppj, "biaya_admin": new_admin,
                              "conn_type": conn, "serial_port": serial_port, "baud": baud,
                              "parity": parity, "host": host, "tcp_port": int(tcp_port),
                              "interval": int(new_interval),
                              "tou_enabled": str(tou), "wbp_start": wbp_start,
                              "wbp_end": wbp_end, "wbp_multiplier": wbp_mult,
                              "current_alert_a": current_alert})
            st.success("Tersimpan.")
            st.rerun()

        st.subheader("Daftar meter / tenant")
        st.caption("Slave = alamat Modbus di meter. Tarif override boleh dikosongkan (pakai tarif default).")
        mdf = pd.DataFrame(meters) if meters else pd.DataFrame(
            {"slave": pd.Series(dtype=int), "tenant": pd.Series(dtype=str),
             "lokasi": pd.Series(dtype=str), "tarif_override": pd.Series(dtype=float),
             "aktif": pd.Series(dtype=bool)})
        mdf["aktif"] = mdf["aktif"].astype(bool)
        edited = st.data_editor(mdf, num_rows="dynamic", width="stretch", hide_index=True,
                                column_config={"slave": st.column_config.NumberColumn("Slave", min_value=1, max_value=247, step=1, required=True),
                                               "tenant": st.column_config.TextColumn("Tenant", required=True),
                                               "lokasi": "Lokasi",
                                               "tarif_override": st.column_config.NumberColumn("Tarif override (Rp/kWh)"),
                                               "aktif": st.column_config.CheckboxColumn("Aktif")})
        if st.button("💾 Simpan daftar meter"):
            rows = [r for r in edited.to_dict("records") if pd.notna(r.get("slave")) and r.get("tenant")]
            for r in rows:
                if pd.isna(r.get("tarif_override")):
                    r["tarif_override"] = None
            db.replace_meters(rows)
            st.success("Daftar meter tersimpan.")
            st.rerun()



def render_demo():
    """Simulasi lokal dalam memori; tanpa menulis ke database Live."""
    WIB = timezone(timedelta(hours=7))
    STEP_MIN = 5
    HISTORY_DAYS = 45
    PALETTE = ["#2563eb", "#0d9488", "#d97706", "#7c3aed", "#16a34a", "#db2777", "#ea580c"]

    # slave, nama, lokasi, beban puncak kW, beban malam kW, jam puncak, tarif khusus (None = default)
    # Tenant sesuai permintaan; lokasi, beban, dan kapasitas hanya simulasi.
    TENANTS = [
        (1, "Uniqlo", "Area contoh 01", 28.0, 5.0, 16.0, None),
        (2, "Matahari", "Area contoh 02", 48.0, 10.0, 16.0, None),
        (3, "The Palace", "Area contoh 03", 11.0, 2.0, 17.0, None),
        (4, "Sport Station", "Area contoh 04", 19.0, 3.0, 15.0, None),
        (5, "Hypermart", "Area contoh 05", 55.0, 17.0, 14.0, None),
        (6, "Solaria", "Area contoh 06", 25.0, 5.0, 19.0, None),
        (7, "A&W", "Area contoh 07", 21.0, 4.0, 19.0, None),
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
        st.markdown("### Pengaturan Tarif Simulasi")
        tarif = st.number_input("Tarif Energi (Rp/kWh)", value=1444.70, step=10.0)
        ppj = st.number_input("PPJ (%)", value=3.0, step=0.5)
        admin = st.number_input("Biaya Administrasi per Tenant (Rp)", value=50000.0, step=5000.0)
        st.caption("Sesuaikan komponen biaya untuk melihat pengaruhnya terhadap estimasi tagihan. Tarif berlaku untuk seluruh tenant demo.")
        st.divider()
        st.caption("Pengaturan simulasi tidak memengaruhi database dan konfigurasi mode operasional.")

    tarif_of = {t[0]: (t[6] or tarif) for t in TENANTS}
    df_all = history()

    # ---------------------------------------------------------------- HEADER
    st.markdown(f"""<div class="hero">
    <span class="pill">🧪 MODE DEMONSTRASI · DATA SIMULASI</span>
    <h1>⚡ Dashboard Monitoring Energi Tenant</h1>
    <p>Ringkasan pemakaian energi tujuh tenant. Nilai pengukuran, lokasi, dan kapasitas ditampilkan sebagai simulasi.</p>
    </div>""", unsafe_allow_html=True)

    with st.expander("Petunjuk Singkat Penggunaan", expanded=True):
        st.markdown(
            "**Ringkasan Pemakaian:** lihat daya, konsumsi energi, dan estimasi biaya setiap tenant.\n\n"
            "**Analisis Grafik:** tentukan tenant, jenis pengukuran, dan periode yang ingin dianalisis.\n\n"
            "**Simulasi Tagihan:** pilih periode, periksa rincian biaya, dan unduh laporan CSV.\n\n"
            "**Pengaturan Tarif:** sesuaikan tarif energi, PPJ, dan biaya administrasi melalui panel samping.\n\n"
            "**Catatan:** data ini hanya untuk demonstrasi dan tidak dapat digunakan sebagai dasar penagihan resmi."
        )

    halaman = st.radio(
        "Navigasi Dashboard",
        ["Ringkasan Pemakaian", "Analisis Grafik", "Simulasi Tagihan", "Panduan Pengguna"],
        horizontal=True, key="halaman_demo",
        help="Pilih bagian yang ingin ditampilkan."
    )
    st.divider()

    # ---------------------------------------------------------------- LIVE
    if halaman == "Ringkasan Pemakaian":
        a_refresh, a_help = st.columns([1, 5])
        if a_refresh.button("Perbarui Data Simulasi", key="refresh_demo"):
            st.rerun()
        a_help.caption("Data yang ditampilkan dihasilkan melalui simulasi, bukan pembacaan meter langsung.")
        # Demo dirender langsung agar konten selalu muncul setelah navigasi.
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
    <div class="kpi"><div class="ic">🔌</div><div class="lb">Total Daya Saat Ini</div><div class="vl">{total_kw:,.1f} kW</div><div class="sub">Total semua tenant</div></div>
    <div class="kpi"><div class="ic">📊</div><div class="lb">Konsumsi Energi Hari Ini</div><div class="vl">{total_kwh:,.0f} kWh</div><div class="sub"><span class="{cls}">{arrow} {abs(delta):.0f}%</span> dibanding kemarin jam ini</div></div>
    <div class="kpi"><div class="ic">💰</div><div class="lb">Estimasi Biaya Hari Ini</div><div class="vl">{rupiah(total_cost)}</div><div class="sub">Belum termasuk PPJ dan biaya administrasi</div></div>
    <div class="kpi"><div class="ic">🟢</div><div class="lb">Meter Simulasi</div><div class="vl">{len(cards)} dari {len(cards)}</div><div class="sub">Diperbarui {n:%H:%M:%S} WIB</div></div>
    </div>"""
            st.markdown(kpis, unsafe_allow_html=True)

            st.markdown(
                '<div class="hint"><b>Memahami Ringkasan:</b> kW menunjukkan daya yang digunakan saat ini, '
                'kWh menunjukkan jumlah energi yang telah digunakan, dan estimasi biaya harian adalah '
                'perkiraan rupiah. Warna hijau, kuning, merah membandingkan beban dengan '
                '<b>kapasitas contoh</b>, bukan hasil pengujian meter fisik.</div>',
                unsafe_allow_html=True)

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
            st.markdown("##### Perbandingan Estimasi Biaya per Tenant")
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
    elif halaman == "Analisis Grafik":
        st.markdown(
            '<div class="hint"><b>Petunjuk Analisis Grafik:</b> pilih tenant yang ingin dianalisis, '
            'pilih parameter, misalnya daya (kW), kemudian tentukan rentang waktu. '
            'Arahkan kursor ke garis untuk melihat nilai pada jam tertentu. '
            'Seluruh grafik menggunakan data simulasi.</div>',
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
            st.info("Pilih setidaknya satu tenant untuk menampilkan grafik.")

        st.markdown("##### Tren Konsumsi Energi Harian (14 Hari Terakhir)")
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
    elif halaman == "Simulasi Tagihan":
        st.markdown(
            '<div class="hint"><b>Petunjuk Perhitungan Tagihan:</b> (1) tentukan periode, '
            '(2) tinjau konsumsi energi dan estimasi biaya pada tabel, '
            '(3) pilih tenant untuk rincian perhitungan, (4) unduh laporan CSV jika diperlukan. '
            'Rumus: (kWh akhir − kWh awal) × tarif + PPJ + admin. '
            'Hasil perhitungan bersifat simulasi, bukan tagihan resmi.</div>',
            unsafe_allow_html=True)
        periode = st.radio("Periode Perhitungan", ["Bulan ini", "7 hari terakhir", "30 hari terakhir"], horizontal=True)
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
        m1.metric("Total Konsumsi Energi", f"{bill['Pemakaian'].sum():,.0f} kWh")
        m2.metric("Total Estimasi Tagihan", rupiah(bill["Total"].sum()))
        top = bill.loc[bill["Total"].idxmax()]
        m3.metric("Estimasi Tagihan Tertinggi", top["Tenant"], rupiah(top["Total"]), delta_color="off")

        show = pd.DataFrame({
            "Tenant": bill["Tenant"], "Lokasi": bill["Lokasi"],
            "Pemakaian (kWh)": bill["Pemakaian"].map(lambda x: f"{x:,.1f}"),
            "Tarif": bill["Tarif"].map(rupiah), "Biaya energi": bill["Energi"].map(rupiah),
            "PPJ": bill["PPJ"].map(rupiah), "Admin": bill["Admin"].map(rupiah),
            "Total tagihan": bill["Total"].map(rupiah)})
        st.dataframe(show, width="stretch", hide_index=True)
        st.download_button("Unduh Laporan CSV", bill.round(2).to_csv(index=False).encode("utf-8"),
                           f"demo_tagihan_{d1}_{today}.csv", "text/csv")

        st.markdown("##### Rincian Estimasi Tagihan per Tenant")
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
    else:
        st.markdown("""
    ### Panduan Penggunaan Dashboard
    1. **Pilih Demo** pada sumber data di menu kiri.
    2. **Pantau Langsung:** cek kW, kWh, dan perkiraan biaya masing-masing tenant.
    3. **Grafik:** pilih tenant untuk membandingkan perubahan pemakaian.
    4. **Tagihan:** pilih periode, lihat rincian satu tenant, lalu unduh CSV.
    5. **Atur tarif:** coba mengganti angka di menu kiri untuk melihat perbedaan biaya.

    **Catatan:** seluruh data tenant di halaman ini simulasi. Nama tenant hanya
    digunakan sebagai contoh pemantauan, bukan menunjukkan angka konsumsi sebenarnya.

    ### Alur kerja bila meter asli sudah tersedia
    """)
        st.markdown("""<div class="flow">
    <div class="step"><div class="n">1</div><b>Meter ADL400</b><small>Terpasang di tiap tenant, mengukur kWh, tegangan, dan arus</small></div>
    <div class="step"><div class="n">2</div><b>Kabel RS485</b><small>Semua meter disambung ke satu jalur kabel data</small></div>
    <div class="step"><div class="n">3</div><b>Program pembaca</b><small>Membaca semua meter tiap 1 menit dan menyimpannya</small></div>
    <div class="step"><div class="n">4</div><b>Dashboard ini</b><small>Menampilkan pemakaian, grafik, dan tagihan</small></div>
    </div>""", unsafe_allow_html=True)
        st.markdown("""
    ##### Penjelasan Parameter Pengukuran
    | Istilah | Artinya |
    |---|---|
    | **kW** (kilowatt) | Daya yang dipakai *saat ini*. Seperti kecepatan mobil di speedometer. |
    | **kWh** (kilowatt-jam) | Total energi yang sudah terpakai. Seperti jarak tempuh di odometer. Ini yang ditagihkan. |
    | **Tegangan (V)** | Kekuatan listrik yang masuk. Normalnya sekitar 220 V per fasa. |
    | **Arus (A)** | Banyaknya aliran listrik yang mengalir ke tenant. |
    | **Faktor daya (PF)** | Seberapa efisien listrik dipakai. Makin dekat 1, makin baik. |
    | **PPJ** | Pajak Penerangan Jalan, persentase tambahan dari biaya energi. |

    ##### Informasi Penting
    - Seluruh angka, lokasi, kapasitas, dan biaya di halaman ini **simulasi**, bukan data pengukuran lapangan.
    - Mode Live membaca database hasil collector yang terhubung ke meter di lokasi. Pilih Mode Live lewat sidebar.
    """)



if pilihan_mode.startswith("Demo"):
    render_demo()
else:
    render_live()
