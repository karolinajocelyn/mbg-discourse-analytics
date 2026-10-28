"""
Pengumpul data YouTube (video + komentar) untuk dua kasus MBG. Gratis, read-only.
Rancangan sejajar dengan x_collect.py: window 45 hari, 5 segmen @ 9 hari, respons mentah disimpan utuh.

Alur tiga tahap:
  1. discover : search.list per kueri dan segmen -> raw/yt_search_*.jsonl, lalu daftar kandidat
                interim/yt_candidates.csv (label manual tidak pernah ditimpa)
  2. (manual) : buka yt_candidates.csv, isi kolom relevan (y/n), channel_type, sub_event
  3. comments : komentar + reply untuk video berlabel relevan=y -> raw/yt_comments_*.jsonl
  4. flatten  : ratakan ke interim/yt_comments.csv (author di-hash, ada kolom in_window)

Pemakaian:
  pip install requests
  export YT_API_KEY="isi_api_key_kamu"        # PowerShell: $env:YT_API_KEY="..."
  export HASH_SALT="salt_rahasia_tim"         # hanya untuk tahap flatten

  python youtube_collect.py discover --dry-run
  python youtube_collect.py discover --only YK1,YS1 --segments S1
  python youtube_collect.py discover                      # semua kueri utama, semua segmen
  python youtube_collect.py comments --max-pages 5
  python youtube_collect.py flatten

Kuota (default 10.000 unit/hari, cek angka terbaru di Cloud Console > Quotas):
  search.list 100 unit, videos.list 1 unit, commentThreads.list 1 unit, comments.list 1 unit.
  Script menghitung unit sendiri dan berhenti di --quota-limit (default 6000).
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://www.googleapis.com/youtube/v3"
WIB = timezone(timedelta(hours=7))
WINDOW_DAYS = 45
SEGMENT_DAYS = 9
SEGMENTS = [f"S{i + 1}" for i in range(WINDOW_DAYS // SEGMENT_DAYS)]
SEARCH_COST = 100

INCIDENT = {
    "sukoharjo": datetime(2025, 1, 16, tzinfo=WIB),
    "karo": datetime(2026, 8, 13, tzinfo=WIB),
}

# Kata lokasi untuk penanda otomatis di judul/deskripsi (bukan penentu akhir).
LOCATION_TERMS = {
    "sukoharjo": ["sukoharjo", "dukuh"],
    "karo": ["karo", "berastagi", "brastagi", "kabanjahe"],
}

# id: (kasus, kueri). Kueri YouTube bersifat semantik dan longgar, jadi dibuat pendek.
QUERIES = {
    "YS1": ("sukoharjo", "keracunan MBG Sukoharjo"),
    "YS2": ("sukoharjo", "SDN Dukuh 03 Sukoharjo keracunan makan bergizi gratis"),
    "YS3": ("sukoharjo", "ayam kurang matang MBG Sukoharjo"),
    "YS4": ("sukoharjo", "keracunan makan bergizi gratis"),
    "YK1": ("karo", "keracunan MBG Berastagi"),
    "YK2": ("karo", "keracunan MBG Kabupaten Karo"),
    "YK3": ("karo", "ratusan siswa keracunan MBG Berastagi SPPG"),
    "YK4": ("karo", "siswi hilang ingatan keracunan MBG Karo"),
    "YK5": ("karo", "RSCM siswi Karo keracunan MBG"),
    "YK6": ("karo", "Gibran jenguk korban keracunan MBG Karo"),
    "YK7": ("karo", "orang tua korban tuntut MBG dihentikan Karo"),
    # Opsional, tidak masuk urutan default (sub-peristiwa Corbuzier, asalnya reel Instagram).
    "YS5": ("sukoharjo", "Deddy Corbuzier MBG makan gratis"),
}
DEFAULT_ORDER = ["YS1", "YS2", "YS3", "YS4", "YK1", "YK2", "YK3", "YK4", "YK5", "YK6", "YK7"]

CAND_FIELDS = [
    "video_id", "kasus", "title", "channel_id", "channel_title", "published_at",
    "view_count", "comment_count", "duration", "matched_queries", "segments",
    "auto_relevan", "relevan", "channel_type", "sub_event",
]


class Quota:
    def __init__(self, limit):
        self.limit = limit
        self.used = 0

    def spend(self, units):
        if self.used + units > self.limit:
            sys.exit(f"Batas kuota lokal {self.limit} unit tercapai (terpakai {self.used}). "
                     "Naikkan --quota-limit atau lanjutkan besok.")
        self.used += units


def segment_window(case, seg):
    idx = SEGMENTS.index(seg)
    base = INCIDENT[case]
    start = base + timedelta(days=idx * SEGMENT_DAYS)
    end = base + timedelta(days=(idx + 1) * SEGMENT_DAYS) - timedelta(seconds=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.astimezone(timezone.utc).strftime(fmt), end.astimezone(timezone.utc).strftime(fmt)


def window_bounds(case):
    start = INCIDENT[case].astimezone(timezone.utc)
    end = (INCIDENT[case] + timedelta(days=WINDOW_DAYS)).astimezone(timezone.utc)
    return start, end


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def need_key():
    key = os.environ.get("YT_API_KEY")
    if not key:
        sys.exit("Set dulu environment variable YT_API_KEY.")
    return key


def api_get(endpoint, params):
    """Kembalikan (status, json). Berhenti total bila kuota habis."""
    for _ in range(3):
        resp = requests.get(f"{BASE}/{endpoint}", params=params, timeout=30)
        if resp.status_code in (500, 503):
            time.sleep(3)
            continue
        break
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:400]}
    if resp.status_code == 403 and "quotaExceeded" in resp.text:
        sys.exit("Kuota harian habis. Reset tengah malam waktu Pasifik (sekitar pukul 14.00 WIB).")
    return resp.status_code, data


def error_reason(data):
    try:
        return data["error"]["errors"][0]["reason"]
    except (KeyError, IndexError, TypeError):
        return "unknown"


# ---------------------------------------------------------------- discover

def search_segment(key, qid, seg, pages, path, quota, order):
    case, query = QUERIES[qid]
    start, end = segment_window(case, seg)
    params = {
        "key": key, "part": "snippet", "type": "video", "q": query, "maxResults": 50,
        "publishedAfter": start, "publishedBefore": end, "regionCode": "ID",
        "relevanceLanguage": "id", "order": order,
    }
    n_items, more = 0, False
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        for page in range(pages):
            quota.spend(SEARCH_COST)
            status, data = api_get("search", params)
            if status != 200:
                print(f"  Error {status} ({error_reason(data)}): {str(data)[:300]}")
                f.close()
                os.remove(tmp)
                return None
            data["_meta"] = {"query_id": qid, "kasus": case, "segmen": seg, "page": page + 1,
                             "collected_at": now_utc()}
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
            n_items += len(data.get("items", []))
            token = data.get("nextPageToken")
            if not token:
                break
            if page + 1 == pages:
                more = True
                break
            params["pageToken"] = token
            time.sleep(0.3)
    os.replace(tmp, path)
    return n_items, more


def load_search_hits(raw_dir):
    """Gabungkan semua raw/yt_search_*.jsonl menjadi {video_id: info}."""
    hits = {}
    for path in sorted(glob.glob(os.path.join(raw_dir, "yt_search_*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                meta = data["_meta"]
                for item in data.get("items", []):
                    vid = item.get("id", {}).get("videoId")
                    if not vid:
                        continue
                    h = hits.setdefault(vid, {"kasus": meta["kasus"], "queries": set(), "segments": set(),
                                              "snippet": item.get("snippet", {})})
                    h["queries"].add(meta["query_id"])
                    h["segments"].add(meta["segmen"])
    return hits


def read_candidates(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        return {r["video_id"]: r for r in csv.DictReader(f)}


def write_candidates(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAND_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows.values(), key=lambda r: (r["kasus"], r["published_at"])):
            w.writerow(r)


def build_candidates(key, args, quota):
    hits = load_search_hits(args.out_dir)
    existing = read_candidates(args.candidates)
    new_ids = [v for v in hits if v not in existing]
    print(f"\nVideo unik dari pencarian: {len(hits)}; baru: {len(new_ids)}; label lama dipertahankan: {len(existing)}")
    for i in range(0, len(new_ids), 50):
        chunk = new_ids[i:i + 50]
        quota.spend(1)
        status, data = api_get("videos", {"key": key, "part": "snippet,statistics,contentDetails",
                                          "id": ",".join(chunk)})
        if status != 200:
            print(f"  videos.list error {status}: {str(data)[:300]}")
            break
        for item in data.get("items", []):
            vid = item["id"]
            sn, st = item.get("snippet", {}), item.get("statistics", {})
            h = hits[vid]
            text = (sn.get("title", "") + " " + sn.get("description", "")).lower()
            flag = "ya" if any(t in text for t in LOCATION_TERMS[h["kasus"]]) else "cek"
            existing[vid] = {
                "video_id": vid, "kasus": h["kasus"], "title": sn.get("title", ""),
                "channel_id": sn.get("channelId", ""), "channel_title": sn.get("channelTitle", ""),
                "published_at": sn.get("publishedAt", ""),
                "view_count": st.get("viewCount", ""),
                "comment_count": st.get("commentCount", "0"),   # kosong bila komentar dimatikan
                "duration": item.get("contentDetails", {}).get("duration", ""),
                "matched_queries": "|".join(sorted(h["queries"])),
                "segments": "|".join(sorted(h["segments"])),
                "auto_relevan": flag, "relevan": "", "channel_type": "", "sub_event": "",
            }
    write_candidates(args.candidates, existing)
    flagged = sum(1 for r in existing.values() if r["auto_relevan"] == "ya")
    print(f"Tersimpan {len(existing)} kandidat di {args.candidates} (penanda lokasi 'ya': {flagged}).")
    print("Langkah berikutnya: isi kolom relevan (y/n), channel_type, sub_event secara manual.")


def cmd_discover(args):
    ids = args.only.split(",") if args.only else DEFAULT_ORDER
    unknown = [i for i in ids if i not in QUERIES]
    if unknown:
        sys.exit(f"Kueri tidak dikenal: {unknown}")
    segs = args.segments.split(",") if args.segments else SEGMENTS
    bad = [s for s in segs if s not in SEGMENTS]
    if bad:
        sys.exit(f"Segmen tidak dikenal: {bad} (pilih dari {SEGMENTS})")
    plan = [(q, s) for q in ids for s in segs]
    est = len(plan) * args.pages * SEARCH_COST
    print(f"Rencana: {len(plan)} pencarian x maks {args.pages} halaman, kuota maksimal {est} unit "
          f"(batas harian default 10.000)")
    if args.dry_run:
        for qid, seg in plan:
            case, query = QUERIES[qid]
            s, e = segment_window(case, seg)
            print(f"  {qid:4s} {case:9s} {seg}  UTC {s} sampai {e}  q='{query}'")
        return

    key = need_key()
    quota = Quota(args.quota_limit)
    os.makedirs(args.out_dir, exist_ok=True)
    current = None
    summary = []
    for qid, seg in plan:
        case, _ = QUERIES[qid]
        if qid != current:
            current = qid
            print(f"\n=== {qid} ({case}) ===")
        path = os.path.join(args.out_dir, f"yt_search_{case}_{qid}_{seg}.jsonl")
        if os.path.exists(path) and not args.force:
            print(f"  {seg}: sudah ada, dilewati (pakai --force untuk menimpa)")
            continue
        res = search_segment(key, qid, seg, args.pages, path, quota, args.order)
        if res is None:
            print(f"  {seg}: gagal, berhenti.")
            break
        n, more = res
        print(f"  {seg}: {n:3d} video {'[MASIH ADA HALAMAN BERIKUTNYA]' if more else '[habis]'}")
        summary.append((qid, seg, n, more))
    build_candidates(key, args, quota)
    print(f"\nKuota terpakai sesi ini: {quota.used} unit. Cocokkan dengan grafik di Cloud Console.")


# ---------------------------------------------------------------- comments

def fetch_video_comments(key, video_id, case, max_pages, order, quota, path):
    params = {"key": key, "part": "snippet,replies", "videoId": video_id,
              "maxResults": 100, "order": order, "textFormat": "plainText"}
    threads, replies_pulled = 0, 0
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        for _ in range(max_pages):
            quota.spend(1)
            status, data = api_get("commentThreads", params)
            if status == 403 and error_reason(data) == "commentsDisabled":
                f.write(json.dumps({"kind": "disabled", "video_id": video_id, "kasus": case,
                                    "collected_at": now_utc()}) + "\n")
                f.close()
                os.replace(tmp, path)
                return "komentar dimatikan", 0
            if status != 200:
                f.close()
                os.remove(tmp)
                return f"error {status} ({error_reason(data)})", threads
            f.write(json.dumps({"kind": "threads", "video_id": video_id, "kasus": case,
                                "collected_at": now_utc(), "data": data}, ensure_ascii=False) + "\n")
            for item in data.get("items", []):
                threads += 1
                total = item["snippet"].get("totalReplyCount", 0)
                have = len(item.get("replies", {}).get("comments", []))
                if total > have:
                    replies_pulled += pull_all_replies(key, item["id"], video_id, case, quota, f)
            token = data.get("nextPageToken")
            if not token:
                break
            params["pageToken"] = token
            time.sleep(0.2)
    os.replace(tmp, path)
    return f"{threads} thread, {replies_pulled} reply tambahan", threads


def pull_all_replies(key, parent_id, video_id, case, quota, fh):
    params = {"key": key, "part": "snippet", "parentId": parent_id, "maxResults": 100,
              "textFormat": "plainText"}
    pulled = 0
    while True:
        quota.spend(1)
        status, data = api_get("comments", params)
        if status != 200:
            return pulled
        fh.write(json.dumps({"kind": "replies", "video_id": video_id, "parent_id": parent_id, "kasus": case,
                             "collected_at": now_utc(), "data": data}, ensure_ascii=False) + "\n")
        pulled += len(data.get("items", []))
        token = data.get("nextPageToken")
        if not token:
            return pulled
        params["pageToken"] = token
        time.sleep(0.2)


def cmd_comments(args):
    rows = read_candidates(args.candidates)
    if not rows:
        sys.exit(f"{args.candidates} belum ada. Jalankan 'discover' dulu.")
    ok = {"y", "ya"}
    chosen = [r for r in rows.values()
              if r["relevan"].strip().lower() in ok
              or (args.include_auto and not r["relevan"].strip() and r["auto_relevan"] == "ya")]
    chosen = [r for r in chosen if int(r["comment_count"] or 0) >= args.min_comments]
    chosen.sort(key=lambda r: int(r["comment_count"] or 0), reverse=True)
    if args.top_per_case:
        kept, count = [], {}
        for r in chosen:
            count[r["kasus"]] = count.get(r["kasus"], 0) + 1
            if count[r["kasus"]] <= args.top_per_case:
                kept.append(r)
        chosen = kept
    est = sum(min(args.max_pages, -(-int(r["comment_count"] or 0) // 100)) for r in chosen)
    print(f"Video terpilih: {len(chosen)}; perkiraan kuota dasar sekitar {est} unit (belum termasuk reply panjang)")
    if args.dry_run:
        for r in chosen:
            print(f"  {r['kasus']:9s} {r['video_id']}  {r['comment_count']:>6s} komentar  {r['channel_title'][:25]:25s} {r['title'][:60]}")
        return
    key = need_key()
    quota = Quota(args.quota_limit)
    os.makedirs(args.out_dir, exist_ok=True)
    for r in chosen:
        path = os.path.join(args.out_dir, f"yt_comments_{r['kasus']}_{r['video_id']}.jsonl")
        if os.path.exists(path) and not args.force:
            print(f"  {r['video_id']}: sudah ada, dilewati")
            continue
        msg, _ = fetch_video_comments(key, r["video_id"], r["kasus"], args.max_pages, args.order, quota, path)
        print(f"  {r['kasus']:9s} {r['video_id']}: {msg}")
    print(f"\nKuota terpakai sesi ini: {quota.used} unit.")


# ---------------------------------------------------------------- flatten

def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def cmd_flatten(args):
    salt = os.environ.get("HASH_SALT")
    if not salt:
        sys.exit("Set dulu environment variable HASH_SALT (salt rahasia tim, jangan dibagikan di luar tim).")
    rows = {}

    def add(c, video_id, parent_id, case, collected_at, reply_count):
        sn = c["snippet"]
        author = sn.get("authorChannelId", {}).get("value", "")
        start, end = window_bounds(case)
        ts = parse_ts(sn["publishedAt"])
        rows[c["id"]] = {
            "comment_id": c["id"], "parent_id": parent_id, "video_id": video_id,
            "author_hash": hashlib.sha256((salt + author).encode()).hexdigest()[:16] if author else "",
            "published_at": sn["publishedAt"], "text": sn.get("textDisplay", ""),
            "like_count": sn.get("likeCount", 0), "reply_count": reply_count,
            "kasus": case, "in_window": start <= ts < end, "collected_at": collected_at,
        }

    for path in sorted(glob.glob(os.path.join(args.out_dir, "yt_comments_*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line)
                if obj["kind"] == "threads":
                    for item in obj["data"].get("items", []):
                        top = item["snippet"]["topLevelComment"]
                        add(top, obj["video_id"], "", obj["kasus"], obj["collected_at"],
                            item["snippet"].get("totalReplyCount", 0))
                        for rep in item.get("replies", {}).get("comments", []):
                            add(rep, obj["video_id"], item["id"], obj["kasus"], obj["collected_at"], 0)
                elif obj["kind"] == "replies":
                    for rep in obj["data"].get("items", []):
                        add(rep, obj["video_id"], obj["parent_id"], obj["kasus"], obj["collected_at"], 0)

    fields = ["comment_id", "parent_id", "video_id", "author_hash", "published_at", "text", "like_count",
              "reply_count", "kasus", "in_window", "collected_at"]
    os.makedirs(os.path.dirname(args.comments_csv) or ".", exist_ok=True)
    with open(args.comments_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows.values():
            w.writerow(r)
    out = sum(1 for r in rows.values() if not r["in_window"])
    print(f"{len(rows)} komentar dan reply tersimpan di {args.comments_csv} (di luar window 45 hari: {out}).")
    print("Penggantian nama korban dengan [KORBAN] dilakukan di tahap preprocessing, bukan di sini.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", default="raw")
    p.add_argument("--candidates", default=os.path.join("interim", "yt_candidates.csv"))
    p.add_argument("--quota-limit", type=int, default=6000)
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="cari video per kueri dan segmen")
    d.add_argument("--only", default=None, help="contoh: YK1,YS1")
    d.add_argument("--segments", default=None, help="contoh: S1,S5")
    d.add_argument("--pages", type=int, default=1, help="halaman per pencarian (50 video per halaman)")
    d.add_argument("--order", default="relevance", choices=["relevance", "date", "viewCount"])
    d.add_argument("--force", action="store_true")
    d.add_argument("--dry-run", action="store_true")
    d.set_defaults(func=cmd_discover)

    c = sub.add_parser("comments", help="ambil komentar untuk video berlabel relevan=y")
    c.add_argument("--max-pages", type=int, default=5, help="halaman thread per video (100 thread per halaman)")
    c.add_argument("--order", default="relevance", choices=["relevance", "time"])
    c.add_argument("--min-comments", type=int, default=5)
    c.add_argument("--top-per-case", type=int, default=0, help="batasi jumlah video per kasus (0 = semua)")
    c.add_argument("--include-auto", action="store_true",
                   help="sertakan video yang belum dilabel tetapi penanda lokasinya 'ya'")
    c.add_argument("--force", action="store_true")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_comments)

    f = sub.add_parser("flatten", help="ratakan respons mentah komentar ke CSV")
    f.add_argument("--comments-csv", default=os.path.join("interim", "yt_comments.csv"))
    f.set_defaults(func=cmd_flatten)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
