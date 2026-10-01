# -*- coding: utf-8 -*-
"""プレミアムバンダイ / ONE PIECE 公式 / ローソンの抽選コレクターと、未実装 source のプローブ。

いずれも「一覧で発見 → 詳細を取得 → 抽選パーサー」の流れ。
2026-10-01 時点では、いずれの一覧にも TCG の抽選告知が無いことを確認している
（その場合は NO_ACTIVE_LOTTERY として記録する）。
"""
from __future__ import annotations

import re

from src.tcg.lottery.schema import SRC_MANUFACTURER
from src.tcg.models import now_jst

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter, anchors

_TCG_TITLE = re.compile(r"ポケモンカード|ONE PIECEカード|ワンピースカード")


class PremiumBandaiLotteryAdapter(LotteryAdapter):
    """プレミアムバンダイの【抽選販売】商品のうち、ONE PIECE カードゲームのもの。

    商品ページは JavaScript で描画されるため、詳細は Playwright で取得する
    （Playwright 未導入の環境では取得をスキップし health に記録する）。
    """

    source_id = "PREMIUM_BANDAI"
    retailer = "PREMIUM_BANDAI"
    retailer_name = "プレミアムバンダイ"
    source_name = "プレミアムバンダイ（抽選販売）"
    tcg = "ONE_PIECE"
    lottery_source_type = SRC_MANUFACTURER
    listing_urls = ("https://p-bandai.jp/", "https://p-bandai.jp/chara/onepiece/")
    max_detail_fetch = 2

    def collect(self) -> list[dict]:
        self.health["last_checked"] = now_jst().isoformat()
        cands: list[dict] = []
        seen: set[str] = set()
        loaded = False
        for lurl in self.listing_urls:
            html = self.fetch_listing(lurl)
            if not html:
                continue
            loaded = True
            for url, text in anchors(html, lurl):
                if not re.search(r"/item/item-\d+/?$", url) or url in seen:
                    continue
                seen.add(url)
                if "【抽選販売】" not in text:
                    continue
                self.funnel.news_pages_discovered += 1
                if not _TCG_TITLE.search(text):
                    self.funnel.reject(REJECT_NOT_CANDIDATE)
                    continue
                cands.append({"url": url, "title": text})
        if loaded:
            self.health["last_success"] = now_jst().isoformat()
        self.funnel.product_links_discovered = len(cands)
        for c in cands[:self.max_detail_fetch]:
            self.requires_js = True
            try:
                detail = self.fetch_detail(c["url"], referer=self.listing_urls[0])
            finally:
                self.requires_js = False
            if not detail:
                continue
            self.lottery_events.extend(self.build_from_article(
                title=c["title"], body=self.to_text(detail), url=c["url"],
                published_at=None, tcg_hint="ONE_PIECE", entry_url=c["url"]))
        return self.finish()


class OnePieceNewsLotteryAdapter(LotteryAdapter):
    """ONE PIECE カードゲーム公式ニュースの抽選販売告知。"""

    source_id = "ONEPIECE_CARD_OFFICIAL"
    retailer = "ONEPIECE_CARD_OFFICIAL"
    retailer_name = "ONE PIECEカードゲーム公式"
    source_name = "ONE PIECEカードゲーム公式（抽選告知）"
    tcg = "ONE_PIECE"
    lottery_source_type = SRC_MANUFACTURER
    news_url = "https://www.onepiece-cardgame.com/news/"
    max_detail_fetch = 2

    def collect(self) -> list[dict]:
        self.health["last_checked"] = now_jst().isoformat()
        html = self.fetch_listing(self.news_url)
        if not html:
            return self.finish()
        self.health["last_success"] = now_jst().isoformat()
        cands: list[dict] = []
        seen: set[str] = set()
        for url, text in anchors(html, self.news_url):
            if "/news/" not in url or url.rstrip("/") == self.news_url.rstrip("/") or url in seen:
                continue
            seen.add(url)
            self.funnel.news_pages_discovered += 1
            if "抽選" not in text:
                self.funnel.reject(REJECT_NOT_CANDIDATE)
                continue
            reason = self.screen_title(text)
            if reason:
                self.funnel.reject(reason)
                continue
            m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*(.*)", text)
            published = None
            if m:
                from datetime import datetime
                from src.tcg.models import JST
                published = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                     tzinfo=JST).isoformat()
            cands.append({"url": url, "title": m.group(4) if m else text,
                          "published_at": published})
        self.funnel.product_links_discovered = len(cands)
        for c in cands[:self.max_detail_fetch]:
            detail = self.fetch_detail(c["url"], referer=self.news_url)
            if not detail:
                continue
            self.lottery_events.extend(self.build_from_article(
                title=c["title"], body=self.to_text(detail), url=c["url"],
                published_at=c["published_at"], tcg_hint="ONE_PIECE"))
        return self.finish()


class LawsonLotteryAdapter(LotteryAdapter):
    """ローソン公式の一覧から TCG の抽選販売告知を発見する。"""

    source_id = "LAWSON"
    retailer = "LAWSON"
    retailer_name = "ローソン"
    source_name = "ローソン（抽選販売）"
    tcg = "POKEMON"
    channel = "STORE"
    listing_urls = ("https://www.lawson.co.jp/campaign/", "https://www.lawson.co.jp/recommend/")
    max_detail_fetch = 2

    def collect(self) -> list[dict]:
        self.health["last_checked"] = now_jst().isoformat()
        cands: list[dict] = []
        seen: set[str] = set()
        loaded = False
        for lurl in self.listing_urls:
            html = self.fetch_listing(lurl)
            if not html:
                continue
            loaded = True
            for url, text in anchors(html, lurl):
                host = self.host(url)
                if not (host == "lawson.co.jp" or host.endswith(".lawson.co.jp")) or url in seen:
                    continue
                seen.add(url)
                if not _TCG_TITLE.search(text + " " + url):
                    continue
                self.funnel.news_pages_discovered += 1
                if "抽選" not in text:
                    self.funnel.reject(REJECT_NOT_CANDIDATE)
                    continue
                cands.append({"url": url, "title": text})
        if loaded:
            self.health["last_success"] = now_jst().isoformat()
        self.funnel.product_links_discovered = len(cands)
        for c in cands[:self.max_detail_fetch]:
            detail = self.fetch_detail(c["url"], referer=self.listing_urls[0])
            if not detail:
                continue
            self.lottery_events.extend(self.build_from_article(
                title=c["title"], body=self.to_text(detail), url=c["url"],
                published_at=None))
        return self.finish()


class SourceProbe(LotteryAdapter):
    """解析器が未実装の source の到達性だけを確認する（抽選は取得しない）。

    「監視していない」のか「アクセスできない」のかを区別するために使う。
    1回の実行で公式トップを1回だけ取得する。
    """

    tcg = "POKEMON"

    def __init__(self, source: dict) -> None:
        self.source_id = source["source_id"]
        self.retailer = source["source_id"]
        self.retailer_name = source["retailer"]
        self.source_name = f"{source['retailer']}（到達確認のみ）"
        self._probe_url = source.get("official_url") or ""
        super().__init__()

    def collect(self) -> list[dict]:
        self.health["last_checked"] = now_jst().isoformat()
        if not self._probe_url:
            self.health["unreachable"] = False
            self.health["probe"] = "no_url"
            return self.finish()
        html = self.fetch_listing(self._probe_url, use_cache=False)
        page = self.funnel.pages[-1] if self.funnel.pages else None
        status = page.http_status if page else None
        if html is not None and status == 200 and len(html) < 200:
            # 200 でも本文が空に近い場合は bot チャレンジの可能性がある
            self.health["probe_note"] = "応答本文がほぼ空"
        if status == 202:
            # 自動アクセスに対するチャレンジ応答（本文なし）。回避はしない
            self.health["blocked"] = True
        if html:
            self.health["last_success"] = now_jst().isoformat()
        self.health["probe"] = "reachable" if html else "not_reachable"
        return self.finish()
