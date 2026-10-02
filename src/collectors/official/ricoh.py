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

        # ── 保存前の公式価格検証（最重要ルール）──
        from src.market.official_price_validator import validate_official_price
        vr = validate_official_price(
            source_id=self.source.id, url=url, http_status=200, canonical_url=url,
            product_name=product.name, model_number=getattr(product, "model_number", "") or "",
            keywords=getattr(product, "keywords", None),
            detected_name=product.name,
            detected_text=json.dumps(result.get("raw", {}), ensure_ascii=False),
            price=result.get("price"), currency="JPY",
            reference_price=getattr(product, "retail_price", 0) or None,
            link_type="item",
            multiple_candidates=False,
        )
        result["raw"]["validation"] = vr.as_dict()
        if not vr.accepted:
            self.logger.info("ricoh_official | %s | 公式価格を拒否: %s", product.name, vr.rejection_reason)
            self.log_collection(product.id, started_at, "rejected",
                                error_message=f"official_price_rejected:{vr.rejection_reason}")
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


        # 全商品カードのテキストを取得し、キーワードマッチで対象を特定
        # ページ全体からパースする（リストページの場合）
        cards = self._extract_cards(soup)
        result["raw"]["total_cards"] = len(cards)

        target_card = None
        # バリエーション区別キーワード（これがproduct.keywordsに含まれていないなら除外対象）
        variant_markers = ["HDF", "Monochrome", "Mono", "Urban", "Limited", "Edition", "Anniversary", "Kit",
                           "Package", "Bundle", "Set",
                           "限定", "セット", "キット", "記念", "パッケージ", "同梱"]
        product_kw_lower = [kw.lower() for kw in product.keywords]
        has_variant = any(
            vm.lower() in kw for kw in product_kw_lower for vm in variant_markers
        )
        # 1) 商品コード（keywords に S0001566 のような形で登録）で一致するカード
        codes = {kw for kw in product.keywords if re.fullmatch(r"S\d{7}", kw)}
        candidates = [c for c in cards if c.get("product_code") and c["product_code"] in codes]
        if not candidates:
            # 2) 商品名のキーワードで一致するカード（バリエーション違い・アクセサリーを除く）
            name_kws = [kw.lower() for kw in product.keywords if not re.fullmatch(r"S\d{7}", kw)]
            for card in cards:
                # 説明文（「セットアップが簡単」など）に当たらないよう、商品名だけで照合する
                text = card.get("name") or card.get("text", "")
                text_lower = text.lower()
                if re.search(r"ケース|ストラップ|バッテリー|アダプター|フード", text):
                    continue
                # 単語として一致させる（「GR III」が「GR IIIx」に部分一致しないように）
                if not any(re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text_lower)
                           for kw in name_kws):
                    continue
                # バリエーション除外: 「GR IV」で検索したとき「GR IV HDF」「GR IV Monochrome」にマッチしないようにする
                # 英語の語は単語として一致させる（説明文の「settings」などで誤除外しない）。日本語は部分一致
                if not has_variant and any(
                        (re.search(r"(?<![a-z])" + vm.lower() + r"(?![a-z])", text_lower) if vm.isascii()
                         else vm in text) for vm in variant_markers):
                    continue
                candidates.append(card)
        if len(candidates) == 1:
            target_card = candidates[0]
        elif len(candidates) > 1:
            # 複数の商品に一致した場合は、どれか1つを選ばない（別商品の価格を割り当てないため）
            result["raw"]["price_method"] = "ambiguous_cards"
            result["raw"]["ambiguous_codes"] = [c.get("product_code") for c in candidates]

        if target_card:
            result["price"] = target_card.get("price")
            result["is_in_stock"] = target_card.get("is_in_stock")
            result["lottery_status"] = target_card.get("lottery_status")
            result["raw"]["price_method"] = "matched_card"
            result["raw"]["matched_card"] = {
                k: v for k, v in target_card.items() if k != "element"
            }
        else:
            # 一致するカードが無ければ価格を取らない（ページ先頭の価格で代用しない）
            result["raw"].setdefault("price_method", "no_matching_card")

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

        価格要素（span.product__price--numeric）ごとに、それを含む商品ブロック
        （div.product__item--detail。無ければ商品詳細リンクを含む最も近い祖先）から、
        商品名・商品コード（pid=S0001551 など）・在庫状態を読む。
        価格と商品名を「並び順」や「前方の文字列」で推測して結びつけない
        （2026-10-02: 商品名が取れず first_on_page で GR IV 系3商品が同じ ¥259,800 になった）。
        """
        cards = []
        for price_el in soup.select("span.product__price--numeric"):
            block = price_el.find_parent("div", class_="product__item--detail")
            if block is None:
                block = price_el
                for _ in range(8):
                    block = block.parent
                    if block is None or block.find("a", href=re.compile("ProductDetail", re.I)):
                        break
            if block is None:
                continue
            link = block.find("a", href=re.compile("ProductDetail", re.I))
            href = link.get("href", "") if link else ""
            m = re.search(r"pid=([A-Za-z0-9]+)", href)
            status_el = block.select_one("span.product__status-text")
            status = status_el.get_text().strip() if status_el else None
            cards.append({
                "text": block.get_text(" ", strip=True),
                # 商品名（リンクの文字列）。照合は説明文ではなく商品名で行う
                "name": link.get_text(" ", strip=True) if link else "",
                "product_code": m.group(1) if m else "",
                "href": href,
                "price": Normalizer.parse_price(price_el.get_text()),
                "is_in_stock": (status != "SOLD OUT") if status else None,
                "status_text": status,
                "lottery_status": None,
            })
        return cards
