# -*- coding: utf-8 -*-
"""TCG Route T1（公式定価 → 国内買取店）: 買取の同一性・単位・条件・鮮度・外れ値・利益・履歴・失敗時の保持。"""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.tcg import buyback as bb
from src.tcg.hub import product_view as pv

JST = bb.JST
NOW = datetime(2026, 11, 21, 18, 0, tzinfo=JST)
ROOT = Path(__file__).resolve().parent.parent

CFG = {
    "freshness": {"page_date_fresh_days": 1, "page_asof_tolerance_minutes": 30, "observed_max_hours": 36},
    "outlier": {"ratio": 1.5}, "surge": {"yen": 1000, "pct": 15},
    "route_costs": {"store_counter": {"label": "店頭受取 → 店頭持込", "purchase_shipping_yen": 0, "outbound_shipping_yen": 0,
                                       "other_yen": 0, "note": "交通費は含まない", "shops_supporting": ["rudeya"]}},
    "shops": {"rudeya": {"name": "買取ルデヤ", "freshness_basis": "page_asof"},
              "kaitorishouten": {"name": "買取商店", "freshness_basis": "page_date"}},
    "targets": [
        {"product_id": "deck", "tcg": "POKEMON", "name": "デッキセット", "unit": "SET", "jan": "4500000000111"},
        {"product_id": "box", "tcg": "POKEMON", "name": "拡張パック BOX", "unit": "BOX", "jan": "4500000000222"},
    ],
}


def art(name, price, jan, memo="新品未開封のみ買取可", badge="新品"):
    p = f'<span class="product-card-price-value">{price:,}<span class="unit">円</span></span>' if price else ""
    return (f'<article class="pgrid-card"><a href="https://r.example/item/1" class="product-card-thumb"></a>'
            f'<span class="product-card-cond-badge is-new">{badge}</span>'
            f'<a class="product-card-name-link" href="https://r.example/item/1">{name}</a>'
            f'<span class="product-card-jan-text">JAN: {jan}</span><span class="product-card-memo">{memo}</span>'
            f'<div class="product-card-price-wrap">{p}</div></article>')


def page(*arts, asof="2026年11月21日 17時55分現在"):
    return f'<html><body><span class="cat-intro-time">{asof}</span>{"".join(arts)}</body></html>'


def row(shop="rudeya", price=8000, jan="4500000000111", cond=bb.C_UNOPENED, obs=NOW, asof=None, upd=None, name="商品"):
    return {"shop": shop, "raw_product_name": name, "jan": jan, "price": price, "condition": cond,
            "source_url": "https://s.example/", "observed_at": obs.isoformat(),
            "page_asof": (asof or obs).isoformat() if shop == "rudeya" else None, "source_updated_at": upd}


# ── パース ──
def test_parse_rudeya_reads_rows_asof_and_skips_rows_without_a_price():
    html = page(art("デッキセット", 8000, "4500000000111"), art("拡張パック BOX [M7]", None, "4500000000222"))
    r = bb.parse_rudeya(html, "https://r.example/c", NOW)
    assert len(r["rows"]) == 1 and r["rows"][0]["price"] == 8000 and r["rows"][0]["jan"] == "4500000000111"
    assert r["asof"] == datetime(2026, 11, 21, 17, 55, tzinfo=JST)
    assert r["rows"][0]["observed_at"] == NOW.isoformat()                 # 取得時刻は実際の取得時刻（ページの時刻で書き換えない）


@pytest.mark.parametrize("memo,badge,expect", [
    ("新品未開封/シュリンク付きのみの買取となります。", "新品", bb.C_SEALED),
    ("未開封品のみ買取可。", "新品", bb.C_UNOPENED),
    ("", "新品", bb.C_NEW),
    ("シュリンクなしは開封扱い", "新品", bb.C_OPENED),
    ("開封済み可", "中古", bb.C_OPENED),
    ("ダンボール未開封のみ買取可、ダンボールそのまま発送買取不可", "新品", bb.C_UNKNOWN),
    ("", "", bb.C_UNKNOWN),
])
def test_condition_never_treats_opened_or_unclear_as_sealed(memo, badge, expect):
    assert bb.condition_of(memo, badge) == expect


# ── 同一性・単位 ──
def test_identity_requires_the_same_jan_and_a_compatible_unit():
    ok = bb.identify(row(jan="4500000000111", name="デッキセット"), CFG["targets"])
    assert ok["identity_status"] == bb.ID_CONFIRMED and ok["product_id"] == "deck" and ok["unit"] == "SET"
    similar = bb.identify(row(jan="4500000000999", name="デッキセット エーフィ"), CFG["targets"])         # 名前が似ていても JAN が違えば別商品
    assert similar["identity_status"] == "NO_TARGET" and similar["product_id"] is None
    case = bb.identify(row(jan="4500000000222", name="拡張パック [カートン]"), CFG["targets"])             # JAN が同じでも単位が違えば採用しない
    assert case["identity_status"] == "UNIT_MISMATCH" and case["product_id"] is None
    box = bb.identify(row(jan="4500000000222", name="拡張パック BOX [M6]"), CFG["targets"])
    assert box["identity_status"] == bb.ID_CONFIRMED and box["unit"] == "BOX"
    deck_as_box = bb.identify(row(jan="4500000000111", name="デッキセット BOX"), CFG["targets"])         # セット商品を BOX と書く行は採用しない
    assert deck_as_box["identity_status"] == "UNIT_MISMATCH"


def test_duplicate_rows_collapse_and_conflicting_prices_are_dropped():
    a = row(price=8000, name="X")
    assert len(bb.dedupe([a, dict(a)])) == 1                             # 「買取強化」と通常の一覧の両方に載る行
    assert bb.dedupe([a, {**a, "price": 9000}]) == []                    # 同じキーで価格が食い違う: どちらも使わない


# ── 鮮度 ──
def test_rudeya_freshness_depends_on_the_page_time_matching_the_fetch_time():
    assert bb.classify_freshness(row(asof=NOW - timedelta(minutes=5)), CFG, NOW)[0] == bb.FRESH
    assert bb.classify_freshness(row(asof=NOW - timedelta(hours=3)), CFG, NOW)[0] == bb.UNKNOWN_FRESHNESS
    r = row(); r["page_asof"] = None
    assert bb.classify_freshness(r, CFG, NOW)[0] == bb.UNKNOWN_FRESHNESS


def test_old_observations_become_stale_and_future_ones_are_unknown():
    old = NOW - timedelta(hours=40)
    assert bb.classify_freshness(row(obs=old), CFG, NOW)[0] == bb.STALE        # 取得に失敗した日の古い価格
    assert bb.classify_freshness(row(obs=NOW + timedelta(hours=2)), CFG, NOW)[0] == bb.UNKNOWN_FRESHNESS


def test_new_wording_without_unopened_is_listed_but_not_executable():
    rows = ann(row(shop="kaitorishouten", price=9000, cond=bb.C_NEW, upd="2026-11-20"))
    s = bb.summarize_product("deck", rows, CFG)
    assert s["status"] == "LISTED_ONLY" and s["highest_executable"] is None and s["highest_listed"]["price"] == 9000


def test_page_dated_shop_uses_the_pages_update_date():
    r = row(shop="kaitorishouten", upd="2026-11-20")
    assert bb.classify_freshness(r, CFG, NOW)[0] == bb.FRESH
    assert bb.classify_freshness({**r, "source_updated_at": "2026-11-17"}, CFG, NOW)[0] == bb.STALE
    assert bb.classify_freshness({**r, "source_updated_at": "2026-11-25"}, CFG, NOW)[0] == bb.UNKNOWN_FRESHNESS
    assert bb.classify_freshness({**r, "source_updated_at": None}, CFG, NOW)[0] == bb.UNKNOWN_FRESHNESS


# ── 最高値・外れ値 ──
def ann(*rows):
    return bb.annotate(list(rows), CFG, NOW)


def test_highest_listed_and_highest_executable_can_differ():
    rows = ann(row(price=9000, cond=bb.C_OPENED), row(shop="kaitorishouten", price=8000, cond=bb.C_UNOPENED, upd="2026-11-20"))
    s = bb.summarize_product("deck", rows, CFG)
    assert s["highest_listed"]["price"] == 9000 and s["highest_executable"]["price"] == 8000     # 開封済みは実行可能に使わない
    assert s["status"] == "EXECUTABLE" and s["single_source"] is True


def test_stale_and_unknown_rows_are_listed_but_never_executable():
    rows = ann(row(price=9000, obs=NOW - timedelta(hours=50)), row(shop="kaitorishouten", price=7000, upd=None))
    s = bb.summarize_product("deck", rows, CFG)
    assert s["status"] == "LISTED_ONLY" and s["highest_executable"] is None and s["highest_listed"]["price"] == 9000


def test_outlier_top_price_is_held_for_review_and_second_is_not_called_the_highest():
    rows = ann(row(price=30000), row(shop="kaitorishouten", price=15000, cond=bb.C_UNOPENED, upd="2026-11-20"))
    s = bb.summarize_product("deck", rows, CFG)
    assert s["status"] == bb.OUTLIER_REVIEW and s["highest_executable"] is None and s["outlier"]["price"] == 30000
    near = bb.summarize_product("deck", ann(row(price=9000), row(shop="kaitorishouten", price=8000, cond=bb.C_UNOPENED, upd="2026-11-20")), CFG)
    assert near["status"] == "EXECUTABLE" and near["highest_executable"]["price"] == 9000 and near["shop_count"] == 2
    assert [r["price"] for r in near["ranking"]] == [9000, 8000]


# ── 利益 ──
MSRP = {"retail_price": 6200, "checked_at": "2026-11-21", "official_url": "https://x"}


def prof(rows, msrp=MSRP, cfg=CFG, pid="deck"):
    return bb.profit_for(bb.summarize_product(pid, ann(*rows), cfg), msrp, cfg)


def test_profit_is_calculated_only_with_a_same_unit_official_price_and_a_known_route():
    p = prof([row(price=8000)])
    assert p["status"] == bb.PROFITABLE and p["net_profit"] == 1800 and p["acquisition_cost"] == 6200
    assert p["roi_pct"] == round(1800 / 6200 * 100, 1) and p["single_source"] is True
    assert prof([row(price=6000)])["status"] == bb.NO_PROFIT                                  # 利益がマイナスなら NO_PROFIT
    assert prof([row(price=8000)], msrp=None)["status"] == bb.NOT_CALCULATED                  # BOX の定価が無い: パック価格から作らない
    assert prof([row(shop="kaitorishouten", price=9000, cond=bb.C_UNOPENED, upd="2026-11-20")])["status"] == bb.NOT_CALCULATED   # 費用の分かる経路が無い
    assert prof([row(price=8000, obs=NOW - timedelta(hours=60))])["status"] == bb.NOT_CALCULATED              # STALE
    assert prof([row(price=8000, cond=bb.C_OPENED)])["status"] == bb.NOT_CALCULATED                           # 開封済み


def test_single_source_far_above_retail_waits_for_a_second_shop():
    p = prof([row(price=30000)])                                         # 定価 6,200 の 4.8 倍・1 店のみ
    assert p["status"] == bb.NOT_CALCULATED and "1 店のみ" in p["reason"]
    two = prof([row(price=30000), row(shop="kaitorishouten", price=25000, cond=bb.C_UNOPENED, upd="2026-11-20")])
    assert two["status"] == bb.PROFITABLE                                # 2 店で確認できれば算出する


def test_unknown_costs_are_never_treated_as_zero():
    cfg = json.loads(json.dumps(CFG))
    cfg["route_costs"]["store_counter"]["outbound_shipping_yen"] = None
    assert prof([row(price=8000)], cfg=cfg)["status"] == bb.NOT_CALCULATED


def test_outlier_blocks_profit():
    rows = [row(price=30000), row(shop="kaitorishouten", price=15000, cond=bb.C_UNOPENED, upd="2026-11-20")]
    assert prof(rows)["status"] == bb.NOT_CALCULATED


# ── 履歴・価格の変化 ──
def test_history_keeps_one_row_per_day_and_detects_price_events():
    r1 = ann(row(price=8000, obs=NOW - timedelta(days=1)))
    h = bb.update_history([], r1, "2026-11-20")
    assert len(h) == 1 and len(bb.update_history(h, r1, "2026-11-20")) == 1
    r2 = ann(row(price=9200))
    ev = bb.price_events(h, r2, "2026-11-21", CFG)
    assert ev and ev[0]["type"] == "BUYBACK_SURGE" and ev[0]["from"] == 8000 and ev[0]["to"] == 9200
    assert bb.price_events(h, ann(row(price=8300)), "2026-11-21", CFG)[0]["type"] == "PRICE_RISE"
    assert bb.price_events(h, ann(row(price=7000)), "2026-11-21", CFG)[0]["type"] == "PRICE_DROP"
    assert bb.price_events(h, ann(row(price=8000)), "2026-11-21", CFG) == []


# ── 収集（失敗時に古い行の日付を進めない） ──
def test_failed_pages_keep_the_previous_rows_with_their_original_time(monkeypatch):
    import scripts.collect_tcg_buyback as c
    cfg = json.loads(json.dumps(CFG))
    cfg["shops"]["rudeya"]["pages"] = ["https://r.example/c"]
    old = ann(row(price=8000, obs=NOW - timedelta(hours=20)))
    old[0]["source_url"] = "https://r.example/c"
    monkeypatch.setattr(c, "fetch", lambda url, timeout=20: None)
    monkeypatch.setattr(c, "_LAST", {"reason": "connection_error"})
    rows, state = c.collect(cfg, old, NOW, fetcher=lambda u: None)
    assert state["rudeya"]["state"] == "FAILED" and rows and rows[0]["observed_at"] == old[0]["observed_at"]


def test_successful_page_replaces_rows_with_the_new_observation():
    import scripts.collect_tcg_buyback as c
    cfg = json.loads(json.dumps(CFG))
    cfg["shops"]["rudeya"]["pages"] = ["https://r.example/c"]
    rows, state = c.collect(cfg, [], NOW, fetcher=lambda u: page(art("デッキセット", 8000, "4500000000111")))
    assert state["rudeya"]["state"] == "OK" and rows[0]["price"] == 8000 and rows[0]["observed_at"] == NOW.isoformat()


# ── 画面（商品カード・HOME） ──
def _hub(buy_rows, msrp_rows=None):
    lots = {"generated_at": NOW.isoformat(), "evaluated_at": NOW.isoformat(), "items": []}
    reg = {"generated_at": NOW.isoformat(), "products": [
        {"tcg": "POKEMON", "product_id": "deck", "name": "デッキセット", "product_type": "CONSTRUCTED_DECK", "release_date": "2026-12-01"},
        {"tcg": "POKEMON", "product_id": "box", "name": "拡張パック BOX", "product_type": "BOOSTER_BOX", "release_date": "2026-12-01"}]}
    ms = {"generated_at": NOW.isoformat(), "verified": msrp_rows if msrp_rows is not None else [
        {"tcg": "POKEMON", "product_id": "deck", "product_type": "CONSTRUCTED_DECK", "retail_price": 6200, "basis": "product_unit",
         "checked_at": "2026-11-21", "official_url": "https://x"}]}
    return pv.build_hub(lots, reg, ms, NOW, {"rows": buy_rows})


def test_hub_shows_profit_only_where_the_evidence_is_complete(monkeypatch):
    monkeypatch.setattr(bb, "load_config", lambda path=bb.CONFIG_PATH: CFG)
    h = _hub([row(price=8000, jan="4500000000111"), row(price=14000, jan="4500000000222", name="拡張パック BOX [M6]")])
    by = {p["product_id"]: p for p in h["products"]}
    deck, box = by["deck"], by["box"]
    assert deck["profit"]["status"] == bb.PROFITABLE and deck["profit"]["net_profit"] == 1800
    assert deck["buyback"]["highest_executable"]["price"] == 8000 and deck["buyback"]["single_source"] is True
    assert box["buyback"]["highest_executable"]["price"] == 14000                       # BOX の買取は表示する
    assert box["profit"]["net_profit"] is None and box["profit"]["status"] == "NOT_CALCULATED"   # BOX の定価が無い: 利益は出さない
    pm = pv.profit_map(h and {"products": [{"tcg": "POKEMON", "product_id": "deck", "product_type": "CONSTRUCTED_DECK"}]},
                       {"verified": [{"tcg": "POKEMON", "product_id": "deck", "product_type": "CONSTRUCTED_DECK", "retail_price": 6200,
                                      "basis": "product_unit", "checked_at": "2026-11-21", "official_url": "https://x"}]},
                       {"rows": [row(price=8000, jan="4500000000111")]}, NOW)
    assert pm[("POKEMON", "deck")]["status"] == bb.PROFITABLE


def test_stale_buyback_is_not_shown_as_an_executable_price(monkeypatch):
    monkeypatch.setattr(bb, "load_config", lambda path=bb.CONFIG_PATH: CFG)
    h = _hub([row(price=8000, jan="4500000000111", obs=NOW - timedelta(hours=60))])
    deck = {p["product_id"]: p for p in h["products"]}["deck"]
    assert deck["buyback"]["highest_executable"] is None and deck["buyback"]["status"] == "LISTED_ONLY"
    assert deck["profit"]["net_profit"] is None


def test_hub_page_renders_the_buyback_and_profit_with_assumptions(monkeypatch):
    from src.content import tcg_hub_page as page_mod
    monkeypatch.setattr(bb, "load_config", lambda path=bb.CONFIG_PATH: CFG)
    html = page_mod.render(_hub([row(price=8000, jan="4500000000111")]), generated_label="x")
    assert "最高買取" in html and "¥8,000" in html and "+1,800円" in html and "ROI" in html
    assert "店頭受取 → 店頭持込" in html and "単一ソース" in html and "交通費" in html


def test_home_profit_badge_only_when_a_profit_exists():
    from src.content.ui import lottery_card as lc
    assert lc._profit_badge({}) == "" and lc._profit_badge({"prof": {"net": None}}) == ""
    b = lc._profit_badge({"prof": {"net": 1800, "roi": 29.0, "single": True}})
    assert "利益根拠あり" in b and "単一ソース" in b


# ── 実データ（コミットされた exports/tcg/buyback.json）の品質 ──
@pytest.mark.skipif(not (ROOT / "exports" / "tcg" / "buyback.json").exists(), reason="buyback.json が無い")
def test_committed_buyback_export_has_no_identity_unit_or_duplicate_errors():
    d = json.loads((ROOT / "exports" / "tcg" / "buyback.json").read_text(encoding="utf-8"))
    cfg = bb.load_config()
    targets = {t["product_id"]: t for t in cfg["targets"]}
    seen = set()
    for r in d["rows"]:
        if r["identity_status"] == bb.ID_CONFIRMED:
            t = targets[r["product_id"]]
            assert r["jan"] == t["jan"] and r["unit"] == t["unit"], r                       # 同一性・単位
            k = (r["shop"], r["jan"], r["condition"], r["raw_product_name"])
            assert k not in seen, f"重複した行: {k}"
            seen.add(k)
        if r["executable"]:
            assert r["freshness"] == bb.FRESH and r["condition"] in bb.EXECUTABLE_CONDITIONS, r   # STALE・条件違いが実行可能になっていない
    for pid, s in d["summaries"].items():
        ex = s["highest_executable"]
        assert ex is None or (ex["executable"] and ex["freshness"] == bb.FRESH)


# ── 独立レビュー（M1〜M6）の回帰 ──
def test_carried_over_rows_after_a_failed_fetch_are_stale_and_not_in_history():
    r = row(shop="kaitorishouten", price=9000, cond=bb.C_UNOPENED, upd="2026-11-20", obs=NOW - timedelta(hours=30))
    carried = {**r, "carried_over": True}
    a = ann(carried)
    assert a[0]["freshness"] == bb.STALE and a[0]["executable"] is False                # 失敗後の古い行は、36 時間以内でも新鮮と言わない
    assert bb.update_history([], a, "2026-11-21") == []                                  # 今日の観測として履歴に入れない


def test_failed_fetch_marks_kept_rows_as_carried_over():
    import scripts.collect_tcg_buyback as c
    cfg = json.loads(json.dumps(CFG))
    cfg["shops"]["rudeya"]["pages"] = ["https://r.example/c"]
    old = ann(row(price=8000, obs=NOW - timedelta(hours=20)))
    old[0]["source_url"] = "https://r.example/c"
    rows, _ = c.collect(cfg, old, NOW, fetcher=lambda u: None)
    assert rows and rows[0]["carried_over"] is True and rows[0]["observed_at"] == old[0]["observed_at"]


@pytest.mark.parametrize("text,badge", [
    ("シュリンク付き 開封済み", "新品"), ("展示品・傷あり 未開封", "新品"), ("未開封のみ 拡張パック BOX(シュリンクなし)", "新品"),
    ("未開封 中古品", "新品"), ("未開封 ダメージ品", "新品")])
def test_negative_condition_words_beat_unopened_wording(text, badge):
    assert bb.condition_of(text, badge) not in bb.EXECUTABLE_CONDITIONS


def test_rudeya_item_name_with_no_shrink_is_not_executable():
    html = page(art("拡張パック BOX(シュリンクなし)", 5000, "4500000000222", memo="未開封のみ買取可"))
    r = bb.parse_rudeya(html, "https://r.example/c", NOW)["rows"][0]
    assert r["condition"] not in bb.EXECUTABLE_CONDITIONS


def test_profit_shows_which_shop_price_it_is_based_on(monkeypatch):
    from src.content import tcg_hub_page as page_mod
    monkeypatch.setattr(bb, "load_config", lambda path=bb.CONFIG_PATH: CFG)
    rows = [row(price=8000, jan="4500000000111"), row(shop="kaitorishouten", price=9000, cond=bb.C_UNOPENED, upd="2026-11-20", jan="4500000000111")]
    html = page_mod.render(_hub(rows), generated_label="x")
    assert "¥9,000" in html and "基準: 買取ルデヤ 買取 ¥8,000・定価 ¥6,200" in html        # 最高買取と利益の基準の店が違うことを画面に出す
    assert "算出前です。出せるのは公式の定価だけ" not in html and "そろった商品だけ" in html     # 古い注意書きを残さない


def test_home_profit_badge_is_for_store_pickup_lotteries_only():
    import inspect
    from src.content.ui import home_feed
    src = inspect.getsource(home_feed._lottery_cards)
    assert '"STORE"' in src                                                              # 通販の抽選には「利益根拠あり」を出さない（送料が前提と違う）


def test_page_records_the_source_time_so_deploy_check_can_detect_a_stale_page():
    from src.content import tcg_hub_page as page_mod
    lots = {"generated_at": "2026-11-21T12:43:22+09:00", "evaluated_at": NOW.isoformat(), "items": []}
    html = page_mod.render_from_json(lots, {}, {}, NOW)
    assert '<meta name="tcg-source-generated-at" content="2026-11-21T12:43:22+09:00">' in html
    other = page_mod.render_from_json({**lots, "generated_at": "2026-11-22T12:00:00+09:00"}, {}, {}, NOW)
    assert 'content="2026-11-22T12:00:00+09:00"' in other and 'content="2026-11-21T12:43:22+09:00"' not in other
