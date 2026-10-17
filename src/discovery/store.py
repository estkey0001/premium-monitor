"""発見の候補の台帳（Phase 27）。

CI は毎回 DB を作り直すので、候補の正本は生成物としてコミットする台帳（exports/discovery/*.json）にする。DB の既存の
product_candidates の表にも写す（既存の候補の仕組み・CLI の approve-product-candidate / reject-product-candidate を
再利用する。別の候補の仕組みは作らない）。

- 候補の ID は発見元と同一性（型番・容量・商品コード・告知の URL など）から作る（毎回別の候補にしない）
- 同じ候補を見つけ直しても discovered_at は変えない。last_seen_on（日付だけ）を進める。内容が同じなら時刻だけを
  書き換えない
- 見つからなくなった候補はすぐ消さない（STALE_AFTER_DAYS で STALE。人が判断した APPROVED / REJECTED はそのまま）
- 正本（config/products.yaml・products の表）には書かない
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

SCHEMA = 1
NEW = "NEW"
PENDING_REVIEW = "PENDING_REVIEW"
MATCHED_EXISTING = "MATCHED_EXISTING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
STALE = "STALE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
ANNOUNCEMENT_REVIEW_REQUIRED = "ANNOUNCEMENT_REVIEW_REQUIRED"
MATCHED_EVENT = "MATCHED_EVENT"
STATUSES = (NEW, PENDING_REVIEW, MATCHED_EXISTING, APPROVED, REJECTED, STALE, REVIEW_REQUIRED,
            ANNOUNCEMENT_REVIEW_REQUIRED, MATCHED_EVENT)
HUMAN_DECIDED = frozenset({APPROVED, REJECTED})     # 人が決めた状態は発見で上書きしない
OPEN_REVIEW = frozenset({NEW, PENDING_REVIEW, REVIEW_REQUIRED, ANNOUNCEMENT_REVIEW_REQUIRED})
STALE_AFTER_DAYS = 7                                # 見つからなくなってから STALE にするまで
RETENTION_DAYS = 90                                 # STALE・MATCHED のまま見つからない候補を残す日数（人の判断は残す）

PRODUCT_FILE = "product_candidates.json"
EVENT_FILE = "event_candidates.json"
# 既存の product_candidates の表の状態（pending / watching / approved / rejected）への写し方
DB_STATUS = {NEW: "pending", PENDING_REVIEW: "pending", REVIEW_REQUIRED: "pending",
             ANNOUNCEMENT_REVIEW_REQUIRED: "pending", APPROVED: "approved", REJECTED: "rejected", STALE: "watching"}


def stable_id(prefix: str, *parts) -> str:
    """発見元と同一性から作る候補の ID（同じものは同じ ID）。"""
    key = "|".join(str(p or "").strip().lower() for p in parts)
    return f"{prefix}-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:12]}"


def empty() -> dict:
    return {"schema": SCHEMA, "candidates": {}}


def load(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty()
    if not isinstance(d, dict) or not isinstance(d.get("candidates"), dict):
        return empty()
    return d


def save(path: Path, store: dict) -> None:
    from src.utils.atomic_write import write_json_atomic
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, store)


def _day(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def upsert(store: dict, cid: str, fields: dict, *, status: str, now: datetime, reasons=()) -> dict:
    """候補を入れる・見つけ直す。discovered_at は最初の発見のまま。人が決めた状態は変えない。

    fields の内容が変わったときだけ updated_at を進める（同じ内容で時刻だけを書き換えない）。
    """
    cands = store["candidates"]
    old = cands.get(cid)
    reasons = sorted(set(reasons or []))
    if old is None:
        rec = dict(fields, candidate_id=cid, status=status, reasons=reasons,
                   discovered_at=now.isoformat(timespec="seconds"), last_seen_on=_day(now),
                   updated_at=now.isoformat(timespec="seconds"))
        cands[cid] = rec
        return rec
    changed = any(old.get(k) != v for k, v in fields.items()) or sorted(old.get("reasons") or []) != reasons
    new_status = old.get("status") if old.get("status") in HUMAN_DECIDED else status
    changed = changed or new_status != old.get("status")
    old.update(fields)
    old["reasons"] = reasons
    old["status"] = new_status
    old["last_seen_on"] = _day(now)
    if changed:
        old["updated_at"] = now.isoformat(timespec="seconds")
    return old


def age_out(store: dict, seen_ids, *, now: datetime, scope=None) -> dict:
    """今回見つからなかった候補を STALE にする（すぐ消さない）。保存期間を過ぎた STALE・MATCHED を消す。

    scope: 対象の候補を絞る関数（発見元ごとに、今回その発見元を読めたときだけ STALE にする）。
    """
    out = {"stale": 0, "dropped": 0}
    seen = set(seen_ids)
    for cid, rec in list(store["candidates"].items()):
        if scope is not None and not scope(rec):
            continue
        if cid in seen:
            continue
        last = datetime.fromisoformat(str(rec.get("last_seen_on") or _day(now)) + "T00:00:00").date()
        gone = (now.date() - last).days
        if rec.get("status") in HUMAN_DECIDED:
            continue                                   # 人が決めたものは残す
        if gone >= RETENTION_DAYS and rec.get("status") in (STALE, MATCHED_EXISTING, MATCHED_EVENT):
            del store["candidates"][cid]
            out["dropped"] += 1
        elif gone >= STALE_AFTER_DAYS and rec.get("status") != STALE:
            rec["stale_from"] = rec.get("status")            # 元の状態（確認待ちだったか・正式なイベントだったか。レビュー M-4）
            rec["status"] = STALE
            rec["updated_at"] = now.isoformat(timespec="seconds")
            out["stale"] += 1
    return out


def counts(store: dict) -> dict:
    c = {s: 0 for s in STATUSES}
    for r in store["candidates"].values():
        c[r.get("status")] = c.get(r.get("status"), 0) + 1
    return c


def decide(path: Path, cid: str, decision: str, *, now: datetime, product_id: str | None = None) -> dict | None:
    """人の判断（APPROVED / REJECTED）を台帳に記録する。正本には書かない（products.yaml への追加は人が手で行う）。"""
    store = load(path)
    rec = store["candidates"].get(cid)
    if rec is None:
        return None
    rec["status"] = APPROVED if decision == "approve" else REJECTED
    rec["reviewed_at"] = now.isoformat(timespec="seconds")
    if product_id:
        rec["approved_product_id"] = product_id
    rec["updated_at"] = now.isoformat(timespec="seconds")
    save(path, store)
    return rec


def mirror_to_db(store: dict, db_path: Path) -> int:
    """台帳の新商品の候補を、既存の product_candidates の表に写す（照合済み・告知は写さない）。写した件数。"""
    import sqlite3
    if not Path(db_path).exists():
        return 0
    n = 0
    con = sqlite3.connect(str(db_path))
    try:
        has = con.execute("select name from sqlite_master where type='table' and name='product_candidates'").fetchone()
        if not has:
            return 0
        for cid, r in store["candidates"].items():
            st = DB_STATUS.get(r.get("status"))
            if st is None or r.get("genre") == "tcg":
                continue                                     # TCG は写さない（既存の下書きの生成などに流さない。レビュー L-7）
            con.execute(
                "insert into product_candidates (id, source_id, product_name, detected_keyword, detected_url, detected_at,"
                " confidence, status, genre, brand, estimated_price, notes, reviewed_at, approved_product_id)"
                " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?) on conflict(id) do update set status=excluded.status,"
                " product_name=excluded.product_name, detected_url=excluded.detected_url,"
                " estimated_price=excluded.estimated_price, notes=excluded.notes, reviewed_at=excluded.reviewed_at,"
                " approved_product_id=excluded.approved_product_id",
                (cid, r.get("source") or "", r.get("product_name") or "", r.get("model_number") or "",
                 r.get("official_url") or "", r.get("discovered_at") or "", 0.9, st, r.get("genre") or "",
                 r.get("brand") or "", r.get("official_price"), ",".join(r.get("reasons") or []),
                 r.get("reviewed_at"), r.get("approved_product_id")))
            n += 1
        con.commit()
    finally:
        con.close()
    return n
