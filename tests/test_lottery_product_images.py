# -*- coding: utf-8 -*-
"""抽選と商品には必ず画像を出す。

- 商品に紐付いた抽選・商品: 公式画像（verified_products.image_publishable が True = その画像に権利者の利用許可の記録があるとき。
  公式サイトへの直接参照）。本番の記録は空なので、本番はすべて代わりの画像。このファイルは許可の記録があることにして仕組みを試す
- 公式画像が無い商品・商品に紐付いていない抽選: ページ内の SVG の代わりの画像（商品名の要点・型番・TCG・種類）
- 公式画像の読み込みに失敗したとき: onerror で代わりの画像に切り替える
- ONE PIECE 公式の /renewal/ 配下の画像は出さない（公式が埋め込みを許可していない）
"""
from __future__ import annotations

import json
import re

import pytest
from datetime import datetime
from pathlib import Path

from src.content import tcg_hub_page as page
from src.content.ui import lottery_card, lottery_page, lottery_view
from src.content.ui import product_image as pi
from src.content.ui import runtime as rt
from src.tcg import verified_products as vp
from src.tcg.hub.product_view import build_hub
from src.tcg.models import JST

from tests._image_permit import ORIGINAL_RIGHTS_PERMISSION, permit_all

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _permitted(monkeypatch):
    permit_all(monkeypatch)
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=JST)
PK_IMG = "https://www.pokemon-card.com/products/2026/images/x.jpg"
OP_IMG = "https://www.onepiece-cardgame.com/onepiececg/bccard/jp/products/2026/11/02/x/img_item01.webp"
OP_RENEWAL = "https://www.onepiece-cardgame.com/renewal/images/products/boosters/op19/img_item01.webp"


def _ev(**kw):
    d = {"lottery_id": "L1", "tcg": "POKEMON", "product_name": "拡張パック「テスト弾」", "retailer": "CARD_LABO",
         "retailer_name": "カードラボ", "event_type": "LOTTERY", "product_id": "pk-test", "product_match": "exact",
         "application_start": "2026-11-18T10:00:00+09:00", "application_end": "2026-11-25T23:59:00+09:00",
         "source_url": "https://www.c-labo.jp/shop/x/blog/1/", "source_type": "STORE_OFFICIAL", "verified": True}
    d.update(kw)
    return d


def _reg(*rows):
    return {"generated_at": NOW.isoformat(), "products": list(rows)}


def _row(pid, name, tcg="POKEMON", img=None, ptype="BOOSTER_BOX", code=None):
    return {"product_id": pid, "name": name, "tcg": tcg, "product_type": ptype, "product_code": code,
            "release_date": "2026-12-01T00:00:00+09:00", "official_url": "https://www.pokemon-card.com/ex/x/",
            "official_image_url": img}


def _pages(evs, reg):
    hub = build_hub({"generated_at": NOW.isoformat(), "items": evs}, reg, {"verified": []}, NOW)
    return page.render(hub), page.render_lottery(hub)


def _images_in(fragment: str) -> tuple[int, int]:
    return fragment.count("<img "), len(re.findall(r'<svg [^>]*data-ph-svg', fragment))


# ── 判定の正本 ──
def test_default_has_no_rights_permission_so_no_official_image(monkeypatch):
    """本番（許可の記録が空）では、どの公式画像も公開しない（社内の使用判断だけでは出さない）。"""
    monkeypatch.setattr(vp, "rights_permission", ORIGINAL_RIGHTS_PERMISSION)
    assert vp.IMAGE_RIGHTS_PERMISSION == {}
    assert not vp.image_publishable("POKEMON", PK_IMG) and not vp.image_publishable("ONE_PIECE", OP_IMG)


def test_permitted_images_publish_both_tcgs_but_never_renewal():
    assert vp.image_publishable("POKEMON", PK_IMG) and vp.image_publishable("ONE_PIECE", OP_IMG)
    assert not vp.image_publishable("ONE_PIECE", OP_RENEWAL)                          # /renewal/ は回避しない
    assert not vp.image_publishable("POKEMON", "https://evil.example/x.jpg")


# ── TCG ハブ ──
def test_hub_shows_official_image_for_bound_lottery_and_product():
    prod, lot = _pages([_ev()], _reg(_row("pk-test", "拡張パック「テスト弾」", img=PK_IMG)))
    for html in (prod, lot):
        assert f'src="{PK_IMG}"' in html
        tag = re.search(r'<img [^>]*>', html).group(0)
        for need in ('alt="拡張パック「テスト弾」"', 'width="320"', 'height="240"', 'loading="lazy"', 'decoding="async"',
                     'referrerpolicy="strict-origin-when-cross-origin"', f'onerror="{page.IMG_ONERROR}"'):
            assert need in tag, need
        assert page.IMG_CREDIT in html                                                # 出典表記
    # 帯（締切が近い抽選）・横スクロール・商品カード・抽選の行のどれにも公式画像
    assert re.search(r'<li class="sr"[^>]*><div class="pimg pokemon"><img ', prod)
    assert re.search(r'<a class="th"[^>]*><div class="pimg pokemon"><img ', prod)
    assert re.search(r'<div class="tc-img"><div class="pimg pokemon"><img ', prod)
    assert re.search(r'<td class="im"><div class="pimg pokemon"><img ', lot)


def test_hub_placeholder_for_product_without_image_has_code_tcg_and_kind():
    reg = _reg(_row("op19", "ブースターパック 応答せよ、世界【OP-19】", tcg="ONE_PIECE", img=None, code="OP-19"))
    prod, lot = _pages([_ev(tcg="ONE_PIECE", product_id="op19", product_name="ブースターパック 応答せよ、世界【OP-19】")], reg)
    for html in (prod, lot):
        assert "<img " not in html
        svg = re.search(r'<div class="pimg onepiece ph"><svg .*?</svg>', html, re.S).group(0)
        for need in (">OP-19</text>", ">応答せよ、世界</text>", ">ONE PIECE カード</text>", ">パック・BOX</text>",
                     'role="img"', 'aria-label="ブースターパック 応答せよ、世界【OP-19】"'):
            assert need in svg, need
        assert "<image" not in svg and "href=" not in svg                            # 外部の画像を読まない
    assert ">OP</b>" not in prod and "<small>ワンピ</small>" not in prod                # 意味の薄い仮置きは出さない


def test_hub_renewal_image_is_not_shown():
    reg = _reg(_row("op19", "ブースターパック 応答せよ、世界【OP-19】", tcg="ONE_PIECE", img=OP_RENEWAL, code="OP-19"))
    prod, lot = _pages([_ev(tcg="ONE_PIECE", product_id="op19", product_name="応答せよ、世界")], reg)
    assert "/renewal/" not in prod and "/renewal/" not in lot and "<img " not in prod + lot
    assert '<div class="pimg onepiece ph"><svg ' in prod


def test_hub_unbound_lottery_gets_placeholder_not_shop_initials():
    evs = [_ev(lottery_id="L2", product_match="none", product_id=None, product_name="ポケモンカードゲーム 拡張パック二種（再販）",
               retailer_name="<b>店</b>")]
    prod, lot = _pages(evs, _reg())
    row = re.search(r'<tr class="ev[^>]*data-product="none".*?</tr>', lot, re.S).group(0)
    assert '<td class="im"><div class="pimg pokemon ph"><svg ' in row and ">パック</text>" in row and ">ポケモンカード</text>" in row
    assert ">二種（再販）</text>" in row                     # 商品名の要点（前置きの「ポケモンカードゲーム」とシリーズ名を外す）
    assert 'class="pimg ph shop"' not in lot and "<b>店</b>" not in lot
    assert re.search(r'<li class="sr"[^>]*><div class="pimg pokemon ph"><svg ', prod)     # 締切が近い抽選の帯


def test_hub_image_failure_switches_to_placeholder():
    prod, _lot = _pages([_ev()], _reg(_row("pk-test", "拡張パック「テスト弾」", img=PK_IMG)))
    box = re.search(r'<div class="pimg pokemon"><img .*?</div>', prod, re.S).group(0)
    assert "onerror=" in box and '<span class="phs" data-phb hidden><svg ' in box
    assert "data-phb" in page.IMG_ONERROR and "this.remove()" in page.IMG_ONERROR and "http" not in page.IMG_ONERROR
    assert ".pimg>.phs[hidden]{display:none}" in page.CSS                           # 表示の規則で隠れたままになる


def test_no_lottery_or_product_row_without_image_on_real_data():
    """公開済みの JSON から作ったページで、画像の無い抽選の行・商品カード・帯・横スクロールが 0 件。公式画像は 1 件以上。"""
    d = ROOT / "exports" / "tcg"
    load = lambda n: json.loads((d / n).read_text(encoding="utf-8"))          # noqa: E731
    pages = page.render_pages_from_json(load("lotteries.json"), load("pokemon_registry.json"), load("msrp.json"),
                                        buyback=load("buyback.json"))
    prod, lot = pages[page.PAGE_PRODUCTS], pages[page.PAGE_LOTTERY]
    blocks = (re.findall(r'<tr class="ev.*?</tr>', lot, re.S) + re.findall(r'<article class="tcard".*?</article>', prod, re.S)
              + re.findall(r'<li class="sr".*?</li>', prod, re.S) + re.findall(r'<a class="th".*?</a>', prod, re.S))
    assert blocks
    missing = [b[:120] for b in blocks if sum(_images_in(b)) == 0]
    assert missing == []
    assert "<img " in prod and "/renewal/" not in prod + lot
    for html in (prod, lot):
        for src in re.findall(r'<img [^>]*src="([^"]+)"', html):
            assert vp.image_ok("POKEMON", src) or vp.image_ok("ONE_PIECE", src), src


# ── 新UI（VM・HOME の抽選カード・抽選ページの行） ──
def test_vm_carries_official_image_only_for_bound_product(monkeypatch):
    idx = {("POKEMON", "pk-test"): _row("pk-test", "拡張パック「テスト弾」", img=PK_IMG),
           ("ONE_PIECE", "op19"): _row("op19", "ブースターパック 応答せよ、世界【OP-19】", tcg="ONE_PIECE", img=OP_RENEWAL, code="OP-19")}
    monkeypatch.setattr(pi, "_index", lambda: idx)
    assert rt.tcg_vm(_ev(), 0)["pic"]["u"] == PK_IMG
    assert rt.tcg_vm(_ev(product_match="ambiguous"), 0)["pic"]["u"] == ""             # 紐付いていなければ公式画像を使わない
    op = rt.tcg_vm(_ev(tcg="ONE_PIECE", product_id="op19"), 0)["pic"]
    assert op["u"] == "" and op["c"] == "OP-19"                                       # /renewal/ は出さない（代わりの画像の材料だけ）


def test_vm_image_does_not_change_runtime_state(monkeypatch):
    monkeypatch.setattr(pi, "_index", lambda: {("POKEMON", "pk-test"): _row("pk-test", "x", img=PK_IMG)})
    vm = rt.tcg_vm(_ev(), 0)
    bare = {k: v for k, v in vm.items() if k != "pic"}
    assert rt.derive_runtime_state(vm, NOW) == rt.derive_runtime_state(bare, NOW)


def test_home_lottery_card_shows_official_image_or_placeholder(monkeypatch):
    monkeypatch.setattr(pi, "_index", lambda: {("POKEMON", "pk-test"): _row("pk-test", "拡張パック「テスト弾」", img=PK_IMG)})
    vm = rt.tcg_vm(_ev(), 0)
    html = lottery_card.render(vm, rt.derive_runtime_state(vm, NOW), 0)
    assert re.search(r'<div class="nu-card__head"><span class="nu-thumb" style="[^"]*aspect-ratio:4/3[^"]*"><img src="' + re.escape(PK_IMG), html)
    for need in ('alt="拡張パック「テスト弾」"', 'loading="lazy"', 'decoding="async"', 'referrerpolicy="strict-origin-when-cross-origin"',
                 'width="320" height="240"', '<span class="phs" data-phb hidden><svg '):
        assert need in html, need
    vm2 = rt.tcg_vm(_ev(product_match="none", product_id=None, product_name="【ポケモンカードゲーム】再販品"), 1)
    html2 = lottery_card.render(vm2, rt.derive_runtime_state(vm2, NOW), 1)
    assert "<img " not in html2 and re.search(r'<span class="nu-thumb ph" style="[^"]*"><svg ', html2) and ">再販品</text>" in html2
    # 旧来の抽選（カメラ・ゲーム機）にも代わりの画像
    leg = rt.legacy_vm({"id": "g1", "product_name": "ゲーム機 本体", "brand": "メーカー直販"}, 0)
    assert re.search(r'<span class="nu-thumb ph" style="[^"]*"><svg ', lottery_card.render(leg, rt.derive_runtime_state(leg, NOW), 2))


def test_new_ui_lottery_rows_all_have_images_on_real_data():
    report = json.loads((ROOT / "exports" / "tcg" / "latest.json").read_text(encoding="utf-8"))
    vms = rt.build_vms(report, [])
    assert vms
    now = datetime.now(tz=JST)
    views = lottery_view.build(vms=vms, tcg_report=report, legacy_items=[], lottery_cats={})
    rows = [lottery_page._row(v, rt.derive_runtime_state(v.vm, now), i) for i, v in enumerate(views)]
    cards = [lottery_card.render(vm, rt.derive_runtime_state(vm, now), i) for i, vm in enumerate(vms)]
    assert [r[:80] for r in rows + cards if sum(_images_in(r)) == 0] == []
    assert any("<img " in c for c in cards)                                           # 公式画像が出る抽選がある
    assert all("/renewal/" not in c for c in rows + cards)
    assert all(re.search(r'<div class="nu-lrow__main nu-lmedia" style="[^"]*"><span class="nu-thumb', r) for r in rows)


def test_new_ui_lottery_page_adds_no_style_element_and_no_credit_without_images():
    class _Cat:
        lottery_views: list = []
        product_ids: set = set()

        def count(self, _k):
            return 0

    class _Model:
        vms: list = []
        states: dict = {}

    html = lottery_page.render(_Cat(), _Model())
    assert "<style" not in html                                                      # 新UIの <style> は 1 つだけ（見た目はインライン）
    assert pi.IMG_CREDIT not in html                                                 # 公式画像が無ければ出典表記は出さない


def test_placeholder_escapes_text_and_uses_no_external_resources():
    svg = pi.placeholder_svg(tcg="POKEMON", name='<script>alert(1)</script>"x', kind="BOX", code="OP-1")
    assert "<script>" not in svg and "&lt;script&gt;" in svg and "&quot;x" in svg
    assert "http" not in svg.replace("http://www.w3.org/2000/svg", "")
