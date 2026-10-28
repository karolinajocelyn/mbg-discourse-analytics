"""QA otomatis: cek pemblokir (run gagal) + laporan qa_report.md."""
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .corpus import VIEWS
from .features import stable_rank

MENTION_LEFT_RE = re.compile(r"@(?!user\b)\w")
HARD_STEPS = ("dedup tweet_id", "window 45 hari", "teks kosong setelah clean")


class QAError(Exception):
    pass


def md_table(df, floatfmt="{:.3f}"):
    if df is None or len(df) == 0:
        return "_(kosong)_\n"
    df = df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df
    cols = [str(c) for c in df.columns]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        cells = []
        for v in row:
            if isinstance(v, float) and not np.isnan(v):
                cells.append(floatfmt.format(v))
            elif v is None or (isinstance(v, float) and np.isnan(v)):
                cells.append("")
            else:
                cells.append(str(v).replace("|", "\\|").replace("\n", " "))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out) + "\n"


def collector_constants(path):
    """Ambil WINDOW_DAYS, SEGMENT_DAYS, dan tanggal INCIDENT dari kode collector."""
    s = Path(path).read_text(encoding="utf-8")
    out = {"window_days": int(re.search(r"^WINDOW_DAYS\s*=\s*(\d+)", s, re.M).group(1)),
           "segment_days": int(re.search(r"^SEGMENT_DAYS\s*=\s*(\d+)", s, re.M).group(1))}
    for kasus, y, m, d in re.findall(r'"(\w+)":\s*datetime\((\d+),\s*(\d+),\s*(\d+)', s):
        out[f"incident_{kasus}"] = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return out


def check_constants(cfg):
    want = {"window_days": cfg.window_days, "segment_days": cfg.segment_days,
            **{f"incident_{k}": v for k, v in cfg.raw["time"]["incident"].items()}}
    problems = []
    for name, rel in cfg.raw["paths"]["collectors"].items():
        p = cfg.p(rel)
        if not p.exists():
            problems.append(f"collector {name} tidak ditemukan: {rel}")
            continue
        got = collector_constants(p)
        for k, v in want.items():
            if got.get(k) != v:
                problems.append(f"konstanta {k} beda: config={v}, {rel}={got.get(k)}")
    return problems


def _text_cols(c):
    return [col for col in ("text_raw_masked", "text_clean", "parent_text_clean", "quoted_text_clean",
                            "video_title_masked") if col in c.columns]


def run_checks(res, cfg):
    c = res["corpus"]
    failures, warnings = [], list(res["warnings"])

    # ---------------------------------------------------------------- pemblokir
    if not c.doc_id.is_unique:
        failures.append("doc_id tidak unik")
    if not c.day.between(0, cfg.window_days - 1).all():
        failures.append("ada dokumen di luar window")
    for col in ("author_id", "in_reply_to_user_id"):
        if col in c.columns:
            failures.append(f"kolom ID akun asli masih ada: {col}")
    masker = res["masker"]
    for col in _text_cols(c):
        s = c[col].dropna().astype(str)
        n_mention = int(s.str.contains(MENTION_LEFT_RE).sum())
        if n_mention:
            failures.append(f"{n_mention} baris {col} masih memuat @mention")
        n_name = int(s.map(masker.found).sum())
        if n_name:
            failures.append(f"{n_name} baris {col} masih memuat nama korban")
    cells = c.groupby(["platform", "kasus"]).size()
    for p in ("x", "youtube"):
        for k in cfg.cases:
            if cells.get((p, k), 0) == 0:
                failures.append(f"sel {p} x {k} kosong")
    att = res["attrition"]
    for (p, k), g in att.groupby(["platform", "kasus"]):
        raw = g[g.step.str.startswith("raw")].before.sum()
        removed = g[g.step.isin(HARD_STEPS)].removed.sum()
        final = cells.get((p, k), 0)
        if raw - removed != final:
            failures.append(f"attrition {p}/{k} tidak rekonsiliasi: {raw} - {removed} != {final}")
    capped = set(res["videos"].loc[res["videos"].video_thread_capped, "video_id"])
    expected = set(cfg.raw["youtube"].get("expected_thread_capped") or [])
    if capped != expected:
        failures.append(f"daftar video kena batas thread berubah: +{sorted(capped - expected)} "
                        f"-{sorted(expected - capped)}")
    if (c.text_clean.str.strip() == "").any():
        failures.append("ada text_clean kosong di korpus")
    stance = c[c.in_v_stance]
    if len(stance) and (stance.text_topic != "").mean() <= 0.9:
        failures.append("text_topic kosong > 10% di v_stance")
    failures += check_constants(cfg)

    # ---------------------------------------------------------------- peringatan
    exp = cfg.raw.get("expected_counts", {})
    xs = res["x_stats"]
    for key, got in (("x_rows", xs["rows"]), ("x_unique", xs["unique"]), ("x_pages", xs["pages"]),
                     ("x_empty_files", xs["empty_files"])):
        if key in exp and exp[key] != got:
            warnings.append(f"{key}: diharapkan {exp[key]}, didapat {got}")
    yraw = att[(att.platform == "youtube") & att.step.eq("raw")].set_index("kasus").before
    for k in cfg.cases:
        key = f"yt_{k}_rows"
        if key in exp and exp[key] != yraw.get(k):
            warnings.append(f"{key}: diharapkan {exp[key]}, didapat {yraw.get(k)}")

    return failures, report(res, cfg, failures, warnings)


def report(res, cfg, failures, warnings):
    c = res["corpus"]
    L = ["# Laporan QA pipeline preprocessing", ""]
    L += ["## Status", "", "**LULUS**" if not failures else "**GAGAL**", ""]
    L += [f"- ❌ {f}" for f in failures] + [f"- ⚠️ {w}" for w in warnings] + [""]

    L += ["## Ringkasan per view", ""]
    rows = []
    for (p, k), g in c.groupby(["platform", "kasus"]):
        rows.append({"platform": p, "kasus": k, "korpus": len(g), **{v: int(g["in_" + v].sum()) for v in VIEWS}})
    L += [md_table(pd.DataFrame(rows)), ""]

    L += ["## Attrition", "", md_table(res["attrition"]), ""]

    vol = c[c.in_v_volume]
    L += ["## Volume per segmen (v_volume)", "",
          md_table(pd.crosstab([vol.platform, vol.kasus], vol.segmen).reset_index()), ""]
    L += ["## Volume per fase (v_volume)", "",
          md_table(pd.crosstab([vol.platform, vol.kasus], vol.phase).reset_index()), ""]
    xv = vol[vol.platform == "x"]
    w = xv.groupby(["kasus", "segmen"]).agg(tweet=("doc_id", "size"), tertimbang=("coverage_weight", "sum"))
    L += ["## Volume X dengan bobot cakupan", "", md_table(w.round(1)), ""]
    karo = vol[vol.kasus == "karo"]
    L += ["## Karo: sebelum vs sesudah laporan kesehatan (v_volume)", "",
          md_table(pd.crosstab(karo.platform, karo.after_health_report.astype(str)).reset_index()), ""]

    L += ["## Cakupan X terhadap counts", "", md_table(res["coverage_summary"]), ""]
    v = res["videos"]
    ycov = v[v.n_comments_collected > 0].groupby("kasus").agg(
        video=("video_id", "size"), median_coverage=("video_coverage_ratio", "median"),
        coverage_lt_80=("video_coverage_ratio", lambda s: int((s < 0.8).sum())),
        thread_capped=("video_thread_capped", "sum"))
    L += ["## Cakupan komentar YouTube per video", "", md_table(ycov), ""]

    yv = vol[vol.platform == "youtube"]
    dom = []
    for (k, seg), g in yv.groupby(["kasus", "segmen"]):
        vc = g.video_id.value_counts()
        dom.append({"kasus": k, "segmen": seg, "komentar": len(g), "video": len(vc),
                    "top1": round(vc.iloc[:1].sum() / len(g), 3), "top5": round(vc.iloc[:5].sum() / len(g), 3),
                    "top10": round(vc.iloc[:10].sum() / len(g), 3)})
    L += ["## Dominasi video (v_volume YouTube)", "", md_table(pd.DataFrame(dom)), ""]

    L += ["## Relevansi", "",
          md_table(c[c.platform == "x"].groupby(["kasus", "relevance_reason"]).size().rename("tweet").reset_index()),
          "", md_table(v.groupby(["kasus", "video_relevance"]).agg(
              video=("video_id", "size"), komentar=("n_comments_collected", "sum")).reset_index()), ""]

    flags = ["is_dup_text", "is_self_repeat", "is_copypasta", "is_news_headline_share", "is_emoji_only",
             "is_low_content", "is_spam", "is_hyperactive_author", "is_very_long", "is_empty_topic",
             "context_available"]
    L += ["## Proporsi flag kualitas (korpus)", "",
          md_table(c.groupby(["platform", "kasus"])[flags].mean().round(3)), ""]
    L += ["## Konteks reply/quote X", "", "", "```", str(res["ctx_stats"]), "```", ""]

    L += ["## Contoh transformasi teks (acak ber-seed)", ""]
    for p in ("x", "youtube"):
        g = c[(c.platform == p) & c.in_v_stance]
        g = g.assign(_r=stable_rank(cfg.seed, g.doc_id)).sort_values("_r").head(20)
        L += [f"### {p}", "", "| text_raw_masked | text_clean | text_topic |", "|---|---|---|"]
        for r in g.itertuples():
            cells = [str(getattr(r, col))[:200].replace("|", "\\|").replace("\n", " ")
                     for col in ("text_raw_masked", "text_clean", "text_topic")]
            L.append("| " + " | ".join(cells) + " |")
        L.append("")
    return "\n".join(L)
