"""Fixture: proyek mini sintetis (data X + YouTube palsu) agar pipeline bisa dites tanpa data asli."""
import csv
import json
import shutil
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SALT = "test-salt"


def tw(id, created, text, author="1", conv=None, refs=None, lang="in", urls=0, **pm):
    t = {"id": id, "created_at": created, "text": text, "author_id": author, "conversation_id": conv or id,
         "lang": lang, "edit_history_tweet_ids": [id],
         "public_metrics": {"like_count": pm.get("like", 0), "retweet_count": 0, "reply_count": 0,
                            "quote_count": 0, "impression_count": 10, "bookmark_count": 0}}
    if refs:
        t["referenced_tweets"] = [{"type": k, "id": v} for k, v in refs]
    if urls:
        t["entities"] = {"urls": [{"url": "https://t.co/x"}] * urls}
    return t


def write_jsonl(path, pages):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for p in pages:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def page(tweets):
    return {"data": tweets, "meta": {"result_count": len(tweets)}} if tweets else {"meta": {"result_count": 0}}


# Waktu UTC. Karo: insiden 2026-08-13 WIB = 2026-08-12T17:00Z. Sukoharjo: 2025-01-15T17:00Z.
HEADLINE = "Kata istana soal puluhan siswa keracunan MBG di Berastagi hari ini https://t.co/abc"

X_FILES = {
    "x_karo_XK1b_D00.jsonl": [page([
        tw("100", "2026-08-13T02:00:00.000Z", "Keracunan MBG di Berastagi parah @abc https://t.co/x", author="11"),
        tw("101", "2026-08-13T03:00:00.000Z", "@abc setuju banget harus diusut tuntas", author="12", conv="100",
           refs=[("replied_to", "100")]),
        tw("102", "2026-08-13T04:00:00.000Z", HEADLINE, author="21", urls=1),
        tw("103", "2026-08-13T04:05:00.000Z", HEADLINE, author="22", urls=1),
        tw("104", "2026-08-13T04:10:00.000Z", HEADLINE, author="23", urls=1),
        tw("105", "2026-08-13T05:00:00.000Z", "𝗕𝗚𝗡 &amp; SPPG Karo harus tanggung jawab, kompensasi korban!",
           author="24"),
        tw("106", "2026-08-13T06:00:00.000Z", "Febiola semoga cepat pulih ya dek, MBG Karo harus dievaluasi",
           author="25"),
        tw("107", "2026-08-13T07:00:00.000Z", "Ini lihat MBG Karo", author="26", conv="999",
           refs=[("quoted", "999"), ("replied_to", "998")]),
    ])],
    # potongan tumpang tindih: tweet 100 muncul lagi
    "x_karo_XK1b_S1a.jsonl": [page([tw("100", "2026-08-13T02:00:00.000Z",
                                       "Keracunan MBG di Berastagi parah @abc https://t.co/x", author="11", like=5)])],
    "x_karo_XK1b_D01.jsonl": [page([])],
    "x_karo_XK2b_D25.jsonl": [page([
        tw("200", "2026-09-07T05:00:00.000Z", "Siswi dirujuk ke RSCM usai keracunan MBG", author="31"),
        tw("201", "2026-08-15T05:00:00.000Z", "Pasien RSCM antre panjang", author="32"),
    ])],
    "x_sukoharjo_XS1_S1.jsonl": [page([
        tw("300", "2025-01-16T05:00:00.000Z", "40 siswa SD Sukoharjo keracunan makan bergizi gratis", author="41"),
        tw("301", "2025-01-16T06:00:00.000Z", "Stop MBG", author="42"),
    ])],
    "x_sukoharjo_XS2_D00.jsonl": [page([
        tw("400", "2025-01-17T05:00:00.000Z", "Ayam kurang matang di menu MBG bikin anak keracunan", author="51"),
        tw("401", "2025-01-29T05:00:00.000Z", "Ayam kurang matang di MBG lagi, keracunan lagi", author="52"),
        tw("402", "2025-01-16T09:00:00.000Z", "Hello this is in english about MBG", author="53", lang="en"),
    ])],
}

CONTEXT = [{"data": [{"id": "999", "author_id": "77", "created_at": "2026-08-13T01:00:00.000Z", "lang": "in",
                      "text": "Kasus keracunan MBG di Karo makin banyak korban"}],
            "errors": [{"resource_id": "998", "title": "Not Found Error"}]}]

VIDEO_HEADER = ["video_id", "kasus", "title", "channel_id", "channel_title", "published_at", "view_count",
                "comment_count", "duration", "matched_queries", "segments", "auto_relevan", "relevan", "channel_type",
                "sub_event"]
COMMENT_HEADER = ["comment_id", "parent_id", "video_id", "author_hash", "published_at", "text", "like_count",
                  "reply_count", "kasus", "in_window", "collected_at"]

VIDEOS = {
    "karo": [
        ["-vidA", "karo", "Puluhan Siswa Berastagi Keracunan MBG", "c1", "Media A", "2026-08-13T05:00:00Z", "10",
         "8", "PT1M", "YK1", "S1", "ya", "y", "media", "umum"],
        ["vidB", "karo", "Pegawai SPPG ejek korban keracunan MBG", "c2", "Kreator B", "2026-09-10T05:00:00Z", "10",
         "2", "PT1M", "YK1", "S4", "ya", "n", "kreator", ""],
        ["vidC", "karo", "SQUISHY DUMPLING MELEDAK", "c3", "Kreator C", "2026-09-10T05:00:00Z", "10", "1", "PT1M",
         "YK1", "S4", "cek", "n", "kreator", ""],
    ],
    "sukoharjo": [
        ["vidD", "sukoharjo", "40 Siswa SD Sukoharjo Keracunan Makan Bergizi Gratis", "c4", "Media D",
         "2025-01-16T08:00:00Z", "10", "3", "PT1M", "YS1", "S1", "ya", "y", "", ""],
    ],
}


def yc(cid, vid, author, ts, text, kasus, parent="", in_window="True", collected="2026-10-21T10:00:00Z"):
    return [cid, parent, vid, author, ts, text, "0", "0", kasus, in_window, collected]


COMMENTS = {
    "karo": [
        yc("k1", "-vidA", "a1", "2026-08-13T06:00:00Z", "Stop MBG", "karo"),
        yc("k2", "-vidA", "a2", "2026-08-13T06:01:00Z", "Stop MBG", "karo"),
        yc("k3", "-vidA", "a3", "2026-08-13T06:02:00Z", "Stop MBG", "karo"),
        yc("k4", "-vidA", "a4", "2026-08-13T06:03:00Z", "😢😢", "karo"),
        yc("k5", "-vidA", "a5", "2026-08-13T06:04:00Z", "Febiona semoga lekas sembuh, BGN harus tanggung jawab!",
           "karo"),
        yc("k6", "-vidA", "a6", "2026-08-13T06:05:00Z", "@@user.satu betul sekali, menit 1:23 jelas banget", "karo",
           parent="k5"),
        yc("k7", "-vidA", "a7", "2026-10-05T06:00:00Z", "komentar telat di luar window", "karo", in_window="False"),
        yc("k8", "-vidA", "a8", "2026-08-13T07:00:00Z", "main slot gacor maxwin hari ini", "karo"),
        yc("k9", "vidB", "a9", "2026-09-10T06:00:00Z", "Pegawainya harus dipecat, tidak punya empati sama sekali",
           "karo", collected="2026-10-27T10:00:00Z"),
        yc("k10", "vidC", "a10", "2026-09-10T06:00:00Z", "lucu banget dumplingnya meledak", "karo",
           collected="2026-10-27T10:00:00Z"),
    ],
    "sukoharjo": [
        yc("s1", "vidD", "b1", "2025-01-16T09:00:00Z", "Kasihan anak anak keracunan, vendor harus diusut", "sukoharjo"),
        yc("s2", "vidD", "b2", "2025-01-16T09:30:00Z", "Semoga cepat sembuh adik adik semuanya ya", "sukoharjo"),
        yc("s3", "vidD", "b3", "2025-01-17T09:30:00Z", "Ayam kurang matang kok bisa lolos dapur", "sukoharjo"),
    ],
}

COLLECTOR_STUB = '''WINDOW_DAYS = 45
SEGMENT_DAYS = 9
INCIDENT = {
    "sukoharjo": datetime(2025, 1, 16, tzinfo=WIB),
    "karo": datetime(2026, 8, 13, tzinfo=WIB),
}
'''


def _write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def make_project(root):
    root = Path(root)
    shutil.copytree(REPO / "config", root / "config", ignore=shutil.ignore_patterns("victim_names.txt"))
    (root / "config" / "victim_names.txt").write_text(
        "\\bfebi(ola|ona)\\w*(\\s+(br\\.?\\s+)?purba)?\\b\n\\bagnesia\\w*\\b\n", encoding="utf-8")
    for name, pages in X_FILES.items():
        write_jsonl(root / "x" / "raw" / name, pages)
    write_jsonl(root / "x" / "context" / "x_context.jsonl", CONTEXT)
    for q, start in (("XK1b", "2026-08-12T17:00:00.000Z"), ("XK2b", "2026-08-12T17:00:00.000Z"),
                     ("XS1", "2025-01-15T17:00:00.000Z"), ("XS2", "2025-01-15T17:00:00.000Z")):
        day = start[:10]
        buckets = [{"start": f"{day}T00:00:00.000Z", "end": f"{day}T17:00:00.000Z", "tweet_count": 0}]
        (root / "x" / "counts").mkdir(parents=True, exist_ok=True)
        (root / "x" / "counts" / f"{q}.json").write_text(json.dumps([{"data": buckets}]), encoding="utf-8")
    for kasus, sub in (("karo", "youtube"), ("sukoharjo", "youtube/sukoharjo")):
        _write_csv(root / sub / f"cand_{kasus}.csv", VIDEO_HEADER, VIDEOS[kasus])
        _write_csv(root / sub / f"comments_{kasus}.csv", COMMENT_HEADER, COMMENTS[kasus])
    (root / "collectors").mkdir()
    (root / "collectors" / "x_collect.py").write_text(COLLECTOR_STUB, encoding="utf-8")
    (root / "collectors" / "youtube_collect.py").write_text(COLLECTOR_STUB, encoding="utf-8")

    cfg = yaml.safe_load((REPO / "config" / "pipeline.yaml").read_text(encoding="utf-8"))
    cfg["paths"]["youtube"] = {
        "karo": {"comments": "youtube/comments_karo.csv", "candidates": "youtube/cand_karo.csv"},
        "sukoharjo": {"comments": "youtube/sukoharjo/comments_sukoharjo.csv",
                      "candidates": "youtube/sukoharjo/cand_sukoharjo.csv"},
    }
    cfg["paths"]["collectors"] = {"x": "collectors/x_collect.py", "youtube": "collectors/youtube_collect.py"}
    cfg["youtube"]["expected_thread_capped"] = []
    cfg["expected_counts"] = {}
    (root / "config" / "pipeline.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return root / "config" / "pipeline.yaml"


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path / "proj")


@pytest.fixture
def cfg(project):
    from anmedsos_prep.config import load_config
    return load_config(project)


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    """Hasil build() pada proyek mini; dipakai banyak test."""
    from anmedsos_prep.config import load_config
    from anmedsos_prep.pipeline import build
    cfg_path = make_project(tmp_path_factory.mktemp("built") / "proj")
    cfg = load_config(cfg_path)
    return cfg, build(cfg, SALT, log=lambda *_: None)
