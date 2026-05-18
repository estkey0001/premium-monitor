"""新製品候補スキャナー。

公式サイトの商品リストや製品ページから、未登録の新製品候補を検出する。
自動でproductsには追加せず、product_candidatesとして保存する。
"""

import logging
import re
from datetime import datetime
from typing import Optional

import ulid

from src.db.repository import Repository
from src.models.product_candidate import ProductCandidateModel
from src.pipeline.normalizer import Normalizer

logger = logging.getLogger(__name__)

# 新製品検出キーワード
NEW_PRODUCT_KEYWORDS = [
    "新製品", "新発売", "発売予定", "予約開始", "抽選販売",
    "先行販売", "開発発表", "正式発表", "後継機",
    "Mark II", "Mark III", "IV", "V", "Pro", "Max", "Ultra",
    "Limited", "HDF", "Monochrome", "NEW",
]

# ブランド→ジャンルマッピング
BRAND_GENRE_MAP = {
    "RICOH": "camera", "PENTAX": "camera", "FUJIFILM": "camera",
    "Canon": "camera", "Nikon": "camera", "Sony": "camera",
    "Leica": "camera", "Panasonic": "camera", "OM SYSTEM": "camera",
    "Apple": "iphone", "iPhone": "iphone", "Mac": "pc", "iPad": "iphone",
    "Nintendo": "game_console", "PlayStation": "game_console", "Xbox": "game_console",
    "Surface": "pc", "Dell": "pc", "Lenovo": "pc",
    "ASUS": "pc", "MSI": "pc", "HP": "pc", "Alienware": "pc",
}


class ProductScanner:
    """新製品候補スキャナー。"""

    def __init__(self, repository: Repository):
        self.repository = repository

    def scan_from_html(
        self,
        html: str,
        source_id: str,
        url: str,
        brand: str = "",
    ) -> list[ProductCandidateModel]:
        """HTML内から新製品候補を検出する。"""
        soup_text = html  # 簡易テキスト抽出
        # HTMLタグを除去
        clean = re.sub(r"<[^>]+>", " ", soup_text)
        clean = re.sub(r"\s+", " ", clean)

        candidates = []
        existing_products = self.repository.list_products(active_only=False)
        existing_names = set(p.name.lower() for p in existing_products)
        existing_keywords = set()
        for p in existing_products:
            for kw in p.keywords:
                existing_keywords.add(kw.lower())

        # 製品名パターンで検出
        product_patterns = self._get_product_patterns(brand)

        for pattern, conf, genre in product_patterns:
            for match in re.finditer(pattern, clean, re.IGNORECASE):
                name = match.group(0).strip()
                # 既存商品と重複チェック
                if name.lower() in existing_names:
                    continue
                if any(kw in name.lower() for kw in existing_keywords if len(kw) > 3):
                    continue

                # キーワードマッチ
                detected_kw = ""
                for kw in NEW_PRODUCT_KEYWORDS:
                    if kw.lower() in name.lower() or kw.lower() in clean[max(0, match.start()-100):match.end()+100].lower():
                        detected_kw = kw
                        break

                candidate = ProductCandidateModel(
                    id=str(ulid.new()),
                    source_id=source_id,
                    product_name=name[:100],
                    detected_keyword=detected_kw,
                    detected_url=url,
                    confidence=conf,
                    genre=genre or BRAND_GENRE_MAP.get(brand, ""),
                    brand=brand,
                )

                # 価格検出
                price_context = clean[match.end():match.end()+200]
                price = Normalizer.parse_price(price_context) if price_context else None
                if price and 1000 < price < 10_000_000:
                    candidate.estimated_price = price

                candidates.append(candidate)

        return candidates

    def scan_ricoh_store(self, html: str, url: str) -> list[ProductCandidateModel]:
        """RICOH Imaging Store の商品リストから候補を検出する。"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        candidates = []
        existing = set(p.name.lower() for p in self.repository.list_products(active_only=False))

        # RICOH Store固有のセレクタ
        name_els = soup.select("a[href*='ProductDetail']")
        price_els = soup.select("span.product__price--numeric")
        status_els = soup.select("span.product__status-text")
        lottery_els = soup.select("span.product__icon--9")

        for i, name_el in enumerate(name_els):
            name = name_el.get_text().strip()
            # アクセサリー除外
            if re.search(r"ケース|ストラップ|バッテリー|アダプター|フード|リング", name):
                continue

            # 既存商品チェック
            is_existing = False
            for en in existing:
                if en in name.lower() or name.lower() in en:
                    is_existing = True
                    break
            if is_existing:
                continue

            price = None
            if i < len(price_els):
                price = Normalizer.parse_price(price_els[i].get_text())

            is_lottery = i < len(lottery_els) and "抽選" in lottery_els[i].get_text()
            is_new = "NEW" in name or any(
                el.get_text().strip() == "NEW"
                for el in name_el.parent.select("span") if el
            ) if name_el.parent else False

            kw = "抽選販売" if is_lottery else ("NEW" if is_new else "新製品候補")

            candidate = ProductCandidateModel(
                id=str(ulid.new()),
                source_id="src_ricoh_imaging",
                product_name=name[:100],
                detected_keyword=kw,
                detected_url=url,
                confidence=0.8 if is_lottery or is_new else 0.5,
                genre="camera",
                brand="RICOH",
                estimated_price=price,
            )
            candidates.append(candidate)

        return candidates

    def save_candidates(self, candidates: list[ProductCandidateModel]) -> int:
        """候補をDBに保存する。既存重複はスキップ。"""
        saved = 0
        for c in candidates:
            try:
                self.repository.insert_product_candidate(c)
                saved += 1
                logger.info(
                    "New candidate: %s (%s) from %s [%s]",
                    c.product_name, c.brand, c.source_id, c.detected_keyword,
                )
            except Exception as e:
                logger.debug("Candidate insert skipped: %s", e)
        return saved

    def _get_product_patterns(self, brand: str) -> list[tuple]:
        """ブランド別の製品名パターンを返す。(regex, confidence, genre)"""
        patterns = []
        if brand in ("RICOH", ""):
            patterns.extend([
                (r"RICOH\s+GR\s+[IVX]+\s*(?:HDF|Monochrome|Urban|Limited)?", 0.8, "camera"),
                (r"PENTAX\s+[A-Z]\w+(?:\s+\w+)?", 0.6, "camera"),
            ])
        if brand in ("FUJIFILM", ""):
            patterns.extend([
                (r"FUJIFILM\s+X[A-Z]?\d+\w*(?:\s+\w+)?", 0.7, "camera"),
                (r"FUJIFILM\s+GFX\s*\d+\w*", 0.7, "camera"),
            ])
        if brand in ("Canon", ""):
            patterns.append((r"Canon\s+EOS\s+R\d+\w*(?:\s+\w+)?", 0.7, "camera"))
        if brand in ("Nikon", ""):
            patterns.append((r"Nikon\s+Z\s*\d+\w*(?:\s+\w+)?", 0.7, "camera"))
        if brand in ("Apple", ""):
            patterns.extend([
                (r"iPhone\s+\d+\s*(?:Pro\s*Max|Pro|Plus|mini)?", 0.7, "iphone"),
                (r"MacBook\s+(?:Air|Pro)\s*(?:M\d+)?", 0.6, "pc"),
            ])
        if brand in ("Nintendo", ""):
            patterns.append((r"Nintendo\s+Switch\s*\d*\s*(?:Pro|Lite|OLED)?", 0.7, "game_console"))
        if brand in ("Sony", "PlayStation", ""):
            patterns.append((r"PlayStation\s*\d+\s*(?:Pro|Slim)?", 0.7, "game_console"))
        return patterns
