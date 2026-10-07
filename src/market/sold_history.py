"""成約（SOLD）の履歴と成約中央値（SOLD_MEDIAN）の作り方（Phase 12）。

成約1件の正本の形（SoldRecord）・検証・重複の除外・CI をまたいだ保存・成約中央値の観測への変換をここに集める。
判定の正本は src/market/price_types（is_item_url・sold_evidence_reasons・sold_median・MIN_SOLD_SAMPLES）で、
ここでは新しい判定の基準を作らない。

決まり:
- 成約日時（sold_at）の無い成約は使わない。観測した時刻（observed_at）で代用しない
- 1件の商品ページの URL（検索結果・ダミーは不可）・商品の同一性の確認・状態がそろったものだけ
- 出品（LISTING）は成約にしない（このモジュールは成約だけを受け付ける）
- 同じ取得元・同じ商品ページ・同じ成約日時は1件（同じ成約を毎回足さない。再取得で observed_at を新しくしない）
- 成約中央値は3件以上（MIN_SOLD_SAMPLES）・集計期間の開始と終了があるものだけ。期間は売値の鮮度の基準
  （normalized_prices.STALE_DAYS = 14日）をそのまま使う（新しい期間を作らない）
- 状態の系統（新品・未使用・中古・開封済み）を混ぜない
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from src.market import price_types as pt

ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_PATH = ROOT / "exports" / "sold_history" / "latest.json"


@dataclass(frozen=True)
class SoldRecord:
    """成約1件。"""
    product_id: str
    source: str               # 取得元（ebay_insights など）
    item_url: str             # 1件の商品ページの URL
    sold_price: int           # 円（外貨は換算後。換算の根拠は note に残す）
    sold_at: str              # 成約日時（ISO8601）。observed_at で代用しない
    condition: str            # new_unopened / used_a など（normalized の状態の名前）
    identity: str             # 同じ商品とみなすキー（商品 ID と容量・型など）
    identity_verified: bool   # 商品の同一性を確かめたか（型番・容量・版の一致）
    observed_at: str          # 取得した時刻（初めて見た時刻。再取得で新しくしない）
    currency: str = "JPY"
    sold_price_original: Optional[float] = None
    title: str = ""
    note: str = ""


def _cond_family(cond: str) -> str:
    from src.content.ui.opportunity import _cond_family as f
    return f(cond)


def record_reasons(r: SoldRecord) -> tuple[str, ...]:
    """成約として使えない理由（空なら使える）。"""
    out = list(pt.sold_evidence_reasons(r.item_url, r.sold_at))     # 商品ページの URL・成約日時（未来は不可）
    if not r.product_id:
        out.append("no_product_id")
    if not (isinstance(r.sold_price, int) and r.sold_price > 0):
        out.append("invalid_price")
    if not r.identity or r.identity_verified is not True:
        out.append("identity_unverified")
    if not _cond_family(r.condition):
        out.append("unknown_condition")
    if not r.observed_at:
        out.append("no_observed_at")
    return tuple(out)


def dedupe_key(r: SoldRecord) -> tuple[str, str, str]:
    """同じ成約を表すキー（取得元・商品ページ・成約日時）。"""
    url = str(r.item_url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return (r.source, url, str(r.sold_at)[:19])


def merge(history: Iterable[SoldRecord], new: Iterable[SoldRecord]) -> tuple[list[SoldRecord], dict]:
    """履歴に新しい成約を足す（使えない成約は足さない。同じ成約は最初に見たものを残す）。

    戻り値: (履歴, {"added": n, "duplicate": n, "rejected": {理由: n}})
    """
    out: list[SoldRecord] = []
    seen: set = set()
    for r in history:
        k = dedupe_key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    stats = {"added": 0, "duplicate": 0, "rejected": {}}
    for r in new:
        why = record_reasons(r)
        if why:
            for w in why:
                stats["rejected"][w] = stats["rejected"].get(w, 0) + 1
            continue
        k = dedupe_key(r)
        if k in seen:
            stats["duplicate"] += 1          # 同じ成約は足さない（observed_at も変えない）
            continue
        seen.add(k)
        out.append(r)
        stats["added"] += 1
    return out, stats


def load(path: Path = HISTORY_PATH) -> list[SoldRecord]:
    """保存した履歴（無い・壊れているときは空）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    fields = set(SoldRecord.__dataclass_fields__)
    for d in data.get("records") or []:
        if isinstance(d, dict):
            try:
                out.append(SoldRecord(**{k: v for k, v in d.items() if k in fields}))
            except TypeError:
                continue
    return out


def save(records: list[SoldRecord], now: datetime, path: Path = HISTORY_PATH) -> None:
    """履歴を書く（CI の生成物として残し、次の実行で読み直す。DB を作り直しても消えない）。"""
    from src.utils.atomic_write import write_text_atomic
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # 取得元の商品名（title）は保存しない（公開のリポジトリに残す情報を、判定に必要な最小限にする。監査 L6。
    # eBay の API のデータを公開のリポジトリに残してよいかは、有効にする前に API の利用規約で確かめる）
    body = {"generated_at": now.isoformat(timespec="seconds"),
            "note": "成約（SOLD）の履歴。成約日時・商品ページ・同一性の確認がそろったものだけ。同じ成約は1件",
            "records": [{**asdict(r), "title": ""} for r in records]}
    write_text_atomic(Path(path), json.dumps(body, ensure_ascii=False, indent=2))


def period(now: datetime, days: Optional[int] = None) -> tuple[datetime, datetime]:
    """成約中央値の集計期間（既定は売値の鮮度の基準 STALE_DAYS）。"""
    from src.market.normalized_prices import STALE_DAYS
    d = STALE_DAYS if days is None else days
    return now - timedelta(days=d), now


def median_stats(records: Iterable[SoldRecord], now: datetime, days: Optional[int] = None) -> list[dict]:
    """商品・状態の系統ごとの成約中央値（price_types.sold_median の結果。件数が足りないものも status つきで返す）。"""
    ps, pe = period(now, days)
    groups: dict[tuple[str, str], list[SoldRecord]] = {}
    for r in records:
        if record_reasons(r):
            continue
        groups.setdefault((r.product_id, _cond_family(r.condition)), []).append(r)
    out = []
    for (pid, fam), rs in sorted(groups.items()):
        samples = [pt.MarketSample(price=r.sold_price, price_type=pt.SOLD, identity=r.identity,
                                   condition=fam, item_url=r.item_url, sold_at=r.sold_at) for r in rs]
        identity = rs[0].identity
        st = pt.sold_median(samples, identity=identity, period_start=ps, period_end=pe, conditions={fam})
        # 日時は文字列でなく時刻として比べる（タイムゾーンの書き方が混ざってもずれない。レビュー Low）
        latest = max(rs, key=lambda r: pt._parse_dt(r.sold_at))
        # 状態は系統の名前（used の中の等級のどれか1つに偏らせない。新品は既存の名前のまま）
        cond = rs[0].condition if fam == "new" else fam
        st.update({"product_id": pid, "condition_family": fam, "condition": cond,
                   "sources": sorted({r.source for r in rs}),
                   "latest_sold_at": latest.sold_at,
                   "first_observed_at": min(rs, key=lambda r: pt._parse_dt(r.observed_at) or now).observed_at})
        out.append(st)
    return out


# API で取った海外の成約（ルートの売値は海外の手数料・送料で計算される。generate_profit_routes の
# overseas_sold_price・collector_method=api の経路）。それ以外（国内）は今は取得元が無い
OVERSEAS_API_SOURCES = frozenset({"ebay_insights"})


def _in_period_records(records: Iterable[SoldRecord], st: dict) -> list[SoldRecord]:
    """集計と同じ条件（使える成約・同じ商品と状態の系統・期間内）の成約。件数不足の参考に使う。"""
    ps, pe = pt._parse_dt(st["period_start"]), pt._parse_dt(st["period_end"])
    out = []
    for r in records:
        if (record_reasons(r) or r.product_id != st["product_id"] or r.identity != st["identity"]
                or _cond_family(r.condition) != st["condition_family"]):
            continue
        t = pt._parse_dt(r.sold_at)
        if ps and pe and t and ps <= t <= pe:
            out.append(r)
    return out


def median_observations(records: Iterable[SoldRecord], now: datetime, days: Optional[int] = None) -> list[dict]:
    """成約の集計を正規化の観測（売値 sell）にする。

    - 3件以上・期間あり（price_types.is_sold_median_eligible）: 成約中央値（sold_median_eligible=True）
    - 1〜2件（API で取った海外の成約だけ）: 中央値は作らない。成約1件ずつを参考の観測にする
      （sold_median_eligible=False・種別 SOLD・商品ページの URL つき。確定の売値に使わず、参考ルートにだけなる。監査 H4）
    - 国内の成約で件数が足りないもの・0件は観測にしない
    観測の observed_at は成約日時（取得した時刻で新しく見せない）。
    """
    from src.market.normalized_prices import make_observation
    records = list(records)
    rows = []
    for st in median_stats(records, now, days):
        overseas = set(st["sources"]) <= OVERSEAS_API_SOURCES
        common = dict(market_type="overseas" if overseas else "sold_median", price_role="sell",
                      price_type="overseas_sold_price" if overseas else "flea_sold_price",
                      collector_method="api" if overseas else "",
                      source_mode="api" if overseas else "", sold_median_identity_verified=True)
        if pt.is_sold_median_eligible(st):
            rows.append(make_observation(
                now, product_id=st["product_id"], product_name="", source_id="sold_median",
                source_name="成約中央値（" + "・".join(st["sources"]) + "）", condition=st["condition"],
                price=st["median"], observed_at=st["latest_sold_at"], confidence="high",
                source_url="", item_url="", link_type="none",
                price_context=f"成約中央値（{st['sample_count']}件）", sample_count=st["sample_count"],
                sold_median_eligible=True, sold_period_start=st["period_start"], sold_period_end=st["period_end"],
                sold_median_min=st["min"], sold_median_max=st["max"], canonical_price_type=pt.SOLD_MEDIAN,
                extraction_method="sold_median", **common))
            continue
        if not overseas:
            continue
        for r in _in_period_records(records, st):
            rows.append(make_observation(
                now, product_id=r.product_id, product_name="", source_id="sold_reference",
                source_name="成約（参考・1件）" + r.source, condition=r.condition, price=r.sold_price,
                observed_at=r.sold_at, confidence="medium", source_url=r.item_url, item_url=r.item_url,
                link_type="item", price_context=f"成約1件（参考。期間内の成約は{st['sample_count']}件で中央値にしない）",
                sample_count=1, sold_median_eligible=False, sold_at=r.sold_at, canonical_price_type=pt.SOLD,
                extraction_method="sold_reference", **common))
    return rows
