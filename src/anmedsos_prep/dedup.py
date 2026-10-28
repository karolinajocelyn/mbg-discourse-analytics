"""Deduplikasi ID dan penandaan near-duplicate (ditandai, tidak dibuang)."""
import hashlib

import numpy as np
import pandas as pd

from .load_x import LoadError


def dedup_x(tweets, query_order):
    """Satu baris per tweet_id. Metrik diambil dari file dengan mtime terbaru (tie-break nama file)."""
    if tweets.groupby("tweet_id").kasus.nunique().max() > 1:
        raise LoadError("ada tweet yang muncul di dua kasus berbeda")
    rank = {q: i for i, q in enumerate(query_order)}
    agg = tweets.groupby("tweet_id").agg(
        query_ids=("query_id", lambda s: "|".join(sorted(set(s)))),
        n_source_files=("source_file", "nunique"),
        primary_query=("query_id", lambda s: min(set(s), key=lambda q: rank.get(q, len(rank)))),
    )
    latest = (tweets.sort_values(["tweet_id", "file_mtime", "source_file"])
              .drop_duplicates("tweet_id", keep="last")
              .drop(columns=["query_id", "slice", "page_index"])
              .set_index("tweet_id"))
    out = latest.join(agg).reset_index()
    return out.sort_values("tweet_id").reset_index(drop=True)


def _group_id(platform, kasus, key):
    return hashlib.sha1(f"{platform}|{kasus}|{key}".encode()).hexdigest()[:12]


def flag_duplicates(df, q):
    """Tambah dup_group_id, is_dup_text, is_self_repeat, is_copypasta, dup_keep, is_news_headline_share.

    Ruang lingkup per platform x kasus. Teks dengan < q['dup_min_tokens'] token tidak pernah ditandai
    (slogan pendek seperti "stop mbg" adalah ekspresi sah, bukan duplikat).
    """
    df = df.copy()
    ntok = df.dup_key.str.split().str.len().fillna(0)
    eligible = ntok >= q["dup_min_tokens"]
    key = df.dup_key.where(eligible)
    gcols = [df.platform, df.kasus, key]
    size = df.groupby(gcols, dropna=True).doc_id.transform("size")
    n_auth = df.groupby(gcols, dropna=True).author_hash.transform("nunique")
    in_group = eligible & (size > 1)
    df["dup_group_id"] = pd.Series(
        [_group_id(p, k, t) if g else None for p, k, t, g in zip(df.platform, df.kasus, df.dup_key, in_group)],
        index=df.index, dtype="string")
    df["is_dup_text"] = in_group & (n_auth >= 2)
    df["is_copypasta"] = in_group & (n_auth >= q["copypasta_min_authors"]) & (ntok >= q["copypasta_min_tokens"])
    order = df.sort_values(["created_at", "doc_id"]).index
    first = ~df.loc[order].duplicated(["platform", "kasus", "dup_key"])
    df["dup_keep"] = ~in_group | first.reindex(df.index)
    self_rep = df.loc[order].duplicated(["platform", "kasus", "author_hash", "dup_key"]).reindex(df.index)
    df["is_self_repeat"] = in_group & self_rep & (df.author_hash != "")
    # X: judul berita yang dibagikan banyak akun (semua anggota grup ber-URL)
    all_url = df.groupby(gcols, dropna=True).n_urls.transform(lambda s: bool((s.fillna(0) > 0).all()))
    df["is_news_headline_share"] = (in_group & (df.platform == "x") & (n_auth >= q["headline_min_authors"])
                                    & all_url.fillna(False).astype(bool))
    for c in ("is_dup_text", "is_copypasta", "dup_keep", "is_self_repeat", "is_news_headline_share"):
        df[c] = df[c].fillna(False).astype(bool)
    return df
