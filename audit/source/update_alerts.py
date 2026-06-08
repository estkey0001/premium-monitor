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
        # 0円（取得失敗/前回価格なし）は差分計算不能 → 偽の「¥0」急騰/急落アラートを出さない。
        if (price_after or 0) <= 0 or (price_before or 0) <= 0:
            continue
        diff = price_after - price_before
        if diff == 0:
            continue

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


def _load_previous_overseas_prices(exclude_today: str) -> dict[str, dict]:
    """前回の海外価格履歴 JSON を読み込む。

    Args:
        exclude_today: 除外する日付文字列 (例: "2026-05-28")

    Returns:
        {product_alias: entry_dict} の辞書
    """
    history_dir = PROJECT_ROOT / "exports" / "overseas_prices" / "history"
    if not history_dir.exists():
        return {}

    import json as _json
    history_files = sorted(history_dir.glob("????-??-??.json"), reverse=True)
    for hf in history_files:
        if hf.stem == exclude_today:
            continue
        try:
            with open(hf, encoding="utf-8") as f:
                data = _json.load(f)
            prev = {}
            for entry in data.get("prices", []):
                alias = entry.get("product_alias", "")
                if alias:
                    prev[alias] = entry
            return prev
        except Exception:
            continue
    return {}


def _load_official_prices() -> dict[str, int]:
    """DB から公式価格を読み込む。

    Returns:
        {product_alias: official_price_jpy} の辞書
    """
    try:
        from src.db.database import Database
        from src.db.repository import Repository
        db = Database()
        repo = Repository(db)
        products = repo.list_products()
        result = {}
        for p in products:
            alias = p.id.replace("prod_", "")
            price = getattr(p, "official_price", None) or getattr(p, "official_price_jpy", None)
            if price and price > 0:
                result[alias] = int(price)
        return result
    except Exception as e:
        print(f"[WARN] 公式価格読み込み失敗: {e}", file=sys.stderr)
        return {}


def _generate_overseas_alerts(now: datetime) -> list[dict]:
    """海外価格関連のアラートを生成する。

    以下のアラートタイプを生成:
      - overseas_price_surge:  海外価格急騰 (前回比+5%以上)
      - overseas_price_drop:   海外価格急落 (前回比-5%以下)
      - overseas_price_stale:  海外価格stale警告 (48h超)
      - premium_detected:      公式価格 < 海外価格 (プレ値検出)
      - pro_arbitrage:         海外価格が公式の110%以上 (裁定機会)

    除外条件:
      - confidence=low
      - collector_method=html_blocked
      - stale のみで他の条件を満たさない場合は stale alert のみ生成
    """
    alerts = []
    today_str = now.strftime("%Y-%m-%d")

    # 現在の海外価格を読み込む
    json_path = PROJECT_ROOT / "exports" / "overseas_prices" / "latest.json"
    if not json_path.exists():
        return []

    try:
        import json as _json
        with open(json_path, encoding="utf-8") as f:
            data = _json.load(f)
    except Exception as e:
        print(f"[WARN] overseas_prices/latest.json 読み込みエラー: {e}", file=sys.stderr)
        return []

    prices = data.get("prices", [])

    # 前回の海外価格を読み込む (今日を除外)
    prev_prices = _load_previous_overseas_prices(exclude_today=today_str)

    # 公式価格を読み込む
    official_prices = _load_official_prices()

    for entry in prices:
        product_name = entry.get("product_name", entry.get("product_alias", ""))
        product_alias = entry.get("product_alias", "")
        price_jpy = entry.get("price_jpy", 0)
        confidence = entry.get("confidence", "low")
        listing_count = entry.get("listing_count", 0)
        stale = entry.get("stale", False)
        market = entry.get("market", "eBay")
        fetched_at = entry.get("fetched_at", "")
        failure_reason = entry.get("failure_reason", "")
        collector_method = entry.get("collector_method", "unknown")
        url = entry.get("url", "")

        # html_blocked は除外 (価格データなし)
        if collector_method == "html_blocked":
            continue

        # 有効な価格がない場合はスキップ
        if not price_jpy or price_jpy <= 0:
            continue

        # confidence=low のみのデータは除外 (アラート対象外)
        if confidence == "low":
            continue

        # overseas_price_stale: 48h超のデータ (confidence≥medium のみ)
        if stale:
            alerts.append(_make_alert(
                alert_type="overseas_price_stale",
                product_name=product_name,
                severity="low",
                title=f"海外価格データ更新が必要: {product_name}",
                message=(
                    f"{market} ¥{price_jpy:,} / "
                    f"最終取得: {fetched_at[:16] if fetched_at else '不明'} (48h超) / "
                    f"confidence={confidence}"
                ),
                product_url=url,
                source="overseas_prices_json",
                confidence=confidence,
            ))
            continue  # stale データはそれ以上の比較アラートを出さない

        # ─── 前回比較アラート ───
        prev = prev_prices.get(product_alias)
        if prev:
            prev_jpy = prev.get("price_jpy", 0)
            prev_conf = prev.get("confidence", "low")

            # 前回も有効データがある場合のみ比較
            if prev_jpy > 0 and prev_conf != "low":
                change_rate = (price_jpy - prev_jpy) / prev_jpy

                if change_rate >= 0.05:
                    # overseas_price_surge (+5%以上)
                    alerts.append(_make_alert(
                        alert_type="overseas_price_surge",
                        product_name=product_name,
                        severity="high" if change_rate >= 0.10 else "medium",
                        title=f"海外価格急騰: {product_name}",
                        message=(
                            f"{market} ¥{prev_jpy:,} → ¥{price_jpy:,} "
                            f"(+{change_rate*100:.1f}%) / confidence={confidence}"
                        ),
                        product_url=url,
                        source="overseas_prices_json",
                        confidence=confidence,
                    ))

                elif change_rate <= -0.05:
                    # overseas_price_drop (-5%以下)
                    alerts.append(_make_alert(
                        alert_type="overseas_price_drop",
                        product_name=product_name,
                        severity="medium",
                        title=f"海外価格急落: {product_name}",
                        message=(
                            f"{market} ¥{prev_jpy:,} → ¥{price_jpy:,} "
                            f"({change_rate*100:.1f}%) / confidence={confidence}"
                        ),
                        product_url=url,
                        source="overseas_prices_json",
                        confidence=confidence,
                    ))

        # ─── 公式価格比較アラート ───
        official_jpy = official_prices.get(product_alias, 0)
        if official_jpy > 0 and price_jpy > 0:
            premium_rate = (price_jpy - official_jpy) / official_jpy

            if premium_rate > 0:
                # premium_detected: 公式価格 < 海外価格
                alerts.append(_make_alert(
                    alert_type="premium_detected",
                    product_name=product_name,
                    severity="high" if premium_rate >= 0.10 else "medium",
                    title=f"プレ値検出: {product_name}",
                    message=(
                        f"公式 ¥{official_jpy:,} < 海外 ¥{price_jpy:,} "
                        f"(+{premium_rate*100:.1f}%) / {market} / confidence={confidence}"
                    ),
                    product_url=url,
                    source="overseas_prices_json",
                    confidence=confidence,
                ))

            if premium_rate >= 0.10:
                # pro_arbitrage: 海外価格が公式の110%以上 (裁定機会)
                profit_est = price_jpy - official_jpy
                alerts.append(_make_alert(
                    alert_type="pro_arbitrage",
                    product_name=product_name,
                    severity="high",
                    title=f"海外裁定機会: {product_name}",
                    message=(
                        f"公式 ¥{official_jpy:,} → 海外 ¥{price_jpy:,} "
                        f"差額 ¥{profit_est:,} (+{premium_rate*100:.1f}%) / "
                        f"{market} / listing_count={listing_count}"
                    ),
                    product_url=url,
                    source="overseas_prices_json",
                    confidence=confidence,
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
