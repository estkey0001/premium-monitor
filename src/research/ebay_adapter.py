"""eBay の二次流通アダプター（出品 = Browse API／成約 = Marketplace Insights API）。secondary_refresh に登録される。

方針（新しい仕組みは作らない。既存の OAuth・成約の検索の部品 src/collectors/api/ebay_insights.py を再利用する）:
- 資格情報が無ければ NOT_CONFIGURED。**通信しない**（token も取りに行かない）。例外も出さない。
- 資格情報があっても、ENABLE_EBAY_API=true でなければ BLOCKED（通信 0）。API_DRY_RUN=true でも通信しない。
- 出品（LISTING）は希望価格であり、成約価格ではない。Browse API は出品中の固定価格だけ（オークションの現在価格は取らない）。
- 成約（SOLD）は Marketplace Insights（審査制）だけ。承認・ライセンスの確認（EBAY_INSIGHTS_APPROVED / EBAY_SOLD_LICENSE_CONFIRMED）が
  そろわない間は sold_access = PENDING_APPROVAL。出品だけ取れたら市場の状態は PARTIAL で、SOLD の中央値は作らない。
- 価格は原通貨のまま保存する（price_original / currency）。円換算（price_jpy）は、為替が確認できたとき（fx_status = CONFIRMED）だけ。
  為替が未確認なら price_jpy を持たない → 利益ルートは NOT_CALCULATED（USD をそのまま円の利益に使わない）。
- 海外の出品を国内で仕入れる計算（送料・関税）は未実装。cross_border_cost_unknown の理由で、ルート C / D の仕入れ候補にしない。
- 同一性は camera_routes.identity_ok（GR IV / GR IV HDF / GR IV Monochrome / GR IIIx / X100VI を混ぜない）で厳密に照合する。
- 実通信は ebay_insights.http_get / fetch_token だけ（テストでは差し替える）。応答の形は eBay の公式仕様に沿うが、資格情報が無いので
  実通信での成功は未確認（モックの契約テストだけ）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src.research import camera_routes as cr
from src.research import secondary_markets as sm

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
FX_PATH = PROJECT_ROOT / "config" / "fx_rates.yaml"

MARKETPLACE_ID = "EBAY_US"
SOURCE_LISTING, SOURCE_SOLD = "ebay_browse_api", "ebay_insights"
MAX_REQUESTS = 24                     # 1 回の実行の検索リクエストの上限（再試行を含む）
BROWSE_LIMIT = 50
FX_MAX_AGE_DAYS = 3                   # 為替の確認日（updated_at）がこれより古いと円換算しない

# 初回の対象（機種名は研究データの名前。検索語は eBay 向けの英語）
FIRST_PRODUCTS = (
    ("RICOH GR IV", "Ricoh GR IV"),
    ("RICOH GR IV HDF", "Ricoh GR IV HDF"),
    ("RICOH GR IV Monochrome", "Ricoh GR IV Monochrome"),
    ("FUJIFILM X100VI", "Fujifilm X100VI"),
)

# eBay の conditionId → 状態。UNKNOWN は条件が読めないもの。整備品・傷あり・ジャンクは混ぜない（_REJECT）
_COND = {"1000": cr.UNOPENED, "1500": cr.LIKE_NEW, "2750": cr.LIKE_NEW, "3000": cr.USED, "4000": cr.USED, "5000": cr.USED, "6000": cr.USED}
_COND_REJECT = {"1750": "new_with_defects", "2000": "refurbished", "2010": "refurbished", "2020": "refurbished", "2030": "refurbished",
                "2500": "refurbished", "7000": "for_parts"}
_COND_TEXT = (("new", cr.UNOPENED), ("open box", cr.LIKE_NEW), ("new other", cr.LIKE_NEW), ("like new", cr.LIKE_NEW), ("used", cr.USED))
_ACCESSORY_WORD = re.compile(r"(?i)\b(case|strap|battery|batteries|charger|manual|instruction|protector|lens cap|cap|hood|cover|pouch|bag|sticker|decal|"
                             r"grip|guard|tripod|cage|adapter|accessor(?:y|ies)|screen|glass|filter ring|hot shoe)\b")
_ACCESSORY_ONLY = re.compile(r"(?i)\bonly\b|\b(for|fits?|compatible|replacement|designed for)\b|\blot of\b|\bno camera\b|付属品のみ|ケースのみ")
_BODY_WORD = re.compile(r"(?i)\b(camera|body|digital|mirrorless|kit)\b")


def is_accessory_only(title: str) -> bool:
    """付属品・アクセサリーだけの出品か。正しい本体 + アクセサリーのセット（"X100VI Digital Camera with case"）は除外しない。
    除外: (1) 「only / for / fits / compatible / replacement」を伴う付属品語、(2) 本体を表す語（camera / body / digital / mirrorless / kit）が無く付属品語がある、
    (3) 題名が付属品語で始まる（"Screen Protector X100VI Camera"）。"""
    t = str(title or "")
    m = _ACCESSORY_WORD.search(t)
    if not m:
        return bool(re.search(r"(?i)\bbox only\b|\bempty box\b|\bno camera\b|付属品のみ|ケースのみ", t))
    if _ACCESSORY_ONLY.search(t) or not _BODY_WORD.search(t):
        return True
    return m.start() == 0 or bool(re.match(r"(?i)\s*(screen|tempered|replacement|leather|silicone|metal)\b", t))


_PARTS = re.compile(r"(?i)for parts|not working|broken|as[- ]is|junk|defective|ジャンク|故障|部品取り")
INSIGHTS_CONDITION_IDS = ("1000", "1500", "2750", "3000", "4000", "5000")


@dataclass
class AdapterResult:
    """アダプターが返す共通の形。records は research_camera_*.json の機種レコード（listing / sold）と同じ形。"""
    market: str
    status: str                                   # AVAILABLE / PARTIAL / NOT_CONFIGURED / PENDING_APPROVAL / BLOCKED / FAILED
    reason: str
    listing_access: str
    sold_access: str
    checked_at: Optional[str] = None
    records: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)     # 件数だけ（秘密の値・自由記述を入れない）

    def public(self) -> dict:
        return {"status": self.status, "reason": self.reason, "listing_access": self.listing_access, "sold_access": self.sold_access,
                "checked_at": self.checked_at, "stats": dict(self.stats)}


def _truthy(env, name: str) -> bool:
    return str((env or {}).get(name) or "").strip().lower() in ("true", "1", "yes", "on")


def has_credentials(env) -> bool:
    cid = (env or {}).get("EBAY_CLIENT_ID") or (env or {}).get("EBAY_APP_ID")        # 空白だけの値は未設定
    return bool(str(cid or "").strip()) and bool(str((env or {}).get("EBAY_CLIENT_SECRET") or "").strip())


def gates(env) -> dict:
    """条件の有無だけ（値は返さない）。"""
    return {"credentials": has_credentials(env), "enabled": _truthy(env, "ENABLE_EBAY_API"), "dry_run": _truthy(env, "API_DRY_RUN"),
            "insights_approved": _truthy(env, "EBAY_INSIGHTS_APPROVED"), "sold_license_confirmed": _truthy(env, "EBAY_SOLD_LICENSE_CONFIRMED")}


# ---------------------------------------------------------------- 為替
def fx_state(currency: str, now: datetime, path: Path = FX_PATH) -> dict:
    """為替の状態。JPY は不要。USD などは config/fx_rates.yaml の <通貨>_JPY と updated_at が新しいときだけ CONFIRMED。
    古い・読めない・無い場合は UNKNOWN（円換算しない）。"""
    cur = str(currency or "").upper()
    if cur == "JPY":
        return {"status": "NOT_NEEDED", "rate": 1.0, "checked_at": None, "currency": cur}
    out = {"status": "UNKNOWN", "rate": None, "checked_at": None, "currency": cur}
    try:
        import yaml
        y = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        rate = (y.get("fx_rates") or {}).get(f"{cur}_JPY")
        m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", str(y.get("updated_at") or ""))
        if not m:
            return out
        d = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        out["checked_at"] = d.isoformat()
        age = (now.date() - d).days
        if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0 and 0 <= age <= FX_MAX_AGE_DAYS:
            out.update(status="CONFIRMED", rate=float(rate))
    except Exception:  # noqa: BLE001 - 読めなければ未確認
        pass
    return out


def credential_shape(env) -> dict:
    """資格情報の「形」だけ（値・先頭文字は返さない）。環境名（Client ID に含まれる -PRD- / -SBX-）・文字数・途中の空白の有無。
    Sandbox と Production の取り違え、貼り付けの混入の切り分けに使う。"""
    cid = str((env or {}).get("EBAY_CLIENT_ID") or (env or {}).get("EBAY_APP_ID") or "").strip()
    sec = str((env or {}).get("EBAY_CLIENT_SECRET") or "").strip()
    tag = "PRD" if "-PRD-" in cid.upper() else "SBX" if "-SBX-" in cid.upper() else "UNKNOWN"
    return {"client_id_environment": tag, "client_id_length": len(cid), "client_secret_length": len(sec),
            "client_id_has_inner_whitespace": bool(re.search(r"\s", cid)), "client_secret_has_inner_whitespace": bool(re.search(r"\s", sec)),
            "client_id_has_quote_or_ctrl": bool(re.search(r"[\"'\x00-\x1f]", cid)), "client_secret_has_quote_or_ctrl": bool(re.search(r"[\"'\x00-\x1f]", sec))}


def _convert(value: float, currency: str, fx: dict) -> Optional[int]:
    """為替が確認できる（JPY・または CONFIRMED）ときだけ円にする。"""
    if currency == "JPY":
        return int(round(value))
    if fx.get("status") == "CONFIRMED" and fx.get("rate"):
        return int(round(value * float(fx["rate"])))
    return None


# ---------------------------------------------------------------- 共通の正規化
def _item_url(item: dict) -> str:
    from src.collectors.api import ebay_insights as ei
    return ei.normalize_item_url(item)


def _condition(item: dict) -> tuple[str, Optional[str]]:
    """(状態, 除外の理由)。conditionId を優先し、無ければ condition の文言。読めなければ UNKNOWN。"""
    cid = str(item.get("conditionId") or "").strip()
    if cid in _COND_REJECT:
        return cr.UNKNOWN, _COND_REJECT[cid]
    if cid in _COND:
        return _COND[cid], None
    txt = str(item.get("condition") or "").strip().lower()
    for k, v in _COND_TEXT:
        if txt == k:
            return v, None
    return cr.UNKNOWN, None


def _money(d) -> tuple[Optional[float], str]:
    try:
        v = float((d or {}).get("value"))
        c = str((d or {}).get("currency") or "").upper()
        return (v, c) if v > 0 and re.fullmatch(r"[A-Z]{3}", c) else (None, "")
    except (TypeError, ValueError):
        return None, ""


def _classify(product: str, item: dict, stats: dict) -> Optional[tuple[str, Optional[str]]]:
    """同一性・状態の検査。通れば (状態, None)、落ちれば None（stats に理由別の件数を足す）。
    状態が UNKNOWN のものは残す（表示はできるが、ルート C / D の実行には使われない）。"""
    title = str(item.get("title") or "")
    ok, _why = cr.identity_ok(product, title)
    if ok and is_accessory_only(title):                    # 英語のアクセサリ・付属品だけの出品（identity_ok は日本語中心）
        ok = False
    if not ok:
        stats["rejected_identity"] = stats.get("rejected_identity", 0) + 1
        return None
    cond, rej = _condition(item)
    if rej or _PARTS.search(title):
        stats["rejected_condition"] = stats.get("rejected_condition", 0) + 1
        return None
    return cond, None


# ---------------------------------------------------------------- 出品（Browse API）
def build_browse_request(query: str, *, limit: int = BROWSE_LIMIT) -> tuple[str, dict]:
    """出品中の固定価格だけ（オークションの現在価格は希望価格ではない）。日本への発送が可能なものに絞る。
    URL の組み立ては ebay_insights（通信の部品。src/research は取得のモジュールを import しない決まり）。"""
    from src.collectors.api import ebay_insights as ei
    return ei.build_browse_request(query, limit=limit)


def parse_browse(payload) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    return [x for x in payload.get("itemSummaries") or [] if isinstance(x, dict)]


def listing_row(product: str, item: dict, *, now: datetime, checked_at: str, fx_cache: dict, stats: dict) -> Optional[dict]:
    """1 件の出品 → 行（原通貨を保存。円は為替が確認できたときだけ）。同一性・状態・価格・商品ページ URL・固定価格がそろわなければ None。"""
    cls = _classify(product, item, stats)
    if cls is None:
        return None
    cond = cls[0]
    price, cur = _money(item.get("price"))
    url = _item_url(item)
    if price is None or not url:
        stats["rejected_no_price_or_url"] = stats.get("rejected_no_price_or_url", 0) + 1
        return None
    opts = [str(b).upper() for b in item.get("buyingOptions") or []]
    if "FIXED_PRICE" not in opts or "AUCTION" in opts:         # 入札のある出品は、price が現在の入札額になりうる（希望価格ではない）
        stats["rejected_not_fixed_price"] = stats.get("rejected_not_fixed_price", 0) + 1
        return None                                        # オークションの現在価格は希望価格ではない
    if cur not in fx_cache:
        fx_cache[cur] = fx_state(cur, now)
    fx = fx_cache[cur]
    ship = None
    ship_cur = ""
    for o in item.get("shippingOptions") or []:
        v, c = _money((o or {}).get("shippingCost"))
        if v is not None and (ship is None or v < ship):
            ship, ship_cur = v, c
    loc = str((item.get("itemLocation") or {}).get("country") or "")[:2].upper()
    return {"market": "eBay", "item_title": str(item.get("title") or "")[:160], "condition": cond,
            "price_jpy": _convert(price, cur, fx), "price_original": price, "currency": cur,
            "fx_status": fx["status"], "fx_rate": fx.get("rate") if fx["status"] == "CONFIRMED" else None, "fx_checked_at": fx.get("checked_at"),
            "shipping_original": ship, "shipping_currency": ship_cur or None, "shipping_status": "KNOWN_ORIGINAL" if ship is not None else "UNKNOWN",
            "import_duty_status": "UNKNOWN", "location": loc or None, "region": MARKETPLACE_ID,
            "url": url, "checked_at": checked_at, "purchasable_now": True, "price_type": "LISTING", "source": SOURCE_LISTING, "result": "FOUND"}


# ---------------------------------------------------------------- 成約（Marketplace Insights）
def sold_row(product: str, item: dict, *, now: datetime, checked_at: str, fx_cache: dict, stats: dict) -> Optional[dict]:
    """1 件の成約 → 行。成約日時・商品ページ URL・価格・同一性・状態がそろうものだけ。成約日時が無ければ取得時刻で代用しない。"""
    cls = _classify(product, item, stats)
    if cls is None:
        return None
    price, cur = _money(item.get("lastSoldPrice"))
    url = _item_url(item)
    sold_at = str(item.get("lastSoldDate") or "")
    if price is None or not url or not sold_at:
        stats["rejected_no_price_or_url"] = stats.get("rejected_no_price_or_url", 0) + 1
        return None
    if cur not in fx_cache:
        fx_cache[cur] = fx_state(cur, now)
    fx = fx_cache[cur]
    return {"market": "eBay", "item_title": str(item.get("title") or "")[:160], "condition": cls[0],
            "price_jpy": _convert(price, cur, fx), "price_original": price, "currency": cur,
            "fx_status": fx["status"], "fx_rate": fx.get("rate") if fx["status"] == "CONFIRMED" else None, "fx_checked_at": fx.get("checked_at"),
            "url": url, "sold_at": sold_at, "checked_at": checked_at, "region": MARKETPLACE_ID, "price_type": "SOLD",
            "source": SOURCE_SOLD, "result": "FOUND"}


def _page(http_get: Callable, token: str, url: str, headers: dict, budget: list) -> dict:
    from src.collectors.api import api_runtime as rt
    budget[0] -= 1
    res = rt.retry_with_backoff(lambda: http_get(url, {**headers, "Authorization": f"Bearer {token}"}),
                                max_retries=max(0, min(2, budget[0])), breaker=rt.CircuitBreaker(threshold=3))
    budget[0] -= max(0, int(res.get("attempts") or 0) - 1)
    return res


def _err_kind(res: dict) -> str:
    return str(res.get("error_kind") or "failed")


# ---------------------------------------------------------------- 本体
def fetch(market_id: str, env, *, http_get: Optional[Callable] = None, token_fn: Optional[Callable] = None,
          now: Optional[datetime] = None, products=FIRST_PRODUCTS) -> AdapterResult:
    """secondary_refresh から呼ばれる。資格情報・有効化・dry-run のどれかが欠けたら通信 0 で状態だけを返す。
    実通信は http_get / token_fn（既定は ebay_insights の実体）。失敗は FAILED で返す（空として扱わない）。"""
    now = now or datetime.now(JST)
    checked_at = now.isoformat(timespec="seconds")
    g = gates(env)
    base = dict(market=market_id, checked_at=checked_at)
    if not g["credentials"]:
        return AdapterResult(status=sm.NOT_CONFIGURED, reason="official_api_not_configured", listing_access=sm.NOT_CONFIGURED,
                             sold_access=sm.NOT_CONFIGURED, stats={"requests": 0}, **base)
    if not g["enabled"]:
        return AdapterResult(status=sm.BLOCKED, reason="official_api_not_enabled", listing_access=sm.BLOCKED, sold_access=sm.BLOCKED,
                             stats={"requests": 0}, **base)
    if g["dry_run"]:
        return AdapterResult(status=sm.BLOCKED, reason="api_dry_run", listing_access=sm.BLOCKED, sold_access=sm.BLOCKED,
                             stats={"requests": 0}, **base)
    from src.collectors.api import ebay_insights as ei
    http_get = http_get or ei.http_get
    token_fn = token_fn or ei.fetch_token
    stats: dict = {"requests": 0, "items_found": 0, "items_matched": 0, "listing_matched": 0, "sold_matched": 0}
    budget = [MAX_REQUESTS]
    fx_cache: dict = {}
    records: dict = {p: {"product": p, "listing": [], "sold": []} for p, _ in products}

    # 出品（Browse）。token の失敗は、資格情報の誤り（FAILED）
    tok, tst = token_fn(ei.BROWSE_SCOPE)
    if not tok:
        return AdapterResult(status=sm.FAILED, reason=f"browse_token_{str(tst).lower()}", listing_access=sm.FAILED, sold_access=sm.FAILED,
                             stats=stats, **base)
    listing_ok = True
    seen: set = set()
    for product, q in products:
        if budget[0] <= 0:
            listing_ok = False
            stats["budget_exhausted"] = True
            break
        url, headers = build_browse_request(q)
        res = _page(http_get, tok, url, headers, budget)
        stats["requests"] = MAX_REQUESTS - budget[0]
        if not res["ok"]:
            listing_ok = False
            stats["listing_error"] = _err_kind(res)
            break
        items = parse_browse(res["data"])
        stats["items_found"] += len(items)
        for it in items:
            row = listing_row(product, it, now=now, checked_at=checked_at, fx_cache=fx_cache, stats=stats)
            if row is None or row["url"] in seen:
                continue
            seen.add(row["url"])
            records[product]["listing"].append(row)
            stats["listing_matched"] += 1

    # 成約（Insights）。承認とライセンスの確認がそろうまで PENDING_APPROVAL（通信 0）
    sold_access, sold_reason = sm.PENDING_APPROVAL, "ebay_insights_not_approved"
    if g["insights_approved"] and not g["sold_license_confirmed"]:
        sold_reason = "sold_license_unconfirmed"
    if g["insights_approved"] and g["sold_license_confirmed"]:
        stok, sst = token_fn(ei.SCOPE)
        if not stok:
            sold_access, sold_reason = ((sm.PENDING_APPROVAL, "ebay_insights_not_approved") if sst == ei.ST_PENDING_APPROVAL
                                        else (sm.FAILED, f"insights_token_{str(sst).lower()}"))
        else:
            sold_access, sold_reason = sm.AVAILABLE, "insights_ok"
            sold_seen: set = set()
            incomplete = False
            for product, q in products:
                offset, pages = 0, 0
                if budget[0] <= 0:
                    incomplete = True                      # 上限に達して、この商品の成約を取れていない
                    break
                while offset is not None and pages < ei.MAX_PAGES and budget[0] > 0:
                    url, headers = ei.build_search_request(q=q, sold_from=now - timedelta(days=90), sold_to=now,
                                                           condition_ids=INSIGHTS_CONDITION_IDS, offset=offset)
                    pages += 1
                    res = _page(http_get, stok, url, headers, budget)
                    stats["requests"] = MAX_REQUESTS - budget[0]
                    if not res["ok"]:
                        kind = _err_kind(res)
                        stats["sold_error"] = kind
                        sold_access, sold_reason = ((sm.PENDING_APPROVAL, "ebay_insights_not_approved") if kind in ("permanent_403", "permanent_400")
                                                    else (sm.FAILED, "insights_request_failed"))
                        break
                    items, offset = ei.parse_item_sales(res["data"] or {})
                    stats["items_found"] += len(items)
                    if offset is not None and pages >= ei.MAX_PAGES:
                        stats["truncated"] = True            # ページの上限で切れた（全件ではない）
                    for it in items:
                        row = sold_row(product, it, now=now, checked_at=checked_at, fx_cache=fx_cache, stats=stats)
                        if row is None or row["url"] in sold_seen:
                            continue
                        sold_seen.add(row["url"])
                        records[product]["sold"].append(row)
                        stats["sold_matched"] += 1
                if sold_access != sm.AVAILABLE:
                    break
            if (incomplete or stats.get("truncated")) and sold_access == sm.AVAILABLE:
                stats["budget_exhausted"] = bool(incomplete)
                sold_access, sold_reason = sm.FAILED, "sold_incomplete"      # 全件でない成約から中央値を作らない（行は捨てる）
    stats["items_matched"] = stats["listing_matched"] + stats["sold_matched"]
    stats["fx"] = {c: {"status": f["status"], "checked_at": f.get("checked_at")} for c, f in fx_cache.items()}
    stats["approval"] = {"insights_approved": g["insights_approved"], "sold_license_confirmed": g["sold_license_confirmed"]}
    stats["requests"] = MAX_REQUESTS - budget[0]
    la = sm.AVAILABLE if listing_ok else sm.FAILED
    if la == sm.FAILED and sold_access == sm.AVAILABLE:
        status, reason = sm.PARTIAL, "listing_failed_sold_ok"
    elif la == sm.FAILED:
        status, reason = sm.FAILED, f"listing_{stats.get('listing_error', 'failed')}"
    elif sold_access == sm.AVAILABLE:
        status, reason = sm.AVAILABLE, "api_ok"
    else:
        status, reason = sm.PARTIAL, "api_listing_only" if sold_access == sm.PENDING_APPROVAL else sold_reason
        stats["sold_reason"] = sold_reason
    for rec_ in records.values():                    # 失敗した側の途中までの行は捨てる（FAILED / 未承認なのに行だけ採用される二重の状態にしない）
        if la != sm.AVAILABLE:
            rec_["listing"] = []
        if sold_access != sm.AVAILABLE:
            rec_["sold"] = []
    return AdapterResult(status=status, reason=reason, listing_access=la, sold_access=sold_access,
                         records=[r for r in records.values() if r["listing"] or r["sold"]], stats=stats, **base)


# ---------------------------------------------------------------- canary（1 商品・最小件数・成約には通信しない）
CANARY_PRODUCT = ("FUJIFILM X100VI", "Fujifilm X100VI")
CANARY_LIMIT = 10


def browse_canary(env, *, http_get: Optional[Callable] = None, token_fn: Optional[Callable] = None, now: Optional[datetime] = None,
                  product=CANARY_PRODUCT, limit: int = CANARY_LIMIT) -> dict:
    """Production の Browse API へ、1 商品・1 リクエストだけ送って結果を報告する（成約 API には一切通信しない）。
    報告は件数・状態・出品の公開情報（題名・価格・URL など）だけ。資格情報・token・Authorization は含めない。
    通信するのは、資格情報・ENABLE_EBAY_API=true・API_DRY_RUN が false のときだけ。"""
    from src.collectors.api import ebay_insights as ei
    now = now or datetime.now(JST)
    g = gates(env)
    rep: dict = {"product": product[0], "checked_at": now.isoformat(timespec="seconds"),
                 "credentials_detected": g["credentials"], "flags": {"enable_ebay_api": g["enabled"], "api_dry_run": g["dry_run"],
                                                                      "insights_approved": g["insights_approved"], "sold_license_confirmed": g["sold_license_confirmed"]},
                 "sold": {"requests": 0, "status": "PENDING_APPROVAL", "note": "Marketplace Insights は審査制（新規は制限あり）。今回は通信しない"},
                 "profit": "NOT_CALCULATED"}
    if not g["credentials"] or not g["enabled"] or g["dry_run"]:
        rep.update(oauth={"status": "NOT_ATTEMPTED"}, browse={"requests": 0},
                   verdict_hint="BLOCKED:" + ("no_credentials" if not g["credentials"] else "not_enabled" if not g["enabled"] else "api_dry_run"))
        return rep
    http_get = http_get or ei.http_get
    token_fn = token_fn or ei.fetch_token
    tok, tst = token_fn(ei.BROWSE_SCOPE)
    rep["oauth"] = {"status": "SUCCESS" if tok else "FAILED", "detail": str(tst)}
    if not tok:                                                          # 失敗の診断（HTTP の状態と eBay のエラーコードだけ）
        rep["oauth"].update({k: v for k, v in getattr(ei, "LAST_TOKEN_ERROR", {}).items() if k in ("http_status", "error")})
        rep["oauth"]["credential_shape"] = credential_shape(env)
    if not tok:
        rep.update(browse={"requests": 0}, verdict_hint="BLOCKED:oauth_" + str(tst).lower())
        return rep
    url, headers = build_browse_request(product[1], limit=limit)
    res = _page(http_get, tok, url, headers, [1])                      # 1 リクエスト・再試行なし
    data = res.get("data") if res.get("ok") else None
    br: dict = {"requests": 1, "http_status": res.get("status"), "ok": bool(res.get("ok")), "error_kind": res.get("error_kind")}
    rep["browse"] = br
    if not res.get("ok"):
        rep["verdict_hint"] = "BLOCKED:browse_http_" + str(res.get("status"))
        return rep
    items = parse_browse(data)
    first = items[0] if items else {}
    br["schema"] = {"top_level_keys": sorted(str(k) for k in (data or {}).keys())[:20], "item_keys": sorted(str(k) for k in first.keys())[:40],
                    "total": (data or {}).get("total"), "has_item_summaries": "itemSummaries" in (data or {})}
    br["returned"] = len(items)
    fx_cache: dict = {}
    matched, rejected, rej_rows = [], {}, []
    for it in items:
        st: dict = {}
        row = listing_row(product[0], it, now=now, checked_at=rep["checked_at"], fx_cache=fx_cache, stats=st)
        if row is None:
            why = next(iter(st), "unknown")
            rejected[why] = rejected.get(why, 0) + 1
            rej_rows.append({"title": str(it.get("title") or "")[:120], "reason": why})
        else:
            matched.append(row)
    br["matched"] = len(matched)
    br["rejected"] = {"total": sum(rejected.values()), "by_reason": rejected}
    rep["listings"] = [{"item_id": str(x["url"]).rsplit("/", 1)[-1], "title": x["item_title"], "price": x["price_original"], "currency": x["currency"],
                        "condition": x["condition"], "shipping": x.get("shipping_original"), "shipping_currency": x.get("shipping_currency"),
                        "location": x.get("location"), "url": x["url"], "checked_at": x["checked_at"], "fx_status": x["fx_status"]} for x in matched[:5]]
    rep["rejected_examples"] = rej_rows[:10]
    rep["fx"] = {c: {"status": f["status"], "checked_at": f.get("checked_at")} for c, f in fx_cache.items()}
    rep["verdict_hint"] = "PASS" if matched else "PARTIAL:no_matched_items"
    return rep
