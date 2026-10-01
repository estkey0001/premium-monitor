"""新UIのナビゲーション（上部ナビ・ボトムナビ・旧ハッシュの読み替え）。

ナビの項目はここで1回だけ定義し、上部ナビとボトムナビの両方をここから作る
（現行UIのようにドロワーとタブで項目が食い違わないようにする）。
管理者向けの画面は一般のナビに出さない。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.content.ui.components import esc


@dataclass(frozen=True)
class NavItem:
    page: str
    label: str        # 上部ナビの文言
    short: str        # ボトムナビの文言（短い）
    icon: str


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("home", "HOME", "HOME", "🏠"),
    NavItem("lottery", "抽選・販売", "抽選", "🎫"),
    NavItem("profit", "利益商品", "利益", "💰"),
    NavItem("search", "商品検索", "検索", "🔍"),
    NavItem("account", "マイページ", "マイ", "👤"),
)

PAGES: tuple[str, ...] = tuple(i.page for i in NAV_ITEMS)
DEFAULT_PAGE = "home"

# 旧UIのハッシュ → 新UIのページ（と、必要なら表示モード）
# 現行UIの id をそのまま受け付ける（外部・通知・note からのリンクを切らさない）
LEGACY_HASH_MAP: dict[str, dict[str, str]] = {
    "tab-lottery": {"page": "lottery"},
    "tab-ranking": {"page": "profit"},
    "tab-sedori": {"page": "profit"},
    "tab-advanced": {"page": "profit", "mode": "pro"},
    "tab-pro": {"page": "profit", "mode": "pro"},
    "tab-beginner": {"page": "profit", "mode": "easy"},
    "tab-health": {"page": "account", "focus": "operator"},
}

# id の前方一致で読み替えるもの（category-* / product-*）
LEGACY_PREFIX_MAP: tuple[tuple[str, dict[str, str]], ...] = (
    ("category-tcg", {"page": "lottery"}),
    ("category-lottery", {"page": "lottery"}),
    ("category-beginner-", {"page": "search"}),
    ("category-pro-", {"page": "search"}),
    ("product-", {"page": "search"}),
)


def resolve_legacy_hash(hash_value: str) -> dict[str, str] | None:
    """旧ハッシュ（先頭の # は有っても無くてもよい）を新UIの行き先に読み替える。"""
    key = (hash_value or "").lstrip("#")
    if not key:
        return None
    if key in LEGACY_HASH_MAP:
        return dict(LEGACY_HASH_MAP[key])
    for prefix, target in LEGACY_PREFIX_MAP:
        if key.startswith(prefix):
            return dict(target)
    return None


def page_href(page: str) -> str:
    return f"?ui=new&page={page}"


def top_nav() -> str:
    """900px 以上で表示する上部ナビ。"""
    links = "".join(
        f'<a class="nu-topnav__link" href="{esc(page_href(i.page))}" data-nu-nav="{esc(i.page)}">'
        f'<span aria-hidden="true">{esc(i.icon)}</span> {esc(i.label)}</a>'
        for i in NAV_ITEMS)
    return f'<nav class="nu-topnav" aria-label="メインメニュー">{links}</nav>'


def bottom_nav() -> str:
    """640px 未満で画面下に固定するボトムナビ（各項目 44px 以上）。"""
    links = "".join(
        f'<a class="nu-bottomnav__link" href="{esc(page_href(i.page))}" data-nu-nav="{esc(i.page)}"'
        f' aria-label="{esc(i.label)}">'
        f'<span class="nu-bottomnav__icon" aria-hidden="true">{esc(i.icon)}</span>'
        f'<span class="nu-bottomnav__label">{esc(i.short)}</span></a>'
        for i in NAV_ITEMS)
    return f'<nav class="nu-bottomnav" aria-label="メインメニュー（下部）">{links}</nav>'


def legacy_map_json() -> str:
    """ブラウザ側で使う読み替え表（JSON）。"""
    import json
    return json.dumps({"exact": LEGACY_HASH_MAP,
                       "prefix": [[p, t] for p, t in LEGACY_PREFIX_MAP],
                       "pages": list(PAGES)}, ensure_ascii=False)
