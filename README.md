# Monitoring Listrik Tenant – Acrel ADL400

Satu aplikasi **Streamlit** dengan dua mode:
- **Demo · simulasi** (default): menampilkan contoh enam tenant, tren daya, dan estimasi tagihan. Tidak memerlukan meter atau collector, dan tidak menyimpan data ke database live.
- **Live · meter asli**: membaca SQLite yang diisi oleh `collector.py`. Memiliki halaman Live, Grafik, Tagihan, dan Pengaturan.

## Jalankan
```bash
pip install -r requirements.txt
streamlit run app.py
```

Untuk pembacaan meter sungguhan, jalankan collector di komputer/gateway yang dapat mengakses perangkat Modbus dan pastikan file database (`ADL400_DB`) sama serta dapat diakses oleh aplikasi Live. Deploy Streamlit Cloud tanpa collector hanya akan menampilkan data nyata bila database hasil pembacaan memang tersedia di lingkungan aplikasi.

## Streamlit Community Cloud
- Branch: `main`
- Main file path: **`app.py`**
- Mode default: **Demo**. Beralih ke Live melalui sidebar.

> Data simulasi bukan data meter lapangan. Tarif, tenant, kapasitas dan tagihan dalam mode Demo hanya contoh.
