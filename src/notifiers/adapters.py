"""通知の配信先（provider）の差し込み口（Phase 20）。

本文の組み立て（build_payload）・検査（validate）・応答の分類（classify_http）までを持つ。通信はしない:
送信は transport（呼び出し側が渡す関数）だけが行い、このモジュールは HTTP の部品を import しない。Phase 20 では
transport をどこからも渡さないので、Discord・Telegram への送信は起きない（テストは偽の transport を渡す）。

配信先の URL・トークン・チャット ID は transport の側が持つ（台帳・本文・ログに入れない）。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

RETRYABLE = "retryable"      # 相手に届いていない（接続できなかった・503・429）。次の実行で出し直してよい
FINAL = "final"              # 出し直しても通らない（認証・宛先・本文の誤り）
AMBIGUOUS = "ambiguous"      # 届いたか分からない（送った後に接続が切れた・応答を読めなかった）。自動では出し直さない
RETRY_AFTER_CAP_SECONDS = 6 * 3600


class ProviderError(Exception):
    """配信の失敗。kind は RETRYABLE / FINAL / AMBIGUOUS。error_class は記録用の短い名前（秘密の値を入れない）。"""

    def __init__(self, kind: str, error_class: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(f"{kind}:{error_class}")
        self.kind, self.error_class, self.status, self.retry_after = kind, error_class, status, retry_after


class TransportError(Exception):
    """transport の通信の失敗。stage="connect" は要求を送り終える前（届いていない）、"read" は送った後（届いたか不明）。"""

    def __init__(self, stage: str = "read"):
        super().__init__(stage)
        self.stage = stage


def classify_http(status: int, headers: dict | None = None, *, now: float | None = None) -> ProviderError | None:
    """HTTP の応答を分類する（2xx は None）。429 は Retry-After を読む（既存の api_runtime.parse_retry_after）。"""
    from src.collectors.api.api_runtime import parse_retry_after
    if 200 <= status < 300:
        return None
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    if status == 429:
        ra = parse_retry_after(h.get("retry-after"), now=now)
        return ProviderError(RETRYABLE, "rate_limited", status=status,
                             retry_after=min(ra, RETRY_AFTER_CAP_SECONDS) if ra is not None else None)
    if status == 503:
        return ProviderError(RETRYABLE, "server_unavailable", status=status)
    if status >= 500:
        # 500・502・504 などは、相手が処理した後に返ることがある（届いたか分からない。自動では出し直さない）
        return ProviderError(AMBIGUOUS, "server_error", status=status)
    if status in (401, 403):
        return ProviderError(FINAL, "auth", status=status)
    if status == 404:
        return ProviderError(FINAL, "invalid_destination", status=status)
    if status in (400, 413, 422):
        return ProviderError(FINAL, "malformed_payload", status=status)
    return ProviderError(FINAL, f"http_{status}", status=status)


class ProviderAdapter:
    """配信先の共通の形。transport(payload, idempotency_key) -> (status, headers, body) を渡したときだけ送れる。"""

    name = "base"
    max_length = 2000

    def __init__(self, transport=None):
        self.transport = transport

    @property
    def configured(self) -> bool:
        return self.transport is not None

    def build_payload(self, record: dict) -> dict:
        raise NotImplementedError

    def validate(self, payload: dict) -> list[str]:
        text = str(payload.get(self._text_field()) or "")
        why = []
        if not text.strip():
            why.append("empty")
        if len(text) > self.max_length:
            why.append("too_long")
        if re.search(r"@(everyone|here)\b", text):
            why.append("mass_mention")
        return why

    def _text_field(self) -> str:
        return "content"

    def delivery_id(self, status: int, headers: dict, body) -> str:
        return ""

    def send(self, record: dict, idempotency_key: str) -> str:
        """1回だけ送る（再試行しない。再試行は次の実行の outbox が決める）。成功なら配信先の ID（無ければ空）。"""
        if self.transport is None:
            raise ProviderError(FINAL, "not_configured")
        payload = self.build_payload(record)
        bad = self.validate(payload)
        if bad:
            raise ProviderError(FINAL, "malformed_payload")
        try:
            status, headers, body = self.transport(payload, idempotency_key)
        except TransportError as e:
            if e.stage == "connect":
                raise ProviderError(RETRYABLE, "connect_failed") from None
            raise ProviderError(AMBIGUOUS, "response_lost") from None
        except Exception as e:  # noqa: BLE001
            # 想定外の失敗は届いたか分からない扱い（送り直さない）。記録は例外のクラス名だけ（URL などを含めない）
            raise ProviderError(AMBIGUOUS, f"transport_{type(e).__name__}") from None
        err = classify_http(int(status), headers)
        if err is not None:
            raise err
        return self.delivery_id(int(status), headers or {}, body)


class DiscordAdapter(ProviderAdapter):
    """Discord の webhook の本文（content は2000文字まで。@everyone などの一斉の呼び出しはしない）。"""

    name = "discord"
    max_length = 2000

    def build_payload(self, record: dict) -> dict:
        # 切り詰めない（末尾の購入・申込の URL を欠かさない。長すぎれば validate で止める）
        return {"content": str(record.get("message") or ""), "allowed_mentions": {"parse": []}}

    def delivery_id(self, status, headers, body) -> str:
        return str((body or {}).get("id") or "") if isinstance(body, dict) else ""


class TelegramAdapter(ProviderAdapter):
    """Telegram の sendMessage の本文（text は4096文字まで。chat_id は transport が付ける。台帳に入れない）。"""

    name = "telegram"
    max_length = 4096

    def _text_field(self) -> str:
        return "text"

    def build_payload(self, record: dict) -> dict:
        return {"text": str(record.get("message") or ""), "disable_web_page_preview": False}

    def delivery_id(self, status, headers, body) -> str:
        res = (body or {}).get("result") if isinstance(body, dict) else None
        return str((res or {}).get("message_id") or "") if isinstance(res, dict) else ""


class LogAdapter(ProviderAdapter):
    """内部のログ（外部への通信なし）。transport を渡さなくても送れる。"""

    name = "log"
    max_length = 10000

    def __init__(self, transport=None):
        super().__init__(transport or self._log)

    @staticmethod
    def _log(payload, key):
        logger.info("ACTIONABLE_NOW %s\n%s", key, payload.get("content"))
        return 200, {}, {"id": f"log:{key}:{datetime.now().strftime('%Y%m%dT%H%M%S')}"}

    def build_payload(self, record: dict) -> dict:
        return {"content": str(record.get("message") or "")}

    def delivery_id(self, status, headers, body) -> str:
        return str((body or {}).get("id") or "") if isinstance(body, dict) else ""


ADAPTERS = {"discord": DiscordAdapter, "telegram": TelegramAdapter, "log": LogAdapter}


def default_adapters() -> dict:
    """Phase 20 の既定: transport を渡さない（Discord・Telegram は未設定。送信は起きない）。"""
    return {"discord": DiscordAdapter(), "telegram": TelegramAdapter(), "log": LogAdapter()}
