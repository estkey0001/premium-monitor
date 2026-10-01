# -*- coding: utf-8 -*-
"""LotteryAdapter — 小売・メーカーの抽選告知を取得する共通基盤（Task16 / Task17）。

流れ: 一覧ページ → 候補リンク → 詳細ページ → 販売文脈の確認 → 抽選パーサー

誤検出の防止（Task18）:
  - タイトルが大会・イベント・キャンペーン参加等なら棄却
  - 「抽選で○○が当たる」型のプレゼント抽選は棄却
  - 「抽選」という語だけでは採用しない（抽選販売 / 購入権 / 抽選受付 等が必要）
取りこぼしの防止（Task19）:
  - 「抽選で当選された方のみ購入可能」「購入権抽選」「事前抽選」「抽選受付」は採用
  - キャンペーン語が本文にあっても、商品 + 抽選販売の文脈があれば評価する
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from src.collectors.tcg.base import BaseTcgCollector
from src.tcg.funnel import (
    PAGE_LISTING, PAGE_NEWS, REJECT_NON_SALE,
)
from src.tcg.lottery.manual import is_official_url
from src.tcg.lottery.parse import (
    extract_eligibility, extract_schedule, extract_target_products,
    product_name_from_title,
)
from src.tcg.lottery.schema import (
    LT_LOTTERY, LT_PURCHASE_RIGHT, LotteryEvent, confidence_for_source,
)
from src.tcg.models import TCG_ONE_PIECE, TCG_POKEMON, now_jst
from src.tcg.sales_context import _GIVEAWAY_RE, is_non_sale_announcement
from src.tcg.shrink import detect_shrink_status

# 棄却理由
REJECT_TOURNAMENT = "tournament_or_event"
REJECT_GIVEAWAY = "giveaway_lottery"
REJECT_NO_LOTTERY_SALE = "no_lottery_sale_context"
REJECT_NO_CARD_PRODUCT = "no_card_product"
REJECT_SCHEDULE_NOT_IN_TEXT = "schedule_not_in_text"
REJECT_NOT_CANDIDATE = "not_lottery_candidate"

# 抽選販売であることを示す語（「抽選」単独は不可）
LOTTERY_SALE_PHRASES = ("抽選販売", "購入権", "抽選受付", "抽選受け付け", "事前抽選",
                        "抽選応募", "抽選で当選された方", "抽選で当選した方", "抽選での販売")
# タイトルだけで抽選販売と判断してよい語（本文を読めない告知用）
ANNOUNCEMENT_SALE_PHRASES = ("抽選販売", "抽選受付", "抽選受け付け", "購入権", "事前抽選",
                             "抽選応募", "商品の抽選", "抽選による販売", "抽選での販売")
# 大会・参加型イベント（タイトルにあれば棄却）
TOURNAMENT_TERMS = ("大会", "トーナメント", "チャンピオンズリーグ", "シティリーグ",
                    "ジムバトル", "体験会", "参加者募集", "プレイヤー募集", "来場者",
                    "イベント参加", "エントリーキャンペーン")
_CARD_WORDS = {
    TCG_POKEMON: ("ポケモンカード", "ポケカ"),
    TCG_ONE_PIECE: ("ONE PIECEカード", "ワンピースカード", "ONE PIECE カード"),
}
_A_RE = re.compile(r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)


def detect_tcg(text: str) -> Optional[str]:
    """文字列がどの TCG の商品か。両方 / どちらでもなければ None。"""
    hits = [tcg for tcg, words in _CARD_WORDS.items() if any(w in (text or "") for w in words)]
    return hits[0] if len(hits) == 1 else None


def anchors(html: str, base_url: str) -> list[tuple[str, str]]:
    """(絶対 URL, アンカーテキスト) の一覧。"""
    out: list[tuple[str, str]] = []
    for href, body in _A_RE.findall(html or ""):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
        out.append((urljoin(base_url, href.strip()), text))
    return out


class LotteryAdapter(BaseTcgCollector):
    """抽選告知コレクターの基底。サブクラスは collect() で発見と取得を行う。"""

    source_id: str = ""
    retailer: str = ""
    retailer_name: str = ""
    lottery_source_type: str = "RETAILER_OFFICIAL"
    channel = "ONLINE"
    max_detail_fetch: int = 4

    # 1回の実行の中で同じ一覧ページを2回取得しないためのキャッシュ
    _page_cache: dict[str, Optional[str]] = {}

    def __init__(self) -> None:
        super().__init__()
        self.source_key = self.source_id
        self.health["source"] = self.source_id
        self.funnel.source = self.source_id
        self.lottery_events: list[dict] = []
        self.announcements: list[dict] = []

    # ── 取得 ────────────────────────────────────────────────────────────
    def fetch_listing(self, url: str, *, use_cache: bool = True) -> Optional[str]:
        self.funnel.pages_discovered += 1
        if use_cache and url in LotteryAdapter._page_cache:
            html = LotteryAdapter._page_cache[url]
            self.funnel.notes.append(f"一覧ページは同一実行内の取得結果を再利用: {url}")
            if html:
                self.funnel.pages_requested += 1
                self.funnel.pages_loaded += 1
            return html
        html = self._fetch(url, page_type=PAGE_LISTING)
        LotteryAdapter._page_cache[url] = html
        return html

    def fetch_detail(self, url: str, referer: Optional[str] = None) -> Optional[str]:
        self.funnel.pages_discovered += 1
        html = self._fetch(url, page_type=PAGE_NEWS, referer=referer)
        if html:
            self.funnel.news_pages_loaded += 1
        return html

    @classmethod
    def clear_cache(cls) -> None:
        cls._page_cache = {}

    # ── 判定 ────────────────────────────────────────────────────────────
    def screen_title(self, title: str) -> Optional[str]:
        """タイトルで棄却すべきなら理由を返す。採用候補なら None。

        大会・参加型イベントは常に棄却する。タイトルに抽選販売を示す語があれば、
        「アプリ」「プレイヤーズクラブ」「特典」等の語では棄却しない（過剰棄却の防止）。
        """
        t = title or ""
        if any(w in t for w in TOURNAMENT_TERMS):
            return REJECT_TOURNAMENT
        if any(w in t for w in ANNOUNCEMENT_SALE_PHRASES):
            return None
        if is_non_sale_announcement(t):
            return REJECT_NON_SALE
        return None

    @staticmethod
    def is_lottery_sale(text: str) -> bool:
        """抽選販売・購入権の抽選と確認できるか（「抽選」単独では不可）。"""
        t = text or ""
        if not any(p in t for p in LOTTERY_SALE_PHRASES):
            return False
        # 「抽選で○○が当たる」だけで、抽選販売の明記が無いものはプレゼント抽選
        if _GIVEAWAY_RE.search(t) and "抽選販売" not in t and "購入権" not in t:
            return False
        return True

    def screen_announcement_title(self, title: str) -> Optional[str]:
        """本文を読めない告知（タイトルだけ）を「抽選告知あり」として残してよいか。

        - 大会・参加型イベントは残さない。
        - タイトルに抽選販売であることを示す語（抽選販売 / 購入権 / 抽選受付 等）があれば、
          「特典」「アプリ」「プレイヤーズクラブ」等の語があっても残す（過剰棄却しない）。
        - 抽選販売の語が無く、プレゼント・キャンペーン・キャンペーン告知だけのものは残さない。
        """
        t = title or ""
        if any(w in t for w in TOURNAMENT_TERMS):
            return REJECT_TOURNAMENT
        if any(w in t for w in ANNOUNCEMENT_SALE_PHRASES):
            if _GIVEAWAY_RE.search(t) and "抽選販売" not in t and "購入権" not in t:
                return REJECT_GIVEAWAY
            return None
        if _GIVEAWAY_RE.search(t) or any(w in t for w in ("プレゼント", "キャンペーン", "景品")):
            return REJECT_GIVEAWAY
        return REJECT_NO_LOTTERY_SALE

    def reject(self, reason: str) -> None:
        self.funnel.reject(reason)
        if self.funnel.pages:
            self.funnel.pages[-1].rejected += 1

    # ── イベント化 ──────────────────────────────────────────────────────
    def build_from_article(self, *, title: str, body: str, url: str,
                           published_at: Optional[str], entry_url: Optional[str] = None,
                           result_url: Optional[str] = None,
                           tcg_hint: Optional[str] = None,
                           source_type: Optional[str] = None) -> list[dict]:
        """記事本文から抽選イベントを作る。対象商品ごとに1件。"""
        self.funnel.candidate_events += 1
        if self.funnel.pages:
            self.funnel.pages[-1].candidate_blocks += 1
        head = (title or "") + "\n" + (body or "")[:400]
        reason = self.screen_title(title)
        if reason:
            self.reject(reason)
            return []
        if not self.is_lottery_sale(head + "\n" + (body or "")):
            self.reject(REJECT_GIVEAWAY if _GIVEAWAY_RE.search(body or "")
                        else REJECT_NO_LOTTERY_SALE)
            return []

        targets = extract_target_products(body) or [
            {"product_name": product_name_from_title(title), "retail_price": None}]
        source_type = source_type or self.lottery_source_type
        entry = entry_url if entry_url and is_official_url(entry_url) else None
        result = result_url if result_url and is_official_url(result_url) else None
        elig = extract_eligibility(body)
        shrink = detect_shrink_status(body)
        event_type = LT_PURCHASE_RIGHT if "購入権" in head else LT_LOTTERY
        out: list[dict] = []
        no_schedule = True
        for tgt in targets:
            name = tgt["product_name"]
            tcg = detect_tcg(name) or tcg_hint or detect_tcg(title)
            if tcg is None:
                self.reject(REJECT_NO_CARD_PRODUCT)
                continue
            sched = extract_schedule(body, published_at, product_name=name)
            if not any(sched.get(k) for k in ("application_start", "application_end",
                                              "application_start_date", "application_end_date")):
                continue
            no_schedule = False
            ev = LotteryEvent(
                tcg=tcg, product_name=name, retailer=self.retailer,
                retailer_name=self.retailer_name, event_type=event_type,
                channel=self.channel, store_specific=False,
                retail_price=tgt.get("retail_price"),
                shrink_status=shrink if shrink != "UNKNOWN" else None,
                entry_url=entry, result_url=result, source_url=url, source_type=source_type,
                confidence=confidence_for_source(source_type), verified=True,
                published_at=published_at, observed_at=now_jst().isoformat(),
                last_verified_at=now_jst().isoformat(),
                collection_method="HTML",
                **{k: v for k, v in sched.items()},
                **{k: v for k, v in elig.items()},
            )
            out.append(ev.to_dict())
        if no_schedule and not published_at:
            self.funnel.notes.append(
                "公開日が取れない記事は、年の書かれていない日付を読まない"
                f"（推測しないため）: {url}")
        if no_schedule:
            # 告知はあるが日程が本文に無い（画像のみ等）。日程は推測しない
            self.reject(REJECT_SCHEDULE_NOT_IN_TEXT)
            self.announcements.append({
                "title": title, "source_url": url, "published_at": published_at,
                "retailer": self.retailer, "retailer_name": self.retailer_name,
                "tcg": tcg_hint or detect_tcg(title + body[:400]),
                "reason": "日程が本文テキストに無い（画像のみ等）。手動確認が必要",
            })
            return []
        self.funnel.accept(len(out))
        if self.funnel.pages:
            self.funnel.pages[-1].accepted += len(out)
        return out

    def finish(self) -> list[dict]:
        """health / funnel を確定させる（到達不能の判定を含む）。"""
        self.lottery_events = list(self.lottery_events)
        msgs = " ".join(self.health.get("error_messages") or [])
        self.health["unreachable"] = (self.funnel.pages_loaded == 0 and
                                      bool(re.search(r"Timeout|ConnectionError|NameResolution",
                                                     msgs)))
        self.health["source_id"] = self.source_id
        self.health["announcements"] = self.announcements
        self._finish(self.lottery_events)
        self.health["events_found"] = len(self.lottery_events)
        return self.lottery_events

    @staticmethod
    def host(url: str) -> str:
        return (urlparse(url or "").hostname or "").lower()
