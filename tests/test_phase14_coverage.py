"""Phase 14（国内の定価・在庫・買取・TCG の網羅）のテスト。

公式ページで確かめた定価・在庫だけを確認済みにし、参考・販売終了・条件付き・中古・照合されていない値を
確定に使わないことを確かめる。各テストには、誤りを入れると失敗する否定対照も付ける。データはテスト用。
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 8, 3, 0, tzinfo=JST)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


AUDIT = _load("p14_audit_official", ROOT / "scripts" / "audit_official_sources.py")


# ── 定価（確認済み・販売終了・参考） ────────────────────────────────────────────

def test_retail_verified_has_official_item_page_price_and_date():
    """確認済みの定価は、公式の商品ページ・価格・確認日（実行日ではない）がそろう。"""
    from src.market import price_evidence as pe
    v = AUDIT.VERIFIED_URLS["prod_switch2"]
    assert v["url"].startswith("https://store-jp.nintendo.com/item/") and v["link_type"] == "item"
    assert v["price"] == 59980 and v["checked_on"] == "2026-10-08" and v["conf"] == "high"
    p = SimpleNamespace(id="prod_switch2", retail_price=59980, official_price=59980,
                        official_price_updated_at=datetime(2026, 10, 8, tzinfo=JST))
    assert pe.is_profit_eligible(pe.classify_product_msrp(p, NOW))
    # 否定対照: 確認日の無い設定値の定価は確認済みにしない
    ref = SimpleNamespace(id="prod_switch2", retail_price=59980, official_price=None, official_price_updated_at=None)
    assert not pe.is_profit_eligible(pe.classify_product_msrp(ref, NOW))


def test_retail_sale_ended_is_reference_only():
    """公式で販売していない商品は、定価を確認済みにしない（参考のまま）。"""
    for pid in ("prod_ps5_de", "prod_gr3"):
        u = AUDIT.OFFICIAL_NOT_SOLD[pid]
        assert u["checked_on"] == "2026-10-08" and u["reason"]
        assert pid not in AUDIT.VERIFIED_URLS
    calls = []

    class _Conn:
        def execute(self, sql, params=()):
            calls.append((sql, params))
            return SimpleNamespace(fetchone=lambda: None)

        def commit(self):
            pass
    AUDIT.register_verified(_Conn(), {"prod_gr3": {"name": "RICOH GR III", "model_number": ""},
                                      "prod_ps5_de": {"name": "PlayStation 5 Digital Edition", "model_number": ""}})
    cleared = [p for sql, p in calls if "official_price=NULL" in sql]
    assert ("prod_gr3",) in cleared and ("prod_ps5_de",) in cleared      # 以前の確認済み定価を外す（参考に戻す）
    assert not [p for sql, p in calls if "SET official_price=?" in sql and p[-1] in ("prod_gr3", "prod_ps5_de")]


def test_sale_ended_sources_are_read_as_official_meta():
    """販売終了の記録の取得元は、公式の取得元として読まれるものにする（読まれないと sale_ended に数えられない）。"""
    from src.market.official_price_validator import OFFICIAL_DOMAINS
    readable = set(OFFICIAL_DOMAINS) | {"src_nintendo_store"}
    for pid, u in AUDIT.OFFICIAL_NOT_SOLD.items():
        assert u["source"] in readable, pid


def test_diagnostics_counts_sale_ended_separately():
    from src.content.ui.admin import build_data_coverage
    cov = build_data_coverage({"retail_prices": {"summary": {"verified": 7, "reference": 38, "sale_ended": 21}},
                               "stock": {"states": {"IN_STOCK": 1, "UNKNOWN": 40}},
                               "buyback": {"usable_products": 26, "fresh_rows": 67}},
                              {"lotteries": [{"event_type": "LOTTERY"}, {"event_type": "PREORDER"},
                                             {"event_type": "PURCHASE_RIGHT"}, {}],
                               "events": [{"event_type": "FIRST_COME"}, {"event_type": "RESTOCK"},
                                          {"event_type": "ONLINE_RESTOCK"}, {"event_type": "RESERVATION_REOPEN"},
                                          {"event_type": "AVAILABLE_NOW"}, {"event_type": "GENERAL_SALE"}]})
    assert cov["retail"] == {"verified": 7, "reference": 38, "sale_ended": 21, "stale": 0, "unknown": 0}
    assert cov["stock"]["IN_STOCK"] == 1 and cov["buyback"]["usable_products"] == 26
    # 予約を抽選と二重に数えない（抽選は LOTTERY・PURCHASE_RIGHT・種類の無い抽選情報）。予約の再開は予約、
    # 再販は明示の再入荷（店頭・EC）だけ。AVAILABLE_NOW（状態）・一般販売は数えない
    assert cov["tcg"] == {"lotteries": 3, "preorder": 2, "first_come": 1, "restock": 2}
    # 壊れた形の報告でも落ちない
    assert build_data_coverage({"retail_prices": "x", "stock": [1]}, {"events": "x", "lotteries": None})["tcg"] == \
        {"lotteries": 0, "preorder": 0, "first_come": 0, "restock": 0}


# ── 在庫（明示の証拠・不明・有効期限） ──────────────────────────────────────

@pytest.mark.parametrize("text,state", [
    ("在庫あり", "IN_STOCK"),
    ("カートに入れる（お届け予定日：通常2～6日後）", "IN_STOCK"),        # 購入できることの明示
    ("カートに入れる 入荷待ち", "OUT_OF_STOCK"),                          # 入荷待ちが並べば在庫切れ
    ("入荷待ち", "OUT_OF_STOCK"),
    ("", "UNKNOWN"), ("発売中", "UNKNOWN"), ("予約受付中", "UNKNOWN"),     # 発売・予約だけでは在庫ありにしない
    ("137,980円(税込)", "UNKNOWN"),                                     # 価格の表示だけでは在庫ありにしない
    ("予約受付中 カートに入れる", "UNKNOWN"),                            # 予約・抽選・発売予定・否定は在庫ありにしない
    ("抽選販売 カートに入れる", "UNKNOWN"),
    ("発売予定 カートに入れる", "UNKNOWN"),
    ("現在カートに入れることはできません", "UNKNOWN"),
    ("メーカー取り寄せ カートに入れる", "UNKNOWN"), ("入荷次第発送 カートに入れる", "UNKNOWN"),
    ("近日発売 カートに入れる", "UNKNOWN"), ("Coming soon カートに入れる", "UNKNOWN"),
    ("在庫あり 予約特典つき", "IN_STOCK"),                               # 「在庫あり」の明示はそのまま
])
def test_stock_needs_explicit_evidence(text, state):
    from src.market.stock_state import stock_state
    assert stock_state(text) == state


def test_switch2_stock_evidence_is_recorded_with_time():
    from src.market.stock_state import stock_state
    v = AUDIT.VERIFIED_URLS["prod_switch2"]
    assert stock_state(v["stock"]) == "IN_STOCK" and v["stock_checked_at"] == "2026-10-08T02:32:13+09:00"
    ps5 = AUDIT.VERIFIED_URLS["prod_ps5_pro"]
    assert stock_state(ps5["stock"]) == "OUT_OF_STOCK" and ps5["stock_checked_at"].startswith("2026-10-08T02:34")
    # 在庫の表示を確認していない商品には在庫を記録しない（AirPods Pro 3 は価格だけ）
    assert "stock" not in AUDIT.VERIFIED_URLS["prod_airpods_pro3"]


def test_stock_ttl_is_not_extended():
    """在庫ありは確認から7日以内だけ。8日前の確認は在庫未確認に戻る（期限を延ばさない）。"""
    from src.content.ui import opportunity as opp
    from src.market import price_evidence as pe
    assert pe.CURRENT_DAYS == 7
    v = SimpleNamespace(buy_stock="IN_STOCK", stock_checked_at=(NOW - timedelta(days=2)).isoformat(),
                        status="IN_STOCK", priority=(0, 1))
    opp._apply_stock_freshness(v, NOW)
    assert v.buy_stock == "IN_STOCK"
    old = SimpleNamespace(buy_stock="IN_STOCK", stock_checked_at=(NOW - timedelta(days=8)).isoformat(),
                          status="IN_STOCK", priority=(0, 1))
    opp._apply_stock_freshness(old, NOW)
    assert old.buy_stock == "UNKNOWN"


# ── 買取（商品ページ・店のトップ・条件付き・中古） ────────────────────────────────

def _sell(link_type="item", url="https://www.kaitorishouten-co.jp/products/detail/25543", **kw):
    from src.market.normalized_prices import _extraction_method, make_observation
    o = make_observation(NOW, product_id="prod_ps5_pro", product_name="PlayStation 5 Pro",
                         source_id="src_kaitori_shouten", source_name="買取商店", market_type="buyback",
                         price_role="sell", price_type="buyback_price", condition=kw.pop("condition", "new_unopened"),
                         price=195200, observed_at=(NOW - timedelta(hours=3)).isoformat(), confidence="high",
                         source_url=url, item_url=url if link_type == "item" else "", link_type=link_type,
                         extraction_method=_extraction_method("auto_scraped"),
                         price_context="プレイステーション5 Pro [CFI-7100B01] 2025版")
    o.update(kw)
    return o


def test_buyback_item_page_is_confirmed_and_shop_home_is_not():
    from src.market.normalized_prices import sell_confirmation_reasons
    assert not sell_confirmation_reasons(_sell())
    # 否定対照（買取の mutation）: 商品ページ → 店のトップにすると確定の売値から外れる
    assert sell_confirmation_reasons(_sell(link_type="shop_home", url="https://www.kaitorishouten-co.jp/"))


def test_used_buyback_is_not_new_product_profit():
    """中古（新品同様を含む）の買取価格は、新品の仕入れの利益に使わない（状態の mutation）。"""
    from src.content.ui.opportunity import _cond_family
    assert _cond_family("new_unopened") == "new"
    for used in ("used_s", "used_a", "used"):
        assert _cond_family(used) == "used" != _cond_family("new_unopened")


def test_conditional_netoff_price_is_not_taken():
    """ネットオフの「未開封品 ○円買取」はクーポン・自宅集荷・箱の条件付き価格なので取らない（無条件の売値にしない）。"""
    from src.collectors.buyback_netoff import _extract_price_from_block
    conditional = "iPhone 17 Pro 1TB 256GB 未開封品 159,600 円買取 512GB 未開封品 190,000 円買取 iPhone Air"
    assert _extract_price_from_block(conditional, "iPhone 17 Pro 1TB", 256) is None
    # 否定対照: 条件の無い「上限」の表記だけ取る
    plain = "iPhone 17 Pro 1TB 256GB 上限 152,000 円買取 iPhone Air"
    assert _extract_price_from_block(plain, "iPhone 17 Pro 1TB", 256) == 152000


# ── TCG（予約・先着・再販・抽選を混ぜない／手動の確認） ─────────────────────────────

@pytest.mark.parametrize("text,kind", [
    ("抽選販売のお知らせ", "LOTTERY"),
    ("予約受付を開始します", "PREORDER"),          # 予約は抽選・在庫・再販と別
    ("先着順で販売します", "FIRST_COME"),           # 先着は抽選と別
    ("再入荷しました", "RESTOCK"),                  # 明示の再入荷だけ
    ("11月21日発売予定", None),                     # 発売予定は再販にしない（推測しない）
    ("発売日のお知らせ", "GENERAL_SALE"),
])
def test_tcg_event_semantics(text, kind):
    from src.tcg.classify import classify_event_type
    assert classify_event_type(text) == kind


def test_preorder_is_not_lottery_and_restock_is_not_release():
    from src.tcg.classify import classify_event_type
    from src.tcg.lottery.schema import LT_LOTTERY, LT_PREORDER
    assert LT_PREORDER != LT_LOTTERY and classify_event_type("予約受付") != "LOTTERY"     # PREORDER mutation
    assert classify_event_type("発売予定のお知らせ") not in ("RESTOCK", "ONLINE_RESTOCK")


def test_manual_verified_event_needs_human_confirmation():
    """アクセスを拒否される公式の取得元（PCO など）は、人が確認した記録だけ公式扱いにする。"""
    from src.tcg.lottery import manual
    row = {"tcg": "POKEMON", "product": "テストBOX", "retailer": "POKEMON_CENTER_ONLINE",
           "source_url": "https://www.pokemoncenter-online.com/news/?id=1", "verified_at": "2026-10-08T03:00:00+09:00",
           "verified_by": "tester", "event_type": "LOTTERY", "application_start": "2026-10-08T10:00:00+09:00",
           "application_end": "2026-10-10T23:59:00+09:00"}
    ai_only, err = manual._row_to_event(dict(row, human_confirmed="false"))
    human, err2 = manual._row_to_event(dict(row, human_confirmed="true"))
    assert not err and not err2
    assert ai_only["source_type"] != human["source_type"]               # AI の転記だけなら公式扱いにしない
    assert ai_only["last_verified_at"] == human["last_verified_at"] == row["verified_at"]   # 確認日は記録のまま


# ── 検索 ───────────────────────────────────────────────────────────────

def _search_rows(details) -> dict:
    """商品ID → 検索の対象の文字列（data-search）。"""
    import re

    from src.content.ui import pages
    html = pages.render_search(details)
    return {pid: s for s, pid in re.findall(r'data-search="([^"]*)".*?product_id=(prod_\w+)', html)}


def _details(with_keywords=True):
    from src.content.ui import product_detail as pd
    kw = (lambda *k: k) if with_keywords else (lambda *k: ())
    return {
        "prod_ps5_pro": pd.ProductDetailView(product_id="prod_ps5_pro", category="game", product_name="PlayStation 5 Pro",
                                             model="CFI-7000A01", keywords=kw("PS5 Pro", "PS5Pro", "CFI-7000")),
        "prod_xbox_sx": pd.ProductDetailView(product_id="prod_xbox_sx", category="game", product_name="Xbox Series X",
                                             keywords=kw("Xbox Series X", "XSX")),
        "prod_switch2": pd.ProductDetailView(product_id="prod_switch2", category="game", product_name="Nintendo Switch 2",
                                             keywords=kw("Switch 2", "SW2", "スイッチ2")),
        "prod_gr4": pd.ProductDetailView(product_id="prod_gr4", category="camera", product_name="RICOH GR IV",
                                         keywords=kw("GR IV", "GR4")),
        "prod_iphone17_256": pd.ProductDetailView(product_id="prod_iphone17_256", category="smartphone",
                                                  product_name="iPhone 17 256GB SIMフリー", keywords=kw("iPhone 17")),
    }


@pytest.mark.parametrize("term,pid", [
    ("ps5", "prod_ps5_pro"), ("xsx", "prod_xbox_sx"), ("sw2", "prod_switch2"), ("スイッチ2", "prod_switch2"),
    ("gr4", "prod_gr4"),
])
def test_search_finds_by_registered_keyword_only(term, pid):
    """キーワードにしか無い語（商品名・型番には無い）で見つかる。キーワードを外すと見つからない（否定対照）。"""
    assert term in _search_rows(_details())[pid]
    assert term not in _search_rows(_details(with_keywords=False))[pid]


@pytest.mark.parametrize("term,pid", [
    ("playstation", "prod_ps5_pro"), ("cfi-7000", "prod_ps5_pro"), ("gr iv", "prod_gr4"),
    ("iphone 17", "prod_iphone17_256"),
])
def test_search_still_finds_by_name_and_model(term, pid):
    assert term in _search_rows(_details(with_keywords=False))[pid]


def test_keywords_escaped_in_search_html():
    from src.content.ui import pages
    from src.content.ui import product_detail as pd
    html = pages.render_search({"p": pd.ProductDetailView(product_id="p", category="game", product_name="X",
                                                          keywords=('"><script>x</script>',))})
    assert "<script>x</script>" not in html


def test_keywords_flow_from_products_to_search():
    """商品の一覧（keywords つき）から商品詳細を組み立てると、検索の行にキーワードが入る。"""
    from src.content.ui import pages
    from src.content.ui import product_detail as pd
    views = pd.build(products=[{"product_id": "prod_ps5_pro", "name": "PlayStation 5 Pro", "genre": "game_console",
                                "model": "CFI-7000A01", "keywords": ["PS5 Pro", "PS5Pro"]}],
                     catalog=None, observations=[], price_history={}, stock_history={}, now=NOW)
    assert views["prod_ps5_pro"].keywords == ("PS5 Pro", "PS5Pro")
    assert "ps5pro" in pages.render_search(views)


# ── ファネル・今すぐ行動できる商品 ─────────────────────────────────────────

def _diag(eligible):
    from src.market import opportunity_diagnostics as od
    s = SimpleNamespace(eligible=eligible, ineligible=[])
    return od.build(products=[], msrp_evidence={}, official_meta={}, observations=[], opportunity_set=s,
                    home_count=len(eligible), list_count=len(eligible), sold_exports=None, now=NOW)


def _view(pid, availability):
    return SimpleNamespace(product_id=pid, kind="official_to_buyback", eligible=True, reasons=(),
                           category="game", availability=availability)


def test_actionable_needs_stock_or_reservation_not_profit_alone():
    """掲載できる利益があっても、在庫ありの明示か予約の根拠が無ければ「今すぐ行動できる」に数えない。"""
    d = _diag([_view("a", "BUY_NOW"), _view("b", "PROFIT_STOCK_UNKNOWN"), _view("c", "OUT_OF_STOCK"),
               _view("d", "LOTTERY"), _view("e", "RESERVATION"), _view("a", "BUY_NOW")])
    assert d["actionable"]["count"] == 2                                 # a（重複は1）・e だけ
    assert {p["product_id"] for p in d["actionable"]["products"]} == {"a", "e"}
    # 否定対照（在庫の mutation）: 在庫ありが在庫未確認に戻ると数えない
    assert _diag([_view("a", "PROFIT_STOCK_UNKNOWN")])["actionable"]["count"] == 0


def test_metrics_report_actionable_without_changing_funnel():
    m = _load("p14_pcm", ROOT / "scripts" / "production_coverage_metrics.py")
    stages = [s for s, _ in m.FUNNEL]
    assert stages[-1] == "actionable" and "actionable_products" not in stages   # ファネルの定義は Phase 11 のまま
    import inspect
    assert '"actionable_products": int((diag.get("actionable") or {}).get("count") or 0)' in inspect.getsource(m)


# ── 量（画面が崩れない） ──────────────────────────────────────────────────

P6 = _load("p14_ui_phase6", ROOT / "tests" / "test_ui_phase6.py")


def _visible(root: str) -> str:
    """表示の部分（script を除く）。JS の isNaN などを誤って拾わない。"""
    import re
    return re.sub(r"<script\b.*?</script>", "", root, flags=re.S)
P4 = _load("p14_ui_phase4", ROOT / "tests" / "test_ui_phase4.py")


@pytest.mark.parametrize("n", [0, 1, 10, 50])
def test_restock_page_scales(n):
    from src.content.ui import shell
    from src.market import stock_state as ss
    h = P4.hist([P4.ob(f"k{i}", ss.IN_STOCK, P4._t(minutes=-5 - i)) for i in range(n)]) if n else P4.hist()
    root = shell.render_root(P4._P1._ctx(stock_history=h))
    sec = _visible(P4._section(root, "restock"))
    assert sum(1 for i in range(n) if f"商品k{i}<" in sec or f"商品k{i} " in sec or f"商品k{i}\"" in sec) == n
    assert "NaN" not in sec and "undefined" not in sec


@pytest.mark.parametrize("n", [1, 10, 50])
def test_profit_page_scales(n):
    from src.content.ui import shell
    deals = [dict(P6.DEAL, product_id=f"prod_t{i}", title=f"テスト商品{i}") for i in range(n)]
    root = shell.render_root(P6._ctx(profit_deals=deals, products=P6.PRODUCTS +
                                     [{"product_id": f"prod_t{i}", "name": f"テスト商品{i}", "genre": "camera"}
                                      for i in range(n)]))
    vis = _visible(root)
    assert 'data-nu-page="opportunities"' in vis and "NaN" not in vis and "undefined" not in vis
    from src.content.ui import product_detail as pd
    assert len(pd.build(products=[{"product_id": f"prod_t{i}", "name": f"テスト商品{i}", "genre": "camera"}
                                  for i in range(n)], catalog=None, observations=[], price_history={},
                        stock_history={}, now=P6.NOW)) == n          # 商品の数だけ商品詳細を作る


@pytest.mark.parametrize("n", [0, 20, 100])
def test_lottery_page_scales(n):
    from src.content.ui import shell
    lots = [{"tcg": "POKEMON", "product_name": f"テストBOX{i}", "retailer_name": "公式ストア", "status": "OPEN",
             "event_type": "LOTTERY", "source_url": f"https://www.pokemoncenter-online.com/news/{i}",
             "entry_url": f"https://www.pokemoncenter-online.com/lottery/{i}", "retail_price": 5400,
             "verified": True, "confidence": "high",
             "application_start": (P6.NOW - timedelta(days=1)).isoformat(),
             "application_end": (P6.NOW + timedelta(days=2)).isoformat()} for i in range(n)]
    report = {"lotteries": lots, "events": [], "source_health": [], "lottery_coverage": {}}
    root = shell.render_root(P6._ctx(tcg_report=report))
    vis = _visible(root)
    assert 'data-nu-page="lottery"' in vis and "NaN" not in vis and "undefined" not in vis
    assert vis.count("テストBOX") >= n                                  # 件数が増えても全部描画する


def test_product_detail_with_many_sources_stock_and_preorder():
    """複数の仕入れ先・売り先・在庫あり・予約があっても商品詳細が崩れず、照合されていない値を確定にしない。"""
    from src.content.ui import shell
    root = shell.render_root(P6._ctx())
    art = P6._article(root, "prod_tcam")
    assert "買取店A" in art and "NaN" not in art
    # 店のトップ（照合未了）・種別不明の高い値を、利益の計算に使った売却先にしない
    assert "利益の計算に使った売却価格" in art
    used = art.split("利益の計算に使った売却価格", 1)[1][:300]
    assert "232,000" in used and "299,000" not in used and "399,000" not in used


def test_switch2_shipping_is_same_for_judgment_and_display():
    """利益の判定（公式 URL を引けない経路）と商品詳細（公式 URL あり）で、Switch 2 の購入送料が同じになる。"""
    from src.market.official_shipping import purchase_shipping
    judged = purchase_shipping("prod_switch2", "", 59980)
    shown = purchase_shipping("prod_switch2", AUDIT.VERIFIED_URLS["prod_switch2"]["url"], 59980)
    assert judged["fee"] == shown["fee"] == 0 and judged["status"] == "CONDITIONAL"
    # 否定対照: 記録の無い商品は、公式 URL が無ければ送料不明のまま（0円とみなさない）
    assert purchase_shipping("prod_unknown_x", "", 59980)["fee"] is None


def test_expired_manual_stock_is_not_written():
    """確認から7日を過ぎた手の在庫の記録は DB に書かない（期限を見ない古い判定に残さない）。"""
    now = datetime(2026, 10, 8, 3, 0, tzinfo=JST)
    assert AUDIT._stock_record_is_current("2026-10-08T02:32:13+09:00", now) is True
    assert AUDIT._stock_record_is_current("2026-10-15T02:00:00+09:00", now + timedelta(days=7)) is True
    assert AUDIT._stock_record_is_current("2026-10-08T02:32:13+09:00", now + timedelta(days=8)) is False
    assert AUDIT._stock_record_is_current("not-a-date", now) is False
    calls = []

    class _Conn:
        def execute(self, sql, params=()):
            calls.append((sql, params))
            return SimpleNamespace(fetchone=lambda: None)

        def commit(self):
            pass
    import importlib
    orig = AUDIT.NOW
    try:
        AUDIT.NOW = now + timedelta(days=9)                               # 9日後の CI
        AUDIT.register_verified(_Conn(), {"prod_switch2": {"name": "Nintendo Switch 2", "model_number": ""}})
    finally:
        AUDIT.NOW = orig
    assert not [p for sql, p in calls if "official_stock_observed_at" in sql]
    importlib.invalidate_caches()
