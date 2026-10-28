"""CLI: python -m anmedsos_prep run | check"""
import argparse
import sys

from .config import load_config
from .pseudonymize import get_salt


def main(argv=None):
    ap = argparse.ArgumentParser(prog="anmedsos_prep", description=__doc__)
    ap.add_argument("--config", default="config/pipeline.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="jalankan pipeline penuh -> processed/<run_id>/ dan processed/latest/")
    r.add_argument("--out", default=None, help="folder output (default: paths.output_dir di config)")
    sub.add_parser("check", help="validasi config & konstanta collector tanpa memproses data")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    if args.cmd == "check":
        from .qa import check_constants
        problems = check_constants(cfg)
        print("OK" if not problems else "\n".join(problems))
        return 1 if problems else 0
    from .pipeline import run
    from .qa import QAError
    salt = get_salt(cfg.raw["hashing"]["salt_env"])
    try:
        run(cfg, salt, out_root=args.out)
    except QAError as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
