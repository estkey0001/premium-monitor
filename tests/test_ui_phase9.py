"""UI Phase 9: 運営者向けのページ（?page=admin&section=…）。読むだけ・ログイン無し・秘密の値を出さない。

旧UIにしかなかった運営の情報（取得元・データ品質・AI 候補・資金配分・実行履歴・通知・システム）を移す。
判定（利益・照合・確定ルート）はやり直さず、既存の判定（record_route_ok など）を通すだけ。データはすべて架空。
"""

from __future__ import annotations

import copy
import importlib.util
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from src.content.ui import admin, navigation, shell
from src.content.ui import opportunity as opp

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P6 = _load("ui_phase6_for_p9", ROOT / "tests" / "test_ui_phase6.py")
RF = _load("route_fixtures_p9", ROOT / "tests" / "route_fixtures.py")
KW, NOW, CHROME, _run, _HELPERS = P6.KW, P6.NOW, P6.CHROME, P6._run, P6._HELPERS
SAFE = RF.safe_route(NOW, "prod_tcam")
RID = opp.route_key(SAFE)


def _t(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


ADMIN = {
    "collector": {"generated_at": _t(hours=1), "shop_detail": [
        {"shop_id": "kaitori_shouten", "total": 5, "ok": 5, "failed": 0, "top_reason": "",
         "last_attempt_at": _t(hours=1), "last_success_at": _t(hours=1), "last_observed_at": _t(hours=1)},
        {"shop_id": "mobile_ichiban", "total": 5, "ok": 0, "failed": 5, "top_reason": "timeout",
         "last_attempt_at": _t(hours=1), "last_success_at": _t(days=3), "last_observed_at": _t(days=3)},
        {"shop_id": "kaitori_itchome", "total": 4, "ok": 2, "failed": 2, "top_reason": "timeout",
         "last_attempt_at": _t(hours=1), "last_success_at": _t(days=5), "last_observed_at": _t(days=5)},
        {"shop_id": "2ndstreet", "total": 4, "ok": 0, "failed": 4, "top_reason": "product_not_listed",
         "last_attempt_at": _t(hours=1), "last_success_at": None, "last_observed_at": None}],
        "suspicious_prices": [{"x": 1}], "price_changes": [], "fetch_failed": [{}, {}]},
    "dq_report": {"consecutive_failed_shops": [{"shop_id": "mobile_ichiban", "consecutive_failures": 12}],
                  "collection": {"total_shops": 4, "shops_all_failed": 2, "total_jobs": 18, "ok_jobs": 7,
                                 "success_rate_pct": 38.9},
                  "failure_reasons": [{"reason": "timeout", "count": 7}]},
    "diagnostics": {"generated_at": _t(minutes=5), "candidate_count": 3, "eligible_count": 1,
                    "exclusion_reasons": {"unverified_buy_price": 1, "invalid_identity": 1},
                    "candidates": [{"product_id": "prod_tgame", "route_type": "RETAIL_TO_BUYBACK",
                                    "reasons": ["unverified_buy_price"], "primary": "unverified_buy_price"},
                                   {"product_id": "prod_gr4", "route_type": "RETAIL_TO_BUYBACK",
                                    "reasons": ["invalid_identity"], "primary": "invalid_identity"}]},
    "ai": {"generated_at": _t(minutes=10), "today_tasks": ["本日の対象なし（データ取得状況を Health タブで確認）"],
           "todays_opportunities": [
               {"product": "テストカメラ 本体", "product_id": "prod_tcam", "kind": "main", "route_id": RID,
                "action": "BUY", "buy_now": "BUY", "opportunity_score": 82, "confidence": "high",
                "buy_conditions": {"buy": "公式 ≤ ¥200,000", "sell": "買取店A ≥ ¥232,000", "roi": "ROI ≥ 8%"},
                "net_profit": 30200, "buy_price_evidence": "VERIFIED_DATED", "sell_price_evidence": "OBSERVED"},
               {"product": "古いルート", "product_id": "prod_gr4", "kind": "main", "route_id": "gone",
                "action": "BUY", "net_profit": 39009},
               {"product": "参考の候補", "product_id": "prod_tgame", "kind": "reference", "route_id": RID,
                "action": "WAIT", "net_profit": 86651}]},
    "allocation": {"plans": {"1000000": {
        "budget": 1000000, "allocated": 600000, "cash": 400000, "expected_profit": 90000, "expected_roi": 0.15,
        "avg_risk_score": 30, "diversification_score": 60, "max_concentration": 0.4,
        "allocations": [{"product": "テストカメラ 本体", "product_id": "prod_tcam", "route_id": RID, "units": 3,
                         "total": 600000, "expected_profit": 90600, "risk_score": 30, "liquidity_score": 70}],
        "waiting": []}}},
    "execution": {"generated_at": _t(hours=2), "execution_success_rate": 0.5, "prediction_accuracy": 0.8},
    "execution_history": {"executions": [
        {"exec_id": "a", "date": "2026-10-01", "product": "RICOH GR IV", "product_id": "prod_gr4", "status": "INVALIDATED",
         "action": "ALERT", "predicted_net": 39009, "invalidated_reason": "route_identity_missing"},
        {"exec_id": "b", "date": "2026-09-01", "product": "架空の試し品", "product_id": "prod_x", "status": "SUCCESS",
         "predicted_net": 12000, "realized_profit": 12000, "note": "sample: 架空"},
        {"exec_id": "c", "date": "2026-09-20", "product": "テストカメラ 本体", "product_id": "prod_tcam",
         "status": "CANCELLED", "action": "WAIT", "predicted_net": 1000}]},
    "notifications_latest": {"channels": ["discord"], "delivery_status": {"discord": "no_events"}, "suppressed_count": 2},
    "api": {"generated_at": _t(hours=3), "dry_run": True, "per_api": {
        "ebay": {"configured": "not_configured", "status": "disabled_kill_switch", "kill_switch_off": True,
                 "healthy": False, "last_success": None, "app_id": "SECRETVALUE1234567890"},
        "rakuten": {"configured": "configured", "status": "enabled", "kill_switch_off": False, "healthy": True,
                    "last_success": _t(hours=4), "token": "tok_abcdefghijklmnop"}}},
    "health": {"generated_at": "2026-10-03 11:00 JST",
               "health_score": {"data_quality": 20, "profit_discovery": 10, "source_health": 12, "link_quality": 5,
                                "freshness": 6, "total": 53},
               "data_quality": {"total_obs": 100, "usable_obs": 40, "stale_rate": 0.3, "zero_rate": 0.1,
                                "item_url_rate": 0.5},
               "anomalies": {"critical": ["取得成功率 0%: モバイル一番"], "warning": ["item_url率 低下"], "info": []},
               "improvements_top10": [{"stars": 5, "action": "EBAY_APP_ID 設定", "effect": "+¥0（参考0→main昇格）",
                                       "effort": "1時間"}]},
    "coverage": {"total_products": 3, "coverage_score": 40},
    "deploy_check": "  Errors: 0 | Warnings: 3 | OK: 700", "prelaunch_check": "  Errors:   0",
    "optional_shops": ["2ndstreet"],
}
NOTES = [
    {"type": "WATCH_TO_BUY", "product_id": "prod_tcam", "route_id": RID, "route_checked": True,
     "created_at": "2026-10-03 10:00 JST", "message": "買い時\nテストカメラ\n利益 ¥30,200",
     "data": {"product": "テストカメラ 本体"}},
    {"type": "WATCH_TO_BUY", "product_id": "prod_tcam", "route_id": RID, "route_checked": True,
     "created_at": "2026-10-03 10:00 JST", "message": "買い時（重複）", "data": {"product": "テストカメラ 本体"}},
    {"type": "NEW_MAIN", "product_id": "prod_gr4", "route_id": "gone", "route_checked": True,
     "created_at": "2026-10-02 10:00 JST", "message": "新規\nGR IV\n利益 ¥39,009", "data": {"product": "RICOH GR IV"}},
    {"type": "HEALTH_ALERT", "product_id": "_health", "created_at": "2026-10-02 09:00 JST",
     "message": "⚠️ データ品質低下\nHealth Score 70 → 50"},
]
TCG = {"source_health": [
    {"source_name": "公式（商品API）", "status": "HEALTHY", "status_reason": "正常（採用 9件）", "last_checked": _t(hours=1),
     "last_success": _t(hours=1), "events_found": 9, "errors": 0},
    {"source_name": "ポケモンセンターオンライン", "status": "BLOCKED", "status_reason": "HTTP 403", "errors": 1}],
    "lottery_sources": [
        {"source_id": "PCO", "retailer": "ポケモンセンターオンライン", "priority": "P0", "state": "SOURCE_BLOCKED",
         "state_label": "アクセス拒否", "adapter": "pco_lottery", "official_url": "https://www.pokemoncenter-online.com/"},
        {"source_id": "X", "retailer": "危ない店", "priority": "P2", "state": "SOURCE_UNREACHABLE",
         "state_label": "接続不可", "adapter": "", "official_url": "javascript:alert(1)"}],
    "lottery_coverage": {"configured_sources": 2, "implemented_collectors": 1, "healthy_sources": 0,
                         "blocked_sources": 1, "unreachable_sources": 1, "not_implemented_sources": 1}}


def _ctx(**kw):
    base = dict(admin_data=copy.deepcopy(ADMIN), notifications=copy.deepcopy(NOTES),
                profit_routes={"main_routes": [SAFE], "generated_at": _t(minutes=30)},   # AI はこの後に生成
                tcg_report=dict(P6._P1._ctx().tcg_report or {}, **TCG))
    base.update(kw)
    return P6._ctx(**base)


def _admin_html(**kw) -> str:
    root = shell.render_root(_ctx(**kw))
    i = root.index('data-nu-page="admin"')
    return root[i:root.index('<section class="nu-page nu-mp"', i)]


def _panel(html: str, key: str) -> str:
    i = html.index(f'data-nu-ad-panel="{key}"')
    j = html.find('data-nu-ad-panel="', i + 10)
    return html[i:j if j >= 0 else len(html)]


# ── 生成（Python） ─────────────────────────────────────────────────────────

def test_admin_page_registered_and_linked():
    root = shell.render_root(_ctx())
    assert "admin" in navigation.PAGES and shell.PAGE_TITLES["admin"] == "運営"
    assert navigation.LEGACY_HASH_MAP["tab-health"] == {"page": "admin"}               # 旧UIの Health → 運営者向け
    assert 'href="?page=admin"' in root                                                # メニュー・運営者向けの案内
    nav = re.findall(r'class="nu-(?:top|bottom)nav[^"]*".*?</nav>', root, re.S)
    assert nav and all("page=admin" not in n for n in nav)                             # 一般のナビには出さない
    ad = _admin_html()
    for k, _l in admin.SECTIONS:
        assert f'data-nu-ad-panel="{k}"' in ad and f'section={k}"' in ad
    assert "ログイン・権限の仕組みは無く" in ad and "読むだけ" in ad


def test_admin_is_read_only_and_has_no_fake_state():
    ad = _admin_html()
    assert "<button" not in ad and "<form" not in ad and "<input" not in ad          # 押せる偽の操作が無い
    text = re.sub(r"<[^>]+>", " ", ad)
    for w in ("ログイン済み", "ログイン中", "管理者としてログイン", "DEMO", "SAMPLE"):
        assert w not in text


def test_secrets_never_rendered():
    root = shell.render_root(_ctx())
    for secret in ("SECRETVALUE1234567890", "tok_abcdefghijklmnop"):
        assert secret not in root
    assert not re.search(r"(?i)bearer\s+[a-z0-9._-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY|/Users/", root)
    ad = _admin_html()
    assert "設定済み" in ad and "未設定" in ad and "無効（停止スイッチ）" in ad                  # 有無と状態だけ


def test_source_semantics_attempt_success_observed():
    v = admin.build_shops(ADMIN["collector"], ADMIN["dq_report"], {"2ndstreet"}, NOW)
    by = {s["id"]: s for s in v}
    assert by["kaitori_shouten"]["status"] == admin.OK and by["kaitori_shouten"]["fresh"] == "fresh"
    assert by["mobile_ichiban"]["status"] == admin.FAIL and by["mobile_ichiban"]["consecutive"] == 12
    assert by["kaitori_itchome"]["status"] == admin.WARN and by["kaitori_itchome"]["fresh"] == "stale"
    assert by["2ndstreet"]["status"] == admin.INFO and by["2ndstreet"]["optional"]
    # 試した・成功・観測は別の時刻（試しただけで成功・新しい観測とは言わない）
    assert by["mobile_ichiban"]["attempt"] != by["mobile_ichiban"]["success"]
    src = _panel(_admin_html(), "sources")
    assert "最後に試した" in src and "最後に成功" in src and "最後の観測" in src and "記録なし" in src


@pytest.mark.parametrize("mutate, expect", [
    (dict(ok=0, failed=5), admin.FAIL),                                                 # 正常 → 失敗
    (dict(last_observed_at=_t(days=4)), admin.WARN),                                     # 観測が古い
    (dict(last_observed_at=None), admin.WARN),                                           # 観測の記録なし
])
def test_source_mutations_are_safe(mutate, expect):
    col = copy.deepcopy(ADMIN["collector"])
    col["shop_detail"][0].update(mutate)
    s = admin.build_shops(col, {}, set(), NOW)
    assert next(x for x in s if x["id"] == "kaitori_shouten")["status"] == expect


def test_tcg_blocked_and_unsafe_url():
    src = _panel(_admin_html(), "sources")
    assert "アクセス拒否（人の確認が必要）" in src and "回避はしない" in src
    assert "javascript:" not in src and 'href="https://www.pokemoncenter-online.com/"' in src


def test_data_quality_drilldown_links_to_products():
    dq = _panel(_admin_html(), "data-quality")
    assert "定価が未確認" in dq and "商品の照合が未完了" in dq
    assert "page=product&amp;product_id=prod_tgame" in dq and "page=product&amp;product_id=prod_gr4" in dq
    assert "重大" in dq and "取得成功率 0%: モバイル一番" in dq


def test_ai_current_only_and_previous_generation():
    ai = _panel(_admin_html(), "ai")
    assert "テストカメラ 本体" in ai and "¥30,200" in ai
    assert "古いルート" not in ai and "39,009" not in ai                                  # 今は確定ルートでない
    assert "86,651" not in ai                                                             # 参考の金額は出さない
    # 今も参考ルートの候補は、行は出すが金額は出さない
    ai_ref = _panel(_admin_html(profit_routes={"main_routes": [SAFE], "reference_routes": [SAFE],
                                               "generated_at": _t(minutes=30)}), "ai")
    assert "参考の候補" in ai_ref and "86,651" not in ai_ref and "参考ルート（金額は出さない）" in ai_ref
    assert "前回の生成" not in ai and "運営の管理画面の「取得元」" in ai                         # 旧UIの「Health タブ」を読み替える
    # 利益ルートより前に作った AI の候補は「前回の生成」と出す
    old = copy.deepcopy(ADMIN)
    old["ai"]["generated_at"] = _t(days=2)
    assert "前回の生成" in _panel(_admin_html(admin_data=old), "ai")


def test_capital_confirmed_routes_only():
    cap = _panel(_admin_html(), "capital")
    assert "テストカメラ 本体" in cap and "¥600,000" in cap and "期待 ROI" in cap
    bad = copy.deepcopy(ADMIN)
    bad["allocation"]["plans"]["1000000"]["allocations"][0]["route_id"] = "gone"           # ルートが無効になった
    cap2 = _panel(_admin_html(admin_data=bad), "capital")
    assert "テストカメラ 本体" not in cap2 and "¥600,000" not in cap2 and "合計（生成時の値）は出していない" in cap2


def test_execution_samples_excluded_and_invalidated_kept():
    ex = _panel(_admin_html(), "execution")
    assert "無効（履歴）" in ex and "RICOH GR IV" in ex and "39,009" not in ex             # 履歴は残し、値は出さない
    assert "サンプルの記録 1件は数えない" in ex and "架空の試し品" not in ex                 # サンプルは一覧にも出さない
    assert "—（実績の記録なし）" in ex                                                      # 実績が無ければ成功率を出さない
    real = copy.deepcopy(ADMIN)
    real["execution_history"]["executions"][1]["note"] = "実際の取引"                       # サンプル → 実績
    assert "50.0%" in _panel(_admin_html(admin_data=real), "execution")


def test_notifications_dedupe_current_and_system():
    n = _panel(_admin_html(), "notifications")
    assert n.count("買い時の条件に到達") == 1 and "今も有効" in n and "¥30,200" in n          # 重複は1回
    assert "当時の通知" in n and "39,009" not in n and "当時の内容は出さない" in n            # 今は無効の通知
    assert "データ品質の低下" in n and "discord" in n and "抑制した通知" in n


def test_zero_yen_not_shown_and_effect_text_safe():
    assert not re.search(r"¥0(?![0-9,])", _admin_html())                                  # 0 は「0円」と書く
    assert "0円（参考ルートから確定ルートへの昇格は 0件）" in _panel(_admin_html(), "system")   # 内部の言葉も言い換える


def test_empty_state_without_artifacts():
    ad = _admin_html(admin_data=None, notifications=None)
    for k, _l in admin.SECTIONS:
        assert f'data-nu-ad-panel="{k}"' in ad
    assert "今の AI の候補はありません" in ad and "実行の記録はありません" in ad and "記録なし" in ad


def test_public_pages_have_no_admin_terms():
    root = shell.render_root(_ctx())
    public = admin.without_admin(root.split('<script type="application/json"', 1)[0])
    for w in ("EBAY_APP_ID", "Health Score", "取得失敗", "HTTP 403", "SOURCE_BLOCKED", "連続失敗"):
        assert w not in public


def test_deploy_check_836_and_mutations():
    dc = _load("deploy_check_p9", ROOT / "scripts" / "deploy_check.py")
    page = "<html><head>" + shell.render_head() + "</head><body>" + shell.render_root(_ctx()) + "</body></html>"

    def lv(html):
        return {x["check"]: x["level"] for x in dc._check_new_ui(html)}["admin_ui_safe"]
    assert lv(page) == "ok"
    marker = '<nav class="nu-ad-nav"'
    for bad in ('<button type="button">再取得</button>', "<p>ログイン済み</p>", "<p>token=abcdefghij123456</p>",
                "<p>Bearer abcdefghijklmnopqrstu</p>", "<p>https://discord.com/api/webhooks/1/x</p>"):
        assert lv(page.replace(marker, bad + marker, 1)) == "error", bad
    assert lv(page.replace('data-nu-ad-panel="capital"', 'data-nu-ad-panel="x"', 1)) == "error"


# ── ブラウザ（Chrome） ─────────────────────────────────────────────────────

_S = _HELPERS + """
function sec(){ var p = [].slice.call(R.querySelectorAll('[data-nu-ad-panel]')).filter(function(e){return !e.hidden;});
  return p.map(function(e){return e.getAttribute('data-nu-ad-panel');}).join(); }
"""


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("query, section, title", [("?page=admin", "overview", "運営 - 概要"),
                                                   ("?page=admin&section=sources", "sources", "運営 - 取得元"),
                                                   ("?page=admin&section=data-quality", "data-quality", "運営 - データ品質"),
                                                   ("?page=admin&section=nope", "overview", "運営 - 概要"),
                                                   ("?ui=new&page=admin&section=execution", "execution", "運営 - 実行履歴")])
def test_dom_direct_sections(tmp_path, query, section, title):
    o = _run(tmp_path, _S + "done({page: state().page, sec: sec(), title: document.title});", query=query,
             **dict(KW, admin_data=copy.deepcopy(ADMIN), notifications=copy.deepcopy(NOTES)))
    assert o["page"] == "admin" and o["sec"] == section and o["title"].startswith(title)


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_section_nav_back_forward_and_legacy_health(tmp_path):
    js = _S + """
    var o = {};
    R.querySelector('[data-nu-ad-tab="ai"]').click(); o.a = [location.search, sec()];
    R.querySelector('[data-nu-ad-tab="capital"]').click(); o.b = [location.search, sec(), document.title];
    history.back();
    setTimeout(function(){ o.back = [location.search, sec()]; done(o); }, 300);
    """
    o = _run(tmp_path, js, query="?page=admin", **dict(KW, admin_data=copy.deepcopy(ADMIN)))
    assert o["a"] == ["?page=admin&section=ai", "ai"]
    assert o["b"][0] == "?page=admin&section=capital" and o["b"][2].startswith("運営 - 資金配分")
    assert o["back"] == ["?page=admin&section=ai", "ai"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("width", [500, 640, 700, 768, 1024, 1440])
def test_dom_admin_no_overflow(tmp_path, width):
    js = _S + """
    var o = {};
    ['overview', 'sources', 'data-quality', 'ai', 'capital', 'execution', 'notifications', 'system'].forEach(function(s){
      history.pushState(null, '', '?page=admin&section=' + s); window.dispatchEvent(new PopStateEvent('popstate'));
      o[s] = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    });
    done(o);
    """
    o = _run(tmp_path, js, width=width, query="?page=admin",
             **dict(KW, admin_data=copy.deepcopy(ADMIN), notifications=copy.deepcopy(NOTES)))
    assert all(v <= 0 for v in o.values()), o


def test_legacy_only_items_moved():
    """旧UIにしかなかった運営の情報（前日比較・せどりルート未成立の理由・次に取得すべきデータ・再販の取得状況・
    フリマの成約）も運営者向けのページにある。"""
    data = copy.deepcopy(ADMIN)
    data["health"]["diff_vs_prev"] = {"available": True, "stale_rate": {"prev": 0.4, "cur": 0.3},
                                      "main_route_count": {"prev": 0, "cur": 1}, "new_main": ["prod_tcam"], "lost_main": []}
    data["resale_status"] = {"collected_at": _t(hours=1), "platforms": {
        "ebay": {"status": "blocked_cloud_ip", "label_jp": "Cloud IP制限中"}, "amazon": {"status": "ok_html", "label_jp": "自動取得済"}}}
    data["flea_sold"] = {"mercari": {"generated_at": _t(hours=1), "products": {"x": {"count_recent": 2}, "y": {"count_recent": 0}}}}
    routes = {"main_routes": [SAFE], "generated_at": _t(minutes=30),
              "zero_route_diagnostics": {"prod_tgame": {"product_name": "テストゲーム機", "main_blocked_reason": "有効な仕入候補なし",
                                                        "buy_candidates": 0, "sell_candidates": 2, "stale_excluded": 1}},
              "missing_data_priority": [{"rank": 1, "label": "eBay sold の最新化", "potential_profit": 0,
                                         "product_count": 3, "priority": "low"}]}
    ad = _admin_html(admin_data=data, profit_routes=routes)
    sys_ = _panel(ad, "system")
    assert "前日比較" in sys_ and "30.0%" in sys_ and "prod_tcam" in sys_
    dq = _panel(ad, "data-quality")
    assert "有効な仕入候補なし" in dq and "page=product&amp;product_id=prod_tgame" in dq and "eBay 成約 の最新化" in dq
    assert "見込みの利益 0円" not in dq and not re.search(r"¥0(?![0-9,])", dq)
    src = _panel(ad, "sources")
    assert "Cloud IP制限中" in src and "自動取得済" in src and "メルカリ" in src and "最近の成約がある商品" in src


def test_check_results_are_labeled_previous_ci_with_time():
    """公開前チェックの結果は前回の CI のもの（このページの生成より前）と明記し、実行日時を出す。"""
    data = copy.deepcopy(ADMIN)
    data["deploy_check"] = " Deploy Check (10 items)\n 実行日時: 2026-10-05T12:00:00+09:00\n  Errors: 0 | Warnings: 1 | OK: 9"
    ov = _panel(_admin_html(admin_data=data), "overview")
    assert "前回の CI の公開前チェック" in ov and "10/05 12:00" in ov and "今の公開のチェックではない" in ov
    assert "実行の日時は記録なし" in ov                                                    # prelaunch は日時なし


def test_admin_times_are_absolute_without_check_word():
    """運営者向けの時刻は絶対時刻だけ（閲覧時の「N分前確認」に書き換えない。生成・試行・通知に「確認」を付けない）。"""
    ad = _admin_html()
    assert "data-nu-time=" not in ad and not re.search(r"\d\d:\d\d確認", ad)


def test_execution_learning_and_capital_previous():
    data = copy.deepcopy(ADMIN)
    data["execution"].update({"invalidated_count": 82, "sample_excluded_count": 128,
                              "insights_top10": ["買取は日次で更新される"],
                              "learning_coefficients": {"opportunity_score_coeff": 1.0, "sample_size": 0, "confidence": "low"}})
    data["allocation"]["generated_at"] = _t(days=2)                                     # 利益ルートより前
    ad = _admin_html(admin_data=data)
    ex = _panel(ad, "execution")
    assert "無効 82件・サンプル 128件" in ex and "今週学んだこと" in ex and "利益の判定には使わない" in ex
    assert "前回の生成" in _panel(ad, "capital")


# ── 再レビューの指摘への対応 ───────────────────────────────────────────────

def test_check_text_keeps_head_time_from_long_output():
    """CI の出力は数万字。実行日時はヘッダ（先頭）にあり、末尾だけ読むと失われる（再レビュー Medium）。"""
    full = " Deploy Check (900 items)\n 実行日時: 2026-10-06T12:01:00+09:00\n" + ("  ✅ [x] ok\n" * 9000) \
        + "\n  Errors: 0 | Warnings: 33 | OK: 764\n"
    t = admin.check_text(full)
    assert len(t) < 4200 and "Errors: 0" in t
    s = admin._check_summary(t)
    assert s["at"] == "2026-10-06T12:01:00+09:00" and s["text"] == "エラー 0・警告 33・OK 764"
    assert admin._check_summary(admin.check_text(full.replace(" 実行日時: 2026-10-06T12:01:00+09:00\n", "")))["at"] == ""


def test_cli_deploy_check_prints_run_time(monkeypatch):
    """CI が実行する `src.cli deploy-check-lp` の出力に実行日時が入る（scripts/deploy_check.main ではなく）。"""
    from click.testing import CliRunner
    import types
    from src import cli
    monkeypatch.setitem(sys.modules, "deploy_check", types.SimpleNamespace(check=lambda: []))
    out = CliRunner().invoke(cli.cli, ["deploy-check-lp"]).output
    assert re.search(r"^ 実行日時: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00$", out, re.M)
    assert admin._check_summary(admin.check_text(out))["at"]


def _warn(**col):
    base = {"suspicious_prices": [], "summary": {}, "shop_detail": []}
    base.update(col)
    return admin.collector_warn(base, {"2ndstreet"}, 5)


def test_collector_warn_levels_match_legacy_order():
    """旧表示の警告バーと同じ分類・順序（隔離した価格は精度の問題に数えない。変動は誤りとは限らない）。"""
    from src.market.price_quality import HARD_REJECT_REASONS
    hard = sorted(HARD_REJECT_REASONS)[0]
    assert _warn()["level"] == "none"
    assert _warn(summary={"low_confidence_count": 1})["level"] == "strong"
    assert _warn(suspicious_prices=[{"reason": hard, "product_alias": "a", "shop": "s"}])["level"] == "strong"
    assert _warn(suspicious_prices=[{"reason": hard, "action": "rejected", "product_alias": "a", "shop": "s"}])["level"] == "rejected"
    mv = _warn(suspicious_prices=[{"reason": "price_change_over_20pct", "product_alias": "a", "shop": "s"}] * 2)
    assert mv["level"] == "moves" and mv["moves"] == 1                                     # 同じ商品・店は1件
    assert _warn(shop_detail=[{"shop_id": "x", "failed": 5}])["level"] == "soft"
    assert _warn(shop_detail=[{"shop_id": "x", "failed": 4}])["level"] == "none"
    assert _warn(shop_detail=[{"shop_id": "2ndstreet", "failed": 9}])["level"] == "info"   # 任意の店だけ
    src = _panel(_admin_html(), "sources")
    assert "取得の警告（旧表示の警告バーと同じ分類）" in src and "低信頼度の価格" in src


def test_price_changes_split_and_reason_labels():
    data = copy.deepcopy(ADMIN)
    data["collector"]["price_changes"] = [{"change_pct": -3.9}, {"change_pct": 43.3}, {"change_pct": -20.0}]
    ad = _admin_html(admin_data=data)
    assert "20% 以上 2件・それ未満 1件" in _panel(ad, "data-quality")
    src = _panel(ad, "sources")
    assert "時間切れ <span class=\"nu-osub\">timeout</span>" in src                      # 言葉＋コード（小さく）
    assert "サイトに掲載なし <span class=\"nu-osub\">product_not_listed</span>" in src
    assert "時間切れ" in _panel(ad, "system")


def test_route_diagnostic_totals_and_observed_prices():
    routes = {"main_routes": [SAFE], "generated_at": _t(minutes=30), "zero_route_diagnostics": {
        "prod_tgame": {"product_name": "テストゲーム機", "main_blocked_reason": "有効な仕入候補なし", "buy_candidates": 1,
                       "sell_candidates": 2, "stale_excluded": 3, "overseas_stale": 1,
                       "rejection_top5": [["stale_over_14d", 3], ["price_zero", 2]],
                       "min_usable_buy": 50000, "min_usable_buy_source": "量販店", "min_usable_buy_identity_verified": True,
                       "max_usable_sell": 61000, "max_usable_sell_source": "買取店B",
                       "max_usable_sell_identity_verified": False}}}
    dq = _panel(_admin_html(profit_routes=routes), "data-quality")
    assert "仕入れの候補 1件・売却の候補 2件・古くて外した価格 3件（うち海外の成約 1件）" in dq
    assert "14日より古い 3件・0円（取得失敗） 2件" in dq
    assert "最安の仕入れ 量販店 ¥50,000" in dq and "最高の売却 買取店B ¥61,000（参考・照合未了）" in dq


def test_execution_open_row_without_current_route_hides_amount():
    data = copy.deepcopy(ADMIN)
    data["execution_history"]["executions"].append(
        {"exec_id": "d", "date": "2026-10-02", "product": "照合できない品", "product_id": "prod_gr4", "status": "OPEN",
         "action": "BUY", "predicted_net": 55555, "route_id": "gone"})
    ex = _panel(_admin_html(admin_data=data), "execution")
    assert "照合できない品" in ex and "55,555" not in ex and "今のルートと照合できない（当時の値は出さない）" in ex


def test_capital_all_empty_is_one_line():
    data = copy.deepcopy(ADMIN)
    data["allocation"]["plans"] = {str(b): {"budget": b, "allocations": [], "waiting": []} for b in (300000, 1000000)}
    cap = _panel(_admin_html(admin_data=data), "capital")
    assert "どの予算（¥300,000・¥1,000,000）も配分・待機は 0件" in cap and "<details" not in cap


def test_overview_explains_counts_and_page_time():
    ov = _panel(_admin_html(), "overview")
    assert "確定のせどりルート）。せどりルートは確定 1件・参考 0件" in ov and "このページの生成" in ov
    assert "取得の警告" in ov and "80 以上で正常" in ov and "旧表示の警告バーと同じ分類" in ov
    low = copy.deepcopy(ADMIN)
    low["health"]["health_score"]["total"] = 30
    assert ">低い<" in _panel(_admin_html(admin_data=low), "overview")


def test_ebay_promotion_condition_in_system():
    data = copy.deepcopy(ADMIN)
    data["min_sold_samples"] = 3
    s = _panel(_admin_html(admin_data=data), "system")
    assert "14日以内の成約" in s and "3件以上・成約日時つき" in s and "SECRETVALUE" not in s


def test_without_admin_handles_nested_sections_without_mypage():
    html = ('<main><section data-nu-page="home">公開</section>'
            '<section class="nu-page nu-ad" data-nu-page="admin"><section>内部A</section><section>内部B</section></section>'
            '<section data-nu-page="routes">公開2</section></main>')
    out = admin.without_admin(html)
    assert "内部" not in out and "公開" in out and "公開2" in out
