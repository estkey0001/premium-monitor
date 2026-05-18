"""買取・海外相場リンク解決モジュール (Phase 15)。

優先順位:
  買取リンク:
    1. buyback_prices.buyback_url (link_verified=true)
    2. buyback_shop_links.yaml の category_urls[genre]
    3. buyback_shop_links.yaml の top_url
    4. 空欄 → LP上は「公式買取ページで確認してください」

  海外リンク:
    overseas_market_links.yaml のテンプレートを商品名で展開し、
    カテゴリ対応したマーケットのリンクを生成する。
    価格データがなくてもリンク生成可能。
"""

import logging
import urllib.parse
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# shop_id → CSV alias のマッピング（SHOP_MAP の逆引き）
_SHOP_ID_TO_ALIAS: dict[str, str] = {
    "src_janpara": "janpara",
    "src_iosys": "iosys",
    "src_geo": "geo",
    "src_sofmap": "sofmap",
    "src_mapcamera": "mapcamera",
    "src_fujiya": "fujiya",
    "src_kitamura": "kitamura",
    "src_mobile_ichiban": "mobile_ichiban",
    "src_kaitori_shouten": "kaitori_shouten",
    "src_kaitori_itchome": "kaitori_itchome",
}


@lru_cache(maxsize=1)
def _load_shop_links() -> dict:
    """buyback_shop_links.yaml を読み込む（キャッシュ）。"""
    path = PROJECT_ROOT / "config" / "buyback_shop_links.yaml"
    if not path.exists():
        logger.warning("buyback_shop_links.yaml が見つからない")
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def _load_overseas_links() -> dict:
    """overseas_market_links.yaml を読み込む（キャッシュ）。"""
    path = PROJECT_ROOT / "config" / "overseas_market_links.yaml"
    if not path.exists():
        logger.warning("overseas_market_links.yaml が見つからない")
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class LinkResolver:
    """商品・カテゴリ・店舗IDからリンクURLを解決する。"""

    # ──── 買取リンク ────────────────────────────────────

    def resolve_buyback_url(
        self,
        shop_id: str,
        genre: str,
        db_url: str = "",
        link_verified: bool = False,
    ) -> tuple[str, str]:
        """買取URLを解決して (url, link_type) を返す。

        link_type:
            "verified"  → DBのURLがlink_verified=true
            "category"  → YAMLのcategory_url
            "top"       → YAMLのtop_url
            "none"      → URLなし（LP上はテキスト表示）
        """
        # 1. DBのURLが検証済みであればそれを使う
        if db_url and link_verified:
            return db_url, "verified"

        # 2. YAML を検索
        shop_links = _load_shop_links()
        alias = _SHOP_ID_TO_ALIAS.get(shop_id, shop_id.replace("src_", ""))
        shop_cfg = shop_links.get(alias, {})

        if shop_cfg:
            # 2-a. category_urls から genre に対応するURL
            cat_urls = shop_cfg.get("category_urls", {})
            genre_key = self._normalize_genre(genre)
            if genre_key and cat_urls.get(genre_key):
                return cat_urls[genre_key], "category"
            # 2-b. 汎用カテゴリ（apple, game）にフォールバック
            for fallback_key in self._genre_fallback_keys(genre_key):
                if cat_urls.get(fallback_key):
                    return cat_urls[fallback_key], "category"
            # 2-c. top_url
            top = shop_cfg.get("top_url", "")
            if top:
                return top, "top"

        return "", "none"

    def resolve_buyback_url_for_row(
        self,
        shop_id: str,
        genre: str,
        row: dict,
    ) -> tuple[str, str]:
        """buyback_prices テーブルの1行から URL を解決する。"""
        return self.resolve_buyback_url(
            shop_id=shop_id,
            genre=genre,
            db_url=row.get("buyback_url") or row.get("url") or "",
            link_verified=bool(row.get("link_verified", False)),
        )

    # ──── 海外相場リンク ────────────────────────────────

    def get_overseas_links(
        self,
        product_name: str,
        genre: str,
        max_links: int = 6,
    ) -> list[dict]:
        """商品名とジャンルから海外相場リンクリストを生成する。

        Returns:
            list of {"name", "label", "icon", "url", "note", "priority"}
        """
        overseas = _load_overseas_links()
        genre_key = self._normalize_genre(genre)
        query = urllib.parse.quote_plus(product_name)

        result = []
        for market_id, cfg in overseas.items():
            cats = cfg.get("categories", [])
            if genre_key and genre_key not in cats:
                # genre_fallback でも試みる
                if not any(k in cats for k in self._genre_fallback_keys(genre_key)):
                    continue
            tmpl = cfg.get("search_url_template", "")
            if not tmpl:
                continue
            url = tmpl.replace("{query}", query)
            result.append({
                "market_id": market_id,
                "name": cfg.get("name", market_id),
                "label": cfg.get("label", cfg.get("name", market_id)),
                "icon": cfg.get("icon", "🌐"),
                "url": url,
                "note": cfg.get("note", ""),
                "priority": cfg.get("priority", 99),
            })

        result.sort(key=lambda x: x["priority"])
        return result[:max_links]

    # ──── ユーティリティ ────────────────────────────────

    @staticmethod
    def _normalize_genre(genre: str) -> str:
        """product.genre をYAMLキーに正規化する。"""
        genre = (genre or "").lower()
        _map = {
            "iphone": "iphone",
            "apple_watch": "apple_watch",
            "airpods": "airpods",
            "mac": "mac",
            "ipad": "ipad",
            "camera": "camera",
            "game_console": "game_console",
            "game": "game_console",
        }
        return _map.get(genre, genre)

    @staticmethod
    def _genre_fallback_keys(genre_key: str) -> list[str]:
        """ジャンルに対するフォールバックキー順序。"""
        _fallback = {
            "iphone": ["apple", "iphone"],
            "mac": ["apple", "mac"],
            "ipad": ["apple", "ipad"],
            "apple_watch": ["apple"],
            "airpods": ["apple"],
            "game_console": ["game", "game_console"],
            "camera": ["camera"],
        }
        return _fallback.get(genre_key, [])

    def link_type_label(self, link_type: str) -> str:
        """link_type を日本語ラベルに変換。"""
        return {
            "verified": "商品ページ",
            "category": "カテゴリ",
            "top": "公式トップ",
            "none": "未登録",
        }.get(link_type, link_type)


# シングルトン
_resolver = None


def get_resolver() -> LinkResolver:
    global _resolver
    if _resolver is None:
        _resolver = LinkResolver()
    return _resolver
