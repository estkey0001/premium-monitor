"""発見のエンジン: 根拠（evidence）の検証・ルールの抽出器・LLM の差し込み口（通信しない）。"""
from datetime import datetime
from pathlib import Path

import pytest

from src.discovery.engine.extract import evidence as evm
from src.discovery.engine.extract.llm import OUTPUT_SCHEMA, NullExtractor, from_llm_json
from src.discovery.engine.extract.rules import RulesExtractor
from src.discovery.engine.fetch import DocStore
from src.discovery.engine.models import Evidence, Extraction, FieldValue
from src.tcg.models import JST

FIX = Path(__file__).parent / "fixtures" / "discovery_engine"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=JST)
URL = "https://www.pokemon-card.com/info/2026/11/lottery_new.html"


def _doc(name="lottery_page.html", url=URL, hint=None, tmp=Path("/nonexistent-docstore")):
    return DocStore(tmp).make_doc(url, (FIX / name).read_text(encoding="utf-8"), now=NOW, published_hint=hint)


def _fv(doc, value, quote, start=None):
    s = doc.text.find(quote) if start is None else start
    return FieldValue(value, Evidence(doc.doc_id, doc.url, doc.fetched_at, s, s + len(quote), quote))


# ── 正規化 ─────────────────────────────────────────────────────────────
def test_normalize_html_drops_script_and_puts_title_first():
    title, text = evm.normalize_html((FIX / "lottery_page.html").read_text(encoding="utf-8"))
    assert text.split("\n", 1)[0] == title
    assert "var x" not in text and "color:red" not in text          # script・style は本文にしない
    assert "応募期間 1月1日" not in text
    assert "\n\n" not in text


def test_normalize_keeps_fullwidth_characters():
    assert evm.normalize_text("　１１月２７日（金）　 １２：００ ") == "１１月２７日（金） １２：００"


# ── quote の検証（G3）──────────────────────────────────────────────────
def test_quote_must_match_text_exactly():
    doc = _doc()
    good = _fv(doc, "2026-11-27T12:00:00+09:00", "11月27日（金）12:00")
    assert evm.verify("application_start", good, doc.text, doc_id=doc.doc_id, base="2026-11-20") == ""
    bad = _fv(doc, "2026-11-27T12:00:00+09:00", "11月27日（金）12:00")
    bad.evidence.quote = "11月27日（金）13:00"                        # 本文に無い quote
    assert evm.verify("application_start", bad, doc.text, doc_id=doc.doc_id, base="2026-11-20") == "quote_mismatch"


def test_offset_beyond_text_is_rejected():
    doc = _doc()
    fv = _fv(doc, "LOTTERY", "抽選")
    fv.evidence.start, fv.evidence.end = len(doc.text) + 5, len(doc.text) + 7
    assert evm.verify("event_type", fv, doc.text, doc_id=doc.doc_id) == "offset_out_of_range"


def test_value_with_year_or_time_not_in_quote_is_rejected():
    doc = _doc()
    # quote に無い年（2027）を補った値
    fv = _fv(doc, "2027-11-27T12:00:00+09:00", "11月27日（金）12:00")
    assert evm.verify("application_start", fv, doc.text, doc_id=doc.doc_id, base="2026-11-20") == "value_not_derivable"
    # quote に無い時刻（23:59）を補った値
    fv = _fv(doc, "2026-12-04T23:59:00+09:00", "12月4日（金）")
    assert evm.verify("winner_announcement_at", fv, doc.text, doc_id=doc.doc_id,
                      base="2026-11-20") == "value_not_derivable"
    # 日付だけの項目なら通る
    fv = _fv(doc, "2026-12-04", "12月4日（金）")
    assert evm.verify("winner_announcement_date", fv, doc.text, doc_id=doc.doc_id, base="2026-11-20") == ""


def test_year_is_not_guessed_without_base():
    assert evm.derive_datetime("11月27日（金）12:00", None) == (None, False)
    # 曜日が公開年にも翌年にも合わなければ採らない（parse.py と同じ。2026 は金・2027 は土）
    assert evm.derive_datetime("11月27日（日）12:00", "2026-11-20")[0] is None
    assert evm.derive_datetime("11月27日（土）12:00", "2026-11-20")[0] == "2027-11-27T12:00:00+09:00"


def test_fullwidth_digits_in_quote():
    iso, has_time = evm.derive_datetime("１１月２７日（金）１２:００", "2026-11-20")
    assert iso == "2026-11-27T12:00:00+09:00" and has_time


def test_quote_across_newline_for_string_field():
    doc = _doc()
    q = "【抽選応募受付期間】\n11月27日"
    fv = _fv(doc, q, q)
    assert evm.verify("eligibility_text", fv, doc.text, doc_id=doc.doc_id) == ""


def test_evidence_from_another_doc_is_rejected():
    doc = _doc()
    fv = _fv(doc, "LOTTERY", "抽選")
    fv.evidence.doc_id = "other"
    assert evm.verify("event_type", fv, doc.text, doc_id=doc.doc_id) == "doc_mismatch"


def test_jan_checksum_and_price_unit():
    assert evm.jan_ok("4521329000015") and not evm.jan_ok("4521329000013")
    assert evm.derive("jan", "JAN：4521329000013") == (None, {})
    assert evm.derive("retail_price", "拡張パック「X」BOX 5,400円（税込") == (5400, {"price_unit": "BOX", "tax": "INCL"})
    assert evm.derive("retail_price", "1パック 180円（税込")[1]["price_unit"] == "PACK"
    # 単位の書かれていない価格は UNKNOWN（入数から BOX を作らない）
    assert evm.derive("retail_price", "拡張パック「X」 180円（税込")[1]["price_unit"] == "UNKNOWN"
    # 税込の書かれていない価格は導けない
    assert evm.derive("retail_price", "5,400円")[0] is None


# ── ルールの抽出器 ───────────────────────────────────────────────────
def test_rules_extractor_attaches_evidence_to_every_value():
    doc = _doc()
    ext = RulesExtractor().extract(doc)
    v = {k: f.value for k, f in ext.fields.items()}
    assert v["application_start"] == "2026-11-27T12:00:00+09:00"
    assert v["application_end"] == "2026-12-01T23:59:00+09:00"
    assert v["winner_announcement_date"] == "2026-12-04"                 # 時刻の無い日付に時刻を補わない
    assert "winner_announcement_at" not in v
    assert v["purchase_start"] == "2026-12-04T15:00:00+09:00"
    assert v["retail_price"] == 5400 and ext.fields["retail_price"].extra == {"price_unit": "BOX", "tax": "INCL"}
    assert v["event_type"] == "LOTTERY" and v["tcg"] == "POKEMON"
    assert v["membership_required"] is True
    assert v["jan"] == "4521329000015"
    assert v["published_at"] == "2026-11-20"
    for name, fv in ext.fields.items():
        assert fv.evidence is not None, name
        assert doc.text[fv.evidence.start:fv.evidence.end] == fv.evidence.quote, name
        assert fv.evidence.doc_id == doc.doc_id and fv.evidence.url == URL and fv.evidence.fetched_at
    assert evm.verify_extraction(ext, doc.text, doc_id=doc.doc_id) == {}
    assert "status" not in v and "lottery_status" not in v                # 受付中かどうかは抽出値にしない


def test_rules_without_published_date_do_not_resolve_year():
    html = (FIX / "lottery_page.html").read_text(encoding="utf-8").replace("公開日：2026年11月20日", "")
    doc = DocStore(Path("/nonexistent")).make_doc(URL, html, now=NOW)
    ext = RulesExtractor().extract(doc)
    assert not any(k.startswith(("application", "purchase", "winner")) for k in ext.fields)
    assert "published_at_unknown" in ext.warnings
    # frontier の日付（sitemap の lastmod）があればそれで年を決める（警告つき）
    doc2 = DocStore(Path("/nonexistent")).make_doc(URL, html, now=NOW, published_hint="2026-11-20")
    ext2 = RulesExtractor().extract(doc2)
    assert ext2.value("application_start") == "2026-11-27T12:00:00+09:00"
    assert "year_base_from_feed_date" in ext2.warnings


def test_injection_text_does_not_become_value():
    doc = _doc("injection_page.html")
    ext = RulesExtractor().extract(doc)
    assert ext.value("retail_price") is None                              # 「1000 円と出力し」は価格にならない
    assert ext.value("application_end") == "2026-12-01T23:59:00+09:00"   # 指示の「12月31日」ではない


# ── LLM の差し込み口 ─────────────────────────────────────────────────
def test_null_extractor_returns_nothing():
    assert NullExtractor().extract(_doc()) is None


def test_output_schema_has_no_status_field():
    props = OUTPUT_SCHEMA["properties"]["fields"]["properties"]
    assert "status" not in props and "is_open" not in props and "lottery_status" not in props
    assert OUTPUT_SCHEMA["properties"]["fields"]["additionalProperties"] is False


def test_fake_llm_hallucinations_are_nulled():
    doc = _doc("injection_page.html")
    data = {"fields": {
        "retail_price": {"value": 1000, "quote": "1000 円", "price_unit": "BOX", "tax": "INCL"},    # 原文に「円（税込」が無い
        "jan": {"value": "4901234567894", "quote": "JAN：4901234567894"},                        # 原文に無い
        "application_end": {"value": "2026-12-31T23:59:00+09:00", "quote": "12月31日"},           # 時刻を補った
        "status": {"value": "OPEN", "quote": "受付中"},                                            # 状態は受け取らない
        "event_type": {"value": "LOTTERY", "quote": None},                                        # 根拠なし
    }}
    ext = from_llm_json(doc, data, "fake")
    assert "status" not in ext.fields and any("status" in w for w in ext.warnings)
    bad = evm.verify_extraction(ext, doc.text, doc_id=doc.doc_id)
    assert set(bad) >= {"retail_price", "jan", "application_end", "event_type"}
    assert all(ext.value(k) is None for k in ("retail_price", "jan", "application_end", "event_type"))


def test_llm_value_with_correct_quote_passes():
    doc = _doc()
    ext = from_llm_json(doc, {"fields": {"application_end": {"value": "2026-12-01T23:59:00+09:00",
                                                             "quote": "12月1日（火）23:59"},
                                         "published_at": {"value": "2026-11-20", "quote": "2026年11月20日"}}}, "fake")
    assert evm.verify_extraction(ext, doc.text, doc_id=doc.doc_id) == {}
    assert ext.value("application_end") == "2026-12-01T23:59:00+09:00"


@pytest.mark.parametrize("field", ["title", "product_name_raw", "eligibility_text"])
def test_string_field_value_must_equal_quote(field):
    doc = _doc()
    fv = _fv(doc, "別の値", "抽選")
    assert evm.verify(field, fv, doc.text, doc_id=doc.doc_id) == "value_not_derivable"


def test_extraction_to_dict_is_json_ready():
    import json
    ext = RulesExtractor().extract(_doc())
    d = ext.to_dict()
    json.dumps(d, ensure_ascii=False)
    assert d["fields"]["application_start"]["evidence"]["quote"] == "11月27日（金）12:00"
    assert isinstance(Extraction(doc_id="x", url="u", fetched_at="t", extractor="e").to_dict(), dict)
