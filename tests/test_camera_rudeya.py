# -*- coding: utf-8 -*-
"""カメラの買取ルデヤ: 一覧と商品ページの突合・機種の同一性・受付状態（fail-closed）・取れなかったときの扱い。"""
import json
from datetime import datetime

import pytest

from src.collectors import camera_rudeya as cru
from src.tcg import buyback as bb
from tests.test_tcg_buyback import ACTIVE_ACTION

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=bb.JST)
BASE = "https://kaitori-rudeya.com/product/item/"
CFG = {"items": [
    {"product": "RICOH GR IV", "jan": "4549212311291", "item": 6119, "name_contains": ["GR IV"], "name_excludes": ["HDF", "Monochrome", "30th"]},
    {"product": "SONY α7R V", "jan": "4548736145573", "item": 2027, "name_contains": ["ILCE-7RM5"], "name_excludes": []},
]}


def card(name, price, jan, item, action=ACTIVE_ACTION, badge="新品", memo="保証書店舗印あり-30000円"):
    p = f'<span class="product-card-price-value">{price:,}<span class="unit">円</span></span>' if price else ""
    return (f'<article class="pgrid-card" id="product{item}"><a href="{BASE}{item}" class="product-card-thumb"></a>'
            f'<span class="product-card-cond-badge is-new">{badge}</span>'
            f'<a class="product-card-name-link" href="{BASE}{item}">{name}</a>'
            f'<span class="product-card-jan-text">JAN: {jan}</span><span class="product-card-memo">{memo}</span>'
            f'<div class="product-card-price-wrap">{p}</div>{action}</article>')


def listing(*cards):
    return cru.parse_list('<html><body><span>2026年11月25日 11時55分現在</span>' + "".join(cards) + "</body></html>", "https://kaitori-rudeya.com/category/detail/11", NOW)


def item_page(name, jan, price, asof="2026-11-25", active=True):
    ld = json.dumps({"@context": "https://schema.org", "@type": "Product", "name": name, "gtin13": jan}, ensure_ascii=False)
    status = "ただいま買取受付中" if active else ""
    return (f'<html><head><script type="application/ld+json">{ld}</script></head><body><div>備考 店舗印あり買取不可 {status}</div>'
            f'<div>買取価格 ¥ {price:,} {asof} 現在</div><button>買取リクエスト</button></body></html>')


GR4 = ("RICOH(リコー) GR IV", "4549212311291", 6119)
A7 = ("SONY(ソニー) α7R V ILCE-7RM5 ボディ*", "4548736145573", 2027)


def run(cards, pages):
    rows = listing(*cards)
    return cru.build_rows(CFG, rows, lambda url: pages.get(url), "2026-11-25")


def test_matching_list_and_item_page_makes_a_found_row():
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119)], {BASE + "6119": item_page(GR4[0], GR4[1], 211000)})
    row = products[0]["buyback"][0]
    assert row["price_jpy"] == 181000 and row["is_product_page"] is True and row["condition"] == "NEW"      # 店舗印ありの価格（完品 211,000 - 30,000）を売値にする
    assert "211,000" in row["reason"] and "安全側" in row["reason"]
    assert row["checked_at"] == "2026-11-25" and row["source_updated_at"] == "2026-11-25" and row["result"] == "FOUND"
    assert row["url"] == BASE + "6119" and row["item_title"] == GR4[0]
    assert notes[0]["ok"] is True and notes[1]["ok"] is False            # α7R V は一覧に無い → 不採用


def test_item_missing_from_the_list_is_rejected_with_reason():
    _, notes = run([card(GR4[0], 211000, GR4[1], 6119)], {BASE + "6119": item_page(GR4[0], GR4[1], 211000)})
    a7 = [n for n in notes if n["product"] == "SONY α7R V"][0]
    assert a7["ok"] is False and "一覧に載っていない" in a7["reason"]


@pytest.mark.parametrize("name", ["RICOH(リコー) GR IV HDF", "RICOH(リコー) GR IV Monochrome", "RICOH(リコー) GR IV 30th Anniversary Edition Kit"])
def test_other_edition_with_the_same_jan_is_rejected(name):
    products, notes = run([card(name, 245000, GR4[1], 6119)], {BASE + "6119": item_page(name, GR4[1], 245000)})
    assert products == [] and "別の版" in notes[0]["reason"]


def test_jan_mismatch_is_rejected():
    products, notes = run([card(GR4[0], 211000, "4549212399999", 6119), card(A7[0], 355000, A7[1], 2027)], {BASE + "2027": item_page(A7[0], A7[1], 355000)})
    gr4 = [n for n in notes if n["product"] == "RICOH GR IV"][0]
    assert gr4["ok"] is False and "一覧に載っていない" in gr4["reason"] and gr4["withdraw"] is True


def test_price_mismatch_between_list_and_item_is_rejected():
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119)], {BASE + "6119": item_page(GR4[0], GR4[1], 205000)})
    assert products == [] and "食い違う" in notes[0]["reason"]


@pytest.mark.parametrize("action", [
    '<div class="product-card-action"><span class="product-card-stopped">お申込一時停止中</span></div>',
    '<div class="product-card-action"><span>未登録の言い回しの停止</span><button class="b">買取リクエスト</button></div>',
    "",
])
def test_stopped_or_unknown_list_row_makes_no_row(action):
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119, action=action)], {BASE + "6119": item_page(GR4[0], GR4[1], 211000)})
    assert products == [] and "受付状態" in notes[0]["reason"]


def test_item_page_without_explicit_active_text_makes_no_row():
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119)], {BASE + "6119": item_page(GR4[0], GR4[1], 211000, active=False)})
    assert products == [] and "受付中" in notes[0]["reason"]


def test_item_page_without_date_makes_no_row():
    html = item_page(GR4[0], GR4[1], 211000).replace("2026-11-25 現在", "")
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119)], {BASE + "6119": html})
    assert products == [] and "日付" in notes[0]["reason"]


def test_unreadable_item_page_makes_no_row():
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119)], {})
    assert products == [] and "読めなかった" in notes[0]["reason"]


def test_non_new_badge_makes_no_row():
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119, badge="中古", memo="中古品")], {BASE + "6119": item_page(GR4[0], GR4[1], 211000)})
    assert products == []


def test_docs_are_split_by_brand_and_sort_after_the_researchers_file():
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119), card(A7[0], 355000, A7[1], 2027)],
                          {BASE + "6119": item_page(GR4[0], GR4[1], 211000), BASE + "2027": item_page(A7[0], A7[1], 355000)})
    docs = cru.build_docs(products, notes, "2026-11-25", NOW, 2)
    assert sorted(docs) == ["research_camera_RICOH_rudeya.json", "research_camera_Sony_rudeya.json"]
    assert "research_camera_Sony.json" < "research_camera_Sony_rudeya.json"
    assert docs["research_camera_Sony_rudeya.json"]["brand"] == "Sony"
    assert docs["research_camera_RICOH_rudeya.json"]["source_results"][0]["result"] == "FOUND"


def test_no_rows_reports_a_failed_source():
    docs = cru.build_docs([], [{"product": "x", "jan": "1", "ok": False, "withdraw": False, "reason": "一覧ページを取得できなかった"}], "2026-11-25", NOW, 1)
    doc = next(iter(docs.values()))
    assert doc["products"] == [] and doc["source_results"][0]["result"] == "FAILED"


def test_collect_script_does_not_write_when_nothing_is_fetched(tmp_path):
    from scripts import collect_camera_rudeya as sc
    docs, notes = sc.collect({"categories": ["https://kaitori-rudeya.com/category/detail/11"], "items": CFG["items"]}, NOW, fetcher=lambda u: None)
    assert not any(n["ok"] for n in notes)
    assert next(iter(docs.values()))["products"] == []


MODAL = '<div class="product-card-action"><!-- 状態・買取方法を選んで個数入力 --><a href="#" class="product-card-btn is-more js-modal-open modal_more" data-target="modal_c6119">条件を選ぶ</a></div>'


def run_html(cards, pages):
    rows = cru.parse_list('<html><body><span>2026年11月25日 11時55分現在</span>' + "".join(cards) + "</body></html>", "https://kaitori-rudeya.com/category/detail/11", NOW)
    return cru.build_rows(CFG, rows, lambda url: pages.get(url), "2026-11-25")


def test_condition_modal_row_is_adopted_only_with_the_item_pages_active_text():
    ok, _ = run_html([card(GR4[0], 210200, GR4[1], 6119, action=MODAL, memo="保証書店舗印あり-30000円")], {BASE + "6119": item_page(GR4[0], GR4[1], 210200)})
    assert ok and ok[0]["buyback"][0]["price_jpy"] == 180200
    none, notes = run_html([card(GR4[0], 210200, GR4[1], 6119, action=MODAL)], {BASE + "6119": item_page(GR4[0], GR4[1], 210200, active=False)})
    assert none == [] and "受付中" in notes[0]["reason"]


def test_condition_modal_row_is_unknown_in_the_list_and_never_active_by_itself():
    rows = cru.parse_list('<html><body>' + card(GR4[0], 210200, GR4[1], 6119, action=MODAL) + "</body></html>", "u", NOW)
    assert rows[0]["accept_state"] == bb.A_UNKNOWN and rows[0]["list_signal"] == cru.SIGNAL_MODAL and not rows[0].get("executable")


@pytest.mark.parametrize("action", [
    MODAL.replace('data-target="modal_c6119"', 'data-target="modal_c1"'),
    MODAL.replace("条件を選ぶ", "条件を選ぶ（受付休止）"),
    MODAL.replace("</div>", '<span class="product-card-stopped">お申込一時停止中</span></div>'),
    MODAL.replace('class="product-card-btn is-more', 'class="product-card-btn is-more disabled'),
])
def test_condition_modal_variants_that_do_not_match_exactly_get_no_signal(action):
    rows = cru.parse_list('<html><body>' + card(GR4[0], 210200, GR4[1], 6119, action=action) + "</body></html>", "u", NOW)
    assert "list_signal" not in rows[0]


def test_same_jan_with_different_prices_is_rejected():
    products, notes = run_html([card(GR4[0], 210200, GR4[1], 6119, action=MODAL), card(GR4[0], 215000, GR4[1], 6119, action=MODAL)],
                               {BASE + "6119": item_page(GR4[0], GR4[1], 210200)})
    assert products == [] and "違う価格" in notes[0]["reason"]


def test_spacing_differences_in_the_name_do_not_break_identity():
    item = {"jan": "4960759909947", "name_contains": ["Z 8"], "name_excludes": ["Kit"]}
    assert cru.identity_ok(item, "Nikon(ニコン)Z8 ボディ", "4960759909947")[0]
    assert cru.identity_ok(item, "Nikon(ニコン) Z　8 ボディ", "4960759909947")[0]
    assert not cru.identity_ok(item, "Nikon(ニコン) Z 8 レンズKit", "4960759909947")[0]


def test_html_comment_containing_a_style_tag_does_not_hide_the_price():
    html = item_page(GR4[0], GR4[1], 211000).replace("<body>", "<body><!-- 解析されるまで <style> が ... --><div>x</div>").replace("</body>", "<style>.a{}</style></body>")
    doc = cru.parse_item_page(html)
    assert doc["price"] == 211000 and doc["asof"] == "2026-11-25"


def test_stamped_not_buyable_makes_no_row():
    """店舗印ありが買取不可の機種は、店で買った新品の売却先にならない。完品の価格を売値にしない。"""
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119, memo="保証書店舗印あり買取不可")], {BASE + "6119": item_page(GR4[0], GR4[1], 211000)})
    assert products == [] and "店舗印ありは買取不可" in notes[0]["reason"]
    products, notes = run([card(A7[0], 355000, A7[1], 2027, memo="店舗印あり買取不可")], {BASE + "2027": item_page(A7[0], A7[1], 355000)})
    assert products == []


@pytest.mark.parametrize("memo", ["新品未開封のみ買取可", "", "店舗印あり"])
def test_unreadable_stamp_policy_makes_no_row(memo):
    products, notes = run([card(GR4[0], 211000, GR4[1], 6119, memo=memo)], {BASE + "6119": item_page(GR4[0], GR4[1], 211000)})
    assert products == [] and "店舗印あり" in notes[0]["reason"]


def test_stamp_deduction_larger_than_price_is_not_used():
    assert cru.stamp_policy("保証書店舗印あり-900000円", 211000)["policy"] == cru.STAMP_UNKNOWN
    assert cru.stamp_policy("保証書店舗印あり-30,000円", 211000) == {"policy": cru.STAMP_DEDUCTION, "deduction": 30000, "price": 181000}


def test_modal_stamped_price_must_agree_with_the_memo():
    modal = "完品 買取 ¥211,000 点 保証書店舗印あり 買取 ¥181,000 (-30,000円) 点"
    assert cru.stamp_policy("保証書店舗印あり-30000円", 211000, modal)["policy"] == cru.STAMP_DEDUCTION
    bad = "完品 買取 ¥211,000 点 保証書店舗印あり 買取 ¥170,000 (-41,000円) 点"
    assert cru.stamp_policy("保証書店舗印あり-30000円", 211000, bad)["policy"] == cru.STAMP_UNKNOWN


ATTN_BTN = '<button type="button" class="product-card-attention js-modal-open" data-target="modal_o6119"><span>注意事項</span></button>'
ATTN_MODAL = '<div id="modal_o6119" class="js-modal pmodal">注意事項 JANコード要確認</div>'


def test_row_with_a_store_attention_notice_is_not_adopted():
    """店自身が「JANコード要確認」と注意している行は、同一性を確認できないので採用しない（注意事項のボタンは JAN の行にあり、本文は一覧の後ろにある）。"""
    c = card(GR4[0], 211000, GR4[1], 6119).replace('</span><span class="product-card-memo">', "</span>" + ATTN_BTN + '<span class="product-card-memo">')
    rows = cru.parse_list("<html><body>" + c + ATTN_MODAL + "</body></html>", "u", NOW)
    assert "JANコード要確認" in rows[0]["attention"]
    products, notes = cru.build_rows(CFG, rows, lambda u: item_page(GR4[0], GR4[1], 211000), "2026-11-25")
    assert products == [] and "注意事項" in notes[0]["reason"]


def test_deliberate_rejections_are_withdrawn_but_fetch_failures_are_not():
    """意図した不採用（買取不可・注意事項・食い違い）は withdrawn（前回の行を引き継がない）。通信の失敗は withdrawn にしない（前回の行を日付ごと引き継ぐ）。"""
    notes = [{"product": "RICOH GR IV", "jan": "1", "ok": True, "price": 1},
             {"product": "SONY α7R V", "jan": "2", "ok": False, "withdraw": True, "reason": "店舗印ありは買取不可"},
             {"product": "Nikon Z8", "jan": "3", "ok": False, "withdraw": False, "reason": "商品ページを読めなかった"}]
    products = [{"product": "RICOH GR IV", "buyback": []}]
    docs = cru.build_docs(products, notes, "2026-11-25", NOW, 3)
    assert sorted(docs) == ["research_camera_RICOH_rudeya.json", "research_camera_Sony_rudeya.json"]
    assert docs["research_camera_Sony_rudeya.json"]["withdrawn"][0]["product"] == "SONY α7R V"
    assert docs["research_camera_Sony_rudeya.json"]["products"] == []
    assert docs["research_camera_RICOH_rudeya.json"]["withdrawn"] == []
    assert all(w["product"] != "Nikon Z8" for d in docs.values() for w in d["withdrawn"])


def test_same_jan_rows_must_agree_on_attention_and_stamp():
    a = card(GR4[0], 210200, GR4[1], 6119, action=MODAL, memo="保証書店舗印あり-30000円")
    b = card(GR4[0], 210200, GR4[1], 6119, action=MODAL, memo="保証書店舗印あり-40000円")
    products, notes = run_html([a, b], {BASE + "6119": item_page(GR4[0], GR4[1], 210200)})
    assert products == [] and "食い違う" in notes[0]["reason"]


def test_collect_script_removes_previous_outputs_before_writing(tmp_path, monkeypatch):
    from scripts import collect_camera_rudeya as sc
    (tmp_path / "research_camera_Sony_rudeya.json").write_text("{}", encoding="utf-8")
    (tmp_path / "research_camera_Sony.json").write_text("{}", encoding="utf-8")        # 調査員のファイルは消さない
    monkeypatch.setattr(sc, "collect", lambda cfg, now: ({"research_camera_RICOH_rudeya.json": {"brand": "RICOH", "products": []}},
                                                         [{"product": "RICOH GR IV", "jan": "1", "ok": True, "price": 1, "url": "https://kaitori-rudeya.com/product/item/1"}]))
    assert sc.main(["--dir", str(tmp_path)]) == 0
    assert not (tmp_path / "research_camera_Sony_rudeya.json").exists()
    assert (tmp_path / "research_camera_Sony.json").exists() and (tmp_path / "research_camera_RICOH_rudeya.json").exists()


def test_found_row_declares_the_stamped_price_basis():
    products, _ = run([card(GR4[0], 211000, GR4[1], 6119)], {BASE + "6119": item_page(GR4[0], GR4[1], 211000)})
    assert products[0]["buyback"][0]["price_basis"] == "STAMPED_WARRANTY"


def test_partial_list_failure_is_a_fetch_failure_not_a_withdrawal():
    """一覧ページを全部は取得できなかったとき、「一覧に載っていない」は通信の失敗として扱う（前回の行を引き継ぐ）。"""
    rows = cru.parse_list("<html><body>" + card(GR4[0], 211000, GR4[1], 6119) + "</body></html>", "u", NOW)
    _, notes = cru.build_rows(CFG, rows, lambda u: item_page(GR4[0], GR4[1], 211000), "2026-11-25", lists_complete=False)
    a7 = [n for n in notes if n["product"] == "SONY α7R V"][0]
    assert a7["withdraw"] is False and "確認できない" in a7["reason"]
    _, notes = cru.build_rows(CFG, rows, lambda u: item_page(GR4[0], GR4[1], 211000), "2026-11-25", lists_complete=True)
    assert [n for n in notes if n["product"] == "SONY α7R V"][0]["withdraw"] is True
    docs = cru.build_docs([], [n for n in notes if n["product"] == "SONY α7R V"], "2026-11-25", NOW, 1)
    assert docs["research_camera_Sony_rudeya.json"]["withdrawn"]
    docs2 = cru.build_docs([], [{"product": "SONY α7R V", "jan": "1", "ok": False, "withdraw": False, "reason": "x"}], "2026-11-25", NOW, 1)
    assert all(not d.get("withdrawn") for d in docs2.values())


def test_unreadable_item_page_is_a_fetch_failure_and_list_decided_rejections_never_fetch():
    """商品ページを読めなかったのは通信の失敗（withdraw=False）。一覧だけで決まる不採用（買取不可）は商品ページを取りに行かない。"""
    _, notes = run([card(GR4[0], 211000, GR4[1], 6119)], {})
    assert notes[0]["withdraw"] is False and "読めなかった" in notes[0]["reason"]
    called = []
    rows = listing(card(GR4[0], 211000, GR4[1], 6119, memo="保証書店舗印あり買取不可"))
    _, notes = cru.build_rows(CFG, rows, lambda u: called.append(u), "2026-11-25")
    assert notes[0]["withdraw"] is True and called == []


def test_non_new_badge_reason_and_item_page_identity_mismatch():
    _, notes = run([card(GR4[0], 211000, GR4[1], 6119, badge="中古")], {BASE + "6119": item_page(GR4[0], GR4[1], 211000)})
    assert "新品" in notes[0]["reason"]
    _, notes = run([card(GR4[0], 211000, GR4[1], 6119)], {BASE + "6119": item_page("RICOH(リコー) GR IV HDF", GR4[1], 211000)})
    assert "商品ページ" in notes[0]["reason"] and "別の版" in notes[0]["reason"]
    _, notes = run([card(GR4[0], 211000, GR4[1], 6119)], {BASE + "6119": item_page(GR4[0], "4549212399999", 211000)})
    assert "商品ページ" in notes[0]["reason"] and "JAN" in notes[0]["reason"]


def test_condition_modal_with_an_extra_element_after_the_link_gets_no_signal():
    extra = MODAL.replace("</div>", '<button type="button" class="x">買取リクエスト</button></div>')
    rows = cru.parse_list("<html><body>" + card(GR4[0], 210200, GR4[1], 6119, action=extra) + "</body></html>", "u", NOW)
    assert "list_signal" not in rows[0]


def test_no_configured_item_found_is_a_structure_change_not_a_withdrawal():
    """設定の機種が一覧に 1 件も見つからない（構造が変わった可能性）ときは、全機種を撤回せず、通信の失敗として扱う。"""
    rows = cru.parse_list("<html><body>" + card("別の商品", 1000, "4000000000000", 1) + "</body></html>", "u", NOW)
    _, notes = cru.build_rows(CFG, rows, lambda u: None, "2026-11-25")
    assert notes and all(n["withdraw"] is False and "構造が変わった可能性" in n["reason"] for n in notes)
    docs = cru.build_docs([], notes, "2026-11-25", NOW, len(notes))
    doc = next(iter(docs.values()))
    assert doc["source_results"][0]["result"] == "FAILED" and not doc.get("withdrawn")
    # 設定の機種が 1 件でも一覧にあれば、載っていない機種は従来どおり撤回
    rows = cru.parse_list("<html><body>" + card(GR4[0], 211000, GR4[1], 6119) + "</body></html>", "u", NOW)
    _, notes = cru.build_rows(CFG, rows, lambda u: item_page(GR4[0], GR4[1], 211000), "2026-11-25")
    assert [n for n in notes if n["product"] == "SONY α7R V"][0]["withdraw"] is True


def test_200_page_without_any_parsable_card_is_a_fetch_failure():
    from scripts import collect_camera_rudeya as sc
    maintenance = "<html><body>" + "メンテナンス中です。" * 80 + "</body></html>"
    docs, notes = sc.collect({"categories": ["https://kaitori-rudeya.com/category/detail/10", "https://kaitori-rudeya.com/category/detail/11"], "items": CFG["items"]},
                             NOW, fetcher=lambda u: maintenance)
    assert not any(n["ok"] for n in notes) and all(n["withdraw"] is False for n in notes)
    assert next(iter(docs.values()))["source_results"][0]["result"] == "FAILED"
