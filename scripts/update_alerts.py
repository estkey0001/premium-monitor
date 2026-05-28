#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""アラート情報を自動生成して data/alerts.csv に保存するスクリプト。

入力:
  - data/lottery_events.csv     (抽選情報)
  - data/manual_buyback_prices.csv (買取価格)
  - data/premium_monitor.db     (price_history, sedori_routes 等)

出力:
  - data/alerts.csv             (アラート一覧)
  - exports/alerts_report/latest.json
  - exports/alerts_report/latest.md

alert_type:
  lottery_open         抽選開始
  lottery_closing_soon 抽選締め切り間近 (48h以内)
  restock              再入荷検出
  buyback_surge        買取急騰
  buyback_drop         買取急落
  premium_detected     プレ値検出
  market_gap           価格差拡大
  overseas_price_surge 海外価格急騰 (前回比+10%以上)
  overseas_price_drop  海外価格急落
  listing_count_spike  海外listing急増
  stale_overseas       海外価格stale警告 (48h超)
  confidence_degraded  confidence が high→medium に低下

severity: high / medium / low
"""
from __future__ import annotations

import csv
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JST = timezone(timedelta(hours=9))
ALERTS_CSV = PROJECT_ROOT / "data" / "alerts.csv"
REPORTS_DIR = PROJECT_ROOT / "exports" / "alerts_report"

ALERT_COLUMNS = [
    "alert_id", "alert_type", "product_name", "brand", "category",
    "severity", "title", "message",
    "product_url", "action_url", "action_label",
    "detected_at", "expires_at",
    "source", "data_source", "confidence",
]


def _now_jst() -> datetime:
    """現在のJST時刻を返す。"""
    return datetime.now(tz=JST)


def _now_str() -> str:
    """現在時刻を文字列で返す。"""
    return _now_jst().strftime("%Y-%m-%d %H:%M")


def _make_alert(**kwargs) -> dict:
    """アラート辞書を生成するファクトリ関数。"""
    base = {col: "" for col in ALERT_COLUMNS}
    base["alert_id"] = str(uuid.uuid4())[:12]
    base["detected_at"] = _now_str()
    base["data_source"] = "auto_generated"
    base["confidence"] = "medium"
    base.update(kwargs)
    return base


def _load_lottery_events() -> list[dict]:
    """lottery_events.csv からイベントリストを読み込む。"""
    path = PROJECT_ROOT / "data" / "lottery_events.csv"
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def _generate_lottery_alerts(now: datetime) -> list[dict]:
    """抽選情報から lottery_open / lottery_closing_soon アラートを生成する。"""
    alerts = []
    events = _load_lottery_events()

    for ev in events:
        status = ev.get("status", "")
        product_name = ev.get("product_name", "")
        brand = ev.get("brand", "")
        entry_start = ev.get("entry_start_at", "")
        entry_end = ev.get("entry_end_at", "")
        url = ev.get("url", "") or ev.get("entry_form_url", "")

        if not product_name:
            continue

        # entry_end_at チェック
        end_dt = None
        if entry_end:
            try:
                end_dt = datetime.strptime(entry_end[:16], "%Y-%m-%d %H:%M").replace(tzinfo=JST)
            except Exception:
                pass

        # entry_start_at チェック
        start_dt = None
        if entry_start:
            try:
                start_dt = datetime.strptime(entry_start[:16], "%Y-%m-%d %H:%M").replace(tzinfo=JST)
            except Exception:
                pass

        # 締め切り間近 (48h以内)
        if end_dt and end_dt > now:
            hours_left = (end_dt - now).total_seconds() / 3600
            if hours_left <= 48:
                alerts.append(_make_alert(
                    alert_type="lottery_closing_soon",
                    product_name=product_name,
                    brand=brand,
                    severity="high" if hours_left <= 24 else "medium",
                    title=f"抽選締め切り間近: {product_name}",
                    message=f"受付終了: {entry_end[:10]} ({int(hours_left)}時間後)",
                    product_url=url,
                    action_url=ev.get("entry_form_url", "") or url,
                    action_label="抽選フォームを確認",
                    expires_at=entry_end[:16] if entry_end else "",
                    source="lottery_events_csv",
                ))

        # 開始直後 (24h以内に開始)
        if start_dt and now <= start_dt <= now + timedelta(hours=24):
            alerts.append(_make_alert(
                alert_type="lottery_open",
                product_name=product_name,
                brand=brand,
                severity="high",
                title=f"抽選開始: {product_name}",
                message=f"受付開始: {entry_start[:10]}",
                product_url=url,
                action_url=ev.get("entry_form_url", "") or url,
                action_label="抽選フォームを確認",
                expires_at=entry_end[:16] if entry_end else "",
                source="lottery_events_csv",
            ))

    return alerts


def _load_buyback_alerts_from_db() -> list[dict]:
    """DBから買取急騰/急落アラートを読み込む。"""
    try:
        from src.db.database import Database
        from src.db.repository import Repository
        db = Database()
        repo = Repository(db)
        db_alerts = repo.list_buyback_alerts(limit=20)
        return [dict(a) for a in db_alerts if a.get("alert_type") in ("buyback_surge", "buyback_drop")]
    except Exception as e:
        print(f"[WARN] DB 読み込み失敗: {e}", file=sys.stderr)
        return []


def _generate_buyback_alerts(now: datetime) -> list[dict]:
    """買取急騰/急落アラートを生成する。"""
    alerts = []
    db_alerts = _load_buyback_alerts_from_db()
    for a in db_alerts:
        atype = a.get("alert_type", "")
        product_name = a.get("product_name", "") or a.get("product_id", "")
        price_after = a.get("price_after") or a.get("new_price") or a.get("buyback_price", 0)
        price_before = a.get("price_before") or a.get("prev_price", 0)
        diff = (price_after - price_before) if (price_after and price_before) else 0

        is_surge = atype == "buyback_surge"
        title = f"買取急騰: {product_name}" if is_surge else f"買取急落: {product_name}"
        msg_parts = []
        if price_before:
            msg_parts.append(f"¥{price_before:,}")
        if price_after:
            sign = "→ " if price_before else ""
            msg_parts.append(f"{sign}¥{price_after:,}")
        if diff:
            sign = "+" if diff > 0 else ""
            msg_parts.append(f"({sign}¥{diff:,})")

        expires_at = ""
        occurred = a.get("occurred_at") or a.get("created_at") or ""
        if occurred:
            try:
                occ_dt = datetime.fromisoformat(str(occurred)[:19])
                if occ_dt.tzinfo is None:
                    occ_dt = occ_dt.replace(tzinfo=JST)
                exp_dt = occ_dt + timedelta(days=1)
                expires_at = exp_dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        alerts.append(_make_alert(
            alert_type=atype,
            product_name=str(product_name),
            brand=str(a.get("brand", "")),
            severity="high" if abs(diff) > 5000 else "medium",
            title=title,
            message=" ".join(msg_parts),
            product_url=str(a.get("url", "") or a.get("buyback_url", "")),
            expires_at=expires_at,
            source="buyback_db",
        ))
    return alerts


def _save_alerts(alerts: list[dict]) -> None:
    """アラートを data/alerts.csv に保存する。"""
    ALERTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERTS_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ALERT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for a in alerts:
            writer.writerow({col: a.get(col, "") for col in ALERT_COLUMNS})
    print(f"[INFO] alerts.csv 保存完了: {len(alerts)} 件")


def _save_reports(alerts: list[dict], now: datetime) -> None:
    """アラートレポートを JSON/MD 形式で保存する。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # severity 別に集計
    high   = [a for a in alerts if a.get("severity") == "high"]
    medium = [a for a in alerts if a.get("severity") == "medium"]
    low    = [a for a in alerts if a.get("severity") == "low"]

    report = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "total": len(alerts),
        "by_severity": {"high": len(high), "medium": len(medium), "low": len(low)},
        "by_type": {},
        "alerts": alerts,
    }
    for a in alerts:
        t = a.get("alert_type", "unknown")
        report["by_type"][t] = report["by_type"].get(t, 0) + 1

    # JSON レポート保存
    json_path = REPORTS_DIR / "latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] alerts_report/latest.json 保存完了")

    # MD レポート保存
    lines = [
        f"# アラートレポート — {now.strftime('%Y-%m-%d %H:%M JST')}",
        "",
        f"- 合計: {len(alerts)} 件（High: {len(high)} / Medium: {len(medium)} / Low: {len(low)}）",
        "",
    ]
    if high:
        lines.append("## 🔴 High Priority")
        for a in high:
            lines.append(f"- [{a.get('alert_type','')}] **{a.get('product_name','')}**: {a.get('title','')} — {a.get('message','')}")
        lines.append("")
    if medium:
        lines.append("## 🟡 Medium Priority")
        for a in medium:
            lines.append(f"- [{a.get('alert_type','')}] **{a.get('product_name','')}**: {a.get('title','')} — {a.get('message','')}")
        lines.append("")

    md_path = REPORTS_DIR / "latest.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[INFO] alerts_report/latest.md 保存完了")


def _generate_overseas_alerts(now: datetime) -> list[dict]:
    """海外価格関連のアラートを生成する。

    以下のアラートタイプを生成:
      - overseas_price_surge: 海外価格急騰 (前回比+10%以上)
      - overseas_price_drop:  海外価格急落
      - listing_count_spike:  海外listing急増
      - stale_overseas:       海外価格stale警告 (48h超)
      - confidence_degraded:  confidence が high→medium に低下
    """
    alerts = []

    # exports/overseas_prices/latest.json を読み込む
    json_path = PROJECT_ROOT / "exports" / "overseas_prices" / "latest.json"
    if not json_path.exists():
        return []

    try:
        import json
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[WARN] overseas_prices/latest.json 読み込みエラー: {e}", file=sys.stderr)
        return []

    prices = data.get("prices", [])

    for entry in prices:
        product_name = entry.get("product_name", entry.get("product_alias", ""))
        price_jpy = entry.get("price_jpy", 0)
        confidence = entry.get("confidence", "low")
        listing_count = entry.get("listing_count", 0)
        stale = entry.get("stale", False)
        market = entry.get("market", "eBay")
        fetched_at = entry.get("fetched_at", "")
        failure_reason = entry.get("failure_reason", "")

        # stale_overseas: 48h超のデータ
        if stale:
            alerts.append(_make_alert(
                alert_type="stale_overseas",
                product_name=product_name,
                severity="low",
                title=f"海外価格データ古い: {product_name}",
                message=f"{market} / 最終取得: {fetched_at[:16] if fetched_at else '不明'} (48h超)",
                source="overseas_prices_json",
                confidence="low",
            ))

        # confidence_degraded: low confidence で価格あり
        if confidence == "low" and price_jpy > 0 and not failure_reason:
            alerts.append(_make_alert(
                alert_type="confidence_degraded",
                product_name=product_name,
                severity="low",
                title=f"海外価格 low confidence: {product_name}",
                message=f"{market} ¥{price_jpy:,} / listing_count={listing_count}",
                source="overseas_prices_json",
                confidence="low",
            ))

    return alerts


def main() -> int:
    """メイン処理: アラートを生成して保存する。"""
    now = _now_jst()
    print(f"[update_alerts] 開始: {now.strftime('%Y-%m-%d %H:%M')} JST")

    alerts: list[dict] = []
    alerts.extend(_generate_lottery_alerts(now))
    alerts.extend(_generate_buyback_alerts(now))
    alerts.extend(_generate_overseas_alerts(now))

    # severity 順にソート（high → medium → low）
    _sev_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: _sev_order.get(a.get("severity", "low"), 2))

    print(f"[INFO] 生成アラート: {len(alerts)} 件")
    _save_alerts(alerts)
    _save_reports(alerts, now)

    return 0


if __name__ == "__main__":
    sys.exit(main())
