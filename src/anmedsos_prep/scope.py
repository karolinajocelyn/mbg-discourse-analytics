"""Cakupan: window waktu, relevansi video YouTube (judul), relevansi tweet X (teks), dan bahasa."""
import re

import numpy as np
import pandas as pd

from .text import normalize_unicode

RELEVANT_X_REASONS = ("keyword_case", "incident_early", "rscm_late", "thread_context")


# ---------------------------------------------------------------- waktu
def add_time(df, cfg, ts_col="created_at"):
    """Tambah kolom waktu relatif terhadap insiden kasus masing-masing (WIB)."""
    df = df.copy()
    ts = pd.to_datetime(df[ts_col], utc=True, format="ISO8601")
    df[ts_col] = ts
    incident = df.kasus.map({k: cfg.incident(k) for k in cfg.cases})
    days = (ts - incident).dt.total_seconds() / 86400
    local = ts.dt.tz_convert(cfg.tz)
    df["days_since_incident"] = days
    df["day"] = np.floor(days).astype(int)
    df["in_window"] = (days >= 0) & (days < cfg.window_days)
    df["date_wib"] = local.dt.strftime("%Y-%m-%d")
    df["hour_wib"] = local.dt.hour
    seg = (df.day // cfg.segment_days + 1).clip(lower=1)
    df["segmen"] = np.where(df.in_window, "S" + seg.astype(str), None)
    phase = pd.Series(None, index=df.index, dtype="object")
    for name, (a, b) in cfg.raw["time"]["phases"].items():
        phase[(df.day >= a) & (df.day < b)] = name
    df["phase"] = phase
    hr = df.kasus.map({k: cfg.health_report(k) for k in cfg.cases})
    has_hr = hr.notna()
    dshr = pd.Series(np.nan, index=df.index)
    dshr[has_hr] = (ts[has_hr] - pd.to_datetime(hr[has_hr], utc=True)).dt.total_seconds() / 86400
    df["days_since_health_report"] = dshr
    df["after_health_report"] = pd.array(np.where(has_hr, dshr >= 0, pd.NA), dtype="boolean")
    return df


# ---------------------------------------------------------------- YouTube: relevansi video
def _lower(s):
    return normalize_unicode(str(s)).lower()


def _first_match(patterns, text):
    for i, p in enumerate(patterns or []):
        if re.search(p, text):
            return i
    return None


def classify_video(title, kasus, day, rules):
    """Kembalikan (level, rule). Urutan: off_topic, sub_kontroversi, inti, other_cases, inti_hari_awal, tidak."""
    r = rules["video"][kasus]
    common = rules["common"]
    t = _lower(title)
    i = _first_match(r.get("off_topic"), t)
    if i is not None:
        return "tidak", f"off_topic:{i}"
    i = _first_match(r.get("sub_kontroversi"), t)
    if i is not None:
        return "sub_kontroversi", f"sub_kontroversi:{i}"
    i = _first_match(r.get("case"), t)
    if i is not None:
        return "inti", f"case:{i}"
    i = _first_match(r.get("other_cases"), t)
    if i is not None:
        return "tidak", f"other_case:{i}"
    if (day is not None and 0 <= day < common["early_days"] and re.search(common["poisoning"], t)
            and re.search(common["program"], t)):
        return "inti_hari_awal", "early"
    return "tidak", "none"


def video_relevance(videos, cfg):
    v = videos.copy()
    inc = v.kasus.map({k: cfg.incident(k) for k in cfg.cases})
    day = np.floor((v.published_at - inc).dt.total_seconds() / 86400).astype(int)
    out = [classify_video(t, k, d, cfg.rules) for t, k, d in zip(v.title, v.kasus, day)]
    v["video_day"] = day
    v["video_relevance"] = [o[0] for o in out]
    v["video_relevance_rule"] = [o[1] for o in out]
    return v


# ---------------------------------------------------------------- X: relevansi teks
def _match_any(patterns, text):
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(re.search(p, text) for p in patterns or [])


def text_relevance(x, cfg, context_text=None):
    """Tandai relevansi tweet X. Tidak membuang baris (D5).

    x: DataFrame tweet unik (kolom: tweet_id, kasus, text, hashtags, day, replied_to_id, quoted_id, conversation_id).
    context_text: dict tweet_id -> teks tweet induk/kutipan dari x_context (opsional).
    """
    rules = cfg.rules["text"]
    common = cfg.rules["common"]
    early = common["early_days"]
    reasons = []
    for text, tags, kasus, day in zip(x.text, x.hashtags, x.kasus, x.day):
        t = _lower(text) + " " + str(tags or "").replace("|", " ")
        is_program = bool(re.search(common["program"], t) or re.search(common["poisoning"], t))
        other = bool(re.search(rules["other_cases"].get(kasus, "(?!x)x"), t))
        if _match_any(rules["case"].get(kasus), t):
            reasons.append("keyword_case")
        elif _match_any(rules.get("incident_early", {}).get(kasus), t):
            reasons.append("incident_early" if (0 <= day < early and is_program and not other) else "ambiguous")
        elif kasus in rules.get("rscm", {}) and re.search(rules["rscm"][kasus]["pattern"], t):
            ok = day >= rules["rscm"][kasus]["min_day"] and is_program and not other
            reasons.append("rscm_late" if ok else "ambiguous")
        else:
            reasons.append("none")
    x = x.copy()
    x["relevance_reason"] = reasons

    # Konteks: tweet yang membalas/mengutip tweet relevan, atau yang tweet induknya (dari x_context) menyebut kasus
    ctx_case = {}
    for tid, txt in (context_text or {}).items():
        ctx_case[tid] = txt
    kasus_of = dict(zip(x.tweet_id, x.kasus))
    for _ in range(5):   # beberapa putaran agar rantai reply ikut terangkat
        relevant = set(x.tweet_id[x.relevance_reason.isin(RELEVANT_X_REASONS)])
        changed = False
        for idx in x.index[~x.relevance_reason.isin(RELEVANT_X_REASONS)]:
            refs = [x.at[idx, "replied_to_id"], x.at[idx, "quoted_id"], x.at[idx, "conversation_id"]]
            refs = [r for r in refs if isinstance(r, str) and r != x.at[idx, "tweet_id"]]
            hit = any(r in relevant and kasus_of.get(r) == x.at[idx, "kasus"] for r in refs)
            if not hit:
                k = x.at[idx, "kasus"]
                hit = any(r in ctx_case and _match_any(rules["case"].get(k), _lower(ctx_case[r])) for r in refs)
            if hit:
                x.at[idx, "relevance_reason"] = "thread_context"
                changed = True
        if not changed:
            break
    x["is_relevant"] = x.relevance_reason.isin(RELEVANT_X_REASONS)
    return x


# ---------------------------------------------------------------- bahasa
def language_ok(x, keep_langs, id_stopwords, min_stop):
    """lang X dipercaya untuk 'in'; selain itu tetap dipakai bila memuat >= min_stop stopword Indonesia."""
    out = []
    for lang, text in zip(x.lang, x.text):
        if lang in keep_langs:
            out.append(True)
            continue
        toks = re.findall(r"[a-z]+", _lower(text))
        out.append(sum(t in id_stopwords for t in toks) >= min_stop)
    return pd.Series(out, index=x.index)
