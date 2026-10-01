"""新UIの「マイページ」（段階B: 仮ページ）。

ログイン機能は作らない（静的サイトのまま）。はじめかた・運営者向け情報への導線を置く。
"""

from __future__ import annotations

from src.content.ui import components as c


def render() -> str:
    return (
        '<section class="nu-page" data-nu-page="account" aria-labelledby="nu-account-title" hidden>'
        '<h1 id="nu-account-title" class="nu-page__title">マイページ</h1>'
        '<h2 class="nu-h2">使い方</h2>'
        '<ul class="nu-linklist">'
        f'<li>{c.button("はじめかた・ヘルプ", "beta/", kind="secondary", external=False)}</li>'
        f'<li>{c.button("現行版の表示に戻る", "./", kind="secondary", external=False)}</li>'
        '</ul>'
        '<h2 class="nu-h2" id="nu-operator" tabindex="-1">運営者向けの情報</h2>'
        '<p class="nu-lead">データの取得状況などの運営者向け情報は、今は現行版の Health に置いています。</p>'
        + c.button("取得状況（現行版）を見る", "./?from=new#tab-health", kind="link", external=False)
        + '<p class="nu-disclaimer">掲載情報は取得時点の参考です。購入・応募の前に必ず公式サイトでご確認ください。</p>'
        '</section>'
    )
