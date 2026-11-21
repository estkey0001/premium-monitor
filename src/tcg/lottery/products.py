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
# 商品名に混じる店舗側の言い回し（販売方法・販売数量の語）。商品を区別する数（「9種」「2種」など）は落とさない
_NOISE = re.compile(r"の?(追加)?抽選(販売|受付|予約)?(について|のお知らせ)?|[（(]\s*(再販|BOX|シュリンク[^）)]*|再入荷|追加)\s*[）)]|"
                    r"※|\d+\s*(BOX|パック)|(?<![A-Za-z])BOX(?![A-Za-z])", re.I)
_KIND_WORDS = re.compile(r"(強化拡張パック|拡張パック|ハイクラスパック|ブースターパック|エクストラブースター|"
                         r"プレミアムブースター|スタートデッキ(EX)?|スターターセット)")
_QUOTED2 = re.compile(r"[「『]([^」』]{2,60})(?:[」』]|$)")
_CODE = re.compile(r"(?<![A-Za-z])(OP|EB|PRB|PEB|ST|P)-?(\d{2})(?!\d)")
_GENERIC = frozenset(_norm(x) for x in ("再販品", "再入荷商品", "再入荷", "新商品", "商品"))


def _codes(name: str) -> set[str]:
    """商品コード（OP-18・EB-05 等）。【】内のコードだけを見る（本文中の英数字を商品コードにしない）。"""
    out = set()
    for br in re.findall(r"[【\[]([^】\]]*)[】\]]", unicodedata.normalize("NFKC", name or "")):
        m = _CODE.fullmatch(br.strip())
        if m:
            out.add(f"{m.group(1).upper()}-{m.group(2)}")
    return out


def _clean(x: str) -> str:
    x = _NOISE.sub("", x)
    x = x.strip(" 　・-")
    return _norm(x)


def _core_names(name: str) -> set[str]:
    """商品を指す名前の候補（「」『』内の名前。無ければブランド名・品番・店舗側の言い回し・種別語を除いた全体）。"""
    nm = unicodedata.normalize("NFKC", name or "")
    q = []
    for x in _QUOTED2.findall(nm):
        stripped = _KIND_WORDS.sub("", x)                      # 「拡張パック 30th CELEBRATION」→ 30th CELEBRATION（種別は別に照合する）
        c = _clean(stripped) or _clean(x)
        if c:
            q.append(c)
    if q:
        return set(q)
    s = _CODE_SUFFIX.sub("", nm)
    s = _BRAND_PREFIX.sub("", s.strip())
    s = _KIND_WORDS.sub("", _NOISE.sub("", s))
    return {_clean(s)}


def _has_quote(name: str) -> bool:
    return bool(_QUOTED2.search(unicodedata.normalize("NFKC", name or "")))


def _rec_codes(rec: dict) -> set[str]:
    c = {str(rec.get("product_code") or "").upper()} - {""}
    return c | _codes(rec.get("name", ""))


def resolve_product(product_name: str, registry: list[dict]) -> dict:
    """registry と照合し {product_id, product_match, provisional_product} を返す。

    exact（商品 ID まで確定して公開してよい）は次のどちらかだけ:
      1. 商品コード（【EB-05】等）が双方にあり、registry で 1 件に定まる
      2. 名前の本体（「」内、無ければ種別語・店舗の言い回しを除いた全体）が完全一致し、候補が 1 件、
         種別が食い違わず、かつ（名前が「」で囲まれているか、種別語が名前に含まれている）
    部分一致・汎用語（再販品など）・複数候補は紐付けない（partial / none / ambiguous）。
    """
    registry = registry or []
    codes = _codes(product_name)
    if codes:
        kind0 = _kind(product_name)
        hits = [r for r in registry if codes & _rec_codes(r)
                and not (kind0 and _kind(r.get("name", "")) and kind0 != _kind(r.get("name", "")))]   # コードが同じでも種別が食い違えば別商品
        if len(hits) == 1:
            h = hits[0]
            return {"product_id": h["product_id"], "product_match": "exact", "provisional_product": False,
                    "release_date": h.get("release_date")}
        if len(hits) > 1:
            return {"product_id": None, "product_match": "ambiguous", "provisional_product": False, "release_date": None}
    names = {n for n in _core_names(product_name) if n}
    if not names or names <= _GENERIC:
        return {"product_id": None, "product_match": "none", "provisional_product": True, "release_date": None}
    kind = _kind(product_name)
    cands = []
    for rec in registry:
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
    if len(exact) == 1 and (_has_quote(product_name) or kind):
        return {"product_id": exact[0]["product_id"], "product_match": "exact",
                "provisional_product": False,
                "release_date": exact[0].get("release_date")}
    if len(exact) > 1 or len(cands) > 1:
        return {"product_id": None, "product_match": "ambiguous",
                "provisional_product": False, "release_date": None}
    if len(cands) == 1:
        # 名前の一部が一致しただけ（または種別が分からない）。別商品の可能性があるので紐付けない
        return {"product_id": None, "product_match": "partial",
                "provisional_product": True, "release_date": None}
    return {"product_id": None, "product_match": "none",
            "provisional_product": True, "release_date": None}
