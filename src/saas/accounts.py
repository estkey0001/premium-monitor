"""Accounts — account_id 単位の口座・設定・Watchlist・Portfolio ストア。

全ユーザーデータ（Watchlist / Notification 設定 / Capital / Execution）を account_id で分離する。
永続先はローカル JSON（data/accounts/<account_id>.json）。将来は DB / KVS に差し替え可能な薄い抽象。
機密（パスワード/トークン）は保存しない（認証は auth.py のプロバイダに委譲）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.saas import subscription as sub

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent.parent
STORE = ROOT / "data" / "accounts"

DEFAULT_SETTINGS = {
    "notify_channels": ["email"],       # email/discord/telegram/line/push（プラン範囲内）
    "notify_frequency": "daily",         # realtime / hourly / daily
    "roi_threshold": 0.08,               # これ以上のROIのみ通知
    "profit_threshold": 5000,            # これ以上の利益のみ通知
}


def _account_id_ok(account_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", account_id or ""))


def _path(account_id: str) -> Path:
    return STORE / f"{account_id}.json"


def new_account(account_id: str, email: str = "", auth_provider: str = "email",
                tier: str = "free") -> dict:
    """新規アカウント雛形（機密は保持しない）。"""
    if not _account_id_ok(account_id):
        raise ValueError("invalid account_id")
    return {
        "account_id": account_id,
        "email": email,
        "auth_provider": auth_provider,     # email / google / apple
        "tier": sub.normalize_tier(tier),
        "created_at": datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M JST"),
        "settings": dict(DEFAULT_SETTINGS),
        "watchlist": [],                    # 監視する product_id のリスト
        "portfolio": {"cash": 0, "holdings": []},  # ユーザー保有（Capital と連携）
        "subscription": {"status": "active", "plan": sub.normalize_tier(tier),
                         "billing_cycle": "monthly", "trial_until": None},
    }


def load(account_id: str) -> dict | None:
    # パストラバーサル防止: 不正な account_id は _path 生成前に拒否
    if not _account_id_ok(account_id):
        return None
    p = _path(account_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def save(account: dict) -> None:
    if not _account_id_ok(account.get("account_id", "")):
        raise ValueError("invalid account_id")
    STORE.mkdir(parents=True, exist_ok=True)
    _path(account["account_id"]).write_text(
        json.dumps(account, ensure_ascii=False, indent=2), encoding="utf-8")


def get_or_create(account_id: str, **kw) -> dict:
    acc = load(account_id)
    if acc is None:
        acc = new_account(account_id, **kw)
        save(acc)
    return acc


def list_accounts() -> list[dict]:
    if not STORE.exists():
        return []
    out = []
    for p in sorted(STORE.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def update_settings(account_id: str, **changes) -> dict:
    """通知チャネル/頻度/ROI閾値/利益閾値 を更新（プラン範囲でチャネルを制限）。"""
    acc = get_or_create(account_id)
    s = acc.setdefault("settings", dict(DEFAULT_SETTINGS))
    if "notify_channels" in changes:
        allowed = sub.allowed_channels(acc["tier"])
        s["notify_channels"] = [c for c in changes["notify_channels"] if c in allowed] or ["email"]
    for k in ("notify_frequency", "roi_threshold", "profit_threshold"):
        if k in changes:
            s[k] = changes[k]
    save(acc)
    return acc


def set_watchlist(account_id: str, product_ids: list[str]) -> dict:
    acc = get_or_create(account_id)
    limit = sub.tier_config(acc["tier"])["watchlist_limit"]
    acc["watchlist"] = list(dict.fromkeys(product_ids))[:limit]
    save(acc)
    return acc


def notify_eligible(account: dict, roi: float, profit: int, channel: str) -> bool:
    """このアカウントの設定でこの通知を送るべきか（閾値・チャネル）。"""
    s = account.get("settings", DEFAULT_SETTINGS)
    if channel not in s.get("notify_channels", []):
        return False
    if (roi or 0) < s.get("roi_threshold", 0):
        return False
    if (profit or 0) < s.get("profit_threshold", 0):
        return False
    return True
