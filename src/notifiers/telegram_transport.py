"""Telegram Bot API の送信の部品（transport。Phase 22）。

- 公式の Bot API（https://api.telegram.org）の sendMessage だけに、HTTPS の POST を1回だけ送る（再試行しない。
  再試行は outbox が次の実行で決める）。第三者の中継は使わない
- 標準のライブラリ（urllib）だけを使う（依存を増やさない）
- トークンは URL に入るが、URL・トークン・チャット ID をログ・例外・戻り値に出さない（例外は段階だけの TransportError にする）
- 本文は adapters.TelegramAdapter.build_payload（そのままの文字。parse_mode は付けない）。chat_id はここで付ける
  （台帳・本文に入れない）。リンクのプレビューは出さない
- 応答: (HTTP の状態, ヘッダー, JSON の本文 or None)。分類は adapters.TelegramAdapter.classify_response
  （200 かつ ok=true だけが成功）

この部品を使うのは、本番の送信の最終の関門（adapters.real_send_gate）を通ったときだけ（CLI の dispatch-notifications）。
"""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request

from src.notifiers.adapters import TransportError

API_BASE = "https://api.telegram.org"          # 公式の Bot API だけ
TIMEOUT_SECONDS = 15


def _connect_failed(exc) -> bool:
    """要求を送り終える前に失敗したと断定できるか（名前の解決・接続の拒否・TLS の確立の失敗）。

    それ以外（タイムアウト・接続の切断など）は、送ったかどうか分からない（届いたか不明にする）。
    """
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (socket.gaierror, ConnectionRefusedError, ssl.SSLCertVerificationError))


def make_telegram_transport(token: str, chat_id: str, *, opener=None, timeout: float = TIMEOUT_SECONDS):
    """transport(payload, idempotency_key) -> (status, headers, body) を作る。値はこの関数の中だけに閉じる。"""
    token, chat_id = str(token or "").strip(), str(chat_id or "").strip()
    url = f"{API_BASE}/bot{token}/sendMessage"
    op = opener or urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def transport(payload: dict, idempotency_key: str):
        body = {"chat_id": chat_id, "text": str(payload.get("text") or ""), "disable_web_page_preview": True}
        req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        stage = ""
        try:
            resp = op.open(req, timeout=timeout)
            status, headers, raw = resp.getcode(), dict(resp.headers or {}), resp.read()
        except urllib.error.HTTPError as e:      # 4xx・5xx（応答はある）
            status, headers = e.code, dict(e.headers or {})
            try:
                raw = e.read()
            except Exception:  # noqa: BLE001
                raw = b""
        except Exception as e:  # noqa: BLE001
            stage = "connect" if _connect_failed(e) else "read"
        if stage:
            # 例外の文字列に URL（トークン）が入ることがあるので、段階だけを渡す。except の外で投げて、元の例外を
            # __context__ にも残さない（監査 L-2）
            raise TransportError(stage)
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            parsed = None                          # 読めない本文（200 なら届いたか不明に分類される）
        return int(status), headers, parsed

    return transport
