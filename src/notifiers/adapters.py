"""通知の配信先（provider）の差し込み口（Phase 20・21）。

outbox（src/notifiers/outbox）の後ろに差し込む。配信先ごとに次を持つ:

- validate_config(env)        送信に要る設定がそろって形が正しいか（値は返さない・表示しない）
- build_payload(record)       本文（outbox の記録の確定の値だけ。利益を計算し直さない。安全な短縮規則で長さに収める）
- validate_payload(payload)   長さ・空・一斉の呼び出し
- classify_response(...)      応答の分類（届いた / 出し直してよい / 出し直さない / 届いたか分からない）
- extract_delivery_id(...)    配信先の ID（Discord の message の id・Telegram の message_id。取れなければ空）

通信はしない。送信は transport（呼び出し側が渡す関数）だけが行い、このモジュールは HTTP の部品を import しない。
送信の部品（HTTP の transport）は Telegram だけ（`src/notifiers/telegram_transport.py`。Phase 22）。Discord は無い。
商品の通知の本番の送信は `PRODUCT_REAL_SEND_ENABLED = False` で常に閉じる。Telegram の接続の試験（canary）だけが、
最終の関門 `real_send_gate(purpose="canary")` を全部通ったときに1件送れる。
配信先の URL・トークン・チャット ID は transport の側だけが持つ（台帳・本文・ログ・画面に入れない。`redact` で消す）。
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime

logger = logging.getLogger(__name__)

RETRYABLE = "retryable"      # 相手に届いていない（接続できなかった・503・429）。次の実行で出し直してよい
FINAL = "final"              # 出し直しても通らない（認証・宛先・本文の誤り）
AMBIGUOUS = "ambiguous"      # 届いたか分からない（送った後に接続が切れた・応答を読めなかった）。自動では出し直さない
RETRY_AFTER_CAP_SECONDS = 6 * 3600

# 送信の部品（HTTP の transport）がある配信先（Phase 22: Telegram だけ。Discord は無い）
IMPLEMENTED_PROVIDERS = frozenset({"telegram"})
# 商品の通知の本番の送信（Phase 22 では無効のまま。接続の試験の成功だけでは開けない。別の明示の許可で変える）
PRODUCT_REAL_SEND_ENABLED = False
REAL_SEND_IMPLEMENTED = PRODUCT_REAL_SEND_ENABLED      # 互換（商品の通知の送信の可否）

# 秘密の値の形（台帳・ログ・画面に出さない。deploy-check の _SECRET_PATTERNS と同じ形）
SECRET_PATTERNS = (r"(?:https?://)?(?:ptb\.|canary\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/\S+",
                   r"api\.telegram\.org/bot\d+:[\w-]+", r"(?<!\d)\d{5,12}:[A-Za-z0-9_-]{30,}",
                   r"hooks\.slack\.com/services/\S+", r"(?i)bearer\s+[A-Za-z0-9._-]{20,}")


def redact(text) -> str:
    """文字列から秘密の値の形を消す（ログ・例外の記録に使う）。"""
    s = str(text or "")
    for p in SECRET_PATTERNS:
        s = re.sub(p, "[REDACTED]", s)
    return s


class ProviderError(Exception):
    """配信の失敗。kind は RETRYABLE / FINAL / AMBIGUOUS。error_class は記録用の短い名前（秘密の値を入れない）。"""

    def __init__(self, kind: str, error_class: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(f"{kind}:{error_class}")
        self.kind, self.error_class, self.status, self.retry_after = kind, error_class, status, retry_after


class TransportError(Exception):
    """transport の通信の失敗。stage="connect" は要求を送り終える前（届いていない）、それ以外は届いたか不明。"""

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


# ── 本文（共通の短縮規則） ─────────────────────────────────────────────────

def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


_DISCORD_MD = re.compile(r"([\\*_~|`>#\[\]()])")


def escape_discord(text: str) -> str:
    """Discord の Markdown として解釈される文字を無効にする（商品名などの文字をそのまま見せる。URL の行には使わない）。"""
    return _DISCORD_MD.sub(r"\\\1", str(text or ""))


def _fmt_lines(record: dict, *, name: str, with_checked: bool) -> list[str]:
    """本文の行（値は outbox の記録の確定の値のまま。利益・ROI を計算し直さない）。"""
    from src.market import actionability as act
    from src.notifiers import actionable as an
    avail = str(record.get("availability_kind") or record.get("availability") or "")
    lines = [f"🎯 {an.TITLES.get(avail, '')}", f"商品: {name}"]
    if an._finite(record.get("net_profit")):
        lines.append(f"想定純利益: +¥{int(record['net_profit']):,}（確定の利益案件）")
    if an._finite(record.get("roi")):
        lines.append(f"ROI: {record['roi'] * 100:.1f}%")
    lines.append(f"状態: {act.LABELS.get(avail, '')}")
    if record.get("deadline"):
        d = act._dt(record["deadline"])
        if d is not None:
            lines.append("締切: " + d.strftime("%m/%d" if act.is_date_only(record["deadline"]) else "%m/%d %H:%M"))
    ck = act._dt(record.get("checked_at")) if record.get("checked_at") else None
    if with_checked and ck is not None:
        lines.append(f"確認: {ck.strftime('%m/%d %H:%M')}（公式）")
    url = str(record.get("action_url") or record.get("cta_url") or "")
    lines.append(f"{record.get('cta_label') or '公式のページ'}: {url}")
    return lines


def fit_message(record: dict, limit: int, *, escape=None) -> str:
    """長さの上限に収める本文（安全な短縮規則。収まらなければ空 = 送らない）。

    意味を変える短縮はしない: 状態・利益・ROI・締切・購入/申込の URL は削らない。削るのは
    1) 確認の時刻の行 2) 商品名の末尾（「…」を付ける。12文字は残す）の順だけ。URL は切らない。
    """
    raw = str(record.get("product") or record.get("product_id") or "")
    esc = escape or (lambda x: x)               # 配信先の書式の文字を無効にする（短縮はエスケープの前の名前で行う）
    for with_checked in (True, False):
        text = "\n".join(_fmt_lines(record, name=esc(raw), with_checked=with_checked))
        if len(text) <= limit:
            return text
    base = "\n".join(_fmt_lines(record, name="", with_checked=False))
    room = limit - len(base)
    if room < 13:
        return ""
    lo, hi = 0, len(raw)                         # エスケープした後の長さが収まる、元の名前の最長の切り口
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(esc(raw[:mid])) + 1 <= room:
            lo = mid
        else:
            hi = mid - 1
    if lo < 12 and lo < len(raw):
        return ""
    return "\n".join(_fmt_lines(record, name=esc(raw[:lo]) + "…", with_checked=False))


class ProviderAdapter:
    """配信先の共通の形。transport(payload, idempotency_key) -> (status, headers, body) を渡したときだけ送れる。"""

    name = "base"
    max_length = 2000
    config_keys: tuple = ()

    def __init__(self, transport=None):
        self.transport = transport
        self.calls = 0                           # transport を実際に呼んだ回数（送信の要求の数）

    @property
    def configured(self) -> bool:
        return self.transport is not None

    # 設定（値は返さない）
    def validate_config(self, env=None) -> list[str]:
        e = env if env is not None else os.environ
        return [f"{k}:missing" for k in self.config_keys if not str(e.get(k) or "").strip()]

    def _text_field(self) -> str:
        return "content"

    def build_payload(self, record: dict) -> dict:
        raise NotImplementedError

    def validate_payload(self, payload: dict) -> list[str]:
        text = str(payload.get(self._text_field()) or "")
        why = []
        if not text.strip():
            why.append("empty")
        if len(text) > self.max_length:
            why.append("too_long")
        if re.search(r"@(everyone|here)\b", text):
            why.append("mass_mention")
        if any(re.search(p, text) for p in SECRET_PATTERNS):
            why.append("secret_in_payload")
        return why

    validate = validate_payload             # Phase 20 の名前（互換）

    def classify_response(self, status: int, headers: dict | None = None, body=None) -> ProviderError | None:
        return classify_http(int(status), headers)

    def extract_delivery_id(self, status: int, headers: dict | None, body) -> str:
        return ""

    def delivery_id(self, status, headers, body) -> str:     # Phase 20 の名前（互換）
        return self.extract_delivery_id(status, headers, body)

    def send(self, record: dict, idempotency_key: str) -> str:
        """1回だけ送る（再試行しない。再試行は次の実行の outbox が決める）。成功なら配信先の ID（無ければ空）。"""
        if self.transport is None:
            raise ProviderError(FINAL, "not_configured")
        payload = self.build_payload(record)
        if self.validate_payload(payload):
            raise ProviderError(FINAL, "malformed_payload")
        fail = None
        self.calls += 1
        try:
            status, headers, body = self.transport(payload, idempotency_key)
        except TransportError as e:
            # 送る前の失敗だけ出し直してよい。送った後・どこで止まったか分からない失敗は、届いたか不明
            fail = (RETRYABLE, "connect_failed") if e.stage == "connect" else (AMBIGUOUS, "response_lost")
        except Exception as e:  # noqa: BLE001
            # 想定外の失敗は届いたか分からない扱い（送り直さない）。記録は例外のクラス名だけ（URL などを含めない）
            fail = (AMBIGUOUS, f"transport_{type(e).__name__}")
        if fail:
            raise ProviderError(*fail)                # except の外で投げる（元の例外を __context__ に残さない）
        try:
            err = self.classify_response(int(status), headers, body)
            did = None if err is not None else self.extract_delivery_id(int(status), headers or {}, body)
        except Exception:  # noqa: BLE001
            # 応答を読めない（形の崩れた本文など）: 送った後なので届いたか分からない（ほかの配信先を止めない。レビュー M-1）
            raise ProviderError(AMBIGUOUS, "classify_failed") from None
        if err is not None:
            raise err
        return did


class DiscordAdapter(ProviderAdapter):
    """Discord の webhook（content は2000文字まで。一斉の呼び出しはしない。webhook の URL は transport だけが持つ）。

    配信先の ID は、webhook を wait=true で呼んだときの応答の message の id（無ければ空）。
    """

    name = "discord"
    max_length = 2000
    config_keys = ("DISCORD_WEBHOOK_URL",)
    _URL = re.compile(r"^https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api(?:/v\d+)?/webhooks/\d+/[\w-]+$")

    def validate_config(self, env=None) -> list[str]:
        e = env if env is not None else os.environ
        why = super().validate_config(e)
        url = str(e.get("DISCORD_WEBHOOK_URL") or "").strip()
        if url and not self._URL.match(url):
            why.append("DISCORD_WEBHOOK_URL:invalid_format")
        return why

    def build_payload(self, record: dict) -> dict:
        return {"content": fit_message(record, self.max_length, escape=escape_discord), "allowed_mentions": {"parse": []}}

    def extract_delivery_id(self, status, headers, body) -> str:
        return str((body or {}).get("id") or "") if isinstance(body, dict) else ""


class TelegramAdapter(ProviderAdapter):
    """Telegram の sendMessage（text は4096文字まで。parse_mode なし = そのままの文字。chat_id は transport が付ける）。

    Telegram は失敗を HTTP 200 + {"ok": false, "error_code": …} で返すことがあるので、本文の ok と error_code も見る。
    429 は parameters.retry_after。配信先の ID は result.message_id。
    """

    name = "telegram"
    max_length = 4096
    config_keys = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    _TOKEN = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,}$")
    _CHAT = re.compile(r"^(?:-?\d{3,20}|@[A-Za-z][A-Za-z0-9_]{4,31})$")

    def _text_field(self) -> str:
        return "text"

    def validate_config(self, env=None) -> list[str]:
        e = env if env is not None else os.environ
        why = super().validate_config(e)
        tok, chat = str(e.get("TELEGRAM_BOT_TOKEN") or "").strip(), str(e.get("TELEGRAM_CHAT_ID") or "").strip()
        if tok and not self._TOKEN.match(tok):
            why.append("TELEGRAM_BOT_TOKEN:invalid_format")
        if chat and not self._CHAT.match(chat):
            why.append("TELEGRAM_CHAT_ID:invalid_format")
        return why

    def build_payload(self, record: dict) -> dict:
        text = str(record.get("message") or "") if record.get("is_test_message") else fit_message(record, self.max_length)
        return {"text": text, "disable_web_page_preview": True}

    def classify_response(self, status, headers=None, body=None) -> ProviderError | None:
        err = classify_http(int(status), headers)
        if isinstance(body, dict) and body.get("ok") is False:
            code = _int(body.get("error_code"), int(status or 0))
            ra = _num(((body.get("parameters") or {}) if isinstance(body.get("parameters"), dict) else {})
                      .get("retry_after"))
            if code == 429:
                return ProviderError(RETRYABLE, "rate_limited", status=code,
                                     retry_after=min(ra, RETRY_AFTER_CAP_SECONDS) if ra is not None else None)
            if code == 200:                                   # ok:false なのに 200 は届いたか分からない
                return ProviderError(AMBIGUOUS, "unexpected_body", status=code)
            return classify_http(code, headers) or ProviderError(AMBIGUOUS, "unexpected_body", status=code)
        if err is None and not (isinstance(body, dict) and body.get("ok") is True):
            return ProviderError(AMBIGUOUS, "unexpected_body", status=int(status))   # 成功の形でない 2xx
        if err is None and not self.extract_delivery_id(status, headers, body):
            # ok=true なのに message_id が無い: 送れたか確かめられない（届いたか不明。自動で出し直さない）
            return ProviderError(AMBIGUOUS, "missing_message_id", status=int(status))
        return err

    def extract_delivery_id(self, status, headers, body) -> str:
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
        logger.info("ACTIONABLE_NOW %s\n%s", key, redact(payload.get("content")))
        return 200, {}, {"id": f"log:{key}:{datetime.now().strftime('%Y%m%dT%H%M%S')}"}

    def build_payload(self, record: dict) -> dict:
        return {"content": fit_message(record, self.max_length)}

    def extract_delivery_id(self, status, headers, body) -> str:
        return str((body or {}).get("id") or "") if isinstance(body, dict) else ""


ADAPTERS = {"discord": DiscordAdapter, "telegram": TelegramAdapter, "log": LogAdapter}


def default_adapters() -> dict:
    """既定: transport を渡さない（Discord・Telegram は未設定。送信は起きない）。"""
    return {"discord": DiscordAdapter(), "telegram": TelegramAdapter(), "log": LogAdapter()}


# ── 本番の送信の最終の関門 ─────────────────────────────────────────────────

def _dry(env) -> bool:
    from src.notifiers import actionable as an
    return an.is_dry_run(env)                   # dry-run の判定は1か所（空・読めない値は dry-run。レビュー L-2）


def _flag(env, key: str, default: str) -> bool:
    return str(env.get(key, default)).strip().lower() in ("true", "1", "yes", "on")


def real_send_gate(env=None, purpose: str = "product") -> dict:
    """本番の送信を有効にしてよいか（全部そろったときだけ allowed）。既定はすべて閉じる。値は返さない。

    purpose="product"（商品の通知）: PRODUCT_REAL_SEND_ENABLED が False なので常に閉じる（Phase 22）。
    purpose="canary"（Telegram の接続の試験の1件）: 次がすべてそろうときだけ開く。
      1) 選んだ配信先が Telegram だけ（NOTIFICATION_PROVIDERS=telegram。Discord は無効）で、送信の部品がある
      2) NOTIFICATION_REAL_SEND=true（ユーザーの明示の許可。リポジトリの変数。既定 false）
      3) NOTIFICATION_DRY_RUN=false（既定 true） 4) TELEGRAM_CANARY=true（接続の試験の明示の旗）
      5) 手動の実行（GITHUB_EVENT_NAME=workflow_dispatch。定時の実行では送らない）
      6) Telegram の設定（TELEGRAM_BOT_TOKEN・TELEGRAM_CHAT_ID）がそろって形が正しい
    """
    e = env if env is not None else os.environ
    providers = [p.strip().lower() for p in str(e.get("NOTIFICATION_PROVIDERS") or "").split(",") if p.strip()]
    if purpose == "canary":
        implemented = providers == ["telegram"] and "telegram" in IMPLEMENTED_PROVIDERS
    else:
        implemented = PRODUCT_REAL_SEND_ENABLED and bool(providers) and set(providers) <= IMPLEMENTED_PROVIDERS
    checks = {"implemented": implemented,
              "real_send_flag": _flag(e, "NOTIFICATION_REAL_SEND", "false"),
              "dry_run_off": not _dry(e),
              "provider_selected": providers == ["telegram"]}
    if purpose == "canary":
        checks["canary_flag"] = _flag(e, "TELEGRAM_CANARY", "false")
        checks["manual_dispatch"] = str(e.get("GITHUB_EVENT_NAME") or "") == "workflow_dispatch"
    config = {p: ADAPTERS[p]().validate_config(e) for p in providers if p in ("discord", "telegram")}
    checks["config_valid"] = bool(config) and all(not v for v in config.values())
    return {"allowed": all(checks.values()), "checks": checks, "providers": providers, "purpose": purpose,
            "config_problems": {p: v for p, v in config.items() if v}}


def telegram_configured(env=None) -> bool:
    """Telegram の設定がそろって形が正しいか（値は返さない）。"""
    return not TelegramAdapter().validate_config(env)
