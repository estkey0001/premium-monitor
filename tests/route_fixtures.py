"""テスト用の「確定として出してよい」利益ルートの雛形（テストではない補助モジュール。データは架空）。

確定ルートの判定（src/content/ui/opportunity.route_reasons）が求める項目をすべてそろえる:
商品の同一性（両側）・状態・仕入れ先のリンク・価格の根拠・鮮度・費用（購入送料・購入時の費用・手数料・発送）・
内訳の一致。各テストは必要な項目だけを上書きして、条件を1つずつ崩す。
"""

from __future__ import annotations

from datetime import datetime, timedelta

# 二次流通で仕入れるときの商品ページ単位の URL（price_types.is_item_url が認める形・ダミーでない番号）
ITEM_URL = "https://jp.mercari.com/item/m48213579146"


def safe_route(now: datetime, pid: str = "prod_safe", *, sell_type: str = "BUYBACK_CASH",
               buy: int = 100000, sell: int = 130000, **kw) -> dict:
    """正規店で新品を買って売るルート（確定の条件をすべて満たす）。"""
    shipping, margin = 1500, 3000
    fee = int(sell * 0.1) if sell_type == "SOLD_MEDIAN" else 0
    net = sell - buy - fee - shipping - margin
    r = {"product_id": pid, "product_name": f"商品{pid}", "buy_source": "家電量販店X", "sell_source": "買取店Y",
         "buy_price": buy, "sell_price": sell, "net_profit": net, "roi": net / buy,
         "platform_fee": fee, "payment_fee": 0, "fx_buffer": 0, "shipping_cost": shipping, "safety_margin": margin,
         "buy_shipping": 0, "buy_required_cost": 0, "route_confidence": "high", "route_type": "shop_to_buyback",
         "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_CURRENT",
         "buy_canonical_type": "RETAIL", "sell_canonical_type": sell_type,
         "buy_price_type": "shop_sale_price",
         "sell_price_type": "flea_sold_price" if sell_type == "SOLD_MEDIAN" else "buyback_price",
         "buy_condition": "new_unopened", "sell_condition": "new_unopened",
         "buy_exact_match": True, "sell_exact_match": True, "buy_link_type": "item",
         "buy_url": "https://www.example-store.jp/i/1", "buy_item_url": "https://www.example-store.jp/i/1",
         "sell_url": "https://www.example-kaitori.jp/p/1",
         "buy_observed_at": (now - timedelta(hours=3)).isoformat(),
         "sell_observed_at": (now - timedelta(hours=2)).isoformat(),
         "buy_observed_age_days": 0.1, "sell_observed_age_days": 0.1}
    if sell_type == "SOLD_MEDIAN":
        r.update({"sell_source": "メルカリ（成約）", "sell_sample_count": 14, "sell_period": "09/03〜10/02",
                  "sell_period_start": (now - timedelta(days=30)).isoformat(),
                  "sell_period_end": (now - timedelta(hours=2)).isoformat(),
                  "sell_min": sell - 10000, "sell_max": sell + 12000})
    r.update(kw)
    return r


def secondary(r: dict) -> dict:
    """同じルートを二次流通（中古の出品）で仕入れる形にする（商品ページ単位の URL つき）。"""
    return dict(r, buy_canonical_type="LISTING", buy_price_type="flea_listing_price",
                buy_condition="used_a", sell_condition="used_a",
                buy_link_type="item", buy_url=ITEM_URL, buy_item_url=ITEM_URL, buy_source="メルカリ（出品）")


class AllSellsVerified(set):
    """テストの買取価格の行はすべて商品照合済みとする（生成器の _sell_keys_cache に入れる）。
    生成器はふだん正規化データ（exports/normalized_price_observations）から照合済みの集合を作るが、テストでは
    リポジトリの実データを読まないようにする。照合未了の扱いは Phase 6.1 のテストで個別の集合を渡して確かめる。"""

    def __contains__(self, key) -> bool:
        return True
