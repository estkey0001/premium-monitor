"""正規化価格観測（normalized price observations）の単一定義モジュール。

買取/販売/出品/落札/海外/下取/公式の全価格を、同一ロジックで正規化する。
ranking / sedori / LP / レポートはすべてこのモジュールを唯一の入力源とすることで、
価格定義（price_role / price_type / 利用可否）を一元化する。

主な公開関数:
  - build_observations(con, now) -> list[dict]: DB から全価格を正規化して返す
  - pro_buy_options(obs, product_id)  -> list[dict]: Pro 仕入れ候補（role=buy, usable_for_pro）
  - pro_sell_options(obs, product_id) -> list[dict]: Pro 売却候補（role=sell, usable_for_pro）
  - beginner_official(obs, product_id) -> dict|None: 初心者の基準価格（公式/定価）
  - beginner_sell(obs, product_id)     -> list[dict]: 初心者の売却候補（買取, usable_for_beginner）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

STALE_DAYS = 14  # これを超えると stale（main calculation から除外）
# 同一商品で auto_scraped high 買取がある場合、これを超える倍率の manual 買取は
# 異常値（手動入力ミス/相場転記ミス）として main calculation から除外する。
MANUAL_OVER_AUTO_RATIO = 1.3  # auto_scraped high の 1.3倍（+30%）超の manual を除外

# Pro ルートで使える price_type
PRO_BUY_TYPES = frozenset({
    "shop_sale_price", "flea_listing_price", "flea_sold_price", "overseas_listing_price",
})
PRO_SELL_TYPES = frozenset({"buyback_price", "overseas_sold_price"})
# Beginner ルートで使える price_type
BEGINNER_TYPES = frozenset({"official_price", "buyback_price"})
# 状態不明とみなす condition
UNKNOWN_CONDITIONS = frozenset({"", "unknown", "不明"})

# sale 系（Pro の buy 側にのみ使う）price_type
SALE_LISTING_TYPES = frozenset({
    "shop_sale_price", "flea_listing_price", "flea_sold_price", "overseas_listing_price",
})

# 本体以外（アクセサリー/ケース/レンズ等）を示すキーワード。タイトル/文脈に含まれれば本体ではない。
ACCESSORY_KEYWORDS = (
    "ケース", "case", "カバー", "cover", "バッテリー", "battery", "充電器", "charger",
    "ストラップ", "strap", "レンズ", "lens", "フィルター", "filter", "アダプター", "adapter",
    "保護", "protector", "leather", "pouch", "grip", "グリップ", "フード", "hood",
    "シール", "skin", "三脚", "tripod", "純正アクセサリ", "アクセサリー", "accessory",
)
# 本体価格の下限比率。参照価格（定価/公式 or 買取中央値）のこの割合未満は本体でない疑い。
BODY_PRICE_FLOOR_RATIO = 0.5


def detect_accessory_in_title(*texts: str) -> bool:
    """タイトル/文脈テキストにアクセサリー語が含まれるか。"""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return False
    return any(kw.lower() in blob for kw in ACCESSORY_KEYWORDS)


def _age_days(observed_at: str, now: datetime) -> float:
    if not observed_at:
        return 9999.0
    try:
        # now が naive で渡されても JST aware に正規化（タイムゾーン比較例外を防ぐ）
        if now.tzinfo is None:
            now = now.replace(tzinfo=JST)
        dt = datetime.fromisoformat(str(observed_at))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return (now - dt.astimezone(JST)).total_seconds() / 86400.0
    except Exception:
        return 9999.0


def classify_link_type(url: str, link_verified: bool, price_role: str) -> str:
    """URL から link_type を分類する（item / search / shop_home / official_top / none）。"""
    u = (url or "").lower()
    if price_role == "official":
        return "official_top"
    if not u:
        return "none"
    if any(k in u for k in ("/detail", "/item", "/products/", "/dp/", "itemid", "goods/")):
        return "item" if link_verified else "item_unverified"
    if any(k in u for k in ("search", "list.aspx", "keyword=", "/sch/", "itemlist")):
        return "search"
    try:
        from urllib.parse import urlparse
        p = urlparse(u)
        if p.path in ("", "/"):
            return "shop_home"
    except Exception:
        pass
    return "unknown"


def classify_sale_price_type(shop_name: str, condition: str) -> tuple[str, str]:
    """販売系（sale_prices）の shop_name から (price_type, market_type) を分類する。"""
    s = (shop_name or "")
    sl = s.lower()
    if any(k in sl for k in ("ebay", "stockx", "amazon.com")) or "海外" in s:
        return "overseas_listing_price", "overseas"
    if "メルカリ" in s or "mercari" in sl:
        return "flea_listing_price", "flea_market"
    if "ヤフオク" in s or "yahoo" in sl or "ヤフー" in s:
        if "落札" in s or "sold" in sl:
            return "flea_sold_price", "flea_market"
        return "flea_listing_price", "flea_market"
    if "ラクマ" in s or "rakuma" in sl or "paypay" in sl:
        return "flea_listing_price", "flea_market"
    return "shop_sale_price", "domestic_retail"


def is_tradein(shop_name: str, notes: str) -> bool:
    """下取（トレードイン）価格「そのもの」かどうかを判定する。

    注意: 富士屋等の買取ページ本文（notes）は「基準査定額…下取は15%UP…」のように
    現金買取と下取の両方を併記する。notes に「下取」が含まれるだけで trade_in 扱い
    すると、現金買取行（基準査定額ベース）まで誤って除外してしまう。
    そのため、現金買取の文脈（基準査定額 / 買取 / 査定）が存在する場合は trade_in と
    みなさない。下取マーカーがあり、かつ現金買取マーカーが無い場合のみ trade_in とする。
    （買取価格の抽出自体は scraper 側で下取段を除外済み: _select_cash_buyback_price）
    """
    blob = f"{shop_name or ''} {notes or ''}"
    has_tradein = ("下取" in blob) or ("トレードイン" in blob) or ("trade-in" in blob.lower())
    if not has_tradein:
        return False
    has_cash = ("基準査定額" in blob) or ("買取" in blob) or ("査定" in blob)
    return not has_cash


def _extraction_method(data_source: str) -> str:
    return {
        "auto_scraped": "auto_scraped",
        "manual_today": "manual",
        "resale_market": "resale_market_manual",
        "fetch_failed": "fetch_failed",
        "product_not_listed": "not_listed",
    }.get(data_source or "", data_source or "unknown")


def make_observation(now: datetime, **kw) -> dict:
    """1観測を正規化スキーマにまとめ、利用可否フラグと rejection_reason を計算する。"""
    price = int(kw.get("price") or 0)
    price_role = kw.get("price_role", "")
    price_type = kw.get("price_type", "")
    condition = kw.get("condition", "") or ""
    confidence = (kw.get("confidence", "") or "").lower()
    observed_at = kw.get("observed_at", "") or ""

    age = _age_days(observed_at, now)
    is_fresh = age <= STALE_DAYS
    unknown_cond = condition in UNKNOWN_CONDITIONS
    is_ti = price_type == "trade_in_price"

    # ── 製品同一性（本体判定）──
    # extracted_title: 取得元の実タイトル。auto_scraped 買取は notes(price_context)=実商品名。
    #                  販売系(resale)は title 列が無いため source_name を代替に用いる。
    extracted_title = (kw.get("extracted_title") or kw.get("price_context", "")
                       or kw.get("source_name", "") or "")
    extracted_text_preview = (kw.get("price_context", "") or "")[:160]
    extraction_method = kw.get("extraction_method", "")
    # タイトル/文脈にアクセサリー語があれば本体でない
    accessory_flag = detect_accessory_in_title(
        extracted_title, kw.get("source_name", ""), kw.get("price_context", ""))
    wrong_model_flag = False  # 機種違いは auto_scraped で strict 一致済み。価格フロアは後段で判定
    # auto_scraped 買取は scraper 側で機種厳密一致済 → 本体確定度 high
    is_exact_product_match = (extraction_method == "auto_scraped") and not accessory_flag
    is_body_only = not accessory_flag
    if accessory_flag:
        product_match_confidence = "low"
        product_match_reason = "accessory_keyword_in_title"
    elif is_exact_product_match:
        product_match_confidence = "high"
        product_match_reason = "strict_model_match"
    elif price_role == "official":
        product_match_confidence = "high"
        product_match_reason = "official_reference"
    else:
        product_match_confidence = "medium"
        product_match_reason = "unverified_title_price_band_pending"

    rejection_reason = ""
    if price <= 0:
        rejection_reason = "price_zero"
    elif not is_fresh:
        rejection_reason = "stale_over_14d"
    elif accessory_flag:
        rejection_reason = "accessory_or_wrong_product"

    # 製品同一性ゲート: 本体のみ / アクセサリー否 / 機種違い否 / 一致度 medium 以上
    identity_ok = (is_body_only and not accessory_flag and not wrong_model_flag
                   and product_match_confidence in ("high", "medium"))

    # Beginner: official_price → buyback_price のみ / trade_in 除外 / sale系除外 /
    #           stale除外 / low除外 / price0除外 / 本体のみ
    is_usable_for_beginner = (
        price > 0 and is_fresh and not is_ti
        and price_type in BEGINNER_TYPES
        and price_role in ("official", "sell")
        and confidence != "low"
        and identity_ok
    )

    # Pro: buy=PRO_BUY_TYPES, sell=PRO_SELL_TYPES / buyback仕入れ禁止 /
    #      trade_in通常売却禁止 / unknown condition除外 / 本体のみ
    pro_buy_ok = (price_role == "buy" and price_type in PRO_BUY_TYPES)
    pro_sell_ok = (price_role == "sell" and price_type in PRO_SELL_TYPES)
    is_usable_for_pro = (
        price > 0 and is_fresh and not is_ti and not unknown_cond
        and (pro_buy_ok or pro_sell_ok)
        and identity_ok
    )

    if not rejection_reason and not is_usable_for_beginner and not is_usable_for_pro:
        if is_ti:
            rejection_reason = "trade_in_excluded"
        elif unknown_cond and (pro_buy_ok or pro_sell_ok):
            rejection_reason = "unknown_condition"
        elif confidence == "low":
            rejection_reason = "low_confidence"
        else:
            rejection_reason = "role_type_not_in_main_calc"

    return {
        "extracted_title": extracted_title[:160],
        "extracted_text_preview": extracted_text_preview,
        "is_exact_product_match": is_exact_product_match,
        "is_body_only": is_body_only,
        "product_match_confidence": product_match_confidence,
        "product_match_reason": product_match_reason,
        "accessory_flag": accessory_flag,
        "wrong_model_flag": wrong_model_flag,
        "product_id": kw.get("product_id", ""),
        "product_name": kw.get("product_name", ""),
        "source_id": kw.get("source_id", ""),
        "source_name": kw.get("source_name", ""),
        "market_type": kw.get("market_type", ""),
        "price_role": price_role,
        "price_type": price_type,
        "condition": condition,
        "price": price,
        "observed_at": observed_at,
        "confidence": confidence or "unknown",
        "source_url": kw.get("source_url", "") or "",
        "item_url": kw.get("item_url", "") or "",
        "link_type": kw.get("link_type", ""),
        "extraction_method": kw.get("extraction_method", ""),
        "collector_method": kw.get("collector_method", "") or "",
        "source_mode": kw.get("source_mode", "") or "",
        "price_context": kw.get("price_context", "") or "",
        "age_days": round(age, 1),
        "observed_age_days": round(age, 1),
        "is_fresh": is_fresh,
        "is_usable_for_beginner": is_usable_for_beginner,
        "is_usable_for_pro": is_usable_for_pro,
        "rejection_reason": rejection_reason,
    }


def build_observations(con, now: datetime | None = None) -> list[dict]:
    """sqlite3 connection から全価格を正規化して観測リストを返す。

    Args:
        con: sqlite3.Connection（row_factory=sqlite3.Row を内部で設定）
        now: 基準時刻（省略時は現在 JST）
    """
    import sqlite3
    if now is None:
        now = datetime.now(tz=JST)
    con.row_factory = sqlite3.Row
    rows: list[dict] = []

    products = {r["id"]: r for r in con.execute(
        "SELECT id, name, official_price, retail_price FROM products WHERE is_active=1"
    ).fetchall()}

    # 1) official_price（公式 / 概算定価）
    for pid, p in products.items():
        official = p["official_price"] or 0
        retail = p["retail_price"] or 0
        ref = official or retail
        if ref <= 0:
            continue
        rows.append(make_observation(
            now, product_id=pid, product_name=p["name"],
            source_id="official", source_name="メーカー公式/定価",
            market_type="official", price_role="official", price_type="official_price",
            condition="new_unopened", price=ref, observed_at=now.isoformat(),
            confidence="high" if official > 0 else "medium",
            source_url="", item_url="", link_type="official_top",
            extraction_method="official" if official > 0 else "retail_concept",
            price_context="公式価格" if official > 0 else "概算定価（要確認）",
        ))

    # 2) buyback_prices（買取 = sell / 下取は trade_in）
    bq = con.execute(
        "SELECT b.*, p.name AS pname FROM buyback_prices b "
        "LEFT JOIN products p ON p.id=b.product_id WHERE b.is_active=1"
    ).fetchall()
    for r in bq:
        ti = is_tradein(r["shop_name"], r["notes"])
        ptype = "trade_in_price" if ti else "buyback_price"
        mtype = "domestic_tradein" if ti else "domestic_buyback"
        url = r["buyback_url"] or ""
        rows.append(make_observation(
            now, product_id=r["product_id"], product_name=r["pname"] or "",
            source_id=r["shop_id"] or "", source_name=r["shop_name"] or "",
            market_type=mtype, price_role="trade_in" if ti else "sell",
            price_type=ptype, condition=r["condition"] or "",
            price=r["buyback_price"] or 0, observed_at=r["observed_at"] or "",
            confidence=r["confidence"] or "",
            source_url=url, item_url=url if bool(r["link_verified"]) else "",
            link_type=classify_link_type(url, bool(r["link_verified"]),
                                         "trade_in" if ti else "sell"),
            extraction_method=_extraction_method(r["data_source"]),
            price_context=r["notes"] or ("下取価格" if ti else "買取価格"),
        ))

    # 3) sale_prices（販売/出品/落札 = buy）
    sp = con.execute(
        "SELECT s.*, p.name AS pname FROM sale_prices s "
        "LEFT JOIN products p ON p.id=s.product_id WHERE s.is_active=1"
    ).fetchall()
    for r in sp:
        ptype, mtype = classify_sale_price_type(r["shop_name"], r["condition"])
        url = r["url"] or ""
        rows.append(make_observation(
            now, product_id=r["product_id"], product_name=r["pname"] or "",
            source_id=r["shop_id"] or "", source_name=r["shop_name"] or "",
            market_type=mtype, price_role="buy", price_type=ptype,
            condition=r["condition"] or "", price=r["sale_price"] or 0,
            observed_at=r["observed_at"] or "", confidence="medium",
            source_url=url, item_url=url if bool(r["link_verified"]) else "",
            link_type=classify_link_type(url, bool(r["link_verified"]), "buy"),
            extraction_method=_extraction_method(r["data_source"]),
            price_context={
                "shop_sale_price": "店頭/EC販売価格",
                "flea_listing_price": "フリマ出品価格",
                "flea_sold_price": "フリマ落札価格",
                "overseas_listing_price": "海外出品価格",
            }.get(ptype, "販売価格"),
        ))

    # 4) price_history overseas（海外: sold=sell / listing=buy）
    # 海外価格の collector_method / source_mode を overseas_prices/latest.json から取得
    # （price_history にはこの情報が無いため）。EBAY_APP_ID 未設定なら source_mode=manual。
    _ov_meta = {}
    _ov_source_mode = ""
    try:
        import json as _json_ov
        from pathlib import Path as _P
        _ovp = _P(__file__).resolve().parent.parent.parent / "exports" / "overseas_prices" / "latest.json"
        if _ovp.exists():
            _ovd = _json_ov.loads(_ovp.read_text(encoding="utf-8"))
            _ov_source_mode = _ovd.get("source_mode", "")
            for _e in _ovd.get("prices", []):
                _sid = "src_" + str(_e.get("source", "")).lower()
                _ov_meta[(_e.get("product_id"), _sid)] = _e.get("collector_method", "")
    except Exception:
        pass

    ov = con.execute(
        "SELECT h.*, p.name AS pname FROM price_history h "
        "LEFT JOIN products p ON p.id=h.product_id WHERE h.price_type='overseas'"
    ).fetchall()
    seen = set()
    for r in sorted(ov, key=lambda x: x["recorded_at"] or "", reverse=True):
        key = (r["product_id"], r["source_id"])
        if key in seen:
            continue
        seen.add(key)
        basis = r["price_basis"] or ""
        src = (r["source_id"] or "").lower()
        is_sold = ("sold" in basis.lower()) or ("落札" in basis) or ("ebay" in src and "販売" not in basis)
        if is_sold:
            ptype, role, ctx = "overseas_sold_price", "sell", "海外落札価格(sold)"
        else:
            ptype, role, ctx = "overseas_listing_price", "buy", "海外出品価格(listing)"
        _cm = _ov_meta.get((r["product_id"], r["source_id"]), "")
        rows.append(make_observation(
            now, product_id=r["product_id"], product_name=r["pname"] or "",
            source_id=r["source_id"] or "", source_name=r["source_id"] or "overseas",
            market_type="overseas", price_role=role, price_type=ptype,
            condition="new_unopened", price=r["price"] or 0,
            observed_at=r["recorded_at"] or "", confidence="medium",
            source_url="", item_url="", link_type="none",
            extraction_method="overseas_history", price_context=ctx,
            collector_method=_cm, source_mode=_ov_source_mode,
        ))

    # ── 異常 manual 買取の除外（auto_scraped high 基準の +30% 超）──
    # 同一商品に auto_scraped high の買取があるのに、manual 買取がそれを大幅に上回る場合、
    # 手動入力ミス/販売・相場価格の転記ミスの可能性が高い。auto を信頼して manual を除外する。
    from collections import defaultdict as _dd
    _auto_high = _dd(float)
    for r in rows:
        if (r["price_type"] == "buyback_price" and r["extraction_method"] == "auto_scraped"
                and r["confidence"] == "high" and r["is_fresh"] and r["price"] > 0):
            if r["price"] > _auto_high[r["product_id"]]:
                _auto_high[r["product_id"]] = r["price"]
    for r in rows:
        if (r["price_type"] == "buyback_price" and r["extraction_method"] == "manual"
                and r["price"] > 0):
            ah = _auto_high.get(r["product_id"], 0)
            if ah > 0 and r["price"] > ah * MANUAL_OVER_AUTO_RATIO:
                r["is_usable_for_beginner"] = False
                r["is_usable_for_pro"] = False
                if not r["rejection_reason"]:
                    r["rejection_reason"] = "manual_over_auto_high"

    # ── 本体価格フロア検証（アクセサリー/別商品の誤採用を除外）──
    # 参照価格 = 定価/公式 と auto_scraped high 買取中央値 の大きい方。
    # 例: GR IV(定価¥194,800) の Amazon ¥61,267 は本体でなくケース/アクセサリーの可能性が高い。
    # 参照価格の BODY_PRICE_FLOOR_RATIO(50%) 未満は本体でないとみなし main calc から除外。
    body_ref: dict = {}
    # 本体参照価格の買取シグナル = manual_over_auto 除外後に「使用可能」な買取価格。
    # （auto_scraped が無い商品でも、信頼できる買取価格を本体参照に使えるようにする。
    #   manual_over_auto で除外済みの異常 manual はここに含まれない＝過大基準を避ける）
    _ref_buyback: dict = _dd(list)
    for r in rows:
        if (r["price_type"] == "buyback_price" and r["price"] > 0
                and r["is_usable_for_beginner"]):
            _ref_buyback[r["product_id"]].append(r["price"])
    for pid, prod in products.items():
        ref = (prod["official_price"] or 0) or (prod["retail_price"] or 0)
        bl = _ref_buyback.get(pid, [])
        if bl:
            bl_sorted = sorted(bl)
            median = bl_sorted[len(bl_sorted) // 2]
            ref = max(ref, median)
        body_ref[pid] = ref
    for r in rows:
        ref = body_ref.get(r["product_id"], 0)
        if ref > 0 and r["price"] > 0 and r["price"] < ref * BODY_PRICE_FLOOR_RATIO:
            # 本体価格として安すぎる → アクセサリー/別商品の疑い
            r["accessory_flag"] = True
            r["is_body_only"] = False
            r["is_exact_product_match"] = False
            r["product_match_confidence"] = "low"
            r["product_match_reason"] = (
                f"price_below_body_floor(<{int(BODY_PRICE_FLOOR_RATIO*100)}%_of_ref¥{ref:,})")
            r["is_usable_for_beginner"] = False
            r["is_usable_for_pro"] = False
            if not r["rejection_reason"] or r["rejection_reason"] == "role_type_not_in_main_calc":
                r["rejection_reason"] = "accessory_or_wrong_product"

    return rows


# ──────────────────────────────────────────────
# アクセサ（ranking / sedori が共通利用する選択ロジック）
# ──────────────────────────────────────────────
def pro_buy_options(obs: list[dict], product_id: str) -> list[dict]:
    """Pro 仕入れ候補（role=buy, is_usable_for_pro）。安い順。"""
    cand = [o for o in obs if o["product_id"] == product_id
            and o["price_role"] == "buy" and o["is_usable_for_pro"]]
    return sorted(cand, key=lambda o: o["price"])


def pro_sell_options(obs: list[dict], product_id: str) -> list[dict]:
    """Pro 売却候補（role=sell, is_usable_for_pro）。高い順。"""
    cand = [o for o in obs if o["product_id"] == product_id
            and o["price_role"] == "sell" and o["is_usable_for_pro"]]
    return sorted(cand, key=lambda o: o["price"], reverse=True)


def beginner_official(obs: list[dict], product_id: str):
    """初心者の基準価格（公式/定価, role=official, usable_for_beginner）。"""
    cand = [o for o in obs if o["product_id"] == product_id
            and o["price_role"] == "official" and o["is_usable_for_beginner"]]
    return cand[0] if cand else None


def beginner_sell(obs: list[dict], product_id: str) -> list[dict]:
    """初心者の売却候補（買取, role=sell, usable_for_beginner）。高い順。"""
    cand = [o for o in obs if o["product_id"] == product_id
            and o["price_role"] == "sell" and o["is_usable_for_beginner"]
            and o["price_type"] == "buyback_price"]
    return sorted(cand, key=lambda o: o["price"], reverse=True)
