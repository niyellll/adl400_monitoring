"""Dashboard monitoring kWh meter Acrel ADL400 (Streamlit).

Jalankan:  streamlit run app.py
Data diisi oleh collector.py (proses terpisah).
"""
import io
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

import billing
import db

st.set_page_config(page_title="Monitoring kWh Tenant", page_icon="⚡", layout="wide")
db.init()


def rupiah(x):
    return "-" if x is None or pd.isna(x) else "Rp " + f"{x:,.0f}".replace(",", ".")


settings = db.get_settings()
meters = db.get_meters()
tarif = float(settings["tarif"])
interval = int(settings["interval"])

st.title("⚡ Monitoring kWh Tenant")
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
                r = con.execute("SELECT kwh FROM readings WHERE slave=? AND ts>=? ORDER BY ts ASC LIMIT 1",
                                (m["slave"], today)).fetchone()
            today_kwh = max(last["kwh"] - r["kwh"], 0) if r else 0
            cards.append((m, last, today_kwh, online))
            if online:
                total_kw += last["kw"]
            total_cost += today_kwh * (m["tarif_override"] or tarif)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total beban saat ini", f"{total_kw:,.2f} kW")
        c2.metric("Estimasi biaya hari ini", rupiah(total_cost))
        c3.metric("Meter online", f"{sum(1 for c in cards if c[3])} / {len(cards)}")
        st.divider()

        cols = st.columns(3)
        for i, (m, last, today_kwh, online) in enumerate(cards):
            with cols[i % 3].container(border=True):
                st.markdown(f"**{m['tenant']}** &nbsp; {'🟢 online' if online else '🔴 offline'}")
                st.caption(f"Slave {m['slave']} · {m['lokasi'] or '-'}")
                if not last:
                    st.write("Belum ada data.")
                    continue
                a, b = st.columns(2)
                a.metric("Daya", f"{last['kw']:.2f} kW")
                b.metric("Total kWh", f"{last['kwh']:,.2f}")
                a.metric("Hari ini", f"{today_kwh:.2f} kWh")
                b.metric("Biaya hari ini", rupiah(today_kwh * (m["tarif_override"] or tarif)))
                st.caption(f"V: {last['v_a']:.0f}/{last['v_b']:.0f}/{last['v_c']:.0f} V · "
                           f"I: {last['i_a']:.1f}/{last['i_b']:.1f}/{last['i_c']:.1f} A · "
                           f"PF {last['pf']:.2f}")
                st.caption(f"Update: {last['ts']}")
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
                    f"SELECT ts, slave, {metric} AS val FROM readings "
                    f"WHERE ts>=? AND slave IN ({','.join('?' * len(pick))}) ORDER BY ts",
                    con, params=[since, *pick])
            if df.empty:
                st.warning("Belum ada data pada rentang ini.")
            else:
                df["ts"] = pd.to_datetime(df["ts"])
                df["Tenant"] = df["slave"].map(names)
                st.line_chart(df.pivot_table(index="ts", columns="Tenant", values="val"))

# ------------------------------------------------------------------ TAGIHAN
with tab_bill:
    st.subheader("Tagihan listrik per tenant")
    today = date.today()
    c1, c2 = st.columns(2)
    d1 = c1.date_input("Dari tanggal", today.replace(day=1))
    d2 = c2.date_input("Sampai tanggal", today)
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
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.metric("Total seluruh tenant", rupiah(df["Total (Rp)"].sum()))
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

    st.subheader("Koneksi ke meter")
    st.caption("Collector membaca pengaturan ini tiap putaran, tidak perlu restart.")
    conn = st.radio("Tipe koneksi", ["serial", "tcp"], horizontal=True,
                    index=0 if settings["conn_type"] == "serial" else 1,
                    format_func=lambda x: "RS485-USB (serial)" if x == "serial" else "Gateway Modbus TCP")
    s1, s2, s3 = st.columns(3)
    serial_port = s1.text_input("Port serial", settings["serial_port"], help="Windows: COM3, Linux: /dev/ttyUSB0")
    baud = s2.selectbox("Baud rate", [2400, 4800, 9600, 19200], index=[2400, 4800, 9600, 19200].index(int(settings["baud"])) if int(settings["baud"]) in [2400, 4800, 9600, 19200] else 2)
    parity = s3.selectbox("Parity", ["N", "E", "O"], index=["N", "E", "O"].index(settings["parity"]))
    t1, t2, t3 = st.columns(3)
    host = t1.text_input("IP gateway", settings["host"])
    tcp_port = t2.number_input("Port TCP", value=int(settings["tcp_port"]), step=1)
    new_interval = t3.number_input("Interval baca (detik)", value=int(settings["interval"]), min_value=5, step=5)

    if st.button("💾 Simpan pengaturan", type="primary"):
        db.save_settings({"tarif": new_tarif, "ppj_persen": new_ppj, "biaya_admin": new_admin,
                          "conn_type": conn, "serial_port": serial_port, "baud": baud,
                          "parity": parity, "host": host, "tcp_port": int(tcp_port),
                          "interval": int(new_interval)})
        st.success("Tersimpan.")
        st.rerun()

    st.subheader("Daftar meter / tenant")
    st.caption("Slave = alamat Modbus di meter. Tarif override boleh dikosongkan (pakai tarif default).")
    mdf = pd.DataFrame(meters) if meters else pd.DataFrame(
        {"slave": pd.Series(dtype=int), "tenant": pd.Series(dtype=str),
         "lokasi": pd.Series(dtype=str), "tarif_override": pd.Series(dtype=float),
         "aktif": pd.Series(dtype=bool)})
    mdf["aktif"] = mdf["aktif"].astype(bool)
    edited = st.data_editor(mdf, num_rows="dynamic", use_container_width=True, hide_index=True,
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
