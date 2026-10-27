# AGENT_PLAN: Penghitung kendaraan CCTV + Derajat Kejenuhan (DJ) JBH6/2 datar, dengan GUI

Dokumen ini lengkap dan berdiri sendiri. Kerjakan berurutan dari Tahap 1 sampai 6. Jangan menambah fitur di luar dokumen ini.

## 1. Tujuan

Program Python yang membaca stream CCTV publik (m3u8), mendeteksi dan melacak kendaraan, menghitungnya per arah lewat ROI dan garis hitung, mengklasifikasikannya ke kelas PKJI, lalu menghitung Derajat Kejenuhan (DJ) per arah sesuai PKJI 2023 untuk jalan bebas hambatan 6 lajur 2 arah (JBH6/2), alinemen datar. GUI harus memperlihatkan video, ROI, garis, dan hitungan berjalan secara realtime, sehingga pengguna bisa memastikan sistem bekerja dengan benar.

Pengguna adalah mahasiswa/peneliti dengan sumber daya terbatas: komputer biasa (kemungkinan tanpa GPU), tanpa data latih, dan tanpa waktu untuk anotasi gambar.

## 2. Prinsip: jangan over-engineering

- Tanpa database, tanpa web server, tanpa framework konfigurasi, tanpa Docker.
- Tanpa fine-tune model pada tahap ini. Pakai YOLOv8n COCO bawaan.
- Satu file untuk logika (`engine.py`), satu file untuk GUI (`app.py`), satu file untuk tes (`test_engine.py`), satu `rois.json`, dan konfigurasi dependency di `pyproject.toml` dengan lockfile `uv.lock`.
- Hanya library: `ultralytics`, `opencv-python`, `numpy`, `PySide6`, `pytest`.
- Bila ragu antara sederhana dan lengkap, pilih sederhana, lalu catat di README singkat.

## 3. Konteks lokasi

- Kamera: tol KM 51+000, resolusi frame acuan 704x576, ada median di tengah.
- Sisi kanan layar, "Arah Cibitung": kendaraan mendekat ke kamera (koordinat y bertambah).
- Sisi kiri layar, "Arah Cimanggis": kendaraan menjauh dari kamera (koordinat y berkurang).
- Tiap arah dianggap 3 lajur (JBH6/2). Jumlah lajur sisi kiri belum dikonfirmasi pengguna, sehingga dibuat parameter.
- Tiang lampu di median bisa menutupi kendaraan sesaat. Frame kadang berkabut.

## 4. Aturan PKJI 2023 (sudah diverifikasi terhadap dokumen)

Kelas kendaraan JBH: MP (mobil penumpang), KS (kendaraan sedang), BB (bus besar), TB (truk besar). Sepeda motor tidak dihitung di JBH.

Pemetaan dari kelas COCO tanpa fine-tune:

| COCO | Label internal | PKJI |
|---|---|---|
| car (2) | MP | MP |
| bus (5) | BUS | BB, atau KS untuk bagian `(1 - bus_bb)` |
| truck (7) | TRUK | TB sebesar `tb_share`, KS sisanya |
| motorcycle (3) | diabaikan | tidak dihitung |

Parameter `tb_share` (default 0.3) dan `bus_bb` (default 1.0) adalah proporsi dari survei manual pengguna. Ini keterbatasan yang diketahui dan harus ditulis di README.

Langkah hitung, per arah:

1. kend/jam per jenis = jumlah terhitung dalam jendela geser (default 300 detik) x 3600 / panjang jendela.
2. Total kend/jam per arah = MP + BB + KS + TB (setelah pembagian di atas).
3. Pilih EMP dari Tabel 2-6 memakai total kend/jam per arah sebagai kunci (bukan SMP/jam, tidak melingkar):

| Total kend/jam per arah | EMP KS | EMP BB | EMP TB |
|---|---|---|---|
| ≤ 1500 | 1,2 | 1,2 | 1,6 |
| 1501 – 2750 | 1,4 | 1,4 | 2,0 |
| 2751 – 3250 | 1,6 | 1,7 | 2,4 |
| > 3250 | 2,0 | 1,6 | 3,3 |

   EMP MP = 1,0. Nilai BB pada baris terakhir (1,6) memang lebih kecil daripada baris sebelumnya (1,7); itu sesuai dokumen, jangan "diperbaiki".
4. q (SMP/jam) = MP x 1,0 + KS x EMP_KS + BB x EMP_BB + TB x EMP_TB.
5. Kapasitas per arah: C = n x C0 x FCLE, dengan C0 = 2500 SMP/jam/lajur (Tabel 2-2, datar), dan FCLE dari Tabel 2-4 (LLE 3,25 → 0,96; 3,50 → 1,00; 3,75 → 1,03; interpolasi linear antar titik). Default n = 3 dan LLE = 3,50, sehingga C = 7500.
6. DJ = q / C per arah. Batas kinerja: DJ ≤ 0,85 berarti masih baik; DJ > 0,85 berarti rawan; DJ ≥ 1 berarti jenuh.
7. Sebelum `warmup` detik (default 60) terlewati, tampilkan "mengumpulkan data" dan jangan tampilkan DJ.

Implementasi referensi sudah ada di `cctv_dj_jbh.py` (fungsi `emp_for`, `capacity`, `status_text`, kelas `CountEngine`). Pindahkan ke `engine.py` dan tes. Biarkan `cctv_dj_jbh.py` tidak diubah sebagai referensi.

## 5. Aturan hitung (ROI + garis)

Konfigurasi tiap arah di `rois.json`:

```json
{
  "ref_size": [704, 576],
  "rois": {
    "Cibitung":  {"polygon": [[372,215],[500,215],[640,380],[410,380]],
                  "line": [[391,297],[570,297]], "direction": "down"},
    "Cimanggis": {"polygon": [[240,215],[326,215],[286,340],[80,340]],
                  "line": [[161,277],[306,277]], "direction": "up"}
  }
}
```

Koordinat di atas adalah perkiraan visual dari satu screenshot. Pengguna akan mengoreksinya lewat editor di GUI. Jika ukuran frame nyata berbeda dari `ref_size`, skalakan koordinat otomatis.

Aturan:

1. Setiap arah punya ROI sendiri, tidak pernah digabung. Sebuah kendaraan dimiliki oleh ROI tempat ia pertama kali masuk.
2. Titik kontak kendaraan = tengah-bawah kotak deteksi.
3. Garis ditaruh di dalam ROI, kira-kira di tengahnya. Garis didefinisikan dari kiri ke kanan (titik A.x ≤ B.x; GUI menukar bila terbalik). Nilai sisi `s(P) = (Bx-Ax)(Py-Ay) - (By-Ay)(Px-Ax)`. Titik di bawah garis (y lebih besar) bernilai positif.
   - `direction: "down"` dihitung bila `s` berpindah dari ≤0 ke >0 (kendaraan bergerak ke bawah layar).
   - `direction: "up"` dihitung bila `s` berpindah dari >0 ke ≤0.
   - Perpindahan ke arah sebaliknya diabaikan.
   - Perpotongan harus terjadi di dalam ruas garis (proyeksi pada AB antara 0 dan 1).
4. Klasifikasi: voting mayoritas dari label pada semua frame saat kendaraan berada di ROI-nya. Hasil dikunci saat dihitung.
5. Cadangan (fallback): jika track hilang atau keluar ROI tanpa pernah melewati garis, tetapi sudah punya minimal `min_hits` (default 3) frame di ROI dan bergerak sesuai `direction`, hitung saat itu dan tandai `via=fallback`. Tanpa syarat ini, kendaraan yang tertutup tiang atau truk tidak terhitung.
6. Anti-ganda: simpan himpunan `counted_ids` selama sesi. Jangan dihapus ketika track dibuang karena basi. (Uji logika awal menemukan ID yang muncul lagi setelah lebih dari 2 detik terhitung dua kali. Ini wajib diperbaiki.) Himpunan ini hanya dikosongkan oleh tombol Reset.
7. Tiap kejadian hitung dicatat: waktu, arah, kelas, id, `via` (line atau fallback).

## 6. Struktur berkas

```
src/
  engine.py          # logika murni: PKJI, ROI, garis, hitung, ringkasan (tanpa Qt, tanpa OpenCV UI)
  app.py             # GUI PySide6 + pembaca stream + YOLO
  test_engine.py     # pytest untuk engine
  rois.json          # konfigurasi ROI dan garis
  pyproject.toml       # metadata dan dependency proyek
  uv.lock              # versi dependency yang dikunci
  README.md          # cara pakai, maksimal satu layar
  cctv_dj_jbh.py     # skrip lama, jangan diubah (referensi)
  out/               # CSV hasil (dibuat otomatis)
```

## 7. Desain `engine.py`

Pertahankan antarmuka seperti `CountEngine` yang ada, dengan tambahan:

- `__init__(rois, lanes=3, lle=3.5, tb_share=0.3, bus_bb=1.0, window_sec=300, min_hits=3, warmup_sec=60)` dengan `rois` berupa dict nama → `{polygon, line, direction}` dalam piksel.
- `update(dets, now)` dengan `dets = [(track_id, label, conf, (x1,y1,x2,y2))]`. Mengembalikan daftar kejadian hitung baru pada pemanggilan itu (untuk log GUI).
- `summary(roi_name, now)` mengembalikan: jumlah per kelas, kend/jam per kelas, total, EMP, q, C, DJ, status.
- `reset()` mengosongkan hitungan dan `counted_ids`.
- Properti yang dibaca GUI: `tracks` (kotak, status "di luar ROI / di dalam ROI / sudah dihitung", kelas), `cum`, `last_event`, `flash`.
- Fungsi bantu: `emp_for`, `capacity`, `status_text`, `point_in_poly`, `side_of_line`.
- Tulis CSV kejadian (`out/events_*.csv`) dan CSV ringkasan (`out/ringkasan_*.csv`) seperti di skrip lama.
- Gunakan `now` dari parameter, bukan `time.time()` di dalam engine, supaya mudah diuji.

## 8. Desain `app.py` (PySide6, sesederhana mungkin)

Argumen CLI: `--source` (URL m3u8, rtsp, atau file video), `--rois rois.json`, `--lanes 3`, `--lle 3.5`, `--tb-share 0.3`, `--bus-bb 1.0`, `--window 300`, `--warmup 60`, `--model yolov8n.pt`, `--imgsz 640`, `--conf 0.3`, `--device`, `--referer`, `--user-agent`, `--demo`.

Arsitektur thread:

- Thread 1, pembaca stream: ambil frame terus-menerus dari `cv2.VideoCapture`, hanya simpan frame terbaru (buang yang lama), reconnect otomatis bila putus. Untuk file video, putar sesuai FPS aslinya.
- Thread 2, pemroses: ambil frame terbaru, jalankan `YOLO.track(persist=True, tracker=bytetrack, classes=[2,5,7], conf, imgsz)` dengan `track_buffer` 60, ubah hasil menjadi `dets`, panggil `engine.update`, lalu kirim frame beranotasi dan ringkasan ke GUI lewat signal Qt.
- Thread GUI: hanya menggambar. Tidak boleh ada inferensi di thread GUI.

Tata letak jendela:

- Kiri: video CCTV dengan ROI transparan per arah (warna berbeda), garis hitung, kotak kendaraan (abu = di luar ROI, kuning = di dalam ROI belum dihitung, hijau = sudah dihitung + label kelas). ROI dan garis berkedip saat ada hitungan baru, dan muncul teks "+1 KELAS" singkat.
- Kanan atas: satu panel per arah berisi hitungan MP/BUS/TRUK dan total, kend/jam, q, C, DJ, status berwarna (hijau lancar, jingga rawan, merah jenuh).
- Kanan bawah: log kejadian (waktu, arah, kelas, id, via). Tanpa cuplikan gambar (tidak dikerjakan sekarang).
- Bawah: tombol Mulai/Jeda, Reset, Edit ROI, Simpan screenshot; kolom isi `tb_share`, `lanes`, `bus_bb`; label FPS proses dan status stream (terhubung / reconnect).

Mode edit ROI (cukup yang minimum):

- Klik "Edit ROI", pilih arah, lalu klik titik-titik polygon (Enter = selesai, Backspace = undo). Setelah itu klik dua titik untuk garis hitung. Pilih arah gerak ("down" atau "up").
- Titik yang sudah ada bisa diseret dengan mouse.
- Tombol Simpan menulis `rois.json` dalam koordinat piksel frame dengan `ref_size` = ukuran frame sebenarnya.
- Selama mode edit, video tetap berjalan tetapi engine dijeda.

Mode `--demo`: tanpa YOLO dan tanpa jaringan. Mesin deteksi palsu membangkitkan kendaraan sintetis (campuran MP/BUS/TRUK) yang bergerak melintasi tiap ROI sesuai arahnya, di atas frame abu-abu atau file video. Fungsinya agar pengguna dan tes bisa memastikan GUI, ROI, garis, dan hitungan bekerja tanpa stream.

## 9. Tahapan kerja (urut)

**Tahap 1: Mesin hitung (`engine.py` + `test_engine.py`)**
Pindahkan dan perbaiki logika dari `cctv_dj_jbh.py`: tambah garis per arah dengan cek arah, `counted_ids`, mode fallback, dan pengembalian kejadian dari `update`. Tulis tes sesuai bagian 10. Selesai bila `pytest` hijau.

**Tahap 2: Kerangka GUI**
`app.py` dengan thread pembaca, thread pemroses, dan tampilan video. Mulai dengan mode `--demo` agar bisa diuji tanpa stream.

**Tahap 3: Tampilan ROI, garis, dan hitungan**
Gambar ROI, garis, kotak kendaraan berwarna, kedipan, panel statistik, dan log kejadian.

**Tahap 4: Editor ROI dan garis**
Gambar, geser, simpan ke `rois.json`, muat ulang.

**Tahap 5: Stream nyata dan ketahanan**
Hubungkan ke m3u8: header `--referer` dan `--user-agent`, reconnect otomatis, dan penanda jam yang datanya hilang di log (jangan diam-diam menghitung jam yang bolong). Uji dengan file video lokal bila stream tidak bisa diakses dari lingkungan Anda, dan katakan dengan jujur bila stream nyata tidak sempat diuji.

**Tahap 6: Dokumentasi dan serah-terima**
`README.md` satu layar: instalasi, cara menjalankan, arti warna, cara menggambar ROI, cara menyetel `tb_share`, keterbatasan, dan cara validasi manual.

## 10. Kriteria penerimaan (harus lulus sebelum dinyatakan selesai)

Tes otomatis di `test_engine.py` (pakai deteksi tiruan, tanpa YOLO):

1. `emp_for` benar di batas: 1500 → (1,2;1,2;1,6); 1501 → (1,4;1,4;2,0); 3000 → (1,6;1,7;2,4); 4000 → (2,0;1,6;3,3).
2. `capacity(3, 3.5) == 7500`; `capacity(3, 3.25) == 7200`; `capacity(3, 3.75) == 7725`.
3. Contoh q: 48 MP, 12 BB, 16,8 KS, 7,2 TB per jam (total 84) → q ≈ 94,08 dan DJ ≈ 0,0125 pada C = 7500.
4. Titik di median (antara kedua ROI) tidak masuk ROI mana pun.
5. Kendaraan yang melintasi garis ke arah yang benar terhitung tepat satu kali. Ke arah sebaliknya tidak terhitung.
6. ID yang sama yang hilang lebih dari 2 detik lalu muncul lagi tidak terhitung dua kali.
7. Kendaraan yang menghilang di tengah ROI setelah `min_hits` frame terhitung satu kali dengan `via=fallback`. Kendaraan dengan kurang dari `min_hits` frame tidak terhitung.
8. Voting kelas: bila 5 frame berlabel TRUK dan 1 frame BUS, hasilnya TRUK.
9. Kedua ROI menghitung terpisah: kendaraan di ROI Cibitung tidak menambah hitungan Cimanggis.
10. DJ bernilai kosong ("mengumpulkan data") sebelum `warmup`.

Uji GUI manual (pengguna atau agent dengan `QT_QPA_PLATFORM=offscreen`):

11. `python app.py --demo` membuka jendela, ROI dan garis terlihat, hitungan naik saat kendaraan sintetis melewati garis, dan warna kotak berubah abu → kuning → hijau.
12. Mode edit: menggeser satu titik lalu menyimpan mengubah `rois.json` dan ROI baru dipakai setelah dimuat ulang.
13. Menutup stream (file video habis atau URL salah) tidak membuat program crash; status tampil sebagai "reconnect" atau "selesai".
14. CSV kejadian dan ringkasan terbentuk di `out/` dan isinya cocok dengan tampilan GUI.

## 11. Keterbatasan yang harus dicantumkan di README

- COCO tidak membedakan KS dan TB, dan tidak membedakan bus sedang dan bus besar. Hasil DJ bergantung pada `tb_share` dan `bus_bb` dari survei manual (saran: hitung manual 30 menit dari rekaman). Cara aman tambahan: laporkan rentang DJ dengan semua truk dianggap KS (batas bawah) dan semua truk dianggap TB (batas atas).
- Kendaraan besar bisa menutupi mobil di belakangnya sehingga hitungan MP cenderung kurang. Tiang median bisa memutus ID sesaat.
- kend/jam diekstrapolasi dari jendela pendek (default 5 menit), jadi sangat berfluktuasi. Untuk analisis resmi, gunakan arus jam puncak yang direkam cukup lama (minimal 1 jam atau beberapa interval 15 menit) dan validasi dengan hitung manual 15 menit per kelas.
- Akurasi turun saat malam, hujan, dan kabut.
- Koordinat ROI dan garis bawaan hanyalah perkiraan awal dan harus dikoreksi di frame nyata.
- Stream CCTV publik biasanya punya syarat penggunaan. Untuk kajian resmi, sebaiknya minta izin ke pengelola jalan.

## 12. Di luar cakupan (jangan dikerjakan)

Fine-tune model, klasifikasi berdasar panjang kendaraan, sepeda motor, versi web, cuplikan gambar per kendaraan, kecepatan tempuh (vB, vMP), tipe alinemen selain datar, JBH selain 6/2, dan prediksi pertumbuhan lalu lintas.

## 13. Serah-terima

Setelah selesai, laporkan singkat: berkas apa saja yang dibuat, hasil `pytest`, bagian GUI mana yang benar-benar diuji dan mana yang belum (terutama stream nyata), serta daftar keterbatasan yang tersisa. Jangan menyatakan sesuatu "sudah berjalan" bila belum diuji.
