# -*- coding: utf-8 -*-
"""TCG: 販売店の BOX 実販売価格の台帳（config/tcg_retailer_box_prices.yaml）。メーカー公式定価とは別物として扱う。

- 台帳の価格は、販売店自身のページに「1BOX ○○円」と載っている価格だけ。パック価格×入数で BOX 価格を作らない（price_basis が
  retailer_listed_box でない行・パック由来の印がある行は採用しない）。公式定価（msrp.json の verified）には入れない。
- 受付状態は保存値を信じず、now から導出する（OPEN / WINNERS_ONLY / CLOSED / UNKNOWN）。判定できなければ UNKNOWN（参考のみ）。
- 条件付きの利益に使えるのは、LOTTERY で応募期間中（OPEN）の行だけ。当選しないと買えないので executable は常に False。
  OPEN 以外（応募終了・当選者のみ・期間外・不明）は REFERENCE_ONLY（過去の参考情報）で、利益は出さない。
- product_id が商品マスタに無い行は採用しない（同一性が不明 = 採用しない）。

collector との統合（抽選の collector が、同じ取得 HTML から販売価格も読む。取得は増やさない）:
- collector 由来の行（rows_from_events）の採用条件は 3 つだけ: 商品の同一性が exact・単位が BOX・価格が正の整数。JAN が無いだけでは捨てない。
  partial / ambiguous / none・単位が BOX でない（PACK / SET / UNKNOWN）・「各」「二種」など対応が曖昧な価格は採用せず、参考表示だけにする
- 手動台帳は検証・フォールバック。同じ商品・同じ店の行が両方にあれば collector を優先し、価格・日程の食い違いは検証エラー（merge_rows の errors）に出す
- collector 由来の verified_at は取得に成功した日（observed_at の日付）。生成時刻・実行日で新しく見せない
- 価格の種類（メーカー希望小売価格 / 正規販売店の通常販売価格 / 抽選販売価格 / 予約販売価格 / 終了した販売の参考価格）は、
  sale_method と受付状態から導出して表示ラベルに出す（price_class）。販売店の価格はメーカー公式定価（msrp.json）に書き換えない
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
STATE_LABEL = {S_OPEN: "応募受付中", S_WINNERS: "当選済みの人向けの購入期間（応募終了・新規応募不可）", S_CLOSED: "購入期間終了", S_UNKNOWN: "受付状態を確認できません"}
SRC_COLLECTOR, SRC_MANUAL = "collector", "manual"
# 価格の種類（表示ラベル）。メーカー希望小売価格は msrp.json 側の価格で、この台帳では作らない
PC_MSRP, PC_REGULAR, PC_LOTTERY, PC_PREORDER, PC_ENDED, PC_UNKNOWN = "MSRP", "REGULAR", "LOTTERY", "PREORDER", "ENDED_REFERENCE", "UNKNOWN"
PRICE_CLASS_LABEL = {PC_MSRP: "メーカー希望小売価格", PC_REGULAR: "正規販売店の通常販売価格", PC_LOTTERY: "抽選販売価格",
                     PC_PREORDER: "予約販売価格", PC_ENDED: "終了した販売の参考価格", PC_UNKNOWN: "販売方法を確認できない価格"}
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
    if e.get("source") == SRC_COLLECTOR:           # collector 由来の行: 採用条件は「同一性 exact・単位 BOX・正の価格」
        if e.get("product_match") != "exact":
            return "商品の同一性が exact ではない（参考表示のみ）"
        if e.get("unit") != "BOX":
            return "単位が BOX と確定していない（参考表示のみ）"
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


def price_class(sale_method, state: str) -> str:
    """価格の種類。終了した販売は参考価格、それ以外は販売方法から決める。販売方法が分からなければ UNKNOWN（通常価格と言わない）。"""
    if state == S_CLOSED:
        return PC_ENDED
    return {"LOTTERY": PC_LOTTERY, "PREORDER": PC_PREORDER, "NORMAL": PC_REGULAR}.get(str(sale_method or ""), PC_UNKNOWN)


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
            "source_kind": SOURCE_KIND, "executable": False,
            "source": e.get("source") or SRC_MANUAL, "price_class": price_class(e.get("sale_method"), st),
            "price_class_label": PRICE_CLASS_LABEL[price_class(e.get("sale_method"), st)],
            "winners_only_note": "すでに当選した人向けの購入期間です。一般の通常購入ではありません" if st == S_WINNERS else None}
    if why:
        return {**base, "kind": "REJECTED", "reason": why}
    if e.get("price_conflict"):
        return {**base, "kind": K_REFERENCE, "reason": "台帳と自動取得の価格が食い違っているため、利益は出さない（台帳の確認値を見直すまで参考止まり）"}
    hold = _event_hold(e["event_ref"], now) if st == S_OPEN and isinstance(e.get("event_ref"), dict) else None
    if hold:
        return {**base, "accept_state": S_UNKNOWN, "accept_label": STATE_LABEL[S_UNKNOWN], "kind": K_REFERENCE,
                "reason": f"{hold}。参考情報で、利益は出さない"}
    if st == S_OPEN:
        vd = _verified_day(e.get("verified_at"))
        if vd is None or (now.astimezone(JST).date() - vd).days > PRICE_MAX_AGE_DAYS:
            return {**base, "kind": K_REFERENCE, "reason": f"価格の確認が {PRICE_MAX_AGE_DAYS} 日より古い。参考情報で、利益は出さない"}
        return {**base, "kind": K_CONDITIONAL, "reason": START_UNCONFIRMED_LABEL if base["start_unconfirmed"] else None}
    start = _parse(e.get("apply_start"))
    if st == S_UNKNOWN and e.get("sale_method") == "LOTTERY" and start is not None and now.astimezone(JST) < start:
        return {**base, "kind": K_REFERENCE, "reason": f"応募開始前（開始日 {start.month}/{start.day}）のため利益は出さない"}
    return {**base, "kind": K_REFERENCE, "reason": STATE_LABEL[st] + "。過去の参考情報で、利益は出さない"}


# ── collector 由来の行（抽選の collector が同じ取得 HTML から読んだ販売価格）─────────────────────────
def _sale_method_of(ev: dict) -> str:
    """event_type から導出する（schema には持たない）。抽選・購入権は LOTTERY、予約は PREORDER。それ以外は UNKNOWN。"""
    et = ev.get("event_type")
    return "LOTTERY" if et in ("LOTTERY", "PURCHASE_RIGHT") else ("PREORDER" if et == "PREORDER" else "UNKNOWN")


def _pick(ev: dict, key: str, date_key: str):
    return ev.get(key) or ev.get(date_key) or None


def _event_hold(ev: dict, now: Optional[datetime]) -> Optional[str]:
    """イベントが「応募できる」と言えない理由（hub の商品の集約状態 product_view と同じ基準）。言えるなら None。

    日程の食い違い（conflict）・未検証（verified でない）・now から導出した状態が応募前〜受付中でないものは、受付中にしない。
    """
    from src.tcg.hub import status as st
    try:
        status = st.live_status(ev, now)
    except Exception:  # noqa: BLE001
        return "抽選の状態を判定できない"
    if ev.get("conflict"):
        return "抽選の日程が情報源どうしで食い違っているため、受付中とは扱わない"
    if ev.get("verified") is not True:
        return "抽選の告知が未検証のため、受付中とは扱わない"
    if status not in st.INTAKE:
        return "いま応募できる状態ではない（" + st.STATUS_LABEL.get(status, str(status)) + "）"
    return None


def row_from_event(ev: dict) -> Optional[dict]:
    """抽選イベント（LotteryEvent の辞書）を台帳と同じ形の行にする。価格が無いイベントは None（台帳に出さない）。

    価格があっても単位が BOX と確定していない・同一性が exact でないものは、行は作るが validate が不採用にする（参考表示のみ）。
    verified_at は取得に成功した日（observed_at の日付）。無ければ None（確認日が無い行は採用されない）。
    """
    if not isinstance(ev, dict):
        return None
    price = _int_price(ev.get("retail_price"))
    if price is None:
        return None
    unit = ev.get("price_unit") if ev.get("price_unit") in ("PACK", "BOX", "SET") else "UNKNOWN"
    od = _verified_day(ev.get("observed_at"))
    return {
        "id": "collector-" + str(ev.get("lottery_id") or ""), "source": SRC_COLLECTOR,
        "product_id": ev.get("product_id"), "tcg": ev.get("tcg"), "product_match": ev.get("product_match"),
        "retailer": ev.get("retailer_name") or ev.get("retailer"), "shop": ev.get("store_name") or ev.get("retailer_name") or ev.get("retailer"),
        "unit": unit, "box_condition": "UNKNOWN", "price_jpy": price,
        "price_basis": BASIS_OK if unit == "BOX" else f"retailer_listed_{unit.lower()}",
        "sale_method": _sale_method_of(ev),
        "apply_start": _pick(ev, "application_start", "application_start_date"), "apply_end": _pick(ev, "application_end", "application_end_date"),
        "winner_announcement": _pick(ev, "winner_announcement_at", "winner_announcement_date"),
        "purchase_start": _pick(ev, "purchase_start", "purchase_start_date"), "purchase_end": _pick(ev, "purchase_end", "purchase_end_date"),
        "shipping": None, "source_url": ev.get("source_url"), "verified_at": od.isoformat() if od else None,
        "jan": None, "human_confirmed": False, "product_code": ev.get("product_code"),
        "event_ref": ev,                     # 元イベント。受付中かどうかは classify が now で判定する（行を作った時刻で固定しない）
    }


def rows_from_events(items, now: Optional[datetime] = None) -> list:
    """公開済みの抽選イベントの一覧から、価格のあるものだけを台帳と同じ形の行にする。壊れた要素は飛ばす（出さない側に倒す）。"""
    out = []
    for ev in items if isinstance(items, list) else []:
        try:
            r = row_from_event(ev)
        except Exception:  # noqa: BLE001
            r = None
        if r:
            out.append(r)
    return out


def adoptable(row: dict) -> bool:
    """collector 由来の行の採用条件: 同一性 exact・単位 BOX・価格が正の整数（JAN は問わない）。"""
    return row.get("product_match") == "exact" and row.get("unit") == "BOX" and _int_price(row.get("price_jpy")) is not None and bool(row.get("product_id"))


def _norm_url(u) -> str:
    return str(u or "").strip().split("#")[0].rstrip("/")


def _norm_shop(s) -> str:
    import re
    return re.sub(r"[\s\u3000]|店$", "", str(s or ""))


def _same_listing(c: dict, l: dict) -> bool:
    """同じ商品・同じ販売店の行か（根拠 URL が同じ、または販売店と店舗名が同じ）。"""
    if c.get("product_id") != l.get("product_id") or not c.get("product_id"):
        return False
    if _norm_url(c.get("source_url")) and _norm_url(c.get("source_url")) == _norm_url(l.get("source_url")):
        return True
    return _norm_shop(c.get("retailer")) == _norm_shop(l.get("retailer")) and _norm_shop(c.get("shop")) == _norm_shop(l.get("shop"))


def _day_of(v, end: bool = False):
    d = _parse(v, end)
    return d.date() if d else None


_ROUND_GAP_DAYS = 3        # 応募期間の開始・終了がこの日数以内なら同じ回の抽選とみなす


def _same_round(c: dict, l: dict) -> bool:
    """collector の行と台帳の行が同じ回（同じ応募期間）の抽選か。どちらかに応募期間の日付が無ければ判別できないので同じ回として扱う。"""
    for k, end in (("apply_start", False), ("apply_end", True)):
        a, b = _day_of(c.get(k), end), _day_of(l.get(k), end)
        if a and b and abs((a - b).days) > _ROUND_GAP_DAYS:
            return False
    return True


def _pick_hit(hits: list, now: Optional[datetime]):
    """採用可能な collector の行のうち、受付中（応募可能）を優先し、無ければ応募終了日が新しいもの。並び順に依存しない（同点は元の順）。"""
    from src.tcg.models import now_jst
    t = now or now_jst()
    best, best_key = None, None
    for c in hits:
        if not adoptable(c):
            continue
        try:
            is_open = accept_state(c, t) == S_OPEN and (not isinstance(c.get("event_ref"), dict) or _event_hold(c["event_ref"], t) is None)
        except Exception:  # noqa: BLE001
            is_open = False
        end = _parse(c.get("apply_end"), True)
        key = (is_open, end.timestamp() if end else float("-inf"))
        if best_key is None or key > best_key:
            best, best_key = c, key
    return best


def _collector_open_gap(c: dict, l: dict, t: datetime) -> Optional[str]:
    """台帳の行が受付中のとき、collector の行がそれを置き換えてよいか。置き換えてはいけない理由（置き換えてよいなら None）。

    置き換えてよいのは、collector の行が受付中と言える、または「同じ回で、応募終了日・検証が確かで、日付どおり終了している」ときだけ。
    応募終了日が読めない・未検証・日程の食い違い・別の回・状態不明は、人が確認した台帳の受付中の行を消さない。
    """
    if accept_state(c, t) == S_OPEN and (not isinstance(c.get("event_ref"), dict) or _event_hold(c["event_ref"], t) is None):
        return None
    if not _same_round(c, l):
        return "自動取得の行は別の回（応募期間が台帳と違う）の抽選"
    if not c.get("apply_end"):
        return "自動取得の行は応募終了日が読めない"
    ev = c.get("event_ref")
    if isinstance(ev, dict) and ev.get("conflict"):
        return "自動取得の行は抽選の日程が情報源どうしで食い違っている"
    if isinstance(ev, dict) and ev.get("verified") is not True:
        return "自動取得の行は告知が未検証"
    if accept_state(c, t) not in (S_WINNERS, S_CLOSED):
        return "自動取得の行は応募の状態を判定できない"
    return None


def merge_rows(collector_rows: list, ledger_rows: list, now: Optional[datetime] = None) -> tuple:
    """(統合した行, 検証エラー)。collector 優先・台帳は検証とフォールバック。

    - 台帳の行に対応する collector の行が採用条件を満たす（adoptable）なら collector の行を使う。日程が食い違えば検証エラーに出す（collector を採用）
    - 同じ回で、単位 BOX 確定の collector 価格が台帳と食い違うときは、どちらが正しいか分からないので、その行は利益計算に使わず参考止まりにする（price_conflict。台帳の確認値を人が見直すまで。採用できない collector 行でも台帳に付ける）
    - 単位 UNKNOWN の collector 価格の食い違いは情報（INFO・ledger_kept_unit_unknown）として記録するだけで、台帳の利益計算は維持する
    - 別の回の行は価格・日程の食い違いとして扱わない
    - 台帳が受付中なのに、collector の行が受付中と言えない（応募終了日なし・未検証・食い違い・別の回）ときは、台帳の行を維持し、理由を検証エラーに出す
    - 対応する collector の行が採用条件を満たさない（単位不明・同一性が exact でない等）なら、台帳の行をそのまま使う
    - 台帳に無い collector の行は、そのまま加える（採用条件を満たさなければ validate が参考表示にする）
    """
    from src.tcg.models import now_jst
    t = now or now_jst()
    ledger = [{**l, "source": l.get("source") or SRC_MANUAL} for l in ledger_rows if isinstance(l, dict)]
    coll = [c for c in collector_rows if isinstance(c, dict)]
    out, errors, used = [], [], set()
    emitted = {}                       # 同じ collector 行を、台帳の複数行（別回）から 2 回出さない
    for l in ledger:
        hits = [(i, c) for i, c in enumerate(coll) if _same_listing(c, l)]
        used.update(i for i, _ in hits)
        chosen = _pick_hit([c for _, c in hits], now)
        if chosen is not None:
            try:
                ledger_open = accept_state(l, t) == S_OPEN
            except Exception:  # noqa: BLE001
                ledger_open = False
            gap = _collector_open_gap(chosen, l, t) if ledger_open else None
            if gap:
                errors.append({"kind": "COLLECTOR_NOT_OPEN", "product_id": l.get("product_id"), "shop": l.get("shop"), "source_url": l.get("source_url"),
                               "resolution": "ledger", "message": f"{gap}ため、台帳の受付中の行を維持した。公式ページで確認してください"})
                out.append(l)
                continue
        price_conflict = None
        for _, c in hits:
            if not _same_round(c, l):
                continue                 # 別回の抽選は価格が違って当然。検証エラーにしない
            if c.get("price_jpy") != l.get("price_jpy"):
                if c.get("unit") == "BOX":
                    errors.append({"kind": "PRICE_MISMATCH", "product_id": l.get("product_id"), "shop": l.get("shop"), "source_url": l.get("source_url"),
                                   "collector_price": c.get("price_jpy"), "manual_price": l.get("price_jpy"), "collector_adopted": c is chosen,
                                   "resolution": "reference_only", "severity": "WARN",
                                   "message": "同じ回で、台帳と自動取得（単位 BOX 確定）の価格が食い違っている。どちらが正しいか分からないため、利益計算に使わず参考止まりにした。公式ページで確認してください"})
                    price_conflict = {"collector_price": c.get("price_jpy"), "manual_price": l.get("price_jpy")}
                else:
                    # 単位が確認できない自動取得の価格は、別の商品・別単位の可能性が高い。それを根拠に人が確認した台帳を参考止まりにしない（情報として残す）
                    errors.append({"kind": "PRICE_MISMATCH", "product_id": l.get("product_id"), "shop": l.get("shop"), "source_url": l.get("source_url"),
                                   "collector_price": c.get("price_jpy"), "manual_price": l.get("price_jpy"), "collector_adopted": c is chosen,
                                   "resolution": "ledger_kept_unit_unknown", "severity": "INFO",
                                   "message": "単位が確認できない自動取得の価格と食い違っています。台帳の値を維持しました。公式ページで確認してください"})
        if chosen is None:
            out.append({**l, "price_conflict": price_conflict} if price_conflict else l)
            continue
        for k, end in (("apply_end", True), ("purchase_start", False), ("purchase_end", True)):
            if not _same_round(chosen, l):
                break                 # 別回の抽選（応募期間が違う）は、台帳の日程と食い違っても検証エラーにしない
            a, b = _day_of(chosen.get(k), end), _day_of(l.get(k), end)
            if a and b and a != b:
                errors.append({"kind": "SCHEDULE_MISMATCH", "field": k, "product_id": l.get("product_id"), "shop": l.get("shop"), "source_url": l.get("source_url"),
                               "collector_value": str(a), "manual_value": str(b), "resolution": "collector",
                               "message": f"collector と手動台帳の {k} が食い違っている。自動取得の値を採用しました。公式ページで確認してください"})
        if id(chosen) in emitted:
            if price_conflict and not out[emitted[id(chosen)]].get("price_conflict"):
                out[emitted[id(chosen)]] = {**chosen, "price_conflict": price_conflict}        # 2 回目の台帳行で食い違いが分かったときは、出力済みの行に付ける
            continue
        emitted[id(chosen)] = len(out)
        out.append({**chosen, "price_conflict": price_conflict} if price_conflict else chosen)
    out.extend(c for i, c in enumerate(coll) if i not in used)
    return out, errors
