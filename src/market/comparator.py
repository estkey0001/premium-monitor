"""市場比較ロジック。

1つの商品について、公式/二次流通/買取/海外の価格を横断比較し、
market_snapshotを生成する。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import ulid
import yaml

from src.db.repository import Repository
from src.models.market_snapshot import MarketSnapshotModel
from src.models.product import ProductModel

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class MarketComparator:
    """1商品の市場横断比較を実行する。"""

    def __init__(self, repository: Repository):
        self.repo = repository
        self.fx = self._load_fx()

    def _load_fx(self) -> dict:
        path = PROJECT_ROOT / "config" / "fx_rates.yaml"
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
            return {
                "rates": data.get("fx_rates", {}),
                "fees": data.get("overseas_fees", {}),
            }
        except Exception:
            return {"rates": {"USD_JPY": 155}, "fees": {}}

    def compare_product(self, product: ProductModel) -> MarketSnapshotModel:
        """商品の市場比較スナップショットを生成する。"""
        # 公式定価
        official = product.official_price or product.retail_price or 0

        # 国内二次流通（最新のused価格）
        used_records = self.repo.list_price_history(
            product_id=product.id, price_type="used", limit=5
        )
        domestic_used = max((p.price for p in used_records), default=None) if used_records else None

        # 国内買取（最新のbuyback価格）
        buyback_records = self.repo.list_price_history(
            product_id=product.id, price_type="buyback", limit=5
        )
        domestic_buyback = max((p.price for p in buyback_records), default=None) if buyback_records else None

        # 二次流通がない場合、retailで定価超えの最高値を参照
        if not domestic_used:
            all_retail = self.repo.list_price_history(
                product_id=product.id, price_type="retail", limit=20
            )
            above_official = [p.price for p in all_retail if official and p.price > official * 1.05]
            if above_official:
                domestic_used = max(above_official)

        # 海外価格（overseas記録があれば）
        overseas_records = self.repo.list_price_history(
            product_id=product.id, price_type="overseas", limit=5
        )
        overseas_jpy = max((p.price for p in overseas_records), default=None) if overseas_records else None

        # 在庫・販売方式
        stock_status = product.official_stock_status or ""
        sale_method = "lottery" if product.is_lottery else (
            "discontinued" if product.is_discontinued else (
                "soldout" if "SOLD" in stock_status.upper() else "normal"
            )
        )

        # 価格差計算
        premium_gap = None
        premium_pct = None
        if official and domestic_used and domestic_used > official:
            premium_gap = domestic_used - official
            premium_pct = round((premium_gap / official) * 100, 1)

        overseas_gap = None
        overseas_pct = None
        if official and overseas_jpy and overseas_jpy > official:
            overseas_gap = overseas_jpy - official
            overseas_pct = round((overseas_gap / official) * 100, 1)

        # 5スコア計算
        premium_score = self._calc_premium_score(official, domestic_used, domestic_buyback)
        scarcity_score = self._calc_scarcity_score(product, stock_status, sale_method)
        liquidity_score = self._calc_liquidity_score(product)
        overseas_gap_score = self._calc_overseas_score(official, overseas_jpy)
        source_confidence = self._calc_source_confidence(product)

        overall = round(
            premium_score * 0.30
            + scarcity_score * 0.25
            + liquidity_score * 0.15
            + overseas_gap_score * 0.15
            + source_confidence * 0.15,
            3,
        )

        # Phase 7B-2: 初心者向けスコア計算
        beginner_score = self._calc_beginner_score(
            official, domestic_buyback, stock_status, sale_method, product
        )
        difficulty_score = self._calc_difficulty_score(
            stock_status, sale_method, scarcity_score, product
        )
        beginner_profit_score = self._calc_beginner_profit_score(
            official, domestic_buyback
        )

        # user_level / recommended_action 判定
        user_level, recommended_action = self._classify_user_level(
            official=official,
            domestic_buyback=domestic_buyback,
            sale_method=sale_method,
            stock_status=stock_status,
            difficulty_score=difficulty_score,
            premium_gap_jpy=premium_gap,
            beginner_profit_score=beginner_profit_score,
        )

        return MarketSnapshotModel(
            id=str(ulid.new()),
            product_id=product.id,
            category=product.genre,
            brand=product.brand,
            product_name=product.name,
            official_price_jpy=official or None,
            domestic_used_price_jpy=domestic_used,
            domestic_buyback_price_jpy=domestic_buyback,
            overseas_price_jpy=overseas_jpy,
            stock_status=stock_status,
            sale_method=sale_method,
            premium_gap_jpy=premium_gap,
            premium_gap_percent=premium_pct,
            overseas_gap_jpy=overseas_gap,
            overseas_gap_percent=overseas_pct,
            premium_score=premium_score,
            scarcity_score=scarcity_score,
            liquidity_score=liquidity_score,
            overseas_gap_score=overseas_gap_score,
            source_confidence=source_confidence,
            overall_score=overall,
            beginner_score=beginner_score,
            difficulty_score=difficulty_score,
            beginner_profit_score=beginner_profit_score,
            user_level=user_level,
            recommended_action=recommended_action,
        )

    def compare_all_products(self, category: Optional[str] = None) -> list[MarketSnapshotModel]:
        """全商品（またはカテゴリ内）の比較を実行する。"""
        products = self.repo.list_products()
        if category:
            products = [p for p in products if p.genre == category]

        snapshots = []
        for product in products:
            try:
                snap = self.compare_product(product)
                self.repo.insert_market_snapshot(snap)
                snapshots.append(snap)
                logger.info(
                    "Market: %s | official=¥%s used=¥%s buyback=¥%s | premium=%s%% | overall=%.2f",
                    product.name,
                    f"{snap.official_price_jpy:,}" if snap.official_price_jpy else "?",
                    f"{snap.domestic_used_price_jpy:,}" if snap.domestic_used_price_jpy else "?",
                    f"{snap.domestic_buyback_price_jpy:,}" if snap.domestic_buyback_price_jpy else "?",
                    f"+{snap.premium_gap_percent}%" if snap.premium_gap_percent else "N/A",
                    snap.overall_score,
                )
            except Exception as e:
                logger.error("Market compare failed for %s: %s", product.name, e)

        # overall_scoreで降順ソート
        snapshots.sort(key=lambda s: s.overall_score, reverse=True)
        return snapshots

    # ===== スコア計算 =====

    def _calc_premium_score(self, official, used, buyback) -> float:
        """価格差の強さ (0.0〜1.0)。"""
        if not official:
            return 0.0

        best_secondary = max(filter(None, [used, buyback]), default=0)
        if best_secondary <= official:
            return 0.0

        gap_pct = (best_secondary - official) / official
        if gap_pct >= 0.50:
            return 1.0
        elif gap_pct >= 0.30:
            return 0.8
        elif gap_pct >= 0.20:
            return 0.6
        elif gap_pct >= 0.10:
            return 0.4
        elif gap_pct >= 0.05:
            return 0.2
        return 0.0

    def _calc_scarcity_score(self, product, stock_status, sale_method) -> float:
        """在庫枯渇・抽選スコア。"""
        score = 0.0
        if sale_method == "lottery":
            score = 0.8
        elif sale_method == "soldout":
            score = 0.7
        elif sale_method == "discontinued":
            score = 0.5
        elif "お取り寄せ" in stock_status or "販売休止" in stock_status:
            score = 0.4

        # SOLD OUT observationsの数
        sold_out_obs = self.repo.db.connection.execute(
            "SELECT COUNT(*) c FROM observations WHERE product_id=? AND is_in_stock=0",
            (product.id,),
        ).fetchone()
        if sold_out_obs and sold_out_obs["c"] >= 3:
            score = max(score, 0.6)

        return round(score, 2)

    def _calc_liquidity_score(self, product) -> float:
        """売れやすさ（観測データの多さで推定）。"""
        obs_count = len(self.repo.list_observations(product_id=product.id, limit=20))
        source_count = len(set(
            o.source_id for o in self.repo.list_observations(product_id=product.id, limit=20)
        ))
        if source_count >= 4:
            return 0.8
        elif source_count >= 2:
            return 0.5
        elif source_count >= 1:
            return 0.3
        return 0.1

    def _calc_overseas_score(self, official, overseas_jpy) -> float:
        """海外価格差スコア。"""
        if not official or not overseas_jpy:
            return 0.0
        gap_pct = (overseas_jpy - official) / official
        if gap_pct >= 0.30:
            return 1.0
        elif gap_pct >= 0.20:
            return 0.7
        elif gap_pct >= 0.10:
            return 0.4
        return 0.0

    def _calc_source_confidence(self, product) -> float:
        """情報源の信頼度。"""
        has_official = bool(product.official_price and product.official_price > 0)
        obs_count = len(self.repo.list_observations(product_id=product.id, limit=10))
        if has_official and obs_count >= 3:
            return 0.9
        elif has_official:
            return 0.7
        elif obs_count >= 2:
            return 0.5
        return 0.2

    # ===== Phase 7B-2: 初心者向けスコア =====

    def _calc_beginner_score(self, official, buyback, stock_status, sale_method, product) -> float:
        """初心者向け度 (0.0〜1.0)。高いほど初心者に向いている。

        高スコア条件:
        - 公式定価が明確
        - 通常販売（抽選・SOLD OUTでない）
        - 買取価格が定価を上回る
        - 有名ブランド（Apple, Nintendo等は手順が明確）
        """
        score = 0.0

        # 公式定価があるか
        if official and official > 0:
            score += 0.20

        # 通常販売で在庫がある
        if sale_method == "normal":
            score += 0.30
            if "在庫あり" in stock_status or stock_status == "" or stock_status == "in_stock":
                score += 0.10
        elif sale_method == "lottery":
            score -= 0.10  # 抽選は初心者には厳しい
        elif sale_method == "soldout":
            score -= 0.20

        # 買取先が明確（buyback価格データがある）
        if buyback and buyback > 0:
            score += 0.15
            # 買取が定価を上回る（確実な利益）
            if official and buyback > official:
                score += 0.15

        # ブランド別の手順の分かりやすさ
        easy_brands = {"Apple", "Nintendo", "Sony"}
        if product.brand in easy_brands:
            score += 0.10

        return round(max(0.0, min(1.0, score)), 2)

    def _calc_difficulty_score(self, stock_status, sale_method, scarcity_score, product) -> float:
        """入手難易度 (0.0〜1.0)。高いほど困難。

        高スコア条件:
        - 抽選販売
        - SOLD OUT
        - 希少性が高い
        - 限定商品
        """
        score = 0.0

        if sale_method == "lottery":
            score += 0.40
        elif sale_method == "soldout":
            score += 0.50
        elif sale_method == "discontinued":
            score += 0.60
        elif "お取り寄せ" in stock_status or "販売休止" in stock_status:
            score += 0.30

        # scarcity_scoreを反映
        score += scarcity_score * 0.30

        # 通常販売なら低め
        if sale_method == "normal":
            score = max(score - 0.20, 0.0)

        # 限定モデルチェック
        name_lower = product.name.lower()
        if any(kw in name_lower for kw in ["monochrome", "limited", "限定", "special"]):
            score += 0.15

        return round(max(0.0, min(1.0, score)), 2)

    def _calc_beginner_profit_score(self, official, buyback) -> float:
        """初心者向け利益スコア (0.0〜1.0)。

        買取価格 - 公式定価 の利益額に基づく。
        利益が確実に見込める（買取 > 定価）場合にスコアが上がる。
        """
        if not official or not buyback or official <= 0:
            return 0.0

        if buyback <= official:
            return 0.0

        profit = buyback - official
        # 利益額に応じたスコア
        if profit >= 50000:
            return 1.0
        elif profit >= 30000:
            return 0.8
        elif profit >= 20000:
            return 0.7
        elif profit >= 10000:
            return 0.5
        elif profit >= 5000:
            return 0.3
        elif profit >= 3000:
            return 0.15
        return 0.0

    def _classify_user_level(
        self, official, domestic_buyback, sale_method, stock_status,
        difficulty_score, premium_gap_jpy, beginner_profit_score,
    ) -> tuple[str, str]:
        """user_level と recommended_action を判定する。

        Returns:
            (user_level, recommended_action)
        """
        # beginner_easy: 公式で買えて、買取が定価を上回り、利益5000円以上、difficulty低
        is_normal_sale = sale_method == "normal"
        is_in_stock = (
            "在庫あり" in stock_status or stock_status in ("", "in_stock")
            or "SOLD" not in stock_status.upper()
        ) if stock_status is not None else True
        has_buyback_profit = (
            official and domestic_buyback
            and domestic_buyback > official
            and (domestic_buyback - official) >= 5000
        )

        if is_normal_sale and is_in_stock and has_buyback_profit and difficulty_score <= 0.35:
            return "beginner_easy", "check_official"

        # beginner_watch: 定価超えの買取or中古はあるが利益が小さい/在庫不安定
        if official and domestic_buyback and domestic_buyback > official and difficulty_score <= 0.50:
            profit = domestic_buyback - official
            if profit >= 3000:
                return "beginner_watch", "check_buyback"

        # advanced_high_profit: 利益3万以上だが入手困難
        if premium_gap_jpy and premium_gap_jpy >= 30000:
            if sale_method in ("lottery", "soldout", "discontinued"):
                return "advanced_high_profit", "lottery_only" if sale_method == "lottery" else "watch_price"
            elif difficulty_score > 0.35:
                return "advanced_high_profit", "watch_price"

        # expert_only: 非常に高難度 + 高利益
        if difficulty_score >= 0.70 and premium_gap_jpy and premium_gap_jpy >= 50000:
            return "expert_only", "watch_price"

        # advanced_high_profit (利益大だが上記に合致しない場合)
        if premium_gap_jpy and premium_gap_jpy >= 30000:
            return "advanced_high_profit", "watch_price"

        # デフォルト: 分類なし（利益が小さいor情報不足）
        if premium_gap_jpy and premium_gap_jpy > 0:
            return "beginner_watch", "watch_price"

        return "", "watch_price"

    def convert_overseas_price(self, price: float, currency: str) -> Optional[int]:
        """海外価格をJPYに変換する。"""
        rate_key = f"{currency}_JPY"
        rate = self.fx["rates"].get(rate_key)
        if not rate:
            return None
        fees = self.fx["fees"]
        jpy = int(price * rate)
        shipping = fees.get("default_shipping_jpy", 3000)
        tax = int(jpy * fees.get("default_import_tax_rate", 0.10))
        platform = int(jpy * fees.get("default_platform_fee_rate", 0.05))
        return jpy + shipping + tax + platform
