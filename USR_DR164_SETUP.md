# USR-DR164 → Acrel ADL400 → Python (tanpa ESP32)

Status: implementasi software sudah disiapkan; **belum diuji pada gateway fisik**.
Jangan gunakan pembacaan untuk penagihan sebelum angka kWh cocok dengan display meter
dan register map/rasio CT/PT telah diverifikasi.

## Alur dan isolasi risiko

- Meter Acrel ADL400/ADL400-D/ADL200 menggunakan **RS485 Modbus RTU**.
- Gateway **PUSR USR-DR164** mengonversi Modbus TCP pada Wi-Fi menjadi Modbus RTU.
- Python `usr_dr164_modbus.py` melakukan **uji baca saja tanpa mengimpor/menulis SQLite**.
- Jika pengujian berhasil, `collector.py` **yang sudah ada** bisa menggunakan mode
  `tcp` pada dashboard dan menyimpan data `readings` melalui API DB yang ada.
- `app.py`, `esp32_receiver.py`, `billing.py`, dan tabel historis tidak perlu diubah.

> Pembacaan dari gateway bukan HTTP POST ESP32: jangan mengirim paket langsung
> ke endpoint `/api/esp32/readings`. HTTP receiver ESP32 tetap ada untuk opsi lama.

## Persyaratan instalasi

**Teknisi listrik yang kompeten** harus memverifikasi keselamatan, isolasi
galvanik, proteksi surge, catu daya dan pemasangan RS485 di panel.
Jangan hubungkan ground RS485 ke netral PLN. Jangan asumsikan RS485 gateway
sudah terisolasi hanya karena perangkat dipasarkan sebagai industrial.

- ADL400: terminal **21/22** sesuai label RS485 meter; verifikasi polaritas A/B
  dengan manual perangkat dan label gateway fisik.
- USR-DR164: gunakan **adaptor DC sesuai label perangkat** (manual menyebut
  rentang 5–36 V DC; suplai 12 V DC sesuai spesifikasi adalah opsi praktis).
- Jangan hubungkan jalur listrik `UA/UB/UC/UN` ke port RS485 gateway.
- Gunakan router/hotspot tepercaya, pastikan laptop dan gateway bisa saling
  menjangkau (client isolation/AP isolation tidak aktif).
- Jaringan Modbus TCP tidak terenkripsi; jangan port-forward ke internet.
  Gunakan segmentasi jaringan/VPN bila diperlukan.

## Setel USR-DR164 melalui web konfigurasi perangkat

Berdasarkan manual resmi PUSR, bagian **Serial Setting / Net Setting**:

| Pengaturan | Nilai awal untuk meter uji |
| --- | --- |
| Work Mode | **STA** (gateway tersambung ke router/hotspot) |
| Serial baud rate | **9600** |
| Data bits | **8** |
| Parity | **None** |
| Stop bits | **1** |
| ModBUS Enabled | **Protocol Conversion**, **bukan** OFF atau Multi Host Polling |
| Socket | **Socket A** (fitur Modbus conversion hanya di Socket A) |
| Socket A Protocol | **TCP Server** |
| TCP Port | Contoh **8899**, sesuaikan port yang benar-benar diatur |
| Register slave ID | **39** (di meter ADL400, bukan di Wi-Fi gateway) |

Gunakan IP LAN yang didapat dari DHCP/router atau IP statis yang valid.
Contoh `192.168.1.80` di bawah **hanya placeholder**, bukan IP gateway nyata.

Manual resmi:
https://www.pusr.com/uploads/20260108/b3e69e40904adb82d6cb31cfbebbcc36.pdf

## Tahap A: uji baca tanpa database

Di PowerShell, dari folder proyek lokal:

```powershell
cd D:\Adl_Monitor\adl400-monitor
python -m pip install -r requirements.txt
python usr_dr164_modbus.py --host 192.168.1.80 --port 8899 --slave 39 --model ADL400
```

Uji ini mengambil **kWh (0x0000, 2 register) dan tegangan fasa A (0x0061)**
sebagai kandidat data. Keduanya harus menghasilkan frame Modbus TCP valid
dengan transaction ID, protocol ID, unit/slave ID, function code dan jumlah
register yang cocok. Jika satu saja gagal, exit code nonzero dan data tidak disimpan.

Setelah hasil kandidat cocok dengan layar ADL400, uji semua field:

```powershell
python usr_dr164_modbus.py --host 192.168.1.80 --port 8899 --slave 39 --model ADL400 --full
```

Untuk ADL200 pilih `--model ADL200`. Untuk ADL400-D pilih `--model ADL400-D`.
Peta register pada `modbus.py` harus cocok dengan **unit fisik/firmware**
dan rasio CT/PT meter. Angka masuk akal saja tidak membuktikan mapping benar.

**Uji ini tidak mengakses, membuat atau mengubah `monitoring.db`**, sekalipun
gateway tidak dapat diakses atau registrasi meter di dashboard belum tersedia.

## Tahap B: backup database sebelum aktivasi kolektor

Tutup semua proses kolektor lama. Gunakan jalur database lokal yang sama dengan
dashboard, lalu buat backup konsisten menggunakan SQLite API, misalnya:

```powershell
cd D:\Adl_Monitor\adl400-monitor
python -c "import sqlite3; s=sqlite3.connect('monitoring.db'); b=sqlite3.connect('monitoring_backup_before_usr_dr164.db'); s.backup(b); b.close(); s.close()"
```

Jangan menimpa file backup yang sudah ada. Periksa lokasi `ADL400_DB` jika
database sebenarnya disimpan di path lain. Backup ini contoh untuk file DB lokal,
**bukan** untuk Streamlit Community Cloud.

## Tahap C: aktifkan kolektor yang sudah ada

Hanya setelah *Tahap A* berhasil, hasil dibandingkan meter, dan backup tersedia:

1. Buka `streamlit run app.py` pada PC yang menyimpan SQLite.
2. Pilih **Live → Pengaturan → Koneksi ke meter → Gateway Modbus TCP**.
3. Isi **IP gateway** dan **Port TCP** yang sama dengan pengujian.
4. Pastikan meter **Slave 39 / ADL400 / Aktif** sudah terdaftar, dan daftar
   tenant/model tidak berubah tanpa persetujuan.
5. Simpan konfigurasi. Perubahan mode adalah keputusan operator; tidak dilakukan
   otomatis oleh skrip diagnostik.
6. **Jalankan tepat satu** kolektor: `python collector.py --once`.
   Periksa log `[OK]` dan angka di Live; lalu jalankan
   `python collector.py` untuk polling berkala ketika benar-benar siap.
7. Jangan jalankan kolektor serial lama atau receiver ESP32 secara paralel
   untuk meter yang sama ketika gateway yang baru diaktifkan.

Mode `tcp` menggunakan tabel lama `readings` dengan snapshot tarif source
`serial` agar dashboard dan billing lama tetap bekerja. Baris lama **tidak
dihapus dan tidak dihitung ulang**, tetapi pastikan nomor slave yang sama
mewakili meter fisik yang sama; jangan gabungkan histori dua meter berbeda.
Data ESP32 di `esp32_real_readings` tetap disimpan terpisah dan tidak
otomatis dipindahkan/ditampilkan saat mode TCP dipilih.

**Khusus uji awal:** jangan aktifkan penagihan otomatis sebelum minimal beberapa
pembacaan valid berturut-turut menunjukkan kWh konsisten dengan layar meter
dan konversi CT/PT tepat.

## Diagnosis singkat

| Pesan | Periksa |
| --- | --- |
| Connection refused/timeout | IP Wi-Fi, port TCP Socket A, firewall, TCP Server |
| Protocol ID/frame mismatch | Gateway belum disetel `Protocol Conversion`; mode transparent TCP berbeda |
| Slave ID mismatch | ID meter, gateway, atau respons tidak sesuai request |
| Modbus exception | Fungsi/register tidak didukung versi meter tersebut |
| kWh beda dari LCD | Register map, skala, CT/PT, model perangkat atau total energi yang dibandingkan |

## Tes otomatis (tanpa perangkat)

```powershell
python -m unittest -v test_usr_dr164_modbus
```

Tes memakai socket palsu yang memecah balasan menjadi beberapa potongan,
mensimulasikan frame salah/exception/terputus, serta memastikan uji read-only
tidak memanggil database.
