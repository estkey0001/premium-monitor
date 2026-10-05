"""Phase 6.1: 商品の照合が済んでいない売却価格を、確定利益（案件・ランキング・Hero・新UI・商品詳細）に使わない。

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
    rank = g._tab_ranking(all_d, [], [d for d in all_d if d.category == "game_console"])
    hero = g._section_hero("2026-10-05", "12:00", NOW, NOW, all_deals=all_d, beginner_display_count=0)
    for html in (rank, hero):
        assert "192,700" not in html and "52,370" not in html
    s = opp.build(deals=g._nu_profit_deals(g._nu_source_deals, {"prod_ps5_pro": rows}), routes=[],
                  product_genres={}, now=NOW)
    assert s.eligible == []


def test_legacy_ranking_and_hero_use_the_verified_sell():
    g = _gen(npx.confirmed_sell_keys([MOBILE, SHOUTEN]))
    rows = [_row("モバイル一番", 192700), _row("買取商店", 192300)]
    deal = g._enrich_deal(_ps5_deal(), rows)
    all_d, *_ = g._gate_and_merge_deals([deal], [deal], [], [], [], {"prod_ps5_pro": rows})
    rank = g._tab_ranking(all_d, [], [d for d in all_d if d.category == "game_console"])
    hero = g._section_hero("2026-10-05", "12:00", NOW, NOW, all_deals=all_d, beginner_display_count=1)
    assert "買取商店" in rank and "モバイル一番" not in rank and "52,370" not in rank
    assert "51,970" in hero and "52,370" not in hero


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


def test_legacy_deal_card_compare_does_not_rank_unverified():
    """旧UIの案件カードの買取店比較: 照合未了の店は順位・差益を付けず「参考・商品照合未完了」。"""
    g = _gen(npx.confirmed_sell_keys([sell_obs("モバイル一番", 192900, exact=False, link="shop_home"),
                                      sell_obs("買取商店", 192300)]))
    rows = [dict(_row("モバイル一番", 192900), shop_id="mobile_ichiban"),
            dict(_row("買取商店", 192300), shop_id="kaitori_shouten")]
    deal = g._enrich_deal(_ps5_deal(), rows)
    for pro in (False, True):
        html = g._deal_card(deal, "badge-easy", "利益あり", buyback_rows=rows, pro_mode=pro)
        assert "+¥54,920" not in html                                  # 未照合の価格の差益（192,900 − 137,980）
        rows_html = html[html.index('class="shop-row'):]                # 買取店比較の行
        i = rows_html.index("モバイル一番")
        assert "商品照合未完了" in rows_html[i:i + 600] and "1位" not in rows_html[i - 200:i]
        j = rows_html.index("買取商店")
        assert "+¥54,320" in rows_html[j:j + 400] and j < i            # 照合済みが先で、差益つき


def test_legacy_monitoring_card_compare_does_not_rank_unverified():
    g = _gen(npx.confirmed_sell_keys([sell_obs("買取商店", 150000)]))
    d = _ps5_deal("買取商店", 150000).model_copy(update={"net_profit_jpy": 0, "user_level": "monitoring"})
    rows = [_row("モバイル一番", 152000), _row("買取商店", 150000)]
    html = g._deal_card_monitoring(d, rows)
    rows_html = html[html.index('class="shop-row'):]
    j, i = rows_html.index("買取商店"), rows_html.index("モバイル一番")
    assert j < i and "参考" in rows_html[i - 120:i] and "商品照合未完了" in rows_html[i:i + 200]
    assert 'shop-rank gold">1<' in rows_html[:j]
