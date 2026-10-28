"""Memuat dan memvalidasi config/pipeline.yaml. Gagal cepat bila ada kunci atau file yang hilang."""
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yaml


class ConfigError(Exception):
    pass


REQUIRED_KEYS = ["paths", "relevance_rules", "keywords_rq2", "text_resources", "time", "x", "youtube",
                 "quality", "hashing", "seed"]


@dataclass
class Config:
    raw: dict
    root: Path
    path: Path
    rules: dict = field(default_factory=dict)
    keywords: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- akses ringkas
    def p(self, rel):
        """Path relatif terhadap root project."""
        return (self.root / rel).resolve()

    @property
    def tz(self):
        return timezone(timedelta(hours=self.raw["time"]["timezone_offset_hours"]))

    @property
    def window_days(self):
        return int(self.raw["time"]["window_days"])

    @property
    def segment_days(self):
        return int(self.raw["time"]["segment_days"])

    def incident(self, kasus):
        d = datetime.strptime(self.raw["time"]["incident"][kasus], "%Y-%m-%d").replace(tzinfo=self.tz)
        return pd.Timestamp(d)

    def health_report(self, kasus):
        v = self.raw["time"].get("health_report", {}).get(kasus)
        if not v:
            return None
        return pd.Timestamp(datetime.strptime(v, "%Y-%m-%d").replace(tzinfo=self.tz))

    @property
    def cases(self):
        return sorted(self.raw["time"]["incident"])

    @property
    def seed(self):
        return int(self.raw["seed"])

    def resource(self, name):
        return self.p(self.raw["text_resources"][name])


def _compile_check(obj, where):
    """Pastikan semua string regex di rules bisa di-compile."""
    if isinstance(obj, str):
        try:
            re.compile(obj)
        except re.error as e:
            raise ConfigError(f"regex tidak valid di {where}: {obj!r} ({e})")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _compile_check(v, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _compile_check(v, f"{where}[{i}]")


def load_config(path="config/pipeline.yaml", root=None):
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"config tidak ditemukan: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if k not in raw]
    if missing:
        raise ConfigError(f"kunci wajib hilang di {path.name}: {missing}")
    root = Path(root).resolve() if root else path.parent.parent
    cfg = Config(raw=raw, root=root, path=path)

    for name in ("relevance_rules", "keywords_rq2"):
        f = cfg.p(raw[name])
        if not f.exists():
            raise ConfigError(f"file {name} tidak ditemukan: {f}")
    cfg.rules = yaml.safe_load(cfg.p(raw["relevance_rules"]).read_text(encoding="utf-8"))
    cfg.keywords = yaml.safe_load(cfg.p(raw["keywords_rq2"]).read_text(encoding="utf-8"))
    _compile_check(cfg.rules, "relevance_rules")
    _compile_check(cfg.keywords, "keywords_rq2")

    for name, rel in raw["text_resources"].items():
        if not cfg.p(rel).exists():
            hint = " (salin dari config/victim_names.example.txt lalu isi)" if name == "victim_names" else ""
            raise ConfigError(f"text resource '{name}' tidak ditemukan: {rel}{hint}")

    if cfg.window_days % cfg.segment_days:
        raise ConfigError("window_days harus kelipatan segment_days")
    if set(raw["time"]["incident"]) != set(raw["paths"]["youtube"]):
        raise ConfigError("kasus di time.incident dan paths.youtube harus sama")
    return cfg


def read_lines(path):
    """Baca file daftar: satu item per baris, abaikan baris kosong dan komentar '#'."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out
