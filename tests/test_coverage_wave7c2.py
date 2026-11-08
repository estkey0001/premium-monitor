"""Wave 7c-2: Sony α7CR・Sony FX3・Canon EOS R3 の公式ページの人手確認（2026-11-08）の登録を固定する。

- α7CR: ソニーストアの購入ページ（ILCE-7CR・ボディのみ・449,900円(税込)・翌日出荷）。送料・JAN は購入ページに無いので確定の仕入れ値には使わない
- FX3（ILME-FX3）: ソニーの製品ページが「生産完了」「ソニーストアでの販売は終了」。後継の ILME-FX3A は別型番
- EOS R3: キヤノンオンラインショップの購入ページが「【販売終了】」。表示の 792,000円は仕入れ値にしない
いきなり確定・actionable・通知に昇格させない（既存の関門の判定をそのまま使う）。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from src.market import official_registry as reg
from src.market import official_shipping as osh

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = {p["id"]: p for p in yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))["products"]}
SONY_HOST = "https://pur.store.sony.jp/"


def test_a7cr_is_registered_from_the_official_sony_store_page_with_the_current_price():
    v = reg.VERIFIED_URLS["prod_a7cr"]
    assert v["source"] == "src_sony_store" and v["url"] == SONY_HOST + "ichigan/products/ILCE-7CR/ILCE-7CR_purchase/"
    assert v["price"] == 449900 and v["price_kind"] == "official_direct" and v["checked_on"] == "2026-11-08"
    assert reg.price_kind_of("prod_a7cr") == "official_direct"
    o = reg.OFFICIAL_DIRECT_OFFERS["prod_a7cr"]
    assert o["price"] == 449900 and o["body_kit"] == "body" and o["sale_mode"] == "NORMAL" and o["url"] == v["url"]
    assert o["stock"] == "UNKNOWN"                                   # 「翌日出荷」の表示だけでは在庫ありにしない
    assert "クーポン" in o["stock_semantics"] and "含めない" in o["stock_semantics"]       # クーポン・カードの割引は価格に含めない
    assert reg.UNVERIFIED.get("prod_a7cr") is None                   # 「要手動検証」の一覧から外れた


def test_a7cr_identity_is_confirmed_by_the_exact_model_code_only_and_no_jan_is_invented():
    p = PRODUCTS["prod_a7cr"]
    assert reg.identity_state(p)[0] == "IDENTITY_CONFIRMED" and "ILCE-7CR" in reg.identity_state(p)[1]
    ev = reg.IDENTITY_EVIDENCE["prod_a7cr"]
    assert ev["model_number"] == "ILCE-7CR" and "jan_code" not in ev and ev["bundle"] == "ボディーのみ"
    assert not p.get("jan_code")                                    # 公式の購入ページに JAN の表示が無い。作らない
    wrong = dict(p, model_number="ILCE-7RM5")                      # 別の型番では確認済みにならない
    assert reg.identity_state(wrong)[0] == "PARTIAL_IDENTITY"


def test_a7cr_official_price_is_not_a_confirmed_cost_without_jan_and_shipping():
    """価格が確認できても、JAN と送料が確認できないので、既存の関門は参考のまま（確定・actionable・通知に昇格しない）。"""
    ok, why = reg.official_direct_gate("prod_a7cr", PRODUCTS["prod_a7cr"], "2026-11-08")
    assert ok is False and set(why) == {"jan_not_exact", "shipping_unknown"}
    s = osh.purchase_shipping("prod_a7cr", reg.VERIFIED_URLS["prod_a7cr"]["url"], 449900)
    assert s["fee"] is None and s["status"] == osh.UNKNOWN          # 送料は購入ページに表示が無い。0 円・550 円と推測しない
    assert "prod_a7cr" not in osh.PRODUCT_SHIPPING


def test_fx3_is_recorded_as_not_sold_and_the_successor_model_is_not_confused():
    n = reg.OFFICIAL_NOT_SOLD["prod_fx3"]
    assert n["checked_on"] == "2026-11-08" and n["source"] == "src_sony_store"
    assert "ILME-FX3A" in n["reason"] and "別型番" in n["reason"]
    assert "prod_fx3" not in reg.VERIFIED_URLS and "prod_fx3" not in reg.OFFICIAL_DIRECT_OFFERS     # 販売終了の商品に価格を付けない
    assert reg.identity_state(PRODUCTS["prod_fx3"])[0] == "DISCONTINUED"
    assert PRODUCTS["prod_fx3"]["model_number"] == "ILME-FX3"          # 登録は元の型番のまま。ILME-FX3A に書き換えない
    assert reg.UNVERIFIED.get("prod_fx3") is None
    assert reg.official_direct_gate("prod_fx3", PRODUCTS["prod_fx3"], "2026-11-08")[0] is False


def test_r3_is_recorded_as_not_sold_and_the_leftover_displayed_price_is_not_used():
    n = reg.OFFICIAL_NOT_SOLD["prod_r3"]
    assert n["checked_on"] == "2026-11-08" and n["source"] == "src_canon_official"
    assert "販売終了" in n["reason"] and "4895C001" in n["reason"] and "仕入れ値にしない" in n["reason"]
    assert "prod_r3" not in reg.VERIFIED_URLS and "prod_r3" not in reg.OFFICIAL_DIRECT_OFFERS
    assert reg.identity_state(PRODUCTS["prod_r3"])[0] == "DISCONTINUED"
    assert reg.UNVERIFIED.get("prod_r3") is None
    assert reg.official_direct_gate("prod_r3", PRODUCTS["prod_r3"], "2026-11-08")[0] is False


def test_registered_urls_are_official_domains_only_and_checked_on_is_the_human_verification_day():
    from src.market.official_price_validator import is_official_domain
    for pid in ("prod_a7cr",):
        assert is_official_domain(reg.VERIFIED_URLS[pid]["url"], reg.VERIFIED_URLS[pid]["source"]) or reg.VERIFIED_URLS[pid]["url"].startswith(SONY_HOST)
    for pid in ("prod_a7cr", "prod_fx3", "prod_r3"):
        rec = reg.VERIFIED_URLS.get(pid) or reg.OFFICIAL_NOT_SOLD[pid]
        assert rec["checked_on"] == "2026-11-08"                    # 人が実際にページを開いて確認した日（実行日で更新しない）


def test_other_registered_products_are_unchanged():
    assert reg.VERIFIED_URLS["prod_a7rv"]["price"] == 533500 and reg.VERIFIED_URLS["prod_a1ii"]["price"] == 990000
    assert reg.VERIFIED_URLS["prod_r6ii"]["price"] == 319000 and reg.VERIFIED_URLS["prod_r5ii"]["price"] == 654500
    assert osh.PRODUCT_SHIPPING["prod_a7rv"]["fee"] == 550          # α7CR の送料（未確認）に、α7R V の 550 円を流用していない


def test_recheck_parser_reads_the_real_a7cr_purchase_page_layout_with_color_suffixes():
    """実ページ（2026-11-08）は「ILCE-7CR/S（シルバー） 翌日出荷 449,900円(税込) ILCE-7CR/B（ブラック） 翌日出荷 449,900円(税込)」。
    色の型番と色名が付いても価格を読む（再確認が毎回失敗しない）。色ごとの価格が食い違えば読まない。別の型番は読まない。"""
    from scripts import recheck_official as R
    page = "α7CRを購入 ボディのみ ILCE-7CR/S（シルバー） 翌日出荷 449,900円(税込) ILCE-7CR/B（ブラック） 翌日出荷 449,900円(税込) 付属品"
    r = R.parse_sony_store(page, "ILCE-7CR")
    assert r["price"] == 449900 and r["stock"] and not r["ended"] and r["model_found"]
    assert R.parse_sony_store(page.replace("ILCE-7CR/B（ブラック） 翌日出荷 449,900", "ILCE-7CR/B（ブラック） 翌日出荷 459,900"), "ILCE-7CR")["price"] is None
    assert R.parse_sony_store(page, "ILCE-7RM5")["price"] is None and R.parse_sony_store(page, "ILCE-7C")["price"] is None
    assert R.parse_sony_store("ILCE-7RM5 翌日出荷 533,500 円(税込)", "ILCE-7RM5")["price"] == 533500       # 従来の並びは変わらない
