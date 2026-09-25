# -*- coding: utf-8 -*-
"""Task6: 入荷報告（コミュニティ / SNS）の取り込み。

SNS の自動スクレイピングは各サービスの ToS 上の制約があるため、
ここでは CSV 経由（手動・許諾済みフィードからの取り込み）のみを受け付ける。

報告1件を「全国で販売中」と解釈しないよう、
店舗・地域・報告時刻・報告元を必ず保持し、信頼度は低く始める。
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from .classify import classify_event_type
from .models import (
    CHANNEL_STORE, EVENT_TYPES, SHRINK_STATUSES, SHRINK_UNKNOWN,
    SRC_COMMUNITY_REPORT, SRC_SOCIAL_REPORT, SRC_STORE_OFFICIAL,
    TCG_TYPES, TcgEvent, now_jst,
)
from .shrink import detect_shrink_status

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_CSV = PROJECT_ROOT / "data" / "tcg_restock_reports.csv"

CSV_COLUMNS = (
    "tcg", "product_id", "product_name", "store_name", "store_chain",
    "prefecture", "city", "reported_at", "quantity_if_known", "shrink_report",
    "source", "source_url", "text", "event_type", "official_confirmation", "note",
)

# source 列に指定できる値。store_official は「店舗公式の告知を確認した」場合のみ。
SOURCE_VALUES = ("social", "community", "store_official")


def load_reports(path: Optional[Path] = None) -> list[dict]:
    """入荷報告 CSV を TcgEvent 相当の dict に変換する。

    必須項目（tcg / product_name / store_chain / prefecture / reported_at）が
    欠けている行は取り込まない。
    """
    path = path or REPORTS_CSV
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            ev = _row_to_event(row)
            if ev is not None:
                out.append(ev.to_dict())
    return out


def _row_to_event(row: dict) -> Optional[TcgEvent]:
    tcg = (row.get("tcg") or "").strip().upper()
    name = (row.get("product_name") or "").strip()
    chain = (row.get("store_chain") or "").strip().upper()
    pref = (row.get("prefecture") or "").strip()
    reported_at = (row.get("reported_at") or "").strip()
    if tcg not in TCG_TYPES or not name or not chain or not pref or not reported_at:
        return None

    text = (row.get("text") or "").strip()
    url = (row.get("source_url") or "").strip()
    # 報告 CSV 由来の行は、URL が公式ドメインでも自動で公式扱いにしない（Task5）。
    # 店舗公式の告知を確認した場合のみ source=store_official と
    # official_confirmation=true の両方を明示することで STORE_OFFICIAL になる。
    declared_source = (row.get("source") or "").strip().lower()
    official_confirmed = (row.get("official_confirmation") or "").strip().lower() \
        in ("true", "1", "yes")
    if declared_source == "store_official" and official_confirmed:
        source_type = SRC_STORE_OFFICIAL
    elif declared_source == "community":
        source_type = SRC_COMMUNITY_REPORT
    else:
        source_type = SRC_SOCIAL_REPORT

    # 販売方式が本文から判定できない行は取り込まない（推測しない）。
    # CSV 側で event_type を明示した場合はそれを使う。
    declared = (row.get("event_type") or "").strip().upper()
    if declared in EVENT_TYPES:
        event_type = declared
    else:
        event_type = classify_event_type(text, store=chain, channel=CHANNEL_STORE)
    if event_type is None:
        return None
    shrink_report = (row.get("shrink_report") or "").strip()
    shrink = detect_shrink_status(shrink_report or text, store_key=chain)
    if shrink not in SHRINK_STATUSES:
        shrink = SHRINK_UNKNOWN

    try:
        qty = int(str(row.get("quantity_if_known") or "").strip() or 0) or None
    except ValueError:
        qty = None

    return TcgEvent(
        tcg=tcg,
        product_id=(row.get("product_id") or name).strip(),
        product_name=name,
        event_type=event_type,
        store=(row.get("store_name") or chain).strip(),
        store_chain=chain,
        channel=CHANNEL_STORE,
        prefecture=pref,
        city=(row.get("city") or "").strip() or None,
        reported_at=reported_at,
        observed_at=reported_at or now_jst().isoformat(),
        quantity_if_known=qty,
        shrink_report=shrink_report or None,
        shrink_status=shrink,
        source_url=url,
        source_type=source_type,
        confidence="low",          # 報告は必ず low から始める（後段で再評価）
        official_confirmation=official_confirmed and source_type == SRC_STORE_OFFICIAL,
        note=(row.get("note") or "").strip() or None,
    )
