"""Baca respons mentah X API (JSONL per halaman) menjadi DataFrame datar."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

FNAME_RE = re.compile(r"^x_(?P<kasus>[a-z]+)_(?P<query_id>X[A-Za-z0-9]+?)_(?P<slice>[DS][A-Za-z0-9]+)\.jsonl$")

X_COLUMNS = [
    "tweet_id", "kasus", "query_id", "slice", "source_file", "page_index", "file_mtime", "created_at",
    "author_id", "conversation_id", "in_reply_to_user_id", "replied_to_id", "quoted_id", "tweet_type", "lang",
    "text", "like_count", "retweet_count", "reply_count", "quote_count", "impression_count", "bookmark_count",
    "hashtags", "n_mentions", "n_urls", "has_media", "context_domains", "possibly_sensitive", "edit_count",
]


class LoadError(Exception):
    pass


def tweet_type(t):
    types = {r["type"] for r in t.get("referenced_tweets", []) or []}
    if {"replied_to", "quoted"} <= types:
        return "quote_reply"
    if "replied_to" in types:
        return "reply"
    if "quoted" in types:
        return "quote"
    return "original"


def _ref(t, kind):
    for r in t.get("referenced_tweets", []) or []:
        if r["type"] == kind:
            return r["id"]
    return None


def flatten_tweet(t):
    pm = t.get("public_metrics", {}) or {}
    ent = t.get("entities", {}) or {}
    domains = sorted({a["domain"]["name"] for a in t.get("context_annotations", []) or [] if "domain" in a})
    return {
        "tweet_id": t["id"],
        "created_at": t["created_at"],
        "author_id": t.get("author_id"),
        "conversation_id": t.get("conversation_id"),
        "in_reply_to_user_id": t.get("in_reply_to_user_id"),
        "replied_to_id": _ref(t, "replied_to"),
        "quoted_id": _ref(t, "quoted"),
        "tweet_type": tweet_type(t),
        "lang": t.get("lang"),
        "text": t.get("text", "") or "",
        "like_count": pm.get("like_count", 0),
        "retweet_count": pm.get("retweet_count", 0),
        "reply_count": pm.get("reply_count", 0),
        "quote_count": pm.get("quote_count", 0),
        "impression_count": pm.get("impression_count"),
        "bookmark_count": pm.get("bookmark_count", 0),
        # hashtag dari entities, bukan regex (lebih akurat untuk hashtag beraksara campur)
        "hashtags": "|".join(sorted({h["tag"].lower() for h in ent.get("hashtags", []) or []})),
        "n_mentions": len(ent.get("mentions", []) or []),
        "n_urls": len(ent.get("urls", []) or []),
        "has_media": "attachments" in t,
        "context_domains": "|".join(domains),
        "possibly_sensitive": bool(t.get("possibly_sensitive", False)),
        "edit_count": len(t.get("edit_history_tweet_ids", []) or [t["id"]]),
    }


def load_x_raw(raw_dir, allowed_queries=None):
    """Kembalikan (tweets, pages). tweets: satu baris per (tweet x file). pages: satu baris per halaman respons."""
    raw_dir = Path(raw_dir)
    files = sorted(raw_dir.glob("*.jsonl"))
    if not files:
        raise LoadError(f"tidak ada file JSONL di {raw_dir}")
    rows, pages = [], []
    for path in files:
        m = FNAME_RE.match(path.name)
        if not m:
            raise LoadError(f"nama file X tidak sesuai pola x_<kasus>_<kueri>_<slice>.jsonl: {path.name}")
        meta = m.groupdict()
        if allowed_queries is not None and meta["query_id"] not in allowed_queries:
            raise LoadError(f"kueri {meta['query_id']} ({path.name}) tidak terdaftar di config x.queries")
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with path.open(encoding="utf-8") as f:
            for page_index, line in enumerate(l for l in f if l.strip()):
                page = json.loads(line)
                data = page.get("data") or []
                pages.append({"source_file": path.name, **meta, "page_index": page_index,
                              "result_count": page.get("meta", {}).get("result_count", len(data))})
                for t in data:
                    rows.append({**flatten_tweet(t), **meta, "source_file": path.name,
                                 "page_index": page_index, "file_mtime": mtime})
    tweets = pd.DataFrame(rows, columns=X_COLUMNS)
    for c in ("tweet_id", "author_id", "conversation_id", "in_reply_to_user_id", "replied_to_id", "quoted_id"):
        tweets[c] = tweets[c].astype("string")
    pages = pd.DataFrame(pages)
    return tweets, pages


def file_stats(pages):
    per_file = pages.groupby("source_file").result_count.sum()
    return {"files": int(per_file.size), "empty_files": int((per_file == 0).sum()), "pages": int(len(pages))}


def load_x_context(path):
    """Tweet induk/kutipan dari x_context.py. Kembalikan (tweets, errors)."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["tweet_id", "author_id", "created_at", "lang", "text"]), pd.DataFrame(
            columns=["tweet_id", "error"])
    rows, errors = [], []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            resp = json.loads(line)
            for t in resp.get("data", []) or []:
                rows.append({"tweet_id": t["id"], "author_id": t.get("author_id"), "created_at": t.get("created_at"),
                             "lang": t.get("lang"), "text": t.get("text", "") or ""})
            for e in resp.get("errors", []) or []:
                errors.append({"tweet_id": e.get("resource_id") or e.get("value"), "error": e.get("title")})
    ctx = pd.DataFrame(rows).drop_duplicates("tweet_id")
    ctx["tweet_id"] = ctx.tweet_id.astype("string")
    return ctx, pd.DataFrame(errors, columns=["tweet_id", "error"])


def load_x_counts(counts_dir, queries):
    """Volume per bucket (hari UTC) dari counts/all. Kolom: query_id, start, end, tweet_count."""
    out = []
    for q in queries:
        f = Path(counts_dir) / f"{q}.json"
        if not f.exists():
            raise LoadError(f"file counts tidak ada: {f}")
        for page in json.loads(f.read_text(encoding="utf-8")):
            for b in page.get("data", []):
                out.append({"query_id": q, "start": b["start"], "end": b["end"], "tweet_count": b["tweet_count"]})
    df = pd.DataFrame(out).drop_duplicates(["query_id", "start"])
    df["start"] = pd.to_datetime(df.start, utc=True, format="ISO8601")
    df["end"] = pd.to_datetime(df.end, utc=True, format="ISO8601")
    return df.sort_values(["query_id", "start"]).reset_index(drop=True)
