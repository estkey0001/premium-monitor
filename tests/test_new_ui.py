"""新UI（?ui=new）の土台のテスト（段階B の土台と、UI Phase 1 のジャンル起点の構成）。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
import yaml

from src.content.ui import components as c
from src.content.ui import design_tokens as t
from src.content.ui import home, navigation, shell
from src.content.ui import status as st

JST = home.JST
NOW = datetime(2026, 10, 2, 10, 0, tzinfo=JST)


# ── テスト用データ ─────────────────────────────────────────────────

PCO = "https://www.pokemoncenter-online.com"


def _iso(delta: timedelta) -> str:
    return (NOW + delta).isoformat()


def _lot(status, **kw):
    """TCG 抽選。status は exports 側の値（新UIは日時から状態を計算し直す）。"""
    ev = {"tcg": "POKEMON", "product_name": f"テストBOX {status} {len(kw)}{sorted(kw)}",
          "retailer_name": "公式ストア", "status": status, "event_type": "LOTTERY",
          "source_url": f"{PCO}/news/1", "entry_url": f"{PCO}/lottery/1", "retail_price": 5400,
          "verified": True, "confidence": "high"}
    ev.update(kw)
    return ev


def _shown(m):
    """HOME に表示されるカード [(種類, 状態またはアクション, 本体)]。"""
    return [(r[0], m.states[r[4]["id"]]["status"] if r[0] == "lot" else r[4].action, r[4])
            for r in m.actions]


def _report(lotteries=(), events=()):
    return {"lotteries": list(lotteries), "events": list(events), "source_health": [],
            "lottery_coverage": {}}


def _opp(action="BUY", kind="main", **kw):
    o = {"product": f"商品 {action}", "action": action, "kind": kind, "confidence": "high",
         "buy_price": 100000, "sell_price": 120000, "net_profit": 12000, "roi": 0.12,
         "buy_source": "公式", "sell_source": "買取A", "priority": 1,
         # 生成側（generate_profit_routes / generate_ai_opportunities）が付ける価格の根拠
         "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_CURRENT", "sell_canonical_type": "BUYBACK_CASH"}
    o.update(kw)
    return o


def _model(**kw):
    args = {"tcg_report": _report(), "opportunities": {}, "profit_routes": {},
            "legacy_lotteries": [], "now": NOW}
    args.update(kw)
    return home.build_home_model(**args)


def _root(**kw) -> str:
    """_model と同じ引数で新UI全体を描画する。"""
    args = {"tcg_report": _report(), "opportunities": {}, "profit_routes": {}, "legacy_lotteries": [],
            "now": NOW}
    args.update(kw)
    return shell.render_root(shell.ShellContext(**args))


def _page(html: str, page: str) -> str:
    """新UIの1ページ分（data-nu-page）の HTML。"""
    start = html.index(f'data-nu-page="{page}"')
    end = html.find("</section>", start)
    return html[start:end]


def _ctx(**kw):
    args = {"tcg_report": _report(), "opportunities": {}, "profit_routes": {},
            "legacy_lotteries": [], "updated_text": "10/02 10:00", "source_issue": False}
    args.update(kw)
    return shell.ShellContext(**args)


class _FakeRepo:
    def __getattr__(self, name):
        return lambda *a, **k: []


def _render_lp(monkeypatch, *, new_ui: bool) -> tuple[str, tuple[str, str]]:
    """DB を使わずに LP 全体を組み立てる（新UIの有無だけを切り替える）。
    戻り値は (HTML, 新UIとして差し込んだ (head, root))。"""
    from src.content.daily_lp_generator import DailyLPGenerator
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    with open("config/lp_settings.yaml", encoding="utf-8") as f:
        g.settings = yaml.safe_load(f) or {}
    g.repo = _FakeRepo()
    captured: list = []
    orig = DailyLPGenerator._new_ui_parts

    def fake(self, **k):
        parts = orig(self, **k) if new_ui else ("", "")
        captured.append(parts)
        return parts
    monkeypatch.setattr(DailyLPGenerator, "_new_ui_parts", fake)
    html = g._render_page(
        date_str="2026-10-02", time_str="10:00", latest_buyback_at=None, latest_deals_at=None,
        lp_generated_at=datetime(2026, 10, 2, 10, 0), beginner_easy=[], beginner_watch=[],
        advanced_deals=[], advanced_snaps=[], watch_candidates=[], buyback_alerts=[],
        all_deals=[], iphone_deals=[], game_deals=[])
    monkeypatch.undo()
    return html, captured[0]


# ── 旧UIを壊さない ─────────────────────────────────────────────────

def test_old_ui_unchanged_without_flag(monkeypatch):
    """新UIを足しても、旧UIの部分は1文字も変わらない（追加されるのは新UIの部分だけ）。"""
    without, _ = _render_lp(monkeypatch, new_ui=False)
    with_ui, (head, root) = _render_lp(monkeypatch, new_ui=True)
    assert head and root
    assert with_ui.count(head) == 1 and with_ui.count(root) == 1
    assert with_ui.replace(head, "", 1).replace(root, "", 1) == without
    # 新UIは <body> の直後、旧UIより前にある
    assert with_ui.index('<div id="new-ui-root"') < with_ui.index('<header class="topbar">')


def test_new_ui_only_with_flag():
    head = shell.render_head()
    # ?ui=new のときだけクラスを付ける。cookie / localStorage では既定化しない
    assert "get('ui')==='new'" in head
    assert "localStorage" not in head and "cookie" not in head
    # 旧UIは ui-new クラスがあるときだけ隠す。新UIは無いとき隠す
    assert "html:not(.ui-new) #new-ui-root{display:none!important}" in head
    assert "html.ui-new body>*:not(#new-ui-root){display:none!important}" in head
    root = shell.render_root(_ctx())
    assert "localStorage" not in root and "document.cookie" not in root


def test_old_dom_ids_preserved(monkeypatch):
    html, _ = _render_lp(monkeypatch, new_ui=True)
    for key in ('id="tab-lottery"', 'id="tab-beginner"', 'id="tab-advanced"', 'id="tab-sedori"',
                'id="tab-health"', 'id="main-tab-nav"', 'id="genre-dropdown"'):
        assert html.count(key) == 1, key


# ── ナビゲーション・ルーティング ────────────────────────────────────

def test_navigation_routes():
    assert navigation.PAGES == ("home", "opportunities", "lottery", "restock", "routes", "more",
                                "search", "account")
    root = shell.render_root(_ctx())
    for page in navigation.PAGES:
        assert f'data-nu-page="{page}"' in root
    for i in navigation.NAV_ITEMS + navigation.BOTTOM_ITEMS:
        href = "?ui=new" if i.page == "home" else f"?ui=new&amp;page={i.page}"
        assert f'href="{href}"' in root
    # 段階B の URL（?page=profit）は利益商品へ読み替える
    assert navigation.PAGE_ALIASES == {"profit": "opportunities"}
    # 管理者向けの画面は一般ナビに出さない
    assert "admin" not in "".join(i.page for i in navigation.NAV_ITEMS)
    # 戻る・進むに対応している
    assert "history.pushState" in root and "popstate" in root
    assert "aria-current" in root


@pytest.mark.parametrize("hash_value, page, mode, category", [
    ("#tab-lottery", "lottery", None, None),
    ("#tab-ranking", "opportunities", None, None),
    ("#tab-sedori", "routes", None, None),
    ("#tab-pro", "opportunities", "pro", None),
    ("#tab-advanced", "opportunities", "pro", None),
    ("#tab-beginner", "opportunities", "easy", None),
    ("#tab-health", "account", None, None),
    ("#category-tcg-lottery", "lottery", None, "tcg"),
    ("#category-pro-camera", "opportunities", None, "camera"),
    ("#category-beginner-iphone", "opportunities", None, "smartphone"),
    ("#product-x100vi", "search", None, None),
])
def test_legacy_hash_mapping(hash_value, page, mode, category):
    target = navigation.resolve_legacy_hash(hash_value)
    assert target["page"] == page
    assert target.get("mode") == mode
    assert target.get("category") == category


def test_unknown_hash_not_mapped():
    assert navigation.resolve_legacy_hash("#something-else") is None
    assert navigation.resolve_legacy_hash("") is None


def test_mobile_bottom_nav_exists():
    root = shell.render_root(_ctx())
    assert root.count('class="nu-bottomnav__link"') == 5
    for label in ("HOME", "利益", "抽選", "在庫", "メニュー"):
        assert f'<span class="nu-bottomnav__label">{label}</span>' in root
    css = shell.render_head()
    assert ".nu-bottomnav{position:fixed" in css
    assert f"@media (min-width:{t.BP_TOPNAV}px){{.nu-topnav{{display:flex" in css


def test_accessibility_landmarks():
    root = shell.render_root(_ctx())
    assert '<main id="nu-main"' in root
    for label in ("メインメニュー", "メインメニュー（下部）", "現在地", "ジャンルで絞り込む"):
        assert f'aria-label="{label}"' in root
    assert '<h1 id="nu-home-title"' in root
    # どのページにも h1 が1つ
    for page in navigation.PAGES:
        assert _page(root, page).count("<h1 ") == 1, page
    assert "focus-visible" in shell.render_head()


# ── タップ領域・はみ出し（CSS の決まりごと） ─────────────────────────

def _css_rule(css: str, selector: str) -> str:
    # 規則の先頭にあるセレクタだけを探す（「.nu-list>li>.nu-card{」のような子孫セレクタに一致させない）
    m = re.search(r"(?:^|[{}])" + re.escape(selector) + r"\{([^}]*)\}", css)
    assert m, selector
    return m.group(1)


def test_touch_targets_at_least_44px():
    css = shell.render_head()
    for sel in (".nu-btn", ".nu-topnav__link", ".nu-brand", ".nu-details summary", ".nu-chip",
                ".nu-quick", ".nu-cat", ".nu-purpose", ".nu-filter__search", ".nu-ctx__clear"):
        px = int(re.search(r"min-height:(\d+)px", _css_rule(css, sel)).group(1))
        assert px >= 44, sel
    assert "width:44px;height:44px" in _css_rule(css, ".nu-iconbtn")
    assert "min-height:var(--bottom-nav-h)" in _css_rule(css, ".nu-bottomnav__link")
    assert t.BOTTOM_NAV_HEIGHT >= 44


def test_no_horizontal_overflow_rules():
    css = shell.render_head()
    # グリッドの列は minmax(0,1fr) で縮められる（長い商品名で横にはみ出さない）
    assert "repeat(2,minmax(0,1fr))" in _css_rule(css, ".nu-cats")
    assert "minmax(0,1fr)" in _css_rule(css, ".nu-purposes") and "minmax(0,1fr)" in _css_rule(css, ".nu-list")
    # ジャンルの切り替えは、その要素の中だけで横スクロールする（ページは横にはみ出さない）
    assert "overflow-x:auto" in _css_rule(css, ".nu-chips")
    # 旧UIの .tab-wrap のような負のマージンを使わない
    assert not re.search(r"margin[a-z-]*:(?:[^;}]*\s)?-\d", css)
    assert "overflow-wrap:anywhere" in _css_rule(css, ".nu-card__title")
    assert "min-width:0" in _css_rule(css, ".nu-card")
    # 表は2つだけ: 開発用の照合表（横スクロールの枠の中）と、利益商品の比較テーブル（1200px 以上だけ。
    # それ未満はカードに切り替え、テーブルを横スクロールさせない）
    root = shell.render_root(_ctx())
    tables = root.count("<table")
    assert tables == 2 and 'class="nu-debug__scroll"' in root and 'class="nu-otable"' in root
    assert "display:none" in _css_rule(css, ".nu-otable-wrap")
    assert f"@media (min-width:{t.BP_OPP_TABLE}px){{.nu-otable-wrap{{display:block}}.nu-ocards{{display:none}}}}" in css


# ── デザイントークン・状態 ──────────────────────────────────────────

def test_design_tokens_limited():
    assert sorted(t.FONT_SIZES.values()) == [12, 14, 16, 20, 24, 32]
    assert sorted(t.SPACING.values()) == [4, 8, 12, 16, 24, 32, 48]
    assert sorted(t.RADIUS.values()) == [8, 12, 16]
    css = shell.render_head()
    for name in ("--color-bg", "--color-surface", "--color-text", "--color-muted",
                 "--color-primary", "--color-success", "--color-warning", "--color-danger",
                 "--space-1", "--radius-md", "--shadow"):
        assert name + ":" in css
    # 直書きの色はトークンの値だけ
    colors = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{6}\b", css)}
    assert colors <= t.all_colors()
    # 文字サイズは px 直書きせず変数を使う
    assert not re.search(r"font-size:\d", css.replace("font-size:var", ""))


def test_status_registry_valid():
    assert st.validate() == []
    for key in ("OPEN", "ENDING_SOON", "UPCOMING", "AVAILABLE", "BUY", "WAIT", "ALERT",
                "BLOCKED", "ENDED", "UNKNOWN", "RESULT_PENDING", "WINNER_PURCHASE_PERIOD",
                "SOURCE_CONFLICT"):
        s = st.STATUSES[key]
        assert s.label and s.icon and s.tone in t.TONES and isinstance(s.priority, int)
    assert st.STATUSES["SOURCE_CONFLICT"].label == "日程要確認"
    assert st.lottery_status({"status": "OPEN", "conflict": True}).key == "SOURCE_CONFLICT"
    assert st.lottery_status({"status": "WHATEVER"}).key == "UNKNOWN"


def test_action_labels():
    assert [st.action_label(a) for a in ("APPLY", "BUY", "WAIT", "SKIP")] == [
        "応募する", "買う", "待つ", "見送る"]


def test_status_colors_by_meaning():
    assert st.STATUSES["ENDING_SOON"].tone == "danger"
    assert st.STATUSES["UPCOMING"].tone == "warning"
    assert st.STATUSES["OPEN"].tone == "success"
    assert st.STATUSES["ENDED"].tone == "neutral"
    # 「これから始まる」と「終わった」が同じ色にならない
    assert st.STATUSES["UPCOMING"].tone != st.STATUSES["ENDED"].tone


# ── カード・空状態 ─────────────────────────────────────────────────

def test_card_density_and_single_cta():
    card = c.Card(title="商品", subtitle="店", status="OPEN", primary_metric="¥1,000",
                  secondary_metric="10/3 締切", cta_label="応募", cta_href="https://example.com",
                  details=[("情報源", "公式"), ("確かさ", "高")])
    assert card.primary_field_count() <= c.Card.MAX_PRIMARY_FIELDS
    html = card.render()
    assert html.count("nu-btn--primary") == 1
    assert "<details" in html and "情報源" in html


def test_empty_states_distinguish_no_data_and_no_active():
    html = _page(_root(tcg_report={}, opportunities={}, profit_routes={}), "lottery")
    assert 'data-empty="NO_DATA"' in html and "まだ情報がありません" in html
    html = _page(_root(tcg_report=_report(lotteries=[_lot("CLOSED")])), "lottery")
    assert 'data-empty="NO_ACTIVE"' in html
    assert "新しい抽選の情報" in html


def test_internal_failure_counts_not_shown():
    html = shell.render_root(_ctx(source_issue=True))
    assert "一部の情報源を取得できていません" in html
    assert "取得失敗" not in html and "EBAY_APP_ID" not in html


# ── HOME の集計 ───────────────────────────────────────────────────

def test_home_counts_from_runtime_state():
    report = _report(
        lotteries=[
            _lot("OPEN", application_start=_iso(-timedelta(days=1)),
                 application_end=_iso(timedelta(days=3))),
            _lot("ENDING_SOON", application_start=_iso(-timedelta(days=1)),
                 application_end=_iso(timedelta(hours=5))),
            _lot("UPCOMING", application_start=_iso(timedelta(hours=3)),
                 application_end=_iso(timedelta(days=2))),
            _lot("UPCOMING", application_start=_iso(timedelta(days=4)),
                 application_end=_iso(timedelta(days=6))),
            _lot("OPEN", conflict=True, application_start=_iso(-timedelta(days=1)),
                 application_end=_iso(timedelta(days=1))),            # 日程要確認は数えない
            _lot("OPEN", announcement_only=True),                     # 日程不明の告知は数えない
            _lot("ENDED"),
        ],
        events=[
            {"status": "AVAILABLE_NOW", "stale": False},
            {"status": "AVAILABLE_NOW", "stale": True},   # 鮮度切れは数えない
            {"status": "COMING_SOON", "premium": {"premium_percent": 35.0}},
            {"status": "ENDED", "premium": {"premium_percent": 50.0}},
        ])
    routes = {"summary": {"main_route_count": 1},
              "main_routes": [{"buy_price": 100000, "sell_price": 120000, "net_profit": 12000,
                               "roi": 0.12, "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_CURRENT", "sell_canonical_type": "BUYBACK_CASH"}]}
    legacy = [{"product_name": "カメラ", "brand": "RICOH",
               "entry_start_at": (NOW - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
               "entry_end_at": (NOW + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")}]
    m = _model(tcg_report=report, profit_routes=routes, legacy_lotteries=legacy,
               opportunities={"todays_opportunities": [_opp("BUY"), _opp("WAIT", "reference")]})
    assert m.counts == {"lottery_open": 3, "ending_today": 2, "starting_24h": 1,
                        "available_now": 1, "high_profit": 1, "high_premium": 1}


def test_date_only_deadline_never_gets_invented_time():
    lot = _lot("OPEN", application_start=_iso(-timedelta(days=2)), application_end=None,
               application_end_date="2026-10-02")
    m = _model(tcg_report=_report(lotteries=[lot]))
    kind, status, vm = _shown(m)[0]
    stt = m.states[vm["id"]]
    assert status == "ENDING_SOON"            # 締切日当日（時刻未公表）は締切間近
    assert "時刻未公表" in stt["when"]
    assert "00:00" not in stt["when"] and "23:59" not in stt["when"] and stt["cd_text"] == ""
    # 締切日当日は締切前と言い切れないので「応募する」を出さない
    assert stt["cta"]["kind"] == "info"
    assert m.counts["ending_today"] == 1


def test_top_actions_order_and_labels():
    report = _report(lotteries=[
        _lot("UPCOMING", application_start=_iso(timedelta(hours=3)),
             application_end=_iso(timedelta(days=2))),
        _lot("OPEN", application_start=_iso(-timedelta(days=1)),
             application_end=_iso(timedelta(days=3))),
        _lot("ENDING_SOON", application_start=_iso(-timedelta(days=1)),
             application_end=_iso(timedelta(hours=2))),
    ])
    opps = {"todays_opportunities": [_opp("WAIT", "reference"), _opp("BUY"), _opp("SKIP"),
                                     _opp("SKIP")]}
    m = _model(tcg_report=report, opportunities=opps)
    assert [x[1] for x in _shown(m)] == ["ENDING_SOON", "OPEN", "BUY", "UPCOMING", "WAIT"]
    assert len(m.actions) <= home.TOP_ACTIONS_LIMIT
    # 抽選・予約のページは同じ並び（締切間近 → 受付中 → まもなく開始）
    html = _page(_root(tcg_report=report, opportunities=opps), "lottery")
    order = [html.index(f'data-nu-status="{k}"') for k in ("ENDING_SOON", "OPEN", "UPCOMING")]
    assert order == sorted(order) and "応募する" in html


def test_upcoming_lottery_not_shown_as_apply():
    lot = _lot("UPCOMING", application_start=_iso(timedelta(hours=3)),
               application_end=_iso(timedelta(days=2)))
    m = _model(tcg_report=_report(lotteries=[lot]))
    stt = m.states[m.vms[0]["id"]]
    assert stt["status"] == "UPCOMING" and stt["cta"]["kind"] == "info"
    assert "応募する" not in _page(_root(tcg_report=_report(lotteries=[lot])), "lottery")


def test_manual_unconfirmed_lottery_labeled():
    lot = _lot("UPCOMING", collection_method="MANUAL_VERIFIED", verified=False,
               confidence="medium", application_start=_iso(timedelta(hours=3)),
               application_end=_iso(timedelta(days=2)))
    html = _page(_root(tcg_report=_report(lotteries=[lot])), "lottery")
    assert "確認待ち" in html and "公式確認済み" not in html
    assert "medium" not in html.split("<details", 1)[0]


# ── 価格のガード（表示だけ） ───────────────────────────────────────

def _buy_cards(m):
    return [x for x in _shown(m) if x[1] == "BUY"]


@pytest.mark.parametrize("override", [
    {"buy_price": 0}, {"sell_price": 0}, {"net_profit": 0}, {"buy_price": None},
    {"roi": "NaN"}, {"roi": float("inf")}, {"roi": -0.1}, {"roi": 0},
])
def test_invalid_price_or_roi_not_shown_as_opportunity(override):
    m = _model(opportunities={"todays_opportunities": [_opp("BUY", **override)]})
    assert not _buy_cards(m)
    assert m.hidden_prices == 1
    html = _root(opportunities={"todays_opportunities": [_opp("BUY", **override)]})
    assert not re.search(r"¥0(?![0-9,])", html)
    assert not re.search(r"(?i)(nan|inf|infinity)\s*%", html)


def test_suspicious_extreme_price_not_recommended():
    # 異常値（+1697% や 定価比 +780% の ¥900,000 のような値）は「おすすめ」に出さない
    extreme = _opp("BUY", buy_price=49980, sell_price=900000, net_profit=848220, roi=16.97)
    m = _model(opportunities={"todays_opportunities": [extreme]})
    assert not _buy_cards(m)
    route = {"buy_price": 49980, "sell_price": 900000, "net_profit": 848220, "roi": 16.97,
             "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_CURRENT", "sell_canonical_type": "BUYBACK_CASH"}
    m = _model(profit_routes={"main_routes": [route], "summary": {"main_route_count": 1}})
    assert m.counts["high_profit"] == 0
    html = _root(opportunities={"todays_opportunities": [extreme]},
                 profit_routes={"main_routes": [route], "summary": {"main_route_count": 1}})
    assert "848,220" not in html and "1697" not in html
    low = {"buy_price": 1000, "sell_price": 2000, "net_profit": 500, "roi": 0.5,
           "route_confidence": "low", "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_CURRENT", "sell_canonical_type": "BUYBACK_CASH"}
    m = _model(profit_routes={"main_routes": [low]})
    assert m.counts["high_profit"] == 0


@pytest.mark.parametrize("premium, counted", [
    ({"premium_percent": 35.0}, True),
    ({"premium_percent": -20.0}, False),
    ({"premium_percent": 900.0}, False),
    ({"premium_percent": 40.0, "insufficient_samples": True}, False),
    ({"premium_percent": "NaN"}, False),
])
def test_premium_guard(premium, counted):
    m = _model(tcg_report=_report(events=[{"status": "COMING_SOON", "premium": premium}]))
    assert m.counts["high_premium"] == (1 if counted else 0)


@pytest.mark.parametrize("override", [
    {"kind": "reference"}, {"confidence": "low"}, {"rejection_reason": "stale"},
])
def test_reference_or_flagged_not_recommended(override):
    m = _model(opportunities={"todays_opportunities": [_opp("BUY", **override)]})
    assert not _buy_cards(m)


def test_wait_reference_hides_amount_and_internal_terms():
    o = _opp("WAIT", "reference", net_profit=86651,
             action_reason="eBay sold 更新（EBAY_APP_ID 設定）後に BUY 候補へ昇格")
    html = _root(opportunities={"todays_opportunities": [o]})
    assert "86,651" not in html and "EBAY_APP_ID" not in html


def test_guard_does_not_change_source_values():
    o = _opp("BUY", buy_price=0)
    before = dict(o)
    _model(opportunities={"todays_opportunities": [o]})
    assert o == before


def test_lottery_price_guard():
    for value, expected in ((0, "価格確認中"), (-1, "価格確認中"), ("abc", "価格確認中"),
                            (None, ""), (5400, "¥5,400")):
        lot = _lot("OPEN", retail_price=value, application_start=_iso(-timedelta(days=1)),
                   application_end=_iso(timedelta(days=3)))
        m = _model(tcg_report=_report(lotteries=[lot]))
        assert m.vms[0]["price"] == expected


# ── 生成の失敗・壊れた入力で旧UIを止めない ─────────────────────────────

def _gen():
    from src.content.daily_lp_generator import DailyLPGenerator
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g.settings = {}
    g.repo = _FakeRepo()
    return g


def test_new_ui_failure_does_not_break_old_ui(monkeypatch):
    from src.content.ui import shell as ui_shell

    def boom(ctx):
        raise RuntimeError("x")
    monkeypatch.setattr(ui_shell, "render_root", boom)
    head, root = _gen()._new_ui_parts(lottery_items=[], lp_generated_at=None,
                                      collection_stats={}, site_title="x")
    assert (head, root) == ("", "")


@pytest.mark.parametrize("report", [
    {"source_health": "broken", "lottery_coverage": None, "lotteries": [None, 3, {"status": "OPEN"}]},
    [],
    {"lotteries": "x", "events": None},
])
def test_malformed_report_still_renders(monkeypatch, report):
    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setattr(DailyLPGenerator, "_load_tcg_report", staticmethod(lambda: report))
    head, root = _gen()._new_ui_parts(lottery_items=[], lp_generated_at=None,
                                      collection_stats={}, site_title="x")
    assert head and '<div id="new-ui-root"' in root


@pytest.mark.parametrize("content", ["{broken", "[1, 2]", '"text"', ""])
def test_load_export_json_broken(tmp_path, monkeypatch, content):
    from src.content import daily_lp_generator as mod
    exports = tmp_path / "exports" / "x"
    exports.mkdir(parents=True)
    (exports / "latest.json").write_text(content, encoding="utf-8")
    monkeypatch.setattr(mod, "__file__", str(tmp_path / "src" / "content" / "daily_lp_generator.py"))
    assert mod.DailyLPGenerator._load_export_json("x", "latest.json") == {}
