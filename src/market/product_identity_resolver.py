#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ProductIdentityResolver — 汎用の商品同一性解決器。

Retail / Buyback / Secondary Market の観測を、正しい product_id へ厳格に紐付ける。
利益判定/AI/Opportunity/Notification/Capital/Execution ロジックは変更しない。

同一性の判定優先順位（Task5）:
  1. JAN / UPC / EAN
  2. Manufacturer SKU / MPN
  3. Exact model number（型番完全一致）
  4. Model name（機種名）
  5. Capacity（容量）
  6. Variant（Pro/Pro Max/HDF/Monochrome 等）
  7. Color
  8. Condition

重要ルール:
  - JAN/SKU/MPN/型番 が一致しない場合、商品名だけで high confidence にしない。
  - 容量不一致・機種不一致は match=false（main 不可）。
  - 検索結果ページ/トップページ由来は confidence を medium 以下へ、
    型番・容量が確認できなければ low（main 不可）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from src.market.price_quality import (
    extract_capacity_gb, _model_key, condition_class, extract_color,
    model_compatible, ACCESSORY_KW,
)


@dataclass
class ResolverResult:
    matched_product_id: Optional[str]
    product_match: bool
    model_match: bool
    capacity_match: Optional[bool]     # None=判定不能
    color_match: Optional[bool]
    condition_match: Optional[bool]
    identity_confidence: str            # high / medium / low
    identity_reason: str
    matched_tier: Optional[str] = None  # jan / sku / model_number / model_name / ...
    accessory_flag: bool = False
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "matched_product_id": self.matched_product_id,
            "product_match": self.product_match, "model_match": self.model_match,
            "capacity_match": self.capacity_match, "color_match": self.color_match,
            "condition_match": self.condition_match,
            "identity_confidence": self.identity_confidence,
            "identity_reason": self.identity_reason, "matched_tier": self.matched_tier,
            "accessory_flag": self.accessory_flag,
        }


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_/（）()、。・]", "", (s or "").lower())


def _is_accessory(text: str) -> bool:
    t = (text or "").lower()
    return any(k.lower() in t for k in ACCESSORY_KW)


class ProductIdentityResolver:
    """商品カタログに対して観測の同一性を解決する。"""

    def __init__(self, products: dict):
        """products: {product_id: {name, model_number, brand, jan, keywords, capacity}}"""
        self.products = products or {}
        # 事前計算: 各商品の正規化型番/機種キー/容量
        self._idx = {}
        for pid, p in self.products.items():
            name = p.get("name", "")
            self._idx[pid] = {
                "name": name,
                "model_number_norm": _norm(p.get("model_number", "")),
                "model_key": _model_key(name),
                "capacity": extract_capacity_gb(name),
                "jan": _norm(p.get("jan_code", "") or p.get("jan", "")),
                "keywords": [str(k) for k in (p.get("keywords") or [])],
                "brand": (p.get("brand") or "").lower(),
            }

    def resolve(self, *, source_title: str = "", source_url: str = "", source_text: str = "",
                brand: str = "", model: str = "", capacity: str = "", color: str = "",
                condition: str = "", jan: str = "", sku: str = "", mpn: str = "",
                link_type: str = "", expected_product_id: Optional[str] = None) -> ResolverResult:
        """観測を最適な product_id に解決する。expected_product_id があれば整合も検証。"""
        blob = " ".join([source_title, source_text, model, sku, mpn]).strip()
        acc = _is_accessory(source_title) or _is_accessory(source_text)

        cap_src = extract_capacity_gb(capacity) or extract_capacity_gb(source_title) \
            or extract_capacity_gb(blob)
        model_key_src = _model_key(source_title or blob or model)
        jan_n = _norm(jan)
        sku_n = _norm(sku or mpn)

        best = None
        best_tier = None
        for pid, ix in self._idx.items():
            # Tier1: JAN
            if jan_n and ix["jan"] and jan_n == ix["jan"]:
                best, best_tier = pid, "jan"
                break
        if not best:
            for pid, ix in self._idx.items():
                # Tier2/3: SKU/MPN or exact model number
                if sku_n and ix["model_number_norm"] and sku_n == ix["model_number_norm"]:
                    best, best_tier = pid, "sku_mpn"
                    break
                if ix["model_number_norm"] and ix["model_number_norm"] in _norm(blob):
                    best, best_tier = pid, "model_number"
                    break
        if not best:
            # Tier4-6: model name + capacity（機種キー一致 かつ 容量一致）
            cands = []
            for pid, ix in self._idx.items():
                if ix["model_key"] and ix["model_key"] == model_key_src:
                    cands.append(pid)
            if len(cands) == 1:
                best, best_tier = cands[0], "model_name"
            elif len(cands) > 1 and cap_src is not None:
                # 機種同一の複数候補 → 容量で絞る
                capm = [pid for pid in cands if self._idx[pid]["capacity"] == cap_src]
                if len(capm) == 1:
                    best, best_tier = capm[0], "model_name+capacity"
                elif expected_product_id in cands:
                    best, best_tier = expected_product_id, "model_name_ambiguous"
            elif expected_product_id and expected_product_id in cands:
                best, best_tier = expected_product_id, "model_name_ambiguous"

        # ソースからモデル情報が抽出できない（汎用ラベル「買取価格」等）→ 独立検証不能。
        # この場合は collector の割当を信頼し、model/capacity は None（不一致ではない）とする。
        source_has_model = bool(model_key_src.strip())
        if not source_has_model and expected_product_id and expected_product_id in self._idx:
            downgraded = link_type in ("search", "shop_home")
            conf = "low" if (downgraded or acc) else "medium"
            reason = ("accessory_detected" if acc else
                      "no_source_title_assignment_trusted" if not downgraded else
                      "nonproduct_url_no_source_title")
            return ResolverResult(
                matched_product_id=expected_product_id,
                product_match=(not acc), model_match=None, capacity_match=None,
                color_match=None, condition_match=None,
                identity_confidence=conf, identity_reason=reason, matched_tier="assignment_trusted",
                accessory_flag=acc, details={"source_has_model": False},
            )

        # 判定
        matched = best
        ix = self._idx.get(matched) if matched else None
        # model_match: variant/世代の矛盾のみを False とする（型番有無等の差は許容）
        model_match = (model_compatible(source_title or blob, ix["name"])
                       if (ix and source_has_model) else None)
        cap_match = None
        if ix and ix["capacity"] is not None and cap_src is not None:
            cap_match = (ix["capacity"] == cap_src)
        cond_match = None
        if condition and ix:
            cond_match = (condition_class(condition) == condition_class(
                self.products.get(matched, {}).get("condition", "")) if self.products.get(matched, {}).get("condition") else None)
        col_src = extract_color(source_title)
        col_match = None  # color は価格差 variant 時のみ厳格（呼び出し側で扱う）

        # confidence 決定（Task5/12）
        conf, reason = self._confidence(best_tier, cap_match, model_match, acc, link_type, cap_src, ix)

        # expected と食い違う場合は mismatch を明示
        if expected_product_id and matched and expected_product_id != matched:
            reason = f"reassigned_from_{expected_product_id}:{reason}"

        return ResolverResult(
            matched_product_id=matched,
            product_match=bool(matched) and not acc,
            model_match=model_match, capacity_match=cap_match,
            color_match=col_match, condition_match=cond_match,
            identity_confidence=conf, identity_reason=reason, matched_tier=best_tier,
            accessory_flag=acc,
            details={"capacity_src": cap_src, "model_key_src": model_key_src},
        )

    def _confidence(self, tier, cap_match, model_match, acc, link_type, cap_src, ix) -> tuple:
        if acc:
            return "low", "accessory_detected"
        if not tier:
            return "low", "no_identity_match"
        # 容量不一致は即 low（main 不可）
        if cap_match is False:
            return "low", "capacity_mismatch"
        # 検索結果/トップページは high にしない（Task12）
        downgraded = link_type in ("search", "shop_home")
        if tier in ("jan", "sku_mpn", "model_number"):
            # 型番・JAN 一致は high（容量も一致 or 容量非関与）
            if cap_match is False:
                return "low", "capacity_mismatch"
            if downgraded:
                return "medium", f"{tier}_but_nonproduct_url"
            return "high", f"exact_{tier}"
        if tier in ("model_name+capacity",):
            if downgraded:
                return "medium", "model+capacity_but_nonproduct_url"
            return "high", "model_name_and_capacity"
        if tier == "model_name":
            # 型番なしの機種名一致 → high にしない（Task5）
            return ("low" if downgraded else "medium"), "model_name_only_no_modelnumber"
        # 曖昧
        return "low", "ambiguous_model_candidates"


def build_products_index(db_path) -> dict:
    """DB products から resolver 用インデックスを構築。"""
    import sqlite3
    c = sqlite3.connect(str(db_path))
    c.row_factory = sqlite3.Row
    out = {}
    try:
        for r in c.execute("SELECT id,name,brand,model_number,jan_code,keywords FROM products WHERE is_active=1"):
            kw = r["keywords"]
            try:
                import json as _j
                kw = _j.loads(kw) if kw and kw.strip().startswith("[") else (kw.split(",") if kw else [])
            except Exception:
                kw = []
            out[r["id"]] = {"name": r["name"], "brand": r["brand"],
                            "model_number": r["model_number"], "jan_code": r["jan_code"],
                            "keywords": kw}
    finally:
        c.close()
    return out
