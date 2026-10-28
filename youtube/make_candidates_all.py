"""
Buat salinan file kandidat dengan relevan=y untuk SEMUA video, supaya `youtube_collect.py comments`
menarik komentar seluruh kandidat (bukan hanya yang dilabel relevan). Relevansi lalu ditentukan
aturan judul di tahap preprocessing (config/relevance_rules.yaml), sama untuk kedua kasus.

Dipakai untuk scrape ulang Karo (2026-10-27). File kandidat asli tidak diubah.

Pemakaian (dari folder data yang berisi interim/):
  python make_candidates_all.py
  python youtube_collect.py --candidates interim/yt_candidates_all.csv comments --dry-run
  python youtube_collect.py --candidates interim/yt_candidates_all.csv comments
  python youtube_collect.py flatten --comments-csv interim/yt_comments_all.csv
"""
import argparse
import csv


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", default="interim/yt_candidates.csv")
    ap.add_argument("--out", default="interim/yt_candidates_all.csv")
    args = ap.parse_args()
    with open(args.src, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    for r in rows:
        r["relevan"] = "y"
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} kandidat ditulis ke {args.out} (semua relevan=y).")


if __name__ == "__main__":
    main()
