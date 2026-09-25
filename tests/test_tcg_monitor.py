# -*- coding: utf-8 -*-
"""TCG 入荷・抽選・プレミア監視レイヤーのテスト。

最重要禁止事項（古い入荷報告を「今買える」と表示 / BOX=シュリンク付き仮定 /
SNS単発を公式確定扱い / 異常値1件を市場価格に採用 等）を回帰テストで固定する。
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.tcg import ALL_COLLECTORS, PokemonCardOfficialCollector  # noqa: E402
from src.collectors.tcg.keyword_page import slugify                          # noqa: E402
from src.tcg import alerts, classify, cluster, dedupe, freshness, premium, scoring, shrink  # noqa: E402
from src.tcg.models import (                                                  # noqa: E402
    EVENT_CONVENIENCE_STORE, EVENT_FIRST_COME, EVENT_LOTTERY, EVENT_PREORDER,
    EVENT_RESTOCK, EVENT_ONLINE_RESTOCK, EVENT_RESERVATION_REOPEN,
    SHRINK_SEALED, SHRINK_TAPE_CUT, SHRINK_UNKNOWN, ST_AVAILABLE_NOW, ST_ENDED,
    TcgEvent, now_jst,
)
from src.tcg.region import region_of, sort_for_display                        # noqa: E402
from src.tcg.sources import SOURCES, convenience_sources, sources_for         # noqa: E402


# ── Task1: Source Registry ────────────────────────────────────────────────
def test_pokemon_and_onepiece_sources_exist():
    assert sources_for("POKEMON"), "Pokemon の監視 source が未登録"
    assert sources_for("ONE_PIECE"), "ONE PIECE の監視 source が未登録"


def test_convenience_chains_are_monitored_independently():
    keys = {s["key"] for s in convenience_sources()}
    assert {"LAWSON", "7-ELEVEN", "FAMILY_MART", "MINISTOP"} <= keys


def test_source_registry_entries_are_well_formed():
    for s in SOURCES:
        assert s["key"] and s["name"] and s["tcg"]
        assert s["source_type"] in (
            "OFFICIAL", "RETAILER_OFFICIAL", "STORE_OFFICIAL",
            "COMMUNITY_REPORT", "SOCIAL_REPORT", "UNVERIFIED")


# ── Task3: 販売方式の厳格分類 ─────────────────────────────────────────────
@pytest.mark.parametrize("text,store,expected", [
    ("抽選販売の応募受付を開始します", "POKEMON_CENTER_ONLINE", EVENT_LOTTERY),
    ("予約受付を開始しました", "YODOBASHI", EVENT_PREORDER),
    ("9/16 7:00より店頭にて先着販売", "YODOBASHI", EVENT_FIRST_COME),
    ("ローソン店頭にて先着で販売します", "LAWSON", EVENT_CONVENIENCE_STORE),
    ("本日再入荷しました", "GEO", EVENT_RESTOCK),
    ("予約キャンセル分の受付を再開します", "AMAZON", EVENT_RESERVATION_REOPEN),
])
def test_event_type_classification(text, store, expected):
    assert classify.classify_event_type(text, store=store) == expected


def test_unknown_text_is_not_guessed():
    assert classify.classify_event_type("本日は晴天なり") is None


def test_lottery_is_not_downgraded_to_convenience_store():
    """コンビニ告知でも「抽選」は FIRST_COME / CONVENIENCE_STORE にしない。"""
    assert classify.classify_event_type(
        "ローソンにて抽選販売を行います", store="LAWSON") == EVENT_LOTTERY


def test_online_restock_separated_from_store_restock():
    assert classify.classify_event_type(
        "再入荷しました", store="AMAZON", channel="ONLINE") == EVENT_ONLINE_RESTOCK


# ── Task5 / Task22: 公式とSNSを同一信頼度にしない ────────────────────────
def test_official_domain_is_official():
    assert classify.classify_source_type(
        "https://www.pokemon-card.com/info/1.html") == "OFFICIAL"


def test_sns_domain_is_social_report():
    assert classify.classify_source_type(
        "https://x.com/foo/status/1") == "SOCIAL_REPORT"


def test_single_sns_report_is_never_high_confidence():
    conf = classify.confidence_for("SOCIAL_REPORT", corroborations=1)
    assert conf == "low"
    assert classify.verification_label("SOCIAL_REPORT", conf, 1) == "Reported"


def test_multiple_sns_reports_never_reach_confirmed():
    conf = classify.confidence_for("SOCIAL_REPORT", corroborations=10)
    assert conf != "high"
    assert classify.verification_label("SOCIAL_REPORT", conf, 10) != "Confirmed"


def test_official_is_confirmed():
    assert classify.verification_label("OFFICIAL", "high", 1) == "Confirmed"


def test_scope_label_never_claims_nationwide_from_single_report():
    label = classify.scope_label("SOCIAL_REPORT", 1, 1)
    assert "全国" not in label
    assert "在庫" in label


# ── Task8: BOX=シュリンク付き と仮定しない ───────────────────────────────
def test_box_does_not_imply_shrink():
    assert shrink.assume_shrink_from_box(True) == SHRINK_UNKNOWN
    assert shrink.detect_shrink_status("BOX販売あり") == SHRINK_UNKNOWN


def test_tape_cut_is_not_sealed():
    st = shrink.detect_shrink_status("BOX購入時はテープカットいたします")
    assert st == SHRINK_TAPE_CUT
    assert shrink.is_sealed(st) is False


def test_onepiece_official_shop_policy_is_tape_cut():
    assert shrink.detect_shrink_status(
        "BOX販売", store_key="ONEPIECE_CARD_OFFICIAL_SHOP") == SHRINK_TAPE_CUT
    assert shrink.shrink_policy_note("ONEPIECE_CARD_OFFICIAL_SHOP")


def test_sealed_detected_and_unknown_is_none():
    assert shrink.detect_shrink_status("シュリンク付き未開封") == SHRINK_SEALED
    assert shrink.is_sealed(SHRINK_UNKNOWN) is None


# ── Task15 / Task16: 古い入荷報告を「今買える」と表示しない ──────────────
def test_stale_restock_is_not_available_now():
    ev = {"event_type": EVENT_RESTOCK, "source_type": "RETAILER_OFFICIAL",
          "reported_at": (now_jst() - timedelta(hours=5)).isoformat()}
    assert freshness.is_stale(ev) is True
    assert freshness.compute_status(ev) == ST_ENDED
    assert freshness.available_now(ev) is False


def test_fresh_official_restock_is_available_now():
    ev = {"event_type": EVENT_RESTOCK, "source_type": "RETAILER_OFFICIAL",
          "reported_at": now_jst().isoformat()}
    assert freshness.compute_status(ev) == ST_AVAILABLE_NOW


def test_unverified_report_is_not_available_now():
    ev = {"event_type": EVENT_RESTOCK, "source_type": "SOCIAL_REPORT",
          "reported_at": now_jst().isoformat()}
    assert freshness.compute_status(ev) != ST_AVAILABLE_NOW


def test_online_restock_ttl_is_shortest():
    assert freshness.ttl_for(EVENT_ONLINE_RESTOCK) == 15 * 60
    assert freshness.ttl_for(EVENT_RESTOCK) == 2 * 60 * 60
    assert freshness.ttl_for("GUERRILLA_SALE") == 30 * 60
    assert freshness.ttl_for(EVENT_LOTTERY) is None   # 締切まで有効


def test_lottery_status_flow():
    now = now_jst()
    ev = {"event_type": EVENT_LOTTERY,
          "application_start": (now - timedelta(days=2)).isoformat(),
          "application_end": (now + timedelta(hours=3)).isoformat()}
    assert freshness.compute_status(ev) == "ENDING_SOON"
    ev2 = dict(ev, application_end=(now - timedelta(days=1)).isoformat(),
               result_date=(now + timedelta(days=1)).isoformat())
    assert freshness.compute_status(ev2) == "RESULT_PENDING"


# ── Task9 / Task10: 異常値1件を市場価格に採用しない ──────────────────────
def test_outlier_is_excluded_from_market_median():
    assert premium.market_median([12000, 12500, 12800, 250000]) == 12500


def test_single_observation_is_not_market_price():
    assert premium.market_median([99000]) is None


def test_premium_calculation():
    p = premium.compute_premium(7200, 12500)
    assert p["premium_yen"] == 5300
    assert p["premium_percent"] == pytest.approx(73.6, abs=0.1)


def test_no_premium_without_retail_price():
    p = premium.compute_premium(None, 12500)
    assert p["premium_yen"] is None and p["premium_percent"] is None


def test_shrink_premium_requires_both_states():
    only_sealed = premium.build_premium(7200, [12000, 12500, 12800], [])
    assert only_sealed["shrink_premium_percent"] is None
    both = premium.build_premium(7200, [12000, 12500, 12800], [9000, 9200, 9400])
    assert both["shrink_premium_percent"] is not None


def test_unclassified_condition_is_not_counted():
    sealed, unsealed = premium.split_by_shrink([
        {"price": 12000, "shrink_status": SHRINK_SEALED},
        {"price": 11000, "shrink_status": SHRINK_UNKNOWN},
    ])
    assert sealed == [12000.0] and unsealed == []


# ── Task21 / Task20: 重複排除と上書き禁止 ────────────────────────────────
def test_duplicate_events_are_merged():
    base = {"tcg": "POKEMON", "product_id": "a", "store": "LAWSON",
            "event_type": EVENT_RESTOCK, "observed_at": now_jst().isoformat()}
    out = dedupe.dedupe_events([
        dict(base, source_type="SOCIAL_REPORT", confidence="low", source_url="x"),
        dict(base, source_type="RETAILER_OFFICIAL", confidence="high", source_url="y"),
    ])
    assert len(out) == 1
    assert out[0]["source_type"] == "RETAILER_OFFICIAL"   # 下位が上位を上書きしない


def test_lower_source_cannot_override_official():
    assert dedupe.can_override("OFFICIAL", "SOCIAL_REPORT") is False
    assert dedupe.can_override("SOCIAL_REPORT", "OFFICIAL") is True


# ── Task7: 地域クラスタリング ─────────────────────────────────────────────
def test_kansai_restock_signal_detected():
    n = now_jst().isoformat()
    evs = [{"event_type": EVENT_RESTOCK, "store_chain": "LAWSON",
            "prefecture": p, "reported_at": n}
           for p in ("大阪府", "兵庫県", "京都府")]
    sigs = cluster.detect_restock_signals(evs)
    assert any(s["signal"] == "KANSAI_RESTOCK_SIGNAL" for s in sigs)
    assert all(s["confirmed"] is False for s in sigs)   # 事実確定ではない


def test_single_report_makes_no_signal():
    n = now_jst().isoformat()
    sigs = cluster.detect_restock_signals(
        [{"event_type": EVENT_RESTOCK, "store_chain": "LAWSON",
          "prefecture": "大阪府", "reported_at": n}])
    assert sigs == []


def test_region_lookup_and_display_order():
    assert region_of("大阪府") == "KANSAI"
    assert region_of(None) is None
    evs = [{"prefecture": "東京都"}, {"prefecture": "大阪府"}]
    assert sort_for_display(evs, user_prefecture="大阪府")[0]["prefecture"] == "大阪府"
    # ユーザー設定が無ければ並べ替えない（位置情報を推測しない）
    assert sort_for_display(evs)[0]["prefecture"] == "東京都"


# ── Task11 / Task12: スコアと BUY NOW ────────────────────────────────────
def test_opportunity_score_in_range():
    ev = {"event_type": EVENT_CONVENIENCE_STORE, "status": ST_AVAILABLE_NOW,
          "source_type": "RETAILER_OFFICIAL", "confidence": "high",
          "shrink_status": SHRINK_UNKNOWN}
    s = scoring.opportunity_score(ev, {"premium_percent": 73.6,
                                       "sealed_sample_count": 6})
    assert 0 <= s["score"] <= 100
    assert set(s["breakdown"]) == set(scoring.WEIGHTS)


def test_buy_now_requires_official_and_available():
    prem = {"premium_percent": 73.6, "premium_yen": 5300}
    ok = scoring.buy_now_signal(
        {"event_type": EVENT_CONVENIENCE_STORE, "status": ST_AVAILABLE_NOW,
         "source_type": "RETAILER_OFFICIAL", "shrink_status": SHRINK_UNKNOWN}, prem)
    assert ok["buy_now"] is True
    ng = scoring.buy_now_signal(
        {"event_type": EVENT_RESTOCK, "status": ST_AVAILABLE_NOW,
         "source_type": "SOCIAL_REPORT"}, prem)
    assert ng["buy_now"] is False and ng["blocked_reasons"]


def test_buy_now_notes_resale_restriction():
    out = scoring.buy_now_signal(
        {"event_type": EVENT_CONVENIENCE_STORE, "status": ST_AVAILABLE_NOW,
         "source_type": "RETAILER_OFFICIAL", "resale_restricted": True,
         "purchase_limit": "1会計5パックまで"},
        {"premium_percent": 80.0, "premium_yen": 5000})
    assert any("転売" in n for n in out["notes"])
    assert any("購入制限" in n for n in out["notes"])


# ── Task14: 即売系は抽選より通知優先度が高い ─────────────────────────────
def test_instant_sale_priority_is_critical_when_official():
    ev = {"event_type": EVENT_CONVENIENCE_STORE, "status": ST_AVAILABLE_NOW,
          "source_type": "RETAILER_OFFICIAL", "confidence": "high"}
    assert scoring.notification_priority(ev) == "CRITICAL"


def test_stale_event_is_low_priority():
    ev = {"event_type": EVENT_CONVENIENCE_STORE, "status": ST_AVAILABLE_NOW,
          "source_type": "RETAILER_OFFICIAL", "confidence": "high", "stale": True}
    assert scoring.notification_priority(ev) == "LOW"


def test_stale_events_are_excluded_from_instant_alerts():
    ev = {"event_type": EVENT_RESTOCK, "status": ST_AVAILABLE_NOW,
          "source_type": "RETAILER_OFFICIAL", "confidence": "high",
          "stale": True, "product_name": "x"}
    assert alerts.instant_sale_alerts([ev]) == []


# ── Task13: 抽選締切アラート ──────────────────────────────────────────────
def test_lottery_deadline_alert_fires_at_3h():
    ev = {"event_type": EVENT_LOTTERY, "product_name": "30th CELEBRATION",
          "application_end": (now_jst() + timedelta(hours=3, minutes=30)).isoformat()}
    out = alerts.lottery_deadline_alerts(ev, window=timedelta(hours=1))
    assert any(a["milestone"] == "application_end_3h" for a in out)


def test_non_lottery_has_no_deadline_alert():
    assert alerts.lottery_deadline_alerts({"event_type": EVENT_RESTOCK}) == []


# ── Task24: 通知文面（入荷時間を推測しない / 在庫保証しない） ─────────────
def test_message_does_not_invent_sale_time():
    msg = alerts.build_sale_message(
        {"event_type": EVENT_RESTOCK, "product_name": "テストBOX",
         "store": "LAWSON", "source_type": "SOCIAL_REPORT"})
    assert "未公表" in msg
    assert "在庫を保証するものではありません" in msg


def test_premium_message_none_when_samples_insufficient():
    assert alerts.build_premium_message(
        {"premium": {"premium_percent": None, "insufficient_samples": True}}) is None


# ── Task2: イベントモデル ─────────────────────────────────────────────────
def test_event_model_rejects_unknown_values():
    with pytest.raises(ValueError):
        TcgEvent(tcg="MAGIC", product_id="a", product_name="n",
                 event_type=EVENT_RESTOCK, store="LAWSON")
    with pytest.raises(ValueError):
        TcgEvent(tcg="POKEMON", product_id="a", product_name="n",
                 event_type="SOMETHING", store="LAWSON")


def test_event_defaults_are_unknown_not_guessed():
    ev = TcgEvent(tcg="POKEMON", product_id="a", product_name="n",
                  event_type=EVENT_RESTOCK, store="LAWSON")
    assert ev.shrink_status == SHRINK_UNKNOWN
    assert ev.box_available is None      # 不明は False と区別する
    assert ev.price is None


# ── Task23: 実 source パーサ ──────────────────────────────────────────────
def test_collector_parses_real_page_text():
    c = PokemonCardOfficialCollector()
    text = ("ポケモンカードゲーム 拡張パック テストBOX\n"
            "販売開始 2099年9月16日 7:00 ローソン店頭にて先着販売\n"
            "お一人様5パックまで\n¥7,200")
    evs = c.parse(text, "https://www.pokemon-card.com/info/1.html")
    assert evs, "実ページ形式のテキストからイベントを抽出できていない"
    ev = evs[0]
    assert ev.event_type == EVENT_CONVENIENCE_STORE
    assert ev.purchase_limit == "1会計5パックまで"
    assert ev.source_type == "OFFICIAL"
    assert ev.shrink_status == SHRINK_UNKNOWN    # 記載が無ければ推測しない


def test_all_collectors_declare_real_urls():
    for cls in ALL_COLLECTORS:
        c = cls()
        assert c.urls, f"{cls.__name__} に監視URLが無い"
        assert all(u.startswith("https://") for u in c.urls)
        assert c.tcg in ("POKEMON", "ONE_PIECE")


def test_slugify():
    assert slugify("ポケモンカードゲーム 拡張パック") == "ポケモンカードゲーム-拡張パック"


# ── 販売文脈フィルタ: 大会・イベント告知を販売情報にしない ────────────────
from src.tcg.sales_context import (  # noqa: E402
    has_product_context, has_sale_context, is_product_lottery, is_sales_block,
)


def test_tournament_announcement_is_not_a_sale():
    block = "ポケカジムエントリーキャンペーン2026年後期、9月1日スタート！ イベント"
    assert is_sales_block(block) is False


def test_event_entry_is_not_a_product_lottery():
    assert is_product_lottery("ポケモンカード入門バトル 事前応募受け付け中") is False
    assert is_product_lottery("拡張パックBOXの抽選販売を行います") is True


def test_real_product_sale_block_passes_filter():
    block = "拡張パック「アビスアイ」BOX メーカー希望小売価格 7,200円 2026年5月22日発売"
    assert has_sale_context(block) and has_product_context(block)
    assert is_sales_block(block) is True


def test_generic_brand_mention_is_not_enough():
    assert has_product_context("ポケモンカードチャンネル") is False


def test_collector_skips_tournament_blocks():
    c = PokemonCardOfficialCollector()
    text = ("ポケカジムエントリーキャンペーン2026年後期、9月1日スタート！\n"
            "2026.8.21 イベント 追加エントリー受付中")
    assert c.parse(text, "https://www.pokemon-card.com/info/") == []


# ── JavaScript 描画ページのフォールバック ────────────────────────────────
def test_js_page_fetch_records_health_when_playwright_missing(monkeypatch):
    """Playwright 未導入でも例外を投げず health に記録する。"""
    from src.collectors.tcg.pokemon import PokemonProductsCollector
    import builtins
    c = PokemonProductsCollector()
    assert c.requires_js is True
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert c._fetch_with_playwright("https://example.com/") is None
    assert c.health["errors"] == 1
    assert "playwright" in c.health["error_messages"][0]


def test_js_page_fetch_uses_playwright_when_available(monkeypatch):
    """Playwright があれば描画後の HTML を返す。"""
    import sys as _sys
    import types
    from src.collectors.tcg.pokemon import PokemonProductsCollector

    class _Page:
        def goto(self, *a, **k): pass
        def wait_for_timeout(self, *a, **k): pass
        def content(self): return "<html>拡張パック</html>"

    class _Browser:
        def new_page(self, *a, **k): return _Page()
        def close(self): pass

    class _Chromium:
        def launch(self, *a, **k): return _Browser()

    class _PW:
        chromium = _Chromium()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: _PW()
    pkg = types.ModuleType("playwright")
    pkg.sync_api = mod
    monkeypatch.setitem(_sys.modules, "playwright", pkg)
    monkeypatch.setitem(_sys.modules, "playwright.sync_api", mod)

    c = PokemonProductsCollector()
    assert c._fetch_with_playwright("https://example.com/") == "<html>拡張パック</html>"
    assert c.health["errors"] == 0


# ── Task6: 入荷報告の取り込み ─────────────────────────────────────────────
def test_restock_report_requires_store_and_region(tmp_path):
    from src.tcg.reports import CSV_COLUMNS, load_reports
    path = tmp_path / "reports.csv"
    rows = [
        # 必須項目が揃っている行
        "POKEMON,box-a,テストBOX,ローソン大阪駅前店,LAWSON,大阪府,大阪市,"
        f"{now_jst().isoformat()},3,シュリンク付き,social,https://x.com/a/status/1,"
        "本日入荷しました,,,",
        # 都道府県が無い行は取り込まない
        "POKEMON,box-a,テストBOX,どこかの店,LAWSON,,,"
        f"{now_jst().isoformat()},,,social,,本日入荷しました,,,",
    ]
    path.write_text(",".join(CSV_COLUMNS) + "\n" + "\n".join(rows) + "\n",
                    encoding="utf-8")
    out = load_reports(path)
    assert len(out) == 1
    ev = out[0]
    assert ev["prefecture"] == "大阪府"
    assert ev["store_chain"] == "LAWSON"
    assert ev["confidence"] == "low"          # 報告は low から始める
    assert ev["source_type"] == "SOCIAL_REPORT"
    assert ev["official_confirmation"] is False
    assert ev["shrink_status"] == "SEALED_SHRINK"   # 報告本文に明記があった場合のみ


def test_report_is_never_treated_as_official(tmp_path):
    from src.tcg.reports import CSV_COLUMNS, load_reports
    path = tmp_path / "r.csv"
    # 公式ドメインの URL が書かれていても、報告 CSV 由来は公式扱いにしない
    row = ("POKEMON,box-b,テストBOX,店舗,LAWSON,兵庫県,神戸市,"
           f"{now_jst().isoformat()},,,community,"
           "https://www.pokemon-card.com/info/,本日入荷しました,,,")
    path.write_text(",".join(CSV_COLUMNS) + "\n" + row + "\n", encoding="utf-8")
    ev = load_reports(path)[0]
    assert ev["source_type"] in ("COMMUNITY_REPORT", "SOCIAL_REPORT")
    assert ev["source_type"] != "OFFICIAL"


# ── eBay 経由の二次流通取得（kill-switch / dry-run を尊重） ───────────────
def test_ebay_observations_disabled_by_default(monkeypatch):
    from src.tcg import secondary
    monkeypatch.delenv("ENABLE_EBAY_API", raising=False)
    monkeypatch.delenv("API_DRY_RUN", raising=False)
    assert secondary.ebay_enabled() is False
    assert secondary.fetch_ebay_observations("p", "keyword") == []


def test_ebay_observations_respect_dry_run(monkeypatch):
    from src.tcg import secondary
    monkeypatch.setenv("ENABLE_EBAY_API", "true")
    monkeypatch.setenv("API_DRY_RUN", "true")     # dry-run 中は実取得しない
    monkeypatch.setenv("EBAY_APP_ID", "dummy")
    assert secondary.ebay_enabled() is False
    assert secondary.fetch_ebay_observations("p", "keyword") == []


def test_ebay_observations_convert_currency(monkeypatch):
    from src.tcg import secondary
    monkeypatch.setenv("ENABLE_EBAY_API", "true")
    monkeypatch.setenv("API_DRY_RUN", "false")
    monkeypatch.setenv("EBAY_APP_ID", "dummy")
    items = [
        {"title": "Pokemon Box sealed shrink", "listing_price_original": 100.0,
         "currency": "USD", "url": "https://ebay.com/1", "condition": "New"},
        # レート不明の通貨は円換算しない
        {"title": "Pokemon Box", "listing_price_original": 50.0,
         "currency": "XYZ", "url": "https://ebay.com/2", "condition": "New"},
    ]
    obs = secondary.fetch_ebay_observations(
        "p", "pokemon box",
        fetcher=lambda kw: items,
        fx_loader=lambda cur: {"rate": 150.0} if cur == "USD" else {"rate": None})
    assert len(obs) == 1
    assert obs[0]["price"] == 15000.0
    assert obs[0]["source"] == "ebay"


# ══════════════════════════════════════════════════════════════════════════
# レビュー指摘の回帰固定（CRITICAL / HIGH / MEDIUM）
# ══════════════════════════════════════════════════════════════════════════

def _load_pipeline():
    """scripts/collect_tcg_events.py をモジュールとして読み込む。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "collect_tcg_events", PROJECT_ROOT / "scripts" / "collect_tcg_events.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── CRITICAL: TTL 対象外イベントが無期限に「今買える」にならない ──────────
def test_old_first_come_is_not_available_now():
    """販売終了日が不明なまま時間が経った販売は AVAILABLE_NOW にしない。"""
    ev = {"event_type": EVENT_FIRST_COME, "source_type": "SOCIAL_REPORT",
          "sale_start": (now_jst() - timedelta(days=400)).isoformat()}
    assert freshness.compute_status(ev) != ST_AVAILABLE_NOW
    assert freshness.available_now(ev) is False


def test_old_official_general_sale_is_not_available_now():
    ev = {"event_type": "GENERAL_SALE", "source_type": "OFFICIAL",
          "sale_start": (now_jst() - timedelta(days=400)).isoformat()}
    assert freshness.compute_status(ev) != ST_AVAILABLE_NOW


def test_recent_official_sale_is_still_available_now():
    ev = {"event_type": "GENERAL_SALE", "source_type": "OFFICIAL",
          "sale_start": (now_jst() - timedelta(hours=2)).isoformat()}
    assert freshness.compute_status(ev) == ST_AVAILABLE_NOW


def test_non_official_sale_is_never_available_now():
    """SNS 報告は販売開始直後でも「今買える」にしない。"""
    ev = {"event_type": EVENT_FIRST_COME, "source_type": "SOCIAL_REPORT",
          "sale_start": (now_jst() - timedelta(hours=1)).isoformat()}
    assert freshness.compute_status(ev) != ST_AVAILABLE_NOW


def test_pipeline_enrich_does_not_promote_old_sale(tmp_path):
    """パイプライン（enrich）を通しても古い販売が BUY NOW にならない。"""
    mod = _load_pipeline()
    raw = [{
        "tcg": "POKEMON", "product_id": "old-box", "product_name": "旧BOX",
        "event_type": EVENT_FIRST_COME, "store": "YODOBASHI",
        "source_type": "RETAILER_OFFICIAL", "confidence": "high",
        "sale_start": (now_jst() - timedelta(days=400)).isoformat(),
        "observed_at": now_jst().isoformat(), "price": 7200,
        "shrink_status": SHRINK_UNKNOWN,
    }]
    events, _ = mod.enrich(raw, {})
    assert events[0]["status"] != ST_AVAILABLE_NOW
    assert events[0]["buy_now"] is False


# ── HIGH: 記事日付が読めない入荷情報は取り込まない ────────────────────────
def test_scraped_restock_without_article_date_is_skipped():
    """取得時刻を報告時刻の代わりにしない（古い記事が常に fresh になる穴）。"""
    c = PokemonCardOfficialCollector()
    text = ("ポケモンカードゲーム 拡張パック テストBOX\n"
            "再入荷しました 価格 7,200円\n在庫あり")
    assert c.parse(text, "https://www.pokemon-card.com/info/") == []


def test_scraped_restock_with_article_date_uses_it():
    c = PokemonCardOfficialCollector()
    text = ("ポケモンカードゲーム 拡張パック テストBOX\n"
            "更新日 2026年9月25日 12:00 再入荷しました\n価格 7,200円")
    evs = c.parse(text, "https://www.pokemon-card.com/info/")
    assert evs and evs[0].reported_at is not None
    assert evs[0].reported_at.startswith("2026-09-25")


# ── HIGH: 日時の位置割当をやめ、ラベル近傍のみ採用する ────────────────────
def test_update_date_is_not_used_as_sale_start():
    got = PokemonCardOfficialCollector.extract_labeled_datetimes(
        "発売日 2024年5月10日 販売中 2023年1月5日 10:00 更新")
    assert got.get("sale_start", "").startswith("2024-05-10")


def test_lottery_dates_are_assigned_by_label():
    got = PokemonCardOfficialCollector.extract_labeled_datetimes(
        "当選発表 2026年10月20日 応募期間 2026年10月1日 〜 2026年10月10日")
    assert got["application_start"].startswith("2026-10-01")
    assert got["application_end"].startswith("2026-10-10")
    assert got["result_date"].startswith("2026-10-20")


def test_inconsistent_period_is_dropped():
    """終了が開始より前になる組は採用しない。"""
    got = PokemonCardOfficialCollector.extract_labeled_datetimes(
        "応募期間 2026年10月10日 〜 2026年10月1日")
    assert "application_start" not in got and "application_end" not in got


def test_adjacent_product_date_is_not_used_as_sale_end():
    """商品一覧で隣の商品の発売日を sale_end にしない。"""
    from src.collectors.tcg.onepiece import OnePieceProductsCollector
    text = ("ブースターパック 商品A\n発売日\n2026.10.10\n"
            "メーカー希望小売価格\n240円(税込)\n"
            "ブースターパック 商品B\n発売日\n2026.11.07\n"
            "メーカー希望小売価格\n660円(税込)")
    evs = OnePieceProductsCollector().parse(text, "https://www.onepiece-cardgame.com/products/")
    assert evs
    for ev in evs:
        assert ev.sale_end is None


# ── MEDIUM: ページ記載の金額を「定価」に昇格させない ──────────────────────
def test_page_price_is_not_promoted_to_retail():
    mod = _load_pipeline()
    raw = [{
        "tcg": "ONE_PIECE", "product_id": "pack-a", "product_name": "ブースターパック",
        "event_type": "GENERAL_SALE", "store": "ONEPIECE_CARD_OFFICIAL",
        "source_type": "OFFICIAL", "confidence": "high", "price": 240,
        "observed_at": now_jst().isoformat(), "shrink_status": SHRINK_UNKNOWN,
    }]
    events, _ = mod.enrich(raw, {})
    # 検証済み定価が無い限り retail_price は None（240円をBOX定価にしない）
    assert events[0]["premium"]["retail_price"] is None
    assert events[0]["premium"]["premium_percent"] is None


def test_verified_retail_price_is_used():
    mod = _load_pipeline()
    raw = [{
        "tcg": "POKEMON", "product_id": "box-a", "product_name": "BOX",
        "event_type": "GENERAL_SALE", "store": "POKEMON_CARD_OFFICIAL",
        "source_type": "OFFICIAL", "confidence": "high", "price": 360,
        "observed_at": now_jst().isoformat(), "shrink_status": SHRINK_UNKNOWN,
    }]
    events, _ = mod.enrich(raw, {"box-a": 7200})
    assert events[0]["premium"]["retail_price"] == 7200


# ── MEDIUM: 重複統合の corroborations が投入順に依存しない ────────────────
def test_corroborations_is_order_independent():
    base = {"tcg": "POKEMON", "product_id": "a", "store": "LAWSON",
            "event_type": EVENT_RESTOCK, "observed_at": now_jst().isoformat()}
    sns = dict(base, source_type="SOCIAL_REPORT", confidence="low", source_url="x")
    official = dict(base, source_type="RETAILER_OFFICIAL", confidence="high",
                    source_url="z")
    a = dedupe.dedupe_events([sns, official])[0]["corroborations"]
    b = dedupe.dedupe_events([official, sns])[0]["corroborations"]
    assert a == b == 2


# ── MEDIUM: 買取価格も1件では採用しない ───────────────────────────────────
def test_buyback_requires_multiple_samples():
    from src.tcg.secondary import buyback_of
    one = [{"source": "card_shop_buyback", "price": 999999.0}]
    assert buyback_of(one) is None
    three = [{"source": "card_shop_buyback", "price": p}
             for p in (8000.0, 8200.0, 8400.0)]
    assert buyback_of(three) == 8200


# ── LOW: 販売方式が読めない入荷報告は取り込まない ─────────────────────────
def test_report_without_detectable_method_is_skipped(tmp_path):
    from src.tcg.reports import CSV_COLUMNS, load_reports
    path = tmp_path / "r.csv"
    row = ("POKEMON,box-c,テストBOX,店舗,LAWSON,大阪府,大阪市,"
           f"{now_jst().isoformat()},,,social,,よくわからない書き込み,,,")
    path.write_text(",".join(CSV_COLUMNS) + "\n" + row + "\n", encoding="utf-8")
    assert load_reports(path) == []


def test_report_with_explicit_event_type_is_used(tmp_path):
    from src.tcg.reports import CSV_COLUMNS, load_reports
    path = tmp_path / "r.csv"
    row = ("POKEMON,box-d,テストBOX,店舗,LAWSON,大阪府,大阪市,"
           f"{now_jst().isoformat()},,,social,,メモ,GUERRILLA_SALE,,")
    path.write_text(",".join(CSV_COLUMNS) + "\n" + row + "\n", encoding="utf-8")
    out = load_reports(path)
    assert out and out[0]["event_type"] == "GUERRILLA_SALE"


def test_sold_out_flag_is_honoured():
    """SOLD_OUT 判定が実際に到達する（不明なら SOLD_OUT にしない）。"""
    ev = TcgEvent(tcg="POKEMON", product_id="a", product_name="n",
                  event_type=EVENT_RESTOCK, store="LAWSON",
                  source_type="RETAILER_OFFICIAL",
                  reported_at=now_jst().isoformat(), sold_out=True).to_dict()
    assert freshness.compute_status(ev) == "SOLD_OUT"
    ev2 = dict(ev, sold_out=None)
    assert freshness.compute_status(ev2) != "SOLD_OUT"


def test_dedupe_key_matches_dedupe_module():
    from src.tcg.dedupe import event_key
    ev = TcgEvent(tcg="POKEMON", product_id="a", product_name="n",
                  event_type=EVENT_RESTOCK, store="LAWSON")
    assert ev.dedupe_key == event_key(ev.to_dict())


def test_open_label_differs_for_sale_and_lottery():
    """発売前の販売情報を「受付中」と表示しない。"""
    from src.content.daily_lp_generator import DailyLPGenerator
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    sale = DailyLPGenerator._tcg_card(g, {
        "tcg": "ONE_PIECE", "product_name": "商品", "event_type": "GENERAL_SALE",
        "status": "OPEN", "store": "ONEPIECE_CARD_OFFICIAL", "source_type": "OFFICIAL",
        "shrink_status": "UNKNOWN", "verification": "Confirmed"})
    assert "発売前" in sale and "受付中" not in sale
    lot = DailyLPGenerator._tcg_card(g, {
        "tcg": "POKEMON", "product_name": "商品", "event_type": "LOTTERY",
        "status": "OPEN", "store": "POKEMON_CENTER_ONLINE", "source_type": "OFFICIAL",
        "shrink_status": "UNKNOWN", "verification": "Confirmed"})
    assert "受付中" in lot


# ── 再レビュー指摘の回帰固定 ──────────────────────────────────────────────
def test_hatsubai_chu_is_not_taken_as_sale_start():
    """「発売中」に部分一致して無関係な日付を拾わない。"""
    got = PokemonCardOfficialCollector.extract_labeled_datetimes(
        "発売中 2023年1月5日 10:00 更新")
    assert "sale_start" not in got


def test_restock_cannot_bypass_ttl_gate_via_hatsubai_chu():
    """記事日付が無い再入荷が「発売中」由来の未来日でゲートを抜けない。"""
    from src.collectors.tcg.pokemon import LawsonPokemonCollector
    text = ("ポケモンカード 拡張パック BOX\n"
            "再入荷しました 発売中 2099年11月24日 時点の在庫情報\n価格 7,200円")
    assert LawsonPokemonCollector().parse(text, "https://www.lawson.co.jp/campaign/") == []


def test_period_label_finds_end_across_long_text():
    got = PokemonCardOfficialCollector.extract_labeled_datetimes(
        "応募期間 2026年10月1日 10:00 から たっぷり余白テキストを挟んで "
        "2026年10月10日 23:59 まで")
    assert got["application_start"].startswith("2026-10-01")
    assert got["application_end"].startswith("2026-10-10")


def test_unofficial_source_is_not_ending_soon():
    """未確認情報を「締切間近」バケットに入れない。"""
    ev = {"event_type": EVENT_FIRST_COME, "source_type": "SOCIAL_REPORT",
          "sale_start": (now_jst() - timedelta(days=400)).isoformat(),
          "sale_end": (now_jst() + timedelta(hours=5)).isoformat()}
    assert freshness.compute_status(ev) == "UNVERIFIED"


def test_store_official_report_can_reach_available_now(tmp_path):
    """店舗公式を確認した報告だけが「今買える」に到達できる。"""
    from src.tcg.reports import CSV_COLUMNS, load_reports
    path = tmp_path / "r.csv"
    now = now_jst().isoformat()
    rows = [
        # source=store_official かつ official_confirmation=true
        f"POKEMON,box-e,テストBOX,ローソン梅田店,LAWSON,大阪府,大阪市,{now},"
        ",,store_official,,本日入荷しました,,true,",
        # official_confirmation が無ければ公式にしない
        f"POKEMON,box-f,テストBOX,ローソン難波店,LAWSON,大阪府,大阪市,{now},"
        ",,store_official,,本日入荷しました,,,",
    ]
    path.write_text(",".join(CSV_COLUMNS) + "\n" + "\n".join(rows) + "\n",
                    encoding="utf-8")
    out = load_reports(path)
    assert out[0]["source_type"] == "STORE_OFFICIAL"
    assert freshness.compute_status(out[0]) == ST_AVAILABLE_NOW
    assert out[1]["source_type"] == "SOCIAL_REPORT"
    assert freshness.compute_status(out[1]) != ST_AVAILABLE_NOW


def test_empty_payload_matches_normal_schema(tmp_path, monkeypatch):
    """失敗時のフォールバック出力が正常系とスキーマ一致。"""
    import json
    mod = _load_pipeline()
    monkeypatch.setattr(mod, "EXPORT_DIR", tmp_path)
    mod._write_empty_payload("boom")
    restocks = json.loads((tmp_path / "restocks.json").read_text(encoding="utf-8"))
    assert "signals" in restocks and restocks["items"] == []
    latest = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    assert latest["counts"]["events"] == 0 and latest["error"] == "boom"
