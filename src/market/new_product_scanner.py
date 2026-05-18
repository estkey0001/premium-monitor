"""新商品・新モデル自動検出スキャナー (Phase 14)。

実サイトのスクレイピングは行わない（高頻度アクセス禁止）。
config/new_product_watchlist.yaml から候補を読み込み、
スコアリングして product_candidates テーブルに保存する。

将来の拡張:
- Apple Newsroom RSS フィード解析
- 公式ページのタイトル/h1 確認（低頻度）
"""

import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import ulid
import yaml

from src.db.repository import Repository
from src.models.product_candidate import ProductCandidateModel

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
JST = timezone(timedelta(hours=9))

# カテゴリ別の初心者向けスコア基準値
CATEGORY_BEGINNER_BASE: dict[str, float] = {
    "iphone": 0.85,
    "game_console": 0.80,
    "mac": 0.65,
    "ipad": 0.70,
    "apple_watch": 0.65,
    "camera": 0.40,  # カメラは知識が必要 → 上級者向け
    "airpods": 0.55,
}

# 販売方法別の転売期待スコア
SALE_METHOD_RESALE_SCORE: dict[str, float] = {
    "lottery": 0.95,
    "limited": 0.85,
    "preorder": 0.60,
    "normal": 0.40,
    "sold_out": 0.70,
}

# 販売方法別の入手難易度
SALE_METHOD_DIFFICULTY: dict[str, float] = {
    "lottery": 0.90,
    "limited": 0.80,
    "preorder": 0.30,
    "normal": 0.10,
    "sold_out": 0.95,
}


class NewProductScanner:
    """新商品候補スキャナー。"""

    def __init__(self, repository: Repository):
        self.repo = repository
        self._watchlist: Optional[dict] = None

    def _load_watchlist(self) -> dict:
        """ウォッチリスト設定を読み込む。"""
        if self._watchlist is not None:
            return self._watchlist
        watchlist_path = PROJECT_ROOT / "config" / "new_product_watchlist.yaml"
        if not watchlist_path.exists():
            logger.warning("new_product_watchlist.yaml が見つからない")
            return {"candidates": [], "watch_keywords": []}
        with open(watchlist_path, "r", encoding="utf-8") as f:
            self._watchlist = yaml.safe_load(f) or {}
        return self._watchlist

    def scan(self) -> dict:
        """新商品スキャンを実行する。

        Returns:
            dict: スキャン結果サマリ
        """
        result = {"new": 0, "updated": 0, "skipped": 0, "errors": []}
        watchlist = self._load_watchlist()
        candidates = watchlist.get("candidates", [])

        for item in candidates:
            try:
                self._process_candidate(item, result)
            except Exception as e:
                logger.error("候補処理エラー: %s — %s", item.get("product_name"), e)
                result["errors"].append(f"{item.get('product_name')}: {e}")

        logger.info(
            "NewProductScanner: new=%d updated=%d skipped=%d errors=%d",
            result["new"], result["updated"], result["skipped"], len(result["errors"])
        )
        return result

    def _process_candidate(self, item: dict, result: dict) -> None:
        """1候補アイテムを処理する。"""
        product_name = item.get("product_name", "").strip()
        if not product_name:
            result["skipped"] += 1
            return

        # 既存候補の確認（同名で pending/watching のものがあればスキップ）
        existing = self._find_existing(product_name)
        if existing and existing.status in ("pending", "watching", "approved"):
            result["skipped"] += 1
            return

        # スコア計算
        category = item.get("category", "")
        sale_method = item.get("sale_method", "normal")
        confidence = float(item.get("confidence", 0.5))

        beginner_score = self._calc_beginner_score(item)
        resale_score = self._calc_resale_score(item)
        difficulty_score = self._calc_difficulty_score(item)
        user_level = self._classify_user_level(beginner_score, resale_score, difficulty_score, category)
        reason = self._build_reason(item, user_level, beginner_score, resale_score)

        candidate = ProductCandidateModel(
            id=str(ulid.new()),
            source_id="src_watchlist",
            product_name=product_name,
            detected_keyword=item.get("detected_keyword", ""),
            detected_url=item.get("detected_url", ""),
            detected_at=datetime.now(tz=JST),
            confidence=confidence,
            status="pending",
            genre=category,
            category=category,
            brand=item.get("brand", ""),
            estimated_price=item.get("official_price"),
            official_price=item.get("official_price"),
            release_date=item.get("release_date", ""),
            reservation_start_at=item.get("reservation_start_at", ""),
            lottery_start_at=item.get("lottery_start_at", ""),
            lottery_end_at=item.get("lottery_end_at", ""),
            sale_method=sale_method,
            detected_source=item.get("detected_source", "watchlist"),
            beginner_score=beginner_score,
            resale_potential_score=resale_score,
            difficulty_score=difficulty_score,
            user_level=user_level,
            reason_for_beginner=reason,
            caution_note=item.get("notes", ""),
            notes=item.get("notes", ""),
        )

        try:
            self.repo.insert_product_candidate(candidate)
            result["new"] += 1
            logger.info("新候補追加: %s [%s] score=%.2f", product_name, user_level, resale_score)
        except Exception as e:
            logger.warning("insert_product_candidate失敗: %s", e)
            result["errors"].append(str(e))

    def _find_existing(self, product_name: str) -> Optional[ProductCandidateModel]:
        """同名の既存候補を検索する。"""
        try:
            all_candidates = self.repo.list_product_candidates(limit=500)
            for c in all_candidates:
                if c.product_name == product_name:
                    return c
        except Exception:
            pass
        return None

    def _calc_beginner_score(self, item: dict) -> float:
        """初心者向け度スコアを計算する（0.0〜1.0）。"""
        category = item.get("category", "")
        sale_method = item.get("sale_method", "normal")
        confidence = float(item.get("confidence", 0.5))

        base = CATEGORY_BEGINNER_BASE.get(category, 0.50)

        # 普通購入可能なら初心者向け+
        if sale_method in ("normal", "preorder"):
            base = min(1.0, base + 0.05)
        elif sale_method in ("lottery", "limited"):
            base = max(0.0, base - 0.15)

        # 公式価格が明確なら+
        if item.get("official_price"):
            base = min(1.0, base + 0.05)

        return round(base * confidence, 3)

    def _calc_resale_score(self, item: dict) -> float:
        """転売・せどり期待値スコアを計算する（0.0〜1.0）。"""
        sale_method = item.get("sale_method", "normal")
        confidence = float(item.get("confidence", 0.5))
        category = item.get("category", "")

        base = SALE_METHOD_RESALE_SCORE.get(sale_method, 0.40)

        # カメラは転売期待が高い
        if category == "camera":
            base = min(1.0, base + 0.10)

        # iPhone/ゲーム機は転売実績あり
        if category in ("iphone", "game_console"):
            base = min(1.0, base + 0.05)

        return round(base * confidence, 3)

    def _calc_difficulty_score(self, item: dict) -> float:
        """入手難易度スコアを計算する（0.0〜1.0）。"""
        sale_method = item.get("sale_method", "normal")
        return SALE_METHOD_DIFFICULTY.get(sale_method, 0.10)

    def _classify_user_level(
        self, beginner_score: float, resale_score: float, difficulty: float, category: str
    ) -> str:
        """ユーザーレベルを分類する。"""
        # 抽選・限定・高難易度は上級者向け
        if difficulty >= 0.80:
            if resale_score >= 0.70:
                return "expert_only"
            return "advanced_high_profit"

        # 初心者向け条件
        if beginner_score >= 0.60 and difficulty < 0.50:
            if resale_score >= 0.50:
                return "beginner_easy"
            return "beginner_watch"

        # カメラ系は基本上級者
        if category == "camera":
            return "advanced_high_profit"

        return "beginner_watch"

    def _build_reason(
        self, item: dict, user_level: str, beginner_score: float, resale_score: float
    ) -> str:
        """候補の理由文を生成する。"""
        parts = []
        sale_method = item.get("sale_method", "normal")
        category = item.get("category", "")

        method_label = {
            "lottery": "抽選販売のため入手困難",
            "limited": "数量限定モデル",
            "preorder": "予約販売・発売前注目",
            "normal": "定価購入可能",
            "sold_out": "品切れ・プレミア価格",
        }.get(sale_method, sale_method)
        parts.append(method_label)

        if category == "iphone":
            parts.append("iPhone は買取店対応が多く流動性が高い")
        elif category == "game_console":
            parts.append("ゲーム機は発売直後にプレミア価格になりやすい")
        elif category == "camera":
            parts.append("カメラは中古・海外相場で差益が出やすい")

        if resale_score >= 0.70:
            parts.append(f"転売期待スコア {resale_score:.0%}")

        return " / ".join(parts)

    def list_watching_candidates(self, limit: int = 10) -> list:
        """watching/pending 状態の候補をLP表示用に返す。"""
        try:
            candidates = self.repo.list_product_candidates(limit=200)
            result = [
                c for c in candidates
                if c.status in ("watching", "pending")
            ]
            result.sort(key=lambda c: c.resale_potential_score, reverse=True)
            return result[:limit]
        except Exception as e:
            logger.error("list_watching_candidates error: %s", e)
            return []
