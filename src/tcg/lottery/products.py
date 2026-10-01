# -*- coding: utf-8 -*-
"""Task20 / Task21: 抽選イベントを商品 registry に紐付ける。

- 「」内の商品名と商品種別（拡張パック / デッキ / BOX / カードセット 等）が
  一致し、候補が1件に絞れる場合だけ product_id を付ける（exact）。
- 候補が複数（例: 9種のカードセットを「9種セット」として抽選）なら紐付けない
  （ambiguous）。商品名だけで high confidence にしない。
- registry に無い商品（新商品・旧商品の再販）は provisional_product=True のまま保持し、
  別の商品へ誤って紐付けない。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

_QUOTED = re.compile(r"「([^」]{2,40})」")
_KINDS = (
    ("deck", ("デッキ", "スターターセット", "スタートデッキ")),
    ("cardset", ("カードセット",)),
    ("premium", ("FUTURISTIC BOX", "プレミアムトレーナーボックス", "スペシャルBOX",
                 "スペシャルボックス", "コレクション")),
    ("booster", ("拡張パック", "強化拡張パック", "ハイクラスパック", "ブースターパック",
                 "エクストラブースター", "プレミアムブースター")),
)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"\s+", "", s)


def _kind(name: str) -> Optional[str]:
    for kind, words in _KINDS:
        if any(w.lower() in (name or "").lower() for w in words):
            return kind
    return None


_BRAND_PREFIX = re.compile(r"^(ポケモンカードゲーム|ONE\s*PIECEカードゲーム|ワンピースカードゲーム)\s*"
                           r"(MEGA)?\s*", re.I)
_CODE_SUFFIX = re.compile(r"[【\[（(][^】\]）)]*[】\]）)]")


def _core_names(name: str) -> set[str]:
    """商品を指す名前の候補（「」内の名前。無ければブランド名・品番を除いた全体）。"""
    q = [_norm(x) for x in _QUOTED.findall(name or "")]
    if q:
        return set(q)
    s = _CODE_SUFFIX.sub("", name or "")
    s = _BRAND_PREFIX.sub("", s.strip())
    return {_norm(s)}


def resolve_product(product_name: str, registry: list[dict]) -> dict:
    """registry と照合し {product_id, product_match, provisional_product} を返す。"""
    names = _core_names(product_name)
    kind = _kind(product_name)
    cands = []
    for rec in registry or []:
        rnames = _core_names(rec.get("name", ""))
        if not (names & rnames):
            # 「」の中身が一方に含まれる場合（「30th CELEBRATION カードセット ニャオハ…」等）
            if not any(n and r and (n in r or r in n) for n in names for r in rnames):
                continue
        rkind = _kind(rec.get("name", ""))
        if kind and rkind and kind != rkind:
            continue
        cands.append(rec)
    exact = [c for c in cands if names & _core_names(c.get("name", ""))]
    if len(exact) == 1:
        return {"product_id": exact[0]["product_id"], "product_match": "exact",
                "provisional_product": False,
                "release_date": exact[0].get("release_date")}
    if len(exact) > 1 or len(cands) > 1:
        return {"product_id": None, "product_match": "ambiguous",
                "provisional_product": False, "release_date": None}
    if len(cands) == 1:
        # 名前の一部が一致しただけ。別商品の可能性があるので紐付けない
        return {"product_id": None, "product_match": "partial",
                "provisional_product": True, "release_date": None}
    return {"product_id": None, "product_match": "none",
            "provisional_product": True, "release_date": None}
