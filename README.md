# Prediksi Kemacetan

Aplikasi penghitung kendaraan dan analisis tingkat kejenuhan jalan berbasis CCTV untuk DJ JBH6/2.

## Menjalankan aplikasi

Masuk ke folder aplikasi terlebih dahulu (Python 3.11+ dan [uv](https://docs.astral.sh/uv/)):

```sh
cd src
uv sync
uv run python app.py --demo
uv run python app.py --source "URL-m3u8-atau-file.mp4"
```

ROI/garis awal ada di `src/rois.json`; sesuaikan koordinat dengan frame kamera sebelum analisis. Demo tidak memerlukan stream atau model. Kotak abu-abu = di luar ROI, kuning = di dalam, hijau = sudah dihitung; panel menunjukkan hitungan, arus, kapasitas, DJ dan status. CSV dibuat di `src/out/` saat aplikasi ditutup. `--tb-share`, `--bus-bb`, dan `--lanes` menerima nilai parameter sesuai survei.

## Editor ROI

Pilih ROI, klik **Edit ROI**, geser titik kontrol polygon/garis; Enter menyelesaikan gambar polygon, Backspace menghapus titik terakhir. Pilih arah `down` atau `up`, lalu **Simpan ROI**. Tombol Mulai/Jeda menghentikan pemrosesan, bukan pembaca frame. Screenshot dan CSV disimpan di `src/out/`.

## Catatan analisis

COCO tidak membedakan KS/TB maupun bus sedang/besar; DJ bergantung pada `tb_share`/`bus_bb`. Survei manual disarankan; laporkan batas bila semua truk diasumsikan KS atau TB. Kendaraan besar menutupi mobil dan tiang median dapat memutus ID; arus jendela 5 menit berfluktuasi. Akurasi turun malam/hujan/kabut. ROI awal perkiraan dan harus dikoreksi. Validasi hitungan manual; analisis resmi idealnya minimal 1 jam atau beberapa interval 15 menit. Hormati syarat penggunaan dan izin CCTV.

Stream uji `https://streaming-cct.co.id/LiveApp/streams/418964061815952674729554.m3u8` berhasil diakses saat pengujian: playlist/segmen HTTP 200, OpenCV membaca frame 704×576, dan GUI offscreen menerima frame (sekitar 8 FPS pada CPU di lingkungan uji). Keberhasilan ini bergantung pada ketersediaan stream dan belum menjamin kelangsungan atau akurasi hitungan. Header referer/user-agent diteruskan sebagai argumen, namun backend OpenCV dapat mengabaikannya. Putus-sambung belum dicatat sebagai interval kehilangan di CSV.
