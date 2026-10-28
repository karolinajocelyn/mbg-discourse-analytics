"""
Tarik teks tweet yang DIBALAS (replied_to) dan DIKUTIP (quoted) untuk konteks stance (keputusan D16).

Hanya tweet yang direferensikan korpus tetapi belum ada di x/raw/ yang ditarik, satu tingkat saja
(induk langsung, bukan induk dari induk). Tidak memakai search, hanya lookup by ID.

Pemakaian (dari folder x/):
  export X_BEARER_TOKEN="..."                       # PowerShell: $env:X_BEARER_TOKEN="..."
  python x_context.py --dry-run                     # hitung ID dan perkiraan biaya, tanpa memanggil API
  python x_context.py                               # tarik, simpan ke context/x_context.jsonl

Aturan:
  - Respons API disimpan utuh per batch (maks. 100 ID) di context/x_context.jsonl, satu baris per respons.
  - Tweet yang sudah dihapus/diproteksi muncul di field "errors" respons dan tetap tersimpan sebagai bukti.
  - File yang sudah ada tidak ditimpa kecuali pakai --force.
  - Field sama dengan x_collect.py, tanpa expansions. Cek saldo di console sebelum dan sesudah.
"""
import argparse
import glob
import json
import os
import sys
import time

import requests

from x_collect import PRICE_PER_POST, TWEET_FIELDS

URL = "https://api.x.com/2/tweets"
BATCH = 100
HERE = os.path.dirname(os.path.abspath(__file__))


def missing_reference_ids(raw_dir):
    """ID tweet induk/kutipan yang direferensikan korpus tetapi tidak ada di raw."""
    have, refs = set(), {}
    for path in sorted(glob.glob(os.path.join(raw_dir, "*.jsonl"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                for t in json.loads(line).get("data", []) or []:
                    have.add(t["id"])
                    for r in t.get("referenced_tweets", []) or []:
                        if r["type"] in ("replied_to", "quoted"):
                            refs.setdefault(r["id"], set()).add(r["type"])
    missing = sorted(i for i in refs if i not in have)
    by_type = {"replied_to": 0, "quoted": 0}
    for i in missing:
        for typ in refs[i]:
            by_type[typ] += 1
    return missing, by_type, len(refs)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", default=os.path.join(HERE, "raw"))
    parser.add_argument("--out", default=os.path.join(HERE, "context", "x_context.jsonl"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    missing, by_type, n_refs = missing_reference_ids(args.raw_dir)
    print(f"Referensi unik (reply/quote): {n_refs}; sudah ada di raw: {n_refs - len(missing)}; perlu ditarik: {len(missing)}")
    print(f"  induk reply: {by_type['replied_to']}, dikutip: {by_type['quoted']}")
    print(f"Perkiraan biaya maksimal: ${len(missing) * PRICE_PER_POST:.2f} ({-(-len(missing) // BATCH)} request)")
    if args.dry_run:
        return

    if os.path.exists(args.out) and not args.force:
        sys.exit(f"{args.out} sudah ada (pakai --force untuk menimpa).")
    token = os.environ.get("X_BEARER_TOKEN")
    if not token:
        sys.exit("Set dulu environment variable X_BEARER_TOKEN.")
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    headers = {"Authorization": f"Bearer {token}"}
    got, errors = 0, 0
    with open(args.out, "w", encoding="utf-8") as f:
        i = 0
        while i < len(missing):
            ids = missing[i:i + BATCH]
            resp = requests.get(URL, headers=headers, timeout=30,
                                params={"ids": ",".join(ids), "tweet.fields": TWEET_FIELDS})
            if resp.status_code == 429:
                print("  Kena rate limit, tunggu 60 detik...")
                time.sleep(60)
                continue
            if resp.status_code != 200:
                print(f"  Error {resp.status_code}: {resp.text[:400]}")
                print("  Berhenti agar tidak membuang saldo. Batch yang sudah tersimpan tetap ada.")
                break
            data = resp.json()
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
            got += len(data.get("data", []) or [])
            errors += len(data.get("errors", []) or [])
            print(f"  batch {i // BATCH + 1}: {len(data.get('data', []) or [])} tweet, "
                  f"{len(data.get('errors', []) or [])} tidak tersedia")
            i += BATCH
            time.sleep(1.1)

    print(f"\nTersimpan: {got} tweet; tidak tersedia (dihapus/diproteksi): {errors}")
    print(f"Perkiraan biaya: ${got * PRICE_PER_POST:.2f}. Bandingkan dengan selisih saldo di console.")


if __name__ == "__main__":
    main()
