"""
Hitung VOLUME post per hari untuk tiap kueri tanpa mengunduh post (murah).

Endpoint counts/all ditagih per REQUEST (sekitar $0.01), bukan per post, jadi satu kueri untuk
window 45 hari biasanya hanya 1 sampai 2 request. Hasilnya dipakai untuk menentukan batas
dan pemecahan segmen sebelum menarik post.

Pemakaian:
  export X_BEARER_TOKEN="..."
  python x_counts.py --dry-run                 # lihat rencana, tanpa API
  python x_counts.py --only XS1                # satu kueri, kedua kasus tidak dicampur (sesuai kasus kueri)
  python x_counts.py                           # semua kueri

Keluaran: jumlah post per bucket, ditampilkan dalam UTC dan WIB. Bucket mengikuti
start_time; kalau awal bucket tidak jatuh di 00:00 WIB, baca kolom UTC apa adanya.
Hasil lengkap disimpan di counts/<kueri>.json.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from x_collect import INCIDENT, QUERIES, WINDOW_DAYS, WIB, days_window

URL = "https://api.x.com/2/tweets/counts/all"
PRICE_PER_REQUEST = 0.01
MAX_PAGES = 5


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="contoh: XS1,XK1b (default: semua kecuali XS4)")
    parser.add_argument("--granularity", default="day", choices=["day", "hour"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ids = args.only.split(",") if args.only else [q for q in QUERIES if q != "XS4"]
    unknown = [i for i in ids if i not in QUERIES]
    if unknown:
        sys.exit(f"Kueri tidak dikenal: {unknown}")

    print(f"Rencana: {len(ids)} kueri, perkiraan {len(ids)} sampai {2 * len(ids)} request, "
          f"sekitar ${len(ids) * PRICE_PER_REQUEST:.2f} sampai ${2 * len(ids) * PRICE_PER_REQUEST:.2f}")
    if args.dry_run:
        return
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        sys.exit("Set dulu environment variable X_BEARER_TOKEN.")
    os.makedirs("counts", exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}

    requests_made = 0
    for qid in ids:
        case, _cap, query = QUERIES[qid]
        start, end = days_window(case, 0, WINDOW_DAYS - 1)
        params = {"query": query, "start_time": start, "end_time": end, "granularity": args.granularity}
        buckets, pages = [], []
        while len(pages) < MAX_PAGES:
            resp = requests.get(URL, headers=headers, params=params, timeout=30)
            requests_made += 1
            if resp.status_code == 429:
                print("  Kena rate limit, tunggu 60 detik...")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                print(f"  Error {resp.status_code}: {resp.text[:400]}")
                break
            data = resp.json()
            pages.append(data)
            buckets.extend(data.get("data", []))
            nxt = data.get("meta", {}).get("next_token")
            if not nxt:
                break
            params["next_token"] = nxt
            time.sleep(1.1)

        with open(f"counts/{qid}.json", "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False)
        total = sum(b["tweet_count"] for b in buckets)
        print(f"\n[{qid}] {case}: {total} post di {len(buckets)} bucket "
              f"(perkiraan biaya jika diambil semua ${total * 0.005:.2f})")
        for b in sorted(buckets, key=lambda x: x["start"]):
            s = datetime.strptime(b["start"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            print(f"  {b['start'][:16]}Z = {s.astimezone(WIB).strftime('%m-%d %H:%M')} WIB  {b['tweet_count']:5d}")

    print(f"\nRequest dibuat: {requests_made}, perkiraan biaya ${requests_made * PRICE_PER_REQUEST:.2f}")


if __name__ == "__main__":
    main()
