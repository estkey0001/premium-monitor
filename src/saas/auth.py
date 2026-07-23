"""Auth — 認証プロバイダ抽象（email / google / apple）。

重要: 実際の OAuth / メール認証は、稼働中のバックエンド（サーバ + HTTPS + セッション/JWT）が
必要で、本リポジトリの静的サイト構成では完結しない。ここでは
「プロバイダ抽象 + 設定の env gating」だけを提供し、外部基盤導入時に実装を差し込む。
資格情報（client_secret 等）はコードに埋め込まず、環境変数から読む（未設定なら無効）。
"""
from __future__ import annotations

import os

PROVIDERS = ("email", "google", "apple")


def provider_configured(provider: str) -> bool:
    """環境変数の有無でプロバイダ有効性を判定（実キーは扱わない）。"""
    p = (provider or "").lower()
    if p == "email":
        return bool(os.environ.get("AUTH_EMAIL_ENABLED"))
    if p == "google":
        return bool(os.environ.get("GOOGLE_OAUTH_CLIENT_ID"))
    if p == "apple":
        return bool(os.environ.get("APPLE_OAUTH_CLIENT_ID"))
    return False


def enabled_providers() -> list[str]:
    return [p for p in PROVIDERS if provider_configured(p)]


def status() -> dict:
    """認証設定の状態（Admin/診断用）。未設定でも安全に報告。"""
    return {
        "providers": list(PROVIDERS),
        "enabled": enabled_providers(),
        "note": "実OAuth/メール認証はバックエンド（サーバ+HTTPS+セッション）が必要。"
                "env（GOOGLE_OAUTH_CLIENT_ID / APPLE_OAUTH_CLIENT_ID / AUTH_EMAIL_ENABLED）で有効化。",
    }


class AuthProvider:
    """プロバイダ実装のインターフェース（外部基盤で継承・実装）。"""

    name = "base"

    def authorize_url(self, redirect_uri: str, state: str) -> str:  # pragma: no cover
        raise NotImplementedError("実装は外部バックエンドで提供")

    def exchange_code(self, code: str) -> dict:  # pragma: no cover
        """認可コード→ユーザー情報（email 等）。実装は外部で。"""
        raise NotImplementedError("実装は外部バックエンドで提供")
