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
LIVE_CANDIDATE_MAX_AGE_HOURS = 24      # 本番の方式の候補を送ってよい、候補にしてからの時間（古い「になりました」を送らない）
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


ADOPTABLE_DRY = frozenset({PENDING, READY, DRY_RUN_PLANNED})   # 本番が引き継げる dry-run の記録（送っていない・取り消していない）


def adoptable_dry(store: dict, key: str, now: datetime) -> dict | None:
    """本番の実行が引き継げる dry-run の記録（定時の実行で検知した変化。Phase 25）。

    検知（記録を作った時刻）から LIVE_CANDIDATE_MAX_AGE_HOURS 以内で、送っていない・取り消していないものだけ。
    それより古い変化は引き継がない（何日も前の「行動できるようになった」を送らない。Phase 20 の監査 M-1 の意図）。
    """
    d = store["records"].get(notification_id(key, MODE_DRY)) if key else None
    if not d or d.get("is_canary") or d.get("status") not in ADOPTABLE_DRY:
        return None
    c = act._dt(d.get("created_at")) if d.get("created_at") else None
    return d if c is not None and c + timedelta(hours=LIVE_CANDIDATE_MAX_AGE_HOURS) > now else None


def _revivable(c: dict) -> bool:
    return c["status"] in (EXPIRED, CANCELLED) and not _resolved_cancel(c) and c.get("error_class") != "stale_candidate"


def handoff_ok(store: dict, key: str, now: datetime) -> bool:
    """この変化（キー）を本番の方式で送れる形にできるか（送っていない・届いたか不明でない・取り消していない）。

    本番の記録があれば配信待ちか戻せる状態、無ければ引き継げる dry-run の記録がある。Phase 25 の受入の判定と observe が使う。
    """
    live = store["records"].get(notification_id(key, MODE_LIVE)) if key else None
    if live is not None:
        # prepare が今回の実行で SENDING にできる配信先（再試行の時刻・回数の上限も同じ。レビュー L-3）
        return any((c["status"] in DUE and (not c.get("next_attempt_at") or (act._dt(c["next_attempt_at"]) or now) <= now)
                    and int(c.get("attempt_count") or 0) < MAX_ATTEMPTS) or _revivable(c)
                   for c in live["channels"].values())
    return adoptable_dry(store, key, now) is not None


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
        # 古い候補（stale_candidate）・人が cancel した配信先は戻さない（新しい移り変わりで送る）
        revivable = [c for c in (old["channels"].values() if old is not None else []) if _revivable(c)]
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
        dry_src = adoptable_dry(store, key, now) if (mode == MODE_LIVE and key and used and nid not in recs) else None
        if dry_src is not None:
            # 定時の実行（dry-run）で検知した変化を、24時間以内なら本番の実行が引き継ぐ（Phase 25。Phase 24 の受入）。
            # 検知の時刻（created_at）は dry-run の記録のまま（古さを新しくしない）。同じキーの本番の記録は1件だけ
            rec = _record(r, key, mode, kind=kind, ident=ident, transition=dry_src["state_transition"], channels=chans,
                          now=now)
            rec["created_at"] = dry_src["created_at"]
            rec["adopted_from"] = dry_src["notification_id"]
            recs[nid] = rec
            if kind == "event":
                _mark_event(st, ident, str(r.get("deadline") or ""))
            stats["notification_candidates"] += 1
            stats["adopted"] = stats.get("adopted", 0) + 1
            stats.setdefault("adopted_ids", []).append(nid)          # 受入状態では新しい検知に数えない（監査 L-3）
            stats["new_outbox"].append(nid)
            prods[pid] = st
            continue
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


def run_key(attempt_id: str) -> str:
    """実行（workflow の run）の識別。CI の attempt_id（gh-<run>-<attempt>）は再実行（Re-run）でも同じ run にまとめる。"""
    parts = str(attempt_id or "").split("-")
    return "-".join(parts[:2]) if len(parts) == 3 and parts[0] == "gh" else str(attempt_id or "")


def product_sends_in_run(store: dict, attempt_id: str, *, exclude_attempt: bool = True) -> int:
    """同じ run（再実行を含む）で、商品の通知を送った（送ろうとした）回数。送っていない（NOT_SENT）は数えない。"""
    rk, n = run_key(attempt_id), 0
    for rec in store["records"].values():
        if rec.get("is_canary") or rec.get("mode") != MODE_LIVE:
            continue
        for c in rec["channels"].values():
            for a in c.get("attempts") or []:
                aid = str(a.get("attempt_id") or "")
                if run_key(aid) == rk and a.get("status") != "NOT_SENT" and not (exclude_attempt and aid == attempt_id):
                    n += 1
    return n


def _stale_live(rec: dict, now: datetime) -> bool:
    """本番の方式の候補が、候補にしてから LIVE_CANDIDATE_MAX_AGE_HOURS を過ぎたか（遅れた「になりました」を送らない）。"""
    if rec.get("mode") != MODE_LIVE or rec.get("is_canary"):
        return False
    c = act._dt(rec.get("created_at")) if rec.get("created_at") else None
    return c is None or c + timedelta(hours=LIVE_CANDIDATE_MAX_AGE_HOURS) <= now


def prepare(store: dict, rows: list, *, now: datetime, mode: str, attempt_id: str,
            adapters: dict | None = None, live_channels=None, send_limit: int | None = None,
            only_keys=None) -> dict:
    """配信の直前の確認。期限切れ → EXPIRED、行動できない・利益が確定でない・URL が違う → CANCELLED、
    dry-run → DRY_RUN_PLANNED、本番で送信先がある → SENDING（attempt_id 付き。この状態を保存してから送る）。

    前の実行の SENDING（送った後に保存できなかった可能性がある）は UNKNOWN_DELIVERY にする（送り直さない）。

    Phase 23（商品の通知の限定運用）:
    - live_channels: 本番の方式で送れる配信先（Secrets を持たない手順が使う。None なら adapters の設定で決める）
    - send_limit: この実行で SENDING にする記録の上限（限定モードは1件）。選ぶ順は既存の順位（診断の行の並び =
      行動できる商品が先・利益商品の順位）。上限を超えた候補は READY（limited_send_hold）のまま次の実行に回す
    - dry-run の実行では本番の方式の記録を送らない（SENDING にしない・取り消さない）。期限切れ・行動できない
      ものだけを整理する（次の本番の実行で確かめ直して送る）
    - only_keys: 本番の方式で SENDING にしてよい冪等性のキー（Phase 26 の受入で選んだ候補だけ）。ほかは READY
      （acceptance_not_selected）のまま送らない。None は制限なし（受入の関門を使わない呼び出し）
    """
    adapters = adapters if adapters is not None else ad.default_adapters()
    by_pid = {str(r["product_id"]): r for r in rows or [] if isinstance(r, dict) and r.get("product_id")}
    rank = {pid: i for i, pid in enumerate(by_pid)}            # 既存の順位（新しい順位の体系は作らない）
    out = {"planned": 0, "sending": 0, "expired": 0, "cancelled": 0, "unknown": 0, "not_configured": 0,
           "final": 0, "held": 0}
    eligible = []                                             # 本番の方式で送ってよい（上限で選ぶ）
    # 上限は run ごと（同じ run の再実行で送った分を引く。レビュー M-1）
    limit_left = None if send_limit is None else max(send_limit - product_sends_in_run(store, attempt_id), 0)
    for rec in store["records"].values():
        stale = [ch for ch, c in rec["channels"].items() if c["status"] == SENDING and c.get("attempt_id") != attempt_id]
        for ch in stale:
            _set(rec, ch, UNKNOWN_DELIVERY, now, error_class="interrupted_after_send")
        out["unknown"] += 1 if stale else 0
        if rec.get("is_canary"):                             # 接続の試験は商品の配信の直前の確認に回さない
            continue
        live_held = rec["mode"] == MODE_LIVE and mode == MODE_DRY   # 本番の記録を dry-run の実行で見る（送らない）
        if rec["mode"] != mode and not live_held:
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
        if not why and _stale_live(rec, now):
            why = ["stale_candidate"]                        # 古い候補（レビュー L-2）: 期限切れにして送らない
        if why:
            status = EXPIRED if (_expired(rec, now) or "expired" in why or "deadline_invalid" in why
                                 or "stale_candidate" in why) else CANCELLED
            for ch in due:
                _set(rec, ch, status, now, error_class=",".join(why)[:80])
            out["expired" if status == EXPIRED else "cancelled"] += 1
            continue
        if live_held:
            continue                                         # 今も送ってよい: 次の本番の実行まで PENDING / READY のまま
        if mode == MODE_LIVE and send_limit is not None:
            eligible.append((rank.get(rec["product_id"], len(rank)), rec["created_at"], rec, due))
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
            elif not ((ch in live_channels) if live_channels is not None
                      else (adapters.get(ch) and adapters[ch].configured)):
                _set(rec, ch, PENDING, now, error_class="not_configured")
                done.add("not_configured")
            elif only_keys is not None and rec["idempotency_key"] not in only_keys:
                _set(rec, ch, READY, now, error_class="acceptance_not_selected")   # 受入で選んでいない（監査 L-2）
                done.add("held")
            else:
                c["attempts"].append({"attempt_id": attempt_id, "attempted_at": _iso(now), "status": SENDING,
                                      "provider": ch, "provider_delivery_id": "", "error_class": ""})
                c["attempt_count"] = c.get("attempt_count", 0) + 1
                _set(rec, ch, SENDING, now, attempt_id=attempt_id, error_class="")
                done.add("sending")
        for k in done:                                       # 件数は通知ごと（配信先ごとではない）
            out[k] += 1
    if eligible:
        eligible.sort(key=lambda x: (x[0], x[1]))
        picked = 0
        for _r, _c, rec, due in eligible:
            done = set()
            for ch in due:
                c = rec["channels"][ch]
                ready = (ch in live_channels) if live_channels is not None else bool(
                    adapters.get(ch) and adapters[ch].configured)
                if c.get("attempt_count", 0) >= MAX_ATTEMPTS:
                    _set(rec, ch, FAILED_FINAL, now, error_class="max_attempts")
                    done.add("final")
                elif not ready:
                    _set(rec, ch, PENDING, now, error_class="not_configured")
                    done.add("not_configured")
                elif only_keys is not None and rec["idempotency_key"] not in only_keys:
                    _set(rec, ch, READY, now, error_class="acceptance_not_selected")   # 受入で選んでいない（送らない）
                    done.add("held")
                elif picked >= limit_left:
                    _set(rec, ch, READY, now, error_class="limited_send_hold")    # 次の実行に回す（送らない）
                    done.add("held")
                else:
                    c["attempts"].append({"attempt_id": attempt_id, "attempted_at": _iso(now), "status": SENDING,
                                          "provider": ch, "provider_delivery_id": "", "error_class": ""})
                    c["attempt_count"] = c.get("attempt_count", 0) + 1
                    _set(rec, ch, SENDING, now, attempt_id=attempt_id, error_class="")
                    done.add("sending")
            if "sending" in done:
                picked += 1                                  # 上限は通知の件数（1件 = 1回の送信の要求）
            for k in done:
                out[k] += 1
    return out


def send(store: dict, *, now: datetime, attempt_id: str, adapters: dict, only_ids=None,
         limit: int | None = None, allowed_keys=None) -> dict:
    """この実行の SENDING の記録だけを、1回ずつ送る（再試行は次の実行の prepare が決める）。

    only_ids: 送る記録の notification_id を限る（接続の試験は自分の記録だけ。監査 M-1）。requests は実際に送った数。
    limit: この実行で送る商品の通知の上限（限定モードは1件）。上限に達した後の SENDING は送らずに READY に戻す
      （送っていないことが確かなので、届いたか不明にしない）。接続の試験は数えない
    """
    out = {"delivered": 0, "retryable": 0, "final": 0, "unknown": 0, "expired": 0, "cancelled": 0, "requests": 0,
           "held": 0}
    # 上限は run ごと（同じ run の再実行で送った分を数える。レビュー M-1）
    product_requests = product_sends_in_run(store, attempt_id) if limit is not None else 0
    for nid_, rec in store["records"].items():
        if only_ids is not None and nid_ not in only_ids:
            continue
        for ch, c in rec["channels"].items():
            if c["status"] != SENDING or c.get("attempt_id") != attempt_id:
                continue
            a = c["attempts"][-1] if c["attempts"] else {}
            if allowed_keys is not None and not rec.get("is_canary") and rec["idempotency_key"] not in allowed_keys:
                _unsend(rec, ch, c, now, "acceptance_not_selected")          # 受入で選んでいない（Phase 26）
                out["held"] += 1
                continue
            if limit is not None and not rec.get("is_canary") and product_requests >= limit:
                _unsend(rec, ch, c, now, "limited_send_hold")
                out["held"] += 1
                continue
            adapter = adapters.get(ch)
            # 本文を作る直前にもう一度確かめる（SENDING を保存してから送るまでに期限・締切が過ぎたら送らない）
            why = [] if rec.get("is_canary") else an.revalidate_fields(
                rec | {"availability": rec["availability_kind"], "cta_url": rec["action_url"]}, now)
            if not why and _stale_live(rec, now):
                why = ["stale_candidate"]                    # 送る直前にも候補の古さ（24時間）を確かめる（監査 L-3）
            if why:
                status = EXPIRED if (_expired(rec, now) or "expired" in why or "deadline_invalid" in why
                                     or "stale_candidate" in why) else CANCELLED
                a.update(status=status, error_class=",".join(why)[:80])
                _set(rec, ch, status, now, error_class=",".join(why)[:80])
                out["expired" if status == EXPIRED else "cancelled"] += 1
                continue
            try:
                if adapter is None or not adapter.configured:
                    raise ad.ProviderError(ad.FINAL, "not_configured")
                calls0 = getattr(adapter, "calls", 0)
                try:
                    did = adapter.send(rec, rec["idempotency_key"])
                finally:
                    made = getattr(adapter, "calls", calls0) - calls0              # 実際に transport を呼んだ数
                    out["requests"] += made
                    if not rec.get("is_canary"):
                        product_requests += max(made, 1)             # 送ろうとした記録は上限に数える（安全側）
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
            a.update(status=DELIVERED, provider_delivery_id=did, delivered_at=_iso(now))
            _set(rec, ch, DELIVERED, now, provider_delivery_id=did, error_class="", delivered_at=_iso(now))
            out["delivered"] += 1
    return out


def _unsend(rec: dict, ch: str, c: dict, now: datetime, why: str) -> None:
    """この実行で SENDING にしたが送っていない（送信の要求をしていないと確かな）配信先を READY に戻す。"""
    if c["attempts"] and c["attempts"][-1].get("status") == SENDING:
        c["attempts"][-1].update(status="NOT_SENT", error_class=why)
    c["attempt_count"] = max(int(c.get("attempt_count") or 0) - 1, 0)   # 送っていないので試行に数えない
    _set(rec, ch, READY, now, error_class=why)


def release_unsent(store: dict, *, now: datetime, attempt_id: str, why: str) -> int:
    """送信の手順が送らないと決めた（関門が閉じた・dry-run）とき、この実行の商品の SENDING を READY に戻す。件数。

    送信の要求をする前なので、届いたか不明（UNKNOWN_DELIVERY）にしない（次の実行の prepare が誤って不明にしない）。
    """
    n = 0
    for rec in store["records"].values():
        if rec.get("is_canary"):
            continue
        for ch, c in rec["channels"].items():
            if c["status"] == SENDING and c.get("attempt_id") == attempt_id:
                _unsend(rec, ch, c, now, why)
                n += 1
    return n


def prune(store: dict, now: datetime) -> int:
    """終わってから RETENTION_DAYS を過ぎた記録を消す（今の候補のキーの記録は消さない）。消した件数。"""
    current = {p.get("current_key") for p in store["products"].values() if p.get("current_key")}
    cut = now - timedelta(days=RETENTION_DAYS)
    # 本番の商品の送信済み・届いたか不明の記録は消さない（受入を使った証拠。消えると受入の関門が外れる。Phase 26）
    drop = [nid for nid, r in store["records"].items() if r["status"] in TERMINAL and not r.get("is_canary")
            and not (r.get("mode") == MODE_LIVE and (r["status"] in (DELIVERED, UNKNOWN_DELIVERY)
                                                     or any(_resolved_cancel(c) for c in r["channels"].values())))
            and r["idempotency_key"] not in current and (act._dt(r.get("updated_at")) or now) < cut]
    for nid in drop:
        del store["records"][nid]
    return len(drop)


def counts(store: dict) -> dict:
    """outbox の記録の状態ごとの件数（運営者向け・集計）。"""
    c = {s: 0 for s in STATUSES}
    for r in store["records"].values():
        if r.get("is_canary"):                               # 接続の試験は商品の通知の件数に入れない
            continue
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


LIVE_CHANNELS = ("telegram",)          # 本番の方式の商品の通知の配信先（Phase 23: Telegram だけ。Discord は無効）
# 受入の関門（Phase 26）を外す明示の値（関門の外の流れだけを確かめるテスト・検査が使う。CLI は使わない）。既定（None）は閉じる
NO_ACCEPTANCE_GATE = "NO_ACCEPTANCE_GATE"


def run_observe(out_dir: Path, diagnostics: dict, *, now: datetime, dry_run: bool) -> dict:
    """LP の生成の中（診断の直後）: 候補を outbox に入れて保存する。配信はしない（次の手順）。

    本番の方式（dry_run=False。商品の通知の関門の意図 = adapters.product_live_intent）の記録の配信先は Telegram だけ。
    """
    out_dir = Path(out_dir)
    path = out_dir / STORE_NAME
    mode = MODE_DRY if dry_run else MODE_LIVE
    with locked(path):
        store, baseline = load(path)
        stats = observe(store, _rows(diagnostics), now=now, mode=mode, baseline=baseline,
                        channels=None if dry_run else list(LIVE_CHANNELS))
        pruned = prune(store, now)
        save(path, store)
    # Phase 24 の受入の状態（Phase 25。検知・記録だけ。送らない・台帳を変えない）
    from src.notifiers import readiness as _rd
    try:
        if not _rd.rows_ok(diagnostics):
            raise ValueError("no_actionability")                     # 診断に判定が無い（監査 L-1）
        if baseline:
            raise ValueError("no_store")                             # 台帳が無い・読めなかった（レビュー L-4）
        new_ids = [n for n in stats["new_outbox"] if n not in set(stats.get("adopted_ids") or [])]
        ready = _rd.evaluate(store, _rows(diagnostics), now=now, new_ids=new_ids, prev=_rd.load(out_dir),
                             diagnostics_generated_at=str((diagnostics or {}).get("generated_at") or ""))
    except Exception as exc:  # noqa: BLE001
        # 判定できない（READY と推測しない）。理由は例外の中身（no_store・no_actionability など。レビュー L-3）
        ready = _rd.failed(now, (str(exc) if isinstance(exc, ValueError) else "") or type(exc).__name__,
                           prev=_rd.load(out_dir))
    _rd.write(out_dir, ready)
    from src.notifiers.routing import get_channels_for_alert
    report = {
        "generated_at": _iso(now), "step": "observe",
        "diagnostics_generated_at": str((diagnostics or {}).get("generated_at") or ""),
        "note": ("内部用（運営者向け）。外部への送信はしない（dry-run）。配信先の URL・トークンは記録しない" if dry_run else
                 "内部用（運営者向け）。商品の通知の限定運用（Telegram だけ・1回の実行で最大1件）。配信先の URL・トークンは記録しない"),
        "type": an.TYPE, "dry_run": dry_run, "is_baseline": baseline, "channels": get_channels_for_alert(an.RANK),
        "newly_actionable": len(((diagnostics or {}).get("actionability") or {}).get("newly_actionable") or []),
        "notification_candidates": stats["notification_candidates"], "dedupe_suppressed": stats["dedupe_suppressed"],
        "baseline_recorded": stats["baseline_recorded"], "pruned": pruned,
        "dispatch_planned": 0, "dispatch_sent": 0, "dispatch_failed": 0, "dispatch_blocked": 0,
        "dispatch_unknown": 0, "dispatch_not_configured": 0, "external_calls": 0,
        "candidates": _summaries(store, stats["new_outbox"]), "counts": counts(store),
        "unknown": list_unknown(store), "provider_status": _load_provider_status(out_dir),
        "delivered_history": delivered_history(store, 20), "phase24_readiness": ready,
        "run_id": str(__import__("os").environ.get("GITHUB_RUN_ID") or "")}
    _write_report(out_dir, report, now)
    return report


def _load_provider_status(out_dir: Path) -> dict:
    """前回の送信の手順が書いた配信先の状態（値は含まない）。"""
    try:
        d = json.loads((Path(out_dir) / "provider_status.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _load_report(out_dir: Path) -> dict:
    try:
        r = json.loads((Path(out_dir) / "latest.json").read_text(encoding="utf-8"))
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


def run_prepare(out_dir: Path, diagnostics: dict, *, now: datetime, dry_run: bool, attempt_id: str,
                adapters: dict | None = None, live_channels=None, send_limit: int | None = None,
                acceptance_env=None) -> dict:
    """配信の直前の確認（dry-run は DRY_RUN_PLANNED・本番は SENDING）。保存してから次の手順（send）に進む。

    acceptance_env: 本番の方式のとき、受入の関門（readiness.acceptance_gate。Phase 26）に使う環境。関門を通った候補の
    キーだけを SENDING にする（通らなければ何も送らない）。None（既定）は空の環境 = 関門は閉じる（監査 L-1）。
    関門を外すのは NO_ACCEPTANCE_GATE を明示したときだけ。
    """
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
        acc = None
        only_keys = None
        if not dry_run and acceptance_env != NO_ACCEPTANCE_GATE:
            from src.notifiers import readiness as _rd
            acc = _rd.acceptance_gate(store, _rows(diagnostics), env=acceptance_env or {}, now=now,
                                      attempt_id=attempt_id, stage="prepare")
            only_keys = {acc["key"]} if acc["allowed"] else set()
        st = prepare(store, _rows(diagnostics), now=now, mode=mode, attempt_id=attempt_id, adapters=adapters,
                     live_channels=live_channels, send_limit=send_limit, only_keys=only_keys)
        save(path, store)
    rep.update({"step": "prepare", "prepared_at": _iso(now), "attempt_id": attempt_id, "dry_run": dry_run,
                "dispatch_planned": st["planned"], "dispatch_blocked": st["expired"] + st["cancelled"],
                "dispatch_expired": st["expired"], "dispatch_cancelled": st["cancelled"],
                "dispatch_unknown": st["unknown"], "dispatch_not_configured": st["not_configured"],
                "dispatch_sending": st["sending"], "dispatch_held": st["held"], "send_limit": send_limit,
                "acceptance": {k: v for k, v in (acc or {}).items() if k != "key"} or None,
                "counts": counts(store), "unknown": list_unknown(store),
                "candidates": _summaries(store, [c["notification_id"] for c in rep.get("candidates") or []
                                                 if isinstance(c, dict) and c.get("notification_id")])})
    _write_report(out_dir, rep, now)
    return rep


def _release(path: Path, now: datetime, attempt_id: str, why: str) -> int:
    """送らないと決めた実行の SENDING（商品）を READY に戻して保存する（送信の要求の前。届いたか不明にしない）。"""
    with locked(path):
        store, baseline = load(path)
        if baseline:
            return 0
        n = release_unsent(store, now=now, attempt_id=attempt_id, why=why)
        if n:
            save(path, store)
        return n


def run_send(out_dir: Path, *, now: datetime, dry_run: bool, attempt_id: str, persisted_sha: str,
             adapters: dict, real_send_allowed: bool = False, limit: int | None = None, acceptance_env=None) -> dict:
    """SENDING を保存した内容（persisted_sha）と今のファイルが同じときだけ送る（保存より前に送らない）。

    real_send_allowed: 本番の送信の最終の関門（adapters.real_send_gate）を通ったか。既定は閉じている（送らない）。
    limit: この実行で送る商品の通知の上限（限定モードは1件）。
    送らないとき（dry-run・関門が閉じた・保存と違う）は、この実行の SENDING を READY に戻す（送信の要求の前なので）。
    """
    out_dir = Path(out_dir)
    path = out_dir / STORE_NAME
    if dry_run:
        return {"step": "send", "skipped": "dry_run", "external_calls": 0,
                "released": _release(path, now, attempt_id, "send_dry_run")}
    if not real_send_allowed:
        return {"step": "send", "skipped": "real_send_disabled", "external_calls": 0,
                "released": _release(path, now, attempt_id, "send_gate_closed")}
    with locked(path):
        if not persisted_sha or file_sha(path) != persisted_sha:
            skipped = True
        else:
            skipped = False
            store, baseline = load(path)
            if baseline:
                return {"step": "send", "skipped": "no_store", "external_calls": 0}
            acc, allowed_keys = None, None
            if acceptance_env != NO_ACCEPTANCE_GATE:
                # 受入の関門（Phase 26）: この実行の SENDING が受入で選んだ候補だけで、受入をまだ使っていないときだけ送る
                # （None = 空の環境 = 閉じる。監査 L-1）
                from src.notifiers import readiness as _rd
                acc = _rd.acceptance_gate(store, [], env=acceptance_env or {}, now=now, attempt_id=attempt_id,
                                          stage="send")
                allowed_keys = {acc["key"]} if acc["allowed"] else set()
            st = send(store, now=now, attempt_id=attempt_id, adapters=adapters, limit=limit, allowed_keys=allowed_keys)
            save(path, store)
    if skipped:
        return {"step": "send", "skipped": "not_persisted", "external_calls": 0,
                "released": _release(path, now, attempt_id, "not_persisted")}
    rep = _load_report(out_dir)
    rep.update({"step": "send", "sent_at": _iso(now), "dispatch_sent": st["delivered"], "requests": st["requests"],
                "acceptance_send": {k: v for k, v in (acc or {}).items() if k != "key"} or None,
                "dispatch_held": st["held"], "send_limit": limit,
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
        elif rec.get("is_canary"):
            # 接続の試験は自動で出し直さない（試し直すときは新しい試験の ID を明示する）
            new, cls = CANCELLED, "resolved_not_delivered:canary_new_id_required"
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


# ── Telegram の接続の試験（canary。Phase 22） ─────────────────────────────────────────

CANARY_TEXT = ("[TEST] Premium Monitor\n"
               "Telegram通知の接続テストです。\n"
               "本番の商品通知ではありません。")
DEFAULT_CANARY_ID = "telegram_canary_v1"
_CANARY_ID = __import__("re").compile(r"^[a-z][a-z0-9_-]{0,39}$")


def valid_canary_id(canary_id: str, env=None) -> bool:
    """試験の ID の形（小文字の英字で始まり、英小文字・数字・_・- の40文字まで。チャット ID（数字・-・@ で始まる）を
    入れられない形）。台帳に入るので、配信先の設定の値を含むものも拒む（監査 L-A）。"""
    import os
    cid = str(canary_id or "")
    if not _CANARY_ID.match(cid):
        return False
    e = env if env is not None else os.environ
    return not any(len(v) >= 6 and v in cid for v in (str(e.get(k) or "").strip() for k in
                                                      ("TELEGRAM_CHAT_ID", "TELEGRAM_BOT_TOKEN")))


def canary_key(canary_id: str) -> str:
    return f"CANARY:telegram:{canary_id}"


def canary_record(store: dict, canary_id: str) -> dict | None:
    return store["records"].get(notification_id(canary_key(canary_id), MODE_LIVE))


def canary_status(store: dict, canary_id: str) -> str:
    """接続の試験の状態（NONE / その記録の状態）。"""
    rec = canary_record(store, canary_id)
    return rec["status"] if rec else "NONE"


def _new_canary(canary_id: str, now: datetime) -> dict:
    key = canary_key(canary_id)
    return {"notification_id": notification_id(key, MODE_LIVE), "idempotency_key": key, "mode": MODE_LIVE,
            "notification_type": "TELEGRAM_CANARY", "is_canary": True, "is_test_message": True,
            "canary_id": canary_id, "product_id": "", "product": "", "availability_kind": "", "kind": "canary",
            "event_id": "", "state_transition": "", "created_at": _iso(now), "updated_at": _iso(now),
            "status": PENDING, "message": CANARY_TEXT, "net_profit": None, "roi": None, "confirmed": False,
            "deadline": "", "checked_at": "", "until_ms": None, "cta_label": "", "action_url": "", "reasons": [],
            "channels": {"telegram": {"status": PENDING, "attempts": [], "attempt_count": 0, "next_attempt_at": "",
                                      "provider_delivery_id": "", "error_class": ""}}}


def run_canary(out_dir: Path, *, now: datetime, attempt_id: str, canary_id: str, adapter, persist) -> dict:
    """Telegram の接続の試験を1件だけ送る（同じ試験の ID では二度と送らない）。

    1) 台帳にこの試験の記録があれば送らない（届いた・不明・失敗のどれでも。出し直せる失敗（429 など）で期限が来たものだけ
       同じ記録で出し直す） 2) 記録を SENDING にして保存 3) persist()（main への保存。保存した台帳の sha を返す）が今の
       ファイルと同じでなければ送らずに戻す 4) 1回だけ送る 5) 結果を保存（次の手順の persist が main に残す）
    """
    out_dir = Path(out_dir)
    path = out_dir / STORE_NAME
    if not valid_canary_id(canary_id):
        return {"canary": "skipped", "reason": "invalid_canary_id", "requests": 0}
    with locked(path):
        store, baseline = load(path)
        if baseline:
            return {"canary": "skipped", "reason": "no_store", "requests": 0}
        rec = canary_record(store, canary_id)
        if rec is not None:
            ch = rec["channels"]["telegram"]
            due = ch["status"] == FAILED_RETRYABLE and (act._dt(ch.get("next_attempt_at")) or now) <= now
            if not due or ch.get("attempt_count", 0) >= MAX_ATTEMPTS:
                return {"canary": "skipped", "reason": f"already_{rec['status'].lower()}", "requests": 0,
                        "status": rec["status"]}
        before = json.loads(dumps(store))
        if rec is None:
            rec = _new_canary(canary_id, now)
            store["records"][rec["notification_id"]] = rec
        ch = rec["channels"]["telegram"]
        ch["attempts"].append({"attempt_id": attempt_id, "attempted_at": _iso(now), "status": SENDING,
                               "provider": "telegram", "provider_delivery_id": "", "error_class": ""})
        ch["attempt_count"] = ch.get("attempt_count", 0) + 1
        _set(rec, "telegram", SENDING, now, attempt_id=attempt_id, error_class="")
        save(path, store)
        sha = persist()                                     # 送る前に SENDING を main に保存する
        if not sha or sha != file_sha(path):
            # 送っていないので手元は元に戻す。保存（push）の途中で失敗したときは main に SENDING が残ることがあり、
            # その場合は次の実行で「届いたか不明」になる（送り直さない。人が解決する）
            save(path, before)
            return {"canary": "skipped", "reason": "not_persisted_or_unknown", "requests": 0}
        out = send(store, now=now, attempt_id=attempt_id, adapters={"telegram": adapter},
                   only_ids={rec["notification_id"]})
        save(path, store)
    st = rec["channels"]["telegram"]
    return {"canary": "sent", "requests": out["requests"], "status": rec["status"],
            "delivered": out.get("delivered", 0), "provider_delivery_id": st.get("provider_delivery_id") or "",
            "error_class": st.get("error_class") or ""}


def provider_status(store: dict, *, configured: bool, canary_gate: bool, canary_id: str) -> dict:
    """配信先の状態（運営者向け。値・トークン・チャット ID は含めない）。"""
    cs = canary_status(store, canary_id)
    if not configured:
        st = "NOT_CONFIGURED"
    elif cs == DELIVERED:
        st = "CANARY_DELIVERED"
    elif cs in (FAILED_FINAL, UNKNOWN_DELIVERY, CANCELLED):
        st = "ERROR"
    elif canary_gate or cs in (PENDING, SENDING, FAILED_RETRYABLE):
        st = "CANARY_PENDING"
    else:
        st = "READY"
    rec = canary_record(store, canary_id)
    ch = (rec or {}).get("channels", {}).get("telegram", {})
    return {"telegram": {"configured": configured, "status": st, "canary_id": canary_id, "canary_status": cs,
                         "last_delivery_status": ch.get("status") or "", "last_error_class": ch.get("error_class") or "",
                         "delivered_at": ch.get("delivered_at") or "",
                         "product_real_send": False}}


def _live_products(store: dict) -> list[dict]:
    return [r for r in store["records"].values() if not r.get("is_canary") and r.get("mode") == MODE_LIVE]


def product_status(store: dict, *, gate: dict, now: datetime, sent_this_run: int = 0) -> dict:
    """商品の通知（本番の方式）の状態（運営者向け。値・トークン・チャット ID・配信先の ID は含めない。Phase 23）。"""
    recs = _live_products(store)
    today = now.strftime("%Y-%m-%d")
    by = {s: sum(1 for r in recs if r["status"] == s) for s in STATUSES}
    return {"enabled": bool(gate.get("allowed")), "limited_mode": bool((gate.get("checks") or {}).get("limited_mode")),
            "send_limit": int(gate.get("send_limit") or ad.PRODUCT_SEND_LIMIT_PER_RUN),
            "sent_this_run": int(sent_this_run),
            "sent_today": sum(1 for r in recs for c in r["channels"].values()
                              if c.get("status") == DELIVERED and str(c.get("delivered_at") or "").startswith(today)),
            "pending": by[PENDING] + by[READY], "sending": by[SENDING], "delivered": by[DELIVERED],
            "unknown": by[UNKNOWN_DELIVERY], "failed": by[FAILED_RETRYABLE] + by[FAILED_FINAL],
            "expired": by[EXPIRED], "cancelled": by[CANCELLED]}


def delivered_history(store: dict, limit: int = 50) -> list[dict]:
    """実際に送った商品の通知（本番の方式・DELIVERED）の履歴。dry-run・配信待ち・接続の試験は入れない。

    利用者向け（マイページ）・運営者向けの履歴に使う。配信先の ID・冪等性のキー・URL は入れない（公開のページに出る）。
    """
    out = []
    for r in _live_products(store):
        at = max((str(c.get("delivered_at") or "") for c in r["channels"].values() if c.get("status") == DELIVERED),
                 default="")
        if r["status"] != DELIVERED or not at:
            continue
        out.append({"product_id": r["product_id"], "product": r["product"], "type": r["notification_type"],
                    "availability": r["availability_kind"], "state": an.TITLES.get(r["availability_kind"], ""),
                    "net_profit": r.get("net_profit"), "roi": r.get("roi"), "delivered_at": at})
    return sorted(out, key=lambda x: x["delivered_at"], reverse=True)[:limit]
