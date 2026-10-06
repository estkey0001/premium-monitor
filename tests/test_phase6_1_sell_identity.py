"""Phase 6.1: 商品の照合が済んでいない売却価格を、確定利益（案件・新UIの利益商品・商品詳細）に使わない。

（UI Phase 10 で旧UIのランキング・Hero・案件カード・買取店比較を削除した。同じ意図を新UIの利益商品・商品詳細と、
旧UIの買取店比較が使っていた正本（normalized_prices.confirmed_sell_keys）で確かめる。）

売却側の正本は src/market/normalized_prices.sell_confirmation_reasons（商品の同一性は正規化の観測の
is_exact_product_match。店のトップ・検索結果の価格は使わない）。データはすべて架空。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.content.ui import opportunity as opp
from src.market import normalized_prices as npx
from src.market import price_evidence as pe
from src.models.beginner_deal import BeginnerDealModel
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime.now(JST).replace(microsecond=0)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


RF = _load("route_fixtures_p61", ROOT / "tests" / "route_fixtures.py")


def sell_obs(src, price, *, exact=True, link="unknown", cond="new_unopened", fresh=True, canon="BUYBACK_CASH",
             pid="prod_ps5_pro", **kw):
    """正規化の観測（買取価格）1件。"""
    d = {"product_id": pid, "price_role": "sell", "price_type": "buyback_price", "canonical_price_type": canon,
         "source_name": src, "price": price, "is_exact_product_match": exact, "link_type": link,
         "condition": cond, "is_fresh": fresh, "rejection_reason": "", "accessory_flag": False,
         "wrong_model_flag": False, "is_usable_for_beginner": True,
         "observed_at": (NOW - timedelta(hours=1)).isoformat()}
    d.update(kw)
    return d


# 本番（2026-10-05）の PS5 Pro と同じ形: 高い方は店のトップの価格（照合未了）、低い方は型番で照合した一覧の行
MOBILE = sell_obs("モバイル一番", 192700, exact=False, link="shop_home")
SHOUTEN = sell_obs("買取商店", 192300, exact=True, link="unknown")


def _gen(keys):
    from src.content.daily_lp_generator import DailyLPGenerator
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g.settings = {}
    g._msrp_evidence = {"prod_ps5_pro": pe.VERIFIED_DATED}
    g._product_info = {}
    g._gate_now = NOW
    g._sell_keys_cache = keys
    return g


def _row(shop, price):
    return {"shop_name": shop, "buyback_price": price, "condition": "new_unopened", "confidence": "high",
            "observed_at": (NOW - timedelta(hours=1)).isoformat(), "data_source": "auto_scraped",
            "buyback_url": "https://example.jp/"}


def _ps5_deal(shop="モバイル一番", price=192700):
    net = price - 137980 - 1800 - 550
    return BeginnerDealModel(id="p", product_id="prod_ps5_pro", product_name="PlayStation 5 Pro",
                             category="game_console", official_price_jpy=137980, best_buyback_price=price,
                             best_buyback_shop=shop, net_profit_jpy=net, gross_profit_jpy=price - 137980,
                             net_profit_rate=net / 137980, buyback_condition="新品未開封",
                             user_level="beginner_easy", sale_method="normal", stock_status="在庫あり",
                             official_url="https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/")


# ── 正本の判定 ────────────────────────────────────────────────────────────

def test_verified_buyback_is_confirmed_and_unverified_is_not():
    assert npx.sell_confirmation_reasons(SHOUTEN) == []
    assert "sell_identity_unverified" in npx.sell_confirmation_reasons(MOBILE)
    assert "sell_url_not_item_level" in npx.sell_confirmation_reasons(MOBILE)


@pytest.mark.parametrize("mutate, reason", [
    (dict(is_exact_product_match=False), "sell_identity_unverified"),       # 照合済み → 未照合
    (dict(link_type="shop_home"), "sell_url_not_item_level"),                # 商品の行 → 店のトップ
    (dict(link_type="search"), "sell_url_not_item_level"),                   # 検索結果
    (dict(condition="used_a"), "condition_mismatch"),                        # 状態の違い
    (dict(condition=""), "condition_mismatch"),                              # 状態が分からない
    (dict(is_fresh=False), "stale_sell_price"),                              # 古い
    (dict(canonical_price_type="UNKNOWN"), "sell_type_not_buyback"),         # 種別不明
    (dict(canonical_price_type="LISTING"), "sell_type_not_buyback"),         # 出品
    (dict(accessory_flag=True), "sell_wrong_product"),                       # 付属品
    (dict(rejection_reason="duplicate_price_collision"), "sell_rejected_duplicate_price_collision"),
    (dict(price=0), "invalid_sell_price"),
])
def test_mutations_drop_out_of_confirmed(mutate, reason):
    o = dict(SHOUTEN, **mutate)
    assert reason in npx.sell_confirmation_reasons(o)
    assert npx.confirmed_sells([o], "prod_ps5_pro") == []
    assert ("prod_ps5_pro", "買取商店", int(o["price"])) not in npx.confirmed_sell_keys([o])


def test_highest_confirmed_not_highest_overall():
    """照合済み ¥190,000 と照合未了 ¥200,000 → ¥190,000 を使う（単純な最高値にしない）。"""
    obs = [sell_obs("店V", 190000), sell_obs("店U", 200000, exact=False, link="shop_home")]
    assert [o["source_name"] for o in npx.confirmed_sells(obs, "prod_ps5_pro")] == ["店V"]
    assert [o["source_name"] for o in npx.beginner_sell(obs, "prod_ps5_pro")] == ["店V"]   # ランキングの入口


def test_all_unverified_gives_no_confirmed_sell():
    obs = [MOBILE, sell_obs("店U2", 191000, exact=False, link="search")]
    assert npx.confirmed_sells(obs, "prod_ps5_pro") == [] and npx.confirmed_sell_keys(obs) == set()
    assert npx.beginner_sell(obs, "prod_ps5_pro") == []


# ── PS5 Pro（本番と同じ形） ───────────────────────────────────────────────────

def test_ps5_pro_uses_verified_shouten_not_mobile_ichiban():
    keys = npx.confirmed_sell_keys([MOBILE, SHOUTEN])
    g = _gen(keys)
    rows = [_row("モバイル一番", 192700), _row("買取商店", 192300)]
    deal = g._enrich_deal(_ps5_deal(), rows)
    assert deal.best_buyback_shop == "買取商店" and deal.best_buyback_price == 192300
    assert deal.net_profit_jpy == 192300 - 137980 - 1800 - 550 == 51970      # 生成側の既存の式
    d, = g._nu_profit_deals([deal], {"prod_ps5_pro": rows})
    assert d["sell_identity_verified"] is True
    s = opp.build(deals=[d], routes=[], product_genres={"prod_ps5_pro": "game_console"}, now=NOW)
    v, = s.eligible
    assert (v.sell_source, v.sell_price, v.net_profit) == ("買取商店", 192300, 51970)
    assert v.acquisition_cost == 137980 + 550 and v.breakdown_ok


def test_unverified_sell_is_never_confirmed_by_the_gate():
    """補完を通らずに未照合の売値が来ても、判定（eligibility）が確定にしない。"""
    g = _gen(npx.confirmed_sell_keys([MOBILE, SHOUTEN]))
    d, = g._nu_profit_deals([_ps5_deal()], {"prod_ps5_pro": [_row("モバイル一番", 192700)]})
    assert d["sell_identity_verified"] is False
    assert "sell_identity_unverified" in opp.deal_reasons(d, NOW)
    # 値が無い（古い生成物など）ときも未照合
    assert "sell_identity_unverified" in opp.deal_reasons({k: v for k, v in d.items()
                                                          if k != "sell_identity_verified"}, NOW)
    gated = g._canonical_deal_gate(_ps5_deal(), {"prod_ps5_pro": [_row("モバイル一番", 192700)]})
    assert gated.net_profit_jpy == 0 and gated.user_level == "monitoring" and gated.best_buyback_price == 0
    assert "買取価格の商品照合が未完了" in gated.notes


def test_all_unverified_removes_profit_everywhere():
    """照合済みの買取価格が1件も無ければ、利益商品から外れる（未照合の価格で件数を保たない）。"""
    g = _gen(npx.confirmed_sell_keys([MOBILE]))
    rows = [_row("モバイル一番", 192700)]
    deal = g._enrich_deal(_ps5_deal(), rows)
    assert deal.net_profit_jpy == 0 and deal.user_level == "monitoring"
    all_d, easy, watch, mon, adv = g._gate_and_merge_deals([deal], [deal], [], [], [deal], {"prod_ps5_pro": rows})
    assert all(d.net_profit_jpy == 0 for d in all_d) and adv == []
    assert all(d.best_buyback_price != 192700 for d in all_d + easy)          # 未照合の価格を案件に残さない
    s = opp.build(deals=g._nu_profit_deals(g._nu_source_deals, {"prod_ps5_pro": rows}), routes=[],
                  product_genres={}, now=NOW)
    assert s.eligible == []


def test_new_ui_profit_uses_the_verified_sell():
    """旧UIのランキング・Hero の後継（新UIの利益商品・TOP10）: 照合済みの買取商店の値で利益を出す。"""
    g = _gen(npx.confirmed_sell_keys([MOBILE, SHOUTEN]))
    rows = [_row("モバイル一番", 192700), _row("買取商店", 192300)]
    deal = g._enrich_deal(_ps5_deal(), rows)
    all_d, *_ = g._gate_and_merge_deals([deal], [deal], [], [], [], {"prod_ps5_pro": rows})
    assert [(d.best_buyback_shop, d.net_profit_jpy) for d in all_d] == [("買取商店", 51970)]
    s = opp.build(deals=g._nu_profit_deals(g._nu_source_deals, {"prod_ps5_pro": rows}), routes=[],
                  product_genres={}, now=NOW)
    v, = s.eligible
    assert v.sell_source == "買取商店" and v.sell_price == 192300 and v.net_profit == 51970


# ── 生成元（スキャナー）も照合済みの中の最高値 ──────────────────────────────────────

class _Repo:
    def __init__(self, rows):
        self.rows = rows

    def list_buyback_prices_by_product(self, product_id, limit=20):
        return self.rows

    def list_sale_prices(self, **kw):
        return []


def _scan(rows, keys):
    from src.market.beginner_deal_scanner import BeginnerDealScanner
    from src.models.product import ProductModel
    s = BeginnerDealScanner(_Repo(rows))
    s._sell_keys = keys
    s._get_official_url = lambda p: ""
    p = ProductModel(id="prod_ps5_pro", name="PlayStation 5 Pro", genre="game_console", brand="Sony",
                     retail_price=137980, official_price=137980, created_at=NOW, updated_at=NOW)
    return s.scan_product(p)


def _db_row(shop_id, shop, price):
    return {"shop_id": shop_id, "shop_name": shop, "buyback_price": price, "condition": "new_unopened",
            "buyback_url": "https://example.jp/", "observed_at": NOW.isoformat(), "data_source": "auto_scraped",
            "link_verified": True}


def test_scanner_picks_highest_verified_buyback():
    rows = [_db_row("mobile_ichiban", "モバイル一番", 192700), _db_row("kaitori_shouten", "買取商店", 192300)]
    d = _scan(rows, npx.confirmed_sell_keys([MOBILE, SHOUTEN]))
    assert d.best_buyback_shop == "買取商店" and d.best_buyback_price == 192300
    assert "モバイル一番" not in d.buyback_prices_json          # 比較の一覧にも未照合の価格を入れない


def test_scanner_without_verified_buyback_is_unconfirmed():
    d = _scan([_db_row("mobile_ichiban", "モバイル一番", 192700)], npx.confirmed_sell_keys([MOBILE]))
    assert d.net_profit_jpy == 0 and d.best_buyback_price == 0 and d.user_level == "monitoring"
    assert "売却価格未確認" in d.recommended_action


# ── 商品詳細: 利益の売却先 = OpportunityView の売却先 = 表の確認済みの行 ──────────────────────

def test_product_detail_profit_sell_matches_opportunity():
    from src.content.ui import product_detail as pd
    from src.content.ui import product_page
    from src.content.ui import shell
    P1 = _load("p1_p61", ROOT / "tests" / "test_ui_phase1.py")
    g = _gen(npx.confirmed_sell_keys([MOBILE, SHOUTEN]))
    rows = [_row("モバイル一番", 192700), _row("買取商店", 192300)]
    deal = g._enrich_deal(_ps5_deal(), rows)
    d, = g._nu_profit_deals([deal], {"prod_ps5_pro": rows})
    t0 = P1.NOW                                                  # test_ui_phase1 の描画の基準時刻にそろえる
    d.update(genre="game_console", sell_checked_at=(t0 - timedelta(hours=1)).isoformat())
    off = {"product_id": "prod_ps5_pro", "price_role": "official", "price_type": "official_price",
           "canonical_price_type": "RETAIL", "source_name": "メーカー公式/定価", "price": 137980,
           "observed_at": t0.strftime("%Y-%m-%d"), "freshness_basis": "verified", "is_exact_product_match": False,
           "rejection_reason": "", "condition": "new_unopened", "link_type": "official_top"}
    at = (t0 - timedelta(hours=1)).isoformat()
    obs = [off, dict(MOBILE, observed_at=at, item_url="https://www.mobile-ichiban.com/"),
           dict(SHOUTEN, observed_at=at, item_url="https://www.kaitorishouten-co.jp/kaden")]
    ctx = P1._ctx(products=[{"product_id": "prod_ps5_pro", "name": "PlayStation 5 Pro", "genre": "game_console",
                             "brand": "Sony", "model": "CFI-7100B01", "official_price": 137980,
                             "official_url": "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/"}],
                  profit_deals=[d], price_observations=obs, product_genres={"prod_ps5_pro": "game_console"})
    model, catalog = shell.build_catalog(ctx)
    v = pd.build(products=ctx.products, catalog=catalog, observations=obs, price_history=None,
                 stock_history=None, now=model.now)["prod_ps5_pro"]
    assert v.opportunity is not None and v.opportunity.sell_source == "買取商店"
    assert v.best_sell.source == "買取商店"                                   # 有効な最高 = 利益の売却先
    mob = next(r for r in v.sell_rows if r.source == "モバイル一番")
    assert not mob.usable and not mob.cta_label                              # 参考・商品照合未完了
    html = product_page._article(v)
    main = html.split('class="nu-pd-morerows"')[0]
    assert "買取商店（買取価格）に ¥192,300 で売る場合" in html and "+¥51,970" in html
    i = main.index("利益の計算に使った売却先")
    assert "確認済み" in main[i:main.index("</tr>", i)]
    assert "モバイル一番" not in main.split('id="pd-ps5_pro-sell"')[1]          # 参考の行は折りたたみの中だけ


# ── 価格の履歴: 未照合の買取価格を確定の系列にしない ────────────────────────────────────

def test_price_history_skips_unverified_buyback():
    from src.market import price_history as ph
    h = ph.merge(ph.empty(), [MOBILE, SHOUTEN], now=NOW)
    assert [s["source"] for s in h["series"].values()] == ["買取商店"]


# ── ルート経由の成果物（AI・資金配分・ヘルス・実行・通知）も未照合の売値を通さない ─────────────────

def test_route_artifacts_reject_unverified_sell():
    bad = RF.safe_route(NOW, "prod_ps5_pro", sell_exact_match=False)
    assert "sell_identity_unverified" in opp.route_reasons(bad, NOW)
    assert opp.confirmed_routes([bad], NOW) == []
    keys = opp.current_route_keys({"main_routes": [bad]}, NOW)
    rec = {"route_id": opp.route_key(bad), "kind": "main", "product_id": "prod_ps5_pro"}
    assert not opp.record_route_ok(rec, keys) and not opp.record_route_alive(dict(rec, status="OPEN"), keys)


# ── deploy-check #833 ────────────────────────────────────────────────────────

def _dc_run(tmp_path, monkeypatch, html: str, obs: list):
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs/index.html").write_text(html, encoding="utf-8")
    (root / "exports/normalized_price_observations").mkdir(parents=True)
    (root / "exports/normalized_price_observations/latest.json").write_text(
        json.dumps({"observations": obs}, ensure_ascii=False), encoding="utf-8")
    for n in ("config", "data", "src", "scripts"):
        (root / n).symlink_to(ROOT / n)
    dc = _load("deploy_check_p61", ROOT / "scripts" / "deploy_check.py")
    monkeypatch.setattr(dc, "PROJECT_ROOT", root)
    monkeypatch.setattr(dc, "PUBLIC_DIR", root / "docs")
    return {r["check"]: r for r in dc._check_data_correctness()}


def _pd_html(shop, price, quality="確認済み"):
    return ('<section data-nu-page="product"><article class="nu-pd" data-nu-pd="prod_ps5_pro">'
            f'<span class="nu-osub">Sony 公式ストアで買い、{shop}（買取価格）に ¥{price:,} で売る場合</span>'
            f'<table><tr><th>{shop}<span>利益の計算に使った売却先</span></th><td>{quality}</td></tr></table>'
            '</article></section><script type="application/json"></script>')


def test_deploy_check_833(tmp_path, monkeypatch):
    ok = _dc_run(tmp_path / "a", monkeypatch, _pd_html("買取商店", 192300), [MOBILE, SHOUTEN])
    assert ok["opportunity_sell_identity_verified"]["level"] == "ok"
    ng = _dc_run(tmp_path / "b", monkeypatch, _pd_html("モバイル一番", 192700, "参考・商品照合未完了"), [MOBILE, SHOUTEN])
    assert ng["opportunity_sell_identity_verified"]["level"] == "error"
    # 店名に括弧があっても正しく読む
    paren = sell_obs("ドラゴンスター（秋葉原）", 192500)
    ok2 = _dc_run(tmp_path / "c", monkeypatch, _pd_html("ドラゴンスター（秋葉原）", 192500), [paren])
    assert ok2["opportunity_sell_identity_verified"]["level"] == "ok"


def _pd_ps5(obs_sell: list[dict], keys_obs: list[dict] | None = None):
    """PS5 Pro の商品詳細（新UI）を、買取の観測 obs_sell で作る。利益の案件は keys_obs の照合で決める。"""
    from src.content.ui import product_detail as pd
    from src.content.ui import product_page
    from src.content.ui import shell
    P1 = _load("p1_p61b", ROOT / "tests" / "test_ui_phase1.py")
    t0 = P1.NOW
    at = (t0 - timedelta(hours=1)).isoformat()
    g = _gen(npx.confirmed_sell_keys(keys_obs if keys_obs is not None else obs_sell))
    rows = [_row(o["source_name"], o["price"]) for o in obs_sell]
    deal = g._enrich_deal(_ps5_deal(), rows)
    deals = g._nu_profit_deals([deal], {"prod_ps5_pro": rows})
    for d in deals:
        d.update(genre="game_console", sell_checked_at=at)
    off = {"product_id": "prod_ps5_pro", "price_role": "official", "price_type": "official_price",
           "canonical_price_type": "RETAIL", "source_name": "メーカー公式/定価", "price": 137980,
           "observed_at": t0.strftime("%Y-%m-%d"), "freshness_basis": "verified", "is_exact_product_match": False,
           "rejection_reason": "", "condition": "new_unopened", "link_type": "official_top"}
    obs = [off] + [dict(o, observed_at=at, item_url="https://kaitori.example.jp/" + str(i))
                   for i, o in enumerate(obs_sell)]
    ctx = P1._ctx(products=[{"product_id": "prod_ps5_pro", "name": "PlayStation 5 Pro", "genre": "game_console",
                             "brand": "Sony", "model": "CFI-7100B01", "official_price": 137980,
                             "official_url": "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/"}],
                  profit_deals=deals, price_observations=obs, product_genres={"prod_ps5_pro": "game_console"})
    model, catalog = shell.build_catalog(ctx)
    v = pd.build(products=ctx.products, catalog=catalog, observations=obs, price_history=None,
                 stock_history=None, now=model.now)["prod_ps5_pro"]
    return v, product_page._article(v)


def test_product_detail_does_not_rank_unverified_sell():
    """旧UIの案件カードの買取店比較の後継（商品詳細の売却の表）: 照合未了の店は利益の計算に使わず、
    購入・売却の誘導（ボタン）も付けず「参考」。順位（1位）は付けない。照合済みの店に利益を付ける。"""
    unv = sell_obs("モバイル一番", 192900, exact=False, link="shop_home")
    v, html = _pd_ps5([unv, sell_obs("買取商店", 192300)])
    mob = next(r for r in v.sell_rows if r.source == "モバイル一番")
    assert not mob.usable and not mob.cta_label and v.best_sell.source == "買取商店"
    assert "+¥54,920" not in html and "1位" not in html                      # 未照合の価格の差益（192,900 − 137,980）
    assert v.opportunity is not None and v.opportunity.sell_source == "買取商店"


def test_product_detail_does_not_use_higher_unverified_sell():
    """旧UIの監視中カードの後継: 照合未了の店の高い値（¥152,000）を「最高」の売却・利益の売却先にしない。
    照合済みの買取商店（¥150,000）だけで利益を計算する。照合済みが無ければ利益を出さない。"""
    v, html = _pd_ps5([sell_obs("モバイル一番", 152000, exact=False), sell_obs("買取商店", 150000)],
                      keys_obs=[sell_obs("買取商店", 150000)])
    assert v.best_sell.source == "買取商店" and v.opportunity.sell_source == "買取商店"
    assert not next(r for r in v.sell_rows if r.source == "モバイル一番").usable
    assert "1位" not in html and "+¥11,670" not in html                      # 未照合の価格の利益（152,000 基準）
    v2, _h = _pd_ps5([sell_obs("モバイル一番", 152000, exact=False)], keys_obs=[])
    assert v2.opportunity is None and v2.best_sell is None


# ── 買取店比較の状態（照合済みの店の数。旧UIの _buyback_comparison が使っていた正本で確かめる） ─────────

def _cmp(obs, rows):
    """照合済みの店の数から比較の状態（none / single / multi）。旧UIの _buyback_comparison と同じ正本
    （normalized_prices.confirmed_sell_keys）。新UIの利益の売却先（sell_identity_verified）も同じ正本を使う。"""
    keys = {k for k in npx.confirmed_sell_keys(obs) if k[0] == "prod_ps5_pro"}
    shops = {k[1] for k in keys}
    state = "none" if not shops else ("single" if len(shops) == 1 else "multi")
    return state, sorted(keys), [o for o in obs if (o["product_id"], o["source_name"], o["price"]) not in keys]


@pytest.mark.parametrize("obs, rows, state, n_conf", [
    ([sell_obs("A", 190000)], [_row("A", 190000)], "single", 1),                                   # 1店舗
    ([sell_obs("A", 190000), sell_obs("B", 189000)], [_row("A", 190000), _row("B", 189000)], "multi", 2),
    ([sell_obs("A", 190000), sell_obs("B", 189000), sell_obs("C", 188000)],
     [_row("A", 190000), _row("B", 189000), _row("C", 188000)], "multi", 3),                       # 3店舗
    ([], [], "none", 0),                                                                           # 0店舗
    ([sell_obs("A", 190000), sell_obs("U", 192000, exact=False, link="shop_home")],
     [_row("U", 192000), _row("A", 190000)], "single", 1),                                          # 1照合済み+1未照合
    ([sell_obs("A", 190000), sell_obs("S", 191000, fresh=False)],
     [_row("S", 191000), _row("A", 190000)], "single", 1),                                          # 1照合済み+古い
    ([sell_obs("A", 190000), sell_obs("I", 191000, exact=False)],
     [_row("I", 191000), _row("A", 190000)], "single", 1),                                          # 1照合済み+照合false
    ([sell_obs("U1", 192000, exact=False, link="shop_home"), sell_obs("U2", 191000, link="search")],
     [_row("U1", 192000), _row("U2", 191000)], "none", 0),                                          # 全部未照合
])
def test_comparison_state(obs, rows, state, n_conf):
    st, conf, ref = _cmp(obs, rows)
    assert st == state and len(conf) == n_conf and len(ref) == len(rows) - n_conf


def test_ps5_pro_single_state_profit_and_833(tmp_path, monkeypatch):
    """PS5 Pro と同じ形（照合済みは買取商店だけ・モバイル一番は参考）: 比較の状態は single。
    新UIの利益は買取商店（¥192,300・純利益 ¥51,970）で、モバイル一番の差益（+¥54,720）は出さない。
    deploy-check #833（旧 #446 の後継の検査）は買取商店なら ok、モバイル一番を売却先にすると ERROR。"""
    assert _cmp([MOBILE, SHOUTEN], [])[0] == "single"
    v, html = _pd_ps5([MOBILE, SHOUTEN])
    assert v.opportunity.sell_source == "買取商店" and "+¥51,970" in html and "+¥54,720" not in html
    assert "比較済み" not in html and "1位" not in html and "2位" not in html
    ok = _dc_run(tmp_path / "a", monkeypatch, _pd_html("買取商店", 192300), [MOBILE, SHOUTEN])
    ng = _dc_run(tmp_path / "b", monkeypatch, _pd_html("モバイル一番", 192700), [MOBILE, SHOUTEN])
    assert ok["opportunity_sell_identity_verified"]["level"] == "ok"
    assert ng["opportunity_sell_identity_verified"]["level"] == "error"


def test_multi_state_uses_highest_verified_sell():
    obs = [sell_obs("買取商店", 192300), sell_obs("買取一丁目", 190000)]
    assert _cmp(obs, [])[0] == "multi"
    v, _html = _pd_ps5(obs)
    assert v.best_sell.source == "買取商店" and v.opportunity.sell_source == "買取商店"
    assert sum(1 for r in v.sell_rows if r.usable) == 2


def test_same_shop_two_rows_is_single_and_deal_sell_counts():
    """同じ店の照合済みの行が2つでも1店舗（multi にしない）。"""
    obs = [sell_obs("買取商店", 192300), sell_obs("買取商店", 190000, cond="new_unopened_simfree")]
    st, conf, ref = _cmp(obs, [_row("買取商店", 192300), _row("買取商店", 190000)])
    assert st == "single" and len(conf) == 2 and ref == []
    # 案件の売値（店名・価格）が照合済みなら確定、照合未了の店なら確定にしない（新UIの判定）
    keys = npx.confirmed_sell_keys([SHOUTEN])
    assert ("prod_ps5_pro", "買取商店", 192300) in keys and ("prod_ps5_pro", "モバイル一番", 192700) not in keys


def test_diagnostics_reason_for_unverified_sell():
    """利益商品の診断（opportunity_diagnostics）でも、売却側の照合未了は「商品の照合」の理由に数える（other にしない）。"""
    from src.market import opportunity_diagnostics as od
    assert od._reason("sell_identity_unverified") == "invalid_identity"
