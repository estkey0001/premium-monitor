# -*- coding: utf-8 -*-
"""Task3 / Task17 / Task31: コレクターのファネル計測と健全性判定。

「errors=0 だから正常」「Playwright が動いたから正常」と判定しないための層。
ページ単位の診断（HTTP status / 本文長 / 発見リンク数 / 候補ブロック数 /
採用・棄却件数と棄却理由）を集計し、商品ページを1件も発見できなければ
DEGRADED とする。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

# ── 健全性ステータス ──────────────────────────────────────────────────────
HEALTH_HEALTHY = "HEALTHY"          # ページ取得・商品発見ともに成立
HEALTH_NO_EVENTS = "OK_NO_EVENTS"   # 正常に取得できたが、現在の販売情報が無い
HEALTH_DEGRADED = "DEGRADED"        # 取得はできたが、期待する商品・記事を発見できない
HEALTH_BLOCKED = "BLOCKED"          # robots.txt 拒否 / HTTP 403 等でアクセスできない
HEALTH_FAILED = "FAILED"            # 1ページも取得できなかった
HEALTH_STATUSES = (HEALTH_HEALTHY, HEALTH_NO_EVENTS, HEALTH_DEGRADED,
                   HEALTH_BLOCKED, HEALTH_FAILED)

# ページ種別
PAGE_LISTING = "listing"    # 商品一覧（API 含む）
PAGE_PRODUCT = "product"    # 商品詳細
PAGE_NEWS_INDEX = "news_index"
PAGE_NEWS = "news"          # ニュース記事
PAGE_OTHER = "other"

# 棄却理由（件数を集計してファネルに出す）
REJECT_NON_SALE = "non_sale_announcement"     # 大会・イベント・キャンペーン参加等
REJECT_EVENT_CATEGORY = "event_category"      # 公式カテゴリが「イベント」
REJECT_NO_SALE_CONTEXT = "no_sale_context"    # 販売語が無い
REJECT_NO_PRODUCT_CONTEXT = "no_product_context"  # 商品語が無い
REJECT_UNKNOWN_METHOD = "unknown_sale_method"  # 販売方式が判定できない
REJECT_NOT_PRODUCT_LOTTERY = "not_product_lottery"  # 「エントリー/応募」だけ
REJECT_NO_PRODUCT_NAME = "no_product_name"
REJECT_DUPLICATE = "duplicate"
REJECT_NO_ARTICLE_DATE = "ttl_event_without_article_date"
REJECT_PAST_RELEASE = "past_release"          # 発売済み（現在イベントではない）
REJECT_ACCESSORY = "accessory"                # 周辺グッズ（BOX 監視対象外）
REJECT_NO_RELEASE_DATE = "no_release_date"
REJECT_INVALID_DATES = "invalid_dates"        # end < start 等


@dataclass
class PageDiagnostic:
    """1ページ分の取得診断。"""

    url: str
    page_type: str = PAGE_OTHER
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    page_title: Optional[str] = None
    html_length: int = 0
    text_length: int = 0
    links_discovered: int = 0
    product_links_discovered: int = 0
    candidate_blocks: int = 0
    accepted: int = 0
    rejected: int = 0
    robots_status: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class CollectorFunnel:
    """コレクター1つ分のファネル集計。"""

    source: str
    # 商品ページの発見を健全性の条件にするか（Pokemon 公式商品コレクター等）
    requires_product_pages: bool = False
    # ニュース記事の発見を健全性の条件にするか
    requires_news_pages: bool = False

    pages_discovered: int = 0
    pages_requested: int = 0
    pages_loaded: int = 0
    product_pages_discovered: int = 0
    product_pages_loaded: int = 0
    news_pages_discovered: int = 0
    news_pages_loaded: int = 0
    links_discovered: int = 0
    product_links_discovered: int = 0
    candidate_events: int = 0
    accepted_sales_events: int = 0
    rejected_events: int = 0
    current_events: int = 0
    blocked_pages: int = 0
    robots_unreachable_pages: int = 0   # robots.txt に到達できず取りに行かなかったページ（禁止とは別。Phase 13）
    errors: int = 0
    rejection_reasons: Counter = field(default_factory=Counter)
    pages: list[PageDiagnostic] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ── 記録 ────────────────────────────────────────────────────────────
    def add_page(self, diag: PageDiagnostic) -> PageDiagnostic:
        self.pages.append(diag)
        return diag

    def reject(self, reason: str, n: int = 1) -> None:
        self.rejected_events += n
        self.rejection_reasons[reason] += n

    def accept(self, n: int = 1) -> None:
        self.accepted_sales_events += n

    # ── 判定 ────────────────────────────────────────────────────────────
    def status(self) -> str:
        """健全性を判定する。errors=0 だけでは HEALTHY にしない。"""
        if self.pages_loaded == 0:
            if self.blocked_pages > 0:
                return HEALTH_BLOCKED
            return HEALTH_FAILED
        if self.requires_product_pages and self.product_pages_discovered == 0:
            return HEALTH_DEGRADED
        if self.requires_news_pages and self.news_pages_discovered == 0:
            return HEALTH_DEGRADED
        if self.accepted_sales_events == 0:
            return HEALTH_NO_EVENTS
        return HEALTH_HEALTHY

    def status_reason(self) -> str:
        """人間向けの判定理由（Source Health に表示する）。"""
        st = self.status()
        if st == HEALTH_BLOCKED:
            return f"アクセス拒否（HTTP 403 / robots 等）: {self.blocked_pages}ページ"
        if st == HEALTH_FAILED:
            if self.robots_unreachable_pages and not self.pages_requested - self.robots_unreachable_pages:
                return (f"robots.txt に到達できないため取得しない（一時的な障害の可能性。禁止ではない）: "
                        f"{self.robots_unreachable_pages}ページ")
            return f"1ページも取得できませんでした（エラー {self.errors}件）"
        if st == HEALTH_DEGRADED:
            if self.requires_product_pages and self.product_pages_discovered == 0:
                return "ページは取得できたが商品ページを1件も発見できない"
            return "ページは取得できたがニュース記事を1件も発見できない"
        if st == HEALTH_NO_EVENTS:
            top = ", ".join(f"{k}={v}" for k, v in self.rejection_reasons.most_common(3))
            return ("正常に取得。現在の販売イベントは0件"
                    + (f"（棄却: {top}）" if top else ""))
        return f"正常（採用 {self.accepted_sales_events}件）"

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "status": self.status(),
            "status_reason": self.status_reason(),
            "pages_discovered": self.pages_discovered,
            "pages_requested": self.pages_requested,
            "pages_loaded": self.pages_loaded,
            "product_pages_discovered": self.product_pages_discovered,
            "product_pages_loaded": self.product_pages_loaded,
            "news_pages_discovered": self.news_pages_discovered,
            "news_pages_loaded": self.news_pages_loaded,
            "links_discovered": self.links_discovered,
            "product_links_discovered": self.product_links_discovered,
            "candidate_events": self.candidate_events,
            "accepted_sales_events": self.accepted_sales_events,
            "rejected_events": self.rejected_events,
            "rejection_reasons": dict(self.rejection_reasons),
            "current_events": self.current_events,
            "blocked_pages": self.blocked_pages,
            "robots_unreachable_pages": self.robots_unreachable_pages,
            "errors": self.errors,
            "notes": list(self.notes),
            "pages": [p.to_dict() for p in self.pages],
        }
