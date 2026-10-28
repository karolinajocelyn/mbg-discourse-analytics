"""
Tarik bertahap X API full-archive search per kueri dan per segmen (read-only, hemat).

Window 45 hari per kasus dibagi 5 segmen @ 9 hari. Tiap kueri dijalankan per segmen
dengan batas post sendiri. X mengembalikan hasil dari yang TERBARU, jadi batas per
segmen membuat sampel tersebar di seluruh window.

Pemakaian:
  pip install requests
  export X_BEARER_TOKEN="isi_bearer_token_kamu"      # PowerShell: $env:X_BEARER_TOKEN="..."

  python x_collect.py --dry-run                      # tampilkan rencana dan biaya maksimal, tanpa memanggil API
  python x_collect.py --only XS1,XK1b                # jalankan kueri utama dulu
  python x_collect.py --only XS1 --segments S1,S5    # hanya segmen tertentu (untuk cek sampel)
  python x_collect.py --only XS1 --days 0-2 --tag S1a --cap 80   # potongan hari khusus (untuk segmen padat)
  python x_collect.py --only XS1 --days 0-1 --tag D01 --cap 150 --until 2025-01-17T06:16:00Z   # sampai jam tertentu
  python x_collect.py --only XK1b --days 0-44 --daily-cap 30   # tiap hari WIB maksimal 30 post

Aturan:
  - Segmen yang sudah ada di folder raw/ dilewati (pakai --force untuk menimpa).
  - Segmen yang mentok di batas dan masih punya hasil berikutnya ditandai MENTOK di
    ringkasan. Hasil X berurutan dari yang terbaru, jadi menaikkan batas segmen yang mentok
    hanya menambah post dari ujung segmen dan melewatkan bagian awalnya. Segmen yang mentok
    dipecah per 2 sampai 3 hari dengan --days dan --tag.
  - Respons API disimpan utuh per halaman di raw/x_<kasus>_<kueri>_<segmen>.jsonl.
  - Script meminta semua field post tetapi TIDAK memakai expansions (mungkin ditagih tambahan).
  - Biaya diperkirakan dari jumlah post x $0.005. Cek saldo di console sebelum dan sesudah
    tiap kueri; selisih yang jauh lebih besar berarti ada biaya tambahan.
  - Waktu di output berupa UTC. Tambah 7 jam untuk WIB.
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
WINDOW_DAYS = 45
SEGMENT_DAYS = 9
SEGMENTS = [f"S{i + 1}" for i in range(WINDOW_DAYS // SEGMENT_DAYS)]  # S1..S5

INCIDENT = {
    "sukoharjo": datetime(2025, 1, 16, tzinfo=WIB),
    "karo": datetime(2026, 8, 13, tzinfo=WIB),
}

# id: (kasus, batas total, kueri). Batas per segmen = batas total / 5.
QUERIES = {
    "XS1": ("sukoharjo", 300,
            '(Sukoharjo OR "Dukuh 03" OR "SDN Dukuh") '
            '(MBG OR "makan bergizi" OR "makan siang gratis" OR "makan gratis" OR "mkn gratis" OR BGN OR SPPG OR keracunan) '
            "-is:retweet"),
    "XS2": ("sukoharjo", 150,
            '("ayam tepung" OR "ayam kurang matang" OR "kurang matang" OR "belum matang" OR "setengah matang" '
            'OR "tidak matang" OR "gak matang" OR "ga matang" OR "gk matang" OR "tdk matang" OR "nggak matang" '
            'OR "kurang mateng" OR "belum mateng" OR "setengah mateng" OR "tidak mateng" OR "gak mateng" '
            'OR "ga mateng" OR "gk mateng" OR "nggak mateng" OR "ngga mateng" '
            'OR "Kodim 0726") '
            '(MBG OR "makan bergizi" OR "makan gratis" OR "mkn gratis" OR keracunan) -is:retweet'),
    "XS3": ("sukoharjo", 200,
            '(keracunan OR keracun OR "sakit perut" OR mual OR muntah OR basi) '
            '(MBG OR "makan bergizi" OR "makan siang gratis" OR "makan gratis" OR "mkn gratis") lang:id -is:retweet'),
    "XK1b": ("karo", 300,
             '("Kabupaten Karo" OR "Kab. Karo" OR "Tanah Karo" OR "siswa Karo" OR "siswi Karo" '
             "OR Berastagi OR Brastagi OR Kabanjahe) "
             '(MBG OR "makan bergizi" OR "makan siang gratis" OR "makan gratis" OR "mkn gratis" OR BGN OR SPPG OR keracunan) -is:retweet'),
    "XK2b": ("karo", 150,
             '(Febiona OR Febiola OR "Febi Yona" OR "siswi Karo" OR RSCM) '
             '(MBG OR keracunan OR BGN OR SPPG OR "hilang ingatan" OR "serangan panik" '
             'OR "tidak hilang ingatan") -is:retweet'),
    "XK3": ("karo", 200,
            '(keracunan OR keracun OR mual OR muntah OR basi) '
            '(MBG OR "makan bergizi" OR "makan siang gratis" OR "makan gratis" OR "mkn gratis" OR SPPG) lang:id -is:retweet'),
    # Opsional, tidak masuk urutan default.
    "XS4": ("sukoharjo", 100,
            '(Corbuzier) (MBG OR keracunan OR "makan gratis" OR "makan bergizi" '
            'OR "makan siang gratis") -is:retweet'),
}
DEFAULT_ORDER = ["XS1", "XK1b", "XS2", "XK2b", "XS3", "XK3"]

TWEET_FIELDS = ",".join([
    "attachments", "author_id", "context_annotations", "conversation_id", "created_at",
    "entities", "geo", "id", "in_reply_to_user_id", "lang", "possibly_sensitive",
    "public_metrics", "referenced_tweets", "reply_settings", "source", "text", "withheld",
])


def segment_window(case, seg):
    """Awal dan akhir segmen dalam UTC (batas WIB 00:00 sampai 23:59:59)."""
    idx = SEGMENTS.index(seg)
    base = INCIDENT[case]
    start = base + timedelta(days=idx * SEGMENT_DAYS)
    end = base + timedelta(days=(idx + 1) * SEGMENT_DAYS) - timedelta(seconds=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.astimezone(timezone.utc).strftime(fmt), end.astimezone(timezone.utc).strftime(fmt)


def days_window(case, day_from, day_to):
    """Rentang hari ke-day_from sampai ke-day_to (inklusif) sejak kejadian, dalam UTC."""
    base = INCIDENT[case]
    start = base + timedelta(days=day_from)
    end = base + timedelta(days=day_to + 1) - timedelta(seconds=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.astimezone(timezone.utc).strftime(fmt), end.astimezone(timezone.utc).strftime(fmt)


def fetch_segment(token, qid, seg, cap, out_dir, window=None):
    case, _total, query = QUERIES[qid]
    start, end = window or segment_window(case, seg)
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "query": query,
        "start_time": start,
        "end_time": end,
        "max_results": max(10, min(500, cap)),
        "tweet.fields": TWEET_FIELDS,
    }
    path = os.path.join(out_dir, f"x_{case}_{qid}_{seg}.jsonl")
    posts, more_available = [], False
    with open(path, "w", encoding="utf-8") as f:
        while True:
            # Halaman bisa berisi lebih sedikit dari max_results, jadi minta hanya sisa kebutuhan
            # (minimum API 10) agar total yang ditagih tidak jauh melewati batas.
            params["max_results"] = max(10, min(500, cap - len(posts)))
            resp = requests.get(URL, headers=headers, params=params, timeout=30)
            if resp.status_code == 429:
                print("  Kena rate limit, tunggu 60 detik...")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                print(f"  Error {resp.status_code}: {resp.text[:400]}")
                return None
            data = resp.json()
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
            batch = data.get("data", [])
            posts.extend(batch)
            next_token = data.get("meta", {}).get("next_token")
            if len(posts) >= cap:
                # Batas tercapai: mentok bila masih ada halaman berikutnya.
                more_available = bool(next_token)
                break
            if not next_token or not batch:
                break
            params["next_token"] = next_token
            time.sleep(1.1)
    return {
        "path": path,
        "posts": len(posts),  # semua yang diambil = semua yang ditagih
        "fetched": len(posts),
        "mentok": more_available,
        "start": start,
        "end": end,
        "sample": posts[:3],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="contoh: XS1,XK1b (default: urutan utama)")
    parser.add_argument("--segments", default=None, help="contoh: S1,S5 (default: semua)")
    parser.add_argument("--cap", type=int, default=None,
                        help="timpa batas post per segmen atau per potongan hari")
    parser.add_argument("--days", default=None,
                        help="potongan hari sejak kejadian, contoh 0-2 (hari ke-0 sampai 2); wajib bersama --tag")
    parser.add_argument("--daily-cap", type=int, default=None,
                        help="dengan --days a-b: tarik tiap hari WIB sendiri-sendiri dengan batas N post per hari "
                             "(hari dengan post lebih sedikit dari N diambil semuanya)")
    parser.add_argument("--max-total", type=int, default=None,
                        help="pengaman keras: berhenti begitu total post yang ditagih mencapai N "
                             "(sangat disarankan, contoh --max-total 300)")
    parser.add_argument("--until", default=None,
                        help="batas akhir waktu (UTC) untuk --days, contoh 2025-01-17T06:16:00Z; "
                             "dipakai agar tidak menarik ulang post yang sudah ada")
    parser.add_argument("--tag", default=None,
                        help="nama potongan untuk --days, contoh S1a (jadi bagian nama file)")
    parser.add_argument("--out-dir", default="raw")
    parser.add_argument("--force", action="store_true", help="timpa segmen yang sudah ada")
    parser.add_argument("--dry-run", action="store_true", help="hanya tampilkan rencana dan biaya maksimal")
    args = parser.parse_args()

    ids = args.only.split(",") if args.only else DEFAULT_ORDER
    unknown = [i for i in ids if i not in QUERIES]
    if unknown:
        sys.exit(f"Kueri tidak dikenal: {unknown}")
    segs = args.segments.split(",") if args.segments else SEGMENTS
    bad = [x for x in segs if x not in SEGMENTS]
    if bad:
        sys.exit(f"Segmen tidak dikenal: {bad} (pilih dari {SEGMENTS})")

    day_range = None
    if args.days:
        if not args.tag and not args.daily_cap:
            sys.exit("--days harus disertai --tag (atau --daily-cap), contoh: --days 0-2 --tag S1a")
        a, b = args.days.split("-")
        day_range = (int(a), int(b))
        if not (0 <= day_range[0] <= day_range[1] < WINDOW_DAYS):
            sys.exit(f"--days harus di dalam 0 sampai {WINDOW_DAYS - 1}")

    plan = []  # (qid, case, label, cap, (start, end))
    for qid in ids:
        case, total, _ = QUERIES[qid]
        if day_range and args.daily_cap:
            for d in range(day_range[0], day_range[1] + 1):
                plan.append((qid, case, f"D{d:02d}", args.daily_cap, days_window(case, d, d)))
        elif day_range:
            cap = args.cap or total // len(SEGMENTS)
            ws, we = days_window(case, *day_range)
            plan.append((qid, case, args.tag, cap, (ws, args.until or we)))
        else:
            per_seg = args.cap or total // len(SEGMENTS)
            for seg in segs:
                plan.append((qid, case, seg, per_seg, segment_window(case, seg)))

    max_posts = sum(p[3] for p in plan)
    print(f"Rencana: {len(plan)} segmen, jumlah batas {max_posts} post (batas teoretis ${max_posts * PRICE_PER_POST:.2f}; "
          "biaya sebenarnya mengikuti jumlah post yang ada, lihat hasil x_counts.py)")
    if args.max_total:
        print(f"Pengaman: berhenti di {args.max_total} post (${args.max_total * PRICE_PER_POST:.2f})")
    if args.dry_run:
        for qid, case, seg, per_seg, (ws, we) in plan:
            print(f"  {qid:5s} {case:9s} {seg:4s} batas {per_seg:3d}  UTC {ws} sampai {we}")
        return

    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        sys.exit("Set dulu environment variable X_BEARER_TOKEN.")
    os.makedirs(args.out_dir, exist_ok=True)

    summary, total_posts = [], 0
    current = None
    for qid, case, seg, per_seg, win in plan:
        if qid != current:
            current = qid
            print(f"\n=== {qid} ({case}) ===  catat saldo di console sebelum kueri ini")
        out_path = os.path.join(args.out_dir, f"x_{case}_{qid}_{seg}.jsonl")
        if os.path.exists(out_path) and not args.force:
            print(f"  {seg}: sudah ada, dilewati (pakai --force untuk menimpa)")
            continue
        result = fetch_segment(token, qid, seg, per_seg, args.out_dir, win)
        if result is None:
            print(f"  {seg}: gagal, berhenti agar tidak membuang saldo.")
            break
        total_posts += result["posts"]
        if args.max_total and total_posts >= args.max_total:
            print(f"  Pengaman --max-total tercapai ({total_posts} post), berhenti.")
            summary.append((qid, seg, result["posts"], result["mentok"]))
            break
        flag = "MENTOK" if result["mentok"] else "habis"
        print(f"  {seg}: {result['posts']:3d} post (batas {per_seg}) [{flag}]  UTC {result['start']} sampai {result['end']}")
        for p in result["sample"]:
            print(f"      - {p['created_at'][:16]}  {p['text'].replace(chr(10), ' ')[:110]}")
        summary.append((qid, seg, result["posts"], result["mentok"]))

    print(f"\nTotal post tersimpan: {total_posts}, perkiraan biaya ${total_posts * PRICE_PER_POST:.2f}")
    mentok = [f"{q}/{s}" for q, s, _n, m in summary if m]
    print("Segmen mentok (kandidat ditambah):", ", ".join(mentok) if mentok else "tidak ada")
    print("Bandingkan perkiraan biaya dengan selisih saldo di console.")


if __name__ == "__main__":
    main()
