"""Flag kualitas: kosong, emoji-only, low-content, spam, akun hiperaktif, teks sangat panjang."""
import re

import numpy as np
import pandas as pd

from .config import read_lines
from .text import alpha_tokens, core_text, has_letters

SPAM_RE = re.compile(r"\bslot\b|gacor|maxwin|togel|judol|wa\.me|whatsapp|cek bio|link di bio|sub balik|"
                     r"subscribe balik|pinjol", re.I)


def flag_quality(df, cfg):
    q = cfg.raw["quality"]
    slogans = [re.compile(p) for p in read_lines(cfg.resource("slogans"))]
    df = df.copy()
    df["is_empty"] = df.text_clean.map(lambda s: core_text(s) == "")
    df["is_emoji_only"] = ~df.is_empty & ~df.text_clean.map(has_letters)
    plain = df.text_clean.map(lambda s: re.sub(r"[^a-z\s]", " ", core_text(s).lower())).str.split().str.join(" ")
    is_slogan = plain.map(lambda s: any(p.search(s) for p in slogans))
    n_alpha = df.text_clean.map(lambda s: len(alpha_tokens(s)))
    df["n_alpha_tokens"] = n_alpha
    df["is_low_content"] = ~df.is_empty & ~df.is_emoji_only & (n_alpha <= q["low_content_max_tokens"]) & ~is_slogan
    df["is_slogan"] = is_slogan
    df["is_spam"] = df.text_raw_masked.str.contains(SPAM_RE)

    act = df.groupby(["platform", "kasus", "author_hash"]).doc_id.transform("size")
    df["author_activity"] = np.where(df.author_hash == "", 0, act)
    thr = (df[df.author_hash != ""].groupby(["platform", "kasus", "author_hash"]).size()
           .groupby(level=[0, 1]).quantile(q["hyperactive_quantile"]))
    thr = thr.clip(lower=q["hyperactive_min_docs"])
    key = list(zip(df.platform, df.kasus))
    df["hyperactive_threshold"] = [thr.get(k, np.inf) for k in key]
    df["is_hyperactive_author"] = (df.author_hash != "") & (df.author_activity >= df.hyperactive_threshold)

    n_chars = df.text_clean.str.len()
    p99 = n_chars.groupby(df.platform).transform(lambda s: s.quantile(q["very_long_quantile"]))
    df["is_very_long"] = n_chars > p99
    return df.drop(columns=["hyperactive_threshold"])
