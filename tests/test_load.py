import pandas as pd
import pytest

from anmedsos_prep.dedup import dedup_x
from anmedsos_prep.load_x import LoadError, file_stats, load_x_context, load_x_raw
from anmedsos_prep.load_youtube import load_case, load_youtube
from conftest import write_jsonl, page, tw


def test_x_overlap_dedup_and_empty_pages(cfg):
    tweets, pages = load_x_raw(cfg.p("x/raw"))
    stats = file_stats(pages)
    assert stats["empty_files"] == 1
    assert (tweets.tweet_id == "100").sum() == 2
    x = dedup_x(tweets, cfg.raw["x"]["queries"])
    assert x.tweet_id.is_unique
    row = x[x.tweet_id == "100"].iloc[0]
    assert row.n_source_files == 2
    assert row.query_ids == "XK1b"


def test_x_quote_reply_not_merged(cfg):
    tweets, _ = load_x_raw(cfg.p("x/raw"))
    assert tweets.loc[tweets.tweet_id == "107", "tweet_type"].iloc[0] == "quote_reply"
    assert tweets.loc[tweets.tweet_id == "101", "tweet_type"].iloc[0] == "reply"


def test_x_bad_filename_is_error(cfg):
    write_jsonl(cfg.p("x/raw/karo_salah.jsonl"), [page([])])
    with pytest.raises(LoadError, match="nama file"):
        load_x_raw(cfg.p("x/raw"))


def test_x_unknown_query_is_error(cfg):
    write_jsonl(cfg.p("x/raw/x_karo_XK9_D00.jsonl"), [page([tw("1", "2026-08-13T00:00:00.000Z", "a")])])
    with pytest.raises(LoadError, match="tidak terdaftar"):
        load_x_raw(cfg.p("x/raw"), allowed_queries=set(cfg.raw["x"]["queries"]))


def test_x_tweet_in_two_cases_is_error(cfg):
    write_jsonl(cfg.p("x/raw/x_sukoharjo_XS1_S2.jsonl"), [page([tw("100", "2025-01-20T00:00:00.000Z", "x")])])
    tweets, _ = load_x_raw(cfg.p("x/raw"))
    with pytest.raises(LoadError, match="dua kasus"):
        dedup_x(tweets, cfg.raw["x"]["queries"])


def test_x_context_loaded_with_errors(cfg):
    ctx, err = load_x_context(cfg.p("x/context/x_context.jsonl"))
    assert list(ctx.tweet_id) == ["999"]
    assert list(err.tweet_id) == ["998"]


def test_youtube_ids_stay_string_and_meta_joined(cfg):
    c, v, warnings = load_youtube(cfg)
    assert "-vidA" in set(c.video_id)
    assert c.comment_id.map(type).eq(str).all()
    assert any("sukoharjo: kolom channel_type kosong" in w for w in warnings)
    assert c.loc[c.comment_id == "k6", "is_reply"].item()
    assert c.loc[c.comment_id == "k6", "thread_id"].item() == "k5"
    assert set(c.batch) == {"awal", "tambahan"}


def test_youtube_orphan_reply_detected(cfg):
    p = cfg.p("youtube/comments_karo.csv")
    df = pd.read_csv(p, dtype=str, keep_default_na=False)
    df.loc[df.comment_id == "k6", "parent_id"] = "hilang"
    df.to_csv(p, index=False)
    with pytest.raises(LoadError, match="tanpa komentar induk"):
        load_youtube(cfg)


def test_youtube_missing_file_is_error(cfg):
    cfg.p("youtube/comments_karo.csv").unlink()
    with pytest.raises(LoadError, match="tidak ditemukan"):
        load_youtube(cfg)


def test_youtube_thread_cap_flag(cfg):
    p = cfg.raw["paths"]["youtube"]["karo"]
    c, v, _ = load_case(cfg.p(p["comments"]), cfg.p(p["candidates"]), "karo", {}, thread_cap=3)
    assert v.set_index("video_id").loc["-vidA", "video_thread_capped"]
    assert not v.set_index("video_id").loc["vidB", "video_thread_capped"]
