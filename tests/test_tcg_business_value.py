# -*- coding: utf-8 -*-
"""TCG Business Value: 抽選→商品の紐付け・公式ページで確認した商品台帳・応募優先度の HOME 反映の不変条件。"""
import json
from datetime import datetime, timedelta

import pytest

from src.tcg import verified_products as vp
from src.tcg.hub import product_view as pv
from src.tcg.lottery.products import resolve_product
from src.tcg.models import JST

REG = [
    {"product_id": "pokemon-拡張パック-ハドウシーカー", "name": "拡張パック「ハドウシーカー」"},
    {"product_id": "pokemon-拡張パック-30th-celebration", "name": "拡張パック「30th CELEBRATION」"},
    {"product_id": "pokemon-premium-deck", "name": "「30th CELEBRATION プレミアムデッキセット エーフィ・ブラッキー」"},
    {"product_id": "pokemon-cardset-1", "name": "「30th CELEBRATION カードセット ニャオハ・ホゲータ・クワッス」"},
    {"product_id": "pokemon-cardset-2", "name": "「30th CELEBRATION カードセット サルノリ・ヒバニー・メッソン」"},
]
OP = [
    {"product_id": "op18", "name": "ブースターパック 神の支配【OP-18】"},
    {"product_id": "eb05", "name": "エクストラブースター ONE PIECE Heroines Edition vol.2【EB-05】"},
    {"product_id": "heroines-box", "name": "ONE PIECEカードゲーム ONE PIECE HEROINES PRECIOUS BOX"},
]


def m(name, reg=REG):
    return resolve_product(name, reg)


@pytest.mark.parametrize("name", [
    "ポケモンカードゲーム MEGA 拡張パック「ハドウシーカー」（1BOX）",
    "ポケモンカードゲーム MEGA 拡張パック ハドウシーカー（BOX）",
    "ポケモンカードゲーム MEGA 拡張パック ハドウシーカー(シュリンクなし)",
    "ポケモンカードゲーム MEGA 拡張パック ハドウシーカーの追加抽選販売について",
    "ポケモンカードゲーム MEGA『拡張パック 30th CELEBRATION』" if False else "ポケモンカードゲーム MEGA 拡張パック ハドウシーカー（再販）",
])
def test_store_wording_noise_does_not_prevent_an_exact_match(name):
    r = m(name)
    assert r["product_match"] == "exact" and r["product_id"] == "pokemon-拡張パック-ハドウシーカー"


@pytest.mark.parametrize("name", [
    "ポケモンカードゲーム MEGA『拡張パック 30th CELEBRATION』",
    "ポケモンカードゲーム MEGA 拡張パック「30th CELEBRATION",          # 閉じ括弧が欠けたタイトル切れ
    "ポケモンカードゲーム MEGA ・拡張パック 30th CELEBRATION 20パック",
])
def test_quote_variants_and_truncation_still_match_the_same_product(name):
    r = m(name)
    assert r["product_match"] == "exact" and r["product_id"] == "pokemon-拡張パック-30th-celebration"


@pytest.mark.parametrize("name", ["【ポケモンカードゲーム】再販品", "【ワンピースカードゲーム】再入荷商品", "再販品", ""])
def test_generic_titles_never_match(name):
    r = m(name, REG + OP)
    assert r["product_id"] is None and r["product_match"] == "none"


def test_multi_product_and_series_only_titles_are_not_exact():
    assert m("ポケモンカードゲームMEGA 30th CELEBRATION カードセット9種（再販）")["product_id"] is None
    r = m("30th CELEBRATION 1BOX")                       # 拡張パックか FUTURISTIC BOX か決まらない
    assert r["product_id"] is None and r["product_match"] in ("ambiguous", "partial")


def test_kind_mismatch_is_never_matched():
    # 拡張パックの名前を、同じ名前を持つデッキに紐付けない
    reg = [{"product_id": "deck", "name": "スターターセット ハドウシーカー"}]
    r = m("拡張パック「ハドウシーカー」", reg)
    assert r["product_id"] is None


def test_unquoted_name_without_a_kind_word_is_not_exact():
    # 名前の本体は一致していても、「」も種別語も無ければ別商品の可能性があるので確定しない
    r = m("ハドウシーカー")
    assert r["product_id"] is None


def test_product_code_matches_exactly_and_only_with_one_candidate():
    assert m("ONE PIECE Heroines Edition vol.2【EB-05】", OP)["product_id"] == "eb05"
    assert m("ワンピースカードゲーム『エクストラブースター ONE PIECE Heroines Edition vol.2【EB-05】』", OP)["product_id"] == "eb05"
    assert m("ONEPIECEカードゲーム ブースターパック 神の支配【OP-18】", OP)["product_id"] == "op18"
    assert m("ブースターパック【OP-99】", OP)["product_id"] is None         # 知らないコードは紐付けない
    dup = OP + [{"product_id": "eb05b", "name": "別のEB-05【EB-05】"}]
    assert m("【EB-05】", dup)["product_match"] == "ambiguous"                # 同じコードが複数なら確定しない


def test_different_one_piece_products_do_not_cross_match():
    r = m("エクストラブースター ONE PIECE Heroines Edition vol.2", OP)
    assert r["product_id"] == "eb05"                                         # BOX（HEROINES PRECIOUS BOX）に流れない
    r = m("ONE PIECE HEROINES PRECIOUS BOX", OP)                         # 種別語も「」も無い名前だけの一致は確定しない（PROBABLE 止まり）
    assert r["product_id"] is None and r["product_match"] == "partial"
    assert m("ONE PIECEカードゲーム ONE PIECE HEROINES PRECIOUS BOX【プレミアム】", OP)["product_id"] != "eb05"


# ── 公式ページで確認した商品の台帳 ───────────────────────────────────────

def test_verified_products_file_rows_are_all_valid_and_well_formed():
    doc = json.loads(vp.PATH.read_text(encoding="utf-8"))
    rows = doc["products"]
    assert rows and len(vp.load()) == len(rows)                              # 検証を通らない行が無い
    ids = [r["product_id"] for r in rows]
    assert len(ids) == len(set(ids))
    for r in rows:
        assert r["evidence"]["source_url"].startswith("https://") and r["evidence"]["checked_on"]
        host = r["official_url"].split("/")[2]
        assert host in ("www.pokemon-card.com", "www.onepiece-cardgame.com", "www.30th.pokemon-card.com"), host
        if r["retail_price_basis"] == "pack":
            assert r["retail_price"] is None and r["pack_price"]            # BOX の定価をパック価格から作らない


def test_load_drops_rows_without_evidence_or_with_a_pack_price_as_msrp(tmp_path):
    base = {"product_id": "x", "name": "N", "tcg": "ONE_PIECE", "official_url": "https://www.onepiece-cardgame.com/products/x.html",
            "retail_price_basis": "product_unit", "retail_price": 1000,
            "evidence": {"source_url": "https://www.onepiece-cardgame.com/products/x.html", "checked_on": "2026-11-21"}}
    bad_evidence = {**base, "product_id": "y", "evidence": {}}
    pack_as_msrp = {**base, "product_id": "z", "retail_price_basis": "pack"}
    http_only = {**base, "product_id": "w", "official_url": "http://example.com/"}
    unknown_tcg = {**base, "product_id": "v", "tcg": "YUGIOH"}
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"products": [base, bad_evidence, pack_as_msrp, http_only, unknown_tcg]}), encoding="utf-8")
    assert [r["product_id"] for r in vp.load(p)] == ["x"]
    assert vp.load(tmp_path / "missing.json") == []


def test_merge_prefers_the_official_api_row_and_marks_manual_rows():
    api = [{"product_id": "op18", "name": "API の行", "tcg": "ONE_PIECE"}]
    ver = [{"product_id": "op18", "name": "台帳", "tcg": "ONE_PIECE", "manual_verified": True},
           {"product_id": "eb05", "name": "台帳2", "tcg": "ONE_PIECE", "manual_verified": True}]
    out = vp.merge(api, ver)
    assert [r["name"] for r in out] == ["API の行", "台帳2"]
    assert vp.is_manual(out[1]) and not vp.is_manual(out[0])


def test_msrp_marks_the_source_of_a_manual_row():
    from src.tcg.msrp import build_msrp
    reg = [{"product_id": "box", "name": "BOX", "tcg": "ONE_PIECE", "retail_price": 8470, "retail_price_basis": "product_unit",
            "official_url": "https://www.onepiece-cardgame.com/products/heroines-box.html", "manual_verified": True},
           {"product_id": "pack", "name": "P", "tcg": "ONE_PIECE", "retail_price": None, "retail_price_basis": "pack", "pack_price": 240,
            "official_url": "https://www.onepiece-cardgame.com/products/eb05.html", "manual_verified": True}]
    ms = build_msrp(reg, "2026-11-21T00:00:00+09:00")
    assert [v["product_id"] for v in ms["verified"]] == ["box"] and ms["verified"][0]["source"] == "official_page"
    assert ms["excluded"][0]["reason"] == "PACK_PRICE_ONLY"                    # パック価格から BOX の定価を作らない


# ── ハブ・HOME への反映 ──────────────────────────────────────────────

def _lot(**kw):
    ev = {"lottery_id": "l1", "tcg": "ONE_PIECE", "retailer_name": "店", "product_name": "EB-05", "product_id": "eb05",
          "product_match": "exact", "verified": True, "conflict": False, "source_type": "OFFICIAL_RETAILER_PAGE",
          "application_start": "2026-11-20T10:00:00+09:00", "application_end": "2026-11-22T23:59:00+09:00",
          "entry_url": "https://example.com/entry", "source_url": "https://example.com/s"}
    ev.update(kw)
    return ev


def test_hub_product_shows_the_one_piece_master_and_pack_price_but_no_invented_profit():
    reg = {"generated_at": "2026-11-21T00:00:00+09:00", "products": vp.load()}
    hub = pv.build_hub({"items": [_lot(product_id="ブースターパック-神の支配-op-18")]}, reg, {"verified": []},
                       datetime(2026, 11, 21, 12, 0, tzinfo=JST))
    p = next(x for x in hub["products"] if x["product_id"] == "ブースターパック-神の支配-op-18")
    assert p["canonical"] == pv.C_MASTER and p["release_date"] == "2026-11-21" and p["pack_price"] == 240
    assert p["profit"]["msrp"] is None and p["profit"]["net_profit"] is None and p["profit"]["roi_pct"] is None
    assert hub["stats"]["bind_rate"] == 1.0


def test_probable_or_unmatched_events_are_not_counted_as_bound():
    hub = pv.build_hub({"items": [_lot(product_match="partial", product_id=None), _lot(lottery_id="l2", product_match="none", product_id=None),
                                  _lot(lottery_id="l3", product_match="ambiguous", product_id=None)]},
                       {"products": vp.load()}, {"verified": []}, datetime(2026, 11, 21, 12, 0, tzinfo=JST))
    assert hub["stats"]["bound_exact"] == 0 and hub["stats"]["bind_rate"] == 0.0
    assert all(v["priority"] in (None, "WATCH") for v in hub["events"])      # 未紐付けは強い応募推奨にしない


def test_home_priority_uses_the_hub_rule_and_never_promotes_unverified():
    from src.content.ui.home_feed import _lottery_priority
    now = datetime(2026, 11, 22, 12, 0, tzinfo=JST)
    ev = _lot()
    assert _lottery_priority(ev, now) in ("S", "A", "B")                # 紐付け済み・確認済みは WATCH にならない
    assert _lottery_priority({**ev, "verified": False}, now) == "WATCH"
    assert _lottery_priority({**ev, "product_match": "partial", "product_id": None}, now) == "WATCH"
    assert _lottery_priority("壊れた入力", now) is None


def test_lottery_card_shows_the_priority_badge_only_for_s_and_a():
    from src.content.ui import lottery_card as lc
    assert "優先 S" in lc._prio_badge({"prio": "S"}) and "優先 A" in lc._prio_badge({"prio": "A"})
    assert lc._prio_badge({"prio": "WATCH"}) == "" and lc._prio_badge({}) == ""


def test_manual_msrp_row_keeps_its_own_check_date_not_the_run_date():
    from src.tcg.msrp import build_msrp
    reg = [{"product_id": "box", "name": "BOX", "tcg": "ONE_PIECE", "retail_price": 8470, "retail_price_basis": "product_unit",
            "official_url": "https://www.onepiece-cardgame.com/products/heroines-box.html", "manual_verified": True,
            "evidence": {"source_url": "https://www.onepiece-cardgame.com/products/heroines-box.html", "checked_on": "2026-11-21"}},
           {"product_id": "api", "name": "API", "tcg": "POKEMON", "retail_price": 6000, "retail_price_basis": "product_unit",
            "official_url": "https://www.pokemon-card.com/ex/m9/"}]
    ms = build_msrp(reg, "2026-12-25T03:00:00+09:00")
    rows = {v["product_id"]: v for v in ms["verified"]}
    assert rows["box"]["checked_at"] == "2026-11-21"                           # 再確認していない台帳の日付を進めない
    assert rows["api"]["checked_at"] == "2026-12-25T03:00:00+09:00"            # 公式 API の行は取得した日


def test_unverified_open_lottery_does_not_make_the_product_look_open():
    reg = {"products": vp.load()}
    ev = _lot(product_id="ブースターパック-神の支配-op-18", verified=False)
    hub = pv.build_hub({"items": [ev]}, reg, {"verified": []}, datetime(2026, 11, 21, 12, 0, tzinfo=JST))
    p = next(x for x in hub["products"] if x["product_id"] == "ブースターパック-神の支配-op-18")
    assert p["counts"]["open"] == 0 and p["counts"]["ending_soon"] == 0 and p["status"] != "OPEN"
    ok = pv.build_hub({"items": [_lot(product_id="ブースターパック-神の支配-op-18")]}, reg, {"verified": []},
                      datetime(2026, 11, 21, 12, 0, tzinfo=JST))
    q = next(x for x in ok["products"] if x["product_id"] == "ブースターパック-神の支配-op-18")
    assert q["counts"]["open"] + q["counts"]["ending_soon"] == 1               # 確認済みなら数える


def test_quantity_that_distinguishes_a_product_is_kept():
    reg = [{"product_id": "set2", "name": "カードセット「ニャオハ 2種」"}]
    assert m("カードセット「ニャオハ 2種」", reg)["product_id"] == "set2"
    assert m("カードセット「ニャオハ 1種」", reg)["product_id"] is None
    assert m("カードセット「ニャオハ 3種」", reg)["product_id"] is None


def test_product_code_does_not_override_a_different_kind():
    assert m("【OP-18】スタートデッキ", OP)["product_id"] is None             # コードが同じでも種別が違えば別商品
    assert m("ブースターパック 神の支配【OP-18】", OP)["product_id"] == "op18"


@pytest.mark.parametrize("name", [
    "ポケモンカードゲーム「ハドウシーカー」ハイクラスパック",          # パックの種類違い（拡張パックではない）
    "拡張パック ハドウシーカー 1パック",                              # 1 パックは BOX 商品ではない
    "拡張パック ハドウシーカー バラパック",
    "「ハドウシーカー」拡張パック プロモーションパック",
    "拡張パック ハドウシーカー ミニ",
])
def test_pack_variants_never_match_the_box_product(name):
    assert m(name)["product_match"] != "exact"


def test_variant_words_must_agree_with_the_registry_name():
    r = m("ブースターパック 神の支配【OP-18】 ドン!!カード付きセット", REG + OP)
    assert r["product_match"] != "exact"
    assert m("ワンピースカードゲーム「ONE PIECE Heroines Edition vol.2」プレシャスBOX", REG + OP)["product_match"] != "exact"
    r = m("ワンピースカードゲーム「ONE PIECE HEROINES PRECIOUS BOX」", REG + OP)
    assert r["product_id"] != "eb05"


@pytest.mark.parametrize("name", ["「30th CELEBRATION」", "「ハドウシーカー」", "ポケモンカードゲーム 「ハドウシーカー」"])
def test_quote_alone_is_not_enough_for_exact(name):
    assert m(name)["product_match"] != "exact"
