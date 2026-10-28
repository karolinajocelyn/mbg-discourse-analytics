"""Fitur analisis: kata kunci RQ2, engagement, kedalaman argumentasi, bobot cakupan X, sampel topik YouTube."""
import hashlib
import re

import numpy as np
import pandas as pd

from .config import read_lines
from .text import core_text

RQ2_GROUPS = ("pihak", "penyebab", "tuntutan")
EVIDENCE_RE = re.compile(r"\d|\bdata\b|hasil lab|uji lab|menurut|\bkata\b|sumber|laporan|fakta", re.I)


def keyword_columns(cfg):
    return [name for group in cfg.keywords.values() for name in group]


def add_keywords(df, cfg):
    df = df.copy()
    lower = df.text_clean.str.lower()
    for group, items in cfg.keywords.items():
        for name, pattern in items.items():
            df[name] = lower.str.contains(pattern, regex=True)
    rq2 = [n for g in RQ2_GROUPS for n in cfg.keywords.get(g, {})]
    df["any_kw_rq2"] = df[rq2].any(axis=1)
    return df


def add_depth(df, cfg):
    """Fitur dasar (n_chars, n_tokens, n_sentences) + fitur kedalaman argumentasi RQ3 (menunggu revisi D10)."""
    from .text import n_sentences
    conn = read_lines(cfg.resource("connectives"))
    conn_re = re.compile(r"\b(" + "|".join(re.escape(c) for c in sorted(conn, key=len, reverse=True)) + r")\b")
    df = df.copy()
    core = df.text_clean.map(core_text)
    df["n_chars"] = df.text_clean.str.len()
    df["n_tokens"] = core.str.split().str.len().fillna(0).astype(int)
    df["n_sentences"] = core.map(n_sentences)
    df["n_connectives"] = core.str.lower().map(lambda s: len(conn_re.findall(s)))
    df["connectives_per_100_tokens"] = np.where(df.n_tokens > 0, 100 * df.n_connectives / df.n_tokens.clip(lower=1), 0)
    df["has_question"] = core.str.contains("?", regex=False)
    df["has_evidence_marker"] = core.str.contains(EVIDENCE_RE)
    return df


def add_engagement_pct(df):
    """Persentil dalam platform x kasus: snapshot metrik berbeda umur, jadi nilai mentah tidak dibandingkan."""
    df = df.copy()
    grp = df.groupby(["platform", "kasus"])
    df["like_pct"] = grp.like_count.rank(pct=True, method="average")
    df["engagement_pct"] = grp.engagement.rank(pct=True, method="average")
    df["log1p_engagement"] = np.log1p(df.engagement.astype(float))
    return df


# ---------------------------------------------------------------- bobot cakupan X
def x_coverage(x, counts, cfg):
    """Bobot cakupan per (kueri, hari UTC) = counts / tweet terambil.

    Bucket counts/all per hari UTC, jadi bobot dihitung per hari UTC (bukan WIB): coverage_weight_approx = True.
    Kembalikan (tabel per kueri-hari, Series bobot per tweet berdasarkan primary_query).
    """
    xe = x.assign(utc_day=x.created_at.dt.tz_convert("UTC").dt.floor("D"))
    rows = []
    for q in cfg.raw["x"]["queries"]:
        got = xe[xe.query_ids.str.split("|").map(lambda qs: q in qs)].groupby("utc_day").size()
        c = counts[counts.query_id == q].copy()
        c["utc_day"] = c.start.dt.floor("D")
        c = c.groupby("utc_day").tweet_count.sum()
        days = sorted(set(c.index) | set(got.index))
        for d in days:
            n_counts = int(c.get(d, 0))
            n_got = int(got.get(d, 0))
            rows.append({"query_id": q, "utc_day": d, "counts": n_counts, "collected": n_got,
                         "coverage_weight": max(1.0, n_counts / n_got) if n_got else np.nan})
    table = pd.DataFrame(rows)
    w = table.set_index(["query_id", "utc_day"]).coverage_weight
    per_tweet = pd.Series([w.get((q, d), np.nan) for q, d in zip(xe.primary_query, xe.utc_day)], index=x.index)
    return table, per_tweet


def coverage_summary(table):
    t = table.groupby("query_id").agg(counts=("counts", "sum"), collected=("collected", "sum"))
    covered = table[table.collected > 0].groupby("query_id").agg(counts_on_collected_days=("counts", "sum"))
    weighted = (table.collected * table.coverage_weight.fillna(0)).groupby(table.query_id).sum().rename("weighted")
    t = t.join(covered).join(weighted).fillna(0)
    t["coverage"] = (t.collected / t.counts).round(3)
    t["uncovered_counts"] = t.counts - t.counts_on_collected_days
    return t.reset_index()


# ---------------------------------------------------------------- sampel topik YouTube (D15)
def stable_rank(seed, ids):
    return ids.map(lambda i: hashlib.sha256(f"{seed}|{i}".encode()).hexdigest())


def topic_sample(df, eligible, max_per_video, seed):
    """True untuk maks. N dokumen per video (urutan hash ber-seed, deterministik). X selalu True."""
    out = pd.Series(False, index=df.index)
    out[eligible & (df.platform == "x")] = True
    yt = df[eligible & (df.platform == "youtube")]
    order = yt.assign(_r=stable_rank(seed, yt.doc_id)).sort_values(["video_id", "_r"])
    keep = order.groupby("video_id").cumcount() < max_per_video
    out[keep[keep].index] = True
    return out
