"""スコアリングエンジン。

Observationに対して以下を計算する:
1. 想定利益 (estimated_profit)
2. alert_type 判定
3. S/A/B/C ランク判定

alert_type:
  stock_available   - 在庫復活
  stock_unavailable - 在庫なし→なし継続（低優先）
  price_premium     - 二次流通価格が定価超え（利益あり）
  buyback_premium   - 買取価格が定価超え
  buyback_surge     - 買取価格急騰
  lottery_open      - 抽選開始
  sold_out          - SOLD OUT検知
  market_signal     - その他の市場シグナル
"""

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

import yaml
from pathlib import Path

from src.db.repository import Repository
from src.models.observation import ObservationModel
from src.models.product import ProductModel
from src.models.source import SourceModel

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class ScoringResult:
    """スコアリング結果。"""
    estimated_profit: Optional[int] = None
    profit_score: float = 0.0
    confidence: float = 0.0
    change_score: float = 0.0
    total_score: float = 0.0
    alert_rank: str = "C"
    alert_type: str = "market_signal"
    should_notify: bool = False
    details: dict = field(default_factory=dict)


class Scorer:
    """スコアリングエンジン。"""

    DEFAULT_FEE_RATE = 0.10
    DEFAULT_SHIPPING = 1500

    def __init__(self, repository: Repository, config_path: Optional[str] = None):
        self.repository = repository
        self.config = self._load_config(config_path)

    def _load_config(self, config_path: Optional[str] = None) -> dict:
        path = config_path or (PROJECT_ROOT / "config" / "scoring_rules.yaml")
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)["scoring"]

    def _get_effective_retail_price(self, product: ProductModel) -> Optional[int]:
        """利益計算に使う定価を決定する。

        優先順位:
        1. 公式サイトから取得した最新定価 (official_price)
        2. products.retail_price（手入力）
        3. 不明ならNone
        """
        if product.official_price and product.official_price > 0:
            return product.official_price
        if product.retail_price and product.retail_price > 0:
            return product.retail_price
        return None

    def _has_verified_retail_price(self, product: ProductModel) -> bool:
        """定価が検証済み（公式 or 手入力）かどうか。"""
        return self._get_effective_retail_price(product) is not None

    def score(
        self,
        observation: ObservationModel,
        product: ProductModel,
        source: SourceModel,
    ) -> ScoringResult:
        """1件のObservationをスコアリングする。"""
        r = ScoringResult()

        # 1. alert_type 判定（利益計算より先に行う）
        self._determine_alert_type(r, observation, product)

        # 2. 想定利益
        self._calc_profit(r, observation, product)

        # 3. 利益スコア (0.0〜1.0)
        self._calc_profit_score(r)

        # 4. confidence
        self._calc_confidence(r, observation, source)

        # 5. 変化検知スコア
        self._calc_change_score(r, observation)

        # 6. 総合スコア
        w = self.config["weights"]
        r.total_score = round(
            r.profit_score * w["profit"]
            + r.change_score * w["change"]
            + r.confidence * w["confidence"],
            3,
        )

        # 7. ランク判定
        self._determine_rank(r, observation)

        logger.info(
            "Scored: %s x %s | type=%s rank=%s profit=%s score=%.2f",
            product.id, source.id, r.alert_type, r.alert_rank,
            f"¥{r.estimated_profit:,}" if r.estimated_profit is not None else "N/A",
            r.total_score,
        )
        return r

    # ===== alert_type =====

    def _determine_alert_type(
        self, r: ScoringResult, obs: ObservationModel, product: ProductModel
    ) -> None:
        # 抽選
        if obs.lottery_status == "open":
            r.alert_type = "lottery_open"
            return

        # 在庫復活判定: 前回なし→今回あり
        prev = self._get_previous(obs)
        if obs.is_in_stock is True and prev and prev.is_in_stock is False:
            r.alert_type = "stock_available"
            return

        # 在庫あり + 価格が定価超え → price_premium
        retail = self._get_effective_retail_price(product)
        if obs.is_in_stock is True and obs.price and retail:
            if obs.price > retail * 1.05:
                r.alert_type = "price_premium"
                return

        # 買取価格が定価超え
        if obs.buyback_price and retail:
            if obs.buyback_price > retail:
                r.alert_type = "buyback_premium"
                return
            # 買取急騰
            if prev and prev.buyback_price:
                change = (obs.buyback_price - prev.buyback_price) / prev.buyback_price
                if change >= 0.10:
                    r.alert_type = "buyback_surge"
                    return

        # SOLD OUT
        if obs.is_in_stock is False and obs.price is None:
            r.alert_type = "sold_out"
            return

        # 在庫なし継続
        if obs.is_in_stock is False:
            r.alert_type = "stock_unavailable"
            return

        # 在庫あり + 定価帯の価格 → 二次流通チェック
        if obs.price and retail and obs.price > retail:
            r.alert_type = "price_premium"
            return

        r.alert_type = "market_signal"

    # ===== 想定利益 =====

    def _calc_profit(
        self, r: ScoringResult, obs: ObservationModel, product: ProductModel
    ) -> None:
        retail = self._get_effective_retail_price(product)
        if not retail:
            r.details["no_retail_price"] = True
            return

        fee_rate = self.config["fee_defaults"]["platform_fee_rate"]
        shipping = self.config["fee_defaults"]["shipping_fee"]

        # パターン1: 買取価格ベース（手数料なし）
        buyback = obs.buyback_price
        if not buyback:
            # 他ソースの最新買取価格を参照
            bp_records = self.repository.list_price_history(
                product_id=obs.product_id, price_type="buyback", limit=5
            )
            if bp_records:
                buyback = max(p.price for p in bp_records)

        if buyback and buyback > retail:
            r.estimated_profit = buyback - retail  # 買取は手数料なし
            r.details["profit_method"] = "buyback"
            r.details["buyback_price"] = buyback
            return

        # パターン2: 二次流通価格ベース（取得価格が定価超え）
        if obs.price and obs.price > retail:
            fees = int(obs.price * fee_rate) + shipping
            r.estimated_profit = obs.price - retail - fees
            r.details["profit_method"] = "secondary"
            r.details["secondary_price"] = obs.price
            r.details["fees"] = fees
            return

        # パターン3: 他ソースの中古価格を参照
        used_records = self.repository.list_price_history(
            product_id=obs.product_id, price_type="used", limit=5
        )
        if used_records:
            best_used = max(p.price for p in used_records)
            if best_used > retail:
                fees = int(best_used * fee_rate) + shipping
                r.estimated_profit = best_used - retail - fees
                r.details["profit_method"] = "cross_source_used"
                r.details["secondary_price"] = best_used
                r.details["fees"] = fees
                return

        # パターン4: 他ソースの小売価格で最高値を参照
        all_records = self.repository.list_price_history(
            product_id=obs.product_id, limit=20
        )
        high = [p.price for p in all_records if p.price > retail]
        if high:
            best = max(high)
            fees = int(best * fee_rate) + shipping
            r.estimated_profit = best - retail - fees
            r.details["profit_method"] = "cross_source_retail"
            r.details["secondary_price"] = best
            r.details["fees"] = fees

    # ===== 利益スコア =====

    def _calc_profit_score(self, r: ScoringResult) -> None:
        if r.estimated_profit is None or r.estimated_profit <= 0:
            r.profit_score = 0.0
            return
        p = r.estimated_profit
        if p >= 30000:
            r.profit_score = 1.0
        elif p >= 20000:
            r.profit_score = 0.8
        elif p >= 10000:
            r.profit_score = 0.6
        elif p >= 5000:
            r.profit_score = 0.4
        else:
            r.profit_score = 0.2

    # ===== confidence =====

    def _calc_confidence(
        self, r: ScoringResult, obs: ObservationModel, source: SourceModel
    ) -> None:
        sw = self.config["source_weights"]
        source_w = sw.get(source.source_type, 0.5)

        age = datetime.now() - obs.observed_at
        if age < timedelta(minutes=5):
            freshness = 1.0
        elif age < timedelta(minutes=30):
            freshness = 0.9
        elif age < timedelta(hours=1):
            freshness = 0.7
        elif age < timedelta(hours=6):
            freshness = 0.5
        else:
            freshness = 0.3

        recent = self.repository.list_observations(product_id=obs.product_id, limit=10)
        other_sources = set(o.source_id for o in recent if o.source_id != obs.source_id)
        if len(other_sources) >= 2:
            consistency = 1.0
        elif len(other_sources) >= 1:
            consistency = 0.85
        else:
            consistency = 0.65

        r.confidence = round(source_w * freshness * consistency, 2)
        r.details["source_weight"] = source_w
        r.details["freshness"] = freshness
        r.details["consistency"] = consistency

    # ===== 変化検知 =====

    def _calc_change_score(self, r: ScoringResult, obs: ObservationModel) -> None:
        prev = self._get_previous(obs)
        if prev is None:
            r.change_score = 0.5
            r.details["change"] = "first_observation"
            return

        # 在庫復活
        if prev.is_in_stock is False and obs.is_in_stock is True:
            r.change_score = 1.0
            r.details["change"] = "stock_restored"
            return

        # 価格変動
        if prev.price and obs.price:
            delta = (obs.price - prev.price) / prev.price
            if abs(delta) >= 0.10:
                r.change_score = 0.8
                r.details["change"] = f"price_{'+' if delta > 0 else ''}{delta:.0%}"
                return

        # 買取変動
        if prev.buyback_price and obs.buyback_price:
            delta = (obs.buyback_price - prev.buyback_price) / prev.buyback_price
            if delta >= 0.10:
                r.change_score = 1.0
                r.details["change"] = f"buyback_+{delta:.0%}"
                return

        r.change_score = 0.1
        r.details["change"] = "no_significant_change"

    # ===== ランク判定 =====

    def _determine_rank(self, r: ScoringResult, obs: ObservationModel) -> None:
        t = self.config["profit_thresholds"]
        c = self.config["confidence_thresholds"]

        has_profit = r.estimated_profit is not None and r.estimated_profit > 0

        # 定価不明ガード: 定価が取得できていない商品はS/Aにしない
        if r.details.get("no_retail_price"):
            r.alert_rank = "B" if r.total_score >= 0.40 else "C"
            r.should_notify = False
            r.details["rank_reason"] = "no_retail_price"
            return

        # S判定
        if (
            has_profit
            and r.estimated_profit >= t["s_rank_min_profit"]
            and r.confidence >= c["s_rank_min_confidence"]
            and (
                obs.is_in_stock is True
                or obs.lottery_status == "open"
                or r.alert_type == "buyback_surge"
            )
        ):
            r.alert_rank = "S"
            r.should_notify = True
            return

        # A判定
        if (
            has_profit
            and r.estimated_profit >= t["a_rank_min_profit"]
            and r.confidence >= c["a_rank_min_confidence"]
        ):
            r.alert_rank = "A"
            r.should_notify = True
            return

        # B判定
        if r.total_score >= 0.40 or (has_profit and r.estimated_profit >= 5000):
            r.alert_rank = "B"
            r.should_notify = False
            return

        # C判定
        r.alert_rank = "C"
        r.should_notify = False

    # ===== helper =====

    def _get_previous(self, obs: ObservationModel) -> Optional[ObservationModel]:
        prev = self.repository.get_latest_observation(
            obs.product_id, obs.source_id, obs.observation_type
        )
        if prev and prev.id == obs.id:
            return None
        return prev
