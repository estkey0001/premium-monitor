"""Market Research Coverage Wave 4: 小売の取得枠の公平な配分・Apple の同一性・Sofmap の固定登録・TCG の取得枠と取得元の状態。

HTML は構造を保った合成の文字列。通信はしない。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.research import candidates as rc
from src.research import retail_lookup as rl

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=JST)
FRESH = "2026-10-29T10:00:00+09:00"


# ── 公平な取得枠 ───────────────────────────────────────────────────────────────────────

def _item(aid, n, base=50, cap=5, min_items=3):
    return {"adapter_id": aid, "kind": "item", "keys": [(f"{aid}-{i}", base - i) for i in range(n)], "min_items": min_items, "cap": cap, "score": base}


def _index(aid, cost, score=100):
    return {"adapter_id": aid, "kind": "index", "cost": cost, "score": score}


def test_apple_demand_never_starves_sony_or_canon():
    plans = [_index("apple_jp", 6, 120), _index("nikon_direct", 2, 110), _item("sony_store", 8), _item("canon_store", 8)]
    out = rl.allocate_budget(plans, budget=rl.HTTP_BUDGET)
    assert out["apple_jp"]["index"] and len(out["sony_store"]["keys"]) >= rl.ITEM_MIN and len(out["canon_store"]["keys"]) >= rl.ITEM_MIN


def test_even_with_a_tiny_budget_every_item_brand_with_demand_gets_at_least_one():
    plans = [_index("apple_jp", 6, 200), _item("sony_store", 4, base=40), _item("canon_store", 4, base=30)]
    out = rl.allocate_budget(plans, budget=8)                                                   # Apple の一覧 6 + 残り 2
    assert out["apple_jp"]["index"] and len(out["sony_store"]["keys"]) == 1 and len(out["canon_store"]["keys"]) == 1
    assert sum(v["http"] for v in out.values()) <= 8


def test_per_source_cap_and_global_http_cap_hold():
    plans = [_item("sony_store", 20, cap=5), _item("canon_store", 20, cap=5), _item("sofmap_new", 20, cap=3), _index("apple_jp", 6)]
    out = rl.allocate_budget(plans, budget=24)
    assert all(len(out[a]["keys"]) <= c for a, c in (("sony_store", 5), ("canon_store", 5), ("sofmap_new", 3)))   # 取得器ごとの上限
    assert sum(v["http"] for v in out.values()) <= 24                                              # 総数の上限
    tiny = rl.allocate_budget(plans, budget=5)
    assert sum(v["http"] for v in tiny.values()) <= 5


def test_index_that_cannot_be_fully_afforded_is_skipped_not_partially_fetched():
    out = rl.allocate_budget([_index("apple_jp", 6, 100), _item("sony_store", 3)], budget=4)
    assert out["apple_jp"]["index"] is False and out["apple_jp"]["http"] == 0                      # 一覧は全ページ取れるときだけ（途中の一覧で引かない）
    assert len(out["sony_store"]["keys"]) == 3


def test_spare_budget_goes_to_the_highest_scored_remaining_keys():
    plans = [_item("sony_store", 6, base=90, cap=6, min_items=1), _item("canon_store", 6, base=10, cap=6, min_items=1)]
    out = rl.allocate_budget(plans, budget=5)
    assert len(out["sony_store"]["keys"]) == 4 and len(out["canon_store"]["keys"]) == 1            # 最低 1 ずつ、余りは点の高い Sony へ


def test_run_lookups_reaches_sony_and_canon_even_when_apple_fills_the_queue():
    cands = []
    for i in range(80):                                                                           # Apple 候補が 80 件（待ち行列の 50 件を超える）
        cands.append({"candidate_id": f"dp_a{i:03d}", "name": f"iPhone 17 Pro 256GB 色{i} MAAA{i % 10}J/A", "identity_basis": "JAN",
                      "jan": f"45499950{i:05d}", "observed_sell_price": 300000 + i, "observed_at": FRESH})
    cands.append({"candidate_id": "dp_s", "name": "SONY ILCE-9TEST ボディ", "identity_basis": "JAN", "jan": "4548736100009",
                  "observed_sell_price": 100000, "observed_at": FRESH})
    cands.append({"candidate_id": "dp_c", "name": "Canon EOS R6 Mark II ボディ", "identity_basis": "JAN", "jan": "4549292200508",
                  "observed_sell_price": 100000, "observed_at": FRESH})
    calls = []

    def fetch(url):
        calls.append(url)
        if "apple.com" in url:
            return "{}", ""
        if "ILCE-9TEST" in url:
            return "<div>ILCE-9TEST 翌日出荷 500,000 円(税込)</div><b>4548736100009</b>", ""
        return None, "timeout"
    rec = rl.run_lookups(cands, NOW, fetch)
    st = rec["adapter_stats"]
    assert st["sony_store"]["requested"] >= 1 and st["canon_store"]["requested"] >= 1 and st["apple_jp"]["requested"] == 6
    assert any("ILCE-9TEST" in u for u in calls) and any("g5666C001" in u for u in calls)           # Sony・Canon の取得が実際に起きた
    assert rec["lookups"]["dp_s"]["status"] == rl.MATCHED and rec["http_requested"] <= rec["http_budget"]


# ── Apple の同一性 ─────────────────────────────────────────────────────────────────────

_APPLE = [{"name": "iPhone 17 Pro 256GB シルバー", "price": 190000, "url": "u", "jan": "", "model": "MAAA3J/A"},
          {"name": "iPhone 17 Pro 512GB シルバー", "price": 220000, "url": "u", "jan": "", "model": "MAAB3J/A"}]


def _idx(entries=_APPLE):
    return {"apple_jp": {"entries": entries, "observed_at": FRESH}}


def _ident(name, part):
    return {"basis": "JAN", "value": "4549995000001", "name": name, "part_number": part}


def test_apple_part_number_with_matching_capacity_and_generation_is_confirmed():
    r = rl.lookup(_ident("iPhone 17 Pro 256GB シルバー MAAA3J/A SIMフリー", "MAAA3J/A"), _idx())
    ev = r["identity_evidence"]
    assert r["status"] == rl.MATCHED and ev["method"] == "part_exact" and ev["attributes_verified"] is True
    assert ev["capacity"] == "256GB" and ev["line"] == "iPhone 17 Pro"


def test_apple_wrong_capacity_or_generation_with_a_valid_part_number_is_rejected():
    assert rl.lookup(_ident("iPhone 17 Pro 512GB シルバー MAAA3J/A", "MAAA3J/A"), _idx())["status"] == rl.IDENTITY_MISMATCH      # 容量が違う
    assert rl.lookup(_ident("iPhone 16 Pro 256GB シルバー MAAA3J/A", "MAAA3J/A"), _idx())["status"] == rl.IDENTITY_MISMATCH      # 世代が違う
    assert rl.lookup(_ident("iPhone 17 Pro Max 256GB シルバー MAAA3J/A", "MAAA3J/A"), _idx())["status"] == rl.IDENTITY_MISMATCH   # 種類が違う


def test_apple_unreadable_name_stays_partial_not_confirmed():
    r = rl.lookup(_ident("アイフォン セブンティーン MAAA3J/A", "MAAA3J/A"), _idx())              # 容量・世代を名前から読めない
    assert r["status"] == rl.UNSUPPORTED or r["identity_evidence"].get("attributes_verified") is not True
    r2 = rl.lookup(_ident("Apple iPhone MAAA3J/A", "MAAA3J/A"), _idx())
    assert r2["status"] == rl.UNSUPPORTED or r2["identity_evidence"].get("attributes_verified") is False


def _dp(price=125000, at=FRESH):
    return {"candidate_id": "dp_x", "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": rc.DISCOVERED, "name": "iPhone 17 Pro 256GB",
            "identity_basis": "JAN", "observed_sell_price": price, "observed_at": at, "retail_price_hint": None,
            "missing_requirements": ["CANONICAL_UNREGISTERED", "OFFICIAL_PRICE_UNKNOWN"]}


def _lk(verified, method="part_exact"):
    ev = {"basis": "JAN", "method": method}
    if verified is not None:
        ev["attributes_verified"] = verified
    return {"status": "MATCHED", "retailer": "Apple（公式）", "source_type": "OFFICIAL_DIRECT", "product_url": "u", "price": 100000,
            "listed_price": 100000, "availability_state": "UNKNOWN", "observed_at": FRESH, "identity_evidence": ev,
            "price_basis": "UNCONDITIONAL", "price_conditions": [], "points": 0}


def test_confirmed_apple_identity_can_be_high_priority_with_only_stock_and_shipping_missing():
    r = rc.apply_lookups([_dp()], {"dp_x": _lk(True)}, NOW, FRESH)[0]
    assert r["identity_status"] == "IDENTITY_CONFIRMED" and r["status"] == rc.RESEARCH_CANDIDATE
    assert rc.IDENTITY_PARTIAL not in r["missing_requirements"] and r["research_class"] == rc.HIGH_PRIORITY_RESEARCH
    assert {rc.STOCK_UNKNOWN, rc.PURCHASE_SHIPPING_UNKNOWN} <= set(r["missing_requirements"])    # 在庫・送料の不明は理由に残す（高優先は妨げない）
    partial = rc.apply_lookups([_dp()], {"dp_x": _lk(False)}, NOW, FRESH)[0]
    assert partial["identity_status"] == "IDENTITY_PARTIAL" and partial["research_class"] == rc.STANDARD_RESEARCH
    assert rc.apply_lookups([_dp()], {"dp_x": _lk(None)}, NOW, FRESH)[0]["research_class"] == rc.STANDARD_RESEARCH      # 属性を確かめていない


# ── Sony の色違い・在庫語 ──────────────────────────────────────────────────────────────

SONY_SILVER = "<div>ILCE-9TEST/S 翌日出荷 449,900 円(税込)</div><b>4548736153967</b>"


def test_sony_color_variants_are_never_merged_by_model_code():
    ad = rl.SonyStoreAdapter()
    assert ad.item_key({"name": "SONY ILCE-9TEST/B ボディ [ブラック]"}) == "ILCE-9TEST"
    # 型番表記が色違いのページ（/S）は、型番だけの一致では読まない（表記が違う）
    assert ad.parse_item(SONY_SILVER, "ILCE-9TEST") == []
    # 同じ型番のページに JAN が1つだけあり、買取の JAN（ブラック）と違えば、別の色。一致にしない
    page = "<div>ILCE-9TEST 翌日出荷 449,900 円(税込)</div><b>4548736153967</b>"
    idx = {"sony_store": {"entries": ad.parse_item(page, "ILCE-9TEST"), "covered": ["ILCE-9TEST"], "observed_at": FRESH}}
    black = {"basis": "JAN", "value": "4548736153974", "name": "SONY ILCE-9TEST ボディ [ブラック]"}
    assert rl.lookup(black, idx)["status"] == rl.NO_MATCH
    silver = {**black, "value": "4548736153967", "name": "SONY ILCE-9TEST ボディ [シルバー]"}
    assert rl.lookup(silver, idx)["status"] == rl.MATCHED


def test_sony_unknown_stock_wording_is_not_guessed_as_in_stock():
    ad = rl.SonyStoreAdapter()
    assert ad.parse_item("<div>ILCE-9TEST 予約受付中 500,000 円(税込)</div><b>4548736100009</b>", "ILCE-9TEST") == []
    assert ad.parse_item("<div>ILCE-9TEST 入荷待ち 500,000 円(税込)</div><b>4548736100009</b>", "ILCE-9TEST")[0]["availability"] == rl.AVAIL_OUT


# ── Sofmap の固定登録 ─────────────────────────────────────────────────────────────────

SOF = ('<html><head><script type="application/ld+json">{"@type":"Product","name":"テスト カメラ PSTEST ブラック","sku":"18246893",'
       '"offers":{"@type":"Offer","price":"79200","availability":"https://schema.org/InStock","url":"https://www.sofmap.com/product_detail.aspx?sku=18246893"}}</script></head>'
       '<body>型番 PSTEST JANコード 4549292119008 ソフマップ特価 ¥79,200 (税込) ソフマップポイント 7,920ポイントサービス 在庫 在庫あり お一人様1点まで</body></html>')


def test_sofmap_reads_only_registered_jan_sku_pairs_with_points_separate():
    ad = rl.SofmapAdapter()
    ident = {"basis": "JAN", "value": "4549292119008", "name": "Canon PowerShot SX740 HS ブラック"}
    assert ad.item_key(ident) == "18246893" and ad.supports(ident)
    assert not ad.supports({**ident, "value": "4549292119999"})                                    # 登録に無い JAN は引かない（検索しない）
    assert not ad.supports({"basis": "MODEL_CODE", "value": "PSSX740HSBK", "name": "Canon PowerShot SX740 HS"})
    e = ad.parse_item(SOF, "18246893")[0]
    assert e["price"] == 79200 and e["points"] == 7920 and e["limited_quantity"] is True and e["availability"] == rl.AVAIL_IN_STOCK
    r = rl.lookup(ident, {"sofmap_new": {"entries": [e], "covered": ["18246893"], "observed_at": FRESH}})
    assert r["status"] == rl.MATCHED and r["source_type"] == rl.LARGE_RETAILER and r["points"] == 7920
    assert r["price"] == 79200 and rl.COND_LIMITED in r["price_conditions"]                       # ポイントは引かない・数量限定は条件


def test_sofmap_rejects_wrong_jan_wrong_sku_used_items_and_sold_out_prices():
    ad = rl.SofmapAdapter()
    assert ad.parse_item(SOF.replace("4549292119008", "4549292119999"), "18246893") == []        # ページの JAN が登録と違う
    assert ad.parse_item(SOF.replace('"sku":"18246893"', '"sku":"99999999"'), "18246893") == []   # 構造化データの sku が違う
    assert ad.parse_item(SOF.replace("テスト カメラ", "【中古】テスト カメラ"), "18246893") == []   # 中古は対象外
    assert ad.parse_item("<html>なし</html>", "18246893") == []
    out = SOF.replace("InStock", "OutOfStock")
    e = ad.parse_item(out, "18246893")[0]
    ident = {"basis": "JAN", "value": "4549292119008", "name": "Canon PowerShot SX740 HS ブラック"}
    assert rl.lookup(ident, {"sofmap_new": {"entries": [e], "covered": ["18246893"], "observed_at": FRESH}})["status"] == rl.NOT_PURCHASABLE


def test_sofmap_table_is_well_formed_and_not_a_search_scraper():
    import re
    from pathlib import Path

    import yaml
    root = Path(__file__).resolve().parent.parent
    doc = yaml.safe_load((root / "config" / "sofmap_products.yaml").read_text(encoding="utf-8"))
    assert doc["verified_on"] and all(re.fullmatch(r"\d{13}", i["jan"]) and re.fullmatch(r"\d{5,12}", i["sku"]) for i in doc["items"])
    ad = rl.SofmapAdapter()
    assert ad.item_url("18246893") == "https://www.sofmap.com/product_detail.aspx?sku=18246893"            # 詳細ページの URL だけ（検索・一覧の URL を作らない）
    assert ad.item_key({"basis": "JAN", "value": "4549292119999", "name": "Canon PowerShot"}) == ""


# ── 仕入れ元の API ─────────────────────────────────────────────────────────────────────

def test_api_sources_stop_as_pending_user_configuration_without_keys_and_never_read_values():
    st = {a["id"]: a for a in rl.api_source_statuses({})}
    assert {a["status"] for a in st.values()} == {rl.API_PENDING} and set(st) == {"yahoo_shopping_v3", "rakuten_ichiba_item_search"}
    assert st["yahoo_shopping_v3"]["jan_lookup"] == "supported" and st["rakuten_ichiba_item_search"]["jan_lookup"] == "unverified"
    ready = {a["id"]: a for a in rl.api_source_statuses({"YAHOO_SHOPPING_APP_ID": "secret-value", "ENABLE_YAHOO_API": "true"})}
    assert ready["yahoo_shopping_v3"]["status"] == rl.API_READY and "secret-value" not in json.dumps(ready)
    off = {a["id"]: a for a in rl.api_source_statuses({"YAHOO_SHOPPING_APP_ID": "x"})}
    assert off["yahoo_shopping_v3"]["status"] == rl.API_DISABLED


# ── TCG: 取得枠の再配分・取得元の状態 ───────────────────────────────────────────────────

def test_detail_budget_gives_leftover_to_the_largest_source_and_reserves_minimums():
    from src.tcg.lottery import budget as b
    caps = [("CARD_LABO", 24), ("HOBBY_STATION", 10), ("KIDS_REPUBLIC", 6), ("FUKUFUKU_TOREKA", 4)]
    order = b.order_by_cap(caps)
    assert [s for s, _c in order] == ["FUKUFUKU_TOREKA", "KIDS_REPUBLIC", "HOBBY_STATION", "CARD_LABO"]      # 小さい順、最後が一番大きい
    left, used = b.DETAIL_BUDGET_TOTAL, {"FUKUFUKU_TOREKA": 4, "KIDS_REPUBLIC": 1, "HOBBY_STATION": 9}            # 遮断された取得元は 1 件だけ
    allow = {}
    for i, (sid, cap) in enumerate(order):
        allow[sid] = b.next_allowance(cap, left, [c for _s, c in order[i + 1:]])
        left -= used.get(sid, 0)
    assert allow["CARD_LABO"] == 24 and left == b.DETAIL_BUDGET_TOTAL - 14                                  # 余りの枠をカードラボが全部使える
    # 先の取得元が使い切っても、後ろの取得元の最低枠（MIN_QUOTA）は残す
    assert b.next_allowance(10, 6, [24]) == 2 and b.next_allowance(10, 3, [24]) == 0 and b.next_allowance(10, 100, []) == 10


def test_collect_sources_runs_small_sources_first_and_sets_allowances(monkeypatch):
    from src.tcg.lottery import pipeline as pl

    seen = []

    class A:
        def __init__(self):
            self.health, self.announcements, self.max_detail_fetch = {}, [], 0

        def collect(self):
            seen.append((self.name, self.max_detail_fetch))
            self.health = {"detail_fetched": self.used, "status": "HEALTHY"}
            return []

    def mk(name, cap, used):
        return type(name, (A,), {"name": name, "max_detail_fetch": cap, "used": used})
    monkeypatch.setattr(pl, "_adapters", lambda: {"big": mk("big", 24, 20), "small": mk("small", 4, 4), "mid": mk("mid", 10, 9)})
    srcs = [{"source_id": "BIG", "retailer": "B", "adapter": "big"}, {"source_id": "SMALL", "retailer": "S", "adapter": "small"},
            {"source_id": "MID", "retailer": "M", "adapter": "mid"}]
    _ev, health, _an = pl.collect_sources(srcs)
    assert [n for n, _a in seen] == ["small", "mid", "big"]                                          # 枠の小さい順
    assert dict(seen)["big"] == 24 and list(health) == ["BIG", "SMALL", "MID"]                       # 登録簿の順で返す
    assert health["BIG"]["detail_allowance"] == 24


def test_source_health_flags_separate_list_detail_blocked_degraded_and_truncated():
    from src.tcg.lottery import registry as reg
    ok = {"pages": [{"page_type": "listing", "http_status": 200}, {"page_type": "news", "http_status": 200}], "blocked": False,
          "structure_changed_pages": 0, "truncated": False}
    assert reg.source_health_flags(ok) == [reg.LIST_OK, reg.DETAIL_OK]
    blocked = {"pages": [{"page_type": "listing", "http_status": 403}], "blocked": True}
    assert reg.source_health_flags(blocked) == [reg.BLOCKED_FLAG]                                    # 手元で取れて CI で 403 の取得元は WORKING に数えない
    deg = {"pages": [{"page_type": "listing", "http_status": 200}], "structure_changed_pages": 1, "truncated": True}
    assert reg.source_health_flags(deg) == [reg.LIST_OK, reg.PARSER_DEGRADED, reg.TRUNCATED_FLAG]
    f = reg.announcement_funnel([{**ok, "health_flags": reg.source_health_flags(ok)}, {**blocked, "health_flags": reg.source_health_flags(blocked)}])
    assert f["sources_list_ok"] == 1 and f["sources_detail_ok"] == 1 and f["sources_blocked"] == 1 and f["sources_parser_degraded"] == 0


def test_blocked_source_is_not_counted_as_working():
    from src.tcg.lottery import registry as reg
    row = {"adapter": "kids_republic_lottery", "state": reg.ST_SOURCE_BLOCKED, "reachable": False, "blocked": True,
           "official_url": "https://x/", "collection_method": "HTML"}
    assert reg.source_class(row) == reg.SC_IMPLEMENTED_BUT_BLOCKED != reg.SC_WORKING


def test_card_labo_prefers_open_then_deadline_soon_then_new(net_fixture=None):
    from src.collectors.tcg.lottery import clabo
    today = "2026-10-29"
    soon, later, ended = "抽選(応募期間:10/28~10/30)", "抽選(応募期間:11/05~11/10)", "抽選(応募期間:10/20~10/25)"
    assert clabo._title_deadline_soon(soon, today) is True and clabo._title_deadline_soon(later, today) is False
    assert clabo._title_deadline_soon(ended, today) is False and clabo._title_ended(ended, today) is True


# ── 公開の集計（取得器ごとの件数だけ） ─────────────────────────────────────────────────────

def test_public_summary_exposes_per_adapter_counts_only_and_ignores_stale_records():
    products = [{"id": "p1", "name": "既存商品", "genre": "camera", "jan": "", "part_numbers": []}]
    stats = {"sony_store": {"supported": 9, "requested": 3, "fetched": 3, "matched": 2, "no_match": 1, "secret_name": "秘密"},
             "evil_adapter": {"matched": 99}}
    api = [{"id": "yahoo_shopping_v3", "status": "PENDING_USER_CONFIGURATION", "docs": "https://x", "required_env": ["YAHOO_SHOPPING_APP_ID"]}]
    kw = dict(products=products, observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW,
              retail_adapter_stats=stats, retail_api_sources=api)
    rep, _ = rc.build(retail_lookups_generated_at=FRESH, **kw)
    s = rc.public_summary(rep)
    assert s["retail_adapters"] == {"sony_store": {"supported": 9, "requested": 3, "fetched": 3, "matched": 2, "no_match": 1}}   # 許可した取得器・件数だけ
    assert s["retail_api_sources"] == {"PENDING_USER_CONFIGURATION": 1}
    text = json.dumps(s, ensure_ascii=False)
    assert "秘密" not in text and "YAHOO_SHOPPING_APP_ID" not in text and "evil_adapter" not in text
    old, _ = rc.build(retail_lookups_generated_at="2026-10-20T00:00:00+09:00", **kw)
    assert rc.public_summary(old)["retail_adapters"] == {}                                           # 古い日の記録の数字を今日のものにしない


def test_card_labo_fetch_order_puts_deadline_soon_before_later_open_and_ended_last():
    from src.collectors.tcg.lottery import clabo
    today = "2026-10-29"
    cards = [{"title": "抽選(応募期間:11/05~11/10)", "url": "u/later", "published_at": "2026-10-28T00:00:00+09:00"},
             {"title": "抽選(応募期間:10/20~10/25)", "url": "u/ended", "published_at": "2026-10-29T00:00:00+09:00"},
             {"title": "抽選(応募期間:10/28~10/30)", "url": "u/soon", "published_at": "2026-10-20T00:00:00+09:00"},
             {"title": "抽選(応募期間なし・新しい告知)", "url": "u/new", "published_at": "2026-10-29T00:00:00+09:00"}]
    order = [c["url"] for c in sorted(cards, key=lambda c: clabo._fetch_priority(c, today), reverse=True)]
    assert order[0] == "u/soon" and order[-1] == "u/ended"                                       # 期限が近いものが先・終了済みが最後
    assert order.index("u/new") < order.index("u/later") and order.index("u/later") < order.index("u/ended")   # 新しい告知は後ろの日付より先


def test_item_plan_without_keys_consumes_no_budget():
    out = rl.allocate_budget([_item("sofmap_new", 0), _item("sony_store", 3)], budget=24)
    assert out["sofmap_new"]["http"] == 0 and out["sofmap_new"]["keys"] == [] and out["sony_store"]["http"] == 3
