"""新UIのナビゲーション（上部ナビ・ボトムナビ・旧ハッシュの読み替え）。

ナビの項目はここで1回だけ定義し、上部ナビとボトムナビの両方をここから作る。
管理者向けの画面（取得状況など）は一般のナビに出さない。

サイトの構造（UI Phase 1）: HOME / 利益商品 / 抽選・予約 / 在庫再開 / せどりルート。
ジャンル（category）は独立したタブではなく、URL の category= で HOME と各一覧の絞り込みに使う。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from src.content.ui.components import esc


@dataclass(frozen=True)
class NavItem:
    page: str
    label: str        # 上部ナビの文言
    short: str        # ボトムナビの文言（短い）
    icon: str         # icons.py の名前


# 上部ナビ（デスクトップ）
NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("home", "HOME", "HOME", "home"),
    NavItem("opportunities", "利益商品", "利益", "trend"),
    NavItem("lottery", "抽選・予約", "抽選", "ticket"),
    NavItem("restock", "在庫再開", "在庫", "package"),
    NavItem("routes", "せどりルート", "ルート", "route"),
)
# ボトムナビ（モバイル。5項目まで。せどりルート・ジャンル・検索は「メニュー」から）
BOTTOM_ITEMS: tuple[NavItem, ...] = (
    NAV_ITEMS[0], NAV_ITEMS[1], NAV_ITEMS[2], NAV_ITEMS[3],
    # ジャンルの「その他」と紛れないよう「メニュー」と呼ぶ
    NavItem("more", "メニュー", "メニュー", "more"),
)

# ページの一覧（ナビに無いページも含む）。account は旧ハッシュ（#tab-health）からだけ開く
PAGES: tuple[str, ...] = ("home", "opportunities", "lottery", "restock", "routes", "more", "search", "account",
                          "product", "mypage")
DEFAULT_PAGE = "home"
# 段階B の URL（?page=profit）を新しいページへ読み替える
PAGE_ALIASES: dict[str, str] = {"profit": "opportunities"}

# 旧UIのハッシュ → 新UIのページ（と、必要なら表示モード・ジャンル）
# 現行UIの id をそのまま受け付ける（外部・通知・note からのリンクを切らさない）
LEGACY_HASH_MAP: dict[str, dict[str, str]] = {
    "tab-lottery": {"page": "lottery"},
    "tab-ranking": {"page": "opportunities"},
    "tab-sedori": {"page": "routes"},
    "tab-advanced": {"page": "opportunities", "mode": "pro"},
    "tab-pro": {"page": "opportunities", "mode": "pro"},
    "tab-beginner": {"page": "opportunities", "mode": "easy"},
    "tab-health": {"page": "account", "focus": "operator"},
}

# id の前方一致で読み替えるもの（category-* / product-*）
LEGACY_PREFIX_MAP: tuple[tuple[str, dict[str, str]], ...] = (
    ("category-tcg", {"page": "lottery", "category": "tcg"}),
    ("category-lottery", {"page": "lottery"}),
    ("category-beginner-iphone", {"page": "opportunities", "category": "smartphone"}),
    ("category-beginner-camera", {"page": "opportunities", "category": "camera"}),
    ("category-pro-camera", {"page": "opportunities", "category": "camera"}),
    ("category-beginner-game", {"page": "opportunities", "category": "game"}),
    ("category-pro-pc", {"page": "opportunities", "category": "pc"}),
    ("category-beginner-", {"page": "opportunities"}),
    ("category-pro-", {"page": "opportunities"}),
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


def page_href(page: str, *, category: str | None = None) -> str:
    """新UIのページの URL（サイト内の相対パス）。HOME は page= を省く。"""
    q = {"ui": "new"}
    if page != DEFAULT_PAGE:
        q["page"] = page
    if category and category != "all":
        q["category"] = category
    return "?" + urlencode(q)


def _icon(name: str, size: int) -> str:
    from src.content.ui.icons import icon
    return icon(name, size=size)


def top_nav() -> str:
    """768px 以上で表示する上部ナビ。HOME 以外はジャンル（category）を保って移動する。"""
    links = "".join(
        f'<a class="nu-topnav__link" href="{esc(page_href(i.page))}" data-nu-nav="{esc(i.page)}"'
        f'{"" if i.page == DEFAULT_PAGE else " data-nu-keepcat"}>{esc(i.label)}</a>'
        for i in NAV_ITEMS)
    return f'<nav class="nu-topnav" aria-label="メインメニュー">{links}</nav>'


def bottom_nav() -> str:
    """768px 未満で画面下に固定するボトムナビ（5項目・各 44px 以上）。"""
    links = "".join(
        f'<a class="nu-bottomnav__link" href="{esc(page_href(i.page))}" data-nu-nav="{esc(i.page)}"'
        f'{"" if i.page == DEFAULT_PAGE else " data-nu-keepcat"}>'
        f'<span class="nu-bottomnav__icon">{_icon(i.icon, 22)}</span>'
        f'<span class="nu-bottomnav__label">{esc(i.short)}</span></a>'
        for i in BOTTOM_ITEMS)
    return f'<nav class="nu-bottomnav" aria-label="メインメニュー（下部）">{links}</nav>'


def legacy_map_json() -> str:
    """ブラウザ側で使う読み替え表（JSON）。"""
    import json
    return json.dumps({"exact": LEGACY_HASH_MAP,
                       "prefix": [[p, t] for p, t in LEGACY_PREFIX_MAP],
                       "pages": list(PAGES), "aliases": PAGE_ALIASES}, ensure_ascii=False)
