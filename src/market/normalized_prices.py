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

from src.market import price_types as _pt

JST = timezone(timedelta(hours=9))

STALE_DAYS = 14  # これを超えると stale（main calculation から除外）
# 公式定価（メーカー・公式ストアで確認した価格）の有効期間。定価は相場ほど速く変わらないので
# 買取・二次流通とは別のしきい値にする（確認日から数える。生成時刻を観測時刻にしない）
OFFICIAL_STALE_DAYS = 180
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
    # フリマ・オークション・eBay の1件の商品ページ（price_types.is_item_url の厳密な形。検索結果・ダミーは含まない）は
    # 商品ページとして扱う（Phase 12: 以前は「unknown」になり、二次流通で仕入れるルートが確定できなかった）
    if _pt.is_item_url(url):
        return "item" if link_verified else "item_unverified"
    # 検索結果・一覧の印を先に見る（/items/search/?q=… のような検索結果を商品ページにしない）
    if any(k in u for k in ("search", "list.aspx", "keyword=", "/sch/", "itemlist")):
        return "search"
    # ダミーの番号の URL（m00000000001 など）は商品ページにしない
    if _pt.is_dummy_url(url):
        return "unknown"
    if any(k in u for k in ("/detail", "/item", "/products/", "/dp/", "itemid", "goods/")):
        return "item" if link_verified else "item_unverified"
    try:
        from urllib.parse import urlparse
        p = urlparse(u)
        if p.path in ("", "/"):
            return "shop_home"
    except Exception:
        pass
    return "unknown"


def classify_sale_price_type(shop_name: str, condition: str, stored_type: str = _pt.UNKNOWN,
                             item_url: str = "", sold_at: str = "") -> tuple[str, str, str]:
    """販売系（sale_prices）を (price_type, market_type, 使えない理由) に分類する。

    成約（flea_sold_price）にするのは、保存された種別が SOLD で、成約の根拠
    （1件の商品ページの URL と成約日時）があるときだけ。店名に「落札」「sold」とあっても、
    種別が記録されていない（UNKNOWN）・根拠が無い値は成約にしない（出品として扱い、利益計算に使わない）。
    """
    s = (shop_name or "")
    sl = s.lower()
    stored = _pt.canonical(stored_type)
    _sold_label = ("落札" in s) or ("sold" in sl) or ("完売" in s) or ("成約" in s)
    if stored == _pt.SOLD_MEDIAN:
        # 成約価格の集計値（eBay の成約の中央値など）は仕入れ値ではない
        reject = "sold_aggregate_not_buy_price"
    elif stored == _pt.SOLD and not _pt.has_sold_evidence(item_url, sold_at):
        reject = "sold_without_evidence"
    elif stored != _pt.SOLD and _sold_label:
        reject = "sold_label_without_evidence"
    else:
        reject = ""
    if any(k in sl for k in ("ebay", "stockx", "amazon.com")) or "海外" in s:
        return "overseas_listing_price", "overseas", reject
    is_flea = (("メルカリ" in s or "mercari" in sl) or ("ヤフオク" in s or "yahoo" in sl or "ヤフー" in s)
               or ("ラクマ" in s or "rakuma" in sl or "paypay" in sl))
    if is_flea:
        if stored == _pt.SOLD and not reject:
            return "flea_sold_price", "flea_market", ""
        return "flea_listing_price", "flea_market", reject
    return "shop_sale_price", "domestic_retail", reject


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


def _sold_median_ok(kw: dict) -> bool:
    """成約中央値として使える観測か（呼び出し側の指定に加え、期間の両端と件数があること）。"""
    n = kw.get("sample_count")
    return (bool(kw.get("sold_median_eligible", False))
            and bool(kw.get("sold_period_start")) and bool(kw.get("sold_period_end"))
            and isinstance(n, int) and n >= _pt.MIN_SOLD_SAMPLES)


def make_observation(now: datetime, **kw) -> dict:
    """1観測を正規化スキーマにまとめ、利用可否フラグと rejection_reason を計算する。"""
    price = int(kw.get("price") or 0)
    price_role = kw.get("price_role", "")
    price_type = kw.get("price_type", "")
    condition = kw.get("condition", "") or ""
    confidence = (kw.get("confidence", "") or "").lower()
    observed_at = kw.get("observed_at", "") or ""

    age = _age_days(observed_at, now)
    if price_role == "official":
        # 公式定価: 確認日があれば OFFICIAL_STALE_DAYS で判定（freshness_basis=verified）。
        # 設定値（config/products.yaml の定価）は確認日を持たないので observed_at は空のまま。
        # 「確認済みで新しい」とは言わず freshness_basis=config_unknown_date と明記したうえで、
        # 従来どおり定価の参考値として使う（使うことを選んでいる。鮮度を偽らない）
        if observed_at:
            is_fresh = age <= OFFICIAL_STALE_DAYS
            freshness_basis = "verified" if is_fresh else "verified_stale"
        else:
            is_fresh = kw.get("extraction_method") == "retail_concept"
            freshness_basis = "config_unknown_date"
    else:
        is_fresh = age <= STALE_DAYS
        freshness_basis = "observed" if is_fresh else "observed_stale"
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
    # auto_scraped 買取は scraper 側で機種厳密一致済 → 本体確定度 high。
    # ただし URL が shop_home / search（＝トップページ/検索結果でSKU個別確定ができない）の場合は
    # exact 扱いにしない（モバイル一番等の「トップページ価格を複数SKUへ同額割当」誤マッチ対策）。
    _link_type = kw.get("link_type", "")
    _url_confirms_sku = _link_type not in ("shop_home", "search")
    # 成約の集計（Phase 12。src/market/sold_history）は、標本の1件ごとに商品の同一性・商品ページ・成約日時を
    # 確かめたものだけで作るので照合済みとする（集計した行に商品ページは無い）。確定の売値に使えるか
    # （件数3以上・期間あり）は sold_median_eligible で別に判定する
    _sold_median_verified = (kw.get("sold_median_identity_verified") is True
                             and isinstance(kw.get("sample_count"), int) and kw.get("sample_count") >= 1)
    is_exact_product_match = (((extraction_method == "auto_scraped") and _url_confirms_sku)
                              or _sold_median_verified) and not accessory_flag
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
        rejection_reason = ("official_stale_over_180d" if price_role == "official" else "stale_over_14d")
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

    # 価格の種別の取り違え（根拠の無い成約・成約の集計値を仕入れ値に使う等）は、利益計算に使わない
    semantic_rejection = kw.get("semantic_rejection") or ""
    if semantic_rejection:
        is_usable_for_beginner = False
        is_usable_for_pro = False
        rejection_reason = semantic_rejection

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
        # 正本の価格の種別（src/market/price_types.py）。根拠の無い成約は SOLD にしない
        "canonical_price_type": kw.get("canonical_price_type") or _pt.canonical(price_type),
        "sample_count": kw.get("sample_count"),
        # 確定利益の売値に使える成約中央値か（SOLD_MEDIAN の条件: 件数 MIN_SOLD_SAMPLES 以上・期間・成約日時）。
        # 集計期間（開始・終了）と件数が揃っていなければ、呼び出し側が True と言っても使わない
        "sold_median_eligible": _sold_median_ok(kw),
        # 成約中央値の集計期間・件数・最小/最大（price_types.sold_median の結果をそのまま。無ければ空。
        # 成約日時の無いデータに「過去30日」などの期間を推測で付けない）
        "sold_period_start": str(kw.get("sold_period_start") or ""),
        "sold_period_end": str(kw.get("sold_period_end") or ""),
        "sold_median_min": kw.get("sold_median_min"),
        "sold_median_max": kw.get("sold_median_max"),
        "sold_at": kw.get("sold_at", "") or "",
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
        "freshness_basis": freshness_basis,
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
        "SELECT id, name, official_price, retail_price, official_price_updated_at "
        "FROM products WHERE is_active=1"
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
            # 観測時刻は「その価格を確認した日時」（official_price_updated_at）。設定値の定価は確認日が無いので空。
            # 生成時刻（now）を入れない: 固定値・設定値を毎日「今確認した」ように見せないため
            condition="new_unopened", price=ref,
            observed_at=(p["official_price_updated_at"] or "") if official > 0 else "",
            confidence="high" if official > 0 else "medium",
            source_url="", item_url="", link_type="official_top",
            extraction_method="official" if official > 0 else "retail_concept",
            price_context="公式価格" if official > 0 else "概算定価（設定値・確認日不明）",
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
        _keys = r.keys()
        url = r["url"] or ""
        ptype, mtype, _sem_reject = classify_sale_price_type(
            r["shop_name"], r["condition"],
            r["price_type"] if "price_type" in _keys else _pt.UNKNOWN,
            item_url=url, sold_at=(r["sold_at"] if "sold_at" in _keys else "") or "")
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
                "flea_sold_price": "フリマ成約価格",
                "overseas_listing_price": "海外出品価格",
            }.get(ptype, "販売価格"),
            sample_count=(r["sample_count"] if "sample_count" in _keys else None),
            sold_at=(r["sold_at"] if "sold_at" in _keys else "") or "",
            semantic_rejection=_sem_reject,
            # 保存された種別をそのまま使う。種別の記録が無い過去の行は UNKNOWN（推測で SOLD にしない）
            canonical_price_type=(_pt.canonical(r["price_type"]) if "price_type" in _keys else _pt.UNKNOWN),
        ))

    # 4) price_history overseas（海外: sold=sell / listing=buy）
    # 海外価格の collector_method / source_mode を overseas_prices/latest.json から取得
    # （price_history にはこの情報が無いため）。EBAY_APP_ID 未設定なら source_mode=manual。
    _ov_meta = {}
    _ov_count = {}  # 海外価格の元にした件数（成約の集計なら成約の件数）
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
                _ov_count[(_e.get("product_id"), _sid)] = _e.get("listing_count")
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
            sample_count=_ov_count.get((r["product_id"], r["source_id"])),
            # 海外の成約は集計値で、1件ごとの成約日時と集計期間を保存していない。
            # そのため SOLD_MEDIAN（確定利益の売値に使える成約中央値）の条件は満たさない
            sold_median_eligible=False,
        ))

    # 5) 成約の履歴（exports/sold_history）から作る成約中央値（Phase 12）。3件以上・期間ありのものだけが入る。
    #    履歴が空なら何も足さない（今の本番は成約0件）
    try:
        from src.market import sold_history as _sh
        _names = {x["id"]: x["name"] for x in con.execute("SELECT id, name FROM products").fetchall()}
        for _o in _sh.median_observations(_sh.load(), now):
            _o["product_name"] = _names.get(_o["product_id"], _o["product_id"])
            rows.append(_o)
    except Exception as _e:  # noqa: BLE001（成約の履歴が読めなくても、他の観測は作る）
        import logging as _lg
        _lg.getLogger(__name__).warning("成約の履歴を読めません: %s", _e)

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

    # ── 重複価格衝突の検出（収集時マッチング誤り対策）──
    # 同一 source × 同一 role/type × 同額 が、容量 or 機種の異なる複数SKUに付与されている
    # 場合は「トップページ/検索の価格を複数SKUへ同額割当」した誤マッチの疑い。
    # 公式(official)は特別仕様で実同額があり得るため対象外（RICOH GR IV系等は別途 audit で reviewed）。
    from src.market.price_quality import (extract_capacity_gb as _cap, _model_key as _mkey,
                                           model_compatible as _mcompat)
    # ── 機種矛盾の検出（例: Leica M11-P リスティングが M11 に割当）──
    # ソースの実タイトルと割当商品名の variant/世代が矛盾する場合は降格（manual_review）。
    for r in rows:
        if r.get("price_role") == "official":
            continue
        title = r.get("extracted_title") or ""
        mc = _mcompat(title, r.get("product_name") or "")
        if mc is False:
            r["is_exact_product_match"] = False
            r["product_match_confidence"] = "low"
            r["product_match_reason"] = "model_variant_mismatch_vs_title"
            r["is_usable_for_pro"] = False
            r["is_usable_for_beginner"] = False
            if not r["rejection_reason"]:
                r["rejection_reason"] = "model_mismatch"
    from collections import defaultdict as _dd2
    _coll = _dd2(list)
    for r in rows:
        if r.get("price_role") == "official" or not r.get("price"):
            continue
        key = (r.get("source_name"), r.get("price_role"), r.get("price_type"), r["price"])
        _coll[key].append(r)
    for key, group in _coll.items():
        pids = {r["product_id"] for r in group}
        if len(pids) < 2:
            continue
        caps = {_cap(r.get("product_name") or "") for r in group}
        models = {_mkey(r.get("product_name") or "") for r in group}
        # 容量 or 機種が2種以上 → 別SKUに同額 = 誤マッチの疑い
        if len([c for c in caps if c is not None]) >= 2 or len(models) >= 2:
            for r in group:
                r["is_exact_product_match"] = False
                r["product_match_confidence"] = "low"
                r["product_match_reason"] = "duplicate_price_collision_across_skus"
                r["is_usable_for_pro"] = False
                r["is_usable_for_beginner"] = False
                if not r["rejection_reason"]:
                    r["rejection_reason"] = "duplicate_price_collision"

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
    """Pro 売却候補（role=sell, is_usable_for_pro）。高い順。

    確定利益の売値に使えるのは買取（BUYBACK_CASH）と、条件を満たした成約中央値（SOLD_MEDIAN）だけ。
    件数・期間・成約日時の無い海外の成約の集計値などは、せどりルートの売値にしない。
    """
    cand = [o for o in obs if o["product_id"] == product_id
            and o["price_role"] == "sell" and o["is_usable_for_pro"]
            and (o.get("sold_median_eligible")
                 or _pt.canonical(o.get("canonical_price_type") or o["price_type"]) in _pt.CONFIRMED_SELL_TYPES)]
    return sorted(cand, key=lambda o: o["price"], reverse=True)


def beginner_official(obs: list[dict], product_id: str):
    """初心者の基準価格（公式/定価, role=official, usable_for_beginner）。"""
    cand = [o for o in obs if o["product_id"] == product_id
            and o["price_role"] == "official" and o["is_usable_for_beginner"]]
    return cand[0] if cand else None


# ── 確定利益の売値に使える観測（売却側の正本。案件・ランキング・旧UI・新UIが共通で使う） ──
# 商品の同一性は make_observation / build_observations の is_exact_product_match（収集元が型番で厳密に照合し、
# 店のトップ・検索結果の価格ではなく、付属品・別の型番・複数 SKU への同額の割り当てでないもの）だけを根拠にする。
# 種別が買取（BUYBACK_CASH）というだけでは確定にしない。
_SELL_URL_NOT_ITEM = ("shop_home", "search")


def sell_confirmation_reasons(o: dict, *, buy_condition: str = "new") -> list[str]:
    """観測1件を確定利益の売値（買取価格）に使えない理由（空なら使える）。

    - 売却の買取価格（BUYBACK_CASH）で、価格が正
    - 商品の同一性が確認済み（is_exact_product_match が True）。店のトップ・検索結果の価格は使わない
    - 付属品・別の型番の疑いがなく、取得失敗・古い・疑わしいなどで外れていない（rejection_reason が空）
    - 確認から14日以内（is_fresh）
    - 状態の系統が仕入れ（定価で買う新品）と同じ
    """
    from src.content.ui.opportunity import _cond_family
    out = []
    if o.get("price_role") != "sell":
        out.append("not_sell")
    if _pt.canonical(o.get("canonical_price_type") or o.get("price_type")) != _pt.BUYBACK_CASH:
        out.append("sell_type_not_buyback")
    price = o.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        out.append("invalid_sell_price")
    if o.get("is_exact_product_match") is not True:
        out.append("sell_identity_unverified")
    if str(o.get("link_type") or "") in _SELL_URL_NOT_ITEM:
        out.append("sell_url_not_item_level")
    if o.get("accessory_flag") or o.get("wrong_model_flag"):
        out.append("sell_wrong_product")
    if o.get("rejection_reason"):
        out.append(f"sell_rejected_{o.get('rejection_reason')}")
    if o.get("is_fresh") is not True:
        out.append("stale_sell_price")
    if not _cond_family(o.get("condition")) or _cond_family(o.get("condition")) != _cond_family(buy_condition):
        out.append("condition_mismatch")
    return list(dict.fromkeys(out))


def confirmed_sells(obs: list[dict], product_id: str) -> list[dict]:
    """確定利益の売値に使える買取価格の観測（高い順）。単純な最高値ではなく、この中の最高値を使う。"""
    cand = [o for o in obs or [] if isinstance(o, dict) and o.get("product_id") == product_id
            and not sell_confirmation_reasons(o)]
    return sorted(cand, key=lambda o: o["price"], reverse=True)


def confirmed_sell_keys(obs: list[dict]) -> set[tuple[str, str, int]]:
    """確定利益の売値に使える買取価格の (商品ID, 店名, 価格)。案件の売値がこの中にあるかで照合する
    （商品名では照合しない）。"""
    return {(str(o["product_id"]), str(o.get("source_name") or ""), int(o["price"]))
            for o in obs or [] if isinstance(o, dict) and o.get("product_id") and not sell_confirmation_reasons(o)}


def beginner_sell(obs: list[dict], product_id: str) -> list[dict]:
    """初心者の売却候補（確定利益の売値に使える買取価格だけ。sell_confirmation_reasons）。高い順。"""
    cand = [o for o in confirmed_sells(obs, product_id)
            if o["is_usable_for_beginner"] and o["price_type"] == "buyback_price"]
    return sorted(cand, key=lambda o: o["price"], reverse=True)
