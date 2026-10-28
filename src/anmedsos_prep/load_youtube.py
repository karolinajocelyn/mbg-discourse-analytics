"""Baca CSV komentar & kandidat video YouTube (hasil youtube_collect.py flatten) per kasus."""
from pathlib import Path

import numpy as np
import pandas as pd

from .load_x import LoadError

COMMENT_COLS = ["comment_id", "parent_id", "video_id", "author_hash", "published_at", "text", "like_count",
                "reply_count", "kasus", "in_window", "collected_at"]
VIDEO_COLS = ["video_id", "kasus", "title", "channel_id", "channel_title", "published_at", "view_count",
              "comment_count", "duration", "matched_queries", "segments", "auto_relevan", "relevan",
              "channel_type", "sub_event"]


def _read(path, required):
    path = Path(path)
    if not path.exists():
        raise LoadError(f"file YouTube tidak ditemukan: {path}")
    # dtype=str: ID YouTube bisa diawali '-' atau berupa angka; jangan sampai terbaca float
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise LoadError(f"kolom wajib hilang di {path.name}: {missing}")
    return df


def load_case(comments_path, candidates_path, kasus, channel_map, thread_cap):
    c = _read(comments_path, COMMENT_COLS)
    v = _read(candidates_path, VIDEO_COLS)
    warnings = []
    if not (c.kasus == kasus).all() or not (v.kasus == kasus).all():
        raise LoadError(f"isi file YouTube {kasus} memuat kasus lain")
    if c.comment_id.duplicated().any():
        raise LoadError(f"comment_id duplikat di {kasus}: {c.comment_id.duplicated().sum()}")
    if v.video_id.duplicated().any():
        raise LoadError(f"video_id duplikat di kandidat {kasus}")
    unknown_video = ~c.video_id.isin(v.video_id)
    if unknown_video.any():
        raise LoadError(f"{unknown_video.sum()} komentar {kasus} dari video yang tidak ada di kandidat")
    orphan = (c.parent_id != "") & ~c.parent_id.isin(c.comment_id)
    if orphan.any():
        raise LoadError(f"{orphan.sum()} reply {kasus} tanpa komentar induk")

    # ---------------------------------------------------------------- video
    v = v.copy()
    for col in ("relevan", "channel_type", "sub_event"):
        v[col] = v[col].str.strip().replace({"-": "", "nan": ""})
    for col in ("channel_type", "sub_event"):
        if (v[col] == "").all():
            warnings.append(f"YouTube {kasus}: kolom {col} kosong di semua {len(v)} video kandidat")
    v["channel_type_norm"] = v.channel_type.map(channel_map).astype("string")
    for col in ("view_count", "comment_count"):
        v[col] = pd.to_numeric(v[col], errors="coerce").fillna(0).astype(int)
    v["published_at"] = pd.to_datetime(v.published_at, utc=True, format="ISO8601")

    # ---------------------------------------------------------------- komentar
    c = c.copy()
    c["text"] = c.text.str.replace("\r\n", "\n").str.replace("\r", "\n")
    c["parent_id"] = c.parent_id.replace("", None).astype("string")
    c["is_reply"] = c.parent_id.notna()
    c["thread_id"] = c.parent_id.fillna(c.comment_id)
    c["like_count"] = pd.to_numeric(c.like_count, errors="coerce").fillna(0).astype(int)
    c["reply_count"] = pd.to_numeric(c.reply_count, errors="coerce").fillna(0).astype(int)
    c["in_window_collector"] = c.in_window.str.lower().eq("true")
    c["created_at"] = pd.to_datetime(c.published_at, utc=True, format="ISO8601")
    c["collected_at"] = pd.to_datetime(c.collected_at, utc=True, format="ISO8601")
    # batch: tanggal tarik paling awal = 'awal', tanggal lain = 'tambahan' (scrape ulang video relevan=n)
    days = c.collected_at.dt.strftime("%Y-%m-%d")
    first = days.min()
    c["batch"] = np.where(days == first, "awal", "tambahan")
    c = c.drop(columns=["published_at", "in_window"])

    got = c.groupby("video_id").size()
    top = c[~c.is_reply].groupby("video_id").size()
    v["n_comments_collected"] = v.video_id.map(got).fillna(0).astype(int)
    v["n_threads_collected"] = v.video_id.map(top).fillna(0).astype(int)
    v["video_coverage_ratio"] = np.where(v.comment_count > 0, v.n_comments_collected / v.comment_count.clip(lower=1),
                                         np.nan)
    v["video_thread_capped"] = v.n_threads_collected >= thread_cap

    meta = v.rename(columns={"title": "video_title", "published_at": "video_published_at",
                             "comment_count": "video_comment_count", "view_count": "video_view_count",
                             "relevan": "relevan_lama"})
    c = c.merge(meta[["video_id", "video_title", "channel_title", "channel_type_norm", "sub_event", "relevan_lama",
                      "video_published_at", "video_comment_count", "video_view_count", "video_coverage_ratio",
                      "video_thread_capped"]], on="video_id", how="left", validate="many_to_one")
    c["comment_before_video"] = c.created_at < c.video_published_at
    return c, v, warnings


def load_youtube(cfg):
    comments, videos, warnings = [], [], []
    ycfg = cfg.raw["youtube"]
    for kasus in cfg.cases:
        p = cfg.raw["paths"]["youtube"][kasus]
        c, v, w = load_case(cfg.p(p["comments"]), cfg.p(p["candidates"]), kasus, ycfg["channel_type_map"],
                            ycfg["thread_cap"])
        comments.append(c)
        videos.append(v)
        warnings += w
    return pd.concat(comments, ignore_index=True), pd.concat(videos, ignore_index=True), warnings
