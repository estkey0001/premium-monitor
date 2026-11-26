# -*- coding: utf-8 -*-
"""TCG の二次流通の価格の種類と、人が確認した成約の台帳・想定利益（監査 H-1 の対応）。

価格の種類（商品ごとの相場の要約に別々に持つ。1つの「市場価格」にまとめない）:

| 種類 | 意味 |
|---|---|
| RETAIL_PRICE | 定価（公式） |
| BUYBACK_PRICE | 買取店の買取価格（src/tcg/buyback.py の領域。ここでは受け取って並べるだけ） |
| LISTING_LOW / LISTING_HIGH | 出品中の最安・最高（売れた価格ではない） |
| BID_PRICE | 買い手の入札・買い注文の価格（売れた価格ではない） |
| LAST_SALE | 直近の成約1件（相場ではない。常に「参考」） |
| SOLD_MEDIAN | 確認済みの成約の中央値（最低件数・鮮度・単位・状態がそろったときだけ） |
| SOLD_COUNT | SOLD_MEDIAN に使った（使おうとした）成約の件数 |

発売前の取引は ACTUAL_SALE（実物の成約）と区別する:
PREORDER_TRADE（予約取引。実物の受け渡し前）・EARLY_SALE（先行販売・イベント先行の成約）は相場（SOLD_MEDIAN）に入れない。

利益の3種（混ぜない）:
  A 買取利益 … src/tcg/buyback.py（このモジュールは触らない）
  B 二次流通の想定利益 … 確認済み成約の中央値 − 仕入れ − 販売手数料 − 送料 − 振込手数料 − その他。常に executable=False・「想定」
  C 出品参考相場 … 出品しか無い。利益は出さない（参考価格だけ）

決まり:
- 出品（LISTING 系）・入札（BID）・買取は成約の台帳に入れない（行ごと受け付けない）
- 成約日（sold_at）の無い成約は使わない。鮮度は sold_at だけで判定し、確認日（verified_at）で延ばさない
- 直近の成約1件だけを相場にしない（最低件数は設定 min_samples。満たさないと「参考（N件）」）
- 費用の根拠が無いもの（料率・送料・振込手数料）は 0 円にせず NOT_CALCULATED
- 推測で値を作らない（外貨は換算しない・単位が分からない商品の成約は使わない）
- このモジュールはネットワークに触れない
"""
from __future__ import annotations

import csv
import os
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlsplit

from src.market import price_types as pt

from .models import (SHRINK_OPENED_BOX, SHRINK_PACK_ONLY, SHRINK_REMOVED, SHRINK_SEALED,
                     SHRINK_TAPE_CUT)

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "secondary_markets.yaml"
FEES_CONFIG_PATH = PROJECT_ROOT / "config" / "camera_routes.yaml"   # 市場ごとの販売手数料の正本
LEDGER_ENV = "TCG_SOLD_LEDGER_PATH"

# ── 価格の種類（要約のキー） ──────────────────────────────────────────────
RETAIL_PRICE = "RETAIL_PRICE"
BUYBACK_PRICE = "BUYBACK_PRICE"
LISTING_LOW = "LISTING_LOW"
LISTING_HIGH = "LISTING_HIGH"
BID_PRICE = "BID_PRICE"
LAST_SALE = "LAST_SALE"
SOLD_MEDIAN = "SOLD_MEDIAN"
SOLD_COUNT = "SOLD_COUNT"
PRICE_KINDS = (RETAIL_PRICE, BUYBACK_PRICE, LISTING_LOW, LISTING_HIGH, BID_PRICE,
               LAST_SALE, SOLD_MEDIAN, SOLD_COUNT)

# ── 成約の段階 ───────────────────────────────────────────────────────────
ACTUAL_SALE = "ACTUAL_SALE"          # 実物の成約（相場に使える唯一の段階）
PREORDER_TRADE = "PREORDER_TRADE"    # 予約取引（実物の受け渡し前）
EARLY_SALE = "EARLY_SALE"            # 先行販売・イベント先行の成約
SALE_PHASES = (ACTUAL_SALE, PREORDER_TRADE, EARLY_SALE)

# 台帳の price_kind → 成約の段階。SOLD は ACTUAL_SALE と同じ
SALE_KIND_TO_PHASE = {"SOLD": ACTUAL_SALE, "LAST_SALE": ACTUAL_SALE, ACTUAL_SALE: ACTUAL_SALE,
                      PREORDER_TRADE: PREORDER_TRADE, EARLY_SALE: EARLY_SALE}
# 成約ではない種類（台帳に書かれていても受け付けない）
NOT_SALE_KINDS = frozenset({
    "LISTING", LISTING_LOW, LISTING_HIGH, "ASK", "ASK_PRICE", "BID", BID_PRICE,
    "BUYBACK", BUYBACK_PRICE, "RETAIL", RETAIL_PRICE, SOLD_MEDIAN, SOLD_COUNT,
    "flea_listing_price", "overseas_listing_price",
})

# 観測1件の種類（secondary の観測 dict の price_kind）
OBS_SOLD = "SOLD"          # 台帳で検証を通った成約（段階は sale_phase）
OBS_LISTING = "LISTING"    # 出品（eBay Browse など）
OBS_BID = "BID"
OBS_UNKNOWN = "UNKNOWN"    # 種類の記録が無い（旧形式の行など）。相場にも利益にも使わない

# 状態（シュリンクの状態の名前をそのまま使う）。UNKNOWN・空は受け付けない
CONDITIONS = (SHRINK_SEALED, SHRINK_REMOVED, SHRINK_TAPE_CUT, SHRINK_OPENED_BOX, SHRINK_PACK_ONLY)
# 単位（buyback.UNITS と同じ名前）
UNITS = ("PACK", "BOX", "CASE", "SET", "PREMIUM_BOX", "DECK", "OTHER")

LEDGER_COLUMNS = ("product_id", "market", "price_kind", "price", "currency", "sold_at",
                  "condition", "unit", "source_url", "verified_at", "note")

# 利益の状態・種類
PROFITABLE, NO_PROFIT, NOT_CALCULATED = "PROFITABLE", "NO_PROFIT", "NOT_CALCULATED"
PROFIT_A_BUYBACK = "A_BUYBACK"
PROFIT_B_SECONDARY_EXPECTED = "B_SECONDARY_EXPECTED"
PROFIT_C_LISTING_REFERENCE = "C_LISTING_REFERENCE"

# 成約中央値の状態
SOLD_OK = "OK"                          # 相場として出せる
SOLD_INSUFFICIENT = "INSUFFICIENT"      # 件数不足 →「参考（N件）」
SOLD_NONE = "NO_SALES"

_DEFAULTS = {"path": ".private/tcg_sold_ledger.csv", "min_samples": pt.MIN_SOLD_SAMPLES,
             "fresh_days": 14, "publish_market_names": False, "product_units": {},
             "costs": {"outbound_shipping_jpy": None, "payout_fee_jpy": {}, "other_jpy": 0}}


# ───────────────────────── 設定 ─────────────────────────

def load_config(path: Path = CONFIG_PATH) -> dict:
    """台帳の設定（config/secondary_markets.yaml の tcg_sold_ledger）。読めなければ既定値。"""
    cfg = {**_DEFAULTS, "costs": dict(_DEFAULTS["costs"]), "product_units": {}}
    try:
        import yaml
        data = (yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("tcg_sold_ledger") or {}
    except Exception:  # noqa: BLE001 - 設定が読めないときは既定値（成約なしと同じく安全側）
        data = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "costs" and isinstance(v, dict):
                cfg["costs"].update(v)
            elif v is not None or k in ("path",):
                cfg[k] = v
    return cfg


def ledger_path(cfg: Optional[dict] = None, env=None) -> Path:
    """台帳の場所。環境変数 TCG_SOLD_LEDGER_PATH > 設定 path。相対パスはリポジトリ基準。"""
    env = os.environ if env is None else env
    raw = str((env or {}).get(LEDGER_ENV) or "").strip() or str((cfg or load_config()).get("path") or "")
    p = Path(raw).expanduser()
    return p if p.is_absolute() else PROJECT_ROOT / p


def load_fee_table(path: Path = FEES_CONFIG_PATH) -> dict:
    """市場 → 販売手数料（config/camera_routes.yaml の fees）。読めなければ空（＝すべて NOT_CALCULATED）。"""
    try:
        import yaml
        return dict((yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}).get("fees") or {})
    except Exception:  # noqa: BLE001
        return {}


def product_units(cfg: Optional[dict] = None) -> dict:
    """商品 → 単位。設定の product_units > config/tcg_buyback.yaml の targets の unit。"""
    cfg = cfg or load_config()
    out: dict = {}
    try:
        from . import buyback
        for t in buyback.load_config().get("targets") or []:
            if t.get("product_id") and t.get("unit"):
                out[str(t["product_id"])] = str(t["unit"]).upper()
    except Exception:  # noqa: BLE001 - 読めなければ設定の分だけ
        pass
    for k, v in (cfg.get("product_units") or {}).items():
        if v:
            out[str(k)] = str(v).upper()
    return out


# ───────────────────────── 台帳（人が確認した成約） ─────────────────────────

@dataclass(frozen=True)
class SaleRecord:
    """検証を通った成約1件。"""
    product_id: str
    market: str
    sale_phase: str          # ACTUAL_SALE / PREORDER_TRADE / EARLY_SALE
    price: int               # 円
    sold_at: datetime        # 成約日時（JST）
    condition: str
    unit: str
    source_url: str
    verified_at: datetime    # 人が確認した日時（鮮度の判定には使わない）
    note: str = ""
    line: int = 0


@dataclass
class LedgerResult:
    records: list = field(default_factory=list)          # list[SaleRecord]
    rejected: list = field(default_factory=list)         # [{"line": n, "product_id": .., "reasons": [...]}]
    duplicates: int = 0
    conflicts: list = field(default_factory=list)        # 同じ商品ページで価格が違う → 両方捨てた
    path: str = ""
    exists: bool = False

    def reason_counts(self) -> dict:
        out: dict = {}
        for r in self.rejected:
            for w in r["reasons"]:
                out[w] = out.get(w, 0) + 1
        return out


def _parse_dt(value) -> Optional[datetime]:
    return pt._parse_dt(value)


def _price(value) -> Optional[int]:
    s = str(value or "").replace(",", "").replace("円", "").replace("¥", "").strip()
    if not re.fullmatch(r"\d+(\.0+)?", s):
        return None
    n = int(float(s))
    return n if n > 0 else None


_LIST_PATH = re.compile(r"(^|/)(search|s|list|lists|category|categories|catalog|ranking|tag|tags|history)(/|$)", re.I)
_LIST_QUERY = re.compile(r"(^|&)(q|query|keyword|keywords|search|word|k|_nkw)=", re.I)


def url_reasons(url: str) -> tuple[str, ...]:
    """成約の根拠の URL として使えない理由（空なら使える）。

    商品ページの形が分かっている市場（price_types の許可リスト）は、その形に合うものだけ。
    それ以外は https・ダミーでない・検索結果・一覧・トップでないこと。
    """
    u = str(url or "").strip()
    if not u:
        return ("no_source_url",)
    if pt.is_dummy_url(u):
        return ("dummy_url",)
    if pt.is_item_url(u):
        return ()
    sp = urlsplit(u)
    if sp.scheme != "https" or not sp.netloc:
        return ("source_url_not_https",)
    host = sp.netloc.lower()
    known = ("mercari.com", "auctions.yahoo.co.jp", "fril.jp", "paypayfleamarket.yahoo.co.jp", "ebay.")
    if any(k in host for k in known):
        return ("not_item_url",)                    # 形が分かっている市場で形に合わない（検索結果など）
    path = sp.path.rstrip("/")
    if not path or _LIST_PATH.search(path) or _LIST_QUERY.search(sp.query or ""):
        return ("not_item_url",)
    return ()


def validate_row(row: dict, *, units: dict, now: datetime) -> tuple[Optional[SaleRecord], list[str]]:
    """台帳の1行を検証する。(成約, 使えない理由)。理由があれば成約は None。"""
    reasons: list[str] = []
    pid = str(row.get("product_id") or "").strip()
    market = str(row.get("market") or "").strip().lower()
    kind = str(row.get("price_kind") or "").strip()
    kind_u = kind.upper()
    if not pid:
        reasons.append("no_product_id")
    if not re.fullmatch(r"[a-z0-9_]+", market or ""):
        reasons.append("invalid_market")
    elif "buyback" in market:
        reasons.append("buyback_is_not_a_sale")      # 買取は buyback.py の領域。成約の台帳に入れない
    if kind in NOT_SALE_KINDS or kind_u in NOT_SALE_KINDS:
        reasons.append("not_a_sale_kind")            # 出品・入札・買取・集計値を成約として受け付けない
        phase = None
    else:
        phase = SALE_KIND_TO_PHASE.get(kind_u)
        if phase is None:
            reasons.append("unknown_price_kind")
    price = _price(row.get("price"))
    if price is None:
        reasons.append("invalid_price")
    cur = str(row.get("currency") or "").strip().upper()
    if cur != "JPY":
        reasons.append("currency_not_jpy")           # 為替は換算しない（推測しない）
    sold_at = _parse_dt(row.get("sold_at"))
    if sold_at is None:
        reasons.append("no_sold_at")
    elif sold_at > now + timedelta(days=1):
        reasons.append("sold_at_in_future")
    verified_at = _parse_dt(row.get("verified_at"))
    if verified_at is None:
        reasons.append("no_verified_at")             # 人が確認していない行は使わない
    elif verified_at > now + timedelta(days=1):
        reasons.append("verified_at_in_future")
    elif sold_at is not None and verified_at.date() < sold_at.date():
        reasons.append("verified_before_sold")       # 成約より前に「確認」はできない
    cond = str(row.get("condition") or "").strip().upper()
    if cond not in CONDITIONS:
        reasons.append("unknown_condition")
    unit = str(row.get("unit") or "").strip().upper()
    expected = units.get(pid)
    if unit not in UNITS:
        reasons.append("unknown_unit")
    elif not expected:
        reasons.append("product_unit_unknown")       # 商品の単位を確かめられないものは使わない
    elif unit != expected:
        reasons.append("unit_mismatch")              # BOX の商品に PACK の成約を混ぜない
    if cond == SHRINK_PACK_ONLY and unit == "BOX":
        reasons.append("unit_mismatch")
    reasons.extend(url_reasons(row.get("source_url")))
    if reasons:
        return None, sorted(set(reasons))
    return SaleRecord(product_id=pid, market=market, sale_phase=phase, price=price, sold_at=sold_at,
                      condition=cond, unit=unit, source_url=str(row.get("source_url")).strip(),
                      verified_at=verified_at, note=str(row.get("note") or "").strip()), []


def _url_key(url: str) -> str:
    return str(url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/").lower()


def load_ledger(path: Optional[Path] = None, *, cfg: Optional[dict] = None, units: Optional[dict] = None,
                now: Optional[datetime] = None, env=None) -> LedgerResult:
    """台帳を読んで検証する。ファイルが無ければ空（成約なし）。

    重複: 同じ市場・同じ商品ページは1件。価格・成約日時も同じなら重複として捨てる（確認日だけ新しい行で増やさない）。
    同じ商品ページで価格か成約日時が違う行は、どちらが正しいか分からないので両方捨てる（conflicts）。
    """
    cfg = cfg or load_config()
    now = now or datetime.now(tz=JST)
    path = Path(path) if path is not None else ledger_path(cfg, env)
    res = LedgerResult(path=str(path.name), exists=path.exists())
    if not res.exists:
        return res
    units = product_units(cfg) if units is None else {k: str(v).upper() for k, v in units.items()}
    by_key: dict = {}
    order: list = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in ("product_id", "price_kind", "price", "sold_at", "source_url") if c not in (reader.fieldnames or [])]
        for i, row in enumerate(reader, start=2):
            if not any(str(v or "").strip() for v in row.values()):
                continue
            if missing:
                # 旧形式（price_kind・sold_at が無い）の行は種類が分からないので使わない
                res.rejected.append({"line": i, "product_id": (row.get("product_id") or "").strip(),
                                     "reasons": ["legacy_format_no_price_kind"]})
                continue
            rec, why = validate_row(row, units=units, now=now)
            if why:
                res.rejected.append({"line": i, "product_id": (row.get("product_id") or "").strip(), "reasons": why})
                continue
            rec = SaleRecord(**{**rec.__dict__, "line": i})
            k = (rec.market, _url_key(rec.source_url))
            if k not in by_key:
                by_key[k] = [rec]
                order.append(k)
            else:
                by_key[k].append(rec)
    for k in order:
        recs = by_key[k]
        first = recs[0]
        same = [r for r in recs[1:] if (r.price, r.sold_at, r.product_id) == (first.price, first.sold_at, first.product_id)]
        if len(same) == len(recs) - 1:
            res.records.append(first)
            res.duplicates += len(same)
        else:
            res.conflicts.append({"market": k[0], "lines": [r.line for r in recs]})
    return res


# ───────────────────────── 相場の要約 ─────────────────────────

def _outlier_split(prices: list[int]) -> tuple[list[int], list[int]]:
    """中央値から大きく外れた値を分ける（premium.filter_outliers と同じ基準）。"""
    from .premium import OUTLIER_HIGH_RATIO, OUTLIER_LOW_RATIO
    if len(prices) < 3:
        return sorted(prices), []
    med = statistics.median(prices)
    keep = [p for p in prices if med * OUTLIER_LOW_RATIO <= p <= med * OUTLIER_HIGH_RATIO]
    drop = [p for p in prices if p not in keep]
    return sorted(keep), sorted(drop)


def sold_summary(records: Iterable[SaleRecord], product_id: str, *, condition: str = SHRINK_SEALED,
                 now: Optional[datetime] = None, cfg: Optional[dict] = None) -> dict:
    """商品・状態ごとの成約の要約（SOLD_MEDIAN・SOLD_COUNT・LAST_SALE）。

    使うのは ACTUAL_SALE で、成約日（sold_at）が fresh_days 以内のものだけ。確認日（verified_at）では延ばさない。
    件数が min_samples 未満なら SOLD_MEDIAN は None で、表示は「参考（N件）」。
    """
    cfg = cfg or load_config()
    now = now or datetime.now(tz=JST)
    min_n = int(cfg.get("min_samples") or pt.MIN_SOLD_SAMPLES)
    fresh_days = int(cfg.get("fresh_days") or 14)
    cutoff = now - timedelta(days=fresh_days)
    mine = [r for r in records if r.product_id == product_id and r.condition == condition]
    actual = [r for r in mine if r.sale_phase == ACTUAL_SALE]
    fresh = [r for r in actual if r.sold_at >= cutoff and r.sold_at <= now + timedelta(days=1)]
    stale = [r for r in actual if r not in fresh]
    kept, outliers = _outlier_split([r.price for r in fresh])
    last = max(fresh, key=lambda r: r.sold_at) if fresh else None
    n = len(kept)
    status = SOLD_OK if n >= min_n else (SOLD_INSUFFICIENT if fresh else SOLD_NONE)
    out = {
        "product_id": product_id, "condition": condition, "price_basis": "VERIFIED_SOLD",
        SOLD_MEDIAN: int(statistics.median(kept)) if status == SOLD_OK else None,
        SOLD_COUNT: n,
        LAST_SALE: last.price if last else None,
        "last_sold_at": last.sold_at.isoformat() if last else None,
        "sold_status": status,
        "min_samples": min_n, "fresh_days": fresh_days,
        "period_start": cutoff.isoformat(), "period_end": now.isoformat(),
        "outliers_excluded": len(outliers), "stale_excluded": len(stale),
        # 発売前の取引は相場に入れず、件数だけ別に持つ
        "preorder_trade_count": sum(1 for r in mine if r.sale_phase == PREORDER_TRADE),
        "early_sale_count": sum(1 for r in mine if r.sale_phase == EARLY_SALE),
        "markets": sorted({r.market for r in fresh}),
        "executable": False,
    }
    if status == SOLD_OK:
        out["label"] = f"成約の中央値（{n}件・直近{fresh_days}日）"
    elif status == SOLD_INSUFFICIENT:
        out["label"] = f"参考（{n}件）"           # 1〜2件の成約を相場として扱わない
    else:
        out["label"] = "確認済みの成約なし"
    if not cfg.get("publish_market_names"):
        out["market_count"] = len(out.pop("markets"))
    return out


def listing_reference(listings: Iterable[dict], product_id: str, *, condition: str = SHRINK_SEALED) -> dict:
    """C 出品参考相場。出品（LISTING）だけから最安・最高を出す。利益は出さない。"""
    prices = [int(o["price"]) for o in listings
              if o.get("product_id") == product_id and o.get("price_kind") == OBS_LISTING
              and o.get("shrink_status", condition) == condition and o.get("price")]
    return {
        "product_id": product_id, "condition": condition, "profit_kind": PROFIT_C_LISTING_REFERENCE,
        LISTING_LOW: min(prices) if prices else None,
        LISTING_HIGH: max(prices) if prices else None,
        "listing_count": len(prices),
        "label": "出品参考（売れた価格ではありません）",
        "profit_yen": None, "profit_status": NOT_CALCULATED, "executable": False,
    }


def market_snapshot(product_id: str, *, records: Iterable[SaleRecord] = (), listings: Iterable[dict] = (),
                    retail_price: Optional[int] = None, buyback_price: Optional[int] = None,
                    bid_price: Optional[int] = None, condition: str = SHRINK_SEALED,
                    now: Optional[datetime] = None, cfg: Optional[dict] = None) -> dict:
    """価格の種類を別々に並べた要約。どれか1つを「市場価格」として選ばない。"""
    s = sold_summary(list(records), product_id, condition=condition, now=now, cfg=cfg)
    c = listing_reference(list(listings), product_id, condition=condition)
    return {
        "product_id": product_id, "condition": condition,
        RETAIL_PRICE: retail_price, BUYBACK_PRICE: buyback_price,
        LISTING_LOW: c[LISTING_LOW], LISTING_HIGH: c[LISTING_HIGH], BID_PRICE: bid_price,
        LAST_SALE: s[LAST_SALE], SOLD_MEDIAN: s[SOLD_MEDIAN], SOLD_COUNT: s[SOLD_COUNT],
        "sold": s, "listing": c,
    }


# ───────────────────────── B 二次流通の想定利益 ─────────────────────────

def expected_profit(summary: dict, purchase_price: Optional[int], *, sell_market: Optional[str] = None,
                    cfg: Optional[dict] = None, fees: Optional[dict] = None) -> dict:
    """B 二次流通の想定利益。常に executable=False・「想定」。

    売値は SOLD_MEDIAN（sold_status=OK）だけ。LAST_SALE・出品・参考（N件）では計算しない。
    販売手数料は status=CONFIRMED の料率だけ。送料・振込手数料は根拠のある値だけ（null は NOT_CALCULATED）。
    """
    cfg = cfg or load_config()
    fees = load_fee_table() if fees is None else fees
    costs = cfg.get("costs") or {}
    out = {"profit_kind": PROFIT_B_SECONDARY_EXPECTED, "label": "想定", "executable": False,
           "sell_price": None, "sell_price_kind": SOLD_MEDIAN, "purchase_price": purchase_price,
           "fee_yen": None, "shipping_yen": None, "payout_fee_yen": None, "other_yen": None,
           "profit_yen": None, "status": NOT_CALCULATED, "reasons": []}
    reasons = out["reasons"]
    if summary.get("sold_status") != SOLD_OK or not summary.get(SOLD_MEDIAN):
        reasons.append("sold_median_not_stable")
    if not (isinstance(purchase_price, int) and purchase_price > 0):
        reasons.append("purchase_price_unknown")
    market = (sell_market or "").strip().lower()
    if not market:
        reasons.append("sell_market_unspecified")
        spec = {}
    else:
        spec = fees.get(market) or {}
    rate = spec.get("rate")
    if market and not (spec.get("status") == "CONFIRMED" and spec.get("evidence_read_body") is True
                       and isinstance(rate, (int, float)) and 0 <= rate < 1):
        reasons.append("fee_rate_unconfirmed")
    ship = costs.get("outbound_shipping_jpy")
    if not isinstance(ship, int) or ship < 0:
        reasons.append("shipping_unknown")
    payout = (costs.get("payout_fee_jpy") or {}).get(market) if market else None
    if not isinstance(payout, int) or payout < 0:
        reasons.append("payout_fee_unknown")
    other = costs.get("other_jpy")
    if not isinstance(other, int) or other < 0:
        reasons.append("other_cost_unknown")
    if reasons:
        return out
    sell = int(summary[SOLD_MEDIAN])
    fee = int(round(sell * float(rate)))
    profit = sell - purchase_price - fee - ship - payout - other
    out.update({"sell_price": sell, "fee_yen": fee, "shipping_yen": ship, "payout_fee_yen": payout,
                "other_yen": other, "profit_yen": profit,
                "status": PROFITABLE if profit > 0 else NO_PROFIT})
    return out


# ───────────────────────── secondary.py の観測との変換 ─────────────────────────

def record_to_observation(r: SaleRecord) -> dict:
    """台帳の成約を secondary の観測 dict にする（price_kind=SOLD・sale_phase つき）。"""
    return {"product_id": r.product_id, "product_name": "", "tcg": "", "source": r.market,
            "price": float(r.price), "shrink_status": r.condition, "condition": r.condition,
            "unit": r.unit, "observed_at": "", "sold_at": r.sold_at.isoformat(),
            "verified_at": r.verified_at.isoformat(), "url": r.source_url,
            "price_kind": OBS_SOLD, "sale_phase": r.sale_phase}


def is_eligible_sold_observation(o: dict, *, now: datetime, fresh_days: int) -> bool:
    """相場（中央値）に使ってよい観測か: 成約・実物の成約・sold_at が鮮度内。出品・種類不明は False。"""
    if o.get("price_kind") != OBS_SOLD or o.get("sale_phase") != ACTUAL_SALE:
        return False
    t = _parse_dt(o.get("sold_at"))
    if t is None:
        return False
    return now - timedelta(days=fresh_days) <= t <= now + timedelta(days=1)
