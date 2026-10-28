import pandas as pd
import yaml

from anmedsos_prep.dedup import flag_duplicates
from anmedsos_prep.features import topic_sample
from conftest import REPO

Q = {"dup_min_tokens": 4, "copypasta_min_authors": 3, "copypasta_min_tokens": 10, "headline_min_authors": 3}


def _docs(rows):
    df = pd.DataFrame(rows, columns=["doc_id", "platform", "kasus", "author_hash", "created_at", "dup_key", "n_urls"])
    df["created_at"] = pd.to_datetime(df.created_at, utc=True)
    return df


def test_headline_shared_by_three_accounts():
    key = "kata istana soal puluhan siswa keracunan"
    df = flag_duplicates(_docs([["x3", "x", "karo", "c", "2026-08-13T03:00Z", key, 1],
                                ["x1", "x", "karo", "a", "2026-08-13T01:00Z", key, 1],
                                ["x2", "x", "karo", "b", "2026-08-13T02:00Z", key, 1]]), Q)
    assert df.is_dup_text.sum() == 3
    assert df.set_index("doc_id").dup_keep.to_dict() == {"x3": False, "x1": True, "x2": False}
    assert df.is_news_headline_share.all()
    assert df.dup_group_id.nunique() == 1


def test_short_slogans_never_flagged():
    df = flag_duplicates(_docs([[f"y{i}", "youtube", "karo", f"a{i}", "2026-08-13T01:00Z", "stop mbg", 0]
                                for i in range(50)]), Q)
    assert not df.is_dup_text.any() and df.dup_keep.all()


def test_self_repeat_and_scope_per_case():
    key = "harus diusut tuntas sampai ke akar"
    df = flag_duplicates(_docs([["a", "youtube", "karo", "u1", "2026-08-13T01:00Z", key, 0],
                                ["b", "youtube", "karo", "u1", "2026-08-13T02:00Z", key, 0],
                                ["c", "youtube", "sukoharjo", "u9", "2025-01-16T01:00Z", key, 0]]), Q)
    d = df.set_index("doc_id")
    assert d.loc["b", "is_self_repeat"] and not d.loc["a", "is_self_repeat"]
    assert not d.loc["a", "is_dup_text"]           # satu penulis saja
    assert d.loc["c", "dup_keep"] and pd.isna(d.loc["c", "dup_group_id"])   # beda kasus, bukan duplikat


def test_tie_break_deterministic():
    key = "teks yang sama persis di detik sama"
    rows = [["b", "x", "karo", "u1", "2026-08-13T01:00Z", key, 0], ["a", "x", "karo", "u2", "2026-08-13T01:00Z", key, 0]]
    d1 = flag_duplicates(_docs(rows), Q).set_index("doc_id").dup_keep
    d2 = flag_duplicates(_docs(rows[::-1]), Q).set_index("doc_id").dup_keep
    assert d1.to_dict() == d2.to_dict() == {"a": True, "b": False}


def test_proposal_keywords_present():
    kw = yaml.safe_load((REPO / "config" / "keywords_rq2.yaml").read_text(encoding="utf-8"))
    import re
    patterns = {n: p for g in kw.values() for n, p in g.items()}
    for term in ("tanggung jawab", "bgn", "kompensasi", "ganti rugi", "evaluasi"):
        assert any(re.search(p, term) for p in patterns.values()), term


def test_topic_sample_caps_per_video_deterministically():
    df = pd.DataFrame({"doc_id": [f"yt_{i}" for i in range(10)] + ["x_1"],
                       "platform": ["youtube"] * 10 + ["x"], "video_id": ["v1"] * 7 + ["v2"] * 3 + [None]})
    elig = pd.Series(True, index=df.index)
    s1 = topic_sample(df, elig, 5, seed=1)
    shuffled = df.sample(frac=1, random_state=3)
    s2 = topic_sample(shuffled, elig.reindex(shuffled.index), 5, seed=1).reindex(df.index)
    assert s1[df.video_id == "v1"].sum() == 5 and s1[df.video_id == "v2"].sum() == 3 and s1.iloc[-1]
    assert s1.equals(s2)
