# -*- coding: utf-8 -*-
"""TCG: 販売店の BOX 実販売価格の台帳 → 条件付きの利益。公式定価と別ラベル・抽選終了は参考のみ・実行可能にならない。"""
import re
from datetime import timedelta

import pytest

from src.content import tcg_hub_page as page_mod
from src.tcg import buyback as bb
from src.tcg import retailer_box as rb
from src.tcg.hub import product_view as pv
from tests.test_tcg_buyback import CFG, NOW, art, page

REG = {"products": [{"product_id": "box", "tcg": "POKEMON", "name": "拡張パック BOX", "product_type": "EXPANSION_PACK",
                     "release_date": "2026-01-01T00:00:00+09:00", "official_url": "https://www.pokemon-card.com/x"}]}


def ent(**kw):
    e = {"id": "t1", "product_id": "box", "tcg": "POKEMON", "retailer": "店", "shop": "テスト店", "unit": "BOX", "box_condition": "UNKNOWN",
         "price_jpy": 6000, "price_basis": rb.BASIS_OK, "sale_method": "LOTTERY",
         "apply_end": (NOW + timedelta(days=1)).isoformat(), "purchase_start": (NOW + timedelta(days=10)).strftime("%Y-%m-%d"),
         "purchase_end": (NOW + timedelta(days=16)).strftime("%Y-%m-%d"), "shipping": "店頭受取のみ",
         "source_url": "https://shop.example/x", "verified_at": "2026-11-21", "jan": None, "human_confirmed": False}
    e.update(kw)
    return e


def hub(entries, sell=9000, now=NOW, msrp=(), reg=REG, action=None):
    kw = {} if action is None else {"action": action}
    rows = [{**r, "page_asof": NOW.isoformat()} for r in bb.parse_rudeya(page(art("拡張パック BOX", sell, "4500000000222", **kw)), "u", NOW)["rows"]]
    import src.tcg.buyback as m
    orig = m.load_config
    m.load_config = lambda *a, **k: CFG
    try:
        return pv.build_hub({"items": []}, reg, {"verified": list(msrp)}, now, {"rows": rows}, retailer_rows=entries)
    finally:
        m.load_config = orig


def test_open_lottery_price_gives_conditional_profit_with_separate_label():
    h = hub([ent()])
    assert h["opportunities"] == []                                     # 公式定価の候補には入らない
    o = h["retailer_opportunities"][0]
    assert o["source_kind"] == "retailer_box_price" and o["conditional"] is True and o["executable"] is False
    assert o["state"] == pv.O_CONDITIONAL and o["profit"]["net_profit"] == 3000 and o["profit"]["msrp"] is None
    assert "当選した場合のみ" in o["condition"] and o["retailer"]["accept_state"] == "OPEN" and o["retailer"]["verified_at"] == "2026-11-21"
    html = page_mod.render(h)
    sec = html[html.index('id="retailer-box"'):html.index('id="page-foot"')]
    assert "販売店価格" in sec and "条件付き" in sec and "当選時のみ" in sec and "公式定価" not in sec       # メーカー定価と混ぜない・当選した場合だけの条件付き
    assert 'class="sb ok"' not in sec                                    # 緑の購入推奨バッジにしない
    assert "data-fb-live" in sec and "data-fb-stale" in sec and "data-rb-until" in sec


def test_conditional_is_never_actionable_or_home():
    import inspect
    o = hub([ent()])["retailer_opportunities"][0]
    assert o["executable"] is False and o["state"] not in (pv.O_PROFIT, pv.O_WATCH)
    assert "retailer" not in inspect.getsource(pv.profit_map)
    assert "BUY" not in page_mod.render(hub([ent()])).split('id="retailer-box"')[1].split('id="page-foot"')[0]


@pytest.mark.parametrize("kw,state", [
    ({"apply_end": (NOW - timedelta(days=1)).isoformat(), "purchase_start": (NOW + timedelta(days=1)).strftime("%Y-%m-%d")}, "WINNERS_ONLY"),
    ({"apply_end": None, "purchase_start": (NOW - timedelta(days=1)).strftime("%Y-%m-%d")}, "WINNERS_ONLY"),
    ({"apply_end": (NOW - timedelta(days=30)).isoformat(), "purchase_end": (NOW - timedelta(days=1)).strftime("%Y-%m-%d")}, "CLOSED"),
    ({"apply_end": None, "purchase_start": None, "purchase_end": None}, "UNKNOWN"),
    ({"sale_method": "NORMAL"}, "UNKNOWN"),
    ({"apply_start": (NOW + timedelta(hours=1)).isoformat()}, "UNKNOWN"),
])
def test_ended_or_unknown_is_reference_only_without_profit(kw, state):
    h = hub([ent(**kw)])
    assert h["retailer_opportunities"] == []
    r = h["retailer_references"][0]
    assert r["accept_state"] == state and r["kind"] == "REFERENCE_ONLY" and r["executable"] is False
    assert "net_profit" not in r and "過去の参考情報" in page_mod._rb_refs(h["retailer_references"])
    assert "過去の参考情報" not in page_mod.render(h)                     # 運用者向けの参考情報は公開ページに出さない


def test_state_is_derived_from_now_not_stored():
    e = ent()
    assert rb.accept_state({**e, "accept_state": "CLOSED"}, NOW) == rb.S_OPEN             # 保存値は無視
    assert rb.accept_state(e, NOW + timedelta(days=2)) == rb.S_WINNERS
    assert rb.accept_state(e, NOW + timedelta(days=30)) == rb.S_CLOSED
    assert hub([e], now=NOW + timedelta(days=2))["retailer_opportunities"] == []


def test_date_only_apply_end_is_valid_until_end_of_that_day():
    e = ent(apply_end="2026-11-21")
    assert rb.accept_state(e, NOW.replace(hour=23, minute=59)) == rb.S_OPEN
    assert rb.accept_state(e, NOW + timedelta(days=1)) == rb.S_WINNERS


def test_product_id_mismatch_is_not_adopted():
    h = hub([ent(product_id="unknown-product")])
    assert h["retailer_opportunities"] == [] and h["retailer_references"][0]["kind"] == "REJECTED"
    assert "マスタに無い" in h["retailer_references"][0]["reason"]


@pytest.mark.parametrize("kw", [{"price_basis": "pack_x_count"}, {"derived_from_pack": True}, {"pack_price": 240, "packs": 20}, {"unit": "PACK"},
                                {"price_jpy": 0}, {"source_url": "http://x"}, {"verified_at": None}])
def test_pack_derived_or_invalid_price_is_rejected(kw):
    h = hub([ent(**kw)])
    assert h["retailer_opportunities"] == [] and h["retailer_references"][0]["kind"] == "REJECTED"


def test_official_msrp_wins_and_is_not_overwritten_by_retailer_price():
    msrp = [{"product_id": "box", "tcg": "POKEMON", "product_type": "EXPANSION_PACK", "retail_price": 5400, "price_text": "5,400円",
             "basis": "product_unit", "checked_at": NOW.isoformat(), "official_url": "https://www.pokemon-card.com/x"}]
    h = hub([ent()], msrp=msrp)
    assert h["retailer_opportunities"] == [] and [o["product_id"] for o in h["opportunities"]] == ["box"]
    assert h["opportunities"][0]["profit"]["acquisition_cost"] == 5400


def test_stale_or_stopped_buyback_shows_no_profit():
    for kw in ({"now": NOW + timedelta(days=3)}, {"action": '<span class="product-card-stopped">お申込一時停止中</span>'}):
        h = hub([ent(apply_end=(NOW + timedelta(days=9)).isoformat())], **kw)
        assert h["retailer_opportunities"] == []
        assert h["retailer_references"][0]["kind"] == "NOT_CALCULATED"


def test_unknown_cost_is_not_zero(monkeypatch):
    cfg = {**CFG, "route_costs": {"store_counter": {**CFG["route_costs"]["store_counter"], "outbound_shipping_yen": None}}}
    import src.tcg.buyback as m
    monkeypatch.setattr(m, "load_config", lambda *a, **k: cfg)
    rows = [{**r, "page_asof": NOW.isoformat()} for r in bb.parse_rudeya(page(art("拡張パック BOX", 9000, "4500000000222")), "u", NOW)["rows"]]
    h = pv.build_hub({"items": []}, REG, {"verified": []}, NOW, {"rows": rows}, retailer_rows=[ent()])
    assert h["retailer_opportunities"] == [] and h["retailer_references"][0]["kind"] == "NOT_CALCULATED"


def test_real_ledger_is_well_formed():
    rows = rb.load_ledger()
    assert len(rows) == 4
    import json
    from pathlib import Path
    reg = json.loads((Path(__file__).resolve().parent.parent / "exports/tcg/pokemon_registry.json").read_text(encoding="utf-8"))
    master = {(p["tcg"], p["product_id"]): p for p in reg["products"]}
    for e in rows:
        assert rb.validate(e, master) is None and e["jan"] is None and e["box_condition"] == "UNKNOWN" and e["human_confirmed"] is False
        assert e["unit"] == "BOX" and e["price_basis"] == rb.BASIS_OK
    assert {e["price_jpy"] for e in rows} == {6000, 5760}


def test_msrp_json_does_not_contain_retailer_prices():
    import json
    from pathlib import Path
    ms = json.loads((Path(__file__).resolve().parent.parent / "exports/tcg/msrp.json").read_text(encoding="utf-8"))
    ids = {e["product_id"] for e in rb.load_ledger()}
    assert not any(v.get("product_id") in ids for v in ms["verified"])


def test_review_m2_static_label_carries_the_deadline_and_is_replaced_when_expired():
    html = page_mod.render(hub([ent()]))
    sec = html[html.index('id="retailer-box"'):html.index('id="page-foot"')]
    assert "data-rb-open" in sec and "締切 " in sec                                       # JS 無効でも期限が読める
    assert "data-rb-expired hidden>応募期限を過ぎました</span>" in sec                     # 期限後は JS で表示が置き換わる
    assert ".rb-expired [data-rb-open]{display:none!important}" in html


def test_apply_deadline_uses_actual_time_or_end_of_day():
    from src.content import tcg_hub_page as hub
    assert hub._apply_deadline("2026-11-30") == "2026-11-30 23:59"
    assert hub._apply_deadline("2026-11-30T21:00:00+09:00") == "2026-11-30 21:00"
    assert hub._apply_deadline("2026-11-30 18:30") == "2026-11-30 18:30"


# ---------------------------------------------------------------- 第 2 回レビュー（L5 / L6 / Auditor L4）
def _kind(e, now=NOW):
    return rb.classify(e, REG_MASTER, now)


REG_MASTER = {("POKEMON", "box"): {"product_id": "box"}}


@pytest.mark.parametrize("bad", ["来週", "2026/11/20", "not-a-date", "13月"])
def test_review_l5_unparseable_apply_start_is_not_open(bad):
    c = _kind(ent(apply_start=bad))
    assert c["accept_state"] == rb.S_UNKNOWN and c["kind"] == rb.K_REFERENCE
    assert _kind(ent())["kind"] == rb.K_CONDITIONAL                              # 開始日が無い行は従来どおり


@pytest.mark.parametrize("bad", ["先日", "2026/11/21", "2026-13-40", "2099-01-01"])
def test_review_l5_verified_at_must_be_a_past_iso_date(bad):
    c = _kind(ent(verified_at=bad))
    assert c["kind"] == "REJECTED"
    assert rb.validate(ent(verified_at="2026-11-21"), REG_MASTER, NOW) is None


def test_review_l5_old_price_check_is_reference_even_if_open():
    old = (NOW - timedelta(days=15)).strftime("%Y-%m-%d")
    c = _kind(ent(verified_at=old))
    assert c["accept_state"] == rb.S_OPEN and c["kind"] == rb.K_REFERENCE and "14" in c["reason"]
    edge = (NOW - timedelta(days=14)).strftime("%Y-%m-%d")
    assert _kind(ent(verified_at=edge))["kind"] == rb.K_CONDITIONAL
    h = hub([ent(verified_at=old)])
    assert h["retailer_opportunities"] == [] and h["retailer_references"][0]["kind"] == rb.K_REFERENCE


def _ops(h) -> str:
    """運用者向けの描画（参考情報・台帳との食い違い）。公開ページ（render）には出さない（test_tcg_cards.test_public_page_has_no_operator_diagnostics）。"""
    return page_mod._rb_refs(h.get("retailer_references") or []) + page_mod._rb_mismatch(h.get("retailer_validation_errors") or [])


def test_review_l6_rejected_reference_hides_price_and_shows_names():
    rej = ent(id="r1", price_basis="pack_x", price_jpy=7200, derived_from_pack=True)
    unknown = ent(id="r2", product_id="zzz-unknown", price_jpy=8800)
    h = hub([rej, unknown, ent(id="r3", apply_end="2026-01-01", purchase_end=None, purchase_start=None)])
    html = _ops(h)
    sec = html[html.index("過去の参考情報（販売店"):]
    sec = sec[:sec.index("</details>")]
    assert "¥7,200" not in sec and "¥8,800" not in sec and "パック価格から作った価格は採用しない" in sec     # 不採用の行は価格を出さない
    assert "商品ID: zzz-unknown" in sec                                                                   # マスタに名前が無いときは ID と明示
    assert "拡張パック BOX" in sec and "・box・" not in sec                                                 # マスタの表示名（素の product_id でなく）
    assert "¥6,000" in sec                                                                                 # 不採用でない参考行は価格を出す


def test_review_auditor_l4_ledger_notes_have_no_time_limited_state():
    from pathlib import Path
    text = rb.CONFIG_PATH.read_text(encoding="utf-8")
    notes = [ln for ln in text.splitlines() if ln.strip().startswith("note:")]
    assert len(notes) == 4 and not any("受付中" in ln for ln in notes)


# ---------------------------------------------------------------- 第 3 回レビュー（参考一覧の OPEN 行・開始日未確認）
def _refs_html(entries, **kw):
    html = _ops(hub(entries, **kw))
    sec = html[html.index("過去の参考情報（販売店"):]
    return sec[:sec.index("</details>")]


OPEN_HEAD = "応募受付中だが条件付き利益を計算できない"


def _open_refs_html(h):
    """L3: OPEN で利益を計算できない行の小見出しの中（見出し語そのものは含めない）。"""
    html = _ops(h)
    sec = html[html.index(OPEN_HEAD):]
    sec = sec[:sec.index("</details>")]
    return sec[sec.index("<ul>"):]


def test_review3_open_reference_row_has_no_static_accepting_label_and_carries_deadline():
    old = (NOW - timedelta(days=15)).strftime("%Y-%m-%d")       # 14 日超の stale な OPEN 行（REFERENCE_ONLY）
    sec = _open_refs_html(hub([ent(verified_at=old)]))
    assert "受付中" not in sec and "応募期限" in sec
    assert "data-rb-card" in sec and "data-rb-until=" in sec and "data-rb-expired hidden" in sec and "応募期限を過ぎました" in sec


def test_review3_not_calculated_open_row_has_no_static_accepting_label():
    h = hub([ent()], action="NO_BUYBACK")
    assert h["retailer_references"] and h["retailer_references"][0]["kind"] == "NOT_CALCULATED" and h["retailer_references"][0]["accept_state"] == "OPEN"
    sec = _open_refs_html(h)
    assert "受付中" not in sec and "応募期限" in sec and "data-rb-until=" in sec


def test_l3_open_not_calculated_row_is_not_under_the_past_reference_heading():
    """L3: 応募期間中で利益を計算できない行は、『過去の参考情報』（終了・当選者のみ・期間外・不明）に入れない。"""
    html = _ops(hub([ent()], action="NO_BUYBACK"))
    assert OPEN_HEAD in html and "過去の参考情報（販売店" not in html            # OPEN の行だけ → 過去の参考情報の見出しごと出ない
    html2 = _ops(hub([ent(), ent(id="t2", apply_end="2026-01-01", purchase_end=None, purchase_start=None, shop="終了店",
                                            source_url="https://shop.example/y")], action="NO_BUYBACK"))
    past = html2[html2.index("過去の参考情報（販売店"):]
    past = past[:past.index("</details>")]
    assert "終了店" in past and "テスト店" not in past
    opn = html2[html2.index(OPEN_HEAD):]
    opn = opn[:opn.index("</details>")]
    assert "テスト店" in opn and "終了店" not in opn


def test_review3_non_open_reference_row_keeps_its_state_label():
    sec = _refs_html([ent(apply_end="2026-01-01", purchase_end=None, purchase_start=None)])
    assert "data-rb-card" not in sec and "購入期間終了" in sec


def test_review3_missing_apply_start_stays_open_but_is_marked_unconfirmed():
    c = _kind(ent())
    assert c["kind"] == rb.K_CONDITIONAL and c["start_unconfirmed"] is True and "開始日未確認" in c["reason"]
    assert _kind(ent(apply_start="2026-11-01"))["start_unconfirmed"] is False
    assert _kind(ent(apply_start="2026-11-01", apply_start_known=False))["start_unconfirmed"] is True
    html = page_mod.render(hub([ent()]))
    sec = html[html.index('id="retailer-box"'):html.index('id="page-foot"')]
    assert "開始日未確認" in sec


def test_review_l3_future_apply_start_reason_says_before_start():
    c = _kind(ent(apply_start=(NOW + timedelta(days=3)).strftime("%Y-%m-%d")))
    assert c["kind"] == rb.K_REFERENCE and c["accept_state"] == rb.S_UNKNOWN
    assert "応募開始前" in c["reason"] and "開始日" in c["reason"] and "受付状態を確認できません" not in c["reason"]
    d = _kind(ent(apply_start="来週"))                                          # 読めない開始日は従来の文言のまま
    assert "受付状態を確認できません" in d["reason"]


# ── 2026-11-26 21:29 JST の Daily LP が deploy-check #853 で止まった件の回帰（販売店 BOX の条件付きカード _rb_card） ──
# 失敗した実行の入力（その日の買取データと tcg.html）は CI の成果物に残っていないので、hub() の fixture で同じカードを描いて確かめる。
def _rb_page(sell=9000, entries=None):
    from src.content.tcg_hub_page import render_pages
    return render_pages(hub(entries if entries is not None else [ent()], sell=sell), generated_label="x")["tcg.html"]


def _check853(html):
    import re

    import scripts.deploy_check as dc
    from src.content.tcg_hub_page import _CFG
    from src.tcg import runtime_freshness as rf
    mx, fut = rf.thresholds(_CFG())
    obs = set(re.findall(r'data-fb-obs="([^"]+)"', html))
    return dc.check_tcg_page_runtime_freshness(html, mx, fut, obs)


def test_rb_card_passes_853_profit_loss_and_none():
    for sell in (9000, 1000):                                      # 黒字・赤字
        html = _rb_page(sell)
        assert '<section class="pcard opp"' in html and _check853(html) == []
    none = _rb_page(entries=[])
    assert '<section class="pcard opp"' not in none and _check853(none) == []                  # カードなし


def test_rb_card_groups_split_by_observed_time_and_kind():
    """買取（最高買取）と利益の取得時刻が違っても、同じ group にしない（group ごとに 1 つの取得時刻）。"""
    import re
    html = _rb_page()
    card = re.search(r'<section class="pcard opp".*?</section>', html, re.S).group(0)
    groups = {}
    for g, o in re.findall(r'data-fb-live data-fb-group="([^"]+)" data-fb-obs="([^"]+)"', card):
        groups.setdefault(g, set()).add(o)
    assert set(groups) == {"rb0-b", "rb0-p", "rb0-s"} and all(len(v) == 1 for v in groups.values())
    other = "2026-11-21T09:00:00+09:00"
    moved = re.sub(r'(data-fb-group="rb0-b" data-fb-obs=")[^"]+', r"\g<1>" + other, html)     # 買取だけ別の時刻
    import scripts.deploy_check as dc
    from src.content.tcg_hub_page import _CFG
    from src.tcg import runtime_freshness as rf
    mx, fut = rf.thresholds(_CFG())
    obs = set(re.findall(r'data-fb-obs="([^"]+)"', moved))
    assert dc.check_tcg_page_runtime_freshness(moved, mx, fut, obs) == []


def test_rb_card_every_amount_is_inside_live_and_has_a_stale_partner():
    """鮮度切れ（JS が live を隠して stale を出す）で、最高買取・純利益・ROI・状態バッジが「再確認待ち」に切り替わる作り。"""
    import re
    card = re.search(r'<section class="pcard opp".*?</section>', _rb_page(), re.S).group(0)
    for g in ("rb0-b", "rb0-p", "rb0-s"):
        assert re.search(rf'data-fb-live data-fb-group="{g}"[^>]*hidden>', card)          # 最初は隠す（JS が新しいと確かめたら出す）
        assert re.search(rf'data-fb-stale data-fb-group="{g}"', card)                     # 古ければこちらが出る
    live_text = " ".join(re.findall(r"<(?:span|div) data-fb-live[^>]*>(.*?)</(?:span|div)>", card, re.S))
    assert "¥" in live_text and "ROI" in live_text and "条件付き" in live_text


def test_rb_card_label_change_does_not_hide_rows_from_853():
    """見出しを変えても検査の対象から外れない: 最高買取・純利益の行から live を外すと #853 が検出する。"""
    html = _rb_page()
    for label in ("最高買取", "条件付きの純利益"):
        i = html.index(f"<dt>{label}</dt>")
        j = html.rindex("<div ", 0, i)
        broken = html[:j] + html[j:i].replace("data-fb-live ", "").replace(" hidden", "") + html[i:]
        assert broken != html and _check853(broken) != []
