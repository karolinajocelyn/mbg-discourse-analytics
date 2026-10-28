"""Orkestrasi: raw X + YouTube -> korpus terpadu, view per analisis, laporan QA."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import qa
from .attrition import Attrition
from .config import read_lines
from .corpus import COLUMN_DOCS, VIEWS, data_dictionary_md, view, view_mask
from .dedup import dedup_x, flag_duplicates
from .features import (add_depth, add_engagement_pct, add_keywords, coverage_summary, keyword_columns, topic_sample,
                       x_coverage)
from .load_x import file_stats, load_x_context, load_x_counts, load_x_raw
from .load_youtube import load_youtube
from .manifest import build_manifest
from .pseudonymize import hash_series
from .quality import flag_quality
from .scope import add_time, language_ok, text_relevance, video_relevance
from .text import TopicNormalizer, VictimMasker, clean_text, core_text, dup_key, has_letters, mask_raw


def _clean_lookup(texts, platform, masker):
    return {k: clean_text(v, platform, masker) for k, v in texts.items()}


def _context_ok(t):
    return isinstance(t, str) and core_text(t) != "" and has_letters(t)


# ---------------------------------------------------------------- X
def prepare_x(cfg, salt, masker, att, log):
    xc = cfg.raw["x"]
    tweets, pages = load_x_raw(cfg.p(cfg.raw["paths"]["x_raw"]), allowed_queries=set(xc["queries"]))
    stats = {**file_stats(pages), "rows": len(tweets), "unique": int(tweets.tweet_id.nunique())}
    log(f"X: {stats['rows']} baris, {stats['unique']} tweet unik, {stats['pages']} halaman")
    for k, g in tweets.groupby("kasus"):
        att.log("x", k, "raw (tweet x file)", len(g), len(g))
    x = dedup_x(tweets, xc["queries"])
    for k in sorted(x.kasus.unique()):
        att.log("x", k, "dedup tweet_id", (tweets.kasus == k).sum(), (x.kasus == k).sum(),
                "potongan file tumpang tindih & tweet di >1 kueri")
    x = add_time(x, cfg)
    before = x
    x = x[x.in_window].copy()
    att.log_df("x", "window 45 hari", before, x)

    ctx, ctx_err = load_x_context(cfg.p(cfg.raw["paths"]["x_context"]))
    all_text = dict(zip(tweets.tweet_id, tweets.text))
    all_text.update({t: v for t, v in zip(ctx.tweet_id, ctx.text) if t not in all_text})
    x = text_relevance(x, cfg, context_text=all_text)

    from Sastrawi.StopWordRemover.StopWordRemoverFactory import StopWordRemoverFactory
    id_stop = set(StopWordRemoverFactory().get_stop_words())
    x["lang_ok"] = language_ok(x, set(xc["keep_langs"]), id_stop, xc["min_id_stopwords_for_other_lang"])

    x["author_hash"] = hash_series(x.author_id, salt)
    x["in_reply_to_hash"] = hash_series(x.in_reply_to_user_id, salt)
    x["text_raw_masked"] = x.text.map(lambda s: mask_raw(s, "x", masker))
    x["text_clean"] = x.text.map(lambda s: clean_text(s, "x", masker))

    needed = set(x.replied_to_id.dropna()) | set(x.quoted_id.dropna())
    lookup = _clean_lookup({k: v for k, v in all_text.items() if k in needed}, "x", masker)
    x["parent_text_clean"] = x.replied_to_id.map(lookup).astype("string")
    x["quoted_text_clean"] = x.quoted_id.map(lookup).astype("string")
    x["context_required"] = x.tweet_type != "original"
    ok_parent = x.replied_to_id.isna() | x.parent_text_clean.map(_context_ok)
    ok_quote = x.quoted_id.isna() | x.quoted_text_clean.map(_context_ok)
    x["context_available"] = ok_parent.astype(bool) & ok_quote.astype(bool)
    x["is_maybe_truncated"] = x.text.str.rstrip().str.endswith("…")
    x["metrics_snapshot_date"] = x.file_mtime.str[:10]
    x["engagement"] = x.like_count + x.retweet_count + x.quote_count + x.reply_count

    counts = load_x_counts(cfg.p(cfg.raw["paths"]["x_counts"]), xc["queries"])
    cov_table, x["coverage_weight"] = x_coverage(x, counts, cfg)
    x["coverage_weight_approx"] = True

    # Data identitas akun asli tidak dibawa ke tahap berikutnya
    x = x.drop(columns=["author_id", "in_reply_to_user_id", "text"])
    ctx_stats = {"requested_missing": len(ctx) + len(ctx_err), "fetched": len(ctx), "unavailable": len(ctx_err),
                 "unavailable_by_reason": ctx_err.error.value_counts().to_dict()}
    return x, stats, cov_table, ctx_stats


# ---------------------------------------------------------------- YouTube
def prepare_youtube(cfg, masker, att, log):
    yt, videos, warnings = load_youtube(cfg)
    log(f"YouTube: {len(yt)} komentar dari {yt.video_id.nunique()} video")
    for k, g in yt.groupby("kasus"):
        att.log("youtube", k, "raw", len(g), len(g))
    yt = add_time(yt, cfg)
    mismatch = int((yt.in_window != yt.in_window_collector).sum())
    if mismatch:
        raise qa.QAError(f"{mismatch} komentar: flag in_window collector berbeda dengan hitungan window")
    before = yt
    yt = yt[yt.in_window].copy()
    att.log_df("youtube", "window 45 hari", before, yt)

    videos = video_relevance(videos, cfg)
    yt = yt.merge(videos[["video_id", "kasus", "video_relevance", "video_relevance_rule"]],
                  on=["video_id", "kasus"], how="left", validate="many_to_one")
    yt["hours_since_video"] = (yt.created_at - yt.video_published_at).dt.total_seconds() / 3600

    yt["text_raw_masked"] = yt.text.map(lambda s: mask_raw(s, "youtube", masker))
    yt["text_clean"] = yt.text.map(lambda s: clean_text(s, "youtube", masker))
    parent_lookup = dict(zip(yt.comment_id, yt.text_clean))
    yt["parent_text_clean"] = yt.parent_id.map(parent_lookup).astype("string")
    yt["context_required"] = yt.is_reply
    yt["context_available"] = ~yt.is_reply | yt.parent_text_clean.map(_context_ok).astype(bool)
    yt["video_title_masked"] = yt.video_title.map(lambda s: masker(str(s)))
    yt["metrics_snapshot_date"] = yt.collected_at.dt.strftime("%Y-%m-%d")
    yt["engagement"] = yt.like_count + yt.reply_count
    yt = yt.drop(columns=["text"])

    videos["title_masked"] = videos.title.map(lambda s: masker(str(s)))
    return yt, videos, warnings


# ---------------------------------------------------------------- korpus
def unify(x, yt, cfg):
    cx = pd.DataFrame({
        "doc_id": "x_" + x.tweet_id, "platform": "x", "kasus": x.kasus, "doc_type": x.tweet_type,
        "source_id": x.tweet_id, "thread_id": x.conversation_id, "parent_id": x.replied_to_id,
        "quoted_id": x.quoted_id, "query_ids": x.query_ids, "primary_query": x.primary_query,
        "n_source_files": x.n_source_files, "in_reply_to_hash": x.in_reply_to_hash,
        "quoted_text_clean": x.quoted_text_clean, "relevance_reason": x.relevance_reason,
        "is_relevant": x.is_relevant, "lang": x.lang, "lang_ok": x.lang_ok, "hashtags": x.hashtags,
        "n_urls": x.n_urls, "has_media": x.has_media, "retweet_count": x.retweet_count,
        "quote_count": x.quote_count, "impression_count": x.impression_count, "edit_count": x.edit_count,
        "is_maybe_truncated": x.is_maybe_truncated, "possibly_sensitive": x.possibly_sensitive,
        "coverage_weight": x.coverage_weight, "coverage_weight_approx": x.coverage_weight_approx,
    })
    cy = pd.DataFrame({
        "doc_id": "yt_" + yt.comment_id, "platform": "youtube", "kasus": yt.kasus,
        "doc_type": np.where(yt.is_reply, "yt_reply", "yt_comment"), "source_id": yt.comment_id,
        "thread_id": yt.thread_id, "parent_id": yt.parent_id, "video_id": yt.video_id,
        "hours_since_video": yt.hours_since_video, "video_title_masked": yt.video_title_masked,
        "channel_type_norm": yt.channel_type_norm, "video_relevance": yt.video_relevance,
        "video_relevance_rule": yt.video_relevance_rule, "relevan_lama": yt.relevan_lama,
        "is_relevant": yt.video_relevance.isin(cfg.raw["youtube"]["main_relevance_levels"]), "batch": yt.batch,
        "video_thread_capped": yt.video_thread_capped, "video_coverage_ratio": yt.video_coverage_ratio,
        "comment_before_video": yt.comment_before_video,
    })
    shared = ["author_hash", "created_at", "date_wib", "hour_wib", "days_since_incident", "day", "segmen", "phase",
              "days_since_health_report", "after_health_report", "text_raw_masked", "text_clean",
              "parent_text_clean", "context_required", "context_available", "like_count", "reply_count",
              "engagement", "metrics_snapshot_date"]
    for col in shared:
        cx[col] = x[col].values
        cy[col] = yt[col].values
    c = pd.concat([cx, cy], ignore_index=True)
    # kolom boolean yang hanya ada di satu platform: NA untuk platform lain, bukan object campuran
    for col in ("lang_ok", "has_media", "is_maybe_truncated", "possibly_sensitive", "coverage_weight_approx",
                "video_thread_capped", "comment_before_video", "context_required", "context_available"):
        c[col] = c[col].astype("boolean")
    c["in_scope_main"] = np.where(c.platform == "x", c.is_relevant & c.lang_ok.fillna(False).astype(bool),
                                  c.is_relevant).astype(bool)
    c["is_relevant"] = c.is_relevant.astype(bool)
    return c


def build(cfg, salt, log=print):
    """Jalankan semua tahap; kembalikan dict berisi DataFrame dan metadata (belum ditulis ke disk)."""
    att = Attrition()
    masker = VictimMasker.from_file(cfg.resource("victim_names"))
    x, x_stats, cov_table, ctx_stats = prepare_x(cfg, salt, masker, att, log)
    yt, videos, warnings = prepare_youtube(cfg, masker, att, log)

    c = unify(x, yt, cfg)
    c["dup_key"] = c.text_clean.map(dup_key)
    c = flag_quality(c, cfg)
    before = c
    c = c[~c.is_empty].copy()
    att.log_df("x", "teks kosong setelah clean", before[before.platform == "x"], c[c.platform == "x"])
    att.log_df("youtube", "teks kosong setelah clean", before[before.platform == "youtube"],
               c[c.platform == "youtube"])
    c = flag_duplicates(c, cfg.raw["quality"])
    c = add_keywords(c, cfg)
    c = add_depth(c, cfg)
    log("Normalisasi text_topic (Sastrawi)...")
    norm = TopicNormalizer.from_config(cfg)
    c["text_topic_nostem"] = c.text_clean.map(lambda s: norm.normalize(s, stem=False))
    c["text_topic"] = c.text_clean.map(lambda s: norm.normalize(s, stem=True))
    c["is_empty_topic"] = c.text_topic.str.strip() == ""
    c = add_engagement_pct(c)

    stance_eligible = view_mask(c.assign(topic_sample=True), "v_stance", cfg) & ~c.is_empty_topic
    c["topic_sample"] = topic_sample(c, stance_eligible, cfg.raw["youtube"]["topic_max_per_video"], cfg.seed)
    for name in VIEWS:
        c["in_" + name] = view_mask(c, name, cfg)

    # Attrition per view (dari korpus non-kosong)
    for platform in ("x", "youtube"):
        cp = c[c.platform == platform]
        steps = [("relevan (+ bahasa X)", cp.in_scope_main),
                 ("bukan spam", cp.in_scope_main & ~cp.is_spam),
                 ("view v_sentiment: dup_keep", cp.in_v_sentiment),
                 ("view v_stance: tanpa emoji-only & low-content", cp.in_v_stance),
                 ("view v_topic: sampel <= 200/video & topik tidak kosong", cp.in_v_topic),
                 ("view v_rq2: ada kata kunci RQ2", cp.in_v_rq2)]
        for k in sorted(cp.kasus.unique()):
            prev = int((cp.kasus == k).sum())
            for step, mask in steps:
                n = int((mask & (cp.kasus == k)).sum())
                att.log(platform, k, step, prev, n)
                if not step.startswith("view v_rq2"):
                    prev = n

    kw = keyword_columns(cfg)
    order = [col for col in COLUMN_DOCS if col in c.columns] + kw
    c = c[order].sort_values(["platform", "kasus", "created_at", "doc_id"]).reset_index(drop=True)

    return {
        "corpus": c, "x": x, "yt": yt, "videos": videos, "attrition": att.frame(), "x_stats": x_stats,
        "coverage_table": cov_table, "coverage_summary": coverage_summary(cov_table), "ctx_stats": ctx_stats,
        "warnings": warnings, "masker": masker,
    }


# ---------------------------------------------------------------- tulis output
def _csv(df, path):
    df.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def _parquet(df, path):
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].astype("string")
    out.to_parquet(path, index=False, engine="pyarrow")


def write_outputs(res, cfg, out_dir, manifest):
    out_dir = Path(out_dir)
    (out_dir / "views").mkdir(parents=True, exist_ok=True)
    c = res["corpus"]
    _csv(c, out_dir / "corpus_all.csv")
    _parquet(c, out_dir / "corpus_all.parquet")
    _parquet(c[c.platform == "x"].dropna(axis=1, how="all"), out_dir / "x_clean.parquet")
    _parquet(c[c.platform == "youtube"].dropna(axis=1, how="all"), out_dir / "yt_clean.parquet")
    for name in VIEWS:
        _parquet(view(c, name, cfg), out_dir / "views" / f"{name}.parquet")
    _csv(c.loc[c.is_emoji_only, ["doc_id", "platform", "kasus", "created_at", "text_clean", "in_v_sentiment"]],
         out_dir / "emoji_only.csv")
    _csv(res["attrition"], out_dir / "attrition_log.csv")
    vcols = ["kasus", "video_id", "title_masked", "channel_title", "published_at", "video_day", "comment_count",
             "n_comments_collected", "n_threads_collected", "video_coverage_ratio", "video_thread_capped",
             "relevan", "video_relevance", "video_relevance_rule"]
    _csv(res["videos"][vcols].sort_values(["kasus", "video_id"]), out_dir / "video_relevance.csv")
    _csv(res["coverage_table"].assign(utc_day=res["coverage_table"].utc_day.dt.strftime("%Y-%m-%d")),
         out_dir / "coverage_x.csv")
    _csv(res["coverage_summary"], out_dir / "coverage_x_summary.csv")
    (out_dir / "data_dictionary.md").write_text(data_dictionary_md(), encoding="utf-8", newline="\n")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
                                           encoding="utf-8", newline="\n")


def run(cfg, salt, out_root=None, log=print, latest=True):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root = Path(out_root or cfg.p(cfg.raw["paths"]["output_dir"]))
    out_dir = out_root / run_id
    res = build(cfg, salt, log=log)
    failures, report = qa.run_checks(res, cfg)
    manifest = build_manifest(cfg, salt, run_id)
    manifest["qa_passed"] = not failures
    write_outputs(res, cfg, out_dir, manifest)
    (out_dir / "qa_report.md").write_text(report, encoding="utf-8", newline="\n")
    if failures:
        raise qa.QAError("QA gagal:\n- " + "\n- ".join(failures) + f"\nLihat {out_dir / 'qa_report.md'}")
    if latest:
        dst = out_root / "latest"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(out_dir, dst)
    log(f"Selesai: {out_dir}")
    return out_dir, res
