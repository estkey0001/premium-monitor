"""カテゴリ横断スキャナー。

特定カテゴリ内の全商品について市場比較を実行し、
プレ値候補を検出する。
"""

import logging
from typing import Optional

from src.db.repository import Repository
from src.market.comparator import MarketComparator
from src.market.premium_detector import PremiumDetector

logger = logging.getLogger(__name__)

# カテゴリ → genreのマッピング
CATEGORY_GENRES = {
    "camera": ["camera"],
    "apple": ["iphone"],
    "game": ["game_console"],
    "pc": ["pc"],
    "all": None,  # 全カテゴリ
}


class CategoryScanner:
    """カテゴリ全体を横断してプレ値候補を検出する。"""

    def __init__(self, repository: Repository):
        self.repo = repository
        self.comparator = MarketComparator(repository)
        self.detector = PremiumDetector(repository)

    def scan(self, category: str = "all") -> dict:
        """カテゴリ内の全商品を比較し、プレ値候補を検出する。"""
        genres = CATEGORY_GENRES.get(category)
        if genres is None and category != "all":
            logger.warning("Unknown category: %s", category)
            genres = [category]

        # 全商品の比較実行
        if genres:
            snapshots = []
            for genre in genres:
                snapshots.extend(self.comparator.compare_all_products(category=genre))
        else:
            snapshots = self.comparator.compare_all_products()

        # プレ値候補検出
        detected = self.detector.detect_from_snapshots(snapshots)

        result = {
            "category": category,
            "total_products": len(snapshots),
            "premium_candidates": len(detected),
            "snapshots": snapshots,
            "detected": detected,
        }

        logger.info(
            "Category scan [%s]: %d products → %d premium candidates",
            category, len(snapshots), len(detected),
        )

        return result
