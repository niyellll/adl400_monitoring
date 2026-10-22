# Monitoring kWh Meter Acrel ADL400 (Tenant Mall)

Dashboard Streamlit untuk memantau kWh meter Acrel ADL400 via Modbus (RS485),
lengkap dengan perhitungan biaya dan tagihan per tenant.

```
Meter ADL400 --RS485--> Konverter USB / Gateway --> collector.py --> monitoring.db <-- app.py (Streamlit)
```

## Fitur
- Live: daya (kW), tegangan, arus, PF, kWh, estimasi biaya hari ini, status online/offline
- Grafik riwayat per tenant
- Tagihan per periode: (kWh akhir - kWh awal) x tarif + PPJ + biaya admin, ekspor CSV/Excel
- Tarif, koneksi, dan daftar tenant bisa diatur dari dashboard
- Mode demo tanpa alat

## Instalasi
```bash
pip install -r requirements.txt
```

## Coba dulu tanpa alat (demo)
```bash
python collector.py --demo      # terminal 1 (isi data simulasi)
streamlit run app.py            # terminal 2
```
Buka tab **Pengaturan**, tambahkan meter (slave 1, 2, 3...), lalu lihat tab Live.

## Pakai meter asli
1. Sambungkan RS485 paralel: A ke A, B ke B di semua meter. Beri tiap meter alamat (slave) berbeda.
2. Di tab **Pengaturan** isi port serial (atau IP gateway), baud rate, dan daftar meter. Samakan dengan setting meter.
3. **Verifikasi peta register** di `modbus.py` (`FIELDS`) dengan manual Modbus ADL400 milikmu.
   Untuk membantu, dump register mentah:
   ```bash
   python collector.py --probe 1 0 130     # slave 1, mulai alamat 0, 130 register
   ```
4. Jalankan `python collector.py` (biarkan menyala terus; bisa dijadikan service / Task Scheduler / systemd).
5. Jalankan `streamlit run app.py`.

## Catatan
- Streamlit Community Cloud **tidak bisa** membaca serial/RS485 lokal. Collector dan dashboard harus berjalan di PC/mini PC di lokasi (atau collector di lokasi dan database dipindah ke server bersama).
- Database `monitoring.db` jangan di-commit ke GitHub (sudah ada di `.gitignore`).
- Cadangkan `monitoring.db` secara rutin karena menjadi dasar tagihan.
- Untuk tagihan resmi, cocokkan dulu angka awal/akhir dengan pembacaan fisik meter.
