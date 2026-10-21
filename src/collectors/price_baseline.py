"""買取価格の「前回との比較」の基準（Production Integrity M-3）。

以前は data/manual_buyback_prices.csv（CI が commit しないので 2026-08-23 の手入力のまま）を前回値として比べていたため、
「前回 ¥134,500 → 今回 ¥200,700（+49%）」「前回 ¥428,000 → 今回 ¥260,000（−39%）」のように、2か月前の手入力の値との差を
毎日「誤価格の疑い」として出していた。ここでは、**直近の正常な自動取得の値**を基準にして、CI の実行ごとに残す。

- 基準に入れるのは、自動取得（auto_scraped）で、価格が正で、隔離されなかった行だけ（手入力・取得失敗・隔離した行は入れない）
- 基準の観測時刻は、実際に取得できた時刻（取得できたときだけ更新する。取得に失敗した日に時刻を新しくしない）
- 基準が MAX_AGE_DAYS（14日）より古いときは使わない（古い値を前回値にしない）。取得に失敗した日は、最後の正常な値を
  そのまま残す（時刻も変えない）。古くなれば捨てる
- 基準が無い組（初めての観測・古くて捨てた）は、前回との比較をしない（NEW_OBSERVATION。変動の警告を出さない）
- 保存先は exports/collector_report/price_baseline.json（CI の commit の対象）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
MAX_AGE_DAYS = 14
SCHEMA = 1
BASELINE_SOURCE = "auto_scraped"


def _parse(value) -> datetime | None:
    s = str(value or "").strip().replace(" JST", "")
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=JST)


def _price(value) -> int:
    try:
        p = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return p if p > 0 else 0


def read_entries(path: Path) -> list[dict]:
    """保存された基準の全行（古い行も含む）。無い・壊れていれば空。"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = d.get("entries") if isinstance(d, dict) else None
    return [e for e in rows or [] if isinstance(e, dict)]


def file_status(path: Path) -> str:
    """基準のファイルの状態: missing（まだ無い）/ unreadable（あるのに読めない・形が違う）/ ok。
    unreadable のとき前回比の判定が黙って全部オフになるので、レポートと運営者向けのアラートに出す。"""
    path = Path(path)
    if not path.exists():
        return "missing"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "unreadable"
    return "ok" if isinstance(d, dict) and isinstance(d.get("entries"), list) else "unreadable"


def is_fresh(entry: dict, now: datetime, max_age_days: int = MAX_AGE_DAYS) -> bool:
    """基準として使える行か（自動取得・価格が正・観測時刻が読めて、未来でなく、max_age_days 以内）。"""
    if entry.get("data_source") != BASELINE_SOURCE or not _price(entry.get("buyback_price")):
        return False
    at = _parse(entry.get("observed_at"))
    if at is None:
        return False
    age = (now - at).total_seconds() / 86400
    return -1 <= age <= max_age_days


def load(path: Path, now: datetime) -> list[dict]:
    """前回との比較に使える基準（compute_suspicious・price_changes がそのまま読める行の形）。"""
    return [e for e in read_entries(path) if is_fresh(e, now)]


def build(previous: list[dict], new_rows: list[dict], now: datetime) -> list[dict]:
    """今回の実行で書き直す基準。

    今回の正常な自動取得の行で、その組（商品 × 店）の基準を置き換える。今回取れなかった組は、前回の基準が14日以内
    ならそのまま残す（値も観測時刻も変えない）。
    """
    out: dict[tuple, dict] = {}
    for e in previous:
        if is_fresh(e, now):
            out[(e.get("product_alias", ""), e.get("buyback_shop", ""))] = {
                k: e.get(k, "") for k in ("product_alias", "buyback_shop", "buyback_price", "condition", "url",
                                          "observed_at", "data_source")}
    for r in new_rows:
        if r.get("data_source") != BASELINE_SOURCE or not _price(r.get("buyback_price")):
            continue                      # 手入力・取得失敗・隔離した行（suspicious_rejected）は基準にしない
        at = _parse(r.get("observed_at"))
        if at is None or at > now + timedelta(days=1):
            continue
        out[(r.get("product_alias", ""), r.get("buyback_shop", ""))] = {
            "product_alias": r.get("product_alias", ""), "buyback_shop": r.get("buyback_shop", ""),
            "buyback_price": _price(r.get("buyback_price")), "condition": r.get("condition", ""),
            "url": r.get("url", ""), "observed_at": r.get("observed_at", ""), "data_source": BASELINE_SOURCE}
    return [out[k] for k in sorted(out)]


def save(path: Path, entries: list[dict], now: datetime) -> None:
    """基準を保存する（途中で壊れないよう一時ファイル経由）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"), "max_age_days": MAX_AGE_DAYS,
           "note": "買取価格の前回との比較の基準（直近の正常な自動取得の値）。手入力・古い値は基準にしない",
           "entries": entries}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def stats(previous_all: list[dict], baseline: list[dict], new_rows: list[dict], file: str = "ok") -> dict:
    """レポートに残す基準の使われ方（新しい観測の数・古くて使わなかった数）。"""
    have = {(e.get("product_alias", ""), e.get("buyback_shop", "")) for e in baseline}
    new_obs = sorted({(r.get("product_alias", ""), r.get("buyback_shop", "")) for r in new_rows
                      if _price(r.get("buyback_price")) and (r.get("product_alias", ""), r.get("buyback_shop", "")) not in have})
    return {"baseline_file": file, "baseline_entries": len(baseline), "stale_baseline_dropped": max(len(previous_all) - len(baseline), 0),
            "new_observations": [{"product_alias": a, "shop": s} for a, s in new_obs],
            "max_age_days": MAX_AGE_DAYS}
