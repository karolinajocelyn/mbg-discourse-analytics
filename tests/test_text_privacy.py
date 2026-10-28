import pandas as pd
import pytest

from anmedsos_prep.pseudonymize import SaltError, get_salt, hash_id
from anmedsos_prep.text import TopicNormalizer, VictimMasker, clean_text, dup_key, mask_raw
from conftest import REPO

MASK = VictimMasker([r"\bfebi(ola|ona)\w*(\s+(br\.?\s+)?purba)?\b", r"\bfebi\s*yona\b", r"\bagnesia\w*\b"])


def test_clean_acceptance_example():
    assert clean_text("𝗕𝗚𝗡 &amp; SPPG​ https://t.co/x @abc", "x", MASK) == "BGN & SPPG @user"


def test_x_leading_reply_mentions_removed():
    assert clean_text("@a @b_c setuju @d", "x", MASK) == "setuju @user"


def test_youtube_mentions_and_timestamps():
    out = clean_text("@@user.satu-2 lihat 1:23 dan 01:02:03", "youtube", MASK)
    assert out == "@user lihat [WAKTU] dan [WAKTU]"


def test_victim_names_masked_but_not_family_name():
    s = "Febiola br. Purba dan Febiona, #febiolapurba, Febi Yona, Agnesia. Pak Purba lain orang"
    out = clean_text(s, "youtube", MASK)
    assert "febi" not in out.lower() and "agnesia" not in out.lower()
    assert out.count("[KORBAN]") == 5
    assert "Pak Purba" in out


def test_mention_containing_victim_name_fully_masked():
    assert mask_raw("@febiola_purba semangat", "x", MASK) == "@user semangat"


def test_salt_required(monkeypatch):
    monkeypatch.delenv("HASH_SALT", raising=False)
    with pytest.raises(SaltError):
        get_salt()


def test_hash_matches_youtube_collector_formula():
    import hashlib
    assert hash_id("s", "123") == hashlib.sha256(b"s123").hexdigest()[:16]
    assert hash_id("s", None) == "" and hash_id("s", pd.NA) == ""


def _norm():
    return TopicNormalizer(slang={"gak": "tidak", "yg": "yang", "bgt": "banget"},
                           stopwords={"yang", "tidak", "banget", "di", "dan"},
                           keep_tokens={"tidak"}, protected={"berastagi", "mbg", "korban"})


def test_topic_keeps_negation_and_protected_tokens():
    n = _norm()
    out = n.normalize("Gak setuju bgt sama MBG di Berastagi, [KORBAN] dirawat #StopMBG", stem=True)
    toks = out.split()
    assert "tidak" in toks and "berastagi" in toks and "mbg" in toks and "korban" in toks
    assert "banget" not in toks and "di" not in toks
    assert "rawat" in toks          # Sastrawi stem: dirawat -> rawat
    assert "stop" in n.normalize("#StopMBG", stem=False).split()


def test_topic_repeated_letters_and_reduplication():
    n = _norm()
    assert n.normalize("bubarkannnn anak2", stem=False) == "bubarkan anak"


def test_dup_key_ignores_placeholders_and_punctuation():
    assert dup_key("@user Stop MBG!!! 😡 [KORBAN]") == "stop mbg"


def test_slang_dict_valid():
    df = pd.read_csv(REPO / "config" / "slang_dict.csv", dtype=str, keep_default_na=False)
    assert df.slang.is_unique
    assert (df.slang == df.slang.str.lower()).all() and (df.baku == df.baku.str.lower()).all()
    assert not set(df.slang) & {"g", "aku", "kaya", "d"}     # entri ambigu dilarang
