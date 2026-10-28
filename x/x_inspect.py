"""
Ringkas file hasil tarikan di folder raw/ tanpa memanggil API (gratis).

Pemakaian:
  python x_inspect.py                 # semua file raw/x_*.jsonl
  python x_inspect.py raw/x_sukoharjo_XS1_S1a.jsonl

Untuk tiap file: jumlah post, rentang waktu (UTC dan WIB), jumlah post per hari WIB
(termasuk duplikat antar file), serta 5 hashtag terbanyak.
"""
import glob
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))


def load(path):
    posts = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            posts.extend(json.loads(line).get("data", []))
    return posts


def parse(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def main():
    paths = sys.argv[1:] or sorted(glob.glob("raw/x_*.jsonl"))
    if not paths:
        sys.exit("Tidak ada file di raw/.")
    seen = {}
    for path in paths:
        posts = load(path)
        if not posts:
            print(f"\n{path}: kosong")
            continue
        times = sorted(parse(p["created_at"]) for p in posts)
        per_day = Counter(t.astimezone(WIB).strftime("%Y-%m-%d") for t in times)
        tags = Counter(h.lower() for p in posts for h in re.findall(r"#\w+", p["text"]))
        print(f"\n{path}: {len(posts)} post")
        print(f"  paling lama : {times[0].strftime('%Y-%m-%d %H:%M')} UTC = {times[0].astimezone(WIB).strftime('%Y-%m-%d %H:%M')} WIB")
        print(f"  paling baru : {times[-1].strftime('%Y-%m-%d %H:%M')} UTC = {times[-1].astimezone(WIB).strftime('%Y-%m-%d %H:%M')} WIB")
        print("  per hari WIB: " + ", ".join(f"{d[5:]}={n}" for d, n in sorted(per_day.items())))
        if tags:
            print("  hashtag     : " + ", ".join(f"{t}({n})" for t, n in tags.most_common(5)))
        for p in posts:
            seen.setdefault(p["id"], p)
    total = sum(len(load(p)) for p in paths)
    print(f"\nTotal baris: {total}, post unik: {len(seen)}, duplikat antar file: {total - len(seen)}")


if __name__ == "__main__":
    main()
