#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Admin Dashboard — 運営向け集計（登録者数/通知数/利益ルート数/Health/実行成功率）。

AIロジックは変更しない。既存の生成物と account ストアを集計するのみ。
出力: exports/admin/latest.json / latest.md
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "admin"


def _load(p):
    try:
        return json.loads((ROOT / p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    from src.saas import accounts, subscription as sub, auth, billing
    accs = accounts.list_accounts()
    by_tier = Counter(a.get("tier", "free") for a in accs)
    by_provider = Counter(a.get("auth_provider", "email") for a in accs)

    ai = _load("exports/ai_opportunities/latest.json")
    notif = _load("exports/notifications/latest.json")
    pr = _load("exports/profit_routes/latest.json")
    health = _load("audit_health/health_report.json")
    execu = _load("exports/execution/latest.json")

    # 通知総数（履歴合算）
    total_notif = 0
    for hp in (ROOT / "exports" / "notifications" / "history").glob("*.json"):
        try:
            total_notif += len(json.loads(hp.read_text(encoding="utf-8")).get("events", []))
        except Exception:
            pass

    payload = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "accounts": {
            "total": len(accs),
            "by_tier": dict(by_tier),
            "by_auth_provider": dict(by_provider),
            "watchlist_total": sum(len(a.get("watchlist", [])) for a in accs),
        },
        "service": {
            "auth": auth.status(), "billing": billing.status(),
            "plans": [p["tier"] for p in billing.plans()],
        },
        "metrics": {
            "main_route_count": pr.get("summary", {}).get("main_route_count", 0),
            "reference_route_count": pr.get("summary", {}).get("reference_route_count", 0),
            "opportunities": len(ai.get("todays_opportunities", [])),
            "notifications_today": notif.get("event_count", 0),
            "notifications_total": total_notif,
            "health_score": (health.get("health_score", {}) or {}).get("total"),
            "execution_success_rate": execu.get("execution_success_rate"),
            "prediction_error_pt": (execu.get("prediction_accuracy", {}) or {}).get("error_points"),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    m = payload["metrics"]; a = payload["accounts"]
    md = ["# Admin Dashboard", "", f"生成: {payload['generated_at']}", "",
          "## 登録者", "",
          f"- 登録者数: **{a['total']}**（{a['by_tier']}）",
          f"- 認証プロバイダ別: {a['by_auth_provider']} / Watchlist登録総数: {a['watchlist_total']}", "",
          "## サービス状態", "",
          f"- 認証有効: {payload['service']['auth']['enabled'] or '（未設定・外部基盤要）'}",
          f"- Stripe: {'有効' if payload['service']['billing']['stripe_configured'] else '未設定（外部基盤要）'}"
          f" / プラン: {payload['service']['plans']}", "",
          "## 指標", "",
          f"- 利益ルート(main): **{m['main_route_count']}** / reference: {m['reference_route_count']}",
          f"- Opportunities: {m['opportunities']} / 通知(本日): {m['notifications_today']} / 通知(累計): {m['notifications_total']}",
          f"- Health Score: {m['health_score']} / 実行成功率: {m['execution_success_rate']}% "
          f"/ 予測誤差: {m['prediction_error_pt']}pt"]
    (OUT / "latest.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"  登録者 {a['total']}（{dict(a['by_tier'])}）/ main {m['main_route_count']} / "
          f"通知累計 {m['notifications_total']} / Health {m['health_score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
