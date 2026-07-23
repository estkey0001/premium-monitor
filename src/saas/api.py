"""REST API — 標準ライブラリ http.server のみ（追加依存なしで起動可）。

エンドポイント（GET）:
  /health                     ヘルスチェック
  /account?account_id=...     アカウント情報（tier/settings/watchlist/portfolio）
  /opportunities?account_id=  Today's Opportunities（tier=pro以上・watchlistでフィルタ可）
  /notifications?account_id=  通知イベント（tier=pro以上・アカウント設定の閾値でフィルタ）
  /capital?account_id=&budget= 資金配分プラン（tier=pro以上）
  /execution?account_id=      実行精度・学習（tier=pro以上）
  /plans                      サブスクプラン一覧

認証: 本番はゲートウェイ/JWTで account_id を検証する前提。ここでは account_id クエリで受け、
プランに応じて 402/403 を返す（実運用ではミドルウェアで認可）。

起動: python -m src.saas.api  （PORT 環境変数、既定 8787）
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.saas import subscription as sub
from src.saas import accounts as acc_store
from src.saas import auth, billing

ROOT = Path(__file__).resolve().parent.parent.parent
EXPORTS = ROOT / "exports"

API_VERSION = "v1"
_ACCOUNT_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")
# 簡易レート制限（per-IP・60秒60req）。本番はゲートウェイ/WAF で置換。
RATE_WINDOW = 60
RATE_MAX = int(os.environ.get("API_RATE_MAX", "60"))
_hits: dict = defaultdict(deque)


def _rate_ok(ip: str) -> bool:
    now = time.monotonic()
    dq = _hits[ip]
    while dq and now - dq[0] > RATE_WINDOW:
        dq.popleft()
    if len(dq) >= RATE_MAX:
        return False
    dq.append(now)
    return True


class ApiError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message


def _valid_account_id(qs) -> str:
    """account_id を検証して返す（不正なら 400）。パストラバーサル/インジェクション防止。"""
    aid = (qs.get("account_id", ["default"])[0]) or "default"
    if not _ACCOUNT_RE.fullmatch(aid):
        raise ApiError(400, "invalid account_id")
    return aid


def _read(rel):
    try:
        return json.loads((EXPORTS / rel).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _account(qs) -> dict:
    return acc_store.get_or_create(_valid_account_id(qs))


def _filter_watchlist(items, watchlist, key="product_id"):
    if not watchlist:
        return items
    return [x for x in items if x.get(key) in watchlist]


def route(path: str, qs: dict) -> tuple[int, dict]:
    if path == "/health":
        return 200, {"ok": True, "version": API_VERSION, "auth": auth.status(), "billing": billing.status()}
    if path == "/plans":
        return 200, {"plans": billing.plans()}
    if path == "/account":
        a = _account(qs)
        return 200, {"account_id": a["account_id"], "tier": a["tier"],
                     "settings": a.get("settings"), "watchlist": a.get("watchlist"),
                     "portfolio": a.get("portfolio"),
                     "features": sorted(sub.tier_config(a["tier"])["features"])}
    if path == "/opportunities":
        a = _account(qs)
        if not sub.can_access(a["tier"], "ai_dashboard"):
            return 402, {"error": "Pro plan required", "feature": "ai_dashboard"}
        d = _read("ai_opportunities/latest.json")
        ops = _filter_watchlist(d.get("todays_opportunities", []), a.get("watchlist"))
        return 200, {"account_id": a["account_id"], "count": len(ops),
                     "daily_recommendation": d.get("daily_recommendation"), "opportunities": ops}
    if path == "/notifications":
        a = _account(qs)
        if not sub.can_access(a["tier"], "notification"):
            return 402, {"error": "Pro plan required", "feature": "notification"}
        d = _read("notifications/latest.json")
        evs = []
        for e in d.get("events", []):
            # アカウント設定（ROI/利益閾値・チャネル）でフィルタ（可能な範囲で）
            data = e.get("data", {})
            if acc_store.notify_eligible(a, data.get("roi", 1.0), data.get("net_profit", 10**9),
                                         a.get("settings", {}).get("notify_channels", ["email"])[0]):
                evs.append(e)
        return 200, {"account_id": a["account_id"], "count": len(evs), "events": evs or d.get("events", [])}
    if path == "/capital":
        a = _account(qs)
        if not sub.can_access(a["tier"], "capital"):
            return 402, {"error": "Pro plan required", "feature": "capital"}
        d = _read("allocation/latest.json")
        budget = qs.get("budget", [str(d.get("default_budget", 3000000))])[0]
        if not re.fullmatch(r"\d{1,12}", str(budget)):
            raise ApiError(400, "invalid budget")
        plan = (d.get("plans", {}) or {}).get(str(budget))
        return 200, {"account_id": a["account_id"], "budget": budget, "plan": plan}
    if path == "/execution":
        a = _account(qs)
        if not sub.can_access(a["tier"], "capital"):
            return 402, {"error": "Pro plan required", "feature": "execution"}
        d = _read("execution/latest.json")
        return 200, {"account_id": a["account_id"], "prediction_accuracy": d.get("prediction_accuracy"),
                     "execution_success_rate": d.get("execution_success_rate"),
                     "learning_coefficients": d.get("learning_coefficients")}
    return 404, {"error": "not found", "path": path}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静音
        pass

    def _client_ip(self) -> str:
        return (self.client_address[0] if self.client_address else "unknown")

    def do_GET(self):
        u = urlparse(self.path)
        if not _rate_ok(self._client_ip()):
            code, body = 429, {"error": "rate limit exceeded"}
        else:
            try:
                code, body = route(u.path, parse_qs(u.query))
            except ApiError as e:
                code, body = e.code, {"error": e.message}
            except PermissionError as e:
                code, body = 403, {"error": str(e)}
            except Exception as e:
                code, body = 500, {"error": "internal error"}  # 詳細は漏らさない
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        # セキュリティヘッダ + 保守的CORS（既定は許可オリジンなし。本番はゲートウェイで設定）
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-API-Version", API_VERSION)
        _allow = os.environ.get("API_CORS_ORIGIN", "")
        if _allow:
            self.send_header("Access-Control-Allow-Origin", _allow)
        self.end_headers()
        self.wfile.write(raw)


def main():
    port = int(os.environ.get("PORT", "8787"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[saas.api] listening on http://127.0.0.1:{port}  (/health /account /opportunities "
          f"/notifications /capital /execution /plans)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
