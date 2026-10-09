"""今すぐ行動の通知の outbox（Phase 20）。送っても二重に送らないための台帳と配信の状態。

候補を配信先へ直接は送らない。必ず次の順にする:

  診断の行 → observe（候補を outbox に PENDING で記録）→ 保存（永続化）→ prepare（配信の直前の確認・SENDING を記録）
  → 保存（永続化。その内容のハッシュを send に渡す）→ send（SENDING の記録だけを送る）→ 保存

- 台帳（products）と outbox（records）は1つのファイルに入れ、まとめて atomic に書く（途中で壊れない・片方だけ進まない）
- 冪等性のキー（idempotency_key）は配信先に依らない: 種類・商品・受付の識別（抽選・予約・先着）か、通常販売の
  「行動できないと確かめた観測」（arm）。同じ候補を作り直しても同じキーになる。outbox は (キー, 方式) で1件だけ
- 送る前に SENDING を永続化する。送った後に保存できずに止まったら、次の実行は SENDING を「届いたか不明」
  （UNKNOWN_DELIVERY）にして自動では送り直さない（二重に送らない側に倒す）
- dry-run は DRY_RUN_PLANNED（DELIVERED と別）。dry-run の記録は本番の送信を止めない（方式ごとに別の記録）
- 判定・利益は計算し直さない（Phase 18 の正本の結果 = 診断の行を使う。配信の直前に最新の行で確かめ直し、本文は最新の値）
- 台帳に配信先の URL・トークン・チャット ID を入れない（公開のリポジトリに保存する）
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from src.market import actionability as act
from src.notifiers import actionable as an
from src.notifiers import adapters as ad

SCHEMA = 2
MODE_DRY, MODE_LIVE = "dry_run", "live"

PENDING = "PENDING"
READY = "READY"
SENDING = "SENDING"
DELIVERED = "DELIVERED"
DRY_RUN_PLANNED = "DRY_RUN_PLANNED"
FAILED_RETRYABLE = "FAILED_RETRYABLE"
FAILED_FINAL = "FAILED_FINAL"
CANCELLED = "CANCELLED"
EXPIRED = "EXPIRED"
UNKNOWN_DELIVERY = "UNKNOWN_DELIVERY"
STATUSES = (PENDING, READY, SENDING, DELIVERED, DRY_RUN_PLANNED, FAILED_RETRYABLE, FAILED_FINAL, CANCELLED, EXPIRED,
            UNKNOWN_DELIVERY)
DUE = frozenset({PENDING, READY, FAILED_RETRYABLE})                  # 配信の直前の確認に回すもの
TERMINAL = frozenset({DELIVERED, DRY_RUN_PLANNED, FAILED_FINAL, CANCELLED, EXPIRED, UNKNOWN_DELIVERY})

MAX_ATTEMPTS = 5                       # 送信の試行の上限（無限に再試行しない）
BACKOFF_SECONDS = 300                  # 再試行の間隔（5分から倍に。上限6時間）
RETENTION_DAYS = 30                    # 終わった記録を残す日数（今の候補のキーは消さない）
NOT_CONFIRMED = an.NOT_CONFIRMED
REARM_STATES = an.REARM_STATES
_EVENT_TYPES = (act.LOTTERY_OPEN, act.PREORDER_OPEN, act.FIRST_COME_OPEN)


# ── キー ──────────────────────────────────────────────────────────────────

def event_identity(row: dict) -> str:
    """抽選・予約・先着の受付の識別（商品 ID|受付の開始）。締切は含めない（締切の延長だけでは新しい受付にしない）。"""
    if row.get("availability") not in _EVENT_TYPES:
        return ""
    parts = str(row.get("event_key") or "").split("|")
    return "|".join(parts[:2]) if len(parts) >= 2 and parts[0] and parts[1] else ""


def idempotency_key(product_id: str, kind: str, ident: str) -> str:
    return f"{an.TYPE}:{product_id}:{kind}:{ident}"


def notification_id(key: str, mode: str) -> str:
    return hashlib.sha256(f"{key}|{mode}".encode()).hexdigest()[:20]


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


# ── 保存 ──────────────────────────────────────────────────────────────────

def empty_store() -> dict:
    return {"schema": SCHEMA, "products": {}, "records": {}}


def migrate(raw) -> dict | None:
    """読み込んだ内容を今の形にする（Phase 19 の台帳 {"products": {...}} も読む）。読めなければ None（基準日）。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("products"), dict):
        return None
    if raw.get("schema") == SCHEMA:
        s = {"schema": SCHEMA, "products": dict(raw["products"]),
             "records": dict(raw.get("records") or {}) if isinstance(raw.get("records"), dict) else {}}
        return s
    out = empty_store()
    for pid, p in raw["products"].items():
        if not isinstance(p, dict):
            continue
        notified = str(p.get("notified_key") or "")
        events = {}
        for e in p.get("notified_events") or []:
            parts = str(e).split("|")
            if len(parts) == 3 and parts[0] and parts[1]:
                events["|".join(parts[:2])] = parts[2]
        last = notified.split("::")
        if len(last) == 4 and last[3].count("|") == 2:
            parts = last[3].split("|")
            events.setdefault("|".join(parts[:2]), parts[2])
        acted = bool(p.get("actionable"))
        # Phase 19 で一般販売を通知していない商品は、次に一般販売で行動できるようになったら通知する（arm 済み）。
        # 抽選などだけを通知した・行動できる抽選の受付中なら、一般販売の側は使っていない
        direct_used = (len(last) == 4 and not last[3]) or (acted and p.get("availability") == act.IN_STOCK)
        armed = "" if direct_used else f"legacy:{p.get('availability') or 'UNKNOWN'}"
        out["products"][str(pid)] = {"availability": str(p.get("availability") or ""), "actionable": acted,
                                     "armed_by": armed, "arm_used": bool(direct_used), "arm_seq": 0,
                                     "known_events": events, "current_key": ""}
    return out


def load(path: Path) -> tuple[dict, bool]:
    """(store, baseline)。無い・壊れている・形が違うときは空の store と baseline=True（候補を出さない）。"""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_store(), True
    s = migrate(raw)
    return (s, False) if s is not None else (empty_store(), True)


def dumps(store: dict) -> str:
    return json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def file_sha(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def save(path: Path, store: dict) -> bool:
    """内容が変わったときだけ atomic に書く（時刻だけの書き換えをしない）。書いたら True。"""
    from src.utils.atomic_write import write_text_atomic
    text = dumps(store)
    try:
        if Path(path).read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    write_text_atomic(path, text)
    return True


@contextlib.contextmanager
def locked(path: Path):
    """同じ台帳を同時に読み書きしない（同じ機械の上の排他。CI の実行どうしは workflow の concurrency が並べる）。"""
    import fcntl
    lock = Path(tempfile.gettempdir()) / f"pm_outbox_{hashlib.sha256(str(Path(path).resolve()).encode()).hexdigest()[:16]}.lock"
    with open(lock, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ── 候補 → outbox ─────────────────────────────────────────────────────────

def _live_known(known, now: datetime) -> dict:
    """通知しない受付（基準日より前から受付中だった・すでに記録を作った）。方式に依らない消えない印で、締切から
    RETENTION_DAYS を過ぎたら消す（最大50件。形の崩れた値・締切の読めない値は捨てる）。"""
    out = {}
    for k, dl in (known or {}).items() if isinstance(known, dict) else []:
        parts = str(k).split("|")
        d = act._dt(dl) if dl else None
        if len(parts) == 2 and all(parts) and d is not None and d + timedelta(days=RETENTION_DAYS) > now:
            out[str(k)] = str(dl)
    return dict(list(out.items())[-50:])


def _mark_event(st: dict, ident: str, deadline: str) -> None:
    """受付を「通知しない」に入れる（締切は新しいほう。延長されても同じ受付として残す）。"""
    old = act._dt(st["known_events"].get(ident)) if st["known_events"].get(ident) else None
    new = act._dt(deadline) if deadline else None
    if new is not None and (old is None or new > old):
        st["known_events"][ident] = str(deadline)
    elif ident not in st["known_events"] and deadline:
        st["known_events"][ident] = str(deadline)


def _record(r: dict, key: str, mode: str, *, kind: str, ident: str, transition: str, channels: list,
            now: datetime) -> dict:
    nid = notification_id(key, mode)
    rec = {"notification_id": nid, "idempotency_key": key, "mode": mode, "notification_type": an.TYPE,
           "product_id": str(r["product_id"]), "product": str(r.get("product") or r["product_id"]),
           "availability_kind": str(r.get("availability") or ""), "kind": kind, "event_id": ident,
           "state_transition": transition, "created_at": _iso(now), "updated_at": _iso(now), "status": PENDING,
           "channels": {ch: {"status": PENDING, "attempts": [], "attempt_count": 0, "next_attempt_at": "",
                             "provider_delivery_id": "", "error_class": ""} for ch in channels}}
    rec.update(_fields(r))
    rec["message"] = an.message(rec | {"availability": rec["availability_kind"]})
    return rec


def _fields(r: dict) -> dict:
    """最新の診断の行の値（利益・ROI・URL・締切・期限）。計算し直さない。"""
    return {"net_profit": r.get("net_profit"), "roi": r.get("roi"), "confirmed": r.get("confirmed") is True,
            "deadline": str(r.get("deadline") or ""), "checked_at": str(r.get("checked_at") or ""),
            "until_ms": r.get("until_ms"), "cta_label": str(r.get("cta_label") or ""),
            "action_url": str(r.get("cta_url") or ""), "reasons": list(r.get("reasons") or [])}


def observe(store: dict, rows: list, *, now: datetime, mode: str, baseline: bool = False,
            channels: list | None = None) -> dict:
    """診断の行で台帳を進め、行動できない → できる になった候補を outbox に PENDING で入れる。件数を返す。

    - 通常販売のキーは arm（行動できないと確かめた観測）。在庫切れ・販売終了で新しい arm になる（re-arm）。
      在庫未確認・更新待ちでは re-arm しない。初めて見た商品は、行動できない観測で arm になる
    - 抽選・予約・先着のキーは受付の識別。同じ受付は一度だけ（一般販売と行き来しても）
    - 前回を見ていない商品（台帳が無い・新しい・利益から外れていた）が行動できる → 記録だけ（基準日）
    - 行が1件も無い実行では台帳を変えない
    """
    from src.notifiers.routing import get_channels_for_alert
    chans = list(channels or get_channels_for_alert(an.RANK))
    prods, recs = store["products"], store["records"]
    stats = {"notification_candidates": 0, "dedupe_suppressed": 0, "baseline_recorded": 0, "revived": 0,
             "new_outbox": []}
    seen = set()
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("product_id"):
            continue
        pid, avail, ok = str(r["product_id"]), str(r.get("availability") or ""), bool(r.get("actionable"))
        seen.add(pid)
        prev = prods.get(pid)
        unobserved = baseline or prev is None or prev.get("availability") in ("", NOT_CONFIRMED)
        st = {"availability": avail, "actionable": ok, "armed_by": str((prev or {}).get("armed_by") or ""),
              "arm_used": bool((prev or {}).get("arm_used")), "arm_seq": int((prev or {}).get("arm_seq") or 0),
              "known_events": _live_known((prev or {}).get("known_events"), now), "current_key": ""}
        if not ok:
            if (avail in REARM_STATES and (not st["armed_by"] or st["arm_used"])) or \
                    (not st["armed_by"] and not st["arm_used"]):
                # 連番を付ける（同じ確認時刻の観測でも、re-arm のたびに別のキーになる）
                st["arm_seq"] += 1
                st["armed_by"] = f'{st["arm_seq"]}:{avail}@{r.get("checked_at") or _iso(now)}'
                st["arm_used"] = False
            prods[pid] = st
            continue
        ident = event_identity(r)
        if ident:
            kind, key = "event", idempotency_key(pid, "event", ident)
            known = ident in st["known_events"]
            # 抽選などの受付中は、一般販売では買えない状態 → 一般販売の arm（まだ無く、使ってもいないとき）
            if not st["armed_by"] and not st["arm_used"]:
                st["arm_seq"] += 1
                st["armed_by"] = f'{st["arm_seq"]}:{avail}@{r.get("checked_at") or _iso(now)}'

        else:
            kind = "direct"
            key = idempotency_key(pid, "direct", st["armed_by"]) if st["armed_by"] else ""
            known = False
        st["current_key"] = key
        if unobserved:
            # 基準日: 今の状態は通知しない（前から続いていた可能性がある）
            if ident:
                _mark_event(st, ident, str(r.get("deadline") or ""))
            else:
                # arm を使い切る（次の実行で同じ arm のキーを作らない。在庫切れ・販売終了で新しい arm になる）
                st["armed_by"], st["arm_used"], st["current_key"] = "", True, ""
            stats["baseline_recorded"] += 1
            prods[pid] = st
            continue
        nid = notification_id(key, mode) if key else ""
        old = recs.get(nid) if nid else None
        revivable = [c for c in (old["channels"].values() if old is not None else [])
                     if c["status"] in (EXPIRED, CANCELLED) and not _resolved_cancel(c)]
        if old is not None and old["status"] in (EXPIRED, CANCELLED) and revivable:
            # 送っていない（期限切れ・取り消し）記録の移り変わりが、また行動できる → 同じ記録（同じキー）で配信待ちに戻す。
            # 人が「送らない」と解決した配信先（cancel）は戻さない（届いていたかもしれない。レビュー H-1）
            for c in revivable:
                c.update(status=PENDING, error_class="", next_attempt_at="")
            old.update(_fields(r))
            old["message"] = an.message(old | {"availability": old["availability_kind"]})
            old["updated_at"] = _iso(now)
            old["status"] = _aggregate(old)
            stats["notification_candidates"] += 1
            stats["revived"] += 1
            stats["new_outbox"].append(nid)
            prods[pid] = st
            continue
        # すでに記録を作った変化は、方式（dry-run / 本番）に依らず作り直さない（消えない印: 通常販売は arm_used、
        # 抽選などは known_events）。記録が消えても（prune）同じキーで送り直さない・dry-run で計画した古い変化を本番に
        # 切り替えた時点で送らない（監査 H-3・M-1）
        used = st["arm_used"] if kind == "direct" else known
        if not key or used or nid in recs:
            stats["dedupe_suppressed"] += 1
            if kind == "event" and known:
                _mark_event(st, ident, str(r.get("deadline") or ""))     # 締切の延長を印にも反映する
            prods[pid] = st
            continue
        prev_av = str((prev or {}).get("availability") or "NONE")
        transition = (f"{prev_av}→{avail}" if kind == "event"
                      else f"{st['armed_by'].split('@')[0].split(':', 1)[-1]}→{avail}")
        recs[nid] = _record(r, key, mode, kind=kind, ident=ident, transition=transition, channels=chans, now=now)
        if kind == "direct":
            st["arm_used"] = True
        else:
            _mark_event(st, ident, str(r.get("deadline") or ""))
        stats["notification_candidates"] += 1
        stats["new_outbox"].append(nid)
        prods[pid] = st
    if seen:
        for pid, st in prods.items():
            if pid not in seen:
                prods[pid] = dict(st, availability=NOT_CONFIRMED, actionable=False, current_key="")
    return stats


# ── 配信の直前の確認 ───────────────────────────────────────────────────────

def _resolved_cancel(c: dict) -> bool:
    """人が届いたか不明を「送らない」（cancel）と解決した配信先か（自動で配信待ちに戻さない）。"""
    res = c.get("resolutions") or []
    return bool(res) and res[-1].get("resolution") == CANCEL


def _expired(rec: dict, now: datetime) -> bool:
    u = rec.get("until_ms")
    if isinstance(u, int) and u <= int(now.timestamp() * 1000):
        return True
    d = act._dt(rec.get("deadline")) if rec.get("deadline") else None
    return d is not None and d <= now


def _aggregate(rec: dict) -> str:
    ss = {c["status"] for c in rec["channels"].values()} or {CANCELLED}
    for s in (SENDING, PENDING, READY, FAILED_RETRYABLE, UNKNOWN_DELIVERY):
        if s in ss:
            return s
    for s in (DELIVERED, DRY_RUN_PLANNED, EXPIRED, CANCELLED, FAILED_FINAL):
        if s in ss:
            return s
    return CANCELLED


def _set(rec: dict, ch: str, status: str, now: datetime, **kw) -> None:
    """配信先の状態を変える（値が同じなら何もしない。時刻だけの書き換えをしない。監査 L-3）。"""
    c = rec["channels"][ch]
    if c["status"] == status and all(c.get(k) == v for k, v in kw.items()):
        return
    c["status"] = status
    c.update(kw)
    rec["updated_at"] = _iso(now)
    rec["status"] = _aggregate(rec)


def prepare(store: dict, rows: list, *, now: datetime, mode: str, attempt_id: str,
            adapters: dict | None = None) -> dict:
    """配信の直前の確認。期限切れ → EXPIRED、行動できない・利益が確定でない・URL が違う → CANCELLED、
    dry-run → DRY_RUN_PLANNED、本番で送信先がある → SENDING（attempt_id 付き。この状態を保存してから送る）。

    前の実行の SENDING（送った後に保存できなかった可能性がある）は UNKNOWN_DELIVERY にする（送り直さない）。
    """
    adapters = adapters if adapters is not None else ad.default_adapters()
    by_pid = {str(r["product_id"]): r for r in rows or [] if isinstance(r, dict) and r.get("product_id")}
    out = {"planned": 0, "sending": 0, "expired": 0, "cancelled": 0, "unknown": 0, "not_configured": 0,
           "final": 0}
    for rec in store["records"].values():
        stale = [ch for ch, c in rec["channels"].items() if c["status"] == SENDING and c.get("attempt_id") != attempt_id]
        for ch in stale:
            _set(rec, ch, UNKNOWN_DELIVERY, now, error_class="interrupted_after_send")
        out["unknown"] += 1 if stale else 0
        if rec["mode"] != mode:
            if rec["status"] in DUE:                         # 方式が変わった（dry-run の未配信を本番で送らない）
                for ch, c in rec["channels"].items():
                    if c["status"] in DUE:
                        _set(rec, ch, CANCELLED, now, error_class="mode_changed")
                out["cancelled"] += 1
            continue
        due = [ch for ch, c in rec["channels"].items() if c["status"] in DUE
               and (not c.get("next_attempt_at") or (act._dt(c["next_attempt_at"]) or now) <= now)]
        if not due:
            continue
        row = by_pid.get(rec["product_id"])
        p = store["products"].get(rec["product_id"]) or {}
        current = bool(row and row.get("actionable") and p.get("current_key") == rec["idempotency_key"])
        if current:
            rec.update(_fields(row))                         # 本文・期限は最新の確定の値（計算し直さない）
            rec["message"] = an.message(rec | {"availability": rec["availability_kind"]})
        cand = rec | {"availability": rec["availability_kind"], "cta_url": rec["action_url"]}
        why = an.revalidate_fields(cand, now) if current else ["not_current"]
        if why:
            status = EXPIRED if (_expired(rec, now) or "expired" in why or "deadline_invalid" in why) else CANCELLED
            for ch in due:
                _set(rec, ch, status, now, error_class=",".join(why)[:80])
            out["expired" if status == EXPIRED else "cancelled"] += 1
            continue
        done = set()
        for ch in due:
            c = rec["channels"][ch]
            if c.get("attempt_count", 0) >= MAX_ATTEMPTS:
                _set(rec, ch, FAILED_FINAL, now, error_class="max_attempts")
                done.add("final")
            elif mode == MODE_DRY:
                _set(rec, ch, DRY_RUN_PLANNED, now)
                done.add("planned")
            elif not (adapters.get(ch) and adapters[ch].configured):
                _set(rec, ch, PENDING, now, error_class="not_configured")
                done.add("not_configured")
            else:
                c["attempts"].append({"attempt_id": attempt_id, "attempted_at": _iso(now), "status": SENDING,
                                      "provider": ch, "provider_delivery_id": "", "error_class": ""})
                c["attempt_count"] = c.get("attempt_count", 0) + 1
                _set(rec, ch, SENDING, now, attempt_id=attempt_id, error_class="")
                done.add("sending")
        for k in done:                                       # 件数は通知ごと（配信先ごとではない）
            out[k] += 1
    return out


def send(store: dict, *, now: datetime, attempt_id: str, adapters: dict) -> dict:
    """この実行の SENDING の記録だけを、1回ずつ送る（再試行は次の実行の prepare が決める）。"""
    out = {"delivered": 0, "retryable": 0, "final": 0, "unknown": 0, "expired": 0, "cancelled": 0}
    for rec in store["records"].values():
        for ch, c in rec["channels"].items():
            if c["status"] != SENDING or c.get("attempt_id") != attempt_id:
                continue
            a = c["attempts"][-1] if c["attempts"] else {}
            adapter = adapters.get(ch)
            # 本文を作る直前にもう一度確かめる（SENDING を保存してから送るまでに期限・締切が過ぎたら送らない）
            why = an.revalidate_fields(rec | {"availability": rec["availability_kind"], "cta_url": rec["action_url"]}, now)
            if why:
                status = EXPIRED if (_expired(rec, now) or "expired" in why or "deadline_invalid" in why) else CANCELLED
                a.update(status=status, error_class=",".join(why)[:80])
                _set(rec, ch, status, now, error_class=",".join(why)[:80])
                out["expired" if status == EXPIRED else "cancelled"] += 1
                continue
            try:
                if adapter is None or not adapter.configured:
                    raise ad.ProviderError(ad.FINAL, "not_configured")
                did = adapter.send(rec, rec["idempotency_key"])
            except ad.ProviderError as e:
                a.update(status=e.kind, error_class=e.error_class)
                if e.kind == ad.AMBIGUOUS:
                    _set(rec, ch, UNKNOWN_DELIVERY, now, error_class=e.error_class)
                    out["unknown"] += 1
                elif e.kind == ad.RETRYABLE and c.get("attempt_count", 0) < MAX_ATTEMPTS:
                    wait = max(float(e.retry_after or 0), BACKOFF_SECONDS * 2 ** max(c["attempt_count"] - 1, 0))
                    wait = min(wait, ad.RETRY_AFTER_CAP_SECONDS)
                    _set(rec, ch, FAILED_RETRYABLE, now, error_class=e.error_class,
                         next_attempt_at=_iso(now + timedelta(seconds=wait)))
                    out["retryable"] += 1
                else:
                    _set(rec, ch, FAILED_FINAL, now, error_class=e.error_class)
                    out["final"] += 1
                continue
            a.update(status=DELIVERED, provider_delivery_id=did)
            _set(rec, ch, DELIVERED, now, provider_delivery_id=did, error_class="")
            out["delivered"] += 1
    return out


def prune(store: dict, now: datetime) -> int:
    """終わってから RETENTION_DAYS を過ぎた記録を消す（今の候補のキーの記録は消さない）。消した件数。"""
    current = {p.get("current_key") for p in store["products"].values() if p.get("current_key")}
    cut = now - timedelta(days=RETENTION_DAYS)
    drop = [nid for nid, r in store["records"].items() if r["status"] in TERMINAL
            and r["idempotency_key"] not in current and (act._dt(r.get("updated_at")) or now) < cut]
    for nid in drop:
        del store["records"][nid]
    return len(drop)


def counts(store: dict) -> dict:
    """outbox の記録の状態ごとの件数（運営者向け・集計）。"""
    c = {s: 0 for s in STATUSES}
    for r in store["records"].values():
        c[r["status"]] = c.get(r["status"], 0) + 1
    return {"outbox_pending": c[PENDING] + c[READY], "sending": c[SENDING], "dry_run_planned": c[DRY_RUN_PLANNED],
            "delivered": c[DELIVERED], "retryable_failed": c[FAILED_RETRYABLE], "final_failed": c[FAILED_FINAL],
            "expired": c[EXPIRED], "cancelled": c[CANCELLED], "ambiguous_delivery": c[UNKNOWN_DELIVERY],
            "records": len(store["records"])}


def cycle(store: dict, diagnostics: dict | None, *, now: datetime, mode: str, baseline: bool = False,
          attempt_id: str = "inline", adapters: dict | None = None, dispatch_now: datetime | None = None,
          channels: list | None = None) -> dict:
    """observe → prepare → send を続けて行う（メモリの上だけ。保存しない。テストと検査で使う）。

    本番は手順ごとに保存する（scripts/persist_notification_state.sh・dispatch-notifications）。
    """
    rows = ((diagnostics or {}).get("actionability") or {}).get("products") or []
    dnow = max(now, dispatch_now) if dispatch_now is not None else now
    obs = observe(store, rows, now=now, mode=mode, baseline=baseline, channels=channels)
    prep = prepare(store, rows, now=dnow, mode=mode, attempt_id=attempt_id, adapters=adapters)
    sent = send(store, now=dnow, attempt_id=attempt_id, adapters=adapters or {}) if mode == MODE_LIVE else {}
    return {"observe": obs, "prepare": prep, "send": sent, "counts": counts(store)}


# ── 手順ごとの実行（保存・報告。LP の生成と dispatch-notifications が使う） ────────────────────

STORE_NAME = "state.json"


def attempt_id_from_env(env=None, now: datetime | None = None) -> str:
    """この実行の識別（CI では run の ID と試行の回数。SENDING の記録をこの実行のものと見分ける）。"""
    import os
    e = env if env is not None else os.environ
    if e.get("GITHUB_RUN_ID"):
        return f'gh-{e["GITHUB_RUN_ID"]}-{e.get("GITHUB_RUN_ATTEMPT") or "1"}'
    import uuid
    return f'local-{(now or datetime.now()).strftime("%Y%m%dT%H%M%S")}-{uuid.uuid4().hex[:8]}'


def _rows(diagnostics: dict | None) -> list:
    return ((diagnostics or {}).get("actionability") or {}).get("products") or []


def _summaries(store: dict, ids) -> list:
    out = []
    for nid in ids:
        r = store["records"].get(nid)
        if r:
            out.append({"notification_id": nid, "product_id": r["product_id"], "product": r["product"],
                        "availability": r["availability_kind"], "status": an.TITLES.get(r["availability_kind"], ""),
                        "transition": r["state_transition"], "kind": r["kind"], "event_id": r["event_id"],
                        "outbox_status": r["status"], "net_profit": r.get("net_profit"), "roi": r.get("roi"),
                        "deadline": r.get("deadline"), "cta_label": r.get("cta_label"),
                        "action_url": r.get("action_url"), "confirmed": r.get("confirmed"),
                        "channels": sorted(r["channels"])})
    return out


def _write_report(out_dir: Path, report: dict, now: datetime) -> None:
    from src.utils.atomic_write import write_json_atomic
    write_json_atomic(out_dir / "latest.json", report)
    hist_path = out_dir / "history" / f"{now.strftime('%Y-%m-%d')}.json"
    try:
        hist = json.loads(hist_path.read_text(encoding="utf-8"))
        runs = hist.get("runs") if isinstance(hist, dict) and isinstance(hist.get("runs"), list) else []
    except (OSError, ValueError):
        runs = []
    runs.append({k: v for k, v in report.items() if k != "note"})
    write_json_atomic(hist_path, {"date": now.strftime("%Y-%m-%d"), "runs": runs[-50:]})


def run_observe(out_dir: Path, diagnostics: dict, *, now: datetime, dry_run: bool) -> dict:
    """LP の生成の中（診断の直後）: 候補を outbox に入れて保存する。配信はしない（次の手順）。"""
    out_dir = Path(out_dir)
    path = out_dir / STORE_NAME
    mode = MODE_DRY if dry_run else MODE_LIVE
    with locked(path):
        store, baseline = load(path)
        stats = observe(store, _rows(diagnostics), now=now, mode=mode, baseline=baseline)
        pruned = prune(store, now)
        save(path, store)
    from src.notifiers.routing import get_channels_for_alert
    report = {
        "generated_at": _iso(now), "step": "observe",
        "diagnostics_generated_at": str((diagnostics or {}).get("generated_at") or ""),
        "note": "内部用（運営者向け）。外部への送信はしない（dry-run）。配信先の URL・トークンは記録しない",
        "type": an.TYPE, "dry_run": dry_run, "is_baseline": baseline, "channels": get_channels_for_alert(an.RANK),
        "newly_actionable": len(((diagnostics or {}).get("actionability") or {}).get("newly_actionable") or []),
        "notification_candidates": stats["notification_candidates"], "dedupe_suppressed": stats["dedupe_suppressed"],
        "baseline_recorded": stats["baseline_recorded"], "pruned": pruned,
        "dispatch_planned": 0, "dispatch_sent": 0, "dispatch_failed": 0, "dispatch_blocked": 0,
        "dispatch_unknown": 0, "dispatch_not_configured": 0, "external_calls": 0,
        "candidates": _summaries(store, stats["new_outbox"]), "counts": counts(store),
        "unknown": list_unknown(store)}
    _write_report(out_dir, report, now)
    return report


def _load_report(out_dir: Path) -> dict:
    try:
        r = json.loads((Path(out_dir) / "latest.json").read_text(encoding="utf-8"))
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


def run_prepare(out_dir: Path, diagnostics: dict, *, now: datetime, dry_run: bool, attempt_id: str,
                adapters: dict | None = None) -> dict:
    """配信の直前の確認（dry-run は DRY_RUN_PLANNED・本番は SENDING）。保存してから次の手順（send）に進む。"""
    out_dir = Path(out_dir)
    path = out_dir / STORE_NAME
    mode = MODE_DRY if dry_run else MODE_LIVE
    rep = _load_report(out_dir)
    # 今回の生成の候補の記録（observe）と同じ診断でなければ確かめ直さない（生成に失敗した実行・古い診断で送らない）
    dg = str((diagnostics or {}).get("generated_at") or "")
    if rep.get("failed") or rep.get("step") != "observe" or not dg or rep.get("diagnostics_generated_at") != dg:
        return {"step": "prepare", "skipped": "diagnostics_not_current"}
    with locked(path):
        store, baseline = load(path)
        if baseline:
            return {"step": "prepare", "skipped": "no_store"}
        st = prepare(store, _rows(diagnostics), now=now, mode=mode, attempt_id=attempt_id, adapters=adapters)
        save(path, store)
    rep.update({"step": "prepare", "prepared_at": _iso(now), "attempt_id": attempt_id, "dry_run": dry_run,
                "dispatch_planned": st["planned"], "dispatch_blocked": st["expired"] + st["cancelled"],
                "dispatch_expired": st["expired"], "dispatch_cancelled": st["cancelled"],
                "dispatch_unknown": st["unknown"], "dispatch_not_configured": st["not_configured"],
                "dispatch_sending": st["sending"], "counts": counts(store), "unknown": list_unknown(store),
                "candidates": _summaries(store, [c["notification_id"] for c in rep.get("candidates") or []
                                                 if isinstance(c, dict) and c.get("notification_id")])})
    _write_report(out_dir, rep, now)
    return rep


def run_send(out_dir: Path, *, now: datetime, dry_run: bool, attempt_id: str, persisted_sha: str,
             adapters: dict, real_send_allowed: bool = False) -> dict:
    """SENDING を保存した内容（persisted_sha）と今のファイルが同じときだけ送る（保存より前に送らない）。

    real_send_allowed: 本番の送信の最終の関門（adapters.real_send_gate）を通ったか。既定は閉じている（送らない）。
    """
    out_dir = Path(out_dir)
    path = out_dir / STORE_NAME
    if dry_run:
        return {"step": "send", "skipped": "dry_run", "external_calls": 0}
    if not real_send_allowed:
        return {"step": "send", "skipped": "real_send_disabled", "external_calls": 0}
    with locked(path):
        if not persisted_sha or file_sha(path) != persisted_sha:
            return {"step": "send", "skipped": "not_persisted", "external_calls": 0}
        store, baseline = load(path)
        if baseline:
            return {"step": "send", "skipped": "no_store", "external_calls": 0}
        st = send(store, now=now, attempt_id=attempt_id, adapters=adapters)
        save(path, store)
    rep = _load_report(out_dir)
    rep.update({"step": "send", "sent_at": _iso(now), "dispatch_sent": st["delivered"],
                "dispatch_failed": st["retryable"] + st["final"], "dispatch_unknown": st["unknown"],
                "counts": counts(store), "unknown": list_unknown(store)})
    _write_report(out_dir, rep, now)
    return rep


# ── 届いたか不明（UNKNOWN_DELIVERY）の人による解決（Phase 21） ───────────────────────────────

MARK_DELIVERED = "delivered"            # 届いていた → DELIVERED（送り直さない）
MARK_NOT_DELIVERED = "not-delivered"    # 届いていなかった → 確かめ直して、出し直せる状態か期限切れ・取り消し
CANCEL = "cancel"                       # 送らない → CANCELLED
KEEP_UNKNOWN = "keep-unknown"           # まだ分からない → そのまま（記録だけ残す）
RESOLUTIONS = (MARK_DELIVERED, MARK_NOT_DELIVERED, CANCEL, KEEP_UNKNOWN)
RESOLVER_TYPE = "operator_cli"          # 解決した人の種類（個人名・メールは残さない）


def list_unknown(store: dict) -> list[dict]:
    """届いたか不明の配信（配信先ごと）。運営者の確認用（配信先の URL・トークンは含めない）。"""
    out = []
    for nid, r in sorted(store["records"].items(), key=lambda kv: kv[1].get("updated_at") or ""):
        for ch, c in r["channels"].items():
            if c["status"] != UNKNOWN_DELIVERY:
                continue
            last = c["attempts"][-1] if c.get("attempts") else {}
            out.append({"notification_id": nid, "product_id": r["product_id"], "product": r.get("product") or "",
                        "provider": ch, "attempted_at": last.get("attempted_at") or "", "state": c["status"],
                        "deadline": r.get("deadline") or "", "reason": c.get("error_class") or "",
                        "mode": r.get("mode") or "", "status_title": an.TITLES.get(r.get("availability_kind"), "")})
    return out


def resolve(store: dict, notification_id: str, resolution: str, *, rows: list, now: datetime,
            channel: str | None = None) -> dict:
    """届いたか不明の配信を、人の判断で解決する（冪等性のキー・記録はそのまま。新しい記録を作らない）。

    届いていなかった（not-delivered）ときは、最新の診断の行で確かめ直す: 今も同じキーで行動できて期限の内なら
    出し直せる状態（FAILED_RETRYABLE。次の実行の配信の直前の確認に回る）、期限切れなら EXPIRED、行動できない・
    利益が確定でないなら CANCELLED。試行の上限を過ぎていれば FAILED_FINAL。
    """
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution: {resolution}")
    rec = store["records"].get(notification_id)
    if rec is None:
        raise KeyError(notification_id)
    chans = [ch for ch, c in rec["channels"].items() if c["status"] == UNKNOWN_DELIVERY and (channel in (None, ch))]
    if not chans:
        raise LookupError("届いたか不明の配信がありません（解決できるのは UNKNOWN_DELIVERY だけ）")
    row = next((r for r in rows or [] if isinstance(r, dict) and str(r.get("product_id")) == rec["product_id"]), None)
    p = store["products"].get(rec["product_id"]) or {}
    result = {}
    for ch in chans:
        c = rec["channels"][ch]
        prev = c["status"]
        if resolution == MARK_DELIVERED:
            new, cls = DELIVERED, "resolved_delivered"
        elif resolution == CANCEL:
            new, cls = CANCELLED, "resolved_cancelled"
        elif resolution == KEEP_UNKNOWN:
            new, cls = UNKNOWN_DELIVERY, c.get("error_class") or ""
        else:
            current = bool(row and row.get("actionable") and p.get("current_key") == rec["idempotency_key"])
            fields = _fields(row) if current else {}
            cand = (rec | fields) | {"availability": rec["availability_kind"],
                                     "cta_url": fields.get("action_url", rec["action_url"])}
            why = an.revalidate_fields(cand, now) if current else ["not_current"]
            if why:
                new = EXPIRED if (_expired(rec | fields, now) or "expired" in why or "deadline_invalid" in why) \
                    else CANCELLED
                cls = "resolved_not_delivered:" + ",".join(why)[:60]
            elif c.get("attempt_count", 0) >= MAX_ATTEMPTS:
                new, cls = FAILED_FINAL, "resolved_not_delivered:max_attempts"
            else:
                rec.update(fields)
                rec["message"] = an.message(rec | {"availability": rec["availability_kind"]})
                new, cls = FAILED_RETRYABLE, "resolved_not_delivered"
        c.setdefault("resolutions", []).append({"resolved_at": _iso(now), "resolution": resolution,
                                                "resolver_type": RESOLVER_TYPE, "previous_status": prev,
                                                "result_status": new})
        if new == FAILED_RETRYABLE:
            _set(rec, ch, new, now, error_class=cls, next_attempt_at=_iso(now))
        elif new != prev:
            _set(rec, ch, new, now, error_class=cls)
        else:
            rec["updated_at"] = _iso(now)
        result[ch] = new
    return {"notification_id": notification_id, "resolution": resolution, "channels": result}


def main_ledger_matches(path: Path, repo_root: Path, *, fetch: bool = True) -> tuple[bool, str]:
    """手元の台帳が main の台帳と同じか（違えば書き換えない。別の実行の記録を上書きしない）。"""
    import subprocess
    p = Path(path)
    try:
        rel = p.resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return False, "台帳がリポジトリの中にありません"

    def git(*a):
        return subprocess.run(["git", *a], cwd=repo_root, capture_output=True, text=True, encoding="utf-8")
    if fetch and git("fetch", "-q", "origin", "main").returncode != 0:
        return False, "main を取得できません（ネットワーク・権限）"
    remote = git("rev-parse", "-q", "--verify", f"origin/main:{rel}").stdout.strip()
    local = git("hash-object", str(p)).stdout.strip() if p.exists() else ""
    if not remote or remote != local:
        return False, "手元の台帳が main の台帳と違います（git pull で合わせてから実行してください）"
    return True, ""
