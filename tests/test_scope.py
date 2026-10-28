import pandas as pd

from anmedsos_prep.scope import add_time, classify_video, text_relevance


def _df(kasus, ts):
    return pd.DataFrame({"kasus": [kasus] * len(ts), "created_at": ts})


def test_window_boundaries_wib(cfg):
    # Karo: insiden 2026-08-13 00:00 WIB = 2026-08-12T17:00Z; hari 45 dimulai 2026-09-27 00:00 WIB
    df = add_time(_df("karo", ["2026-08-12T16:59:59Z", "2026-08-12T17:00:00Z", "2026-09-26T16:59:59Z",
                               "2026-09-26T17:00:00Z"]), cfg)
    assert list(df.in_window) == [False, True, True, False]
    assert list(df.day) == [-1, 0, 44, 45]
    assert df.segmen.tolist()[1:3] == ["S1", "S5"]


def test_phase_and_health_report(cfg):
    df = add_time(_df("karo", ["2026-08-14T00:00:00Z", "2026-08-25T00:00:00Z", "2026-09-07T16:59:00Z",
                               "2026-09-07T17:00:00Z"]), cfg)
    assert df.phase.tolist() == ["awal", "tengah", "tengah", "lanjut"]
    assert df.days_since_health_report.iloc[2] < 0 <= df.days_since_health_report.iloc[3]
    assert df.after_health_report.tolist() == [False, False, False, True]
    s = add_time(_df("sukoharjo", ["2025-01-16T00:00:00Z"]), cfg)
    assert pd.isna(s.after_health_report.iloc[0])


def test_video_rule_levels(cfg):
    r = cfg.rules
    assert classify_video("Siswi Berastagi kehilangan ingatan", "karo", 30, r)[0] == "inti"
    assert classify_video("Pegawai SPPG ejek korban hilang ingatan", "karo", 30, r)[0] == "sub_kontroversi"
    assert classify_video("Puluhan siswa keracunan MBG", "karo", 2, r)[0] == "inti_hari_awal"
    assert classify_video("Puluhan siswa keracunan MBG", "karo", 20, r)[0] == "tidak"
    assert classify_video("Ratusan santri Sidoarjo keracunan MBG", "karo", 2, r)[0] == "tidak"
    assert classify_video("Deddy Corbuzier dongkol soal ayam MBG", "sukoharjo", 3, r)[0] == "sub_kontroversi"
    assert classify_video("Deddy Corbuzier dilantik jadi stafsus", "sukoharjo", 3, r)[0] == "tidak"
    assert classify_video("40 Siswa SD Sukoharjo keracunan", "sukoharjo", 30, r)[0] == "inti"


def _x(rows):
    df = pd.DataFrame(rows, columns=["tweet_id", "kasus", "text", "day", "replied_to_id", "quoted_id",
                                     "conversation_id"])
    df["hashtags"] = ""
    return df


def test_xs2_incident_early_rule(cfg):
    x = _x([["1", "sukoharjo", "ayam kurang matang MBG bikin keracunan", 1, None, None, "1"],
            ["2", "sukoharjo", "ayam kurang matang MBG bikin keracunan", 12, None, None, "2"],
            ["3", "sukoharjo", "ayam kurang matang MBG di Nunukan keracunan", 1, None, None, "3"]])
    out = text_relevance(x, cfg)
    assert out.relevance_reason.tolist() == ["incident_early", "ambiguous", "ambiguous"]


def test_rscm_rule_and_thread_context(cfg):
    x = _x([["1", "karo", "Siswi dirujuk RSCM usai keracunan MBG", 25, None, None, "1"],
            ["2", "karo", "Antrean RSCM panjang", 25, None, None, "2"],
            ["3", "karo", "Siswi dirujuk RSCM usai keracunan MBG", 5, None, None, "3"],
            ["4", "karo", "MBG Karo makin parah", 3, None, None, "4"],
            ["5", "karo", "setuju, harus diusut", 3, "4", None, "4"],
            ["6", "karo", "ini dia", 3, None, "99", "6"],
            ["7", "karo", "balasan tanpa konteks", 3, "98", None, "98"]])
    out = text_relevance(x, cfg, context_text={"99": "korban di Berastagi bertambah"})
    assert out.relevance_reason.tolist() == ["rscm_late", "ambiguous", "ambiguous", "keyword_case", "thread_context",
                                             "thread_context", "none"]
    assert out.is_relevant.tolist() == [True, False, False, True, True, True, False]
