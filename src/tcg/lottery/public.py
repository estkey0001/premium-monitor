# -*- coding: utf-8 -*-
"""抽選の公開用の出口（公開 JSON・公開ページに渡す前に、出してよい項目だけにする）。

公開しない（第三者の文章・由来や公開条件を確かめていない自由文・根拠の原文）:
- eligibility_text（応募条件の原文・手動台帳の要約。告知の文の引用を含む）
- payment_method_requirement（支払い方法の行の原文）
- price_text（価格の行の原文。「お一人様 1BOX：5,760円」等。金額は retail_price・price_unit の値として出す）
- shipping_period（発送時期の原文）
- conditions の quote（根拠の行）と other_conditions（条件の行の原文）
構造化した値（conditions の value・期間・金額・期限・上限、真偽値の項目、日程、URL）は出す。
告知の件名（product_name・announcements の title・lottery_sources.json の discovered_titles）は、商品と告知を識別する見出しとして
出している（発見の処理が lottery_sources.json を読む）。件名を出すかどうかは人の判断待ち（HANDOFF）。
取得器・手動台帳・マージ・例外時の空の出力のどれを通った記録にも、同じ規則をかける（呼び出し側は必ずこの関数を通す）。
"""
from __future__ import annotations

from typing import Iterable

from src.tcg.lottery.conditions import strip_quotes

PRIVATE_FREE_TEXT = ("eligibility_text", "payment_method_requirement", "price_text", "shipping_period")


def public_event(ev: dict) -> dict:
    out = dict(ev)
    for k in PRIVATE_FREE_TEXT:
        if k in out:
            out[k] = None
    if "conditions" in out:
        out["conditions"] = strip_quotes(out.get("conditions") if isinstance(out.get("conditions"), dict) else {})
    # 商品名の出どころ: 商品マスターと完全一致（master）か、店舗の告知の見出しから取った名前（announcement）か
    out["product_name_source"] = ("master" if out.get("product_id") and out.get("product_match") == "exact"
                                  and not out.get("provisional_product") else "announcement")
    return out


def public_events(evs: Iterable[dict]) -> list[dict]:
    return [public_event(e) for e in (evs or []) if isinstance(e, dict)]


def leaked_fields(ev: dict) -> list[str]:
    """公開してはいけない項目が入っていれば、その名前（deploy-check・テスト用）。"""
    bad = [k for k in PRIVATE_FREE_TEXT if ev.get(k)]
    c = ev.get("conditions")
    if isinstance(c, dict):
        if c.get("other_conditions"):
            bad.append("conditions.other_conditions")
        bad += [f"conditions.{k}.quote" for k, v in c.items() if isinstance(v, dict) and v.get("quote")]
    return bad
