"""Subscription — Free / Pro / Enterprise の権限ゲート。

AIロジックは変更しない。どのプランがどの機能を使えるかだけを定義する。
"""
from __future__ import annotations

# 機能フラグ
FEATURES = [
    "beginner", "pro", "ai_dashboard", "notification", "capital",
    "api", "multi_account", "csv_export",
]

TIERS = {
    "free": {
        "label": "Free",
        "price_monthly": 0, "price_yearly": 0,
        "features": {"beginner"},
        "notify_channels": {"email"},
        "watchlist_limit": 5,
        "account_limit": 1,
    },
    "pro": {
        "label": "Pro",
        "price_monthly": 1480, "price_yearly": 14800,
        "features": {"beginner", "pro", "ai_dashboard", "notification", "capital"},
        "notify_channels": {"email", "discord", "telegram", "line", "push"},
        "watchlist_limit": 100,
        "account_limit": 1,
    },
    "enterprise": {
        "label": "Enterprise",
        "price_monthly": 9800, "price_yearly": 98000,
        "features": set(FEATURES),  # 全機能 + api / multi_account / csv_export
        "notify_channels": {"email", "discord", "telegram", "line", "push"},
        "watchlist_limit": 1000,
        "account_limit": 20,
    },
}

DEFAULT_TIER = "free"


def normalize_tier(tier: str) -> str:
    t = (tier or "").strip().lower()
    return t if t in TIERS else DEFAULT_TIER


def can_access(tier: str, feature: str) -> bool:
    """指定プランが feature を使えるか。"""
    return feature in TIERS[normalize_tier(tier)]["features"]


def tier_config(tier: str) -> dict:
    return TIERS[normalize_tier(tier)]


def allowed_channels(tier: str) -> set:
    return set(TIERS[normalize_tier(tier)]["notify_channels"])


def gate(tier: str, feature: str) -> None:
    """アクセス不可なら PermissionError（API/サービス層で利用）。"""
    if not can_access(tier, feature):
        raise PermissionError(f"feature '{feature}' requires a higher plan (current: {normalize_tier(tier)})")
