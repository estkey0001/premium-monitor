"""Phase 0.1: ユーザーに誤解を招く表示（確認日不明の定価での利益・時刻のずれ・警告の重大度）のテスト。

各テストは、修正前の挙動なら失敗する形（否定対照）を含める。
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.market import price_evidence as pe

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 2, 17, 49, tzinfo=JST)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _product(pid, *, retail=0, official=None, updated_at=None):
    return SimpleNamespace(id=pid, retail_price=retail, official_price=official,
                           official_price_updated_at=updated_at)


def _deal(pid, profit, name=None, category="game_console", rate=0.5):
    return SimpleNamespace(product_id=pid, product_name=name or pid, net_profit_jpy=profit,
                           net_profit_rate=rate, category=category, best_buyback_shop="モバイル一番",
                           user_level="beginner_easy")


def _generator(evidence: dict):
    from src.content.daily_lp_generator import DailyLPGenerator
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g.settings = {}
    g._msrp_evidence = evidence
    return g


# ── 価格の根拠の分類 ────────────────────────────────────────────────────────

def test_price_evidence_classification():
    assert pe.classify_product_msrp(_product("ps5", retail=119980), NOW) == pe.CONFIGURED_REFERENCE
    # official_price はあるが確認日が無い（seed の設定値）も確認日不明
    assert pe.classify_product_msrp(_product("x", official=1000), NOW) == pe.CONFIGURED_REFERENCE
    assert pe.classify_product_msrp(_product("gr4", official=211800, updated_at="2026-10-02T08:49:00+00:00"),
                                    NOW) == pe.VERIFIED_CURRENT
    assert pe.classify_product_msrp(_product("ip", official=179800, updated_at="2026-08-23"),
                                    NOW) == pe.VERIFIED_DATED
    assert pe.classify_product_msrp(_product("old", official=1000, updated_at="2025-12-01"),
                                    NOW) == pe.STALE
    assert pe.classify_product_msrp(_product("none"), NOW) == pe.UNKNOWN
    assert pe.classify_dated_price(1000, "読めない", NOW) == pe.UNKNOWN
    assert pe.classify_dated_price(1000, "2027-01-01", NOW) == pe.UNKNOWN  # 未来の確認日
    # 既存の freshness_basis を読み替える
    assert pe.from_freshness_basis("config_unknown_date") == pe.CONFIGURED_REFERENCE
    assert pe.from_freshness_basis("verified") == pe.VERIFIED_DATED
    assert pe.from_freshness_basis("observed") == pe.VERIFIED_CURRENT
    assert pe.from_freshness_basis("observed_stale") == pe.STALE
    assert pe.from_freshness_basis(None) == pe.UNKNOWN


def test_profit_display_eligibility_conditions():
    ok = pe.profit_display_eligibility(buy_price=100, buy_evidence=pe.VERIFIED_DATED,
                                       sell_price=200, sell_evidence=pe.VERIFIED_CURRENT)
    assert ok.eligible and ok.reasons == ()
    ng = pe.profit_display_eligibility(buy_price=119980, buy_evidence=pe.CONFIGURED_REFERENCE,
                                       sell_price=192000, sell_evidence=pe.VERIFIED_CURRENT)
    assert not ng.eligible and "buy_configured_reference" in ng.reasons
    ng = pe.profit_display_eligibility(buy_price=0, buy_evidence=pe.VERIFIED_CURRENT, sell_price=1,
                                       sell_evidence=pe.STALE, identity_confirmed=False,
                                       price_kind_allowed=False, costs_known=False)
    assert set(ng.reasons) == {"invalid_buy_price", "sell_stale", "identity_unconfirmed",
                               "price_kind_not_allowed", "costs_unknown"}


# ── 確認日不明の定価は「最高利益」「TOP」「BUY」に出さない ─────────────────────────

def test_unknown_date_msrp_cannot_become_strong_profit_opportunity():
    g = _generator({"prod_ps5_pro": pe.CONFIGURED_REFERENCE})
    deals = [_deal("prod_ps5_pro", 70220, "PlayStation 5 Pro")]
    html = g._section_hero("2026-10-02", "17:49", NOW, NOW, all_deals=deals, beginner_display_count=1)
    assert "最高利益参考" not in html
    assert "参考差額 +¥70,220" in html and "確定利益ではありません" in html


def test_verified_msrp_may_calculate_profit():
    """否定対照: 定価を確認済みなら、これまでどおり「最高利益参考」として出す。"""
    g = _generator({"prod_ps5_pro": pe.CONFIGURED_REFERENCE, "prod_gr4": pe.VERIFIED_CURRENT})
    deals = [_deal("prod_ps5_pro", 70220), _deal("prod_gr4", 12000, category="camera")]
    html = g._section_hero("2026-10-02", "17:49", NOW, NOW, all_deals=deals, beginner_display_count=2)
    # 確認日不明の +¥70,220 の方が大きいが、「最高利益」は確認済みの +¥12,000 で出す
    assert "最高利益参考 <strong>+¥12,000</strong>" in html
    assert "70,220" not in html


def test_unknown_date_msrp_cannot_enter_buy_top_list():
    g = _generator({"prod_ps5_pro": pe.CONFIGURED_REFERENCE, "prod_gr4": pe.VERIFIED_CURRENT})
    deals = [_deal("prod_ps5_pro", 70220, "PlayStation 5 Pro"),
             _deal("prod_gr4", 12000, "RICOH GR IV", category="camera")]
    html = g._tab_ranking(deals, [], [d for d in deals if d.category == "game_console"])
    panel = html.split('id="rtab-all">', 1)[1].split("</div>\n", 1)[0]
    gr_pos, ps_pos = panel.find("RICOH GR IV"), panel.find("PlayStation 5 Pro")
    assert 0 <= gr_pos < ps_pos                       # 確認済みが先
    first_row = panel.split('<div class="rank-row', 2)[1]
    assert "RICOH GR IV" in first_row and "&#128081;" in first_row   # 👑 は確認済みに
    ps_row = panel[panel.rfind('<div class="rank-row', 0, ps_pos):]
    assert "rank-ref" in ps_row and "&#128081;" not in ps_row and "参考差額 +¥70,220" in ps_row
    # ゲーム機タブ（確認済みが無い）でも 👑・順位を付けない
    game = html.split('id="rtab-game">', 1)[1].split("</div>\n", 1)[0]
    assert "&#128081;" not in game and "rank-ref" in game


def _route(**kw):
    r = {"buy_price": 119980, "sell_price": 192000, "net_profit": 70220, "roi": 0.585,
         "buy_price_evidence": "CONFIGURED_REFERENCE", "sell_price_evidence": "VERIFIED_CURRENT",
         "sell_canonical_type": "BUYBACK_CASH"}
    r.update(kw)
    return r


def test_new_ui_unknown_date_price_not_promoted_to_buy_or_high_profit():
    from src.content.ui import home
    o = {"product": "PS5 Pro", "action": "BUY", "kind": "main", "confidence": "high", "priority": 1,
         "buy_source": "公式", "sell_source": "モバイル一番", **_route()}
    for ev in ("CONFIGURED_REFERENCE", "STALE", "UNKNOWN", None):
        m = home.build_home_model(tcg_report={}, opportunities={"todays_opportunities": [dict(o, buy_price_evidence=ev)]},
                                  profit_routes={"main_routes": [_route(buy_price_evidence=ev)]},
                                  legacy_lotteries=[], now=NOW)
        assert m.counts["high_profit"] == 0
        assert not [a for a in m.opp_cards if a.action == "BUY"] and m.hidden_prices == 1
    # 否定対照: 仕入れ・売却とも確認済みなら BUY・高利益に出る
    m = home.build_home_model(tcg_report={}, opportunities={"todays_opportunities": [
        dict(o, buy_price_evidence="VERIFIED_DATED", roi=0.5)]},
        profit_routes={"main_routes": [_route(buy_price_evidence="VERIFIED_DATED", roi=0.5)]},
        legacy_lotteries=[], now=NOW)
    assert m.counts["high_profit"] == 1 and [a for a in m.opp_cards if a.action == "BUY"]


def test_profit_routes_carry_price_evidence():
    gpr = _load_script("generate_profit_routes")
    buy = {"source_name": "店A", "source_id": "a", "product_id": "p", "product_name": "P", "price": 100000,
           "price_type": "shop_sale_price", "condition": "new", "observed_at": "2026-10-02",
           "freshness_basis": "observed", "confidence": "high"}
    sell = dict(buy, source_name="店B", source_id="b", price=130000, price_type="buyback_price",
                freshness_basis="config_unknown_date")
    r = gpr._make_route(buy, sell, NOW)
    assert r["buy_price_evidence"] == "VERIFIED_CURRENT"
    assert r["sell_price_evidence"] == "CONFIGURED_REFERENCE"


# ── 時刻: UTC → JST、タイムゾーン付きの保存 ──────────────────────────────────

@pytest.fixture
def utc_env():
    """CI のランナーと同じく、実行環境のタイムゾーンを UTC にする。"""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def test_utc_timestamp_renders_correct_jst(utc_env):
    from src.content.daily_lp_generator import _generation_time, _jst_str
    gen = _generation_time()
    utc_now = datetime.now(timezone.utc)
    assert gen.utcoffset() == timedelta(hours=9)                  # JST に変換済み
    assert abs((gen - utc_now).total_seconds()) < 5               # 同じ瞬間（9時間ずれていない）
    assert _jst_str(gen) == gen.strftime("%Y-%m-%d %H:%M JST")
    assert _jst_str(datetime(2026, 10, 2, 8, 49, tzinfo=timezone.utc)) == "2026-10-02 17:49 JST"
    # 否定対照: 修正前の形（タイムゾーン無しの UTC に「JST」と付ける）は9時間ずれる
    naive = datetime.now()
    assert naive.tzinfo is None and _jst_str(naive) != _jst_str(gen)


def test_existing_naive_timestamp_is_not_reinterpreted():
    """根拠の無い古いタイムゾーン無しの値を、勝手に UTC として補正しない（従来どおり JST として読む）。"""
    from src.content.daily_lp_generator import _jst_str
    assert _jst_str(datetime(2026, 10, 2, 8, 0)) == "2026-10-02 08:00 JST"


def test_workflow_runs_in_jst():
    wf = (ROOT / ".github/workflows/daily_lp.yml").read_text(encoding="utf-8")
    assert "TZ: Asia/Tokyo" in wf


def test_timezone_aware_official_timestamp_preserved(tmp_path, utc_env):
    from src.db.database import Database
    from src.db.repository import Repository
    db = Database(str(tmp_path / "r.db"))
    db.init_schema()
    db.connection.execute(
        "INSERT INTO products (id, name, genre, brand, retail_price, is_active, created_at, updated_at) "
        "VALUES ('p','GR IV','camera','RICOH',194800,1,'2026-10-01T00:00:00','2026-10-01T00:00:00')")
    repo = Repository(db)
    repo.mark_official_price_candidate("p", 211800, "src_ricoh")
    v = db.connection.execute("SELECT official_price_updated_at FROM products WHERE id='p'").fetchone()[0]
    assert v.endswith("+09:00")                                   # タイムゾーン付き（JST のオフセット）
    d = datetime.fromisoformat(v)
    assert abs((d - datetime.now(timezone.utc)).total_seconds()) < 10
    obs = datetime(2026, 10, 2, 8, 49, tzinfo=timezone.utc)
    repo.mark_official_price_candidate("p", 211800, "src_ricoh", observed_at=obs)
    v = db.connection.execute("SELECT official_price_updated_at FROM products WHERE id='p'").fetchone()[0]
    assert v == "2026-10-02T08:49:00+00:00"
    assert repo.get_product("p").official_price_updated_at.astimezone(JST).strftime("%H:%M") == "17:49"
    with pytest.raises(ValueError):
        repo.mark_official_price_candidate("p", 211800, "src_ricoh", observed_at=datetime(2026, 10, 2, 8, 49))


def test_ricoh_collector_stores_aware_utc(monkeypatch, utc_env):
    """RICOH の新規取得は、観測・価格履歴・公式価格の取得時刻をタイムゾーン付きで保存する。

    オフセットは +09:00（observations などはタイムゾーン無しの JST の値と文字列で並べ替えるため）。
    CI と同じ UTC の実行環境でも、取得した瞬間がずれないことを確かめる。
    """
    import logging

    import src.market.official_price_validator as opv
    from src.collectors.official import ricoh
    captured = {}

    class _Repo:
        def insert_observation(self, obs):
            captured["obs"] = obs.observed_at

        def insert_price_history(self, ph):
            captured["ph"] = ph.recorded_at

        def mark_official_price_candidate(self, *a, **kw):
            captured["mark"] = kw.get("observed_at")

    c = ricoh.RicohOfficialCollector.__new__(ricoh.RicohOfficialCollector)
    c.repository = _Repo()
    c.source = SimpleNamespace(id="src_ricoh")
    c.logger = logging.getLogger("t")
    c.log_collection = lambda *a, **kw: None
    c.fetch_page = lambda url: "<html></html>"
    c.hash_html = lambda html: "h"
    c._parse = lambda html, product, url: {"price": 211800, "is_in_stock": True, "raw": {},
                                           "lottery_status": None}
    monkeypatch.setattr(opv, "validate_official_price",
                        lambda **kw: SimpleNamespace(accepted=True, as_dict=lambda: {}))
    product = SimpleNamespace(id="prod_gr4", name="GR IV", retail_price=194800, model_number="", keywords=[])
    c.collect(product, SimpleNamespace(target_url="https://www.ricoh-imaging.co.jp/"))
    assert set(captured) == {"obs", "ph", "mark"}
    for k in ("obs", "ph", "mark"):
        assert captured[k].tzinfo is not None and captured[k].utcoffset() == timedelta(hours=9)
    assert abs((captured["obs"] - datetime.now(timezone.utc)).total_seconds()) < 10   # 同じ瞬間


def test_scanner_scanned_at_is_timezone_aware(tmp_path, utc_env):
    from src.db.database import Database
    from src.db.repository import Repository
    from src.market.beginner_deal_scanner import BeginnerDealScanner
    from src.models.buyback_price import BuybackPriceModel
    db = Database(str(tmp_path / "s.db"))
    db.init_schema()
    db.connection.execute(
        "INSERT INTO products (id, name, genre, brand, retail_price, is_active, created_at, updated_at) "
        "VALUES ('prod_ps5_pro','PS5 Pro','game_console','Sony',119980,1,'2026-10-01T00:00:00','2026-10-01T00:00:00')")
    repo = Repository(db)
    repo.insert_buyback_price(BuybackPriceModel(
        id="b1", product_id="prod_ps5_pro", shop_id="src_mobile_ichiban", shop_name="モバイル一番",
        buyback_price=192000, condition="new_unopened", buyback_url="https://example.com/",
        observed_at=datetime.now(JST), data_source="auto_scraped", link_verified=True, confidence="high"))
    deal = BeginnerDealScanner(repo).scan_product(repo.get_product("prod_ps5_pro"))
    assert deal is not None
    assert deal.scanned_at.utcoffset() == timedelta(hours=9)       # UTC の実行環境でも JST 付き
    assert abs((deal.scanned_at - datetime.now(timezone.utc)).total_seconds()) < 10


def test_scorer_handles_timezone_aware_observation():
    """タイムゾーン付きの観測時刻（RICOH）でも、スコアの鮮度計算が TypeError にならない。"""
    from src.models.observation import ObservationModel
    from src.pipeline.scorer import Scorer
    s = Scorer.__new__(Scorer)
    s.config = {"source_weights": {"official": 1.0}}
    s.repository = SimpleNamespace(list_observations=lambda **kw: [])
    src = SimpleNamespace(source_type="official")
    for at in (datetime.now(JST), datetime.now(timezone.utc), datetime.now()):
        obs = ObservationModel(id="o", product_id="p", source_id="src_ricoh", observation_type="official_price",
                               observed_at=at, price=211800, confidence=0.99)
        r = SimpleNamespace(details={})
        s._calc_confidence(r, obs, src)                             # 例外にならない
        assert r.confidence > 0


def test_ai_opportunities_carry_price_evidence():
    gao = _load_script("generate_ai_opportunities")
    route = {"product_id": "p", "product_name": "P", "buy_source": "店A", "buy_price": 100000,
             "sell_source": "店B", "sell_price": 130000, "net_profit": 20000, "roi": 0.2,
             "route_type": "shop_to_buyback", "route_confidence": "high",
             "buy_observed_age_days": 1, "sell_observed_age_days": 1,
             "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_DATED"}
    main, = gao.build_candidates({"main_routes": [route], "reference_routes": []})
    assert main["buy_price_evidence"] == "VERIFIED_CURRENT" and main["sell_price_evidence"] == "VERIFIED_DATED"
    # 根拠の項目が無いルートは UNKNOWN（新UIは BUY に出さない）
    route.pop("buy_price_evidence")
    main, = gao.build_candidates({"main_routes": [route], "reference_routes": []})
    assert main["buy_price_evidence"] == "UNKNOWN"


# ── 表示する時刻の意味（生成時刻・試行時刻を「情報確認」にしない） ─────────────────

def test_generation_time_not_displayed_as_observation_time():
    from src.content.daily_lp_generator import DailyLPGenerator
    report = {"generated_at": "2026-10-02T17:49:00+09:00",
              "source_health": [{"last_success": "2026-10-02T16:25:00+09:00"},
                                {"last_success": None, "last_attempt": "2026-10-02T17:48:00+09:00"}]}
    assert DailyLPGenerator._nu_data_checked_text(report) == "10/02 16:25"


def test_last_attempt_not_displayed_as_last_success():
    from src.content.daily_lp_generator import DailyLPGenerator
    report = {"generated_at": "2026-10-02T17:49:00+09:00",
              "source_health": [{"last_success": None, "last_attempt": "2026-10-02T17:48:00+09:00",
                                 "errors": 1}]}
    assert DailyLPGenerator._nu_data_checked_text(report) == ""   # 時刻を出さない


# ── 品質ゲートの重大度（ERROR / WARNING / INFO） ───────────────────────────────

def _gate(suspicious, tmp_path, monkeypatch):
    m = _load_script("check_collector_quality")
    monkeypatch.setattr(m, "HISTORY_PATH", tmp_path / "failure_history.json")
    return m.evaluate({"summary": {"total": 1, "ok": 1, "failed": 0}, "suspicious_prices": suspicious,
                       "product_shop_detail": {}, "low_confidence_count": 0})


def test_large_price_movement_is_warning(tmp_path, monkeypatch):
    r = _gate([{"product_alias": "switch2", "shop": "geo", "price": 35000, "reason": "price_change_over_20pct"},
               {"product_alias": "ps5_pro", "shop": "kaitori_shouten", "price": 191700,
                "reason": "outlier_vs_peer_shops"}], tmp_path, monkeypatch)
    assert r["failures"] == []
    assert any("大きく変動した価格 2件" in w for w in r["warnings"])


def test_wrong_product_price_is_error(tmp_path, monkeypatch):
    r = _gate([{"product_alias": "iphone17pro256", "shop": "kaitori_shouten", "price": 192000,
                "reason": "cross_product_same_price"},
               {"product_alias": "iphone17pro256", "shop": "kaitori_shouten", "price": 435000,
                "reason": "above_genre_max"}], tmp_path, monkeypatch)
    assert len(r["failures"]) == 1 and "2件" in r["failures"][0]
    assert not any("大きく変動" in w for w in r["warnings"])


def test_lp_warn_bar_price_movement_is_soft_warning(tmp_path, monkeypatch):
    import src.content.daily_lp_generator as mod
    (tmp_path / "exports/collector_report").mkdir(parents=True)
    (tmp_path / "exports/collector_report/latest.json").write_text(json.dumps({"suspicious_prices": [
        {"product_alias": "switch2", "shop": "geo", "price": 35000, "reason": "price_change_over_20pct"}]}),
        encoding="utf-8")
    monkeypatch.setattr(mod, "__file__", str(tmp_path / "src" / "content" / "daily_lp_generator.py"))
    html = mod.DailyLPGenerator.__new__(mod.DailyLPGenerator)._collector_warn_bar_html()
    assert "collector-warn-soft" in html and "collector-warn-strong" not in html
    assert "⚠ 前回から大きく変動した買取価格が 1件" in html
    # 一般向けの表示に内部の理由コード・チェック番号を出さない
    assert "price_change_over_20pct" not in html and "#8" not in html


def test_false_freshness_is_error(tmp_path, monkeypatch):
    """値が同じで観測日時だけ新しい手動 CSV の変更（鮮度の偽装）は deploy-check で error。"""
    import subprocess
    dc = _load_script("deploy_check")
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    hdr = ("product_alias,source,price_type,price,currency,condition,is_sold,url,observed_at,"
           "data_source,link_verified,price_basis\n")
    f = repo / "data/manual_market_prices.csv"
    f.write_text(hdr + "gr4,ebay,overseas,1850,USD,new,true,u,2026-07-22T10:00:00+09:00,manual_today,true,s\n",
                 encoding="utf-8")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "a"]):
        subprocess.run(cmd, cwd=repo, check=True, env=env)
    f.write_text(hdr + "gr4,ebay,overseas,1850,USD,new,true,u,2026-08-22T10:00:00+09:00,manual_today,true,s\n",
                 encoding="utf-8")
    # 監査スクリプトは自分の置き場所からリポジトリを決めるので、シンボリックリンクでなく複製する
    import shutil
    shutil.copytree(ROOT / "scripts", repo / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(dc, "PROJECT_ROOT", repo)
    levels = {x["check"]: x["level"] for x in dc._check_data_correctness() if str(x.get("message", "")).find("#822") >= 0
              or x["check"].startswith("no_timestamp_only")}
    assert levels and set(levels.values()) == {"error"}
    # 否定対照: 価格が変わった（実際に再確認した）更新は error にしない
    f.write_text(hdr + "gr4,ebay,overseas,1790,USD,new,true,u,2026-08-22T10:00:00+09:00,manual_today,true,s\n",
                 encoding="utf-8")
    assert {x["check"]: x["level"] for x in dc._check_data_correctness()}["no_timestamp_only_update"] == "ok"


def test_beginner_card_labels_unknown_date_msrp_as_reference():
    from src.models.beginner_deal import BeginnerDealModel
    d = BeginnerDealModel(id="x", product_id="prod_ps5_pro", product_name="PlayStation 5 Pro",
                          category="game_console", official_price_jpy=119980, best_buyback_price=192000,
                          best_buyback_shop="モバイル一番", gross_profit_jpy=72020, net_profit_jpy=70220,
                          net_profit_rate=0.585, user_level="beginner_easy", sale_method="normal")
    g = _generator({"prod_ps5_pro": pe.CONFIGURED_REFERENCE})
    html = g._deal_card(d, "badge-watch", "参考差額", buyback_rows=[])
    assert "参考定価（確認日不明）" in html and "参考差額（定価の確認日不明）" in html
    assert "確定利益ではありません" in html and "公式価格（定価）" not in html
    # 否定対照: 定価を確認済みなら従来どおりの表示
    g = _generator({"prod_ps5_pro": pe.VERIFIED_DATED})
    html = g._deal_card(d, "badge-easy", "利益あり", buyback_rows=[])
    assert "公式価格（定価）" in html and "差益（定価購入→最高買取）" in html and "確認日不明" not in html


@pytest.mark.parametrize("verified_ids", [{"prod_gr4"}, set()])
def test_existing_beginner_deploy_checks_pass_with_reference_cards(tmp_path, monkeypatch, verified_ids):
    """確認済みと参考差額の案件が混ざっても、全部が参考差額でも、旧UIの初心者タブ・ランキングの
    deploy-check（#349 #394 #448 #454 #458 #462）が通る（表示の区別で既存の検査を壊していない）。"""
    from src.db.database import Database
    from src.db.repository import Repository
    from src.content.daily_lp_generator import DailyLPGenerator
    from src.models.beginner_deal import BeginnerDealModel
    now = datetime.now(JST)
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    g = DailyLPGenerator(Repository(db))

    def deal(pid, name, cat, off, bb, shop):
        net = bb - off - 1800
        return BeginnerDealModel(id=pid, product_id=pid, product_name=name, category=cat, official_price_jpy=off,
                                 best_buyback_price=bb, best_buyback_shop=shop, gross_profit_jpy=bb - off,
                                 net_profit_jpy=net, net_profit_rate=net / off, user_level="beginner_easy",
                                 sale_method="normal", scanned_at=now)
    deals = [deal("prod_ps5_pro", "PlayStation 5 Pro", "game_console", 119980, 192000, "モバイル一番"),
             deal("prod_switch2", "Nintendo Switch 2", "game_console", 49980, 55300, "買取商店"),
             deal("prod_gr4", "RICOH GR IV", "camera", 211800, 240000, "フジヤカメラ")]
    g._msrp_evidence = {d.product_id: (pe.VERIFIED_CURRENT if d.product_id in verified_ids
                                       else pe.CONFIGURED_REFERENCE) for d in deals}

    def row(shop, price):
        return {"shop_id": "src_x", "shop_name": shop, "buyback_price": price, "condition": "new_unopened",
                "buyback_url": "https://example.com/", "observed_at": now.isoformat(),
                "data_source": "auto_scraped", "link_verified": True, "confidence": "high"}
    bybp = {d.product_id: [row(d.best_buyback_shop, d.best_buyback_price), row("他店", d.best_buyback_price - 300)]
            for d in deals}
    beg = g._tab_beginner(deals, [], buyback_by_product=bybp, latest_buyback_at=now,
                          monitoring_deals=[], fetch_failed_deals=[])
    rank = g._tab_ranking(deals, [], [d for d in deals if d.category == "game_console"])
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs/index.html").write_text(
        f'<html><body><div id="tab-ranking">{rank}</div><div id="tab-beginner">{beg}</div>'
        f'<div id="tab-advanced"></div></body></html>', encoding="utf-8")
    for n in ("config", "data", "exports", "src", "scripts"):  # deploy-check は読むだけ（書き込まない）
        (root / n).symlink_to(ROOT / n)
    dc = _load_script("deploy_check")
    monkeypatch.setattr(dc, "PROJECT_ROOT", root)
    monkeypatch.setattr(dc, "PUBLIC_DIR", root / "docs")
    lv = {r["check"]: r["level"] for r in dc.check()}
    for k in ("ranking_beginner_consistency", "beginner_profit_label_updated", "beginner_profit_above_monitoring",
              "beginner_no_watch_badge_on_profit", "beginner_profit_tier_badges", "beginner_kohaba_note_wording"):
        assert lv.get(k) == "ok", (k, lv.get(k))
    # 表示の区別そのもの
    assert ("参考差額あり（定価の確認日不明）" in beg) and ("参考差額 +¥72,020" in beg)
    assert ("利益あり: <strong>1</strong>件" in beg) == bool(verified_ids)
    assert ("&#128081;" in rank) == bool(verified_ids)
