# -*- coding: utf-8 -*-
"""LawsonPokemonDiscoveryCollector — ローソン公式のポケモンカード販売告知（Task12）。

方針:
  - ローソン公式のキャンペーン / おすすめ一覧から、ポケモンカードに関する
    ページへのリンクを「発見」してから取得する（URL を推測・ハードコードしない）。
  - 取得したページは既存の sales_context / ラベル付き日時抽出を通す。
  - 販売開始時刻（「午前7時」「7:00」等）は、販売・発売ラベルの近くに
    明記されている場合だけ保存する。推測しない。
  - 予約可否・取り置き可否・BOX 販売可否も、明記がある場合だけ True / False。
    記載が無ければ None（「BOX 販売あり」をシュリンク付きとも扱わない）。
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from src.tcg.funnel import PAGE_LISTING, PAGE_PRODUCT
from src.tcg.models import now_jst

from .pokemon import LawsonPokemonCollector

LAWSON_ROOT = "https://www.lawson.co.jp"
# 発見の起点（いずれも実際に HTTP 200 を確認した一覧ページ）
DISCOVERY_PAGES: tuple[str, ...] = (
    LAWSON_ROOT + "/campaign/",
    LAWSON_ROOT + "/recommend/",
)
MAX_FOLLOW = 2

# ポケモン「カード」に関するリンクだけを辿る（ポケモンのグッズ等は対象外）
_CARD_LINK_RE = re.compile(r"ポケモンカード|ポケカ|pokemon[-_ ]?card|pokemoncard", re.I)
_ANCHOR_RE = re.compile(r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)

# 販売開始時刻（販売・発売ラベルの近くにある場合のみ）
#   ラベルが先:  「販売開始 7:00」「発売日 9月16日 午前7時」
#   時刻が先:    「午前7時より販売開始」「7:00から発売」
_SALE_TIME_RE = re.compile(
    r"(?:販売開始|発売開始|販売日|発売日|販売時間)[^。\n]{0,30}?"
    r"(午前|午後)?\s*(\d{1,2})\s*(?:時|:|：)\s*(\d{2})?")
_SALE_TIME_AFTER_RE = re.compile(
    r"(午前|午後)?\s*(\d{1,2})\s*(?:時|:|：)\s*(\d{2})?\s*分?\s*(?:より|から)\s*"
    r"(?:販売|発売)")


def discover_card_links(html: str, base_url: str) -> list[str]:
    """一覧ページからポケモンカード関連ページへのリンクを発見する（ローソン公式内のみ）。"""
    out: list[str] = []
    for href, body in _ANCHOR_RE.findall(html or ""):
        text = re.sub(r"<[^>]+>", " ", body)
        if not _CARD_LINK_RE.search(href + " " + text):
            continue
        url = urljoin(base_url, href.strip()).split("#", 1)[0]
        host = (urlparse(url).hostname or "").lower()
        if (host == "lawson.co.jp" or host.endswith(".lawson.co.jp")) and url not in out:
            out.append(url)
    return out


def extract_sale_time(text: str) -> Optional[str]:
    """「午前7時」「7:00」等が販売ラベル近傍に明記されていれば "HH:MM" を返す。"""
    m = _SALE_TIME_RE.search(text or "") or _SALE_TIME_AFTER_RE.search(text or "")
    if not m:
        return None
    ampm, hh, mm = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    if ampm == "午後" and hh < 12:
        hh += 12
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


# 店舗ごとに異なることを示す表現（可否を断定しない）
_PARTIAL_WORDS = ("店舗によって", "店舗により", "一部店舗", "一部の店舗", "店舗ごとに")

# 肯定語の直後に続くと否定になる表現（「BOX販売は行っておりません」等）
_NEGATION_AFTER_RE = re.compile(
    r"^[^。\n]{0,12}?(は行って(おり)?ません|は行いません|不可|できません|"
    r"いたしません|しておりません|ございません|はありません|なし|お受けして)")


def _explicit_flag(text: str, positive: tuple[str, ...],
                   negative: tuple[str, ...]) -> Optional[bool]:
    """明記がある場合だけ True / False。

    否定の定型句、または肯定語の直後に続く否定表現があれば False。
    （「予約受付は行っておりません」を「予約可」と読まないため）
    """
    t = text or ""
    # 「店舗によって」「一部店舗」等は全体の可否ではないので断定しない
    if any(w in t for w in _PARTIAL_WORDS):
        return None
    if any(w in t for w in negative):
        return False
    found_positive = False
    for w in positive:
        start = 0
        while True:
            i = t.find(w, start)
            if i < 0:
                break
            if _NEGATION_AFTER_RE.match(t[i + len(w):]):
                return False
            found_positive = True
            start = i + len(w)
    return True if found_positive else None


def extract_store_conditions(text: str) -> dict:
    """予約・取り置き・BOX 販売の可否（明記がある場合だけ）。"""
    return {
        "reservation_allowed": _explicit_flag(
            text, ("予約受付", "ご予約いただけます", "予約可", "ご予約"),
            ("予約不可", "予約はできません", "予約は承っておりません", "ご予約はお受け")),
        "hold_allowed": _explicit_flag(
            text, ("お取り置きいただけます", "取り置き可", "お取り置き"),
            ("取り置き不可", "お取り置きはできません", "お取り置きは承っておりません")),
        "box_sale": _explicit_flag(
            text, ("BOX販売", "ボックス販売", "BOXでの販売"),
            ("BOXでの販売はございません", "BOXでの販売は行いません",
             "パックのみの販売", "パック単位での販売")),
    }


class LawsonPokemonDiscoveryCollector(LawsonPokemonCollector):
    """ローソン公式の一覧からポケモンカード関連ページを発見して解析する。"""

    source_name = "ローソン（ポケモンカード告知）"
    urls = DISCOVERY_PAGES

    def collect(self) -> list[dict]:
        self.health["last_checked"] = now_jst().isoformat()
        found: list[str] = []
        for url in DISCOVERY_PAGES:
            self.funnel.pages_discovered += 1
            html = self._fetch(url, page_type=PAGE_LISTING)
            if not html:
                continue
            self.health["last_success"] = now_jst().isoformat()
            links = discover_card_links(html, url)
            self.funnel.pages[-1].product_links_discovered = len(links)
            self.funnel.product_links_discovered += len(links)
            for link in links:
                if link not in found:
                    found.append(link)
        self.funnel.product_pages_discovered = len(found)
        if not found:
            self.funnel.notes.append(
                "ローソン公式の一覧にポケモンカード関連ページが見つかりませんでした"
                "（現在告知が無い可能性。推測 URL は取得しません）")

        events: list[dict] = []
        for link in found[:MAX_FOLLOW]:
            self.funnel.pages_discovered += 1
            html = self._fetch(link, page_type=PAGE_PRODUCT)
            if not html:
                continue
            self.funnel.product_pages_loaded += 1
            text = self.to_text(html)
            conditions = extract_store_conditions(text)
            sale_time = extract_sale_time(text)
            for ev in self.parse(text, link, html):
                d = ev.to_dict()
                d.update({k: v for k, v in conditions.items() if v is not None})
                if sale_time:
                    d["sale_start_time"] = sale_time
                d["store_chain"] = "LAWSON"
                d["official_confirmation"] = True   # ローソン本部の公式告知
                events.append(d)
        return self._finish(events)
