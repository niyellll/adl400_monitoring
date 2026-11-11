# Monitoring Listrik Tenant – Acrel ADL200 / ADL400 / ADL400-D

Satu aplikasi **Streamlit** dengan dua mode:
- **Demo · simulasi** (default): menampilkan contoh tujuh tenant, tren daya, dan estimasi tagihan. Tidak memerlukan meter atau collector, dan tidak menyimpan data ke database live.
- **Live · meter asli**: membaca SQLite yang diisi oleh `collector.py`. Memiliki halaman Live, Grafik, Tagihan, dan Pengaturan.

## Tipe meter / model perangkat

Di **Live → Pengaturan → Daftar meter / tenant**, pilih **Model Meter** untuk setiap slave (pilihan terpisah dari jenis tarif tenant).

- **ADL200**: 1 fase, kWh register `0x0000` (2 register), tegangan `0x000B`, arus `0x000C`, daya `0x000D`, PF `0x0010`. Fase L2/L3 disimpan `NULL`, tidak direkayasa menjadi nol.
- **ADL400**: 3 fase, memakai map keluarga ADL400 sesuai manual. Konfirmasi alamat/skala, versi firmware, rasio CT/PT, dan jumlah fase pada meter sebenarnya sebelum dipakai untuk tagihan.
- **ADL400-D**: 3 fase, menggunakan peta yang sebelumnya terbukti merespons pada pengujian COM10 slave 31. Pilihan default untuk meter lama agar data historis tidak berubah.

Pembaca `collector.py` menggunakan model setiap tenant untuk memilih register. Perubahan model **tidak** menghitung ulang data lama. Label per meter juga masuk ke laporan Excel tagihan. Pengujian model bisa dilakukan tanpa perangkat: `python -m unittest -v test_meter_models`.

**Penting:** model perangkat tidak sama dengan skema penagihan. Semua model dapat dipilih sebagai tarif tunggal atau WBP/LWBP di software; ini tidak berarti fitur multi-tarif fisik tersedia pada setiap unit. Untuk ADL200 (1 fase), kolom L2/L3 memang tidak berlaku. Jika mengubah model saat menggunakan slave yang sama, verifikasi identitas meter serta kontinuitas register kWh agar histori dan tarif tidak tercampur. Jangan hubungkan listrik panel tanpa teknisi berwenang.

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

## ESP32 Wi-Fi (HTTP) — SQLite lokal (pembacaan REAL)

Opsi ketiga tersedia di **Live → Pengaturan → Koneksi ke meter → ESP32 Wi-Fi (HTTP)**.
Alur: ADL400 (Modbus RTU RS485) → transceiver RS485-TTL yang kompatibel 3,3 V → ESP32 → hotspot/router → `esp32_receiver.py` (laptop/mini PC) → SQLite lokal → dashboard Live.

**Penting:** Firmware pengirim contoh `{"kwh":123.45,"jenis":"SIMULASI"}` dari latihan sebelumnya *bukan* pembacaan meter. Firmware ESP32 harus terlebih dahulu membaca register Modbus ADL400 yang diverifikasi sesuai model dan manual yang benar. Contoh simulasi tidak diterima penerima REAL. Jangan hubungkan meter ke tegangan listrik tanpa teknisi listrik berwenang; verifikasi tegangan logika dan isolasi RS485.

### Persiapan laptop Windows

1. Jalankan dashboard **lokal** menggunakan `streamlit run app.py`, pilih **Live**, kemudian di **Pengaturan** tambahkan meter/tenant dengan slave Modbus aktual (misalnya 1), centang Aktif, dan simpan. Pilih **ESP32 Wi-Fi (HTTP)**, lalu simpan.
2. Pastikan penerima dan dashboard memakai **file database yang sama**. Contoh ketika aplikasi ada pada `D:\Adl_Monitor\adl400-monitor`:
   ```bat
   cd /d D:\Adl_Monitor\adl400-monitor
   set ADL400_DB=D:\Adl_Monitor\adl400-monitor\monitoring.db
   set ADL400_ESP32_TOKEN=GANTI_DENGAN_TOKEN_ACAK_PANJANG_MINIMAL_24_KARAKTER
   python -u esp32_receiver.py
   ```
   Jalankan `streamlit run app.py` dari **CMD kedua** yang juga menetapkan `ADL400_DB` ke jalur identik. Token rahasia disetel juga pada firmware ESP32 melalui header `X-Device-Token`. **Jangan commit token atau password Wi-Fi ke GitHub.**
3. Server penerima membuka port **5001** (bukan 5000 milik server simulasi terdahulu). Izinkan akses hanya dari ESP32 pada jaringan tepercaya; koneksi lokal menggunakan HTTP tanpa enkripsi. Untuk penggunaan lintas internet gunakan HTTPS/VPN dan autentikasi pada endpoint; jangan port-forward ke internet.
4. Firmware ESP32 POST ke `http://IP_LAPTOP:5001/api/esp32/readings` dengan header `Content-Type: application/json` dan `X-Device-Token: <token>`. Isi payload yang berasal dari hasil **pembacaan meter asli**, misalnya struktur ini (angka sengaja tidak diberikan sebagai data nyata):
   ```json
   {
     "device": "ESP32",
     "jenis": "REAL",
     "slave": 1,
     "kwh": null,
     "kw": null,
     "v_a": null, "v_b": null, "v_c": null,
     "i_a": null, "i_b": null, "i_c": null,
     "pf": null
   }
   ```
   Ganti `kwh: null` dengan angka numerik kumulatif **hasil meter**, bukan data contoh; kolom lain boleh `null` bila register belum terverifikasi. Request dengan `kwh: null` akan ditolak.
5. Respons server **200** berarti pembacaan tersimpan. Respons **401** token salah, **409** pilih mode ESP32 di dashboard, **422** slave belum terdaftar/aktif, **400** payload tidak valid.

Pembacaan ESP32 disimpan pada tabel khusus `esp32_real_readings`. Grafik dan Tagihan Live memilih tabel sesuai mode, sehingga simulasi dari `esp32_test.db` **tidak tercampur** dengan penagihan. File `esp32_test.db` dari latihan tetap terpisah.

**Batasan deploy:** Streamlit Community Cloud menggunakan filesystem sementara dan tidak dapat membaca SQLite di laptop secara langsung. Mode Live pada Cloud memerlukan infrastruktur database persisten dan koneksi terproteksi tersendiri; fitur ini dirancang pertama untuk laptop/mini PC di lokasi. Pertahankan SQLite lokal, lakukan backup berkala. Jangan menjalankan `collector.py --demo` pada database tagihan nyata.
