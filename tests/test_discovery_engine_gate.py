"""発見のエンジン: 品質ゲート G1〜G10（通信しない）。"""
from datetime import datetime
from pathlib import Path

from src.discovery.engine.dedupe import ExistingIndex
from src.discovery.engine.extract.llm import from_llm_json
from src.discovery.engine.extract.rules import RulesExtractor
from src.discovery.engine.fetch import DocStore
from src.discovery.engine.gate import ALL_GATES, evaluate
from src.tcg.models import JST

FIX = Path(__file__).parent / "fixtures" / "discovery_engine"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=JST)
URL = "https://www.pokemon-card.com/info/2026/11/lottery_new.html"
REG = {"POKEMON": [{"product_id": "pkm-test", "name": "拡張パック「テストフレア」BOX"}], "ONE_PIECE": []}


def _doc(url=URL, html=None, hint=None):
    html = html if html is not None else (FIX / "lottery_page.html").read_text(encoding="utf-8")
    return DocStore(Path("/nonexistent")).make_doc(url, html, now=NOW, published_hint=hint)


def _eval(doc=None, llm=None, now=NOW, registry=REG, existing=None, cut=None):
    doc = doc or _doc()
    return evaluate(doc, RulesExtractor().extract(doc), llm, now=now, registry=registry,
                    existing=existing or ExistingIndex(), cut_hosts=cut)


def test_all_gates_pass_gives_publish_ready_but_not_verified():
    g = _eval()
    assert set(g.passed) == set(ALL_GATES) and g.failed == []
    assert g.publish_ready and not g.drop
    assert g.lottery_status == "UPCOMING"                     # 状態は日程と現在時刻から計算
    assert g.g4_mode == "rules_only"


def test_status_is_computed_not_extracted():
    # 同じ本文でも、現在時刻が変われば状態が変わる（抽出値として持たない）
    assert _eval(now=datetime(2026, 11, 28, 12, 0, tzinfo=JST)).lottery_status == "OPEN"
    assert _eval(now=datetime(2026, 12, 1, 12, 0, tzinfo=JST)).lottery_status == "ENDING_SOON"


def test_g1_without_doc_is_dropped():
    doc = _doc()
    g = evaluate(None, RulesExtractor().extract(doc), None, now=NOW, registry=REG)
    assert g.drop and g.drop_reason.startswith("G1")


def test_g2_unofficial_domain_is_not_publish_ready():
    g = _eval(_doc(url="https://blog.example.com/lottery.html"))
    assert "G2:unofficial_source" in g.failed and not g.publish_ready


def test_g4_disagreement_nulls_value():
    doc = _doc()
    llm = from_llm_json(doc, {"fields": {"application_end": {"value": "2026-12-08T23:59:00+09:00",
                                                             "quote": "12月8日（火）23:59"},
                                         "published_at": {"value": "2026-11-20", "quote": "2026年11月20日"}}}, "fake")
    g = _eval(doc, llm=llm)
    assert "G4:extractor_disagreement:application_end" in g.failed
    assert "application_end" not in g.values
    assert g.private_notes["disagreement"]["application_end"]["llm"] == "2026-12-08T23:59:00+09:00"
    assert not g.publish_ready and g.g4_mode == "disagree"


def test_g4_agreement_passes():
    doc = _doc()
    llm = from_llm_json(doc, {"fields": {"application_end": {"value": "2026-12-01T23:59:00+09:00",
                                                             "quote": "12月1日（火）23:59"},
                                         "published_at": {"value": "2026-11-20", "quote": "2026年11月20日"}}}, "fake")
    g = _eval(doc, llm=llm)
    assert "G4" in g.passed and g.g4_mode == "agree" and g.publish_ready


def test_g3_llm_hallucination_blocks_publish_ready():
    doc = _doc()
    llm = from_llm_json(doc, {"fields": {"retail_price": {"value": 1000, "quote": "1000円（税込", "price_unit": "BOX",
                                                          "tax": "INCL"}}}, "fake")
    g = _eval(doc, llm=llm)
    assert "G3:evidence_mismatch:llm.retail_price" in g.failed
    assert g.values["retail_price"].value == 5400            # ルールの値（根拠つき）だけが残る
    assert not g.publish_ready


def test_g5_product_unmapped():
    g = _eval(registry={"POKEMON": [], "ONE_PIECE": []})
    assert "G5:product_unmapped" in g.failed and not g.publish_ready


def test_g6_ended_is_dropped_and_unknown_waits():
    g = _eval(now=datetime(2027, 1, 20, 12, 0, tzinfo=JST))
    assert g.drop and g.drop_reason == "G6:ended"
    html = (FIX / "lottery_page.html").read_text(encoding="utf-8")
    html = html.split("<p>【抽選応募受付期間】</p>")[0] + "</body></html>"
    g2 = _eval(_doc(html=html))
    assert g2.lottery_status == "UNKNOWN" and "G6:status_unknown" in g2.failed and not g2.drop


def test_g7_old_article():
    g = _eval(now=NOW)
    assert "G7" in g.passed
    html = (FIX / "lottery_page.html").read_text(encoding="utf-8").replace("2026年11月20日", "2026年9月1日")
    g2 = _eval(_doc(html=html))
    assert "G7:stale_article" in g2.failed and not g2.publish_ready


def test_g8_duplicate_is_dropped():
    idx = ExistingIndex()
    idx.add(URL + "/", "lottery:lot-1")
    g = _eval(existing=idx)
    assert g.drop and g.drop_reason == "G8:duplicate_of:lottery:lot-1"


def test_g9_price_without_unit_is_nulled():
    html = (FIX / "lottery_page.html").read_text(encoding="utf-8").replace(
        "・拡張パック「テストフレア」BOX 5,400円（税込）", "・拡張パック「テストフレア」 5,400円（税込）")
    reg = {"POKEMON": [{"product_id": "pkm-test", "name": "拡張パック「テストフレア」"}]}
    g = _eval(_doc(html=html), registry=reg)
    assert "G9:price_unit_unknown" in g.failed and "retail_price" not in g.values


def test_g10_blocked_source_is_dropped():
    g = _eval(cut={"www.pokemon-card.com": "http_403"})
    assert g.drop and g.drop_reason == "G10:source_blocked_in_run"


def test_reasons_are_short_names():
    g = _eval(registry={"POKEMON": []})
    assert "product_unmapped" in g.reasons()
