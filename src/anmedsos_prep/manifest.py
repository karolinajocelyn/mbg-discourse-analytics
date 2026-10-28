"""Manifest run: sidik jari setiap file input, versi library, commit git, dan fingerprint salt (bukan salt-nya)."""
import hashlib
import importlib.metadata
import platform
import subprocess
from pathlib import Path

LIBS = ["pandas", "numpy", "PyYAML", "Sastrawi", "pyarrow"]


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def count_lines(path):
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def salt_fingerprint(salt):
    return hashlib.sha256(salt.encode()).hexdigest()[:8] if salt else None


def git_commit(root):
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        commit = out.stdout.strip() if out.returncode == 0 else None
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True,
                               timeout=10).stdout.strip()
        return {"commit": commit, "dirty": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def input_files(cfg):
    """Semua file input yang dibaca pipeline, terurut."""
    paths = cfg.raw["paths"]
    files = sorted(cfg.p(paths["x_raw"]).glob("*.jsonl")) + sorted(cfg.p(paths["x_counts"]).glob("*.json"))
    ctx = cfg.p(paths["x_context"])
    if ctx.exists():
        files.append(ctx)
    for kasus in sorted(paths["youtube"]):
        for kind in ("comments", "candidates"):
            files.append(cfg.p(paths["youtube"][kasus][kind]))
    files += [cfg.path, cfg.p(cfg.raw["relevance_rules"]), cfg.p(cfg.raw["keywords_rq2"])]
    files += [cfg.resource(k) for k in sorted(cfg.raw["text_resources"])]
    return files


def build_manifest(cfg, salt, run_id):
    files = []
    for f in input_files(cfg):
        rel = Path(f).resolve().relative_to(cfg.root).as_posix()
        entry = {"path": rel, "sha256": sha256_file(f), "bytes": Path(f).stat().st_size}
        if rel.endswith((".jsonl", ".csv")):
            entry["lines"] = count_lines(f)
        if "victim_names" in rel:
            entry = {"path": rel, "sha256": entry["sha256"]}   # isi tidak dicatat
        files.append(entry)
    versions = {}
    for lib in LIBS:
        try:
            versions[lib] = importlib.metadata.version(lib)
        except importlib.metadata.PackageNotFoundError:
            versions[lib] = None
    return {
        "run_id": run_id,
        "python": platform.python_version(),
        "libraries": versions,
        "git": git_commit(cfg.root),
        "x_salt_fingerprint": salt_fingerprint(salt),
        "youtube_salt_fingerprint": cfg.raw["hashing"].get("youtube_salt_fingerprint"),
        "config": cfg.raw,
        "inputs": files,
    }
