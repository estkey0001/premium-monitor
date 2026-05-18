"""RICOH Imaging Store Collector。

公式ストアから以下を取得する:
- 公式定価
- 在庫状態 (SOLD OUT / 在庫あり)
- 抽選販売ステータス
- 販売終了/製造完了情報

Chrome調査結果 (2026-05-17):
  URL: ricohimagingstore.com/Form/Product/ProductList.aspx?shop=0&cat=002002
  価格: span.product__price--numeric → "¥139,800"
  在庫: span.product__status-text → "SOLD OUT"
  抽選: span.product__icon--9 → "抽選販売"
  SSR: requestsで取得可能
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


class RicohOfficialCollector(BaseCollector):
    """RICOH Imaging Store Collector。"""

    def collect(
        self, product: ProductModel, config: ProductSourceConfigModel
    ) -> Optional[ObservationModel]:
        url = config.target_url
        if not url:
            self.logger.error("No target_url for %s", product.id)
            return None

        started_at = datetime.now()
        html = self.fetch_page(url)
        if html is None:
            self.log_collection(product.id, started_at, "error", error_message="fetch failed")
            return None

        try:
            result = self._parse(html, product, url)
        except Exception as e:
            self.logger.error("Parse error: %s", e)
            self.log_collection(product.id, started_at, "error", error_message=str(e))
            return None

        now = datetime.now()
        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type="official_price",
            observed_at=now,
            is_in_stock=result["is_in_stock"],
            price=result["price"],
            lottery_status=result.get("lottery_status"),
            raw_text=json.dumps(result["raw"], ensure_ascii=False),
            raw_html_hash=self.hash_html(html),
            confidence=0.99,  # 公式サイトは最高信頼度
        )
        self.repository.insert_observation(obs)

        # price_history に retail として保存
        if result["price"]:
            self.repository.insert_price_history(PriceHistoryModel(
                id=str(ulid.new()),
                product_id=product.id,
                source_id=self.source.id,
                price_type="retail",
                price=result["price"],
                recorded_at=now,
            ))

        # productsテーブルの公式価格フィールドを更新
        if result["price"]:
            stock_status = "SOLD OUT" if result["is_in_stock"] is False else "在庫あり"
            self.repository.mark_official_price_candidate(
                product.id,
                result["price"],
                self.source.id,
                stock_status=stock_status,
                is_lottery=result.get("lottery_status") in ("open", "closed"),
                is_discontinued=result.get("is_discontinued", False),
            )

        # 公式価格更新候補をログ
        if result["price"] and result["price"] != product.retail_price:
            self.logger.info(
                "OFFICIAL PRICE UPDATE CANDIDATE: %s current=¥%s official=¥%s",
                product.name,
                f"{product.retail_price:,}" if product.retail_price else "N/A",
                f"{result['price']:,}",
            )

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "ricoh_official | %s | price=¥%s | stock=%s | lottery=%s",
            product.name,
            f"{result['price']:,}" if result['price'] else "N/A",
            result["is_in_stock"],
            result.get("lottery_status", "N/A"),
        )
        return obs

    def _parse(self, html: str, product: ProductModel, url: str) -> dict:
        result = {
            "price": None,
            "is_in_stock": None,
            "lottery_status": None,
            "is_discontinued": False,
            "url": url,
            "raw": {},
        }

        soup = self.parse_html(html)

        # 商品カードのリストから対象商品をキーワードで特定
        # RICOH Imaging Storeのリストページは複数商品を含む
        # span.product__price--numeric, span.product__status-text, span.product__icon--9

        price_elements = soup.select("span.product__price--numeric")
        status_elements = soup.select("span.product__status-text")
        lottery_elements = soup.select("span.product__icon--9")
        product_names = soup.select("a[class*='product__name'], h2, h3")

        # 全商品カードのテキストを取得し、キーワードマッチで対象を特定
        # ページ全体からパースする（リストページの場合）
        cards = self._extract_cards(soup)
        result["raw"]["total_cards"] = len(cards)

        target_card = None
        # バリエーション区別キーワード（これがproduct.keywordsに含まれていないなら除外対象）
        variant_markers = ["HDF", "Monochrome", "Mono", "Urban", "Limited", "Edition"]
        product_kw_lower = [kw.lower() for kw in product.keywords]
        has_variant = any(
            vm.lower() in kw for kw in product_kw_lower for vm in variant_markers
        )

        for card in cards:
            text = card.get("text", "")
            text_lower = text.lower()
            # アクセサリー除外
            if re.search(r"ケース|ストラップ|バッテリー|アダプター|フード", text):
                continue
            # キーワードマッチ
            if not any(kw.lower() in text_lower for kw in product.keywords):
                continue
            # バリエーション除外: 「GR IV」で検索したとき「GR IV HDF」「GR IV Monochrome」にマッチしないようにする
            if not has_variant:
                if any(vm.lower() in text_lower for vm in variant_markers):
                    continue
            target_card = card
            break

        if target_card:
            result["price"] = target_card.get("price")
            result["is_in_stock"] = target_card.get("is_in_stock")
            result["lottery_status"] = target_card.get("lottery_status")
            result["raw"]["matched_card"] = {
                k: v for k, v in target_card.items() if k != "element"
            }
        else:
            # フォールバック: ページ全体から最初の価格を取得
            if price_elements:
                result["price"] = Normalizer.parse_price(price_elements[0].get_text())
                result["raw"]["price_method"] = "first_on_page"
            if status_elements:
                status_text = status_elements[0].get_text().strip()
                result["is_in_stock"] = status_text != "SOLD OUT"
                result["raw"]["status_text"] = status_text
            if lottery_elements:
                result["lottery_status"] = "closed"  # デフォルトclosed
                result["raw"]["has_lottery_label"] = True

        # 抽選状態の詳細判定
        page_text = soup.get_text()
        if "抽選販売エントリー受付中" in page_text:
            result["lottery_status"] = "open"
        elif "抽選販売エントリー受付は終了" in page_text:
            result["lottery_status"] = "closed"
        elif "次回の予定は" in page_text and "未定" in page_text:
            result["lottery_status"] = "closed"
            result["raw"]["next_lottery"] = "未定"

        # 販売終了/製造完了
        if "販売終了" in page_text:
            result["is_discontinued"] = True
        if "製造完了" in page_text or "生産完了" in page_text:
            result["is_discontinued"] = True
            result["raw"]["production_ended"] = True

        return result

    def _extract_cards(self, soup) -> list[dict]:
        """ページ内の商品カードを全て抽出する。

        戦略: 商品名リンクを起点に、直後の価格・状態要素をペアリングする。
        リンクのhrefにProductDetailを含む <a> タグを商品名として使う。
        """
        cards = []

        # 商品名リンク（hrefパターンを複数対応）
        all_names = soup.select("a[href*='ProductDetail']")
        if not all_names:
            all_names = soup.select("a[href*='productdetail']")
        if not all_names:
            all_names = soup.select("a[href*='Product/']")

        # 価格と状態の全要素
        all_prices = soup.select("span.product__price--numeric")
        all_statuses = soup.select("span.product__status-text")

        if all_names and len(all_names) == len(all_prices):
            # 名前と価格の数が一致 → インデックスでペアリング
            for i, name_el in enumerate(all_names):
                card = {"text": name_el.get_text().strip()}
                card["price"] = Normalizer.parse_price(all_prices[i].get_text())
                if i < len(all_statuses):
                    status = all_statuses[i].get_text().strip()
                    card["is_in_stock"] = status != "SOLD OUT"
                    card["status_text"] = status
                card["lottery_status"] = None
                cards.append(card)
        elif all_prices:
            # フォールバック: 価格要素の前方テキストを使ってカードを組み立てる
            # HTMLを文字列として分割し、各価格の前のテキストを商品名として扱う
            html_str = str(soup)
            for i, price_el in enumerate(all_prices):
                price_html = str(price_el)
                idx = html_str.find(price_html)
                if idx < 0:
                    continue
                # 価格の前200文字から商品名を探す
                before = html_str[max(0, idx - 500):idx]
                # <a>タグのテキストを抽出
                name_match = re.findall(r"<a[^>]*>([^<]+)</a>", before)
                card_text = name_match[-1].strip() if name_match else ""

                card = {
                    "text": card_text,
                    "price": Normalizer.parse_price(price_el.get_text()),
                }
                if i < len(all_statuses):
                    status = all_statuses[i].get_text().strip()
                    card["is_in_stock"] = status != "SOLD OUT"
                    card["status_text"] = status
                card["lottery_status"] = None
                cards.append(card)

        return cards
