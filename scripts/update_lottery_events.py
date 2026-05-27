#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抽選イベント情報を自動取得して data/lottery_events.csv に保存するオーケストレーター。

アーキテクチャ:
  各コレクターは src/collectors/lottery/ に実装されており、
  このスクリプトはそれらを順番に呼び出して結果を lottery_events.csv に統合する。

コレクター一覧:
  - RicohLotteryCollector     : RICOH Imaging Store (GR IV シリーズ)
  - FujifilmLotteryCollector  : 富士フイルムXストア
  - SonyLotteryCollector      : Sony Store Japan (PS5 Pro 等)
  - NintendoLotteryCollector  : マイニンテンドーストア (Switch 2)
  - CameraRetailersLotteryCollector : マップカメラ / キタムラ
  - AmazonLotteryCollector    : Amazon 招待制購入
  - RakutenBooksLotteryCollector : 楽天ブックス

取得方針:
  - requests で静的取得 → 失敗時は Playwright (domcontentloaded, timeout=60s)
  - 取得失敗時は既存 CSV の値を保持（上書きしない）
  - product_code をキーとして重複管理（後勝ち: 新しい取得結果が優先）

Exit codes:
  0: OK（1件以上成功 または 全件スキップ）
  1: 全件失敗
"""
from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# パス設定
# ──────────────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "lottery_events.csv"
JST = timezone(timedelta(hours=9))

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

# コレクター間のスリープ（秒）— 過度なアクセスを防ぐ
COLLECTOR_INTERVAL = 2.0


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
                else:
                    # product_code なしは product_name をキーにする
                    name = row.get("product_name", "")
                    if name:
                        rows[f"__name__{name}"] = dict(row)
        return rows
    except Exception as e:
        print(f"[WARN] 既存 CSV 読み込み失敗: {e}", file=sys.stderr)
        return {}


def _save_csv(rows: dict[str, dict]) -> None:
    """rows を CSV_PATH に保存する。"""
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    # product_code キーの `__name__` プレフィックスを除去
    clean_rows = {}
    for k, v in rows.items():
        clean_rows[k] = v
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in clean_rows.values():
            writer.writerow({col: row.get(col, "") for col in CSV_COLUMNS})
    print(f"[INFO] CSV 保存完了: {CSV_PATH} ({len(clean_rows)} 件)")


# ──────────────────────────────────────────────────────────────────────────────
# コレクター管理
# ──────────────────────────────────────────────────────────────────────────────

def _load_collectors() -> list:
    """利用可能なコレクターをロードして返す。ImportError は WARNING として無視。"""
    sys.path.insert(0, str(PROJECT_ROOT))
    collectors = []

    try:
        from src.collectors.lottery.ricoh import RicohLotteryCollector
        collectors.append(RicohLotteryCollector())
        print("[INFO] RicohLotteryCollector ロード済み")
    except ImportError as e:
        print(f"[WARN] RicohLotteryCollector ロード失敗: {e}", file=sys.stderr)

    try:
        from src.collectors.lottery.fujifilm import FujifilmLotteryCollector
        collectors.append(FujifilmLotteryCollector())
        print("[INFO] FujifilmLotteryCollector ロード済み")
    except ImportError as e:
        print(f"[WARN] FujifilmLotteryCollector ロード失敗: {e}", file=sys.stderr)

    try:
        from src.collectors.lottery.sony import SonyLotteryCollector
        collectors.append(SonyLotteryCollector())
        print("[INFO] SonyLotteryCollector ロード済み")
    except ImportError as e:
        print(f"[WARN] SonyLotteryCollector ロード失敗: {e}", file=sys.stderr)

    try:
        from src.collectors.lottery.nintendo import NintendoLotteryCollector
        collectors.append(NintendoLotteryCollector())
        print("[INFO] NintendoLotteryCollector ロード済み")
    except ImportError as e:
        print(f"[WARN] NintendoLotteryCollector ロード失敗: {e}", file=sys.stderr)

    try:
        from src.collectors.lottery.camera_retailers import CameraRetailersLotteryCollector
        collectors.append(CameraRetailersLotteryCollector())
        print("[INFO] CameraRetailersLotteryCollector ロード済み")
    except ImportError as e:
        print(f"[WARN] CameraRetailersLotteryCollector ロード失敗: {e}", file=sys.stderr)

    try:
        from src.collectors.lottery.amazon import AmazonLotteryCollector
        collectors.append(AmazonLotteryCollector())
        print("[INFO] AmazonLotteryCollector ロード済み")
    except ImportError as e:
        print(f"[WARN] AmazonLotteryCollector ロード失敗: {e}", file=sys.stderr)

    try:
        from src.collectors.lottery.rakuten_books import RakutenBooksLotteryCollector
        collectors.append(RakutenBooksLotteryCollector())
        print("[INFO] RakutenBooksLotteryCollector ロード済み")
    except ImportError as e:
        print(f"[WARN] RakutenBooksLotteryCollector ロード失敗: {e}", file=sys.stderr)

    return collectors


# ──────────────────────────────────────────────────────────────────────────────
# マージ
# ──────────────────────────────────────────────────────────────────────────────

def _merge_events(
    existing: dict[str, dict],
    new_events: list[dict],
) -> dict[str, dict]:
    """既存 CSV と新規取得結果をマージする。新規データが優先（後勝ち）。"""
    result = dict(existing)  # 既存をベースに
    for ev in new_events:
        code = ev.get("product_code", "")
        key = code if code else f"__name__{ev.get('product_name', '')}"
        if not key or key == "__name__":
            continue
        # 新規データで上書き（既存より新しい情報を優先）
        result[key] = {col: ev.get(col, "") for col in CSV_COLUMNS}
    return result


# ──────────────────────────────────────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    """メイン処理。exit code を返す。"""
    now_jst = datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M")
    print(f"[update_lottery_events] 開始: {now_jst} JST")

    # 既存 CSV 読み込み
    existing = _load_existing_csv()
    print(f"[INFO] 既存 CSV: {len(existing)} 件")

    # コレクターをロード
    collectors = _load_collectors()
    if not collectors:
        print("[ERROR] 有効なコレクターが1件もロードできなかった", file=sys.stderr)
        return 1

    print(f"[INFO] {len(collectors)} コレクターを実行します")

    # 各コレクターを実行して結果を収集
    all_new_events: list[dict] = []
    success_count = 0
    fail_count = 0

    for i, collector in enumerate(collectors):
        if i > 0:
            print(f"[INFO] コレクター間インターバル待機: {COLLECTOR_INTERVAL}s")
            time.sleep(COLLECTOR_INTERVAL)

        print(f"\n[INFO] {collector.SHOP_NAME} ({collector.SHOP_ID}) を実行中...")
        try:
            events = collector.collect()
            if events:
                print(f"  → {len(events)} 件取得")
                all_new_events.extend(events)
                success_count += 1
            else:
                print(f"  → 0 件（取得なし or 全件スキップ）")
        except Exception as e:
            print(f"  → エラー: {e}", file=sys.stderr)
            fail_count += 1

    print(f"\n[INFO] 全コレクター完了: 成功={success_count} 失敗={fail_count} "
          f"取得イベント合計={len(all_new_events)} 件")

    # 既存 CSV とマージして保存
    merged = _merge_events(existing, all_new_events)
    _save_csv(merged)

    # 全件失敗は exit 1
    if success_count == 0 and fail_count == len(collectors):
        print("[ERROR] 全コレクター失敗", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
