"""Normalisasi teks: text_raw_masked, text_clean, text_topic(_nostem), dup_key."""
import html
import re
import unicodedata

import pandas as pd

from .config import read_lines

ZERO_WIDTH_RE = re.compile("[­​-‏⁠-⁤﻿]")
URL_RE = re.compile(r"https?://\S+|www\.\S+|\bpic\.(?:x|twitter)\.com/\S+|\byoutu\.be/\S+|\bt\.co/\S+", re.I)
# Handle X: huruf/angka/_ ; handle YouTube boleh berisi titik & strip dan reply sering diawali '@@'
MENTION_RE = {"x": re.compile(r"@\w+"), "youtube": re.compile(r"@@?[\w][\w.\-]*")}
LEADING_MENTIONS_RE = re.compile(r"^(?:@user[\s,:]*)+")
VIDEO_TS_RE = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])")
WS_RE = re.compile(r"\s+")
LETTER_RE = re.compile(r"[^\W\d_]")
PLACEHOLDER_RE = re.compile(r"@user|\[KORBAN\]|\[WAKTU\]")
SENTENCE_RE = re.compile(r"[.!?]+(?:\s|$)|\n+")


class VictimMasker:
    """Ganti nama korban (anak di bawah umur) dengan [KORBAN]. Pola dari config/victim_names.txt."""

    def __init__(self, patterns):
        self.patterns = [re.compile(p, re.I) for p in patterns]

    @classmethod
    def from_file(cls, path):
        return cls(read_lines(path))

    def __call__(self, s):
        for p in self.patterns:
            s = p.sub("[KORBAN]", s)
        return s

    def found(self, s):
        return any(p.search(s) for p in self.patterns)


def normalize_unicode(s):
    s = html.unescape(s)
    s = unicodedata.normalize("NFKC", s)       # huruf matematis 𝗕𝗚𝗡 -> BGN
    return ZERO_WIDTH_RE.sub("", s)


def mask_raw(s, platform, masker):
    """Teks asli dengan mention & nama korban dimask; selebihnya tidak diubah (untuk audit)."""
    s = "" if s is None or (isinstance(s, float) and pd.isna(s)) else str(s)
    return masker(MENTION_RE[platform].sub("@user", s))


def clean_text(s, platform, masker):
    """text_clean: untuk sentimen/emosi, stance, coding, embedding. Emoji, kapital, tanda baca dipertahankan."""
    s = "" if s is None or (isinstance(s, float) and pd.isna(s)) else str(s)
    s = normalize_unicode(s)
    s = s.replace("\r", " ").replace("\n", " ")
    s = URL_RE.sub(" ", s)
    s = MENTION_RE[platform].sub("@user", s)    # mention dulu: handle yang memuat nama korban ikut hilang
    s = masker(s)
    s = WS_RE.sub(" ", s).strip()
    if platform == "x":
        s = LEADING_MENTIONS_RE.sub("", s)       # prefix @user otomatis pada reply
        s = re.sub(r"^RT\s+@user:?\s*", "", s)
    if platform == "youtube":
        s = VIDEO_TS_RE.sub("[WAKTU]", s)
    return WS_RE.sub(" ", s).strip()


def core_text(s):
    """Teks tanpa placeholder, untuk cek kosong/emoji-only."""
    return WS_RE.sub(" ", PLACEHOLDER_RE.sub(" ", s)).strip()


def has_letters(s):
    return bool(LETTER_RE.search(core_text(s)))


def alpha_tokens(s):
    return re.findall(r"[a-z]{2,}", core_text(s).lower())


def n_sentences(s):
    s = s.strip()
    if not s:
        return 0
    return max(1, len([p for p in SENTENCE_RE.split(s) if p and p.strip()]))


def dup_key(s):
    """Kunci duplikat: lowercase, tanpa placeholder/tanda baca/emoji/angka. TANPA slang & stem."""
    s = core_text(s).lower()
    s = re.sub(r"[^a-z\s]", " ", s)
    return WS_RE.sub(" ", s).strip()


def _split_camel(m):
    return " " + re.sub(r"(?<=[a-z])(?=[A-Z])", " ", m.group(1)) + " "


class TopicNormalizer:
    """text_topic: lowercase, slang, stopword (negasi dipertahankan), stem Sastrawi dengan cache."""

    def __init__(self, slang, stopwords, keep_tokens, protected):
        self.slang = slang
        self.keep = set(keep_tokens)
        self.stopwords = set(stopwords) - self.keep
        self.protected = set(protected)
        self._stemmer = None
        self._cache = {}

    @classmethod
    def from_config(cls, cfg):
        slang_df = pd.read_csv(cfg.resource("slang"), dtype=str, keep_default_na=False)
        slang = dict(zip(slang_df.slang.str.strip(), slang_df.baku.str.strip()))
        from Sastrawi.StopWordRemover.StopWordRemoverFactory import StopWordRemoverFactory
        stop = set(StopWordRemoverFactory().get_stop_words()) | set(read_lines(cfg.resource("stopwords_extra")))
        return cls(slang, stop, read_lines(cfg.resource("keep_tokens")), read_lines(cfg.resource("protected_tokens")))

    @property
    def stemmer(self):
        if self._stemmer is None:
            from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
            self._stemmer = StemmerFactory().create_stemmer()
            try:
                # kamus kata dasar Sastrawi berupa list (lookup lambat); ubah ke set
                d = self._stemmer.delegatedStemmer.dictionary
                d.words = set(d.words)
            except AttributeError:
                pass
        return self._stemmer

    def stem(self, tok):
        if tok in self.protected:
            return tok
        if tok not in self._cache:
            self._cache[tok] = self.stemmer.stem(tok) or tok
        return self._cache[tok]

    def tokens(self, text_clean):
        s = re.sub(r"#(\w+)", _split_camel, text_clean)
        s = s.lower().replace("@user", " ").replace("[korban]", " korban ").replace("[waktu]", " ")
        s = re.sub(r"makan(an)? bergizi gratis", " mbg ", s)
        s = re.sub(r"\b([a-z]+)2\b", r"\1", s)            # anak2 -> anak
        s = re.sub(r"[^a-z\s]", " ", s)
        s = re.sub(r"([a-z])\1{2,}", r"\1", s)           # bubarkannnn -> bubarkan
        out = []
        for t in s.split():
            for w in self.slang.get(t, t).split():
                if len(w) >= 2 and w not in self.stopwords:
                    out.append(w)
        return out

    def normalize(self, text_clean, stem=True):
        toks = self.tokens(text_clean)
        if stem:
            toks = [self.stem(t) for t in toks]
            toks = [t for t in toks if t and t not in self.stopwords]
        return " ".join(toks)
