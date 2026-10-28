"""Pseudonimisasi akun. Rumus sama dengan youtube_collect.py: sha256(salt + id)[:16]."""
import hashlib
import os

import pandas as pd


class SaltError(Exception):
    pass


def get_salt(env_name="HASH_SALT"):
    salt = os.environ.get(env_name, "")
    if not salt:
        raise SaltError(f"environment variable {env_name} kosong. Set salt tim dulu (jangan ditulis ke file).")
    return salt


def hash_id(salt, value):
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA or str(value) == "":
        return ""
    return hashlib.sha256((salt + str(value)).encode()).hexdigest()[:16]


def hash_series(s, salt):
    return s.map(lambda v: hash_id(salt, v)).astype("string")
