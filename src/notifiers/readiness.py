"""Phase 24（実データの商品の通知の本番の受入）を始めてよいかの判定（Phase 25。検知・記録・見える化だけ）。

判定のロジックは新しく作らない:
- 行動できるか・利益・期限・公式のページは Phase 18 の正本（診断の行 = actionability.products）と Phase 19 の
  配信の直前の確認（actionable.revalidate_fields）
- 「行動できない → できる」の変化と、その同一性（冪等性のキー）は Phase 19〜23 の outbox の記録
- 候補の古さは Phase 23 の上限（outbox.LIVE_CANDIDATE_MAX_AGE_HOURS。最初に検知した時刻から。時刻を新しくしない）
- 優先の順は既存の順位（診断の行の並び。新しい順位の体系は作らない）

送信はしない（外部への通信 0）。変数・関門は変えない。判定できない（診断が無い・壊れている・台帳を合わせられない）ときは
REVIEW_REQUIRED（READY と推測しない）。秘密の値（トークン・チャット ID・webhook）は元から扱わない。冪等性のキーも出さない
（候補の ID はキーのハッシュ）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from src.market import actionability as act
from src.notifiers import actionable as an
from src.notifiers import outbox as ob

FILE_NAME = "phase24_readiness.json"

WAITING = "PHASE24_WAITING"
READY = "PHASE24_REAL_CANDIDATE_READY"
REVIEW_REQUIRED = "PHASE24_REVIEW_REQUIRED"
ACCEPTANCE_DONE = "PHASE24_ACCEPTANCE_DONE"     # 受入で商品の通知を送った（追加の送信は別の判断。READY にしない）
STATUSES = (WAITING, READY, REVIEW_REQUIRED, ACCEPTANCE_DONE)

# 今回の実行の検知の結果
NO_ACTIONABLE_CHANGE = "NO_ACTIONABLE_CHANGE"
NEW_ACTIONABLE_FOUND = "NEW_ACTIONABLE_FOUND"
ACTIONABLE_STILL_PRESENT = "ACTIONABLE_STILL_PRESENT"
ACTIONABLE_LOST = "ACTIONABLE_LOST"
DETECTION_FAILED = "DETECTION_FAILED"
ACCEPTANCE_COMPLETED = "ACCEPTANCE_COMPLETED"            # 受入で送った（候補が無くなったのではない）

# 候補の移り変わり（履歴）
C_READY = "READY"                      # 受入の候補（送ってよい条件を今も満たす）
C_EXPIRED = "EXPIRED"                  # 検知から24時間を過ぎた
C_INVALIDATED = "INVALIDATED"          # 行動できない・利益が確定でない・期限・締切・公式のページ・同一性が崩れた
C_DELIVERED = "DELIVERED"              # 受入で送った（Telegram に届いた）
C_CANCELLED = "CANCELLED"              # 人が送らないと決めた・送信の失敗で出し直さない
C_UNKNOWN = "UNKNOWN_DELIVERY"         # 送ったが届いたか不明（人の解決待ち。自動で送り直さない）

C_HELD = "HELD"                        # 受入は済んでいるので送らない（追加の送信は別の判断）
LABELS = {WAITING: "実データの候補待ち", READY: "Phase 24 の受入候補あり", REVIEW_REQUIRED: "判定できない（要確認）",
          ACCEPTANCE_DONE: "受入済み（追加の送信はしない）"}
C_LABELS = {C_READY: "受入候補", C_EXPIRED: "期限切れ（検知から24時間）", C_INVALIDATED: "無効（行動できなくなった）",
            C_DELIVERED: "送信済み", C_CANCELLED: "取り消し", C_UNKNOWN: "届いたか不明（要解決）",
            C_HELD: "保留（受入は済んでいる）"}
HISTORY_MAX = 50


def rows_ok(diagnostics) -> bool:
    """診断に今すぐ行動の判定（actionability.products の list）があるか。無ければ判定できない（WAITING にしない）。"""
    a = (diagnostics or {}).get("actionability") if isinstance(diagnostics, dict) else None
    return isinstance(a, dict) and isinstance(a.get("products"), list)


def is_ready(d: dict | None) -> bool:
    """出力が READY として読めるか（READY かつ形の正しい候補が1件以上。壊れた READY は READY と扱わない。監査 L-2）。"""
    if not isinstance(d, dict) or d.get("status") != READY:
        return False
    cs = d.get("candidates")
    return isinstance(cs, list) and bool(cs) and all(isinstance(c, dict) and c.get("product_id") and c.get("candidate_id")
                                                     for c in cs)


def normalized(d: dict | None) -> dict:
    """表示用: 状態が知らない値・壊れた READY なら REVIEW_REQUIRED に落とす（READY と推測しない）。"""
    d = d if isinstance(d, dict) else {}
    if d.get("status") not in STATUSES or (d.get("status") == READY and not is_ready(d)):
        return failed(datetime.now(), "readiness_unavailable" if not d else "readiness_malformed", prev=d)
    return d


def candidate_id(key: str) -> str:
    """候補の ID（冪等性のキーのハッシュ。キーそのものは出さない）。"""
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:16]


def _product_records(store: dict) -> dict:
    """冪等性のキー → そのキーの商品の記録（dry-run・本番。接続の試験は除く）。"""
    by: dict = {}
    for r in store.get("records", {}).values():
        if isinstance(r, dict) and not r.get("is_canary") and r.get("notification_type") == an.TYPE \
                and r.get("idempotency_key"):
            by.setdefault(r["idempotency_key"], []).append(r)
    return by


def _detected_at(recs: list) -> datetime | None:
    """最初に検知した時刻（その変化の記録のうち最も古い created_at。新しくしない）。"""
    ds = [act._dt(r.get("created_at")) for r in recs if r.get("created_at")]
    ds = [d for d in ds if d is not None]
    return min(ds) if ds else None


def _terminal_state(recs: list) -> str:
    """本番の記録の終わった状態（送った・届いたか不明・取り消し）。無ければ空。"""
    live = [r for r in recs if r.get("mode") == ob.MODE_LIVE]
    st = {r.get("status") for r in live}
    if ob.DELIVERED in st:
        return C_DELIVERED
    if ob.UNKNOWN_DELIVERY in st or ob.SENDING in st:
        return C_UNKNOWN
    if ob.FAILED_FINAL in st:
        return C_CANCELLED
    if any(ob._resolved_cancel(c) for r in live for c in r.get("channels", {}).values()):
        return C_CANCELLED
    return ""


def _why_invalid(row: dict | None, prod: dict, key: str, now: datetime) -> list[str]:
    """候補が今も送ってよい条件を満たさない理由（Phase 19 の配信の直前の確認と同じ。空なら満たす）。"""
    if not row or not row.get("actionable"):
        return ["not_actionable"]
    if prod.get("current_key") != key:
        return ["not_current"]                       # 在庫切れなどを挟んだ（別の変化になった）
    f = ob._fields(row)
    return an.revalidate_fields(f | {"availability": str(row.get("availability") or ""),
                                     "cta_url": f["action_url"]}, now)


def evaluate(store: dict, rows: list, *, now: datetime, new_ids=(), prev: dict | None = None,
             diagnostics_generated_at: str = "") -> dict:
    """受入の状態・候補・履歴を返す（送信しない。台帳を変えない）。"""
    by_key = _product_records(store)
    order = {str(r["product_id"]): i for i, r in enumerate(rows or []) if isinstance(r, dict) and r.get("product_id")}
    by_pid = {str(r["product_id"]): r for r in rows or [] if isinstance(r, dict) and r.get("product_id")}
    prev_hist = {h.get("candidate_id"): h for h in ((prev or {}).get("history") or []) if isinstance(h, dict)}
    new_keys = {store["records"][n]["idempotency_key"] for n in new_ids or [] if n in store.get("records", {})}
    max_age = timedelta(hours=ob.LIVE_CANDIDATE_MAX_AGE_HOURS)
    cands, hist = [], []
    for key, recs in by_key.items():
        pid = str(recs[0].get("product_id") or "")
        det = _detected_at(recs)
        cid = candidate_id(key)
        term = _terminal_state(recs)
        why: list[str] = []
        if term:
            state = term
        elif det is None or det + max_age <= now:
            state = C_EXPIRED
        else:
            why = _why_invalid(by_pid.get(pid), store.get("products", {}).get(pid) or {}, key, now)
            if not why and not ob.handoff_ok(store, key, now):
                why = ["outbox_not_creatable"]           # 本番の方式の記録を安全に作れない（受入で送れない）
            state = C_INVALIDATED if why else C_READY
        latest = max(recs, key=lambda r: str(r.get("updated_at") or ""))
        row = by_pid.get(pid) or {}
        src = row if state == C_READY else latest
        avail = str((src.get("availability") if state == C_READY else latest.get("availability_kind")) or "")
        item = {"candidate_id": cid, "product_id": pid, "product": str(latest.get("product") or pid),
                "net_profit": src.get("net_profit"), "roi": src.get("roi"), "availability": avail,
                "type": an.TITLES.get(avail, ""), "state_label": act.LABELS.get(avail, ""),
                "checked_at": str(src.get("checked_at") or ""), "deadline": str(src.get("deadline") or ""),
                "action_url": str((row.get("cta_url") if state == C_READY else latest.get("action_url")) or ""),
                "detected_at": det.isoformat(timespec="seconds") if det else "",
                "age_hours": round((now - det).total_seconds() / 3600, 1) if det else None,
                "lifecycle": state, "reason": ",".join(why)[:80], "rank": order.get(pid)}
        old = prev_hist.get(cid) or {}
        # 状態が変わったときだけ時刻を進める（毎回の実行で時刻だけを新しくしない）
        changed = old.get("changed_at") if old.get("lifecycle") == state and old.get("changed_at") else \
            now.isoformat(timespec="seconds")
        hist.append({k: item[k] for k in ("candidate_id", "product_id", "product", "type", "detected_at", "lifecycle",
                                          "reason")} | {"changed_at": changed})
        if state == C_READY:
            cands.append(item | {"new_this_run": key in new_keys})
    cands.sort(key=lambda c: (c["rank"] if c["rank"] is not None else 10 ** 6, c["detected_at"]))
    for i, c in enumerate(cands):
        c["priority"] = i + 1                         # 既存の順位（診断の行の並び）での順番
    states = {h["lifecycle"] for h in hist}
    error = ""
    if C_UNKNOWN in states:
        # 受入の送信が届いたか不明（人の解決が要る）: 次の受入を始めない（2通目を送らない）
        status, error, cands = REVIEW_REQUIRED, "unknown_delivery_needs_resolution", []
    elif C_DELIVERED in states:
        # 受入で1件送った（Phase 24 は1件だけ）: 残りの候補は READY にしない（レビュー M-1）
        status, cands = ACCEPTANCE_DONE, []
    else:
        status = READY if cands else WAITING
    if status in (REVIEW_REQUIRED, ACCEPTANCE_DONE):
        for h in hist:
            if h["lifecycle"] == C_READY:
                h["lifecycle"] = C_HELD
                old = prev_hist.get(h["candidate_id"]) or {}
                h["changed_at"] = old.get("changed_at") if old.get("lifecycle") == C_HELD and old.get("changed_at") \
                    else now.isoformat(timespec="seconds")
    p = prev or {}
    prev_had = p.get("status") == READY or any(isinstance(h, dict) and h.get("lifecycle") == C_READY
                                               for h in p.get("history") or [])
    if status == ACCEPTANCE_DONE:
        detection = ACCEPTANCE_COMPLETED
    elif any(c["new_this_run"] for c in cands):
        detection = NEW_ACTIONABLE_FOUND
    elif cands:
        detection = ACTIONABLE_STILL_PRESENT
    elif prev_had:
        detection = ACTIONABLE_LOST
    else:
        detection = NO_ACTIONABLE_CHANGE
    hist.sort(key=lambda h: (h["detected_at"], h["candidate_id"]), reverse=True)
    from src.notifiers import adapters as ad
    return {"status": status, "label": LABELS[status], "detection": detection, "generated_at": now.isoformat(timespec="seconds"),
            "error": error, "run_id": _run_id(),
            "diagnostics_generated_at": diagnostics_generated_at,
            "actionable": sum(1 for r in rows or [] if isinstance(r, dict) and r.get("actionable")),
            "candidate_count": len(cands), "candidate_ids": [c["candidate_id"] for c in cands],
            "candidates": cands, "top_candidate": cands[0]["candidate_id"] if cands else "",
            "send_limit": ad.PRODUCT_SEND_LIMIT_PER_RUN, "external_sends": 0,
            "history": hist[:HISTORY_MAX],
            "note": "内部用（運営者向け）。検知と記録だけ（送信しない）。受入は手動の手順で行う（ops/Secrets設定.md）"}


def _run_id() -> str:
    import os
    return str(os.environ.get("GITHUB_RUN_ID") or "")


def failed(now: datetime, error: str, *, prev: dict | None = None, diagnostics_generated_at: str = "") -> dict:
    """判定できない（REVIEW_REQUIRED）。READY と推測しない。前回の履歴は残す（時刻は変えない）。"""
    return {"status": REVIEW_REQUIRED, "label": LABELS[REVIEW_REQUIRED], "detection": DETECTION_FAILED,
            "error": str(error)[:80], "generated_at": now.isoformat(timespec="seconds"), "run_id": _run_id(),
            "diagnostics_generated_at": diagnostics_generated_at, "actionable": None, "candidate_count": 0,
            "candidate_ids": [], "candidates": [], "top_candidate": "", "send_limit": 1, "external_sends": 0,
            "history": list(((prev or {}).get("history") or []))[:HISTORY_MAX],
            "note": "内部用（運営者向け）。今回は判定できなかった（送信しない）"}


def load(out_dir: Path) -> dict:
    try:
        d = json.loads((Path(out_dir) / FILE_NAME).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write(out_dir: Path, data: dict) -> None:
    from src.utils.atomic_write import write_json_atomic
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    write_json_atomic(Path(out_dir) / FILE_NAME, data)


def refresh(store: dict, diagnostics: dict | None, report: dict | None, *, now: datetime, attempt_id: str,
            prev: dict | None) -> dict:
    """送信の手順の後に、今の台帳で受入の状態を確かめ直す（CI の Summary の手順。監査 M-1）。

    今回の生成の報告（latest.json）が今回の診断のものでなければ判定できない（前回の出力を今回のものとして出さない）。
    今回の run で商品の通知を送った（送ろうとした）ら、追加の手動の実行をしないように示す。送信はしない。
    """
    rep = report if isinstance(report, dict) else {}
    dg = str((diagnostics or {}).get("generated_at") or "")
    # CI では今回の run の生成の報告でなければ判定できない（チェックアウトに残った前回の出力を今回のものにしない。レビュー M-2）
    if rep.get("failed") or not dg or rep.get("diagnostics_generated_at") != dg or not rows_ok(diagnostics) \
            or (_run_id() and str(rep.get("run_id") or "") != _run_id()):
        return failed(now, "not_current_run", prev=prev, diagnostics_generated_at=dg)
    rows = ((diagnostics or {}).get("actionability") or {}).get("products") or []
    d = evaluate(store, rows, now=now, prev=prev, diagnostics_generated_at=dg)
    p = prev if isinstance(prev, dict) else {}
    if p.get("diagnostics_generated_at") == dg and p.get("status") == d["status"] and p.get("detection"):
        d["detection"] = p["detection"]                       # 同じ実行の observe の検知の結果を保つ
    sent = ob.product_sends_in_run(store, attempt_id, exclude_attempt=False) if attempt_id else 0
    d["sent_this_run"] = sent
    if sent:
        d["note"] = ("この実行で商品の通知を送った（送ろうとした）。追加の手動の実行はしない。変数を安全な値に戻す"
                     "（ops/Secrets設定.md）")
    return d


def summary_lines(d: dict) -> list[str]:
    """CI の出力・GitHub Actions の Summary 用（値・キーは出さない）。"""
    lines = [f"Phase24 readiness: {d.get('status') or REVIEW_REQUIRED}（{LABELS.get(d.get('status'), LABELS[REVIEW_REQUIRED])}）",
             f"generated_at: {d.get('generated_at') or '不明'}",
             f"detection: {d.get('detection') or DETECTION_FAILED}",
             f"actionable: {d.get('actionable') if d.get('actionable') is not None else '不明'}",
             f"candidates: {int(d.get('candidate_count') or 0)}（Phase 24 の受入で送るのは最大 {d.get('send_limit') or 1} 件）",
             "external sends: 0（この判定は送信しない）"]
    if d.get("sent_this_run"):
        lines.insert(1, f"この実行で商品の通知を送った（{d['sent_this_run']}件）。追加の手動の実行はしない・変数を安全な値に戻す")
    for c in d.get("candidates") or []:
        lines.append(f"  #{c.get('priority')} {c.get('product')}・{c.get('type')}・検知 {c.get('detected_at')}"
                     f"（{c.get('age_hours')}時間前）")
    return lines
