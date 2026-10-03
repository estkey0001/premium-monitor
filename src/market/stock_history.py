"""在庫の状態の履歴（在庫再開。UI Phase 4）。

CI の DB は実行のたびに作り直されるので、前回の在庫の状態は exports/stock_history/latest.json に残し、
次の実行で読み込んで比べる。ここでは「観測」（取得に成功した在庫の状態）だけを受け取り、状態の変化を記録する。

用語（混同しない）:
- state: 今の在庫の状態（最後に取得に成功した観測の値）
- last_checked_at: 最後に在庫の状態を取得できた時刻（取得に失敗した実行では更新しない）
- restocked_at: 在庫切れ（OUT_OF_STOCK）を確認した後に、在庫あり（IN_STOCK）を確認した時刻（再入荷）
- first_seen_in_stock_at: 在庫切れを確認したことが無い状態から、初めて在庫ありを確認した時刻（「在庫確認」。
  再入荷とは言わない）

重複を出さない: 在庫あり → 未確認 → 在庫あり は、間に在庫切れを確認していないので新しい再入荷にしない
（再入荷の判定は「最後に分かっていた在庫の有無」= last_definite_state だけで行う）。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.market import stock_state as ss

SCHEMA_VERSION = 1
MAX_EVENTS = 500
EVENT_RESTOCK, EVENT_FIRST_SEEN, EVENT_SOLD_OUT = "RESTOCK", "FIRST_SEEN", "SOLD_OUT"

# 観測で受け取る項目（state と observed_at は必須）
OBS_FIELDS = ("key", "product_id", "product_name", "category", "store", "source_type", "event_type", "variant",
              "condition", "state", "observed_at", "price", "price_observed_at", "url", "source_url",
              "purchase_limit")


def empty() -> dict:
    return {"schema_version": SCHEMA_VERSION, "updated_at": "", "entries": {}, "events": []}


def load(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty()
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        return empty()
    data.setdefault("entries", {})
    data.setdefault("events", [])
    return data


def save(path: Path, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


# 観測の時刻が実行時刻より先にあってよい余裕（時計のずれ）。これより未来の観測は捨てる
FUTURE_TOLERANCE_SECONDS = 600
# 観測ごとにまとめて上書きする項目（観測に無ければ空にする。前回の価格・URL を引き継がない）
OVERWRITE_FIELDS = ("price", "price_observed_at", "url", "source_url", "purchase_limit")


def _dt(v):
    """時刻つきの日時だけ読む（日付だけの値を 0 時とみなさない）。"""
    from src.tcg.models import parse_dt
    s = str(v or "").strip()
    if len(s) < 16 or s[10] not in "T ":
        return None
    return parse_dt(s.replace(" ", "T", 1))


def apply(history: dict, observations: list[dict], *, now: datetime) -> dict:
    """観測を履歴に反映する（元の dict を書き換えて返す）。取得に失敗した店・商品は観測に入れないこと。"""
    entries: dict = history.setdefault("entries", {})
    events: list = history.setdefault("events", [])
    for o in observations:
        state = o.get("state")
        at = _dt(o.get("observed_at"))
        if state not in ss.STOCK_STATES or at is None or not o.get("key"):
            continue
        if (at - now).total_seconds() > FUTURE_TOLERANCE_SECONDS:
            continue    # 未来の時刻の観測は使わない（期限が先に延び、その後の観測を受け付けなくなるため）
        e = entries.get(o["key"])
        if e is None:
            e = {"state": ss.UNKNOWN, "last_definite_state": "", "last_checked_at": "", "restocked_at": "",
                 "first_seen_in_stock_at": "", "previous_state": ""}
            entries[o["key"]] = e
        last = _dt(e.get("last_checked_at"))
        if last is not None and at <= last:
            continue    # 前回より新しくない観測では何も変えない（時刻だけ進めない）
        prev_def = e.get("last_definite_state") or ""
        kind = ""
        if state == ss.IN_STOCK and prev_def == ss.OUT_OF_STOCK:
            kind, e["restocked_at"] = EVENT_RESTOCK, at.isoformat()
        elif state == ss.IN_STOCK and not prev_def and not e.get("first_seen_in_stock_at"):
            kind, e["first_seen_in_stock_at"] = EVENT_FIRST_SEEN, at.isoformat()
        elif state == ss.OUT_OF_STOCK and prev_def == ss.IN_STOCK:
            kind = EVENT_SOLD_OUT
        if state in ss.DEFINITE_STATES:
            e["last_definite_state"] = state
        e["previous_state"] = e.get("state") or ss.UNKNOWN
        e["state"] = state
        e["last_checked_at"] = at.isoformat()
        for k in OBS_FIELDS:
            if k in ("state", "observed_at"):
                continue
            if k in OVERWRITE_FIELDS:
                e[k] = o.get(k) if o.get(k) not in (None, "") else ""
            elif o.get(k) not in (None, ""):
                e[k] = o[k]
        if kind:
            events.append({"key": o["key"], "kind": kind, "previous_state": prev_def or ss.UNKNOWN,
                           "new_state": state, "transition_at": at.isoformat(),
                           "product_id": o.get("product_id") or "", "product_name": o.get("product_name") or "",
                           "store": o.get("store") or "", "source": o.get("source_type") or ""})
    history["events"] = events[-MAX_EVENTS:]
    history["updated_at"] = now.isoformat(timespec="seconds")
    return history
