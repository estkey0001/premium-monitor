"""新UIの「商品検索」ページ（段階B: 仮ページ）。

段階D でジャンル・メーカー・条件の絞り込みを実装する。今はジャンルごとに
現行版の該当箇所へ案内するだけ。
"""

from __future__ import annotations

from src.content.ui import components as c

# (表示名, 現行UIの id)
GENRES = (
    ("TCG（ポケカ・ワンピース）", "category-tcg"),
    ("iPhone・スマホ", "category-beginner-iphone"),
    ("タブレット", "category-beginner-tablet"),
    ("PC・Mac", "category-pro-pc"),
    ("カメラ", "category-pro-camera"),
    ("ゲーム機", "category-beginner-game"),
)


def render() -> str:
    links = "".join(
        f'<li>{c.button(label, "./?from=new#" + anchor, kind="secondary")}</li>'
        for label, anchor in GENRES)
    return (
        '<section class="nu-page" data-nu-page="search" aria-labelledby="nu-search-title" hidden>'
        '<h1 id="nu-search-title" class="nu-page__title">商品検索</h1>'
        '<p class="nu-lead">絞り込み検索は次の段階で公開します。今はジャンルから現行版の一覧を開けます。</p>'
        f'<ul class="nu-linklist">{links}</ul>'
        '</section>'
    )
