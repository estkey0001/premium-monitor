"""Billing — Stripe プラン定義・課金抽象（月額/年額/Trial）。

重要: 実際の課金処理は Stripe アカウント + サーバ + webhook 受信 + HTTPS が必要で、
本リポジトリの静的構成では完結しない。ここではプラン定義と webhook ハンドラ抽象、
env gating（STRIPE_SECRET_KEY 未設定なら無効）だけを提供する。シークレットは埋め込まない。
"""
from __future__ import annotations

import os

from src.saas import subscription as sub

TRIAL_DAYS = 14

# Stripe Price ID は環境変数で注入（コードに埋め込まない）
PRICE_ENV = {
    ("pro", "monthly"): "STRIPE_PRICE_PRO_MONTHLY",
    ("pro", "yearly"): "STRIPE_PRICE_PRO_YEARLY",
    ("enterprise", "monthly"): "STRIPE_PRICE_ENT_MONTHLY",
    ("enterprise", "yearly"): "STRIPE_PRICE_ENT_YEARLY",
}


def stripe_configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def plans() -> list[dict]:
    out = []
    for tier, cfg in sub.TIERS.items():
        out.append({
            "tier": tier, "label": cfg["label"],
            "price_monthly": cfg["price_monthly"], "price_yearly": cfg["price_yearly"],
            "trial_days": TRIAL_DAYS if tier != "free" else 0,
            "features": sorted(cfg["features"]),
        })
    return out


def price_id(tier: str, cycle: str) -> str | None:
    env = PRICE_ENV.get((sub.normalize_tier(tier), cycle))
    return os.environ.get(env) if env else None


def status() -> dict:
    return {
        "stripe_configured": stripe_configured(),
        "trial_days": TRIAL_DAYS,
        "plans": [(p["tier"], p["price_monthly"], p["price_yearly"]) for p in plans()],
        "note": "実課金は Stripe アカウント + サーバ + webhook が必要。"
                "STRIPE_SECRET_KEY / STRIPE_PRICE_* を環境変数で設定して有効化。",
    }


def handle_webhook(event_type: str, payload: dict) -> dict:
    """Stripe webhook の処理骨子（外部サーバで署名検証の上で呼ぶ）。
    ここでは account の subscription 状態遷移のみを表現（実送金処理は行わない）。"""
    from src.saas import accounts
    account_id = (payload or {}).get("account_id")
    if not account_id:
        return {"ok": False, "reason": "no account_id"}
    acc = accounts.load(account_id)
    if not acc:
        return {"ok": False, "reason": "account not found"}
    st = acc.setdefault("subscription", {})
    mapping = {
        "checkout.session.completed": ("active", payload.get("tier", "pro")),
        "customer.subscription.deleted": ("canceled", "free"),
        "invoice.payment_failed": ("past_due", acc.get("tier", "free")),
    }
    if event_type in mapping:
        status_, tier_ = mapping[event_type]
        st["status"] = status_
        acc["tier"] = sub.normalize_tier(tier_)
        st["plan"] = acc["tier"]
        accounts.save(acc)
        return {"ok": True, "account_id": account_id, "status": status_, "tier": acc["tier"]}
    return {"ok": True, "ignored": event_type}
