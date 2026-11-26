# -*- coding: utf-8 -*-
"""商品台帳の公式画像 URL の検査（data/tcg_verified_products.json → verified_products.load）。"""
import json

from src.tcg import verified_products as vp


def _rec(tcg, img, **kw):
    base = {"product_id": "p1", "name": "商品", "tcg": tcg, "retail_price_basis": "pack",
            "official_url": "https://example.invalid/x", "official_image_url": img,
            "evidence": {"source_url": "https://example.invalid/x", "checked_on": "2026-11-26"}}
    base.update(kw)
    return base


def _load(tmp_path, recs):
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"products": recs}, ensure_ascii=False), encoding="utf-8")
    return vp.load(p)


def test_official_https_images_are_kept_per_tcg():
    assert vp.image_ok("ONE_PIECE", "https://www.onepiece-cardgame.com/onepiececg/bccard/jp/products/2026/03/19/ppvbEWL5lA3yBgPr/img_item01.webp")
    assert vp.image_ok("POKEMON", "https://www.pokemon-card.com/products/2025/images/M2.jpg")


def test_wrong_host_http_noimage_and_lookalike_hosts_are_rejected():
    assert not vp.image_ok("ONE_PIECE", "https://www.pokemon-card.com/products/2025/images/M2.jpg")
    assert not vp.image_ok("POKEMON", "https://www.onepiece-cardgame.com/x/img_item01.webp")
    assert not vp.image_ok("POKEMON", "http://www.pokemon-card.com/products/2025/images/M2.jpg")
    assert not vp.image_ok("ONE_PIECE", "https://www.onepiece-cardgame.com/images/img_noimage_booster_jp.webp")
    assert not vp.image_ok("POKEMON", "https://pokemon-card.com.evil.example/a.jpg")
    assert not vp.image_ok("POKEMON", "https://evilpokemon-card.com/a.jpg")
    assert not vp.image_ok("YUGIOH", "https://www.pokemon-card.com/a.jpg")
    assert not vp.image_ok("POKEMON", None)


def test_onepiece_renewal_images_are_not_embedded():
    """/renewal/ 配下は公式が CORP same-site を返す（他サイトに埋め込めない）。使わずにプレースホルダにする。"""
    assert not vp.image_ok("ONE_PIECE", "https://www.onepiece-cardgame.com/renewal/images/products/decks/st29/img_item01.webp")
    assert not vp.image_ok("ONE_PIECE", "https://www.onepiece-cardgame.com/RENEWAL/images/products/boosters/op15/img_item01.webp")


def test_bad_image_drops_only_the_image_not_the_row(tmp_path):
    rows = _load(tmp_path, [_rec("ONE_PIECE", "https://www.pokemon-card.com/a.jpg")])
    assert len(rows) == 1 and rows[0]["official_image_url"] is None


def test_good_image_survives_load(tmp_path):
    url = "https://www.onepiece-cardgame.com/onepiececg/bccard/jp/products/2026/09/17/uqpcLANBkRtwZ4GX/img_item01.webp"
    rows = _load(tmp_path, [_rec("ONE_PIECE", url)])
    assert rows[0]["official_image_url"] == url


def test_ledger_images_all_pass_and_have_evidence():
    """実データの台帳: 画像があれば公式ホストで、確認元ページと確認日がある。"""
    doc = json.loads(vp.PATH.read_text(encoding="utf-8"))
    with_img = [r for r in doc["products"] if r.get("official_image_url")]
    assert with_img, "台帳に公式画像が1件も無い"
    for r in with_img:
        assert vp.image_ok(r["tcg"], r["official_image_url"]), r["name"]
        ev = r["evidence"]
        assert str(ev.get("image_source_url", "")).startswith("https://"), r["name"]
        assert ev.get("image_checked_on"), r["name"]


def test_publishable_requires_cleared_terms(monkeypatch):
    """URL が公式でも、利用条件を確認した TCG でなければ公開しない（既定は空）。"""
    url = "https://www.pokemon-card.com/products/2025/images/M2.jpg"
    assert vp.IMAGE_USE_CLEARED == {}
    assert not vp.image_publishable("POKEMON", url)
    monkeypatch.setattr(vp, "IMAGE_USE_CLEARED", {"POKEMON": "test"})
    assert vp.image_publishable("POKEMON", url)
    assert not vp.image_publishable("POKEMON", "https://evil.example/a.jpg")
    assert not vp.image_publishable("ONE_PIECE", "https://www.onepiece-cardgame.com/x/img_item01.webp")
