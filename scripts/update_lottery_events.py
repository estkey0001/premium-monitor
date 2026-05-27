#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RICOH公式ストアの抽選商品情報を自動取得して data/lottery_events.csv に保存するスクリプト。

取得方針:
  - requests で静的取得 → 失敗時は Playwright (domcontentloaded, timeout=60s)
  - 既知商品3件の商品詳細ページをそれぞれ取得
  - 取得できた日程・forms.gle で CSV を更新
  - 取得失敗時は既存 CSV の値を保持（上書きしない）

Exit codes:
  0: OK（1件以上成功 または 全件スキップ）
  1: 全件失敗
"""
from __future__ import annotations

import csv
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "lottery_events.csv"

JST = timezone(timedelta(hours=9))

# 取得対象の既知商品
KNOWN_PRODUCTS = [
    {
        "product_code": "S0001580",
        "product_name": "RICOH GR IV Monochrome",
        "brand": "RICOH",
        "official_price": "¥283,800（税込）",
        "category": "002010",
    },
    {
        "product_code": "S0001566",
        "product_name": "RICOH GR IV HDF",
        "brand": "RICOH",
        "official_price": "¥187,020（税込）",
        "category": "002010",
    },
    {
        "product_code": "S0001551",
        "product_name": "RICOH GR IV",
        "brand": "RICOH",
        "official_price": "¥194,800（税込）",
        "category": "002010",
    },
]

# CSV カラム定義
CSV_COLUMNS = [
    "product_name",
    "brand",
    "product_code",
    "official_price",
    "sale_method",
    "status",
    "entry_start_at",
    "entry_end_at",
    "url",
    "entry_form_url",
    "source_url",
    "checked_at",
    "data_source",
    "note",
]

# リクエスト間スリープ（秒）
REQUEST_INTERVAL = 1.5


# ──────────────────────────────────────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────────────────────────────────────

def _now_jst_str() -> str:
    """現在の JST 日時を YYYY-MM-DD HH:MM 形式で返す。"""
    return datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M")


def _product_url(product_code: str, category: str = "002010") -> str:
    """商品詳細ページの URL を生成。"""
    return (
        f"https://ricohimagingstore.com/Form/Product/ProductDetail.aspx"
        f"?shop=0&pid={product_code}&cat={category}"
    )


def _parse_dates_from_text(text: str) -> tuple[str, str]:
    """テキストから受付開始・終了日時を抽出する。

    Returns:
        (entry_start_at, entry_end_at): 取得失敗時は空文字
    """
    # 受付期間のブロックを探す
    # パターン1: YYYY年M月D日 HH:MM
    date_pattern_jp = r"(\d{4})年(\d{1,2})月(\d{1,2})日[^\d]*?(\d{1,2}):(\d{2})"
    # パターン2: YYYY/M/D HH:MM
    date_pattern_slash = r"(\d{4})/(\d{1,2})/(\d{1,2})[\s　]*(\d{1,2}):(\d{2})"

    def _extract_datetime(m, fmt: str) -> str:
        try:
            year, month, day, hour, minute = (
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)), int(m.group(5)),
            )
            return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
        except Exception:
            return ""

    # 受付期間の近傍テキストを優先して検索
    # 受付期間ブロックを切り出す（前後300文字）
    period_idx = text.find("受付期間")
    if period_idx >= 0:
        context = text[max(0, period_idx): period_idx + 600]
    else:
        context = text

    dates: list[str] = []
    for pattern in [date_pattern_jp, date_pattern_slash]:
        for m in re.finditer(pattern, context):
            dt_str = _extract_datetime(m, pattern)
            if dt_str:
                dates.append(dt_str)
        if len(dates) >= 2:
            break

    # 全文からも探す（コンテキスト検索で2件取れない場合）
    if len(dates) < 2:
        for pattern in [date_pattern_jp, date_pattern_slash]:
            for m in re.finditer(pattern, text):
                dt_str = _extract_datetime(m, pattern)
                if dt_str and dt_str not in dates:
                    dates.append(dt_str)
            if len(dates) >= 2:
                break

    entry_start_at = dates[0] if len(dates) >= 1 else ""
    entry_end_at = dates[1] if len(dates) >= 2 else ""
    return entry_start_at, entry_end_at


def _extract_forms_gle(text: str) -> str:
    """テキストから forms.gle URL を抽出する。"""
    m = re.search(r"https://forms\.gle/[A-Za-z0-9]+", text)
    return m.group(0) if m else ""


def _determine_status(entry_end_at: str) -> str:
    """entry_end_at が過去なら 'closed'、なければ 'active'。"""
    if not entry_end_at:
        return "active"
    try:
        now = datetime.now(tz=JST).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(entry_end_at[:16])
        if end_dt.tzinfo is not None:
            end_dt = end_dt.replace(tzinfo=None)
        return "closed" if end_dt < now else "active"
    except Exception:
        return "active"


# ──────────────────────────────────────────────────────────────────────────────
# HTTP 取得
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_with_requests(url: str) -> str | None:
    """requests で URL を取得し、テキストを返す。失敗時は None。"""
    try:
        import requests
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ja-JP,ja;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            return resp.text
        print(f"[WARN] requests: HTTP {resp.status_code} for {url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] requests 失敗: {e}", file=sys.stderr)
        return None


def _fetch_with_playwright(url: str) -> str | None:
    """Playwright で URL を取得し、テキストを返す。失敗時は None。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                text = page.inner_text("body")
                return text
            finally:
                browser.close()
    except Exception as e:
        print(f"[WARN] Playwright 失敗: {e}", file=sys.stderr)
        return None


def _fetch_page_text(url: str) -> str | None:
    """requests → Playwright の順でページテキストを取得。"""
    text = _fetch_with_requests(url)
    if text and len(text) > 500:
        return text
    print(f"[INFO] requests で十分なコンテンツが取れなかったため Playwright を試みます: {url}")
    return _fetch_with_playwright(url)


# ──────────────────────────────────────────────────────────────────────────────
# CSV 操作
# ──────────────────────────────────────────────────────────────────────────────

def _load_existing_csv() -> dict[str, dict]:
    """既存の lottery_events.csv を読み込み、{product_code: row_dict} を返す。"""
    if not CSV_PATH.exists():
        return {}
    try:
        rows: dict[str, dict] = {}
        with open(CSV_PATH, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("product_code", "")
                if code:
                    rows[code] = dict(row)
        return rows
    except Exception as e:
        print(f"[WARN] 既存 CSV 読み込み失敗: {e}", file=sys.stderr)
        return {}


def _save_csv(rows: dict[str, dict]) -> None:
    """rows ({product_code: row_dict}) を CSV_PATH に保存する。"""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows.values():
            writer.writerow(row)
    print(f"[INFO] CSV 保存完了: {CSV_PATH} ({len(rows)} 件)")


# ──────────────────────────────────────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────────────────────────────────────

def process_product(product: dict, existing: dict[str, dict]) -> dict | None:
    """1商品を取得・解析して row dict を返す。失敗時は None。"""
    code = product["product_code"]
    url = _product_url(code, product.get("category", "002010"))

    print(f"[INFO] 取得中: {product['product_name']} ({code})")
    print(f"  URL: {url}")

    text = _fetch_page_text(url)
    if not text:
        print(f"[WARN] ページ取得失敗: {code}", file=sys.stderr)
        return None

    # 受付日時・フォーム URL を抽出
    entry_start_at, entry_end_at = _parse_dates_from_text(text)
    entry_form_url = _extract_forms_gle(text)
    status = _determine_status(entry_end_at)

    print(f"  受付開始: {entry_start_at or '（取得失敗）'}")
    print(f"  受付終了: {entry_end_at or '（取得失敗）'}")
    print(f"  フォーム: {entry_form_url or '（取得失敗）'}")
    print(f"  ステータス: {status}")

    # 既存行をベースに、取得できたフィールドのみ上書き
    base: dict = existing.get(code, {}).copy()

    # 固定フィールド
    base["product_name"]  = product["product_name"]
    base["brand"]         = product["brand"]
    base["product_code"]  = code
    base["official_price"] = product["official_price"]
    base["sale_method"]   = "抽選販売"
    base["url"]           = url
    base["source_url"]    = url
    base["checked_at"]    = _now_jst_str()
    base["data_source"]   = "auto_scraped"
    if "note" not in base:
        base["note"] = ""

    # 取得できたフィールドのみ更新（空文字の場合は既存値を保持）
    if entry_start_at:
        base["entry_start_at"] = entry_start_at
    elif "entry_start_at" not in base:
        base["entry_start_at"] = ""

    if entry_end_at:
        base["entry_end_at"] = entry_end_at
    elif "entry_end_at" not in base:
        base["entry_end_at"] = ""

    if entry_form_url:
        base["entry_form_url"] = entry_form_url
    elif "entry_form_url" not in base:
        base["entry_form_url"] = ""

    # status は entry_end_at が取得できた場合のみ更新
    if entry_end_at:
        base["status"] = status
    elif "status" not in base:
        base["status"] = "active"

    return base


def main() -> int:
    """メイン処理。exit code を返す。"""
    print(f"[update_lottery_events] 開始: {_now_jst_str()} JST")

    # 既存 CSV 読み込み
    existing = _load_existing_csv()
    print(f"[INFO] 既存 CSV: {len(existing)} 件")

    # 各商品を処理
    success_count = 0
    result_rows: dict[str, dict] = dict(existing)  # 既存行をベースに

    for i, product in enumerate(KNOWN_PRODUCTS):
        if i > 0:
            print(f"[INFO] レート制限待機: {REQUEST_INTERVAL}s")
            time.sleep(REQUEST_INTERVAL)

        row = process_product(product, existing)
        if row is not None:
            result_rows[product["product_code"]] = row
            success_count += 1
        else:
            # 取得失敗時: 既存行を保持（変更なし）
            print(f"[INFO] 取得失敗のため既存値を保持: {product['product_code']}")

    # CSV に保存（1件でも処理できれば保存）
    _save_csv(result_rows)

    print(f"\n[完了] 成功: {success_count}/{len(KNOWN_PRODUCTS)} 件")

    if success_count == 0:
        print("[ERROR] 全件取得失敗", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
