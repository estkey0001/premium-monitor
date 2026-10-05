"""商品ごとの価格の履歴（実際に観測した値だけを積み上げる）。

正規化データ（exports/normalized_price_observations/latest.json）は毎回上書きされるので、
その中の「取得に成功し、商品の照合が済み、観測日時がある値」だけを、商品×種別×取得元の系列に足していく。

- 点は観測日時（observed_at）と価格だけ。生成時刻・試行時刻を点にしない。補間しない。日付を埋めない
- 同じ観測日時の点は足さない（同じ値を毎日足し直さない。時刻を新しく見せない）
- 種別を混ぜない（販売価格・買取価格・出品価格・成約中央値は別の系列）
- 取得に失敗した値（0円・取得失敗）・照合未了・設定値の定価（確認日なし）は入れない

出力: exports/price_history/latest.json（CI がコミットして次回に引き継ぐ）
"""

from __future__ import annotations

from datetime import datetime

from src.market import price_types as pt

SCHEMA_VERSION = 1
MAX_POINTS = 180          # 系列ごとに残す点の数（古いものから捨てる）

# 系列の種類（画面の呼び方は price_types.label と同じ。市場価格1本にまとめない）
KIND_RETAIL = "retail"
KIND_BUYBACK = "buyback"
KIND_LISTING = "listing"
KIND_SOLD_MEDIAN = "sold_median"
KIND_LABELS = {KIND_RETAIL: "販売価格（定価）", KIND_BUYBACK: "買取価格", KIND_LISTING: "出品価格（代表値）",
               KIND_SOLD_MEDIAN: "成約中央値"}


def empty() -> dict:
    return {"schema_version": SCHEMA_VERSION, "updated_at": "", "series": {}}


def _kind(o: dict) -> str:
    """観測1件の系列の種類。履歴に入れない値は空文字。"""
    t = pt.canonical(o.get("canonical_price_type"))
    role = str(o.get("price_role") or "")
    if role == "official" and t == pt.RETAIL:
        # 定価は確認日のあるものだけ（設定値で確認日不明のものは入れない）
        return KIND_RETAIL if o.get("freshness_basis") in ("verified", "verified_stale") else ""
    if o.get("is_exact_product_match") is not True:
        return ""
    # 状態の違う価格（中古・未使用・開封済みなど）は混ぜない。監視している新品の系統だけ
    from src.content.ui.opportunity import _cond_family
    if _cond_family(o.get("condition")) != "new":
        return ""
    if t == pt.BUYBACK_CASH and role == "sell":
        return KIND_BUYBACK
    if t == pt.SOLD_MEDIAN or o.get("sold_median_eligible") is True:
        return KIND_SOLD_MEDIAN
    if t == pt.LISTING:
        return KIND_LISTING
    return ""


def series_key(product_id: str, kind: str, source: str) -> str:
    return f"{product_id}|{kind}|{source}"


def _same_time(a: str, b: str) -> bool:
    """2つの観測時刻が同じか（日付だけどうしは文字列で、時刻つきどうしは時刻として比べる）。"""
    from src.tcg.models import parse_dt
    a, b = str(a or ""), str(b or "")
    if a == b:
        return True
    if len(a) == 10 or len(b) == 10:
        return False
    da, db = parse_dt(a.replace(" ", "T", 1)), parse_dt(b.replace(" ", "T", 1))
    return da is not None and db is not None and da == db


def _future(at: str, now: datetime) -> bool:
    """観測の時刻が今より後か（日付だけの観測は、その日の終わりまでを今と比べる。時刻を作らない）。"""
    from datetime import timedelta

    from src.tcg.models import JST, parse_dt
    if len(at) == 10:
        d = parse_dt(at + "T23:59:59+09:00")
    else:
        d = parse_dt(at.replace(" ", "T", 1))
    if d is None:
        return True                                    # 読めない時刻は入れない
    return d > now.astimezone(JST) + timedelta(minutes=5)


def merge(history: dict | None, observations: list | None, now: datetime | None = None) -> dict:
    """前回の履歴に、今回の観測のうち新しい点だけを足す（既存の点は書き換えない）。未来の時刻の観測は入れない。"""
    from src.tcg.models import JST
    now = now or datetime.now(tz=JST)
    h = history if isinstance(history, dict) and isinstance(history.get("series"), dict) else empty()
    series: dict = h["series"]
    for o in observations or []:
        if not isinstance(o, dict):
            continue
        kind = _kind(o)
        price = o.get("price")
        at = str(o.get("observed_at") or "")
        if not kind or not isinstance(price, (int, float)) or price <= 0 or not at or _future(at, now):
            continue
        if str(o.get("rejection_reason") or "") not in ("", "stale_over_14d"):
            continue                                   # 取得失敗・疑わしい値・付属品などは入れない
        pid = str(o.get("product_id") or "")
        src = str(o.get("source_name") or o.get("source_id") or "")
        if not pid or not src:
            continue
        key = series_key(pid, kind, src)
        s = series.setdefault(key, {"product_id": pid, "kind": kind, "source": src, "points": []})
        if any(_same_time(p["at"], at) for p in s["points"]):
            continue                                   # 同じ観測は足さない（書式が違っても同じ時刻なら同じ観測）
        point = {"at": at, "price": int(price)}
        if kind == KIND_SOLD_MEDIAN:
            point.update({"samples": o.get("sample_count"), "period_start": o.get("sold_period_start") or "",
                          "period_end": o.get("sold_period_end") or ""})
        s["points"].append(point)
        s["points"].sort(key=lambda p: p["at"])
        del s["points"][:-MAX_POINTS]
    return h


def changes(history: dict | None, product_id: str, *, since: datetime | None = None) -> list[dict]:
    """系列の隣り合う2点で価格が変わったところ（変化の前・後・時刻・取得元）。推測の変化は作らない。"""
    from src.tcg.models import parse_dt
    out = []
    for s in ((history or {}).get("series") or {}).values():
        if s.get("product_id") != product_id:
            continue
        pts = s.get("points") or []
        for a, b in zip(pts, pts[1:]):
            if a["price"] == b["price"]:
                continue
            at = parse_dt(str(b["at"]).replace(" ", "T", 1))
            if since is not None and (at is None or at < since):
                continue
            out.append({"kind": s["kind"], "source": s["source"], "before": a["price"], "after": b["price"],
                        "changed_at": b["at"], "previous_at": a["at"]})
    return sorted(out, key=lambda c: c["changed_at"], reverse=True)
