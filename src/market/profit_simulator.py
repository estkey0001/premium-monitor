"""利益シミュレーター (Phase 10)。"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.db.repository import Repository
from src.models.beginner_deal import DEFAULT_COSTS
from src.models.buyback_price import BuybackPriceModel, BUYBACK_SHOPS, CONDITION_LABELS

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports" / "simulations"


class ProfitSimulator:
    """利益シミュレーションを実行する。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def simulate(
        self,
        product_id: str,
        shop_id: Optional[str] = None,
        shipping: int = 1000,
        transfer_fee: int = 300,
        transport: int = 500,
        cc_fee_rate: float = 0.0,
        other_costs: int = 0,
    ) -> Optional[dict]:
        """利益シミュレーションを実行する。"""
        product = self.repo.get_product(product_id)
        if not product:
            return None

        official = product.official_price or product.retail_price or 0
        if official <= 0:
            return {"error": f"公式価格が未設定: {product.name}"}

        # 買取価格を取得
        buybacks = self.repo.list_buyback_prices(product_id=product_id)
        # price_historyからも補完
        ph_buybacks = self.repo.list_price_history(
            product_id=product_id, price_type="buyback", limit=20
        )
        seen = {b.shop_id for b in buybacks}
        for ph in ph_buybacks:
            if ph.source_id not in seen:
                buybacks.append(BuybackPriceModel(
                    id=ph.id, product_id=product_id, shop_id=ph.source_id,
                    shop_name=BUYBACK_SHOPS.get(ph.source_id, {}).get("name", ph.source_id),
                    buyback_price=ph.price, condition="new_unopened",
                    observed_at=ph.recorded_at,
                ))
                seen.add(ph.source_id)

        if shop_id:
            buybacks = [b for b in buybacks if b.shop_id == shop_id]
        if not buybacks:
            return {"error": f"買取価格データなし: {product.name} (shop={shop_id})"}

        # コスト
        cc_fee = int(official * cc_fee_rate)
        total_costs = shipping + transfer_fee + transport + cc_fee + other_costs

        # 全店舗でシミュレーション
        results = []
        for b in sorted(buybacks, key=lambda x: x.buyback_price, reverse=True):
            gross = b.buyback_price - official
            net = gross - total_costs
            rate = round(net / official, 4) if official > 0 else 0

            results.append({
                "shop_id": b.shop_id,
                "shop_name": b.shop_name or b.shop_id,
                "buyback_price": b.buyback_price,
                "condition": CONDITION_LABELS.get(b.condition, b.condition),
                "gross_profit": gross,
                "total_costs": total_costs,
                "net_profit": net,
                "net_profit_rate": rate,
                "profitable": net > 0,
            })

        best = results[0] if results else {}

        sim = {
            "product_id": product_id,
            "product_name": product.name,
            "brand": product.brand,
            "official_price": official,
            "cost_breakdown": {
                "shipping": shipping,
                "transfer_fee": transfer_fee,
                "transport": transport,
                "cc_fee": cc_fee,
                "other": other_costs,
                "total": total_costs,
            },
            "shops": results,
            "best_shop": best.get("shop_name", ""),
            "best_net_profit": best.get("net_profit", 0),
            "best_rate": best.get("net_profit_rate", 0),
            "simulated_at": datetime.now().isoformat(),
        }

        return sim

    def save_simulation(self, sim: dict) -> str:
        """シミュレーション結果をファイルに保存する。"""
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        pid = sim.get("product_id", "unknown")
        path = EXPORTS_DIR / f"sim_{pid}_{now}.txt"

        lines = [
            f"=== 利益シミュレーション ===",
            f"",
            f"商品: {sim['product_name']}",
            f"ブランド: {sim['brand']}",
            f"公式価格: ¥{sim['official_price']:,}",
            f"",
            f"--- コスト ---",
        ]
        cb = sim["cost_breakdown"]
        lines.extend([
            f"  送料:       ¥{cb['shipping']:,}",
            f"  振込手数料: ¥{cb['transfer_fee']:,}",
            f"  移動コスト: ¥{cb['transport']:,}",
            f"  クレカ手数料: ¥{cb['cc_fee']:,}",
            f"  その他:     ¥{cb['other']:,}",
            f"  合計:       ¥{cb['total']:,}",
            f"",
            f"--- 買取店別 ---",
        ])
        for s in sim["shops"]:
            icon = "✅" if s["profitable"] else "❌"
            lines.append(
                f"  {icon} {s['shop_name']:<14} "
                f"買取¥{s['buyback_price']:>8,} "
                f"粗利{s['gross_profit']:>+8,} "
                f"実質{s['net_profit']:>+8,} "
                f"({s['net_profit_rate']:.1%})"
            )
        lines.extend([
            f"",
            f"最適: {sim['best_shop']} → 実質+¥{sim['best_net_profit']:,} ({sim['best_rate']:.1%})",
        ])

        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)
