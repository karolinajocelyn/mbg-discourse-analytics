"""End-to-end pada proyek mini: QA lulus, privasi terjaga, view benar, output deterministik."""
import hashlib

import pandas as pd

from anmedsos_prep import qa
from anmedsos_prep.config import load_config
from anmedsos_prep.corpus import view
from anmedsos_prep.pipeline import run
from conftest import SALT, make_project


def test_qa_passes(built):
    cfg, res = built
    failures, report = qa.run_checks(res, cfg)
    assert failures == [], failures
    assert "LULUS" in report


def test_privacy_in_corpus(built):
    _, res = built
    c = res["corpus"]
    text = pd.concat([c[col].dropna().astype(str) for col in ("text_raw_masked", "text_clean", "parent_text_clean")])
    assert not text.str.contains(r"(?i)febi|agnesia").any()
    assert not text.str.contains(r"@(?!user\b)\w").any()
    assert "author_id" not in c.columns and "in_reply_to_user_id" not in c.columns
    assert (c.loc[c.platform == "x", "author_hash"].str.len() == 16).all()


def test_attrition_and_scope(built):
    _, res = built
    c = res["corpus"].set_index("doc_id")
    assert "yt_k7" not in c.index                         # di luar window
    assert c.loc["yt_k8", "is_spam"] and not c.loc["yt_k8", "in_v_volume"]
    assert c.loc["yt_k9", "video_relevance"] == "sub_kontroversi" and not c.loc["yt_k9", "in_v_volume"]
    assert c.loc["yt_k10", "video_relevance"] == "tidak"
    assert c.loc["x_101", "relevance_reason"] == "thread_context"
    assert c.loc["x_200", "relevance_reason"] == "rscm_late"
    assert c.loc["x_201", "relevance_reason"] == "ambiguous" and not c.loc["x_201", "in_v_volume"]
    assert c.loc["x_400", "relevance_reason"] == "incident_early"
    assert c.loc["x_401", "relevance_reason"] == "ambiguous"
    assert not bool(c.loc["x_107", "context_available"])  # induk 998 tidak tersedia


def test_views(built):
    cfg, res = built
    c = res["corpus"].set_index("doc_id")
    # slogan pendek: masuk semua view stance, bukan duplikat
    assert c.loc[["yt_k1", "yt_k2", "yt_k3"], "in_v_stance"].all()
    # emoji-only: sentimen ya, stance tidak
    assert c.loc["yt_k4", "in_v_sentiment"] and not c.loc["yt_k4", "in_v_stance"]
    # judul berita kembar: volume 3, sentimen 1
    heads = c.loc[["x_102", "x_103", "x_104"]]
    assert heads.in_v_volume.sum() == 3 and heads.in_v_sentiment.sum() == 1
    assert c.loc["x_105", "kw_tanggung_jawab"] and c.loc["x_105", "kw_kompensasi"] and c.loc["x_105", "in_v_rq2"]
    v = view(res["corpus"], "v_volume", cfg)
    assert v[v.platform == "youtube"].groupby("video_id").video_weight.sum().round(6).eq(1).all()
    sens = view(res["corpus"], "v_volume", cfg, include_sub=True)
    assert "yt_k9" in set(sens.doc_id)


def _hashes(d):
    return {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file() and p.name != "manifest.json"}


def test_run_is_deterministic(tmp_path):
    cfg = load_config(make_project(tmp_path / "proj"))
    out1, _ = run(cfg, SALT, out_root=tmp_path / "o1", log=lambda *_: None, latest=False)
    out2, _ = run(cfg, SALT, out_root=tmp_path / "o2", log=lambda *_: None, latest=False)
    h1, h2 = _hashes(out1), _hashes(out2)
    assert h1 == h2 and "corpus_all.parquet" in h1 and "views/v_topic.parquet" in h1
