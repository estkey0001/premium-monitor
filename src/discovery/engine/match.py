"""商品マスタとの照合（新しい照合の規則は書かない。src/tcg/lottery/products.resolve_product だけ）。

exact は商品コードか名前の厳密な一致だけ。名前の部分一致・複数候補は結び付けない（G5 で product_unmapped）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TCG_DIR = PROJECT_ROOT / "exports" / "tcg"


def load_registry(tcg_dir: Path = TCG_DIR) -> dict:
    """{"POKEMON": [...], "ONE_PIECE": [...]}（resolve_product に渡す形: product_id・name・product_code・release_date）。"""
    out: dict = {"POKEMON": [], "ONE_PIECE": []}
    try:
        reg = json.loads((Path(tcg_dir) / "pokemon_registry.json").read_text(encoding="utf-8"))
        # pokemon_registry.json には ONE PIECE の正本の行（tcg_verified_products.json から合流）も入る。tcg で振り分ける
        for p in reg.get("products") or []:
            if isinstance(p, dict) and p.get("product_id"):
                out["ONE_PIECE" if p.get("tcg") == "ONE_PIECE" else "POKEMON"].append(p)
    except (OSError, ValueError, AttributeError):
        pass
    try:
        latest = json.loads((Path(tcg_dir) / "latest.json").read_text(encoding="utf-8"))
        seen = {p["product_id"] for p in out["ONE_PIECE"]}
        for e in latest.get("events") or []:
            if isinstance(e, dict) and e.get("store") == "ONEPIECE_CARD_OFFICIAL" and e.get("product_id") \
                    and e["product_id"] not in seen:
                seen.add(e["product_id"])
                out["ONE_PIECE"].append({"product_id": e["product_id"], "name": e.get("product_name") or "",
                                         "product_code": e.get("product_code"), "release_date": e.get("release_date")})
    except (OSError, ValueError, AttributeError):
        pass
    return out


def match_product(name: Optional[str], code: Optional[str], tcg: Optional[str], registry: dict) -> dict:
    """{product_id, product_match(exact/ambiguous/partial/none), provisional_product}。"""
    from src.tcg.lottery.products import resolve_product
    if not name and not code:
        return {"product_id": None, "product_match": "none", "provisional_product": True}
    q = (name or "") + (f"【{code}】" if code and code not in (name or "") else "")
    regs = [registry.get(tcg) or []] if tcg else [registry.get("POKEMON") or [], registry.get("ONE_PIECE") or []]
    results = [resolve_product(q, r) for r in regs if r]
    exact = [r for r in results if r.get("product_match") == "exact"]
    if len(exact) == 1:
        return {k: exact[0].get(k) for k in ("product_id", "product_match", "provisional_product")}
    if len(exact) > 1 or any(r.get("product_match") == "ambiguous" for r in results):
        return {"product_id": None, "product_match": "ambiguous", "provisional_product": False}
    if any(r.get("product_match") == "partial" for r in results):
        return {"product_id": None, "product_match": "partial", "provisional_product": True}
    return {"product_id": None, "product_match": "none", "provisional_product": True}
