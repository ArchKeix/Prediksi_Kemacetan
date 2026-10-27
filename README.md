# Penghitung Kendaraan CCTV — JBH6/2

Aplikasi desktop Python untuk mendeteksi dan melacak kendaraan dari video/CCTV, menghitung kendaraan per arah menggunakan ROI dan counting line, lalu memperkirakan arus `q` dan derajat kejenuhan (DJ) untuk JBH6/2.

> Hasil adalah estimasi. Model COCO tidak mengklasifikasikan kendaraan persis menurut PKJI, sehingga hasil perlu divalidasi dengan hitung manual. Baca bagian [Keterbatasan](#keterbatasan-dan-validasi) sebelum memakai hasil untuk laporan.

## 1. Persyaratan

- Windows 10/11.
- Python 3.11 atau lebih baru.
- [`uv`](https://docs.astral.sh/uv/) untuk mengelola environment dan dependency.
- Untuk CCTV online: koneksi internet dan URL stream yang masih aktif.
- Model YOLO yang tersedia di folder `src/` (contohnya `yolov8n.pt`).

Instal `uv` bila belum ada:

```powershell
pip install uv
```

## 2. Instalasi dan menjalankan

Buka PowerShell/terminal pada root repository, lalu masuk ke folder aplikasi:

```powershell
cd src
uv sync
```

`uv sync` membuat environment dan memasang dependency sesuai `pyproject.toml`/`uv.lock`. Jalankan demo tanpa koneksi CCTV:

```powershell
uv run python app.py --demo --model yolov8n.pt --rois rois.json
```

Jalankan dengan file video lokal:

```powershell
uv run python app.py --source "C:\path\ke\video.mp4" --model yolov8n.pt --rois rois.json
```

Jalankan dengan CCTV HLS/M3U8:

```powershell
uv run python app.py --source "https://alamat-stream/index.m3u8" --model yolov8n.pt --rois rois.json
```

Contoh URL yang pernah dipakai pada proyek (aksesnya dapat berubah sewaktu-waktu):

```powershell
uv run python app.py --source "https://jmlive.jasamarga.com/hls/2/bf81454d-3459-4935-b878-4012b567edea/index.m3u8" --model yolov8n.pt --rois rois.json
```

Pastikan terminal berada di `src` saat menjalankan perintah di atas. Jalur `rois.json`, file model relatif, dan folder output dihitung dari folder kerja tersebut.

## 3. Opsi perintah

Opsi yang paling umum:

| Opsi | Default | Keterangan |
|---|---:|---|
| `--source` | kosong | URL M3U8/RTSP atau jalur file video. Wajib kecuali memakai `--demo`. |
| `--demo` | mati | Menjalankan simulasi tanpa stream CCTV. |
| `--rois` | `rois.json` | File konfigurasi polygon ROI dan counting line. |
| `--model` | `yolo26s.pt` | File model YOLO. Contoh: `yolov8n.pt`. |
| `--imgsz` | `640` | Ukuran input inferensi YOLO. Nilai lebih besar dapat membantu objek kecil tetapi lebih berat. |
| `--conf` | `0.3` | Ambang confidence deteksi. |
| `--device` | otomatis | Perangkat inferensi, misalnya `cpu` atau indeks GPU yang didukung Ultralytics. |
| `--lanes` | `3` | Jumlah lajur per arah untuk perhitungan kapasitas. |
| `--lle` | `3.5` | Lebar lajur efektif (meter). |
| `--tb-share` | `0.3` | Proporsi kelas COCO `truck` yang diasumsikan TB; sisanya KS. Nilai survei manual lebih baik. |
| `--bus-bb` | `1.0` | Proporsi kelas COCO `bus` yang diasumsikan BB; sisanya KS. |
| `--window` | `300` | Jendela hitungan dalam detik untuk estimasi arus per jam. `300` berarti 5 menit. |
| `--warmup` | `60` | Detik pengumpulan data sebelum DJ ditampilkan. |
| `--stitch-sec` | `1.5` | Rentang waktu untuk mencoba menyambungkan track yang ID-nya berganti. |
| `--no-crop` | mati | Menonaktifkan crop area deteksi dan memproses seluruh frame. |
| `--referer` | kosong | Referer opsional untuk sumber stream tertentu. |
| `--user-agent` | kosong | User-Agent opsional untuk sumber stream tertentu. |

Contoh menjalankan di CPU dengan jendela 5 menit:

```powershell
uv run python app.py --source "C:\video.mp4" --model yolov8n.pt --device cpu --window 300 --warmup 60
```

## 4. Menggunakan aplikasi

- **Mulai/Jeda**: menghentikan atau melanjutkan pemrosesan/inferensi. Pembaca stream tetap berjalan saat pemrosesan dijeda.
- **Reset**: mengosongkan hitungan dan ID yang sudah dihitung untuk sesi berjalan.
- **Simpan screenshot**: menyimpan gambar tampilan ke `src/out/screenshot.png` jika aplikasi dijalankan dari folder `src`.
- **Simpan ROI**: menulis polygon, counting line, dan arah ke file ROI yang sedang dipakai.
- **Panel statistik**: menampilkan hitungan, estimasi kend/jam, `q`, kapasitas `C`, DJ dan status per ROI/arah.
- **Log kejadian**: mencatat waktu, arah, kelas deteksi, ID track, dan cara hitung (`line` atau `fallback`).

Warna bounding box:

- Abu-abu: di luar ROI.
- Kuning: berada di ROI, belum dihitung.
- Hijau: sudah dihitung.

## 5. Mengatur ROI dan counting line

ROI dan garis awal berada di `src/rois.json` (atau `rois.json` jika terminal berada di `src`). Koordinat bawaan disiapkan untuk frame kamera 640×480 dan hanya perkiraan; sesuaikan dengan kamera yang digunakan.

### Arti ROI dan garis hitung

- **ROI (polygon)** adalah area untuk melacak kendaraan dan mengumpulkan prediksi kelas. Masuk ROI tidak menambah hitungan.
- **Counting line** adalah garis hitung di dalam ROI. Kendaraan dihitung satu kali saat titik tengah-bawah bounding box melintasi garis ke arah yang ditetapkan.
- Kendaraan yang keluar ROI tidak otomatis dihitung lagi. ID yang sudah dihitung ditahan agar tidak terjadi hitung ganda.
- Fallback dapat menghitung track yang hilang sebelum mencapai garis jika syarat engine terpenuhi; event ditandai `fallback`.

### Arah gerak

Arah `up/down` mengacu pada koordinat gambar, bukan arah mata angin:

- `up`: kendaraan bergerak ke bagian atas gambar; nilai koordinat `y` mengecil.
- `down`: kendaraan bergerak ke bagian bawah gambar; nilai koordinat `y` membesar.

Konfigurasi awal kamera saat ini:

- `Arah_Kiri`: `up`.
- `Arah_Kanan`: `down`.

Jika kamera di-flip atau sudut pandangnya berubah, periksa dan sesuaikan arah tersebut.

### Mengedit dari GUI

1. Jalankan aplikasi dan tunggu frame tampil.
2. Klik **Edit ROI**. Pemrosesan dijeda agar titik lebih mudah diedit.
3. Pilih arah/ROI pada dropdown **ROI**.
4. Untuk memindahkan titik polygon, klik-tahan titik kontrol lalu drag.
5. Untuk menambahkan titik polygon, pilih mode **Polygon**, klik titik baru, lalu tekan **Enter** untuk mengakhiri penambahan titik. **Perhatian:** klik di area kosong menambahkan titik ke polygon yang ada; jangan klik sembarang jika hanya ingin memindahkan titik yang sudah ada.
6. Untuk counting line, pilih mode **Garis hitung**. Jika garis sudah ada, drag endpoint hijau untuk memindahkannya. Jika belum ada/lengkap, klik dua titik untuk membuat garis.
7. Pilih arah `up` atau `down` pada dropdown **Arah**.
8. Klik **Simpan ROI**.
9. Klik **Edit ROI** lagi untuk melanjutkan pemrosesan.

Sebelum survei, pastikan polygon mencakup lajur yang dihitung, tidak mencakup median/gore atau jalur lain, dan counting line melintasi jalur yang benar. Counting line sebaiknya berada pada bagian gambar tempat kendaraan sudah cukup jelas terdeteksi dan belum terpotong tepi frame.

## 6. Cara kerja klasifikasi dan perhitungan

Model COCO bawaan tidak memiliki kelas PKJI `MP`, `KS`, `BB`, `TB`. Pemetaan yang digunakan:

| Kelas model COCO | Perlakuan aplikasi |
|---|---|
| `car` | MP |
| `bus` | BUS, dibagi menjadi BB/KS memakai `bus_bb` |
| `truck` | TRUK, dibagi menjadi TB/KS memakai `tb_share` |
| `motorcycle` | Diabaikan untuk JBH |

Contoh `tb_share=0.3` berarti 30% hitungan `truck` dialokasikan ke TB dan 70% ke KS. Itu **asumsi proporsi**, bukan pengenalan jenis tiap truk. Sesuaikan berdasarkan sampel manual, dan nyatakan asumsi ini dalam laporan.

Volume hasil hitung diekstrapolasi dari jendela pengamatan ke kend/jam. Aplikasi lalu mengonversi komposisi kendaraan memakai EMP PKJI dan menghitung:

```text
q  = arus dalam SMP/jam
C  = kapasitas berdasarkan lajur dan lebar lajur efektif
DJ = q / C
```

Parameter kapasitas bawaan ditujukan untuk JBH6/2 datar dengan 3 lajur per arah dan lebar lajur efektif 3,50 m. Pastikan tipe jalan, jumlah lajur, lebar lajur, alinemen, dan EMP memang sesuai lokasi. Jangan gunakan hasil bawaan untuk tipe jalan/kondisi lain tanpa menyesuaikan parameter dan metode PKJI.

## 7. Output

Saat aplikasi ditutup normal, CSV ditulis ke folder `out/` relatif terhadap folder kerja (biasanya `src/out/`):

- `events.csv`: kejadian hitung per kendaraan/track.
- `ringkasan.csv`: akumulasi hitungan per arah dan kelas.

Jika aplikasi crash atau proses dihentikan paksa, file mungkin belum ditulis. Salin atau arsipkan output sebelum menjalankan eksperimen baru jika ingin mempertahankan hasil sebelumnya.

## 8. Troubleshooting

### Aplikasi tidak menemukan `rois.json` atau model

Pastikan perintah dijalankan dari folder `src`:

```powershell
cd src
uv run python app.py --demo --model yolov8n.pt --rois rois.json
```

### Tidak ada kendaraan yang terhitung

- Pastikan titik tengah-bawah bbox benar-benar berada dalam polygon ROI.
- Pastikan kendaraan melintasi counting line di dalam segmen garis, bukan di luar ujungnya.
- Periksa arah `up/down`.
- Periksa bahwa frame kamera sesuai resolusi/koordinat ROI.
- Coba `--conf 0.2` atau `--imgsz 960` bila kendaraan kecil sulit dideteksi; inferensi dapat menjadi lebih lambat.
- Uji dahulu dengan `--demo` untuk memastikan mekanisme hitung berjalan.

### Stream putus, timeout, atau layar berhenti

URL HLS dapat aktif sesaat lalu timeout, berubah, atau membatasi akses. Coba buka URL dari jaringan yang sama dan jalankan file video lokal untuk membedakan masalah stream dari masalah aplikasi. Log OpenCV seperti `Stream timeout`, error decode H.264, atau gagal mengambil frame biasanya berkaitan dengan stream/koneksi/backend FFmpeg; jika berulang, simpan waktu kejadian dan URL (tanpa credential) untuk investigasi. Jangan menganggap timeout sebagai arus nol—data selama koneksi terputus bukan hasil survei yang valid.

### GUI tidak terbuka di server/headless

Aplikasi memakai GUI desktop Qt. Jalankan pada desktop Windows yang memiliki sesi grafis; `QT_QPA_PLATFORM=offscreen` hanya untuk pengujian tertentu, bukan penggunaan normal.

## 9. Keterbatasan dan validasi

- COCO tidak membedakan KS dari TB atau bus sedang dari bus besar. `tb_share` dan `bus_bb` sangat memengaruhi komposisi dan estimasi `q`.
- Kendaraan dapat tertutup kendaraan besar atau objek median; tracking dapat kehilangan ID, fallback dapat mengurangi tetapi tidak menghilangkan kesalahan.
- Bbox dan perspektif kamera tidak cukup untuk mengukur panjang kendaraan PKJI secara akurat. Jangan menafsirkan ukuran bbox mentah sebagai panjang kendaraan.
- Hitungan pada jendela 5 menit diekstrapolasi menjadi kend/jam dan dapat berfluktuasi. Untuk analisis, gunakan periode yang representatif—misalnya interval 15 menit atau satu jam—dan validasi dengan hitung manual pada video yang sama.
- Akurasi dapat turun pada malam hari, hujan, kabut, blur, atau resolusi rendah.
- Aplikasi menghitung DJ untuk konfigurasi JBH6/2 datar; hasil bukan pengganti survei atau analisis teknik resmi.
- Pastikan memiliki izin menggunakan stream CCTV dan mematuhi syarat penyedia.

## 10. Menjalankan test

Dari folder root proyek:

```powershell
cd src
uv run pytest -q
```

Test engine tidak memerlukan CCTV atau inferensi YOLO.
