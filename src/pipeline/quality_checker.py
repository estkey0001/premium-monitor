"""Phase 8: データ整合性・品質チェック。

CLI / Streamlit の両方から呼べる共通ロジック。
チェック結果は {"level": "error"/"warning"/"ok", "category": "...", "message": "...", ...} の辞書リストで返す。
"""

import logging
import re
from datetime import datetime
from typing import Optional

from src.db.repository import Repository

logger = logging.getLogger(__name__)

# --- 投稿テンプレート禁止表現 ---
FORBIDDEN_PHRASES = [
    "確実に儲かる", "絶対利益", "誰でも稼げる", "今すぐ買え",
    "買えば勝ち", "ノーリスク", "guaranteed", "sure profit",
    "必ず儲かる", "100%利益", "損しない", "絶対に稼げる",
    "確実に利益", "リスクゼロ", "損失ゼロ",
]

# --- CLI PRODUCT_ALIASES / SOURCE_ALIASES の定義を外部参照 ---
CLI_PRODUCT_ALIASES = {
    "iphone17pro256", "iphone17pro",
    "iphone16pm", "iphone16pm_256", "iphone16pm_512",
    "gr4", "griv", "gr4_hdf", "griv_hdf", "gr4_mono", "griv_mono",
    "gr3x", "gr3_hdf", "gr3",
    "x100vi",
    "ps5_pro", "switch2",
}

CSV_PRODUCT_ALIASES = {
    "gr4", "gr4_hdf", "gr4_mono", "gr3x", "gr3", "gr3_hdf",
    "x100vi",
    "iphone17pro256", "iphone17pro",
    "iphone16pm", "iphone16pm_256", "iphone16pm_512",
    "ps5_pro", "switch2",
}


class QualityChecker:
    """データ品質の検証を行う。"""

    def __init__(self, repository: Repository):
        self.repo = repository
        self.db = repository.db

    # ====================================================
    # 1. データ整合性チェック (validate-data)
    # ====================================================

    def validate_data(self) -> list[dict]:
        """全データの整合性をチェックする。"""
        results = []
        results.extend(self._check_products())
        results.extend(self._check_observations_fk())
        results.extend(self._check_price_history_fk())
        results.extend(self._check_market_snapshots_fk())
        results.extend(self._check_market_snapshots_fields())
        results.extend(self._check_price_anomalies())
        results.extend(self._check_overseas_currency())
        return results

    def _check_products(self) -> list[dict]:
        """商品マスタの整合性チェック。"""
        results = []
        products = self.repo.list_products(active_only=False)

        registered_ids = {p.id for p in products}

        for p in products:
            # official_price が 0 or NULL
            if not p.official_price or p.official_price == 0:
                if p.retail_price and p.retail_price > 0:
                    results.append({
                        "level": "warning",
                        "category": "product_official_price",
                        "message": f"{p.name}: official_price未設定 (retail_price=¥{p.retail_price:,})",
                        "product_id": p.id,
                    })
                else:
                    results.append({
                        "level": "error",
                        "category": "product_price_missing",
                        "message": f"{p.name}: official_priceもretail_priceも未設定",
                        "product_id": p.id,
                    })

            # retail_price と official_price の乖離
            if p.retail_price and p.official_price and p.official_price > 0:
                gap = abs(p.retail_price - p.official_price)
                if gap > 0 and gap / max(p.retail_price, 1) > 0.1:
                    results.append({
                        "level": "warning",
                        "category": "product_price_mismatch",
                        "message": (
                            f"{p.name}: retail_price=¥{p.retail_price:,} vs "
                            f"official_price=¥{p.official_price:,} (差額¥{gap:,})"
                        ),
                        "product_id": p.id,
                    })

            # product_id が CLI aliases に登録されているか
            # id → prod_xxx → alias は xxx 部分
            short_id = p.id.replace("prod_", "")
            if short_id not in CLI_PRODUCT_ALIASES and p.id not in CLI_PRODUCT_ALIASES:
                results.append({
                    "level": "warning",
                    "category": "product_alias_missing",
                    "message": f"{p.name}: CLI aliasに未登録 (id={p.id})",
                    "product_id": p.id,
                })

        return results

    def _check_observations_fk(self) -> list[dict]:
        """observations の FK整合性チェック。"""
        results = []
        rows = self.db.connection.execute("""
            SELECT DISTINCT o.source_id
            FROM observations o
            LEFT JOIN sources s ON s.id = o.source_id
            WHERE s.id IS NULL
        """).fetchall()
        for r in rows:
            results.append({
                "level": "error",
                "category": "observation_fk_source",
                "message": f"observations.source_id='{r['source_id']}' がsourcesに存在しない",
            })
        return results

    def _check_price_history_fk(self) -> list[dict]:
        """price_history の FK整合性チェック。"""
        results = []
        rows = self.db.connection.execute("""
            SELECT DISTINCT ph.source_id
            FROM price_history ph
            LEFT JOIN sources s ON s.id = ph.source_id
            WHERE s.id IS NULL
        """).fetchall()
        for r in rows:
            results.append({
                "level": "error",
                "category": "price_history_fk_source",
                "message": f"price_history.source_id='{r['source_id']}' がsourcesに存在しない",
            })
        return results

    def _check_market_snapshots_fk(self) -> list[dict]:
        """market_snapshots の FK整合性チェック。"""
        results = []
        rows = self.db.connection.execute("""
            SELECT DISTINCT ms.product_id
            FROM market_snapshots ms
            WHERE ms.product_id IS NOT NULL
              AND ms.product_id != ''
              AND ms.product_id NOT IN (SELECT id FROM products)
        """).fetchall()
        for r in rows:
            results.append({
                "level": "error",
                "category": "snapshot_fk_product",
                "message": f"market_snapshots.product_id='{r['product_id']}' がproductsに存在しない",
            })
        return results

    def _check_market_snapshots_fields(self) -> list[dict]:
        """market_snapshots の必須フィールドチェック。"""
        results = []

        # user_level が空
        rows = self.db.connection.execute("""
            SELECT id, product_name FROM market_snapshots
            WHERE user_level IS NULL OR user_level = ''
        """).fetchall()
        for r in rows:
            results.append({
                "level": "warning",
                "category": "snapshot_user_level_empty",
                "message": f"market_snapshot '{r['product_name']}': user_level未設定",
                "snapshot_id": r["id"],
            })

        # recommended_action が空
        rows = self.db.connection.execute("""
            SELECT id, product_name FROM market_snapshots
            WHERE recommended_action IS NULL OR recommended_action = ''
        """).fetchall()
        for r in rows:
            results.append({
                "level": "warning",
                "category": "snapshot_action_empty",
                "message": f"market_snapshot '{r['product_name']}': recommended_action未設定",
                "snapshot_id": r["id"],
            })

        # beginner_score / difficulty_score が NULL
        rows = self.db.connection.execute("""
            SELECT id, product_name FROM market_snapshots
            WHERE beginner_score IS NULL OR difficulty_score IS NULL
        """).fetchall()
        for r in rows:
            results.append({
                "level": "warning",
                "category": "snapshot_score_null",
                "message": f"market_snapshot '{r['product_name']}': beginner/difficulty_scoreがNULL",
                "snapshot_id": r["id"],
            })

        return results

    def _check_price_anomalies(self) -> list[dict]:
        """価格の異常値チェック。"""
        results = []

        # 0円・1円
        rows = self.db.connection.execute("""
            SELECT id, product_id, source_id, price, price_type
            FROM price_history WHERE price <= 1
        """).fetchall()
        for r in rows:
            results.append({
                "level": "error",
                "category": "price_anomaly_zero",
                "message": (
                    f"price_history: product={r['product_id']} source={r['source_id']} "
                    f"type={r['price_type']} price=¥{r['price']} (0円/1円)"
                ),
            })

        # 10億円以上
        rows = self.db.connection.execute("""
            SELECT id, product_id, source_id, price, price_type
            FROM price_history WHERE price >= 1000000000
        """).fetchall()
        for r in rows:
            results.append({
                "level": "error",
                "category": "price_anomaly_extreme",
                "message": (
                    f"price_history: product={r['product_id']} source={r['source_id']} "
                    f"type={r['price_type']} price=¥{r['price']:,} (10億円以上)"
                ),
            })

        return results

    def _check_overseas_currency(self) -> list[dict]:
        """海外価格のJPY換算チェック。"""
        results = []

        # overseas type で price < 1000 は未換算の可能性
        rows = self.db.connection.execute("""
            SELECT id, product_id, source_id, price
            FROM price_history
            WHERE price_type = 'overseas' AND price < 1000
        """).fetchall()
        for r in rows:
            results.append({
                "level": "warning",
                "category": "overseas_not_converted",
                "message": (
                    f"overseas price ¥{r['price']} (product={r['product_id']}, "
                    f"source={r['source_id']}) — JPY未換算の可能性"
                ),
            })

        return results

    # ====================================================
    # 3. 初心者向け品質チェック
    # ====================================================

    def check_beginner_quality(self) -> list[dict]:
        """beginner_easy の品質チェック。不足あれば降格推奨を返す。"""
        results = []

        from src.models.market_snapshot import MarketSnapshotModel
        rows = self.db.connection.execute("""
            SELECT * FROM market_snapshots WHERE user_level = 'beginner_easy'
        """).fetchall()

        for row in rows:
            snap = MarketSnapshotModel(**dict(row))
            issues = []

            # 公式価格が取得済みか
            if not snap.official_price_jpy or snap.official_price_jpy == 0:
                issues.append("公式価格が未設定")

            # 買取価格が取得済みか
            if not snap.domestic_buyback_price_jpy or snap.domestic_buyback_price_jpy == 0:
                issues.append("買取価格が未取得")

            # sale_method が normal
            if snap.sale_method not in ("normal", ""):
                issues.append(f"sale_method={snap.sale_method} (normalでない)")

            # difficulty_score <= 0.35
            if snap.difficulty_score > 0.35:
                issues.append(f"difficulty_score={snap.difficulty_score:.2f} (>0.35)")

            # 想定利益 >= 5000円
            if snap.official_price_jpy and snap.domestic_buyback_price_jpy:
                profit = snap.domestic_buyback_price_jpy - snap.official_price_jpy
                if profit < 5000:
                    issues.append(f"想定利益=¥{profit:,} (<5,000円)")
            else:
                issues.append("利益計算不可（価格不足）")

            # 公式購入URL確認（product経由）
            if snap.product_id:
                try:
                    psc_rows = self.db.connection.execute("""
                        SELECT target_url FROM product_source_configs
                        WHERE product_id = ? AND source_id LIKE 'src_%'
                        LIMIT 1
                    """, (snap.product_id,)).fetchall()
                    if not psc_rows:
                        issues.append("公式購入URLが未設定")
                except Exception:
                    pass  # product_source_configsテーブルが存在しない場合はスキップ

            if issues:
                results.append({
                    "level": "warning",
                    "category": "beginner_quality",
                    "message": f"{snap.product_name}: {'; '.join(issues)}",
                    "snapshot_id": snap.id,
                    "product_name": snap.product_name,
                    "issues": issues,
                    "should_downgrade": len(issues) >= 2,
                })
            else:
                results.append({
                    "level": "ok",
                    "category": "beginner_quality",
                    "message": f"{snap.product_name}: 品質OK",
                    "snapshot_id": snap.id,
                    "product_name": snap.product_name,
                    "issues": [],
                    "should_downgrade": False,
                })

        return results

    # ====================================================
    # 4. 上級者向け品質チェック
    # ====================================================

    def check_advanced_quality(self) -> list[dict]:
        """advanced_high_profit / expert_only の品質チェック。"""
        results = []

        from src.models.market_snapshot import MarketSnapshotModel
        rows = self.db.connection.execute("""
            SELECT * FROM market_snapshots
            WHERE user_level IN ('advanced_high_profit', 'expert_only')
        """).fetchall()

        for row in rows:
            snap = MarketSnapshotModel(**dict(row))
            issues = []

            # 利益 30,000円以上
            effective_profit = snap.premium_gap_jpy or 0
            if snap.official_price_jpy and snap.domestic_buyback_price_jpy:
                buyback_profit = snap.domestic_buyback_price_jpy - snap.official_price_jpy
                effective_profit = max(effective_profit, buyback_profit)

            if effective_profit < 30000:
                issues.append(f"想定利益=¥{effective_profit:,} (<30,000円)")

            # 入手難易度が明示されている
            if snap.difficulty_score < 0.3:
                issues.append(f"difficulty_score={snap.difficulty_score:.2f} (上級者向けにしては低い)")

            # 抽選/SOLD OUT/販売休止/海外差 の理由が存在
            has_reason = (
                snap.sale_method in ("lottery", "soldout", "discontinued")
                or snap.scarcity_score >= 0.5
                or (snap.overseas_gap_percent and snap.overseas_gap_percent >= 10)
            )
            if not has_reason:
                issues.append("入手困難の根拠が不明（抽選/SOLD OUT/希少性/海外差なし）")

            if issues:
                results.append({
                    "level": "warning",
                    "category": "advanced_quality",
                    "message": f"{snap.product_name}: {'; '.join(issues)}",
                    "snapshot_id": snap.id,
                    "product_name": snap.product_name,
                    "issues": issues,
                })
            else:
                results.append({
                    "level": "ok",
                    "category": "advanced_quality",
                    "message": f"{snap.product_name}: 品質OK",
                    "snapshot_id": snap.id,
                    "product_name": snap.product_name,
                    "issues": [],
                })

        return results

    # ====================================================
    # 5. 投稿テンプレート安全表現チェック
    # ====================================================

    def validate_publish_text(self) -> list[dict]:
        """publish_queueの禁止表現チェック。"""
        results = []

        rows = self.db.connection.execute("""
            SELECT id, channel, title, body FROM publish_queue
        """).fetchall()

        for row in rows:
            item_id = row["id"]
            channel = row["channel"]
            body = row["body"] or ""
            title = row["title"] or ""
            full_text = f"{title} {body}"

            for phrase in FORBIDDEN_PHRASES:
                if phrase.lower() in full_text.lower():
                    # body抜粋（該当箇所の前後50文字）
                    idx = full_text.lower().find(phrase.lower())
                    start = max(0, idx - 30)
                    end = min(len(full_text), idx + len(phrase) + 30)
                    excerpt = full_text[start:end]

                    results.append({
                        "level": "error",
                        "category": "publish_forbidden_phrase",
                        "message": f"[{channel}] 禁止表現検出: '{phrase}'",
                        "item_id": item_id,
                        "channel": channel,
                        "forbidden_phrase": phrase,
                        "excerpt": excerpt,
                    })

        if not rows:
            results.append({
                "level": "ok",
                "category": "publish_text",
                "message": "publish_queueにデータなし（チェック対象なし）",
            })
        elif not any(r["level"] == "error" for r in results):
            results.append({
                "level": "ok",
                "category": "publish_text",
                "message": f"全{len(rows)}件の投稿テンプレートに禁止表現なし",
            })

        return results

    # ====================================================
    # 全チェック統合
    # ====================================================

    def run_all_checks(self) -> dict:
        """全チェックを実行し、カテゴリ別にまとめる。"""
        data_results = self.validate_data()
        beginner_results = self.check_beginner_quality()
        advanced_results = self.check_advanced_quality()
        publish_results = self.validate_publish_text()

        all_results = data_results + beginner_results + advanced_results + publish_results

        summary = {
            "total": len(all_results),
            "errors": len([r for r in all_results if r["level"] == "error"]),
            "warnings": len([r for r in all_results if r["level"] == "warning"]),
            "ok": len([r for r in all_results if r["level"] == "ok"]),
            "results": all_results,
            "data_results": data_results,
            "beginner_results": beginner_results,
            "advanced_results": advanced_results,
            "publish_results": publish_results,
        }
        return summary
