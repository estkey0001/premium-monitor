"""Phase 29（発見から登録した商品の公式直販価格・買取の照合）のテスト。

公式直販価格は公式の証拠（部品番号の組・容量・価格・URL）がそろうときだけ。買取は機種・容量・SIMフリー・キャリア版の除外・
部品番号まで照合し、色で価格が違えば最も低い色の行を使う。ネットワークには出ない（ページは本物と同じ形の小さな HTML）。
各テストに否定の対照を付ける。
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from src.collectors import buyback_kaitori_shouten as ks
from src.discovery import apple
from src.discovery import store as st
from src.market import official_registry as reg
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parent.parent
PID, ALIAS = "prod_iphoneair_256", "iphoneair_256"
PARTS = ["MG274J/A", "MG284J/A", "MG294J/A", "MG2A4J/A"]
NOW = datetime(2026, 10, 17, 23, 30, tzinfo=JST)


def product() -> dict:
    return {p["id"]: p for p in yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))
            ["products"]}[PID]


def ks_html(rows) -> str:
    return ("<table><tr><th>品目</th><th>新品買取</th><th>中古買取</th></tr>" + "".join(
        f'<tr><td><a href="{u}">{n}</a></td><td class="num">¥{p:,}</td><td class="num">¥90,000</td></tr>'
        for n, p, u in rows) + "</table>")


ROWS = [("iPhone Air 256GB スカイブルー MG2A4J/A SIMフリー", 133000, "/products/detail/24681"),
        ("iPhone Air 256GB ライトゴールド MG294J/A SIMフリー", 135000, "/products/detail/24682"),
        ("iPhone Air 256GB クラウドホワイト MG284J/A SIMフリー", 135000, "/products/detail/24683"),
        ("iPhone Air 256GB スペースブラック MG274J/A SIMフリー", 135000, "/products/detail/24684"),
        ("iPhone Air 512GB スカイブルー MG2F4J/A SIMフリー", 137000, "/products/detail/24685"),
        ("iPhone Air 1TB スペースブラック MG2G4J/A SIMフリー", 152000, "/products/detail/24692")]


def collector():
    return ks.KaitoriShoutenCsvCollector.__new__(ks.KaitoriShoutenCsvCollector)


# ── 公式直販価格 ──────────────────────────────────────────────────────────

def test_official_price_evidence_matches_registration():
    p = product()
    v, ev, o = reg.VERIFIED_URLS[PID], reg.IDENTITY_EVIDENCE[PID], reg.OFFICIAL_DIRECT_OFFERS[PID]
    assert v["price_kind"] == "official_direct" and v["url"] == p["official_url"] and v["price"] == 189800
    assert set(ev["variant_skus"]) == set(p["part_numbers"]) == set(PARTS)                # 公式の部品番号の組と同じ
    assert {c for c, _col, _p in ev["variant_skus"].values()} == {"256GB"}                # 256GB だけ
    assert o["price"] == v["price"] and o["stock"] == "UNKNOWN"                           # 在庫は推測しない
    assert reg.identity_state(p)[0] == "IDENTITY_CONFIRMED"
    assert reg.official_direct_gate(PID, p) == (True, ())
    assert reg.official_price_label(PID, 189800) == "公式直販価格"                      # 定価（希望小売価格）と呼ばない
    assert reg.official_price_label(PID, 199800) == "参考価格"                          # 記録と違う値は参考


def test_reference_price_alone_is_not_confirmed(monkeypatch):
    """設定値（retail_price）だけでは公式直販価格にしない（公式の証拠が無ければ関門で止まる）。"""
    for d in (reg.VERIFIED_URLS, reg.IDENTITY_EVIDENCE, reg.OFFICIAL_DIRECT_OFFERS):
        monkeypatch.delitem(d, PID)
    ok, why = reg.official_direct_gate(PID, product())
    assert not ok and "no_official_direct_evidence" in why


def test_canonical_parts_and_capacity_must_match_evidence():
    """正本の part_numbers・capacity を書き換えたら、実行時も確定に使わない（レビュー M-1）。"""
    p = product()
    for bad in (dict(p, part_numbers=PARTS[:2]), dict(p, part_numbers=PARTS[:3] + ["MZZZ9J/A"]),
                dict(p, part_numbers=[]), dict(p, capacity="512GB")):
        assert reg.official_direct_gate(PID, bad)[0] is False and reg.identity_state(bad)[0] != "IDENTITY_CONFIRMED"
    assert reg.official_direct_gate("prod_iphone17_256", {"name": "iPhone 17 256GB SIMフリー", "model_number": ""})[0]


def test_db_shaped_row_also_checks_canonical_parts(monkeypatch):
    """公式の価格を DB に書く経路（DB の行に part_numbers の列が無い）でも、正本の組・容量を引いて照合する（再レビュー M-1）。"""
    row = {"id": PID, "name": "iPhone Air 256GB SIMフリー", "brand": "Apple", "model_number": "", "jan_code": None,
           "retail_price": 189800, "official_price": None}
    assert reg.official_direct_gate(PID, row) == (True, ())                                         # 対照
    monkeypatch.setattr(reg, "_canonical_identity", lambda pid: {"part_numbers": PARTS[:2], "capacity": "256GB"})
    assert reg.official_direct_gate(PID, row)[0] is False
    monkeypatch.setattr(reg, "_canonical_identity", lambda pid: {"part_numbers": PARTS, "capacity": "512GB"})
    assert reg.official_direct_gate(PID, row)[0] is False
    monkeypatch.setattr(reg, "_canonical_identity", lambda pid: {"part_numbers": PARTS, "capacity": "256GB"})
    assert reg.official_direct_gate(PID, row)[0] is True
    monkeypatch.setattr(reg, "_canonical_identity", lambda pid: None)                    # 正本を読めない
    assert reg.official_direct_gate(PID, row)[0] is False
    assert reg.official_direct_gate(PID, dict(row, part_numbers=None))[0] is False


def test_wrong_capacity_or_generation_breaks_identity():
    p = product()
    assert reg.official_direct_gate(PID, dict(p, name="iPhone Air 512GB SIMフリー"))[0] is False      # 容量違い
    assert reg.official_direct_gate(PID, dict(p, name="iPhone 17 256GB SIMフリー"))[0] is False       # 機種違い
    assert reg.identity_state(dict(p, name="iPhone 17 Pro 256GB SIMフリー"))[0] != "IDENTITY_CONFIRMED"
    assert reg.official_direct_gate(PID, p)[0] is True                                                # 対照


def test_recheck_reads_parts_and_flags_change():
    sys.path.insert(0, str(ROOT / "scripts"))
    import recheck_official as ro
    t = next(x for x in ro._targets() if x["product_id"] == PID)
    assert t["parser"] == "apple_parts" and t["match"] == ",".join(sorted(PARTS))

    def page(price, extra=""):
        return "".join(f'"partNumber":"{x}","price":{{"fullPrice":{price}.00}}' for x in PARTS) + extra
    r = ro.parse_apple_parts(page(189800), t["match"])
    assert ro.classify(t, r) == "unchanged"
    assert ro.classify(t, ro.parse_apple_parts(page(199800), t["match"])) == "changed"     # 自動で確定を書き換えない
    mixed = page(189800).replace('"MG2A4J/A","price":{"fullPrice":189800', '"MG2A4J/A","price":{"fullPrice":224800')
    assert ro.classify(t, ro.parse_apple_parts(mixed, t["match"])) == "failed"            # 容量の違う値が混ざれば読まない


def test_recheck_change_blocks_official_direct_audit():
    p = product()
    rows = reg.official_direct_audit([p], today="2026-10-18",
                                     recheck=[{"product_id": PID, "url": reg.VERIFIED_URLS[PID]["url"],
                                               "recorded_price": 189800, "status": "changed", "price": 199800,
                                               "observed_at": "2026-10-18T12:00:00+09:00"}])
    row = next(r for r in rows if r.get("product_id") == PID)
    assert row["eligible"] is False and row["reasons"] == ["recheck_changed"]       # 価格が変われば人の確認待ち
    ok = next(r for r in reg.official_direct_audit([p], today="2026-10-18") if r.get("product_id") == PID)
    assert ok["eligible"] is True and ok["reasons"] == []                                              # 対照
    old = next(r for r in reg.official_direct_audit([p], today="2026-11-05") if r.get("product_id") == PID)
    assert old["eligible"] is False and "verified_at_stale" in old["reasons"]       # 確認から14日を過ぎれば使わない


def test_shipping_known_from_official_record():
    from src.market import official_shipping as osh
    s = osh.purchase_shipping(PID, reg.VERIFIED_URLS[PID]["url"], 189800)
    assert s["fee"] == 0 and s.get("checked_on") and s.get("source") == "src_apple_jp"
    unknown = osh.purchase_shipping("prod_x", "https://shop.example.com/x", 1000)
    assert unknown["fee"] is None                                                            # 根拠が無ければ 0 にしない


# ── 買取の照合 ─────────────────────────────────────────────────────────────

def test_buyback_rule_is_exact_for_registered_product():
    rule = ks.ROW_RULES[ALIAS]
    assert "SIMフリー" in rule["require"] and set(rule["parts"]) == set(PARTS) and rule["color_policy"] == "min"
    assert ks.PRODUCT_URLS[ALIAS] == "https://www.kaitorishouten-co.jp/category/1/709"
    got = ks.match_rows(ROWS, ALIAS)
    assert [r[2] for r in got] == [f"/products/detail/2468{i}" for i in (1, 2, 3, 4)]          # 256GB の4色だけ


def test_buyback_rejects_wrong_capacity_carrier_and_non_simfree():
    bad = [("iPhone Air 512GB スカイブルー MG2F4J/A SIMフリー", 300000, "/products/detail/1"),          # 容量違い
           ("iPhone Air 256GB スカイブルー MG2A4J/A au", 300000, "/products/detail/2"),                # キャリア版
           ("iPhone Air 256GB スカイブルー MG2A4J/A docomo SIMフリー", 300000, "/products/detail/3"),
           ("iPhone Air 256GB スカイブルー MG2A4J/A", 300000, "/products/detail/4"),                    # SIMフリーの明示なし
           ("iPhone Air 256GB スカイブルー MZZZ9J/A SIMフリー", 300000, "/products/detail/5"),          # 公式に無い部品番号
           ("iPhone Air 256GB スカイブルー MG2A4J/A MG274J/A SIMフリー", 300000, "/products/detail/6"),  # 番号が2つ
           ("iPhone 17 Pro Air 256GB MG2A4J/A SIMフリー", 300000, "/products/detail/7"),                # 別の機種
           ("iPhone Air 256GB スカイブルー MG2A4J/A SIMフリー 中古", 300000, "/products/detail/8")]       # 中古
    assert ks.match_rows(bad, ALIAS) == []
    assert ks.match_rows(ROWS[:1], ALIAS) == ROWS[:1]                                                   # 対照


def test_color_specific_prices_not_mixed():
    c = collector()
    assert c._parse_price(ks_html(ROWS), ALIAS, "") == 133000                    # 最高値の色（135,000）を使わない
    assert c._parse_detail_url(ks_html(ROWS), "x") == "https://www.kaitorishouten-co.jp/products/detail/24681"
    same = [(n, 135000, u) for n, _p, u in ROWS[:4]]
    assert c._parse_price(ks_html(same), ALIAS, "") == 135000                                           # 対照
    assert c._parse_price(ks_html(ROWS), "iphone17_256", "") is None              # 既存の商品の規則は変えない


def test_used_column_never_read_as_new():
    c = collector()
    html = ks_html(ROWS).replace("新品買取", "中古買取X")                         # 新品買取の列が無い表
    assert c._parse_price(html, ALIAS, "") is None and c.last_failure_reason == "product_not_listed"


def test_buyback_target_registered_and_not_kept_on_failure():
    spec = importlib.util.spec_from_file_location("_ubp", ROOT / "scripts" / "update_buyback_prices.py")
    ubp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ubp)
    t = next(x for x in ubp.TARGET_PRODUCTS if x["product_alias"] == ALIAS)
    assert t["condition"] == "new_unopened_simfree" and t["shops"] == ["kaitori_shouten"]
    assert ALIAS not in ubp.KEEP_PREVIOUS_ON_FAILURE                    # 失敗した日に前回の行を今の価格に見せない
    assert ubp.OFFICIAL_PRICES[ALIAS] == reg.VERIFIED_URLS[PID]["price"]
    assert "kaitori_shouten" in ubp.ROW_MATCHED_SHOPS
    from src.market.buyback_csv_importer import ALIAS_MAP
    assert ALIAS_MAP[ALIAS] == PID


# ── 発見の照合（Phase 28 の登録の後）──────────────────────────────────────

def test_discovery_loop_closure_with_registered_canon(tmp_path):
    y = tmp_path / "products.yaml"
    y.write_text((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    page = '<script>{"products":[' + ",".join(
        f'{{"sku":"{x[:5]}","partNumber":"{x}","price":{{"fullPrice":189800.00}},"category":"iphone",'
        f'"name":"iPhone Air 256GB {col}"}}' for x, col in zip(PARTS, ("Space Black", "Cloud White", "Light Gold",
                                                                        "Sky Blue"))) + "]}</script>"
    pages = {apple.LIST_URL: '<a href="/jp/shop/buy-iphone/iphone-air">x</a>',
             apple.FAMILY_URL.format(slug="iphone-air"): page}
    out = tmp_path / "out"
    s = st.empty()
    cid = apple.candidate_id("iphone air", "256GB")
    st.upsert(s, cid, {"source": apple.SOURCE, "product_name": "iPhone Air 256GB", "match_to_existing": ""},
              status=st.PENDING_REVIEW, now=NOW - timedelta(days=1))
    st.mark_registered(s, cid, now=NOW - timedelta(days=1), target="config/products.yaml", registered_id=PID)
    st.save(out / st.PRODUCT_FILE, s)
    apple.run(out, y, now=NOW, fetch=lambda u: (pages.get(u), "" if u in pages else "not_found"))
    cands = st.load(out / st.PRODUCT_FILE)["candidates"]
    assert cands[cid]["status"] == st.REGISTERED and cands[cid]["match_to_existing"] == PID
    assert len(cands) == 1                                                       # 同じ商品の候補を作り直さない
    assert apple.canonical_iphones(y)[("iphone air", "256GB")] == PID


def test_deploy_check_864_ok_and_catches_reference_only(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_check as dc
    assert dc._check_phase29_activation()[0]["level"] == "ok"
    monkeypatch.setitem(reg.IDENTITY_EVIDENCE, PID, dict(reg.IDENTITY_EVIDENCE[PID], variant_skus={
        "MG274J/A": ("256GB", "Space Black", 189800), "MG2D4J/A": ("512GB", "Cloud White", 189800)}))
    assert dc._check_phase29_activation()[0]["level"] == "error"


# ── 売る側の確定・利益・今すぐ行動（既存の正本の判定だけを使う。UI で計算し直さない）──────────────

def _obs(url="https://www.kaitorishouten-co.jp/products/detail/24681", data_source="auto_scraped", **kw):
    from src.market.normalized_prices import _extraction_method, classify_link_type, make_observation
    base = dict(product_id=PID, product_name="iPhone Air 256GB SIMフリー", source_id="src_kaitori_shouten",
                source_name="買取商店", market_type="domestic_buyback", price_role="sell",
                price_type="buyback_price", condition="new_unopened", price=133000,
                observed_at="2026-10-17T23:22:00+09:00", confidence="high", source_url=url, item_url=url,
                link_type=classify_link_type(url, True, "sell"), extraction_method=_extraction_method(data_source),
                price_context="買取価格")
    base.update(kw)
    return make_observation(NOW, **base)


def test_fresh_row_level_buyback_is_confirmed_sell():
    from src.market.normalized_prices import sell_confirmation_reasons
    assert sell_confirmation_reasons(_obs()) == []


def test_shop_home_stale_used_manual_not_confirmed():
    from src.market.normalized_prices import sell_confirmation_reasons
    assert "sell_url_not_item_level" in sell_confirmation_reasons(_obs(url="https://www.kaitorishouten-co.jp/"))
    assert sell_confirmation_reasons(_obs(observed_at="2026-10-01T09:00:00+09:00"))                    # 14日より古い
    assert "condition_mismatch" in sell_confirmation_reasons(_obs(condition="used_a"))
    assert sell_confirmation_reasons(_obs(data_source="manual_today"))                 # 手入力は照合済みにしない


def _deal(**kw):
    from src.content.ui import opportunity as opp
    from src.market.official_shipping import purchase_shipping
    ship = purchase_shipping(PID, reg.VERIFIED_URLS[PID]["url"], 189800)
    d = {"product_id": PID, "title": "iPhone Air 256GB SIMフリー", "genre": "iphone", "brand": "Apple",
         "official_price": 189800, "sell_price": 133000, "sell_shop": "買取商店",
         "sell_checked_at": "2026-10-17T23:22:00+09:00", "official_checked_at": "2026-10-17T23:21:00+09:00",
         "msrp_evidence": "VERIFIED_CURRENT", "sell_identity_verified": True, "purchase_shipping": ship["fee"],
         "purchase_shipping_status": ship["status"], "condition": "new_unopened",
         "sell_url": "https://www.kaitorishouten-co.jp/products/detail/24681", "user_level": "beginner_watch"}
    d.update(kw)
    v0 = opp.from_deal(d)
    d.setdefault("net_profit", d["sell_price"] - d["official_price"] - sum(a for _l, a in v0.cost_lines))
    return d


def test_today_prices_give_no_profit():
    """2026-10-17: 公式直販 189,800円・買取（最も低い色）133,000円 → 利益は出ない（no_profit が正しい）。"""
    from src.content.ui import opportunity as opp
    d = _deal()
    assert d["net_profit"] < 0 and "no_profit" in opp.deal_reasons(d, NOW)


def test_positive_profit_with_unknown_stock_not_actionable():
    from src.content.ui import opportunity as opp
    from src.market.opportunity_diagnostics import ACTIONABLE_AVAILABILITY
    d = _deal(sell_price=200000, stock_status="")
    assert d["net_profit"] > 0 and opp.deal_reasons(d, NOW) == ()                      # 確定の利益（式は既存の正本）
    v = opp.from_deal(d)
    opp._apply_stock_freshness(v, NOW)
    assert v.availability not in ACTIONABLE_AVAILABILITY                               # 在庫が不明なら行動できない
    from src.market import actionability as act
    a = act.evaluate(profitable=True, identity_ok=True, stock="UNKNOWN", stock_checked_at="", sale_method="normal",
                     buy_url=reg.VERIFIED_URLS[PID]["url"], now=NOW)
    assert a.actionable is False and "stock_unknown" in a.reasons


def test_unknown_shipping_or_unverified_sell_blocks_profit():
    from src.content.ui import opportunity as opp
    assert opp.deal_reasons(_deal(sell_price=200000, purchase_shipping=None, purchase_shipping_status="UNKNOWN"),
                            NOW) != ()                                                 # 送料が分からなければ 0 にしない
    assert "sell_identity_unverified" in opp.deal_reasons(_deal(sell_price=200000, sell_identity_verified=False), NOW)
    assert opp.deal_reasons(_deal(sell_price=200000, msrp_evidence="CONFIGURED_REFERENCE"), NOW) != ()   # 設定値は不可


def test_admin_registered_status_shows_states_without_recalc():
    from src.content.ui import admin
    pc = {"candidates": {"apple-x": {"status": "REGISTERED", "registered_id": PID, "product_name": "iPhone Air 256GB"},
                         "apple-y": {"status": "PENDING_REVIEW", "product_name": "iPhone Duo 256GB"}}}
    diag = {"retail_prices": {"products": [{"product_id": PID, "product": "iPhone Air 256GB SIMフリー",
                                            "evidence": "VERIFIED_CURRENT", "price": 189800}]},
            "candidates": [{"product_id": PID, "route_type": "RETAIL_TO_BUYBACK", "reasons": ["no_profit"]}]}
    rows = admin.build_registered(pc, diag)
    assert rows == [{"product_id": PID, "name": "iPhone Air 256GB SIMフリー", "official": "VERIFIED_CURRENT",
                     "official_price": 189800, "buyback": "取得あり", "profit": "利益なし（no_profit）"}]
    diag["candidates"] = [{"product_id": PID, "route_type": "RETAIL_TO_BUYBACK", "reasons": ["no_sell_price"]}]
    assert admin.build_registered(pc, diag)[0]["buyback"] == "未取得"
    diag["candidates"] = [{"product_id": PID, "route_type": "RETAIL_TO_BUYBACK", "reasons": ["no_profit"]},
                          {"product_id": PID, "route_type": "SHOP_TO_BUYBACK", "reasons": ["no_sell_price"]}]
    r = admin.build_registered(pc, diag)[0]
    assert (r["buyback"], r["profit"]) == ("取得あり", "利益なし（no_profit）")           # 別のルートで上書きしない
    diag["candidates"] = []                                                              # 診断で除外の理由なし = 確定
    r = admin.build_registered(pc, diag)[0]
    assert (r["buyback"], r["profit"]) == ("取得あり", "確定（診断で除外の理由なし）")
    diag["retail_prices"]["products"][0]["evidence"] = "CONFIGURED_REFERENCE"           # 公式が設定値なら確定と出さない
    assert admin.build_registered(pc, diag)[0]["profit"] != "確定（診断で除外の理由なし）"
    diag["retail_prices"]["products"][0]["evidence"] = "VERIFIED_CURRENT"
    html = admin._discovery({"registered": admin.build_registered(pc, diag), "metrics": {}})
    assert "発見から登録した商品の状態" in html and "<button" not in html


def test_search_blob_covers_name_capacity_and_part_numbers():
    p = product()
    blob = " ".join([p["name"], *p["keywords"]]).lower()
    for q in ("iphone air", "256gb", "mg274j/a", "mg2a4j/a"):
        assert q in blob
