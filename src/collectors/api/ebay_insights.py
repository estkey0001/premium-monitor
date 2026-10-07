"""eBay Marketplace Insights API（成約の履歴）のアダプター（Phase 12。本番では未起動）。

背景:
- 以前使っていた Finding API（findItemsByKeywords・findCompletedItems）は 2025-02-05 に廃止された。
- 成約（売れた価格・成約日時）を取れる公式の経路は Marketplace Insights API（item_sales/search）だけで、
  eBay の審査で許可された開発者だけが使える（Limited Release）。過去90日の成約を返す。
- 認証は OAuth のクライアント認証（client_credentials）。必要な Secret は EBAY_CLIENT_ID（または EBAY_APP_ID）と
  EBAY_CLIENT_SECRET。どちらかが無ければ PENDING_USER_CONFIGURATION（取りに行かない）。
- 許可（scope buy.marketplace.insights）が無いと token の取得が invalid_scope などで失敗する → ACCESS_NOT_GRANTED。

安全:
- 秘密の値（client_secret・access token・Authorization ヘッダー）はログ・生成物・例外の文言に出さない（redact）
- ENABLE_EBAY_API=true の明示が無ければ使わない。dry-run（API_DRY_RUN）・段階（EBAY_API_STAGE。既定は1商品の canary）を守る。
  canary の合格（exports/sold_history/canary.json）が無ければ段階を上げても1商品のまま
- 429 は無制限に再試行しない（api_runtime.retry_with_backoff: 最大4回・Retry-After を優先）。1回の実行のリクエスト数に上限
- 生の応答は公開の HTML に出さない（このモジュールは SoldRecord に変換したものだけを返す）

成約1件にするのは、1件の商品ページの URL（https://www.ebay.com/itm/<番号>）・成約日時（lastSoldDate）・
商品の同一性（ProductIdentityResolver が同じ商品と判定）・状態（conditionId）がそろったものだけ。
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Callable, Optional

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search"
SCOPE = "https://api.ebay.com/oauth/api_scope/buy.marketplace.insights"
MARKETPLACE_ID = "EBAY_US"
MAX_LIMIT = 200            # 1ページの最大件数
MAX_PAGES = 3              # 1商品あたりのページ数の上限（取りすぎない）
MAX_REQUESTS_PER_RUN = 30  # 1回の実行の検索リクエストの上限（token を除く）
SOURCE = "ebay_insights"

# eBay の conditionId → 状態（normalized の名前）。分からない状態は使わない
# （中古の等級は eBay の段階と国内の等級が1対1に対応しないので、まとめて used にする。監査 L4）
CONDITION_MAP = {"1000": "new_unopened", "1500": "new_opened", "2750": "used", "3000": "used",
                 "4000": "used", "5000": "used"}

ST_PENDING = "PENDING_USER_CONFIGURATION"
ST_DISABLED = "DISABLED"
ST_DRY_RUN = "DRY_RUN"
ST_ACCESS = "ACCESS_NOT_GRANTED"
ST_OK = "OK"
ST_ERROR = "ERROR"

# eBay の token は v^1.1#i^1#... のように ^ や # を含むので、空白・引用符・区切りまでをすべて伏せる（監査 M1）
_SECRET_PATTERNS = (re.compile(r"(Bearer|Basic)\s+[^\s\"',;}]+"),
                    re.compile(r"(access_token|client_secret|refresh_token)[\"']?\s*[:=]\s*[\"']?[^\s\"',}]+"))


def redact(text: str) -> str:
    """秘密の値を伏せる（ログ・例外の文言に使う）。環境変数の秘密の値そのものも伏せる。"""
    s = str(text or "")
    for p in _SECRET_PATTERNS:
        s = p.sub(lambda m: m.group(1) + " ***", s)
    for k in ("EBAY_CLIENT_SECRET", "EBAY_CLIENT_ID", "EBAY_APP_ID"):
        v = os.environ.get(k)
        if v and len(v) >= 6:
            s = s.replace(v, "***")
    return s


def credentials() -> Optional[tuple[str, str]]:
    cid = os.environ.get("EBAY_CLIENT_ID") or os.environ.get("EBAY_APP_ID")
    sec = os.environ.get("EBAY_CLIENT_SECRET")
    return (cid, sec) if cid and sec else None


def status() -> str:
    """今の状態（秘密の値は返さない）。

    成約の API は、資格情報があっても ENABLE_EBAY_API=true を明示したときだけ使う（未設定は停止。監査 M6）。
    """
    from src.collectors.api import api_runtime as rt
    if not credentials():
        return ST_PENDING
    if (os.environ.get("ENABLE_EBAY_API", "") or "").strip().lower() not in ("true", "1", "yes", "on") \
            or rt.kill_switch_on("ebay"):
        return ST_DISABLED
    if rt.is_dry_run():
        return ST_DRY_RUN
    return ST_OK


def build_search_request(*, q: str = "", gtin: str = "", category_ids: str = "",
                         sold_from: Optional[datetime] = None, sold_to: Optional[datetime] = None,
                         condition_ids: tuple[str, ...] = ("1000",), limit: int = MAX_LIMIT,
                         offset: int = 0) -> tuple[str, dict]:
    """検索の URL と（認証以外の）ヘッダー。Authorization は呼ぶ直前に付ける（ここには入れない）。"""
    if not (q or gtin or category_ids):
        raise ValueError("q・gtin・category_ids のどれかが必要")
    filters = []
    if sold_from and sold_to:
        f = lambda d: d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")  # noqa: E731
        filters.append(f"lastSoldDate:[{f(sold_from)}..{f(sold_to)}]")
    if condition_ids:
        filters.append("conditionIds:{" + "|".join(condition_ids) + "}")
    params = {"limit": str(max(1, min(int(limit), MAX_LIMIT))), "offset": str(max(0, int(offset)))}
    if q:
        params["q"] = q
    if gtin:
        params["gtin"] = gtin
    if category_ids:
        params["category_ids"] = category_ids
    if filters:
        params["filter"] = ",".join(filters)
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params, safe=":[]{}|,")
    return url, {"X-EBAY-C-MARKETPLACE-ID": MARKETPLACE_ID, "Accept": "application/json"}


def token_request() -> Optional[tuple[str, dict, bytes]]:
    """token を取るリクエスト（URL・ヘッダー・本文）。資格情報が無ければ None。ログに出さない。"""
    cred = credentials()
    if not cred:
        return None
    basic = base64.b64encode(f"{cred[0]}:{cred[1]}".encode()).decode()
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": SCOPE}).encode()
    return TOKEN_URL, {"Authorization": f"Basic {basic}",
                       "Content-Type": "application/x-www-form-urlencoded"}, body


def normalize_item_url(item: dict) -> str:
    """商品ページの URL（https://www.ebay.com/itm/<番号>）。番号が読めなければ空。"""
    url = str(item.get("itemWebUrl") or "")
    m = re.search(r"/itm/(?:[^/?#]+/)?(\d{9,15})", url)
    if not m:
        iid = str(item.get("itemId") or "")
        m = re.search(r"\|(\d{9,15})\|", iid) or re.fullmatch(r"(\d{9,15})", iid)
    return f"https://www.ebay.com/itm/{m.group(1)}" if m else ""


def parse_item_sales(payload: dict) -> tuple[list[dict], Optional[int]]:
    """応答の itemSales と、次のページの offset（無ければ None）。形が違えば空。"""
    if not isinstance(payload, dict):
        return [], None
    items = [x for x in payload.get("itemSales") or [] if isinstance(x, dict)]
    nxt = None
    try:
        total, off, lim = int(payload.get("total") or 0), int(payload.get("offset") or 0), int(payload.get("limit") or 0)
        if payload.get("next") and lim and off + lim < total:
            nxt = off + lim
    except (TypeError, ValueError):
        nxt = None
    return items, nxt


def to_sold_records(items: list[dict], *, product_id: str, resolver, fx_rate: Optional[float],
                    now: datetime) -> tuple[list, dict]:
    """itemSales を SoldRecord にする（同一性・商品ページ・成約日時・状態・価格がそろったものだけ）。

    戻り値: (SoldRecord の一覧, {理由: 件数}（使わなかった理由）)
    """
    from src.market.sold_history import SoldRecord, record_reasons
    out, rejected = [], {}

    def _rej(r):
        rejected[r] = rejected.get(r, 0) + 1
    for it in items:
        url = normalize_item_url(it)
        sold_at = str(it.get("lastSoldDate") or "")          # 成約日時。無ければ使わない（取得時刻で代用しない）
        cond = CONDITION_MAP.get(str(it.get("conditionId") or ""), "")
        price = it.get("lastSoldPrice") or {}
        try:
            value = float(price.get("value"))
        except (TypeError, ValueError):
            _rej("no_price")
            continue
        cur = str(price.get("currency") or "")
        if cur == "JPY":
            jpy = int(round(value))
        elif cur == "USD" and fx_rate:
            jpy = int(round(value * float(fx_rate)))
        else:
            _rej("no_fx_rate")
            continue
        res = resolver.resolve(source_title=str(it.get("title") or ""), source_url=url,
                               condition=cond, link_type="item", expected_product_id=product_id)
        verified = (res.matched_product_id == product_id and res.identity_confidence == "high"
                    and not res.accessory_flag and res.capacity_match is not False and res.model_match is not False)
        rec = SoldRecord(product_id=product_id, source=SOURCE, item_url=url, sold_price=jpy, sold_at=sold_at,
                         condition=cond, identity=product_id, identity_verified=verified,
                         observed_at=now.isoformat(timespec="seconds"), currency=cur,
                         sold_price_original=value, title=str(it.get("title") or "")[:160],
                         note=(f"USD→JPY {fx_rate}" if cur == "USD" else ""))
        why = record_reasons(rec)
        if why:
            for w in why:
                _rej(w)
            continue
        out.append(rec)
    return out, rejected


def collect(product_id: str, query: str, *, resolver, now: datetime, fx_rate: Optional[float],
            http_get: Callable[[str, dict], dict], token: str, days: int = 90,
            request_budget: Optional[list] = None, sleep_fn: Optional[Callable[[float], None]] = None
            ) -> tuple[list, dict]:
    """1商品の成約を取る（ページを MAX_PAGES まで）。http_get(url, headers) は api_runtime の形の dict を返す。

    呼ぶ側が token を渡す（ここでは token を作らない・保存しない）。request_budget は [残り回数] の共有の箱。
    """
    from datetime import timedelta

    from src.collectors.api import api_runtime as rt
    budget = request_budget if request_budget is not None else [MAX_REQUESTS_PER_RUN]
    records, rejected, offset, pages = [], {}, 0, 0
    breaker = rt.CircuitBreaker(threshold=3)
    while offset is not None and pages < MAX_PAGES and budget[0] > 0:
        url, headers = build_search_request(q=query, sold_from=now - timedelta(days=days), sold_to=now,
                                            offset=offset)
        budget[0] -= 1
        pages += 1
        kw = {} if sleep_fn is None else {"sleep_fn": sleep_fn}
        res = rt.retry_with_backoff(lambda: http_get(url, {**headers, "Authorization": f"Bearer {token}"}),
                                    max_retries=2, breaker=breaker, **kw)
        if not res["ok"]:
            rejected["request_" + str(res.get("error_kind") or "failed")] = 1
            break
        items, offset = parse_item_sales(res["data"] or {})
        recs, rej = to_sold_records(items, product_id=product_id, resolver=resolver, fx_rate=fx_rate, now=now)
        records.extend(recs)
        for k, v in rej.items():
            rejected[k] = rejected.get(k, 0) + v
    return records, rejected


def dry_run_plan(targets: list[tuple[str, str]], now: datetime) -> dict:
    """本番に書き込まない確認用の出力（送るはずのリクエストの一覧。秘密の値は含めない）。"""
    from datetime import timedelta
    plan = []
    for pid, q in targets:
        url, headers = build_search_request(q=q, sold_from=now - timedelta(days=90), sold_to=now)
        plan.append({"product_id": pid, "url": url, "headers": headers})
    return {"status": status(), "token_url": TOKEN_URL, "scope": SCOPE,
            "credentials_present": bool(credentials()), "requests": plan}


def dumps_safe(obj) -> str:
    """生成物に書くときの JSON（秘密の値を伏せる）。"""
    return redact(json.dumps(obj, ensure_ascii=False))
