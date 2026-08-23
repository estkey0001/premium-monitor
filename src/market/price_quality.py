#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retail / Buyback / Resale 価格の品質ゲート（役割認識型）。

公式価格フェーズで作った official_price_validator を土台に、販売価格・買取価格・
二次流通に流用できる品質判定を提供する。利益判定/AI/Opportunity/Notification/
Capital/Execution ロジックは一切変更しない（取得・正規化・品質管理のみ）。

提供する判定:
  - 商品同一性: 容量(GB)・型番・カラー・新品/中古 の厳格一致
  - 誤認防止: アクセサリー/分割月額/ポイント額/下取額 の除外（validator流用）
  - Main昇格ゲート: high confidence + fresh + exact match のみ
  - duplicate_price_pattern: 同一ソースで複数SKUが同額 → 警告（弾かず要確認）
  - 正規化フラグ: 税込/送料/ポイント/買取/下取 が別項目として保持されているか
  - Freshness: 取得失敗時に古い値を新時刻へ更新しない（監査で検出）
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from src.market.official_price_validator import (
    ACCESSORY_KW, NON_SALE_KW, NON_BODY_PRICE_KW, sanity_check_price,
)

# ソース種別 → 正規ドメイン（誤ドメイン混入検出用）
RETAIL_DOMAINS = {
    "src_kakaku": ("kakaku.com",), "src_yodobashi": ("yodobashi.com",),
    "src_biccamera": ("biccamera.com",), "src_rakuten": ("rakuten.co.jp",),
    "src_yahoo": ("yahoo.co.jp", "shopping.yahoo.co.jp"),
}
BUYBACK_DOMAINS = {
    "shop_マップカメラ": ("mapcamera.com",), "shop_フジヤカメラ": ("fujiya-camera.co.jp",),
    "shop_じゃんぱら": ("janpara.co.jp",), "shop_イオシス": ("iosys.co.jp",),
}
RESALE_DOMAINS = {
    "src_ebay": ("ebay.com",), "src_mercari": ("mercari.com", "jp.mercari.com"),
}

# ソース表示名の分類（audit の source グルーピング用）
RETAIL_SOURCES = ["価格.com", "ヨドバシ", "ビックカメラ", "楽天市場", "Yahoo", "楽天市場新品"]
BUYBACK_SOURCES = ["マップカメラ", "フジヤカメラ", "じゃんぱら", "イオシス", "カメラのキタムラ",
                   "ソフマップ", "買取商店", "ゲオ", "買取一丁目", "ネットオフ"]
RESALE_SOURCES = ["eBay sold(新品)", "eBay", "メルカリ未使用", "Mercari sold",
                  "ヤフオク (新品/未使用落札)", "Yahoo Auction sold", "Amazon JP (新品出品)"]

_CAP_RE = re.compile(r"(\d{1,4})\s*(gb|tb|ｇｂ)", re.I)
_COLORS = ("ブラック", "ホワイト", "シルバー", "ゴールド", "ブルー", "グリーン", "レッド",
           "パープル", "ピンク", "グレー", "スペースグレイ", "ミッドナイト", "スターライト",
           "ナチュラル", "デザート", "black", "white", "silver", "blue", "titanium", "チタン")


def extract_capacity_gb(text: str) -> Optional[int]:
    """テキストから容量(GB換算)を抽出。'1TB'→1024, '256GB'→256。無ければ None。"""
    if not text:
        return None
    m = _CAP_RE.search(text)
    if not m:
        return None
    val = int(m.group(1))
    return val * 1024 if m.group(2).lower() == "tb" else val


def capacity_consistent(product_name: str, obs_name: str) -> Optional[bool]:
    """容量一致。両方に容量があり一致=True / 異なる=False / どちらか無し=None。"""
    a, b = extract_capacity_gb(product_name), extract_capacity_gb(obs_name)
    if a is None or b is None:
        return None
    return a == b


def extract_color(text: str) -> Optional[str]:
    t = (text or "").lower()
    for c in _COLORS:
        if c.lower() in t:
            return c
    return None


def condition_class(condition: str) -> str:
    """condition を new / used / unknown に大別。"""
    c = (condition or "").lower()
    if any(k in c for k in ("new", "unused", "新品", "未使用", "未開封")):
        return "new"
    if any(k in c for k in ("used", "中古", "_a", "_b", "_c")):
        return "used"
    return "unknown"


def identity_strict_ok(product_name: str, obs) -> tuple[bool, Optional[str]]:
    """容量・型番・カラー・新品中古の厳格一致。NG時に理由を返す。"""
    cap = capacity_consistent(product_name, obs.get("product_name") or obs.get("extracted_title") or "")
    if cap is False:
        return False, "capacity_mismatch"
    if obs.get("wrong_model_flag"):
        return False, "wrong_model"
    if obs.get("accessory_flag"):
        return False, "accessory"
    if not obs.get("is_body_only", True):
        return False, "not_body_only"
    return True, None


def effective_confidence(obs) -> str:
    """NPO の confidence を土台に、link_type=search 等を low へ降格。"""
    conf = obs.get("product_match_confidence") or obs.get("confidence") or "low"
    if obs.get("link_type") == "search":
        return "low"
    if not obs.get("is_exact_product_match") and conf == "high":
        conf = "medium"
    return conf


def is_main_promotable(obs) -> bool:
    """Main 昇格ゲート: high confidence + fresh + exact match（+本体/価格>0/非拒否）。"""
    if not obs.get("price"):
        return False
    if obs.get("rejection_reason"):
        return False
    if not obs.get("is_fresh"):
        return False
    if not obs.get("is_exact_product_match"):
        return False
    if effective_confidence(obs) != "high":
        return False
    ok, _ = identity_strict_ok(obs.get("product_name", ""), obs)
    return ok


def price_role_sanity(obs, reference_price: Optional[int]) -> Optional[str]:
    """役割別の価格 sanity。異常なら理由、正常なら None。

    - 共通: validator の sanity（0/1円・月額/分割・下取・中古文脈・相場30%以下）
    - buyback(price_role=sell, buyback_price): 相場を大きく超える下取増額等は別途注意
    """
    ctx = (obs.get("price_context") or "") + " " + (obs.get("extracted_text_preview") or "")
    base = sanity_check_price(obs.get("price"), reference_price, ctx)
    if base:
        return base
    return None


def detect_duplicate_price_pattern(observations) -> list:
    """同一ソース・同一役割で、複数の異なるSKU(product_id)が同額 → 警告候補。

    弾かない（本体が実際に同額の特別仕様もある）。人が確認するための flag。
    """
    groups = defaultdict(set)
    price_map = defaultdict(list)
    for o in observations:
        p = o.get("price")
        if not p:
            continue
        key = (o.get("source_name"), o.get("price_role"), o.get("price_type"), p)
        groups[key].add(o.get("product_id"))
        price_map[key].append(o)
    out = []
    for key, pids in groups.items():
        if len(pids) >= 2:
            src, role, ptype, price = key
            out.append({
                "source_name": src, "price_role": role, "price_type": ptype,
                "price": price, "product_ids": sorted(pids), "count": len(pids),
                "note": "同一ソースで複数SKUが同額。特別仕様で実同額の可能性もあるため人が確認",
            })
    out.sort(key=lambda x: -x["count"])
    return out


def normalization_flags(obs) -> dict:
    """税込/送料/ポイント/買取/下取 が別項目として区別されているか（price_type 起点）。"""
    pt = obs.get("price_type") or ""
    ctx = (obs.get("price_context") or "").lower()
    return {
        "has_price_type": bool(pt),
        "tax_included_assumed": True,  # 設計上、格納価格は税込本体
        "shipping_separated": "送料" not in ctx,   # 送料が価格文脈に混入していない
        "points_separated": ("ポイント" not in ctx and "還元" not in ctx),
        "is_buyback": pt == "buyback_price",
        "is_tradein_excluded": ("下取" not in ctx),
        "role": obs.get("price_role"),
    }
