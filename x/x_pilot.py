"""
Pilot X API full-archive search untuk 6 kueri (read-only, hemat).

Pemakaian:
  pip install requests
  export X_BEARER_TOKEN="isi_bearer_token_kamu"      # PowerShell: $env:X_BEARER_TOKEN="..."
  python x_pilot.py                      # semua kueri, 30 post per kueri
  python x_pilot.py --only XS1,XK1       # sebagian kueri saja
  python x_pilot.py --per-query 20       # lebih hemat

Catatan penting:
  - X mengembalikan hasil dari yang TERBARU ke yang terlama di dalam rentang tanggal.
    Karena itu pilot memakai rentang pendek per kueri (hari ke-0 sampai 3 sejak kejadian),
    supaya sampelnya berasal dari masa ramai, bukan dari ujung window.
  - Respons API disimpan utuh per halaman (JSONL) di folder pilot_x/.
  - Script meminta semua field post, tapi TIDAK memakai expansions (data akun dan post
    yang dikutip), karena expansions mungkin ditagih sebagai resource tambahan.
  - Biaya perkiraan: jumlah post x $0.005. Cek saldo di console sebelum dan sesudah.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

URL = "https://api.x.com/2/tweets/search/all"
WIB = timezone(timedelta(hours=7))
PRICE_PER_POST = 0.005

INCIDENT = {
    "sukoharjo": datetime(2025, 1, 16, tzinfo=WIB),
    "karo": datetime(2026, 8, 13, tzinfo=WIB),
}

# (kasus, rentang hari default untuk pilot, kueri)
QUERIES = {
    "XS1": ("sukoharjo", (0, 3),
            '(Sukoharjo OR "Dukuh 03" OR "SDN Dukuh") '
            '(MBG OR "makan bergizi" OR "makan siang gratis" OR "makan gratis" OR BGN OR SPPG OR keracunan) '
            "-is:retweet"),
    "XS2": ("sukoharjo", (0, 3),
            '("ayam tepung" OR "ayam kurang matang" OR "kurang matang" OR "Kodim 0726") '
            '(MBG OR "makan bergizi" OR "makan gratis" OR keracunan) -is:retweet'),
    "XS3": ("sukoharjo", (0, 3),
            '(keracunan OR keracun OR "sakit perut" OR mual OR muntah OR basi) '
            '(MBG OR "makan bergizi" OR "makan siang gratis" OR "makan gratis") lang:id -is:retweet'),
    "XK1": ("karo", (0, 3),
            "(Karo OR Berastagi OR Brastagi OR Kabanjahe) "
            '(MBG OR "makan bergizi" OR BGN OR SPPG OR keracunan) -is:retweet'),
    # Dampak lanjutan baru ramai sekitar hari ke-20 sampai 35, jadi rentangnya berbeda.
    "XK2": ("karo", (20, 35),
            '(Febiona OR Febiola OR "Febi Yona" OR "hilang ingatan" OR "gangguan ingatan" '
            'OR "lupa ingatan" OR "tidak mengenali" OR kejang) (MBG OR keracunan OR BGN OR SPPG) -is:retweet'),
    "XK3": ("karo", (0, 3),
            '(keracunan OR keracun OR mual OR muntah OR basi) '
            '(MBG OR "makan bergizi" OR SPPG) lang:id -is:retweet'),

    # Kueri revisi setelah pilot pertama (belum diuji).
    # XK1b: tanpa kata "karo" tunggal, karena dalam bahasa Jawa berarti "dengan".
    "XK1b": ("karo", (0, 3),
             '("Kabupaten Karo" OR "Kab. Karo" OR "Tanah Karo" OR "siswa Karo" OR "siswi Karo" '
             "OR Berastagi OR Brastagi OR Kabanjahe) "
             '(MBG OR "makan bergizi" OR BGN OR SPPG OR keracunan) -is:retweet'),
    # XK2b: menangkap bantahan RSCM dan serangan panik, bukan hanya klaim hilang ingatan.
    "XK2b": ("karo", (20, 35),
             '(Febiona OR Febiola OR "Febi Yona" OR "siswi Karo" OR RSCM) '
             '(MBG OR keracunan OR BGN OR SPPG OR "hilang ingatan" OR "serangan panik" '
             'OR "tidak hilang ingatan") -is:retweet'),
    # XS4: kontroversi Deddy Corbuzier yang menggerakkan diskusi Sukoharjo.
    "XS4": ("sukoharjo", (0, 3),
            '(Corbuzier) (MBG OR keracunan OR "makan gratis" OR "makan bergizi" '
            'OR "makan siang gratis") -is:retweet'),
}

TWEET_FIELDS = ",".join([
    "attachments", "author_id", "context_annotations", "conversation_id", "created_at",
    "entities", "geo", "id", "in_reply_to_user_id", "lang", "possibly_sensitive",
    "public_metrics", "referenced_tweets", "reply_settings", "source", "text", "withheld",
])


def window(case, day_from, day_to):
    base = INCIDENT[case]
    start = base + timedelta(days=day_from)
    end = base + timedelta(days=day_to + 1) - timedelta(seconds=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.astimezone(timezone.utc).strftime(fmt), end.astimezone(timezone.utc).strftime(fmt)


def run_query(token, qid, per_query, days_override, out_dir):
    case, default_days, query = QUERIES[qid]
    day_from, day_to = days_override or default_days
    start, end = window(case, day_from, day_to)
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "query": query,
        "start_time": start,
        "end_time": end,
        "max_results": max(10, min(500, per_query)),
        "tweet.fields": TWEET_FIELDS,
    }

    posts, path = [], os.path.join(out_dir, f"{qid}_raw.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        while len(posts) < per_query:
            resp = requests.get(URL, headers=headers, params=params, timeout=30)
            if resp.status_code == 429:
                print("  Kena rate limit, tunggu 60 detik...")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                print(f"  Error {resp.status_code}: {resp.text[:400]}")
                return
            data = resp.json()
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
            posts.extend(data.get("data", []))
            token_next = data.get("meta", {}).get("next_token")
            if not token_next or not data.get("data"):
                break
            params["next_token"] = token_next
            time.sleep(1.1)

    posts = posts[:per_query]
    print(f"\n[{qid}] {case}, hari {day_from} sampai {day_to} (UTC {start} sampai {end})")
    print(f"  Post terambil: {len(posts)}  (perkiraan biaya ${len(posts) * PRICE_PER_POST:.3f})")
    for p in posts[:8]:
        text = p["text"].replace("\n", " ")[:130]
        print(f"  - {p['created_at'][:16]}  {text}")
    return len(posts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="contoh: XS1,XK1")
    parser.add_argument("--per-query", type=int, default=30)
    parser.add_argument("--days", default=None, help="timpa rentang hari, contoh: 0-3")
    parser.add_argument("--out-dir", default="pilot_x")
    args = parser.parse_args()

    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        sys.exit("Set dulu environment variable X_BEARER_TOKEN.")

    default_ids = ["XS1", "XS2", "XS3", "XK1", "XK2", "XK3"]  # kueri revisi hanya jalan lewat --only
    ids = args.only.split(",") if args.only else default_ids
    unknown = [i for i in ids if i not in QUERIES]
    if unknown:
        sys.exit(f"Kueri tidak dikenal: {unknown}")

    days_override = None
    if args.days:
        a, b = args.days.split("-")
        days_override = (int(a), int(b))

    os.makedirs(args.out_dir, exist_ok=True)
    total = 0
    for qid in ids:
        total += run_query(token, qid, args.per_query, days_override, args.out_dir) or 0

    print(f"\nTotal post: {total}, perkiraan biaya ${total * PRICE_PER_POST:.2f}")
    print("Bandingkan dengan selisih saldo di console. Selisih yang lebih besar berarti ada biaya tambahan.")


if __name__ == "__main__":
    main()
