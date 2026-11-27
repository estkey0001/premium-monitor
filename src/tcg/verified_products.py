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


# 商品画像を置いてよい公式のホスト（TCG ごと）。画像だけの検査なので、外れても行は捨てず画像を None にする
IMAGE_HOSTS = {"POKEMON": "pokemon-card.com", "ONE_PIECE": "onepiece-cardgame.com"}


def image_ok(tcg: Any, url: Any) -> bool:
    """公式サイトの https の画像か（TCG とホストが一致し、未発売の仮画像 noimage でない）。"""
    from urllib.parse import urlparse
    base = IMAGE_HOSTS.get(tcg) if isinstance(tcg, str) else None
    if not base or not isinstance(url, str):
        return False
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not (host == base or host.endswith("." + base)):
        return False
    path = u.path.lower()
    # ONE PIECE 公式の /renewal/ 配下の画像は cross-origin-resource-policy: same-site を返す（他サイトへの埋め込みを公式が許可していない）。
    # 回避（中継・保存しての再配信）はせず、使わない（2026-11-26 確認）
    if tcg == "ONE_PIECE" and path.startswith("/renewal/"):
        return False
    return "noimage" not in path


# 画像の公開には 2 つの段階がある。混同しない。
#   (1) 社内の使用判断（IMAGE_INTERNAL_DECISION）: 運営者が「使いたい」と決めた記録。権利者の許可ではないので、これだけでは公開しない。
#   (2) 権利者の利用許可・公開利用の根拠（IMAGE_RIGHTS_PERMISSION）: 画像ごと（URL ごと）に、許可の根拠の URL・確認日・根拠の種類を記録したもの。
# 公開ページに公式画像を出すのは、(2) に記録がある画像だけ（image_publishable）。無ければ代わりの画像（SVG）。
#
# 2026-11-27 の確認（画像ごとの公開利用の根拠）:
#   - ポケモンカード公式 pokemon-card.com/policy.html: 掲載データのコピー・複製・掲示・配布を断り、リンクはテキストリンクに限る。
#     報道・小売・アフィリエイト向けの画像の利用許諾・素材の提供の記載なし → 根拠なし（禁止）。
#   - ONE PIECE カードゲーム公式（トップのフッター）: 画像・テキスト・データの無断転用・転載を断る。
#     バンダイのウェブサイトご利用条件（bandai.co.jp/site/notice/）: 事前許諾なしの複製・掲示・頒布を禁止。画像の利用許諾の規定なし → 根拠なし（禁止）。
#   したがって、どの公式画像にも公開利用の根拠が無い。IMAGE_RIGHTS_PERMISSION は空（全部が代わりの画像）。
#   権利者から許可を得たときは、その画像の URL ごとに {"tcg", "basis", "source_url", "checked_on"} を記録する。
IMAGE_INTERNAL_DECISION: dict[str, str] = {
    "POKEMON": "2026-11-27 運営者が公式画像の使用を希望（社内の判断。権利者の許可ではない。サイトポリシーは掲示を禁止）",
    "ONE_PIECE": "2026-11-27 運営者が公式画像の使用を希望（社内の判断。権利者の許可ではない。公式・バンダイの規定は転載を禁止）",
}

IMAGE_RIGHTS_PERMISSION: dict[str, dict] = {}

_PERMISSION_KEYS = ("tcg", "basis", "source_url", "checked_on")


def rights_permission(url: Any) -> dict | None:
    """その画像 URL の、権利者の利用許可・公開利用の根拠の記録。根拠の項目がそろっていなければ None（記録が無いのと同じ）。"""
    rec = IMAGE_RIGHTS_PERMISSION.get(url) if isinstance(url, str) else None
    if not isinstance(rec, dict) or not all(isinstance(rec.get(k), str) and rec.get(k).strip() for k in _PERMISSION_KEYS):
        return None
    if not str(rec["source_url"]).startswith("https://"):
        return None
    return rec


def image_publishable(tcg: Any, url: Any) -> bool:
    """公開ページに出してよい公式画像か: 公式のホストの画像（image_ok）で、かつその画像に権利者の利用許可・公開利用の根拠の記録がある
    （rights_permission。TCG も一致）。社内の使用判断（IMAGE_INTERNAL_DECISION）だけでは出さない。"""
    if not (isinstance(tcg, str) and image_ok(tcg, url)):
        return False
    rec = rights_permission(url)
    return bool(rec) and rec.get("tcg") == tcg


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
            img = rec.get("official_image_url")
            out.append({**rec, "manual_verified": True,
                        "official_image_url": img if image_ok(rec.get("tcg"), img) else None})
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
