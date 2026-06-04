#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正規化価格観測（normalized_price_observations）を生成する。

買取価格・販売価格・出品価格・落札価格・海外価格・下取価格を
一元的に正規化し、ranking / sedori / LP が同じ価格定義を共有できる
唯一の正規化テーブルを出力する。

各観測には price_role（buy / sell / official / trade_in）を必ず付与し、
- is_usable_for_beginner: 初心者ルート（公式→買取）で使えるか
- is_usable_for_pro:      Proルート（販売/出品/落札/海外出品 → 買取/海外落札）で使えるか
- rejection_reason:       main calculation から除外される理由
を計算する。

出力:
  - exports/normalized_price_observations/latest.json
  - exports/normalized_price_observations/latest.md

ルール（仕様）:
  Beginner:
    - official_price → buyback_price のみ
    - trade_in_price 除外 / sale・listing・sold 価格除外
    - stale 14日超除外 / confidence low 除外 / price=0 除外
  Pro:
    - buy側:  shop_sale_price / flea_listing_price / flea_sold_price / overseas_listing_price
    - sell側: buyback_price / overseas_sold_price
    - buyback_price を仕入れ価格として使わない
    - trade_in_price を通常売却価格として使わない
    - unknown condition 除外 / stale 14日超除外 / price=0 除外
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JST = timezone(timedelta(hours=9))
DB_PATH = PROJECT_ROOT / "data" / "premium_monitor.db"
REPORT_DIR = PROJECT_ROOT / "exports" / "normalized_price_observations"

STALE_DAYS = 14  # これを超えると stale（main calculation から除外）

# Pro ルートで使える price_type
PRO_BUY_TYPES = frozenset({
    "shop_sale_price", "flea_listing_price", "flea_sold_price", "overseas_listing_price",
})
PRO_SELL_TYPES = frozenset({"buyback_price", "overseas_sold_price"})
# Beginner ルートで使える price_type
BEGINNER_TYPES = frozenset({"official_price", "buyback_price"})
# 状態不明とみなす condition
_UNKNOWN_CONDITIONS = frozenset({"", "unknown", "不明", None})


def _age_days(observed_at: str, now: datetime) -> float:
    """観測時刻からの経過日数を返す。"""
    if not observed_at:
        return 9999.0
    try:
        dt = datetime.fromisoformat(str(observed_at))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return (now - dt.astimezone(JST)).total_seconds() / 86400.0
    except Exception:
        return 9999.0


def _classify_link_type(url: str, link_verified: bool, price_role: str) -> str:
    """URL から link_type を分類する。"""
    u = (url or "").lower()
    if price_role == "official":
        return "official_top"
    if not u:
        return "none"
    if any(k in u for k in ("/detail", "/item", "/products/", "/dp/", "itemid", "goods/")):
        return "product_page" if link_verified else "product_page_unverified"
    if any(k in u for k in ("search", "list.aspx", "keyword=", "/sch/", "itemlist")):
        return "search"
    # ドメイン直下のみ＝店舗トップ
    try:
        from urllib.parse import urlparse
        p = urlparse(u)
        if p.path in ("", "/"):
            return "store_top"
    except Exception:
        pass
    return "unknown"


def _classify_sale_price_type(shop_name: str, condition: str) -> tuple[str, str]:
    """販売系（sale_prices）の shop_name から (price_type, market_type) を分類する。"""
    s = (shop_name or "")
    sl = s.lower()
    # 海外（buy 側の海外出品として扱う）
    if any(k in sl for k in ("ebay", "stockx", "amazon.com")) or "海外" in s:
        return "overseas_listing_price", "overseas"
    # フリマ
    if "メルカリ" in s or "mercari" in sl:
        return "flea_listing_price", "flea_market"
    if "ヤフオク" in s or "yahoo" in sl or "ヤフー" in s:
        if "落札" in s or "sold" in sl:
            return "flea_sold_price", "flea_market"
        return "flea_listing_price", "flea_market"
    if "ラクマ" in s or "rakuma" in sl or "paypay" in sl:
        return "flea_listing_price", "flea_market"
    # それ以外は店舗/EC 販売価格
    return "shop_sale_price", "domestic_retail"


def _is_tradein(shop_name: str, notes: str) -> bool:
    """下取（トレードイン）価格かどうかを判定する。"""
    blob = f"{shop_name or ''} {notes or ''}"
    return ("下取" in blob) or ("トレードイン" in blob) or ("trade-in" in blob.lower())


def _make_row(now: datetime, **kw) -> dict:
    """1観測を正規化スキーマにまとめ、利用可否フラグと rejection_reason を計算する。"""
    price = int(kw.get("price") or 0)
    price_role = kw.get("price_role", "")
    price_type = kw.get("price_type", "")
    condition = kw.get("condition", "") or ""
    confidence = (kw.get("confidence", "") or "").lower()
    observed_at = kw.get("observed_at", "") or ""

    age = _age_days(observed_at, now)
    is_fresh = age <= STALE_DAYS
    unknown_cond = condition in _UNKNOWN_CONDITIONS
    is_tradein = price_type == "trade_in_price"

    # ── main calculation から除外される根本理由（優先順） ──
    rejection_reason = ""
    if price <= 0:
        rejection_reason = "price_zero"
    elif not is_fresh:
        rejection_reason = "stale_over_14d"

    # ── Beginner 利用可否 ──
    # official_price → buyback_price のみ / trade_in 除外 / sale系除外 / stale除外 / low除外 / price0除外
    is_usable_for_beginner = (
        price > 0
        and is_fresh
        and not is_tradein
        and price_type in BEGINNER_TYPES
        and price_role in ("official", "sell")  # 公式(buy基準) と 買取(sell)
        and confidence != "low"
    )

    # ── Pro 利用可否 ──
    # buy側: shop_sale/flea_listing/flea_sold/overseas_listing
    # sell側: buyback/overseas_sold
    # buyback を仕入れに使わない・trade_in を通常売却に使わない・unknown condition 除外
    pro_buy_ok = (price_role == "buy" and price_type in PRO_BUY_TYPES)
    pro_sell_ok = (price_role == "sell" and price_type in PRO_SELL_TYPES)
    is_usable_for_pro = (
        price > 0
        and is_fresh
        and not is_tradein
        and not unknown_cond
        and (pro_buy_ok or pro_sell_ok)
    )

    # rejection_reason の補完（main calc いずれにも使えない場合に具体理由を残す）
    if not rejection_reason and not is_usable_for_beginner and not is_usable_for_pro:
        if is_tradein:
            rejection_reason = "trade_in_excluded"
        elif unknown_cond and (pro_buy_ok or pro_sell_ok):
            rejection_reason = "unknown_condition"
        elif confidence == "low":
            rejection_reason = "low_confidence"
        else:
            rejection_reason = "role_type_not_in_main_calc"

    return {
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
        "price_context": kw.get("price_context", "") or "",
        "age_days": round(age, 1),
        "is_fresh": is_fresh,
        "is_usable_for_beginner": is_usable_for_beginner,
        "is_usable_for_pro": is_usable_for_pro,
        "rejection_reason": rejection_reason,
    }


def _extraction_method(data_source: str) -> str:
    return {
        "auto_scraped": "auto_scraped",
        "manual_today": "manual",
        "resale_market": "resale_market_manual",
        "fetch_failed": "fetch_failed",
        "product_not_listed": "not_listed",
    }.get(data_source or "", data_source or "unknown")


def build_observations(now: datetime) -> list[dict]:
    """DB から全価格を読み出し、正規化観測のリストを返す。"""
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    rows: list[dict] = []

    products = {r["id"]: r for r in con.execute(
        "SELECT id, name, official_price, retail_price FROM products WHERE is_active=1"
    ).fetchall()}

    # ── 1) official_price（公式 / 概算定価）──
    for pid, p in products.items():
        official = p["official_price"] or 0
        retail = p["retail_price"] or 0
        ref = official or retail
        if ref <= 0:
            continue
        rows.append(_make_row(
            now,
            product_id=pid, product_name=p["name"],
            source_id="official", source_name="メーカー公式/定価",
            market_type="official", price_role="official", price_type="official_price",
            condition="new_unopened", price=ref,
            observed_at=now.isoformat(),  # 公式価格は常に有効（定価基準）
            confidence="high" if official > 0 else "medium",
            source_url="", item_url="", link_type="official_top",
            extraction_method="official" if official > 0 else "retail_concept",
            price_context="公式価格" if official > 0 else "概算定価（要確認）",
        ))

    # ── 2) buyback_prices（買取 = sell / 下取は trade_in）──
    bq = con.execute(
        "SELECT b.*, p.name AS pname FROM buyback_prices b "
        "LEFT JOIN products p ON p.id=b.product_id WHERE b.is_active=1"
    ).fetchall()
    for r in bq:
        tradein = _is_tradein(r["shop_name"], r["notes"])
        ptype = "trade_in_price" if tradein else "buyback_price"
        mtype = "domestic_tradein" if tradein else "domestic_buyback"
        url = r["buyback_url"] or ""
        rows.append(_make_row(
            now,
            product_id=r["product_id"], product_name=r["pname"] or "",
            source_id=r["shop_id"] or "", source_name=r["shop_name"] or "",
            market_type=mtype, price_role="trade_in" if tradein else "sell",
            price_type=ptype, condition=r["condition"] or "",
            price=r["buyback_price"] or 0, observed_at=r["observed_at"] or "",
            confidence=r["confidence"] or "",
            source_url=url, item_url=url if bool(r["link_verified"]) else "",
            link_type=_classify_link_type(url, bool(r["link_verified"]),
                                          "trade_in" if tradein else "sell"),
            extraction_method=_extraction_method(r["data_source"]),
            price_context=r["notes"] or ("下取価格" if tradein else "買取価格"),
        ))

    # ── 3) sale_prices（販売/出品/落札 = buy）──
    sp = con.execute(
        "SELECT s.*, p.name AS pname FROM sale_prices s "
        "LEFT JOIN products p ON p.id=s.product_id WHERE s.is_active=1"
    ).fetchall()
    for r in sp:
        ptype, mtype = _classify_sale_price_type(r["shop_name"], r["condition"])
        url = r["url"] or ""
        rows.append(_make_row(
            now,
            product_id=r["product_id"], product_name=r["pname"] or "",
            source_id=r["shop_id"] or "", source_name=r["shop_name"] or "",
            market_type=mtype, price_role="buy", price_type=ptype,
            condition=r["condition"] or "", price=r["sale_price"] or 0,
            observed_at=r["observed_at"] or "",
            confidence="medium",  # 販売系は手動/フリマ収集のため medium 基準
            source_url=url, item_url=url if bool(r["link_verified"]) else "",
            link_type=_classify_link_type(url, bool(r["link_verified"]), "buy"),
            extraction_method=_extraction_method(r["data_source"]),
            price_context={
                "shop_sale_price": "店頭/EC販売価格",
                "flea_listing_price": "フリマ出品価格",
                "flea_sold_price": "フリマ落札価格",
                "overseas_listing_price": "海外出品価格",
            }.get(ptype, "販売価格"),
        ))

    # ── 4) price_history overseas（海外: sold=sell / listing=buy）──
    ov = con.execute(
        "SELECT h.*, p.name AS pname FROM price_history h "
        "LEFT JOIN products p ON p.id=h.product_id "
        "WHERE h.price_type='overseas'"
    ).fetchall()
    # ソースごと最新1件
    _seen = set()
    for r in sorted(ov, key=lambda x: x["recorded_at"] or "", reverse=True):
        key = (r["product_id"], r["source_id"])
        if key in _seen:
            continue
        _seen.add(key)
        basis = r["price_basis"] or ""
        src = (r["source_id"] or "").lower()
        is_sold = ("sold" in basis.lower()) or ("落札" in basis) or ("ebay" in src and "販売" not in basis)
        if is_sold:
            ptype, role, ctx = "overseas_sold_price", "sell", "海外落札価格(sold)"
        else:
            ptype, role, ctx = "overseas_listing_price", "buy", "海外出品価格(listing)"
        rows.append(_make_row(
            now,
            product_id=r["product_id"], product_name=r["pname"] or "",
            source_id=r["source_id"] or "", source_name=r["source_id"] or "overseas",
            market_type="overseas", price_role=role, price_type=ptype,
            condition="new_unopened", price=r["price"] or 0,
            observed_at=r["recorded_at"] or "",
            confidence="medium",
            source_url="", item_url="", link_type="none",
            extraction_method="overseas_history",
            price_context=ctx,
        ))

    con.close()
    return rows


def _summarize(rows: list[dict]) -> dict:
    """集計サマリを返す。"""
    from collections import Counter
    by_role = Counter(r["price_role"] for r in rows)
    by_type = Counter(r["price_type"] for r in rows)
    by_reject = Counter(r["rejection_reason"] for r in rows if r["rejection_reason"])
    return {
        "total": len(rows),
        "usable_for_beginner": sum(1 for r in rows if r["is_usable_for_beginner"]),
        "usable_for_pro": sum(1 for r in rows if r["is_usable_for_pro"]),
        "fresh": sum(1 for r in rows if r["is_fresh"]),
        "by_price_role": dict(by_role),
        "by_price_type": dict(by_type),
        "rejection_reasons": dict(by_reject),
    }


def _write_md(path: Path, now: datetime, summary: dict, rows: list[dict]) -> None:
    """人間可読の Markdown を書き出す。"""
    o = [f"# Normalized Price Observations", "",
         f"生成: {now.strftime('%Y-%m-%d %H:%M JST')}", "",
         "全価格（買取/販売/出品/落札/海外/下取/公式）を単一スキーマに正規化。",
         "`price_role`（buy/sell/official/trade_in）を必ず付与し、",
         "`is_usable_for_beginner` / `is_usable_for_pro` で main calculation 利用可否を判定。", "",
         "## サマリ", "",
         f"- 総観測数: **{summary['total']}**",
         f"- Beginner 利用可: {summary['usable_for_beginner']} / Pro 利用可: {summary['usable_for_pro']}",
         f"- fresh(≤{STALE_DAYS}日): {summary['fresh']}", "",
         "### price_role 別", "",
         "| role | 件数 |", "|---|---|"]
    for k, v in sorted(summary["by_price_role"].items()):
        o.append(f"| {k} | {v} |")
    o += ["", "### price_type 別", "", "| type | 件数 |", "|---|---|"]
    for k, v in sorted(summary["by_price_type"].items()):
        o.append(f"| {k} | {v} |")
    o += ["", "### rejection_reason 別（main calc 除外）", "", "| reason | 件数 |", "|---|---|"]
    for k, v in sorted(summary["rejection_reasons"].items()):
        o.append(f"| {k} | {v} |")
    # Beginner / Pro で実際に使われる観測の抜粋
    o += ["", "## Beginner 利用可（official_price / buyback_price のみ）", "",
          "| product | role | type | price | conf | age | source |", "|---|---|---|---|---|---|---|"]
    for r in [x for x in rows if x["is_usable_for_beginner"]][:30]:
        o.append(f"| {r['product_name'][:22]} | {r['price_role']} | {r['price_type']} | "
                 f"¥{r['price']:,} | {r['confidence']} | {r['age_days']}d | {r['source_name'][:16]} |")
    o += ["", "## Pro 利用可（buy=販売/出品/落札/海外出品, sell=買取/海外落札）", "",
          "| product | role | type | price | cond | age | source |", "|---|---|---|---|---|---|---|"]
    for r in [x for x in rows if x["is_usable_for_pro"]][:30]:
        o.append(f"| {r['product_name'][:22]} | {r['price_role']} | {r['price_type']} | "
                 f"¥{r['price']:,} | {r['condition']} | {r['age_days']}d | {r['source_name'][:16]} |")
    path.write_text("\n".join(o) + "\n", encoding="utf-8")


def main() -> int:
    now = datetime.now(tz=JST)
    print(f"[generate_normalized_price_observations] 開始: {now.strftime('%Y-%m-%d %H:%M')} JST")
    if not DB_PATH.exists():
        print(f"[ERROR] DB が見つかりません: {DB_PATH}", file=sys.stderr)
        return 1
    rows = build_observations(now)
    summary = _summarize(rows)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "schema_version": 1,
        "stale_days": STALE_DAYS,
        "pro_buy_types": sorted(PRO_BUY_TYPES),
        "pro_sell_types": sorted(PRO_SELL_TYPES),
        "beginner_types": sorted(BEGINNER_TYPES),
        "summary": summary,
        "observations": rows,
    }
    (REPORT_DIR / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(REPORT_DIR / "latest.md", now, summary, rows)
    print(f"  観測 {summary['total']} 件 / beginner利用可 {summary['usable_for_beginner']} "
          f"/ pro利用可 {summary['usable_for_pro']}")
    print(f"  → {REPORT_DIR / 'latest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
