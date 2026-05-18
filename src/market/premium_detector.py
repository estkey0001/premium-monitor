"""プレ値候補検出ロジック。

market_snapshotsから以下の条件でプレ値候補を抽出する:
- 公式定価より二次流通価格が20%以上高い
- 公式定価より買取価格が10%以上高い
- 公式販売がSOLD OUT
- 抽選販売になっている
- 中古在庫が極端に少ない
- 海外相場が国内定価より高い

Phase 7B-2:
- 初心者向け（beginner_easy）：公式で買え、買取が定価超え、利益5000円以上
- 上級者向け（advanced_high_profit）：利益3万以上だが抽選/SOLD OUT/高難度
- expert_only: 非常に高難度 + 高利益
"""

import logging
from datetime import datetime
from typing import Optional

import ulid

from src.db.repository import Repository
from src.models.market_snapshot import MarketSnapshotModel
from src.models.product_candidate import ProductCandidateModel

logger = logging.getLogger(__name__)


class PremiumDetector:
    """プレ値候補を検出する。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def detect_from_snapshots(self, snapshots: list[MarketSnapshotModel]) -> list[dict]:
        """snapshotsからプレ値候補を検出する。

        Phase 7B-2: 初心者向け案件も検出対象に含める。
        - 従来の高利益条件に加え、買取 > 定価 で利益5000円以上の低難度案件も検出
        """
        candidates = []

        for snap in snapshots:
            reasons = []

            # 条件1: 二次流通 > 定価+20%
            if (snap.official_price_jpy and snap.domestic_used_price_jpy
                    and snap.premium_gap_percent and snap.premium_gap_percent >= 20):
                reasons.append(f"二次流通プレ値 +{snap.premium_gap_percent}%")

            # 条件2: 買取 > 定価+10%
            if (snap.official_price_jpy and snap.domestic_buyback_price_jpy
                    and snap.domestic_buyback_price_jpy > snap.official_price_jpy * 1.10):
                gap = round((snap.domestic_buyback_price_jpy - snap.official_price_jpy) / snap.official_price_jpy * 100, 1)
                reasons.append(f"買取プレ値 +{gap}%")

            # 条件3: SOLD OUT / 抽選
            if snap.sale_method in ("lottery", "soldout"):
                reasons.append(f"販売方式: {snap.sale_method}")

            # 条件4: scarcity_score高
            if snap.scarcity_score >= 0.5:
                reasons.append(f"希少性スコア: {snap.scarcity_score:.1f}")

            # 条件5: 海外価格差
            if snap.overseas_gap_percent and snap.overseas_gap_percent >= 10:
                reasons.append(f"海外価格差 +{snap.overseas_gap_percent}%")

            # 条件6 (Phase 7B-2): 初心者向け — 買取 > 定価で利益5000円以上
            if (snap.official_price_jpy and snap.domestic_buyback_price_jpy
                    and snap.domestic_buyback_price_jpy > snap.official_price_jpy
                    and (snap.domestic_buyback_price_jpy - snap.official_price_jpy) >= 5000):
                buyback_profit = snap.domestic_buyback_price_jpy - snap.official_price_jpy
                if not any("買取プレ値" in r for r in reasons):
                    reasons.append(f"買取利益 +¥{buyback_profit:,}")

            if reasons:
                candidates.append({
                    "snapshot": snap,
                    "reasons": reasons,
                    "is_premium": snap.premium_score >= 0.4,
                    "is_scarce": snap.scarcity_score >= 0.5,
                    "user_level": snap.user_level,
                    "recommended_action": snap.recommended_action,
                })

        # overall_scoreで降順
        candidates.sort(key=lambda c: c["snapshot"].overall_score, reverse=True)
        return candidates

    def filter_by_user_level(
        self, candidates: list[dict], user_level: str
    ) -> list[dict]:
        """user_levelでフィルタする。

        Args:
            candidates: detect_from_snapshotsの結果
            user_level: "beginner" or "advanced"
        """
        if user_level == "beginner":
            return [
                c for c in candidates
                if c.get("user_level") in ("beginner_easy", "beginner_watch")
            ]
        elif user_level == "advanced":
            return [
                c for c in candidates
                if c.get("user_level") in ("advanced_high_profit", "expert_only")
            ]
        return candidates

    def _build_reason_for_beginner(self, snap: MarketSnapshotModel) -> str:
        """初心者向けの理由文を生成する。"""
        parts = []
        if snap.user_level == "beginner_easy":
            if snap.official_price_jpy and snap.domestic_buyback_price_jpy:
                profit = snap.domestic_buyback_price_jpy - snap.official_price_jpy
                parts.append(f"公式で通常購入可、買取利益+¥{profit:,}")
            if snap.sale_method == "normal":
                parts.append("通常販売で入手しやすい")
        elif snap.user_level == "beginner_watch":
            parts.append("利益見込みあり、在庫状況を要確認")

        return "。".join(parts) if parts else ""

    def _build_caution_note(self, snap: MarketSnapshotModel) -> str:
        """注意事項を生成する。"""
        notes = []
        if snap.user_level in ("advanced_high_profit", "expert_only"):
            if snap.sale_method == "lottery":
                notes.append("抽選販売のため当選が必要")
            elif snap.sale_method == "soldout":
                notes.append("SOLD OUT状態、再販情報を要確認")
            if snap.difficulty_score >= 0.6:
                notes.append("入手難易度が非常に高い")
        if snap.user_level == "beginner_watch":
            notes.append("在庫・買取価格は変動します。購入前に必ず確認してください")
        if snap.user_level == "beginner_easy":
            notes.append("在庫・買取価格は変動します")

        return "。".join(notes) if notes else ""

    def save_as_product_candidates(self, detected: list[dict]) -> int:
        """検出結果をproduct_candidatesに保存する（未登録分のみ）。"""
        existing = set(
            c.product_name.lower()
            for c in self.repo.list_product_candidates(limit=200)
        )
        saved = 0

        for d in detected:
            snap = d["snapshot"]
            if snap.product_name.lower() in existing:
                continue

            # 既にproductsに登録済みならスキップ
            if snap.product_id:
                continue

            candidate = ProductCandidateModel(
                id=str(ulid.new()),
                source_id="market_scan",
                product_name=snap.product_name,
                detected_keyword="; ".join(d["reasons"][:3]),
                detected_url="",
                confidence=min(snap.overall_score + 0.1, 1.0),
                genre=snap.category,
                brand=snap.brand,
                estimated_price=snap.official_price_jpy,
                notes=f"premium={snap.premium_score:.1f} scarcity={snap.scarcity_score:.1f} overall={snap.overall_score:.2f}",
                # Phase 7B-2
                user_level=snap.user_level,
                beginner_score=snap.beginner_score,
                difficulty_score=snap.difficulty_score,
                reason_for_beginner=self._build_reason_for_beginner(snap),
                caution_note=self._build_caution_note(snap),
            )
            try:
                self.repo.insert_product_candidate(candidate)
                saved += 1
                existing.add(snap.product_name.lower())
            except Exception as e:
                logger.debug("Candidate save skipped: %s", e)

        return saved
