"""運営者向けの劣化アラート（PRODUCTION_HEALTH_ALERT）。商品の通知とは完全に別の仕組み。

目的: 収集が劣化しても Daily LP Update は「落ちなかった」だけで success になる（収集の step は continue-on-error）。
劣化が画面（管理画面・健康度）にしか出ず、誰かが開くまで気づけなかった（Production Integrity 監査 M-4）。
ここでは劣化を「運営者向けのアラート候補」として記録し、CI の注記・Step Summary・管理画面に出す。

分離の約束（deploy-check #869 が検査する）:
- 商品の通知（ACTIONABLE_NOW・Telegram・outbox・受入の関門）と一切つなげない。このモジュールは notifiers を import せず、
  顧客向けの候補を作らない（product_notification_candidates は常に 0）。Secrets・外部の送信先を使わない
- 外部へ送らない（external_sends は常に 0）。出すのは exports/ops/ の記録・CI の注記・Step Summary だけ
- 同じ異常は毎回出さない（状態 + 取得元 + 理由 = key で重複を抑える）。重くなったとき（WARNING → HIGH）だけ出し直す
- 復旧したら PRODUCTION_HEALTH_RECOVERED の記録を出す

どのアラートを出すか（key の種類）:
- required_source_failure   必須の店が3日以上連続で1件も取れない（既知のブロックは WARNING・予想外の理由は HIGH）
- new_source_failure        必須の店が今日から取れなくなった（HIGH。任意の店の失敗は想定内なので出さない）
- failure_rate              必須の店の行の失敗率が閾値以上（50% = WARNING・80% = HIGH）
- quality_gate_failure      誤りの可能性が高い価格の隔離・低信頼度の価格（商品ごと。WARNING）
- official_verification_expiry  公式の確認の期限が3日以内（WARNING）・切れた（HIGH）
- official_recheck_failing  公式の再確認が3日連続で失敗（WARNING）・7日連続（HIGH）
- collector_report_missing  取得レポートが無い（HIGH）
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
TYPE = "PRODUCTION_HEALTH_ALERT"
RECOVERED_TYPE = "PRODUCTION_HEALTH_RECOVERED"
SCHEMA = 1
WARNING, HIGH = "WARNING", "HIGH"
_RANK = {WARNING: 1, HIGH: 2}

CONSECUTIVE_DAYS = 3                    # 必須の店の連続失敗の日数
FAILURE_RATE_WARNING_PCT = 50.0
FAILURE_RATE_HIGH_PCT = 80.0
EXPIRY_WARNING_DAYS = 3                 # 公式の確認の期限が残りこの日数以内
RECHECK_FAILURE_WARNING_DAYS = 3
RECHECK_FAILURE_HIGH_DAYS = 7
# 既知のブロック・仕様（取得の作法を守った結果で、回避しない）。連続しても WARNING（degraded）。これ以外の理由は予想外（HIGH）
KNOWN_BLOCKED_REASONS = frozenset({
    "http_403", "http_401", "site_blocked", "robots_unreachable", "robots_disallowed", "rate_limited_429",
    "service_unavailable", "not_supported", "product_not_listed"})


def _alert(category: str, source: str, severity: str, reason: str, title: str, details: str, **evidence) -> dict:
    return {"key": f"{category}:{source}", "category": category, "source": source, "severity": severity,
            "reason": reason, "title": title, "details": details, "evidence": evidence}


def evaluate(inputs: dict, now: datetime) -> list[dict]:
    """今の劣化（アラートの一覧）。判定だけ（状態・出力は reconcile / run が行う）。

    inputs: collector（collector_report/latest.json）・failure_history（店 → 失敗した日の一覧）・official_status
    （official_registry.verification_status の行）・optional_shops（任意の店）・hard_reject_reasons
    """
    collector = inputs.get("collector") or {}
    history = inputs.get("failure_history") or {}
    optional = set(inputs.get("optional_shops") or ())
    hard = set(inputs.get("hard_reject_reasons") or ())
    out: list[dict] = []
    if not collector:
        return [_alert("collector_report_missing", "collector_report", HIGH, "report_not_generated",
                       "取得レポートがありません", "exports/collector_report/latest.json が無い・読めない")]

    by_shop = collector.get("by_shop") or {}
    reasons_by_shop: dict[str, set[str]] = {}
    for f in collector.get("fetch_failed") or []:
        if isinstance(f, dict) and f.get("shop"):
            reasons_by_shop.setdefault(f["shop"], set()).add(str(f.get("reason") or "unknown"))

    today = now.date()
    req_ok = req_failed = 0
    for shop, st in sorted(by_shop.items()):
        if not isinstance(st, dict):
            continue
        ok, failed = int(st.get("ok") or 0), int(st.get("failed") or 0)
        if shop in optional:
            continue                                         # 任意の店は不安定でも想定内（出さない）
        req_ok, req_failed = req_ok + ok, req_failed + failed
        if ok > 0 or failed == 0:
            continue
        days = _consecutive_days(history.get(shop) or [], today)
        reasons = sorted(reasons_by_shop.get(shop) or {"unknown"})
        unexpected = [r for r in reasons if r not in KNOWN_BLOCKED_REASONS]
        if days >= CONSECUTIVE_DAYS:
            out.append(_alert(
                "required_source_failure", shop, HIGH if unexpected else WARNING, ",".join(reasons),
                f"必須の店 {shop} が {days} 日連続で取得できません",
                f"理由: {', '.join(reasons)}（{'予想外の理由' if unexpected else '既知のブロック・仕様。回避せず人が確認する'}）",
                consecutive_days=days, reasons=reasons))
        else:
            out.append(_alert(
                "new_source_failure", shop, HIGH, ",".join(reasons),
                f"必須の店 {shop} が取得できなくなりました（{days}日目）", f"理由: {', '.join(reasons)}",
                consecutive_days=days, reasons=reasons))
    tried = req_ok + req_failed
    if tried:
        pct = req_failed / tried * 100
        if pct >= FAILURE_RATE_WARNING_PCT:
            out.append(_alert(
                "failure_rate", "required_shops", HIGH if pct >= FAILURE_RATE_HIGH_PCT else WARNING,
                f"{pct:.0f}%", f"必須の店の行の失敗率が {pct:.0f}% です",
                f"必須の店の行 {tried} 件のうち {req_failed} 件が取れていません（閾値 {FAILURE_RATE_WARNING_PCT:.0f}% / "
                f"{FAILURE_RATE_HIGH_PCT:.0f}%）", rate_pct=round(pct, 1), rows_failed=req_failed, rows=tried))

    # 品質ゲート（誤りの可能性が高い価格の隔離・低信頼度）。商品ごとに1件（毎日の別の店の隔離で件数が増えても重ねない）
    wrong = {}
    for s in collector.get("suspicious_prices") or []:
        if isinstance(s, dict) and s.get("reason") in hard:
            wrong.setdefault(str(s.get("product_alias") or "?"), []).append(s)
    for alias, items in sorted(wrong.items()):
        out.append(_alert(
            "quality_gate_failure", alias, WARNING, ",".join(sorted({str(i.get("reason")) for i in items})),
            f"{alias} の価格に誤りの可能性が高いものがあります（隔離）",
            "; ".join(f"{i.get('shop')}: {i.get('details')}" for i in items[:3]), items=len(items)))
    if int(collector.get("low_confidence_count") or 0) > 0:
        out.append(_alert("quality_gate_failure", "low_confidence", WARNING, "low_confidence",
                          "信頼度が低い価格が公開されている可能性があります",
                          f"{collector.get('low_confidence_count')} 件", count=collector.get("low_confidence_count")))

    # 公式の確認の期限・再確認の連続失敗
    for r in inputs.get("official_status") or []:
        pid = r.get("product_id")
        if r.get("expired"):
            out.append(_alert("official_verification_expiry", pid, HIGH, "expired", f"{pid} の公式の確認が切れています",
                              f"確認日 {r.get('last_verified')}（期限 14 日）", days_left=r.get("days_left")))
        elif int(r.get("days_left", 99)) <= EXPIRY_WARNING_DAYS:
            out.append(_alert("official_verification_expiry", pid, WARNING, "expiring",
                              f"{pid} の公式の確認が残り {r.get('days_left')} 日で切れます",
                              f"確認日 {r.get('last_verified')}（再確認が unchanged になれば延びる）", days_left=r.get("days_left")))
        n = int(r.get("consecutive_failures") or 0)
        if n >= RECHECK_FAILURE_WARNING_DAYS:
            out.append(_alert("official_recheck_failing", pid, HIGH if n >= RECHECK_FAILURE_HIGH_DAYS else WARNING,
                              "recheck_failed", f"{pid} の公式の再確認が {n} 日連続で失敗しています",
                              "公式ページの移動・表示の変更・ブロックの可能性。人が公式ページを確認する", consecutive_days=n))
    return sorted(out, key=lambda a: (-_RANK[a["severity"]], a["key"]))


def _consecutive_days(failure_days: list, today) -> int:
    """今日（または昨日）から連続して失敗した日数（failure_history の日付の並び）。"""
    days = set()
    for d in failure_days:
        try:
            days.add(datetime.fromisoformat(str(d)[:10]).date())
        except ValueError:
            continue
    n, cur = 0, today
    if cur not in days:
        cur = today - timedelta(days=1)          # 今日の履歴がまだ無ければ昨日から数える
    while cur in days:
        n += 1
        cur -= timedelta(days=1)
    return n


def reconcile(state: dict | None, current: list[dict], now: datetime) -> tuple[dict, dict]:
    """状態と今のアラートを突き合わせる（重複の抑制・重くなったときの出し直し・復旧）。

    戻り値: (新しい状態, {"candidates": [...新規・重くなった...], "suppressed": n, "recovered": [...]})
    状態の active は key → {first_seen, last_seen, severity, emitted_severity, times_seen}
    """
    active = dict((state or {}).get("active") or {})
    stamp = now.isoformat(timespec="seconds")
    candidates, suppressed, new_active = [], 0, {}
    for a in current:
        prev = active.get(a["key"])
        entry = {"first_seen": (prev or {}).get("first_seen") or stamp, "last_seen": stamp, "severity": a["severity"],
                 "emitted_severity": (prev or {}).get("emitted_severity", ""),
                 "times_seen": int((prev or {}).get("times_seen") or 0) + 1}
        if prev is None or _RANK[a["severity"]] > _RANK.get(entry["emitted_severity"], 0):
            candidates.append({**a, "type": TYPE, "event": "NEW" if prev is None else "ESCALATED",
                               "first_seen": entry["first_seen"], "generated_at": stamp})
            entry["emitted_severity"] = a["severity"]
        else:
            suppressed += 1                                      # 同じ異常は出し直さない
        new_active[a["key"]] = entry
    recovered = []
    for key, prev in sorted(active.items()):
        if key not in new_active:
            recovered.append({"key": key, "type": RECOVERED_TYPE, "event": "RECOVERED",
                              "first_seen": prev.get("first_seen"), "recovered_at": stamp,
                              "last_severity": prev.get("severity")})
    return ({"schema": SCHEMA, "updated_at": stamp, "active": new_active},
            {"candidates": candidates, "suppressed": suppressed, "recovered": recovered})


def build_record(current: list[dict], result: dict, now: datetime) -> dict:
    """exports/ops/health_alert.json の中身（運営者向け。顧客の通知・外部の送信とは無関係）。"""
    return {"type": TYPE, "schema": SCHEMA, "audience": "operator", "generated_at": now.isoformat(timespec="seconds"),
            "note": "運営者向けの劣化アラート候補（商品の通知ではない）。外部へは送らない。CI の注記・Step Summary・管理画面に出す",
            "active_count": len(current), "high": sum(1 for a in current if a["severity"] == HIGH),
            "warning": sum(1 for a in current if a["severity"] == WARNING),
            "candidates": result["candidates"], "suppressed": result["suppressed"], "recovered": result["recovered"],
            "active": current,
            "product_notification_candidates": 0, "customer_notification": False, "external_sends": 0}


def read_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
