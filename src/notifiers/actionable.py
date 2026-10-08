"""今すぐ行動できるようになった利益商品の通知（Phase 19。通知の種類 ACTIONABLE_NOW）。

既存の通知エンジン（scripts/generate_notifications.py の種類・優先度・配信先の構造、src/notifiers/routing の配信先）に
1つの種類として足す。判定はしない: 「今すぐ行動できるか」は src/market/actionability（Phase 18 の正本）が決め、
その結果（exports/opportunity_diagnostics の actionability.products）を読むだけ。利益も再計算しない。

- 候補: 行動できない → 行動できる に変わった商品だけ（同じ状態では毎回出さない）
- 重複の抑制: 商品・種類・状態・抽選などの受付（商品コードと受付期間）の組み合わせ（dedupe_key）。最後に通知した組み合わせと
  同じなら出さない。在庫切れ・受付終了など「できない」と確かめた状態になったら再び通知できる（re-arm）。
  在庫未確認・更新待ち（確認できなかった）では re-arm しない（取得の失敗のたびに同じ通知を繰り返さない）
- 配信の直前にもう一度確かめる（期限・締切・公式の購入/申込のページ・確定の利益）
- 外部への送信はしない（dry-run）。送信の関数（sender）は今は渡していない。dry-run を外しても sender が無ければ送らない
"""
from __future__ import annotations

import os
import math
from datetime import datetime

from src.market import actionability as act

TYPE = "ACTIONABLE_NOW"
PRIORITY = "Critical"            # 確定の利益 + 今すぐ行動できる（既存の WATCH_TO_BUY と同じ優先度）
RANK = "S"                       # 配信先は既存のランクの表（routing.RANK_CHANNELS）の S と同じ
TITLES = {act.IN_STOCK: "購入可能になりました", act.LOTTERY_OPEN: "抽選受付が始まりました",
          act.PREORDER_OPEN: "予約受付が始まりました", act.FIRST_COME_OPEN: "先着販売が始まりました"}
# re-arm（もう一度通知できるようにする）のは、通常販売で行動できないと確かめた状態だけ。抽選・予約・先着の受付終了では
# 消さない（ページの表示の揺れで同じ受付を2回通知しない。別の受付は受付の識別が変わるので通知する。レビュー M-2）
REARM_STATES = frozenset({act.OUT_OF_STOCK, act.SALE_ENDED})
# 送信の失敗で再試行するもの（タイムアウト・429・5xx）
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3

PLANNED = "dry_run_planned"      # dry-run で配信を計画した（送っていない）
SENT = "sent"
FAILED = "failed"
BLOCKED = "revalidation_failed"  # 配信の直前の確認で止めた
NOT_CONFIGURED = "not_configured"  # dry-run ではないが送信先が無い（送らない）
DELIVERED = frozenset({PLANNED, SENT})   # 通知済みとして記録する（次の実行で同じものを出さない）
# 確定の利益から外れた商品の台帳の状態（状態の変化を見ていないので、戻ってきたときは商品ごとの基準日として通知しない）
NOT_CONFIRMED = "NOT_CONFIRMED"


class SendError(Exception):
    """送信の失敗（status: HTTP の状態。タイムアウトは None）。"""

    def __init__(self, status: int | None = None, message: str = ""):
        super().__init__(message or f"status={status}")
        self.status = status

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status in RETRY_STATUSES


def is_dry_run(env=None) -> bool:
    """dry-run か（既定は dry-run。NOTIFICATION_DRY_RUN が "false" のときだけ外れる）。"""
    v = str((env if env is not None else os.environ).get("NOTIFICATION_DRY_RUN", "true")).strip().lower()
    return v not in ("false", "0", "no", "off")


def event_identity(row: dict) -> str:
    """抽選・予約・先着の受付の識別（商品コードと受付期間）。通常販売は空。"""
    return str(row.get("event_key") or "") if row.get("availability") in (
        act.LOTTERY_OPEN, act.PREORDER_OPEN, act.FIRST_COME_OPEN) else ""


def dedupe_key(row: dict) -> str:
    return "::".join((str(row.get("product_id") or ""), TYPE, str(row.get("availability") or ""), event_identity(row)))


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def message(c: dict) -> str:
    """通知の本文（値は診断の行のまま。利益を計算し直さない）。"""
    lines = [f"🎯 {TITLES.get(c['availability'], '')}", c.get("product") or c["product_id"]]
    if _finite(c.get("net_profit")):
        roi = f" / ROI {c['roi'] * 100:.1f}%" if _finite(c.get("roi")) else ""
        lines.append(f"想定純利益 +¥{int(c['net_profit']):,}{roi}（確定の利益案件）")
    if c.get("deadline"):
        d = act._dt(c["deadline"])
        if d is not None:
            lines.append("締切 " + d.strftime("%m/%d" if act.is_date_only(c["deadline"]) else "%m/%d %H:%M"))
    ck = act._dt(c.get("checked_at")) if c.get("checked_at") else None
    if ck is not None:
        lines.append(f"{ck.strftime('%m/%d %H:%M')} 公式で確認")
    lines.append(f"{c.get('cta_label') or ''}: {c.get('cta_url') or ''}")
    return "\n".join(lines)


def _events_of(prev: dict) -> list:
    """台帳の通知できた受付。前の形式（notified_events が無い）なら、通知済みの組み合わせの受付の部分から作る（監査 L-2）。"""
    ev = prev.get("notified_events")
    if isinstance(ev, list):
        return ev
    last = str(prev.get("notified_key") or "").split("::")
    return [last[3]] if len(last) == 4 and last[3] else []


def _live_events(events, now: datetime) -> list[str]:
    """通知できた受付の識別のうち、締切（識別の最後の部分）を読めて、まだ過ぎていないもの（最大20件。形の崩れた値は捨てる）。"""
    out = []
    for e in events if isinstance(events, list) else []:
        parts = str(e).split("|")
        end = act._dt(parts[-1]) if len(parts) == 3 and parts[0] and parts[-1] else None
        if end is not None and end > now:
            out.append(str(e))
    return out[-20:]


def detect(rows: list, ledger: dict | None, *, now: datetime) -> tuple[list[dict], list[dict], dict]:
    """候補・抑制した候補・次の台帳を返す。ledger が None（台帳が無い）なら基準日（候補を出さず、今の状態を記録する）。

    前回の状態を見ていない商品（台帳に無い・前回は確定の利益から外れていた）は、商品ごとの基準日として記録だけする
    （利益だけが変わって在庫ありのままの商品を「購入可能になりました」と通知しない。監査 M-1）。
    """
    prev_all = dict(ledger or {})
    nxt = {k: dict(v) for k, v in prev_all.items() if isinstance(v, dict)}
    cands, suppressed = [], []
    seen = set()
    baselined: list[str] = []
    for r in rows or []:
        if not isinstance(r, dict) or not r.get("product_id"):
            continue
        pid, avail = str(r["product_id"]), str(r.get("availability") or "")
        seen.add(pid)
        prev = nxt.get(pid, {})
        unobserved = not prev or prev.get("availability") in ("", NOT_CONFIRMED)
        st = {"availability": avail, "actionable": bool(r.get("actionable")), "event_id": event_identity(r),
              "notified_key": prev.get("notified_key", ""), "notified_at": prev.get("notified_at", ""),
              # 通知できた抽選・予約・先着の受付（締切を過ぎたものは消す）。一般販売と行き来しても同じ受付を2回出さない
              "notified_events": _live_events(_events_of(prev), now)}
        if not r.get("actionable"):
            if avail in REARM_STATES:
                st["notified_key"], st["notified_at"] = "", ""          # できないと確かめた → もう一度通知できる
            nxt[pid] = st
            continue
        key = dedupe_key(r)
        if unobserved:                                                 # 台帳が無い（基準日）ときも、すべてここに入る
            st["notified_key"] = key                                   # 基準日: 今の状態は通知しない
            if st["event_id"] and st["event_id"] not in st["notified_events"]:
                st["notified_events"] = st["notified_events"] + [st["event_id"]]   # 基準日より前からの受付（監査 L-1）
            baselined.append(pid)
            nxt[pid] = st
            continue
        # 抑制するのは、最後に通知できた組み合わせと同じとき（通常販売のできる → できる）と、通知できた受付（抽選・予約・先着）
        # と同じ受付のとき（一般販売と行き来しても、表示が予約などに変わっても同じ受付は2回出さない。レビュー L-2・H-1）。
        # 配信が失敗・止めたものは通知済みに入らないので出し直す（監査 M-1）。抽選から一般販売（在庫あり）に変わったら
        # 新しい買い方として通知する（監査 L-1）
        # 同じ受付のときは notified_key を書き換えない（最後に通知できた一般販売の組み合わせを残し、抽選と在庫ありの行き来で
        # 「購入可能になりました」を繰り返さない。監査 M-1）
        seen_event = bool(st["event_id"]) and st["event_id"] in st["notified_events"]
        if prev.get("notified_key") == key or seen_event:
            suppressed.append({"product_id": pid, "dedupe_key": key, "availability": avail})
            nxt[pid] = st
            continue
        cands.append({
            "type": TYPE, "priority": PRIORITY, "product_id": pid, "product": str(r.get("product") or pid),
            "availability": avail, "status": TITLES.get(avail, ""),
            "transition": f"{prev.get('availability') or 'NONE'}→{avail}",
            "net_profit": r.get("net_profit"), "roi": r.get("roi"), "confirmed": bool(r.get("confirmed")),
            "deadline": r.get("deadline") or "", "checked_at": r.get("checked_at") or "",
            "until_ms": r.get("until_ms"), "cta_label": r.get("cta_label") or "", "cta_url": r.get("cta_url") or "",
            "event_id": event_identity(r), "reasons": list(r.get("reasons") or []),
            "dedupe_key": key, "generated_at": now.isoformat(timespec="seconds")})
        nxt[pid] = st
    # 確定の利益から外れた（状態の変化を見ていない）。ただし行が1件も無い実行（利益ルートの一時的な欠けなど）では
    # 台帳を変えない（1回の欠けで全商品を基準日に戻して、その間の在庫の再開を取りこぼさないように。レビュー L-1）
    if seen:
        for pid, st in nxt.items():
            if pid not in seen:
                nxt[pid] = dict(st, availability=NOT_CONFIRMED, actionable=False)
    for c in cands:
        c["message"] = message(c)
    # 前回の状態を見ていないため記録だけした（通知しなかった）行動できる商品（運営者が取りこぼしに気付けるように）
    suppressed.extend({"product_id": pid, "dedupe_key": "", "availability": "", "baseline": True} for pid in baselined)
    return cands, suppressed, nxt


def revalidate(c: dict, now: datetime) -> list[str]:
    """配信の直前の確認（行動できない理由。空なら配信してよい）。生成から配信までに期限が過ぎたものを送らない。"""
    why = []
    if c.get("availability") not in act.ACTIONABLE_TYPES:
        why.append("not_actionable")
    if c.get("reasons"):
        why.append("has_reasons")
    if not (c.get("confirmed") is True and _finite(c.get("net_profit")) and c["net_profit"] > 0):
        why.append("profit_not_confirmed")
    now_ms = int(now.timestamp() * 1000)
    if not isinstance(c.get("until_ms"), int) or c["until_ms"] <= now_ms:
        why.append("expired")
    if c.get("availability") != act.IN_STOCK:
        d = act._dt(c.get("deadline")) if c.get("deadline") else None
        if d is None or d <= now:
            why.append("deadline_invalid")
    if not act._official_url(c.get("cta_url") or ""):
        why.append("url_not_official")
    if c.get("dedupe_key") != dedupe_key(c | {"event_key": c.get("event_id")}):
        why.append("dedupe_key_mismatch")
    return why


def dispatch(cands: list[dict], *, now: datetime, dry_run: bool = True, sender=None,
             max_attempts: int = MAX_ATTEMPTS) -> list[dict]:
    """配信（dry-run では送らずに計画だけ）。sender(candidate, idempotency_key) は送信の関数（今は渡していない）。"""
    out = []
    for c in cands:
        r = {"product_id": c["product_id"], "dedupe_key": c["dedupe_key"], "event_id": c.get("event_id") or "",
             "attempts": 0, "error": ""}
        why = revalidate(c, now)
        if why:
            r.update(status=BLOCKED, error=",".join(why))
        elif dry_run:
            r["status"] = PLANNED
        elif sender is None:
            r["status"] = NOT_CONFIGURED
        else:
            r["status"] = FAILED
            for i in range(max_attempts):
                r["attempts"] = i + 1
                try:
                    sender(c, c["dedupe_key"])     # 同じ通知の再試行は同じ識別子で送る（受け側で重ねない）
                except SendError as e:
                    r["error"] = f"status={e.status}" if e.status else "timeout"
                    if not e.retryable:
                        break
                    continue
                r.update(status=SENT, error="")
                break
        out.append(r)
    return out


def apply_results(ledger: dict, results: list[dict], now: datetime) -> dict:
    """配信の結果を台帳に記録する（計画・送信できたものだけ通知済み。失敗・止めたものは次の実行で出し直せる）。"""
    nxt = {k: dict(v) for k, v in ledger.items()}
    for r in results:
        if r.get("status") in DELIVERED and r["product_id"] in nxt:
            st = nxt[r["product_id"]]
            st.update(notified_key=r["dedupe_key"], notified_at=now.isoformat(timespec="seconds"))
            if r.get("event_id") and r["event_id"] not in (st.get("notified_events") or []):
                st["notified_events"] = list(st.get("notified_events") or []) + [r["event_id"]]
    return nxt


def run(diagnostics: dict | None, ledger: dict | None, *, now: datetime, dry_run: bool = True,
        sender=None, dispatch_now: datetime | None = None) -> tuple[dict, dict]:
    """診断の行から、候補・抑制・配信の計画を作る。(報告, 次の台帳) を返す。

    dispatch_now: 配信の直前の確認に使う時刻（生成を始めた時刻より後。監査 L-3）。無ければ now。
    """
    dnow = max(now, dispatch_now) if dispatch_now is not None else now
    from src.notifiers.routing import get_channels_for_alert
    rows = ((diagnostics or {}).get("actionability") or {}).get("products") or []
    cands, suppressed, nxt = detect(rows, ledger, now=now)
    channels = get_channels_for_alert(RANK)
    for c in cands:
        c["channels"] = channels
    results = dispatch(cands, now=dnow, dry_run=dry_run, sender=sender)
    by = {r["dedupe_key"]: r for r in results}
    for c in cands:
        c["dispatch_status"] = by[c["dedupe_key"]]["status"]
        c["dispatch_error"] = by[c["dedupe_key"]]["error"]
        c["dry_run"] = dry_run
    nxt = apply_results(nxt, results, dnow)
    count = {s: sum(1 for r in results if r["status"] == s) for s in (PLANNED, SENT, FAILED, BLOCKED, NOT_CONFIGURED)}
    report = {
        "generated_at": now.isoformat(timespec="seconds"),
        "dispatched_at": dnow.isoformat(timespec="seconds"),
        # どの診断から作ったか（読む側が、前回の出力を今回のものと取り違えないため。監査 L-4）
        "diagnostics_generated_at": str((diagnostics or {}).get("generated_at") or ""),
        "note": "内部用（運営者向け）。外部への送信はしない（dry-run）。配信先の URL・トークンは記録しない",
        "type": TYPE, "dry_run": dry_run, "is_baseline": ledger is None, "channels": channels,
        # 診断（前回の診断との比較）の「行動できるようになった」商品の数と、台帳で重複を除いた通知の候補の数
        "newly_actionable": len(((diagnostics or {}).get("actionability") or {}).get("newly_actionable") or []),
        "notification_candidates": len(cands),
        "dedupe_suppressed": sum(1 for x in suppressed if not x.get("baseline")),
        "baseline_recorded": sum(1 for x in suppressed if x.get("baseline")), "dispatch_planned": count[PLANNED], "dispatch_sent": count[SENT],
        "dispatch_failed": count[FAILED], "dispatch_blocked": count[BLOCKED],
        "dispatch_not_configured": count[NOT_CONFIGURED],
        "candidates": cands, "suppressed": suppressed,
    }
    return report, nxt
