"""全ページ白に固定（2026-11-27）と、HOME の商品画像の検査（deploy-check #899）・在庫再開の行の画像の回帰テスト。"""
from __future__ import annotations

import re
from pathlib import Path

import scripts.deploy_check as dc
from src.content.ui import product_image as pi

ROOT = Path(__file__).resolve().parents[1]
# 公開ページを作るコード（docs/archive/ の転送ページ ARCHIVE_INDEX_HTML は過去アーカイブの扱いなので対象外）
GENERATORS = ("src/content/daily_lp_generator.py", "src/content/iphone_buyback_page.py", "src/content/camera_market_page.py",
              "src/content/camera_research_page.py", "src/content/tcg_hub_page.py", "scripts/generate_beta_report.py")


def test_every_page_generator_fixes_the_light_theme():
    for p in GENERATORS:
        s = (ROOT / p).read_text(encoding="utf-8")
        assert '<html lang="ja">' not in s, p                                     # data-theme の無い html を出さない
        assert 'data-theme="light"' in s, p
    bp = (ROOT / "scripts" / "build_public_lp.py").read_text(encoding="utf-8")
    report = bp.split('html_content = f"""', 1)[1].split('"""', 1)[0]           # collector_report.html の雛形
    assert '<html lang="ja" data-theme="light">' in report
    assert "#0f1117" not in report and "--bg: #ffffff" in report                   # 配色そのものが白（属性だけでは白にならない）
    beta = (ROOT / "scripts" / "generate_beta_report.py").read_text(encoding="utf-8")
    assert "prefers-color-scheme" not in beta and "--bg:#fff;" in beta
    for p in ("src/content/ui/shared_css.py", "src/content/ui/styles.py"):
        assert "color-scheme:light dark" not in (ROOT / p).read_text(encoding="utf-8"), p


def test_dark_css_is_only_under_the_not_light_guard():
    """ダークの CSS は :root:not([data-theme="light"]) の中だけ（data-theme="light" の全ページでは効かない）。"""
    from src.content.ui import design_tokens as t
    from src.content.ui import shared_css
    assert t.BASE_COLORS["bg"] == "#ffffff"
    css = shared_css.legacy_css()
    found = list(re.finditer(r"@media \(prefers-color-scheme:dark\)\{([^{]*)\{", css))
    assert found                                                                    # 空振りしない
    for m in re.finditer(r"@media \(prefers-color-scheme:dark\)\{([^{]*)\{", css):
        assert ':not([data-theme="light"])' in m.group(1), m.group(0)[:80]


def _thumb(src: str) -> str:
    return f'<span class="nu-thumb">{pi.img_tag(src, "テスト")}</span>'


def test_home_image_check_899_rejects_unofficial_or_uncleared_images(monkeypatch):
    from src.tcg import verified_products as vp
    ok = "https://www.pokemon-card.com/assets/images/card_images/large/x.png"
    assert dc.check_tcg_images(_thumb(ok), "x")                                       # 許可の記録が無い（本番）
    __import__("tests._image_permit", fromlist=["x"]).permit_all(monkeypatch)
    assert dc.check_tcg_images(_thumb(ok), "x") == []
    css = '<div style="background:url(https://www.pokemon-card.com/a/x.png)"></div>'
    assert dc.check_tcg_images(css, "x") == []                                        # 許可の記録があれば url() も可
    __import__("tests._image_permit", fromlist=["x"]).permit_none(monkeypatch)
    assert dc.check_tcg_images(css, "x") and dc.check_tcg_images('<img srcset="https://www.pokemon-card.com/a/x.webp 2x">', "x")
    __import__("tests._image_permit", fromlist=["x"]).permit_all(monkeypatch)
    assert dc.check_tcg_images(_thumb("https://shop.example.com/a.png"), "x")       # 公式以外のホスト
    __import__("tests._image_permit", fromlist=["x"]).permit_none(monkeypatch)
    assert dc.check_tcg_images(_thumb(ok), "x")                                       # 使うと決めていない TCG の画像
    bad_onerror = _thumb(ok).replace(f'onerror="{pi.IMG_ONERROR}"', 'onerror="alert(1)"')
    __import__("tests._image_permit", fromlist=["x"]).permit_all(monkeypatch)
    assert dc.check_tcg_images(bad_onerror, "x")


def test_image_tag_lets_the_official_site_see_the_embedding_origin():
    tag = pi.img_tag("https://www.pokemon-card.com/a.png", "x")
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in tag and "no-referrer" not in tag


def test_restock_rows_always_have_an_image():
    from datetime import datetime
    from src.content.ui import restock_page
    from src.content.ui.restock_view import RestockView
    from src.tcg.models import JST
    v = RestockView(key="k", product_id="p", category="camera", product_name='SONY α1 II "<b>"', variant="", condition="new",
                    retailer="ソニーストア", stock_state="IN_STOCK", previous_stock_state="OUT_OF_STOCK", restocked_at="",
                    first_seen_at="", last_checked_at="", last_success_at="", fresh_until="", price=None, price_observed_at="",
                    purchase_limit="", purchase_url="", source_url="", source_type="", event_type="")
    row = next(getattr(restock_page, n) for n in dir(restock_page) if n in ("_row", "row", "render_row"))(v, 0, datetime(2026, 11, 27, tzinfo=JST))
    assert '<span class="nu-thumb ph"' in row and "<svg" in row and "<b>" not in row


def test_image_check_catches_official_images_outside_img_src(monkeypatch):
    """許可の記録が無い公式画像は、srcset の 2 つ目以降・拡張子なし・実体参照の url()・image-set()・<source>・data-src・preload でも不可。
    <a href> のテキストリンクと、属性でも url() でもない JSON の中のリンク先は対象外。"""
    __import__("tests._image_permit", fromlist=["x"]).permit_none(monkeypatch)
    for h in ('<img src="data:," srcset="a.png 1x, https://www.pokemon-card.com/x/y.jpg 2x" onerror="">',
              '<div data-src="https://www.onepiece-cardgame.com/x/item"></div>',
              '<div style="background:url(&quot;https://www.pokemon-card.com/x/img&quot;)"></div>',
              '<style>.a{background-image:image-set("https://www.pokemon-card.com/a/b.webp" 1x)}</style>',
              '<picture><source srcset="https://www.pokemon-card.com/a/b.avif"></picture>',
              '<link rel="preload" as="image" href="https://www.pokemon-card.com/a/b.jpg">',
              '<video poster="//www.pokemon-card.com/a/b.jpg"></video>',
              '<meta property="og:image" content="https://www.pokemon-card.com/a/b.jpg">',
              '<svg><image href="https://www.onepiece-cardgame.com/a/b.webp"/></svg>',
              '<svg><image xlink:href="https://www.pokemon-card.com/a/b.png"/></svg>',
              '<object data="https://www.pokemon-card.com/a/b.svg"></object>'):
        assert any("権利者の利用許可" in x for x in dc.check_tcg_images(h, "x")), h
    ok = ('<a href="https://www.pokemon-card.com/ex/m4/">公式</a>'
          '<script>var vm={"info":"https://www.pokemon-card.com/info/x.html"}</script>')
    assert dc.check_tcg_images(ok, "x") == []
