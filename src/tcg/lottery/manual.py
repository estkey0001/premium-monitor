# -*- coding: utf-8 -*-
"""Task13 / Task14: 手動確認済みの抽選情報（bot 対策で自動取得できない公式 source 向け）。

data/tcg_verified_lotteries.csv を読み込む。

- 必須: product / retailer / application_start / application_end / source_url /
        verified_at / verified_by / eligibility / notes（列が存在すること）
- source_url が公式ドメインでなければ MANUAL_VERIFIED_OFFICIAL にしない。
- 表示期限は抽選の日程で決まる（締切・購入期限を過ぎたら CLOSED / ENDED）。
  observed_at は verified_at のままにし、読み込むたびに新しくしない（fresh 化しない）。
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from src.tcg.models import TCG_TYPES, parse_dt

from .schema import (
    LT_LOTTERY, LOTTERY_EVENT_TYPES, SRC_MANUAL, SRC_MANUAL_OFFICIAL, LotteryEvent,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANUAL_CSV = PROJECT_ROOT / "data" / "tcg_verified_lotteries.csv"

REQUIRED_COLUMNS = ("product", "retailer", "application_start", "application_end",
                    "source_url", "verified_at", "verified_by", "eligibility", "notes")
CSV_COLUMNS = (
    "tcg", "product", "retailer", "retailer_name", "event_type", "store_specific",
    "store_name", "prefecture", "city", "application_start", "application_end",
    "winner_announcement_at", "purchase_start", "purchase_end", "shipping_period",
    "retail_price", "eligibility", "human_confirmed", "membership_required", "app_required",
    "identity_verification_required", "purchase_history_required",
    "payment_method_requirement", "entry_url", "source_url", "verified_at",
    "verified_by", "notes",
)

# 公式とみなすドメイン（メーカー / 小売の公式サイト）
OFFICIAL_DOMAINS: tuple[str, ...] = (
    "pokemon-card.com", "pokemoncenter-online.com", "pokemon.co.jp",
    "onepiece-cardgame.com", "p-bandai.jp", "bandai.co.jp",
    "geo-online.co.jp", "toysrus.co.jp", "joshinweb.jp", "edion.com",
    "yamada-denkiweb.com", "tsite.jp", "biccamera.com", "yodobashi.com",
    "amazon.co.jp", "rakuten.co.jp", "7net.omni7.jp", "lawson.co.jp",
)


def is_official_url(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return bool(host) and any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def _flag(v: str) -> Optional[bool]:
    v = (v or "").strip().lower()
    if v in ("true", "1", "yes", "y"):
        return True
    if v in ("false", "0", "no", "n"):
        return False
    return None


def load_manual_lotteries(path: Optional[Path] = None) -> tuple[list[dict], list[str]]:
    """手動確認済みの抽選を読み込む。(events, errors) を返す。"""
    path = path or MANUAL_CSV
    if not path.exists():
        return [], []
    events: list[dict] = []
    errors: list[str] = []
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            return [], [f"必須列が不足: {missing}"]
        for n, row in enumerate(reader, start=2):
            ev, err = _row_to_event(row)
            if err:
                errors.append(f"{n}行目: {err}")
                continue
            events.append(ev)
    return events, errors


def _row_to_event(row: dict) -> tuple[Optional[dict], Optional[str]]:
    tcg = (row.get("tcg") or "").strip().upper()
    product = (row.get("product") or "").strip()
    retailer = (row.get("retailer") or "").strip().upper()
    src = (row.get("source_url") or "").strip()
    verified_at = (row.get("verified_at") or "").strip()
    verified_by = (row.get("verified_by") or "").strip()
    if tcg not in TCG_TYPES:
        return None, f"tcg が不正: {tcg!r}"
    if not product or not retailer or not src or not verified_at or not verified_by:
        return None, "product / retailer / source_url / verified_at / verified_by は必須"
    start = (row.get("application_start") or "").strip() or None
    end = (row.get("application_end") or "").strip() or None
    for label, v in (("application_start", start), ("application_end", end),
                     ("verified_at", verified_at)):
        if v and parse_dt(v) is None:
            return None, f"{label} が ISO8601 ではない: {v!r}"
    if start and end and parse_dt(end) < parse_dt(start):
        return None, "application_end が application_start より前"

    official = is_official_url(src)
    # 人が公式ページを確認したか（AI による転記だけなら False）。
    # 確認されるまでは公式扱いにしない（矛盾判定・応募ボタン・通知の対象外）、確度は medium。
    human = _flag(row.get("human_confirmed") or "") is True
    source_type = SRC_MANUAL_OFFICIAL if (official and human) else SRC_MANUAL
    et = (row.get("event_type") or LT_LOTTERY).strip().upper() or LT_LOTTERY
    if et not in LOTTERY_EVENT_TYPES:
        return None, f"event_type が不正: {et!r}"
    entry = (row.get("entry_url") or "").strip() or None
    if entry and not is_official_url(entry):
        entry = None    # Task27: 公式以外の URL を応募ボタンにしない
    price = (row.get("retail_price") or "").strip()
    try:
        price_v = int(price.replace(",", "")) if price else None
    except ValueError:
        return None, f"retail_price が数値ではない: {price!r}"

    store_specific = bool(_flag(row.get("store_specific") or ""))
    ev = LotteryEvent(
        tcg=tcg, product_name=product, retailer=retailer,
        retailer_name=(row.get("retailer_name") or "").strip() or None,
        event_type=et, store_specific=store_specific,
        store_name=(row.get("store_name") or "").strip() or None,
        prefecture=(row.get("prefecture") or "").strip() or None,
        city=(row.get("city") or "").strip() or None,
        application_start=start, application_end=end,
        winner_announcement_at=(row.get("winner_announcement_at") or "").strip() or None,
        purchase_start=(row.get("purchase_start") or "").strip() or None,
        purchase_end=(row.get("purchase_end") or "").strip() or None,
        shipping_period=(row.get("shipping_period") or "").strip() or None,
        retail_price=price_v,
        eligibility_text=(row.get("eligibility") or "").strip() or None,
        membership_required=_flag(row.get("membership_required") or ""),
        app_required=_flag(row.get("app_required") or ""),
        identity_verification_required=_flag(row.get("identity_verification_required") or ""),
        purchase_history_required=_flag(row.get("purchase_history_required") or ""),
        payment_method_requirement=(row.get("payment_method_requirement") or "").strip() or None,
        entry_url=entry,
        source_url=src, source_type=source_type,
        confidence=("high" if (official and human) else "medium" if official else "low"),
        verified=official and human, verified_by=verified_by,
        # 手動入力は確認日時を観測時刻とする（読み込みのたびに新しくしない）
        observed_at=verified_at, last_verified_at=verified_at,
        collection_method="MANUAL_VERIFIED",
        notes=[n for n in [(row.get("notes") or "").strip()] if n],
    )
    if not official:
        ev.notes.append("根拠 URL が公式サイトではないため公式確認扱いにしていません")
    elif not human:
        ev.notes.append("公式告知の内容を転記したデータです（人による確認待ち）。"
                        "必ず公式ページで日程をご確認ください")
    return ev.to_dict(), None
