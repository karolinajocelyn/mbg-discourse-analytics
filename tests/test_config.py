import pytest
import yaml

from anmedsos_prep.config import ConfigError, load_config
from anmedsos_prep.qa import check_constants, collector_constants
from conftest import REPO


def test_repo_config_matches_collectors():
    """Konstanta config sama dengan x_collect.py dan youtube_collect.py (bila collector ada di repo)."""
    cfg = load_config(REPO / "config" / "pipeline.yaml") if (REPO / "config" / "victim_names.txt").exists() else None
    if cfg is None:
        pytest.skip("config/victim_names.txt tidak ada (tidak di-commit)")
    assert check_constants(cfg) == []


def test_collector_constants_parsed():
    got = collector_constants(REPO / "x" / "x_collect.py")
    assert got == {"window_days": 45, "segment_days": 9, "incident_sukoharjo": "2025-01-16",
                   "incident_karo": "2026-08-13"}


def test_missing_victim_file_gives_hint(project):
    (project.parent / "victim_names.txt").unlink()
    with pytest.raises(ConfigError, match="victim_names.example"):
        load_config(project)


def test_invalid_regex_fails_fast(project):
    rules = project.parent / "relevance_rules.yaml"
    data = yaml.safe_load(rules.read_text(encoding="utf-8"))
    data["common"]["program"] = "(mbg"
    rules.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="regex tidak valid"):
        load_config(project)


def test_window_must_be_multiple_of_segment(project):
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["time"]["segment_days"] = 7
    project.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError, match="kelipatan"):
        load_config(project)
