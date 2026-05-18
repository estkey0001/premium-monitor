"""マップカメラ Collector。

マップカメラはSPA（完全JS描画）のため、requestsでは取得不可。
Playwrightを使用してブラウザレンダリング後のDOMを取得する。

検索結果ページから以下を取得する:
- 中古販売価格（在庫あり品の最安値）
- 新品販売価格（ある場合）
- 在庫状態（SOLD OUT / 在庫あり）
- 商品点数

実ページ調査結果（2026-05-17）:
- 検索URL: /search?keyword=GR+IIIx&category=all&sell=used
- 商品名: aタグ内テキスト "RICOH (リコー) GR IIIx[ID: XXXX]"
- 価格: span.price テキスト "￥XXX,XXX(税込)"
- 在庫: "SOLD OUT" テキスト / なければ在庫あり
- ラベル: "新品", "中古", "新同品", "美品", "良品", "並品"
- 各商品は個別IDページ: /item/XXXXXXXXXXXX
"""

import json
import logging
import re
from datetime import datetime
from typing import Optional

import ulid

from src.collectors.base import BaseCollector
from src.models.observation import ObservationModel, PriceHistoryModel
from src.models.product import ProductModel
from src.models.source import ProductSourceConfigModel
from src.pipeline.normalizer import Normalizer

logger = logging.getLogger(__name__)


class MapCameraCollector(BaseCollector):
    """マップカメラ Collector（Playwright使用）。"""

    def collect(
        self, product: ProductModel, config: ProductSourceConfigModel
    ) -> Optional[ObservationModel]:
        url = config.target_url
        if not url:
            self.logger.error("No target_url configured for %s", product.id)
            return None

        started_at = datetime.now()

        # Playwrightでページを取得
        html = self._fetch_with_playwright(url)
        if html is None:
            self.log_collection(product.id, started_at, "error",
                                error_message="playwright fetch failed")
            return None

        try:
            result = self._parse_search_results(html, product, url)
        except Exception as e:
            self.logger.error("Parse error for %s: %s", url, e)
            self.log_collection(product.id, started_at, "error", error_message=str(e))
            return None

        if result["used_price"] is None and result["new_price"] is None:
            self.logger.warning("No price data for %s at %s", product.name, url)
            # SOLD OUTでも商品数は記録する
            if result["total_items"] > 0:
                self.logger.info("  -> %d items found but all SOLD OUT", result["total_items"])

            self.log_collection(product.id, started_at, "success",
                                error_message=f"all_sold_out ({result['total_items']} items)")

            # SOLD OUTでもobservation自体は記録する（在庫なし情報として価値がある）
            now = datetime.now()
            obs = ObservationModel(
                id=str(ulid.new()),
                product_id=product.id,
                source_id=self.source.id,
                observation_type="price",
                observed_at=now,
                is_in_stock=False,
                price=None,
                raw_text=json.dumps(result["raw"], ensure_ascii=False),
                raw_html_hash=self.hash_html(html),
                confidence=0.90,
            )
            self.repository.insert_observation(obs)
            return obs

        primary_price = result["used_price"] or result["new_price"]

        now = datetime.now()
        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type="price",
            observed_at=now,
            is_in_stock=result["is_in_stock"],
            price=primary_price,
            raw_text=json.dumps(result["raw"], ensure_ascii=False),
            raw_html_hash=self.hash_html(html),
            confidence=self._calc_confidence(result),
        )
        self.repository.insert_observation(obs)

        if result["used_price"]:
            self.repository.insert_price_history(PriceHistoryModel(
                id=str(ulid.new()), product_id=product.id, source_id=self.source.id,
                price_type="used", price=result["used_price"], recorded_at=now,
            ))
        if result["new_price"]:
            self.repository.insert_price_history(PriceHistoryModel(
                id=str(ulid.new()), product_id=product.id, source_id=self.source.id,
                price_type="retail", price=result["new_price"], recorded_at=now,
            ))

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "mapcamera | %s | used=¥%s | new=¥%s | stock=%s | items=%d",
            product.name,
            f"{result['used_price']:,}" if result['used_price'] else "N/A",
            f"{result['new_price']:,}" if result['new_price'] else "N/A",
            result["is_in_stock"],
            result["total_items"],
        )
        return obs

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """Playwrightでページを取得する。"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.error(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )
            return None

        self.logger.info("Fetching with Playwright: %s", url)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=self.session.headers.get("User-Agent", ""),
                    locale="ja-JP",
                )
                page = context.new_page()
                page.goto(url, wait_until="networkidle", timeout=30000)
                # SPAのレンダリングを待つ
                page.wait_for_timeout(3000)

                # Buyeeポップアップを閉じる
                try:
                    close_btn = page.locator('[class*="buyee"] button, .modal-close, [aria-label="Close"]')
                    if close_btn.count() > 0:
                        close_btn.first.click()
                        page.wait_for_timeout(500)
                except Exception:
                    pass

                html = page.content()
                browser.close()
                return html

        except Exception as e:
            self.logger.error("Playwright fetch failed: %s", e)
            return None

    def _parse_search_results(self, html: str, product: ProductModel, url: str) -> dict:
        result = {
            "used_price": None,
            "new_price": None,
            "is_in_stock": None,
            "total_items": 0,
            "in_stock_count": 0,
            "sold_out_count": 0,
            "url": url,
            "raw": {},
        }

        soup = self.parse_html(html)

        # 総商品数を取得 "52 商品中" テキスト
        count_match = re.search(r"(\d+)\s*商品中", html)
        if count_match:
            result["total_items"] = int(count_match.group(1))
            result["raw"]["total_items_text"] = count_match.group(0)

        # 全リンクからカメラ本体をフィルタ
        # パターン: "RICOH (リコー) GR IIIx[ID: XXXX]" のようなリンク
        camera_links = []
        for a in soup.find_all("a"):
            text = a.get_text()
            href = a.get("href", "")
            # キーワードマッチ＋アクセサリー除外
            if not any(kw.lower() in text.lower() for kw in product.keywords):
                continue
            if re.search(r"ケース|フィルム|レンズ|ファインダー|アダプター|バッテリー|ストラップ|グリップ|キャップ|フード", text):
                continue
            if "/item/" in href:
                camera_links.append(a)

        result["raw"]["camera_links_found"] = len(camera_links)

        # 各商品の情報を抽出
        used_prices = []
        new_prices = []

        for link in camera_links:
            # リンクの周辺要素（親の兄弟）から価格・状態を取得
            card = self._find_card_parent(link)
            if not card:
                continue

            card_text = card.get_text()

            # 価格取得: span.price テキスト
            price_el = card.select_one("span.price")
            price = None
            if price_el:
                price = Normalizer.parse_price(price_el.get_text())
            else:
                # フォールバック: カード内の全価格を取得
                prices = Normalizer.parse_price_multiple(card_text)
                # カメラ本体価格帯のみ（1万円以上）
                prices = [p for p in prices if p >= 10000]
                if prices:
                    price = prices[0]

            # SOLD OUT判定
            is_sold_out = "SOLD OUT" in card_text or "sold out" in card_text.lower()

            # 新品/中古判定
            is_used = bool(re.search(r"中古|新同品|美品|良品|並品", card_text))
            is_new = "新品" in card_text and not is_used

            if price and not is_sold_out:
                if is_used:
                    used_prices.append(price)
                elif is_new:
                    new_prices.append(price)
                else:
                    used_prices.append(price)  # デフォルトは中古扱い

            if is_sold_out:
                result["sold_out_count"] += 1
            else:
                result["in_stock_count"] += 1

        # 最安値を採用
        if used_prices:
            result["used_price"] = min(used_prices)
            result["raw"]["used_prices"] = sorted(used_prices)
        if new_prices:
            result["new_price"] = min(new_prices)
            result["raw"]["new_prices"] = sorted(new_prices)

        result["is_in_stock"] = result["in_stock_count"] > 0

        result["raw"]["in_stock_count"] = result["in_stock_count"]
        result["raw"]["sold_out_count"] = result["sold_out_count"]

        return result

    def _find_card_parent(self, element, max_depth: int = 6):
        """リンク要素から商品カードの親要素を見つける。"""
        el = element
        for _ in range(max_depth):
            el = el.parent
            if el is None or el.name == "body":
                return element.parent  # フォールバック
            # 商品カードは通常、複数の子要素（画像・タイトル・価格等）を含む
            children = list(el.children)
            # テキストノードを除外した子要素数
            elem_children = [c for c in children if hasattr(c, 'name') and c.name]
            if len(elem_children) >= 3:
                return el
        return element.parent

    def _calc_confidence(self, result: dict) -> float:
        base = 0.85
        if result.get("in_stock_count", 0) >= 3:
            base = 0.92
        return round(base, 2)
