"""新UIの「利益商品」ページ（段階B: 仮ページ）。

段階D でランキング・せどりルート・初心者・Pro をここへまとめる。
今は検証済み・参考の件数と、現行版への導線だけを出す。
"""

from __future__ import annotations

from src.content.ui import components as c
from src.content.ui.home import route_reject_reason


def render(profit_routes: dict | None) -> str:
    routes = profit_routes or {}
    main = [r for r in (routes.get("main_routes") or []) if not route_reject_reason(r)]
    ref = routes.get("reference_routes") or []
    if not routes:
        body = c.empty_state("NO_DATA", "利益商品の情報がまだありません",
                             "最初の取得が終わると表示されます")
    elif not main:
        body = c.empty_state("NO_ACTIVE", "現在、検証済みで利益が出る商品はありません",
                             f"参考情報（未検証）は {len(ref)}件あります")
    else:
        body = (f'<p class="nu-lead">検証済み {len(main)}件 ・ 参考（未検証） {len(ref)}件</p>')
    return (
        '<section class="nu-page" data-nu-page="profit" aria-labelledby="nu-profit-title" hidden>'
        '<h1 id="nu-profit-title" class="nu-page__title">利益商品</h1>'
        '<p class="nu-lead">表示モード: <span data-nu-mode-label>かんたん</span>'
        '（「かんたん」と「詳細」の切り替えは次の段階で公開します）</p>'
        f'{body}'
        + c.button("現行版のランキングを見る", "./?from=new#tab-ranking", kind="secondary")
        + c.button("現行版のせどりルートを見る", "./?from=new#tab-sedori", kind="secondary")
        + '</section>'
    )
