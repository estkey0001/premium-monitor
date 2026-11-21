# -*- coding: utf-8 -*-
"""公式ページで確認した TCG 商品の台帳（data/tcg_verified_products.json）を商品の登録に合流させる。

目的: 公式 API の取得窓に入らない商品（過去の再販対象）と、API が無い ONE PIECE の商品マスターを、
根拠（公式の URL と確認日）つきで持つ。抽選イベントを商品に紐付ける照合（resolve_product）と、
TCG ハブの商品情報・定価に使う。

守ること:
- 公式 API の行（今日取れた行）が同じ商品 ID にあれば、そちらを優先し、台帳の行は足さない。
- 根拠（https の公式 URL・確認日）が揃わない行は読み捨てる（推測で埋めない）。
- BOX の価格はパック価格から作らない。retail_price は公式が商品 1 個の価格と明記した行だけ（basis=product_unit）。
- 確認日は台帳の値のまま保つ（読み込んだ日に更新しない）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parents[2] / "data" / "tcg_verified_products.json"
_TCGS = ("POKEMON", "ONE_PIECE")
_BASIS = ("pack", "product_unit", None)


def _valid(rec: Any) -> bool:
    if not isinstance(rec, dict):
        return False
    ev = rec.get("evidence")
    if not isinstance(ev, dict) or not str(ev.get("source_url") or "").startswith("https://") or not ev.get("checked_on"):
        return False
    if not str(rec.get("official_url") or "").startswith("https://"):
        return False
    if not rec.get("product_id") or not rec.get("name") or rec.get("tcg") not in _TCGS:
        return False
    if rec.get("retail_price_basis") not in _BASIS:
        return False
    price = rec.get("retail_price")
    if price is not None and (not isinstance(price, int) or isinstance(price, bool) or price <= 0
                              or rec.get("retail_price_basis") != "product_unit"):
        return False                      # 商品 1 個の価格と明記されていない値は定価にしない
    return True


def load(path: Path | None = None) -> list[dict]:
    """台帳の行（検証を通ったものだけ）。無い・壊れているときは空。"""
    try:
        doc = json.loads((path or PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = doc.get("products") if isinstance(doc, dict) else None
    out, seen = [], set()
    for rec in rows if isinstance(rows, list) else []:
        if _valid(rec) and rec["product_id"] not in seen:
            seen.add(rec["product_id"])
            out.append({**rec, "manual_verified": True})
    return out


def merge(registry: list[dict], verified: list[dict] | None = None) -> list[dict]:
    """公式 API 由来の registry に、台帳の行を足す（同じ商品 ID は API 側を優先）。"""
    reg = list(registry or [])
    have = {r.get("product_id") for r in reg if isinstance(r, dict)}
    for rec in (load() if verified is None else verified):
        if rec["product_id"] not in have:
            reg.append(rec)
            have.add(rec["product_id"])
    return reg


def is_manual(rec: dict) -> bool:
    return bool(isinstance(rec, dict) and rec.get("manual_verified"))
