"""利益商品を「今すぐ行動できるか」で判定する正本（Phase 18）。

今すぐ行動できる（actionable）のは、次が全部そろうときだけ:
- 確定の利益案件（opportunity.eligibility を通った。利益がプラス・同一性・費用・鮮度）
- 今の購入の経路（公式の購入ページ・抽選の申込ページなどの URL。ストアのトップなどの一般のページは使わない）
- 今の購入の可否の証拠（下の ACTIONABLE_TYPES）

購入の可否の種類（availability）:
- 通常販売: IN_STOCK（在庫ありを確認してから3時間以内。stock_state.STOCK_FRESH_SECONDS を再利用）/
  STOCK_STALE（在庫ありだったが3時間を過ぎた＝更新待ち）/ OUT_OF_STOCK / UNKNOWN / SALE_ENDED
- 抽選: LOTTERY_OPEN（受付期間中）/ LOTTERY_UPCOMING（受付前）/ LOTTERY_CLOSED（締切後）/
  LOTTERY_UNKNOWN（日程が分からない。OPEN と推測しない）/ PURCHASE_PERIOD_OPEN（当選者だけの購入期間。一般の人は
  行動できない）
- 予約・先着: PREORDER_OPEN / PREORDER_CLOSED / FIRST_COME_OPEN / FIRST_COME_CLOSED

期限は2つのまま（目的が違う。Phase 15 で明記）:
- 利益の案件の「在庫あり（○時点）」の表示: price_evidence.CURRENT_DAYS（7日）
- 今すぐ行動できる・在庫再開・商品詳細の「購入可能」: 3時間（ここ）。7日前の在庫ありを「今すぐ買える」に使わない
抽選・予約・先着は締切まで有効（tcg.freshness.NO_TTL_EVENTS と同じ）。ただし公式のページを確認した時刻が
CURRENT_DAYS（7日）以内で、未来でないときだけ受付中と言う（新しい期限は作らない）。

判定はここだけで行い、画面（Python の生成・JavaScript）では判定し直さない（画面は結果の値と期限だけを使う）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlparse

IN_STOCK, OUT_OF_STOCK, UNKNOWN, STOCK_STALE, SALE_ENDED = "IN_STOCK", "OUT_OF_STOCK", "UNKNOWN", "STOCK_STALE", "SALE_ENDED"
LOTTERY_OPEN, LOTTERY_UPCOMING, LOTTERY_CLOSED, LOTTERY_UNKNOWN = (
    "LOTTERY_OPEN", "LOTTERY_UPCOMING", "LOTTERY_CLOSED", "LOTTERY_UNKNOWN")
PURCHASE_PERIOD_OPEN, PURCHASE_PERIOD_CLOSED = "PURCHASE_PERIOD_OPEN", "PURCHASE_PERIOD_CLOSED"
PREORDER_OPEN, PREORDER_CLOSED = "PREORDER_OPEN", "PREORDER_CLOSED"
FIRST_COME_OPEN, FIRST_COME_CLOSED = "FIRST_COME_OPEN", "FIRST_COME_CLOSED"
UPCOMING = "UPCOMING"           # 予約・先着の受付前

AVAILABILITY_TYPES = (IN_STOCK, OUT_OF_STOCK, UNKNOWN, STOCK_STALE, SALE_ENDED, LOTTERY_OPEN, LOTTERY_UPCOMING,
                      LOTTERY_CLOSED, LOTTERY_UNKNOWN, PURCHASE_PERIOD_OPEN, PURCHASE_PERIOD_CLOSED,
                      PREORDER_OPEN, PREORDER_CLOSED, FIRST_COME_OPEN, FIRST_COME_CLOSED, UPCOMING)
# 今すぐ行動できる種類（通常販売は在庫あり、抽選・予約・先着は受付中だけ）
ACTIONABLE_TYPES = frozenset({IN_STOCK, LOTTERY_OPEN, PREORDER_OPEN, FIRST_COME_OPEN})

LABELS = {IN_STOCK: "購入可能", OUT_OF_STOCK: "在庫切れ", UNKNOWN: "在庫未確認", STOCK_STALE: "更新待ち",
          SALE_ENDED: "販売終了", LOTTERY_OPEN: "抽選受付中", LOTTERY_UPCOMING: "抽選受付前", LOTTERY_CLOSED: "抽選終了",
          LOTTERY_UNKNOWN: "抽選（日程未確認）", PURCHASE_PERIOD_OPEN: "当選者の購入期間",
          PURCHASE_PERIOD_CLOSED: "購入期間終了", PREORDER_OPEN: "予約受付中", PREORDER_CLOSED: "予約終了",
          FIRST_COME_OPEN: "先着販売中", FIRST_COME_CLOSED: "先着販売終了", UPCOMING: "受付前"}
CTA_LABELS = {IN_STOCK: "購入する", LOTTERY_OPEN: "抽選に申し込む", PREORDER_OPEN: "予約する", FIRST_COME_OPEN: "購入する"}
# 期限を過ぎたときに画面が出す表示（判定はしない。生成時に決めた期限を過ぎたら、この文言に落とすだけ）
EXPIRED_LABELS = {IN_STOCK: "更新待ち", LOTTERY_OPEN: "抽選終了", PREORDER_OPEN: "予約終了",
                  FIRST_COME_OPEN: "先着販売終了"}

# 行動できない理由（正本の名前）
REASONS = {
    "not_profitable": "確定の利益の条件を満たさない",
    "identity_unverified": "売却価格の商品の照合が未完了",
    "stock_out": "在庫切れ", "stock_unknown": "在庫未確認", "availability_stale": "在庫の確認から時間が経った（更新待ち）",
    "sale_ended": "公式の販売終了", "lottery_closed": "抽選の受付終了", "lottery_not_open": "抽選の受付前",
    "lottery_deadline_unknown": "抽選の日程が分からない", "lottery_evidence_stale": "抽選の情報の確認が古い",
    "winner_only_period": "当選者だけの購入期間", "preorder_closed": "予約の受付終了",
    "first_come_closed": "先着販売の終了", "missing_action_url": "購入・申込のページが分からない",
    "lottery_status_conflict": "抽選の情報が食い違う（ページに受付終了など）",
}

# 購入・申込のページと認める形（公式のドメインごと。ここに合うページだけ。一覧・トップ・紹介・販促のページは使わない。
# レビュー H1・監査 M-3）。パスは大文字・小文字を区別する。クエリが必要なものは必要な項目を指定する
_ACTION_PAGES = {
    "pur.store.sony.jp": (r"^/ps5/products/[^/]+/[^/]+_purchase/?$", None),
    "www.apple.com": (r"^/jp/shop/buy-[a-z0-9-]+/[a-z0-9-]+/?$", None),
    "store.canon.jp": (r"^/online/g/g[0-9A-Za-z]+/?$", None),
    "nij.nikon.com": (r"^/shop/g/g\d+/?$", None),
    "mall-jp.fujifilm.com": (r"^/shop/g/g\d+/?$", None),
    "ricohimagingstore.com": (r"^/Form/Product/ProductDetail\.aspx$", "pid"),
    "store-jp.nintendo.com": (r"^/item/[^/]+/[^/]+/?$", None),
}
_GENERIC_PATHS = ("", "/")      # 互換のため残す（判定は _ACTION_PAGES）
_IN_STOCK_SECONDS_KEY = "official_store"
_FUTURE_TOLERANCE_SECONDS = 300          # 確認時刻が未来なのは時計のずれの5分まで（それ以上は信用しない）


@dataclass
class Actionability:
    availability: str
    actionable: bool
    reasons: tuple[str, ...] = ()
    cta_label: str = ""
    cta_url: str = ""
    deadline: str = ""            # 受付の締切（ISO。分かるときだけ）
    checked_at: str = ""          # 購入の可否を確認した時刻（ISO）
    until_ms: int | None = None   # 「今すぐ行動できる」と言える期限（ミリ秒。画面はこれを過ぎたら表示を落とす）
    event: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return LABELS.get(self.availability, LABELS[UNKNOWN])

    @property
    def expired_label(self) -> str:
        return EXPIRED_LABELS.get(self.availability, "")


def _dt(v):
    from src.tcg.models import JST, parse_dt
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=JST))
    s = str(v or "").strip()
    return parse_dt(s.replace(" JST", "")) if s else None


def _official_url(url: str) -> bool:
    """公式の購入・申込のページか（https・_ACTION_PAGES のドメインとパスの形に合う）。"""
    import re
    from urllib.parse import parse_qs
    try:
        u = urlparse(str(url or ""))
    except ValueError:
        return False
    if u.scheme != "https" or not u.netloc:
        return False
    rule = _ACTION_PAGES.get(u.netloc.lower())
    if not rule or not re.match(rule[0], u.path):
        return False
    return not rule[1] or bool((parse_qs(u.query).get(rule[1]) or [""])[0].strip())


def find_event(events, product_id: str, model: str = "") -> dict | None:
    """利益案件の商品の、抽選・予約・先着の情報（商品 ID か、型番 = 商品コードの完全一致だけ。商品名では結び付けない）。

    同じ商品に複数あるときは、確認の新しいものを選ぶ（同じ時刻なら受付中のもの）。
    """
    pid, code = str(product_id or "").strip(), str(model or "").strip()
    cands = []
    for ev in events or []:
        if not isinstance(ev, dict) or ev.get("reference_only"):
            continue
        if (pid and str(ev.get("product_id") or "").strip() == pid) or \
                (code and str(ev.get("product_code") or "").strip() == code):
            cands.append(ev)
    if not cands:
        return None
    def _ts(e):
        d = _dt(e.get("checked_at") or e.get("verified_at"))
        return d.timestamp() if d else 0.0                      # 書式の違う時刻を文字列で比べない（監査 L-4）
    # 確認の新しい行を優先する（新しい行が受付終了なら、それを使う。古い受付中の行を選ばない。レビュー L-a）
    return max(cands, key=lambda e: (_ts(e), str(e.get("status") or "").lower() in ("active", "open")))


def _event_kind(ev: dict) -> str:
    s = f'{ev.get("sale_method") or ""} {ev.get("event_type") or ""}'.lower()
    if "抽選" in s or "lottery" in s:
        return "lottery"
    if "予約" in s or "preorder" in s or "reservation" in s:
        return "preorder"
    if "先着" in s or "first_come" in s:
        return "first_come"
    return ""                                                   # 種類が分からない（抽選と推測しない。監査 L-3）


_DATE_ONLY = __import__("re").compile(r"^\d{4}-\d{1,2}-\d{1,2}$")


def is_date_only(value) -> bool:
    """時刻の無い日付（YYYY-MM-DD。月・日が1桁も含む）か。画面で日付だけを出すかの判定に使う。"""
    return bool(_DATE_ONLY.match(str(value or "").strip()))


def _when(value: str, key: str) -> dict:
    """時刻の無い日付は *_date の項目で渡す（その日の中の時刻を推測しない。compute_lottery_status の安全側。監査 M-1）。"""
    v = str(value or "").strip()
    if not v:
        return {}
    return {f"{key}_date": v} if _DATE_ONLY.match(v) else {key: v}


def event_availability(ev: dict, now: datetime) -> tuple[str, str, str, str, tuple[str, ...]]:
    """抽選・予約・先着の情報 → (種類, 締切, 確認時刻, 申込の URL, 理由)。日程・確認が分からなければ受付中と言わない。

    受付中と言えるのは、種類が分かり（抽選・予約・先着）、開始と締切の両方が分かり（片方だけなら日程不明。監査 H-2）、
    収集側が「状態の矛盾」（ページに受付終了とあるのに日付では受付中など）を付けておらず（監査 H-1）、公式のページを
    確認した時刻が7日以内で未来でないときだけ。申込のページは申込の URL（entry_form_url）だけ（商品・一覧のページに
    切り替えない。監査 M-3）。
    """
    from src.market import price_evidence as pe
    from src.tcg.lottery import schema as ls
    kind = _event_kind(ev)
    start = str(ev.get("application_start") or ev.get("entry_start_at") or "").strip()
    end = str(ev.get("application_end") or ev.get("entry_end_at") or "").strip()
    checked = _dt(ev.get("checked_at") or ev.get("verified_at"))
    url = str(ev.get("entry_form_url") or "").strip()
    end_dt = _dt(end)
    # 時刻の無い締切は日付のまま（時刻を作らない。画面は日付だけ出す。レビュー L5）
    deadline = (end if _DATE_ONLY.match(end) else end_dt.isoformat()) if end_dt else ""
    st = ls.compute_lottery_status({**_when(start, "application_start"), **_when(end, "application_end"),
                                    **_when(str(ev.get("purchase_start") or ""), "purchase_start"),
                                    **_when(str(ev.get("purchase_end") or ""), "purchase_end")}, now)
    closed_by_page = str(ev.get("status") or "").strip().lower() in ("closed", "ended", "end", "finished", "受付終了",
                                                                  "終了", "締切", "締め切り", "販売終了")
    checked_iso = checked.isoformat() if checked else ""
    if not kind:
        return LOTTERY_UNKNOWN, deadline, checked_iso, url, ("lottery_deadline_unknown",)
    opened = {"lottery": LOTTERY_OPEN, "preorder": PREORDER_OPEN, "first_come": FIRST_COME_OPEN}[kind]
    closed = {"lottery": LOTTERY_CLOSED, "preorder": PREORDER_CLOSED, "first_come": FIRST_COME_CLOSED}[kind]
    closed_reason = {"lottery": "lottery_closed", "preorder": "preorder_closed", "first_come": "first_come_closed"}[kind]
    if st == ls.L_WINNER_PURCHASE_PERIOD:
        return PURCHASE_PERIOD_OPEN, deadline, checked_iso, url, ("winner_only_period",)
    if closed_by_page or st in (ls.L_CLOSED, ls.L_RESULT_PENDING, ls.L_WINNER_ANNOUNCED, ls.L_ENDED):
        return closed, deadline, checked_iso, url, (closed_reason,)
    if st == ls.L_UPCOMING:
        return LOTTERY_UPCOMING if kind == "lottery" else UPCOMING, deadline, checked_iso, url, ("lottery_not_open",)
    if str(ev.get("status_conflict") or "").strip().lower() in ("true", "1", "yes"):
        return LOTTERY_UNKNOWN, deadline, checked_iso, url, ("lottery_status_conflict",)
    # 開始が読めない（空・書式の違う値）ときも日程不明（監査 L-a）。時刻の無い締切の当日は、締切を過ぎたかもしれない
    # ので受付中と言わない（監査 M-a）
    end_day_today = _DATE_ONLY.match(end) is not None and end_dt is not None and now >= end_dt
    if st not in (ls.L_OPEN, ls.L_ENDING_SOON) or not end_dt or _dt(start) is None or end_day_today:
        return LOTTERY_UNKNOWN, deadline, checked_iso, url, ("lottery_deadline_unknown",)
    # 受付中と言えるのは、公式のページを確認した時刻が7日以内で、未来でないときだけ（未来は5分まで。監査 L-1）
    if checked is None:
        return LOTTERY_UNKNOWN, deadline, "", url, ("lottery_evidence_stale",)
    age = (now - checked).total_seconds()
    if age > pe.CURRENT_DAYS * 86400 or age < -_FUTURE_TOLERANCE_SECONDS:
        return LOTTERY_UNKNOWN, deadline, checked_iso, url, ("lottery_evidence_stale",)
    return opened, deadline, checked_iso, url, ()


def evaluate(*, profitable: bool, identity_ok: bool, stock: str, stock_checked_at, sale_method: str = "",
             buy_url: str = "", event: dict | None = None, now: datetime,
             buy_url_is_item: bool | None = None) -> Actionability:
    """1件の利益案件の「今すぐ行動できるか」。理由は行動できない理由を全部返す。

    buy_url_is_item: 購入ページが公式で確認済みの商品の購入ページ（product_source_config の verified・link_type item）か。
    False なら購入のボタンを出さない（None は呼び出し側が分からない。ドメインと一般のページの除外だけで見る）。
    抽選の情報は、販売の方法・在庫の表示が抽選・予約のときだけ使う（通常販売の在庫ありより優先しない。監査 L-3）。
    """
    from src.market import price_evidence as pe
    from src.market.stock_state import STOCK_FRESH_SECONDS
    reasons: list[str] = []
    if not profitable:
        reasons.append("not_profitable")
    if not identity_ok:
        reasons.append("identity_unverified")
    deadline, checked_iso, url, until = "", "", "", None
    sm = str(sale_method or "").lower()
    if sm in ("discontinued", "ended", "sale_ended") or stock == SALE_ENDED:
        avail = SALE_ENDED
        reasons.append("sale_ended")
    elif stock in ("LOTTERY", "RESERVATION", "PREORDER") or any(w in sm for w in ("lottery", "抽選", "予約", "preorder",
                                                                                      "reservation")):
        if event:
            avail, deadline, checked_iso, url, why = event_availability(event, now)
            reasons.extend(why)
            if avail in ACTIONABLE_TYPES and deadline:
                # 締切か、確認から7日の早いほうまで（CI が止まっても古い根拠で申込のボタンを残さない。監査 L-2）
                lim = [_dt(deadline)]
                if checked_iso:
                    lim.append(_dt(checked_iso) + timedelta(days=pe.CURRENT_DAYS))
                until = int(min(lim).timestamp() * 1000)
        else:
            avail = LOTTERY_UNKNOWN
            reasons.append("lottery_deadline_unknown")
    else:
        checked = _dt(stock_checked_at)
        checked_iso = checked.isoformat() if checked else ""
        url = str(buy_url or "")
        age = (now - checked).total_seconds() if checked else None
        if stock in (IN_STOCK, OUT_OF_STOCK) and (age is None or age > pe.CURRENT_DAYS * 86400
                                                  or age < -_FUTURE_TOLERANCE_SECONDS):
            # 7日を過ぎた（または確認時刻が無い・未来の）在庫の表示は在庫未確認（Phase 15 の規則。レビュー M1）
            stock = UNKNOWN
        if stock == IN_STOCK:
            ttl = STOCK_FRESH_SECONDS[_IN_STOCK_SECONDS_KEY]
            if age is not None and -_FUTURE_TOLERANCE_SECONDS <= age <= ttl:
                avail = IN_STOCK
                until = int((min(checked, now) + timedelta(seconds=ttl)).timestamp() * 1000)
            else:
                avail = STOCK_STALE
                reasons.append("availability_stale")
        elif stock == OUT_OF_STOCK:
            avail = OUT_OF_STOCK
            reasons.append("stock_out")
        else:
            avail = UNKNOWN
            reasons.append("stock_unknown")
        if buy_url_is_item is False and avail in ACTIONABLE_TYPES:
            reasons.append("missing_action_url")
    if avail in ACTIONABLE_TYPES and not _official_url(url):
        reasons.append("missing_action_url")
    # 期限（画面がボタンを消す時刻）がすでに過ぎている判定は行動できない（生成の判定と画面を食い違わせない。監査 M-a）
    if not reasons and avail in ACTIONABLE_TYPES and until is not None and until <= int(now.timestamp() * 1000):
        reasons.append("lottery_deadline_unknown" if avail != IN_STOCK else "availability_stale")
    ok = not reasons and avail in ACTIONABLE_TYPES
    return Actionability(availability=avail, actionable=ok, reasons=tuple(dict.fromkeys(reasons)),
                         cta_label=CTA_LABELS.get(avail, "") if ok else "", cta_url=url if ok else "",
                         deadline=deadline, checked_at=checked_iso, until_ms=until if ok else None,
                         event=dict(event or {}))
