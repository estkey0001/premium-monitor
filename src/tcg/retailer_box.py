# -*- coding: utf-8 -*-
"""TCG: 販売店の BOX 実販売価格の台帳（config/tcg_retailer_box_prices.yaml）。メーカー公式定価とは別物として扱う。

- 台帳の価格は、販売店自身のページに「1BOX ○○円」と載っている価格だけ。パック価格×入数で BOX 価格を作らない（price_basis が
  retailer_listed_box でない行・パック由来の印がある行は採用しない）。公式定価（msrp.json の verified）には入れない。
- 受付状態は保存値を信じず、now から導出する（OPEN / WINNERS_ONLY / CLOSED / UNKNOWN）。判定できなければ UNKNOWN（参考のみ）。
- 条件付きの利益に使えるのは、LOTTERY で応募期間中（OPEN）の行だけ。当選しないと買えないので executable は常に False。
  OPEN 以外（応募終了・当選者のみ・期間外・不明）は REFERENCE_ONLY（過去の参考情報）で、利益は出さない。
- product_id が商品マスタに無い行は採用しない（同一性が不明 = 採用しない）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from src.tcg.models import JST

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "tcg_retailer_box_prices.yaml"

SOURCE_KIND = "retailer_box_price"                 # 公式定価（msrp）とは別のラベル
BASIS_OK = "retailer_listed_box"
S_OPEN, S_WINNERS, S_CLOSED, S_UNKNOWN = "OPEN", "WINNERS_ONLY", "CLOSED", "UNKNOWN"
STATE_LABEL = {S_OPEN: "応募受付中", S_WINNERS: "当選者のみ購入可（応募終了）", S_CLOSED: "購入期間終了", S_UNKNOWN: "受付状態を確認できません"}
K_CONDITIONAL, K_REFERENCE = "CONDITIONAL", "REFERENCE_ONLY"
PRICE_MAX_AGE_DAYS = 14                            # 価格の確認日がこれより古い行は、受付中でも条件付きの利益に使わず参考にする
CONDITION_TEXT = "抽選に当選した場合のみ（当選しなければ購入できません）"


def _int_price(v) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def _https(v) -> bool:
    return isinstance(v, str) and v.startswith("https://") and len(v) > 12


def _parse(v, end_of_day: bool = False) -> Optional[datetime]:
    """日付 or 時刻付き ISO。日付だけなら、終了側はその日の終わり、開始側は 0 時（JST）。読めなければ None。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=JST)
        if isinstance(v, date):                                          # yaml が日付だけを date に読んだ場合
            d = datetime(v.year, v.month, v.day, tzinfo=JST)
        else:
            s = str(v).strip()
            if len(s) != 10:
                d = datetime.fromisoformat(s.replace("Z", "+00:00"))
                return d if d.tzinfo else d.replace(tzinfo=JST)
            d = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=JST)
        return d + timedelta(days=1) - timedelta(seconds=1) if end_of_day else d
    except Exception:  # noqa: BLE001
        return None


def load_ledger(path: Path = CONFIG_PATH) -> list:
    """台帳の行（辞書のリスト）。読めない・壊れているときは空（何も採用しない = 安全側）。"""
    try:
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return []
    ents = data.get("entries") if isinstance(data, dict) else None
    return [e for e in ents if isinstance(e, dict)] if isinstance(ents, list) else []


def accept_state(e: dict, now: datetime) -> str:
    """応募期間・当選者の購入期間から now で導出する。保存値は使わない。"""
    now = now.astimezone(JST)
    if e.get("sale_method") != "LOTTERY":
        return S_UNKNOWN                                      # 通常販売・予約は在庫・受付が確認できないので、受付中とは言わない
    start = _parse(e.get("apply_start"))
    end = _parse(e.get("apply_end"), True)
    p_start = _parse(e.get("purchase_start"))
    p_end = _parse(e.get("purchase_end"), True)
    if p_end and now > p_end:
        return S_CLOSED
    if end:
        if start and now < start:
            return S_UNKNOWN                                  # 応募開始前: 受付中ではない（参考のみ）
        if e.get("apply_start") not in (None, "") and start is None and now <= end:
            return S_UNKNOWN                                  # 開始日が書かれているのに読めない: 開始前かもしれないので OPEN にしない
        if now <= end:
            return S_OPEN
        return S_WINNERS if p_end else S_CLOSED
    if p_start and p_end and now >= p_start:
        return S_WINNERS                                      # 応募終了日の記載が無くても、購入期間に入っていれば応募は終わっている
    return S_UNKNOWN


def _verified_day(v) -> Optional[date]:
    """verified_at を ISO の日付（または日時）として読む。読めなければ None。"""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        s = str(v).strip()
        return datetime.strptime(s, "%Y-%m-%d").date() if len(s) == 10 else datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:  # noqa: BLE001
        return None


def validate(e: dict, master: dict, now: Optional[datetime] = None) -> Optional[str]:
    """採用できない理由（採用できるなら None）。now があれば、確認日が未来でないことも見る。"""
    if (e.get("tcg"), e.get("product_id")) not in master:
        return "商品マスタに無い product_id（同一性が不明）"
    if e.get("unit") != "BOX":
        return "BOX 単位ではない"
    if e.get("price_basis") != BASIS_OK or e.get("derived_from_pack") or e.get("pack_price") or e.get("packs"):
        return "販売店ページの BOX 価格ではない（パック価格から作った価格は採用しない）"
    if _int_price(e.get("price_jpy")) is None:
        return "価格が不正"
    if not _https(e.get("source_url")):
        return "根拠 URL が無い"
    if not e.get("verified_at"):
        return "確認日が無い"
    vd = _verified_day(e.get("verified_at"))
    if vd is None:
        return "確認日が日付として読めない"
    if now is not None and vd > now.astimezone(JST).date():
        return "確認日が未来の日付"
    return None


START_UNCONFIRMED_LABEL = "応募期間内の可能性（開始日未確認）"


def _start_unconfirmed(e: dict) -> bool:
    """応募開始日が台帳に無い（または apply_start_known: false）行。OPEN は維持するが、開始前でないことは確認できていないと明記する。"""
    return e.get("apply_start_known") is False or e.get("apply_start") in (None, "")


def classify(e: dict, master: dict, now: datetime) -> dict:
    """台帳 1 行の扱い。kind: CONDITIONAL（応募受付中で、条件付きの利益に使える）／REFERENCE_ONLY（参考情報）／REJECTED（不採用）。"""
    why = validate(e, master, now)
    st = accept_state(e, now)
    base = {"id": e.get("id"), "product_id": e.get("product_id"), "tcg": e.get("tcg"), "retailer": e.get("retailer"), "shop": e.get("shop"),
            "unit": e.get("unit"), "price_jpy": e.get("price_jpy"), "sale_method": e.get("sale_method"), "accept_state": st,
            "accept_label": STATE_LABEL[st], "shipping": e.get("shipping"), "source_url": e.get("source_url"),
            "verified_at": e.get("verified_at"), "box_condition": e.get("box_condition") or "UNKNOWN", "jan": e.get("jan"),
            "human_confirmed": e.get("human_confirmed") is True, "apply_end": e.get("apply_end"),
            "start_unconfirmed": _start_unconfirmed(e),
            "purchase_start": e.get("purchase_start"), "purchase_end": e.get("purchase_end"),
            "source_kind": SOURCE_KIND, "executable": False}
    if why:
        return {**base, "kind": "REJECTED", "reason": why}
    if st == S_OPEN:
        vd = _verified_day(e.get("verified_at"))
        if vd is None or (now.astimezone(JST).date() - vd).days > PRICE_MAX_AGE_DAYS:
            return {**base, "kind": K_REFERENCE, "reason": f"価格の確認が {PRICE_MAX_AGE_DAYS} 日より古い。参考情報で、利益は出さない"}
        return {**base, "kind": K_CONDITIONAL, "reason": START_UNCONFIRMED_LABEL if base["start_unconfirmed"] else None}
    start = _parse(e.get("apply_start"))
    if st == S_UNKNOWN and e.get("sale_method") == "LOTTERY" and start is not None and now.astimezone(JST) < start:
        return {**base, "kind": K_REFERENCE, "reason": f"応募開始前（開始日 {start.month}/{start.day}）のため利益は出さない"}
    return {**base, "kind": K_REFERENCE, "reason": STATE_LABEL[st] + "。過去の参考情報で、利益は出さない"}
