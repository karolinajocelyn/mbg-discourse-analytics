"""Skema korpus terpadu X + YouTube, view per analisis, dan kamus data."""
import pandas as pd

from .features import topic_sample

# kolom -> (platform, keterangan). Urutan di sini = urutan kolom output.
COLUMN_DOCS = {
    "doc_id": ("X/YT", "ID dokumen: x_<tweet_id> atau yt_<comment_id>"),
    "platform": ("X/YT", "x | youtube"),
    "kasus": ("X/YT", "sukoharjo | karo"),
    "doc_type": ("X/YT", "original/reply/quote/quote_reply (X); yt_comment/yt_reply (YT)"),
    "source_id": ("X/YT", "tweet_id atau comment_id asli"),
    "thread_id": ("X/YT", "X: conversation_id; YT: comment_id komentar utama"),
    "parent_id": ("X/YT", "X: ID tweet yang dibalas; YT: comment_id induk (reply)"),
    "quoted_id": ("X", "ID tweet yang dikutip"),
    "video_id": ("YT", "ID video"),
    "query_ids": ("X", "kueri X yang menemukan tweet (gabungan terurut)"),
    "primary_query": ("X", "kueri prioritas pertama (config x.queries) untuk bobot cakupan"),
    "n_source_files": ("X", "jumlah file raw yang memuat tweet ini"),
    "author_hash": ("X/YT", "sha256(salt + id akun)[:16]; X dan YT memakai ruang ID berbeda"),
    "in_reply_to_hash": ("X", "hash akun yang dibalas"),
    "created_at": ("X/YT", "waktu unggah (UTC)"),
    "date_wib": ("X/YT", "tanggal WIB"),
    "hour_wib": ("X/YT", "jam WIB"),
    "days_since_incident": ("X/YT", "hari (pecahan) sejak insiden kasus, WIB"),
    "day": ("X/YT", "hari bulat sejak insiden (0-44)"),
    "segmen": ("X/YT", "S1-S5, 9 hari per segmen"),
    "phase": ("X/YT", "awal (0-8) / tengah (9-25) / lanjut (26-44); sama untuk kedua kasus"),
    "days_since_health_report": ("X/YT Karo", "hari relatif terhadap laporan kesehatan 2026-09-08; negatif = sebelum"),
    "after_health_report": ("X/YT Karo", "True bila setelah laporan kesehatan; NA untuk Sukoharjo"),
    "hours_since_video": ("YT", "umur video (jam) saat komentar ditulis"),
    "text_raw_masked": ("X/YT", "teks asli; hanya mention -> @user dan nama korban -> [KORBAN]. Untuk audit"),
    "text_clean": ("X/YT", "untuk sentimen/emosi, stance, coding, embedding: emoji/kapital/tanda baca utuh"),
    "text_topic": ("X/YT", "untuk LDA/c-TF-IDF/frekuensi: lowercase, slang, stopword (negasi tetap), stem"),
    "text_topic_nostem": ("X/YT", "text_topic tanpa stemming"),
    "dup_key": ("X/YT", "kunci deteksi duplikat (tanpa slang/stem)"),
    "parent_text_clean": ("X/YT", "text_clean tweet/komentar yang dibalas (konteks stance)"),
    "quoted_text_clean": ("X", "text_clean tweet yang dikutip"),
    "context_required": ("X/YT", "True untuk reply/quote"),
    "context_available": ("X/YT", "True bila tidak butuh konteks atau semua teks konteks tersedia & berisi"),
    "video_title_masked": ("YT", "judul video, nama korban dimask"),
    "channel_type_norm": ("YT", "media | kreator (Karo); NA untuk Sukoharjo"),
    "video_relevance": ("YT", "inti | inti_hari_awal | sub_kontroversi | tidak (aturan judul)"),
    "video_relevance_rule": ("YT", "pola yang cocok di relevance_rules.yaml"),
    "relevan_lama": ("YT", "label relevan lama dari kandidat (referensi saja)"),
    "relevance_reason": ("X", "keyword_case | incident_early | rscm_late | thread_context | ambiguous | none"),
    "is_relevant": ("X/YT", "X: alasan relevan; YT: video_relevance di level utama"),
    "lang": ("X", "label bahasa dari X"),
    "lang_ok": ("X", "lang in, atau teks berisi >= 3 stopword Indonesia"),
    "in_scope_main": ("X/YT", "relevan + bahasa OK (YT: inti/inti_hari_awal) -> dasar semua view utama"),
    "hashtags": ("X", "hashtag dari entities (lowercase, '|')"),
    "n_urls": ("X", "jumlah URL"),
    "has_media": ("X", "punya lampiran media"),
    "like_count": ("X/YT", "jumlah like (snapshot)"),
    "reply_count": ("X/YT", "jumlah reply (snapshot)"),
    "retweet_count": ("X", "jumlah retweet (snapshot)"),
    "quote_count": ("X", "jumlah quote (snapshot)"),
    "impression_count": ("X", "jumlah impresi (snapshot)"),
    "engagement": ("X/YT", "X: like+retweet+quote+reply; YT: like+reply"),
    "like_pct": ("X/YT", "persentil like dalam platform x kasus"),
    "engagement_pct": ("X/YT", "persentil engagement dalam platform x kasus"),
    "log1p_engagement": ("X/YT", "log(1 + engagement)"),
    "metrics_snapshot_date": ("X/YT", "tanggal snapshot metrik (X: mtime file raw, proxy; YT: collected_at)"),
    "edit_count": ("X", "jumlah versi tweet (riwayat edit)"),
    "is_maybe_truncated": ("X", "teks diakhiri '…'"),
    "possibly_sensitive": ("X", "flag X possibly_sensitive"),
    "batch": ("YT", "awal (2026-10-21) | tambahan (scrape ulang video relevan=n)"),
    "video_thread_capped": ("YT", "video kena batas 500 thread (D12)"),
    "video_coverage_ratio": ("YT", "komentar terambil / comment_count video"),
    "comment_before_video": ("YT", "timestamp komentar sebelum video terbit (premiere/upload ulang)"),
    "coverage_weight": ("X", "counts / terambil per (primary_query, hari UTC); >= 1"),
    "coverage_weight_approx": ("X", "True: bucket counts per hari UTC, bukan WIB"),
    "dup_group_id": ("X/YT", "ID grup near-duplicate (per platform x kasus)"),
    "is_dup_text": ("X/YT", "teks sama ditulis >= 2 akun"),
    "is_self_repeat": ("X/YT", "akun yang sama menulis teks yang sama lagi"),
    "is_copypasta": ("X/YT", ">= 3 akun, >= 10 token"),
    "is_news_headline_share": ("X", "judul berita (ber-URL) dibagikan >= 3 akun"),
    "dup_keep": ("X/YT", "salinan pertama per grup duplikat (atau bukan duplikat)"),
    "is_emoji_only": ("X/YT", "tanpa huruf; masuk view sentimen saja"),
    "is_low_content": ("X/YT", "<= 2 token alfabet dan bukan slogan program"),
    "is_slogan": ("X/YT", "slogan pendek sah (stop mbg, makan beracun gratis, ...)"),
    "is_spam": ("X/YT", "judol/kontak/promo; dibuang dari semua view"),
    "author_activity": ("X/YT", "jumlah dokumen akun ini di platform x kasus"),
    "is_hyperactive_author": ("X/YT", "aktivitas >= max(20, kuantil 99,5%)"),
    "is_very_long": ("X/YT", "panjang > p99 platform"),
    "is_empty_topic": ("X/YT", "text_topic kosong"),
    "n_chars": ("X/YT", "panjang text_clean"),
    "n_tokens": ("X/YT", "jumlah token text_clean"),
    "n_alpha_tokens": ("X/YT", "jumlah token alfabet >= 2 huruf"),
    "n_sentences": ("X/YT", "jumlah kalimat"),
    "n_connectives": ("X/YT", "penanda argumen (RQ3, menunggu revisi D10)"),
    "connectives_per_100_tokens": ("X/YT", "n_connectives per 100 token (RQ3)"),
    "has_question": ("X/YT", "mengandung '?' (RQ3)"),
    "has_evidence_marker": ("X/YT", "angka/data/menurut/sumber (RQ3)"),
    "any_kw_rq2": ("X/YT", "ada kata kunci RQ2 (pihak/penyebab/tuntutan)"),
    "topic_sample": ("X/YT", "masuk sampel topik (YT maks. 200 per video, D15)"),
    "in_v_volume": ("X/YT", "anggota view volume"),
    "in_v_sentiment": ("X/YT", "anggota view sentimen"),
    "in_v_stance": ("X/YT", "anggota view stance"),
    "in_v_topic": ("X/YT", "anggota view topik"),
    "in_v_rq2": ("X/YT", "anggota view RQ2"),
}

VIEWS = ("v_volume", "v_sentiment", "v_stance", "v_topic", "v_rq2")


def view_mask(c, name, cfg, exclude_hyperactive=False, exclude_capped=False, include_sub=False,
              require_context=False):
    """Mask boolean sebuah view. Opsi = analisis sensitivitas (D12, D14, D16, akun hiperaktif)."""
    scope = c.in_scope_main.copy()
    if include_sub:   # D14: sub_kontroversi hanya untuk Karo
        scope |= (c.platform == "youtube") & (c.kasus == "karo") & (c.video_relevance == "sub_kontroversi")
    base = scope & ~c.is_spam
    if exclude_hyperactive:
        base &= ~c.is_hyperactive_author
    if exclude_capped:
        base &= ~c.video_thread_capped.fillna(False).astype(bool)
    if require_context:
        base &= c.context_available.fillna(True).astype(bool)
    if name == "v_volume":
        return base
    sent = base & c.dup_keep
    if name == "v_sentiment":
        return sent
    stance = sent & ~c.is_emoji_only & ~c.is_low_content
    if name == "v_stance":
        return stance
    if name == "v_rq2":
        return stance & c.any_kw_rq2
    if name == "v_topic":
        eligible = stance & ~c.is_empty_topic
        if not (include_sub or exclude_hyperactive or exclude_capped or require_context):
            return eligible & c.topic_sample
        return topic_sample(c, eligible, cfg.raw["youtube"]["topic_max_per_video"], cfg.seed)
    raise ValueError(f"view tidak dikenal: {name}")


def view(c, name, cfg, **opts):
    """DataFrame view + video_weight (1 / jumlah komentar video itu di view; untuk proporsi makro per video)."""
    v = c[view_mask(c, name, cfg, **opts)].copy()
    n = v.groupby("video_id").doc_id.transform("size")
    v["video_weight"] = (1.0 / n).where(v.platform == "youtube")
    return v


def data_dictionary_md():
    lines = ["# Kamus data `corpus_all`", "", "| Kolom | Platform | Keterangan |", "|---|---|---|"]
    for col, (plat, desc) in COLUMN_DOCS.items():
        lines.append(f"| `{col}` | {plat} | {desc} |")
    lines += ["", "Ditambah kolom kata kunci `kw_*` dari `config/keywords_rq2.yaml`.", ""]
    return "\n".join(lines)
