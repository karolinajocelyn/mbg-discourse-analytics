"""
Bandingkan post yang SUDAH terambil dengan hitungan X (counts) per bucket, gratis (tanpa API).

Pemakaian (setelah x_counts.py dan x_collect.py dijalankan di folder yang sama):
  python x_verify.py XS1
  python x_verify.py XS1 XS2

Untuk tiap kueri: tabel per bucket (hari UTC) berisi hitungan X, jumlah post unik yang terambil,
dan rasionya. Baris bertanda KURANG berarti yang terambil di bawah 90% dari hitungan X.
"""
import glob
import json
import sys
from datetime import datetime, timedelta, timezone

from x_collect import QUERIES

WIB = timezone(timedelta(hours=7))


def ts(s):
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def main():
    qids = sys.argv[1:]
    if not qids:
        sys.exit("Pemakaian: python x_verify.py XS1 [XS2 ...]")
    for qid in qids:
        if qid not in QUERIES:
            print(f"{qid}: kueri tidak dikenal")
            continue
        case = QUERIES[qid][0]
        try:
            pages = json.load(open(f"counts/{qid}.json", encoding="utf-8"))
        except FileNotFoundError:
            print(f"{qid}: counts/{qid}.json tidak ada, jalankan x_counts.py dulu")
            continue
        buckets = sorted((b for p in pages for b in p.get("data", [])), key=lambda b: b["start"])
        files = sorted(glob.glob(f"raw/x_{case}_{qid}_*.jsonl"))
        posts = {}
        for path in files:
            for line in open(path, encoding="utf-8"):
                for p in json.loads(line).get("data", []):
                    posts[p["id"]] = p
        per_bucket = [0] * len(buckets)
        outside = 0
        starts = [ts(b["start"]) for b in buckets]
        ends = [ts(b["end"]) for b in buckets]
        for p in posts.values():
            t = datetime.strptime(p["created_at"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            for i, (s, e) in enumerate(zip(starts, ends)):
                if s <= t < e:
                    per_bucket[i] += 1
                    break
            else:
                outside += 1
        total_counts = sum(b["tweet_count"] for b in buckets)
        print(f"\n[{qid}] {case}: {len(files)} berkas, {len(posts)} post unik terambil, hitungan X {total_counts}")
        print("  bucket (UTC)       WIB mulai     X   ambil  rasio")
        for b, s, n in zip(buckets, starts, per_bucket):
            c = b["tweet_count"]
            if c == 0 and n == 0:
                continue
            ratio = f"{n / c:5.0%}" if c else "  n/a"
            flag = "  KURANG" if c and n / c < 0.9 else ""
            print(f"  {b['start'][:16]}Z  {s.astimezone(WIB).strftime('%m-%d %H:%M')}  {c:5d}  {n:5d}  {ratio}{flag}")
        if outside:
            print(f"  {outside} post berada di luar bucket mana pun")
        print(f"  Total terambil / hitungan X: {len(posts)} / {total_counts} ({len(posts) / total_counts:.0%})" if total_counts else "")


if __name__ == "__main__":
    main()
