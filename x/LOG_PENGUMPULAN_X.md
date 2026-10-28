# Log pengumpulan data TK2 (rekonstruksi)

Disusun dari riwayat percakapan dengan Claude (waktu kirim kode dan waktu kamu mengirim hasil) dan waktu ubah berkas
yang tampil di Explorer. Semua waktu dalam WIB (UTC+7), tanggal 19 Oktober 2026 kecuali disebut lain.
Catatan: skrip X tidak menulis log sendiri, jadi waktu di bawah adalah rekonstruksi, bukan catatan otomatis.

## Versi skrip x_collect.py

| Versi | Dibuat (WIB) | sha256 (12) | Perubahan |
|---|---|---|---|
| v1 | 13.28 | b6062c4ad36e | Versi awal: segmen 9 hari, 5 segmen, kueri XS1 sampai XK3 |
| v2 | 13.30 | 99c4228b88e3 | Tambah ejaan tidak baku (mkn gratis, gak/ga/gk/tdk/nggak matang) |
| v3 | 13.36 | 8233879371db | Tambah --days dan --tag. Masih ada bug kelebihan tarik |
| v4 | 13.42 | 1d7751c71238 | Kueri XS2 ditambah varian "mateng" (gak/ga/gk/nggak/ngga mateng dan seterusnya) |
| v5 | 13.45 | 9fad4bc568fa | Perbaikan bug kelebihan tarik, penghitungan biaya sesuai post terbayar, tambah --until |
| v6 | 13.48 | 8e1c1cfdd46b | Tambah --daily-cap (satu tarikan per hari WIB) |
| v7 | 13.58 | 73da4a797a74 | Tambah --max-total (pengaman keras). Ini versi terakhir |

## Pengambilan data X dan versi yang dipakai

| Waktu (WIB) | Berkas | Perintah | Versi |
|---|---|---|---|
| 11.45 dan 12.01 | (pilot, tidak dipakai di data akhir) | x_pilot.py | x_pilot.py |
| 13.35 | XS1_S1, S2, S3, S4, S5 | x_collect.py --only XS1 | v2 |
| 13.40 | XS1_S1a | --days 0-2 --tag S1a --cap 100 | v3 (bug kelebihan tarik) |
| 13.41 | XS1_S1b | --tag S1b | v3 (bug kelebihan tarik) |
| 13.47 dan 13.54 | counts/*.json | x_counts.py | versi terakhir |
| 13.49 | XS1_D01 | --days 0-1 --tag D01 --until ... | v5 atau v6 (perilaku sama) |
| 13.57 | XS2_D00 sampai D44 | --only XS2 --days 0-44 --daily-cap 80 | v6 |
| sekitar 14.00 sampai 16.24 | XK1b_D00 sampai D39 | --only XK1b --days 0-44 --daily-cap 300 --max-total 1400, berhenti karena kredit habis | v7 |
| sekitar 16.27 | XK1b_D40 sampai D44 | --days 40-44 --daily-cap 300 --max-total 150 | v7 |
| sekitar 16.28 | XK2b_D00 sampai D44 (D37 sampai D44 menyusul) | --daily-cap 200 --max-total 450, lalu --days 37-44 --max-total 100 | v7 |

Waktu pasti untuk baris XK1b dan XK2b ada di waktu ubah berkas dan di MANIFEST_data.csv (jalankan make_manifest.py).

## Kondisi akun
- Berkas XS1 (S1, S1a, S1b) memakai versi dengan bug kelebihan tarik. Isi data tidak terpengaruh, tetapi biaya lebih besar dari batas cap (sekitar 469 post terbayar untuk XS1).
- Saat kredit habis di tengah XK1b, pengambilan dilanjutkan dengan Bearer Token akun lain (akun teman). Berkas yang sudah ada dilewati.

## Aturan umum
- Semua tarikan memakai X API v2 search/all dengan -is:retweet, window 45 hari (WIB): Sukoharjo 16 Jan sampai 1 Mar 2025, Karo 13 Agu sampai 26 Sep 2026.
- Kueri persis tiap versi ada di berkas versi yang bersangkutan (konstanta QUERIES).

## Catatan verifikasi (2026-10-28)
- Kueri di `x_collect.py` (v7, versi di repo ini) identik dengan kueri versi yang benar-benar dipakai menarik data:
  XS1 (v2) sama dengan v7; XS2 diubah di v4 (varian "mateng") dan ditarik dengan v6, sama dengan v7; XK1b/XK2b ditarik
  dengan v7. Jadi `x_collect.py` di repo ini mereproduksi kueri seluruh data X. Perbedaan antarversi hanya pada opsi
  (`--days`, `--until`, `--daily-cap`, `--max-total`) dan perbaikan bug kelebihan tarik, yang tidak mengubah isi data.
- Konteks reply/quote ditarik 2026-10-28 dengan `x_context.py` (424 ID diminta, 398 tersedia, 26 tidak tersedia).
