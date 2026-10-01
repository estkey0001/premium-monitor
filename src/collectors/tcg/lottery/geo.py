# -*- coding: utf-8 -*-
"""GeoLotteryAdapter — ゲオのお知らせ一覧から TCG の抽選販売告知を取得する。

一覧: https://geo-online.co.jp/news/ （2026-10-01 に HTTP 200 / robots 許可を確認）
応募先: ゲオ抽選販売専用サイト（draw.geo-online.co.jp、公式サブドメイン）
"""
from __future__ import annotations

import re
from datetime import datetime

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter, anchors

NEWS_URL = "https://geo-online.co.jp/news/"
_ITEM_RE = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(.+)")
_DETAIL_DATE_RE = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")


class GeoLotteryAdapter(LotteryAdapter):
    source_id = "GEO"
    retailer = "GEO"
    retailer_name = "ゲオ"
    source_name = "ゲオ（抽選販売のお知らせ）"
    tcg = "POKEMON"            # TcgEvent 用の既定値（抽選イベントは商品ごとに判定）
    channel = "STORE"
    max_detail_fetch = 5

    def collect(self) -> list[dict]:
        from src.tcg.models import now_jst
        self.health["last_checked"] = now_jst().isoformat()
        html = self.fetch_listing(NEWS_URL)
        if not html:
            return self.finish()
        self.health["last_success"] = now_jst().isoformat()

        cands: list[dict] = []
        seen: set[str] = set()
        for url, text in anchors(html, NEWS_URL):
            if not re.search(r"/news/\d+$", url) or url in seen:
                continue
            seen.add(url)
            m = _ITEM_RE.match(text)
            title = m.group(4) if m else text
            self.funnel.news_pages_discovered += 1
            # TCG の抽選・予約の告知だけを候補にする
            if not (re.search(r"抽選|予約|購入権", title)
                    and re.search(r"ポケモンカード|ONE PIECEカード|ワンピースカード", title)):
                self.funnel.reject(REJECT_NOT_CANDIDATE)
                continue
            published = None
            if m:
                try:
                    published = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                         tzinfo=JST).isoformat()
                except ValueError:
                    published = None
            cands.append({"url": url, "title": title, "published_at": published})
        self.funnel.product_links_discovered = len(cands)

        for c in cands[:self.max_detail_fetch]:
            detail = self.fetch_detail(c["url"], referer=NEWS_URL)
            if not detail:
                continue
            text = self.to_text(detail)
            if not c["published_at"]:
                d = _DETAIL_DATE_RE.search(text)
                if d:
                    c["published_at"] = datetime(int(d.group(1)), int(d.group(2)),
                                                 int(d.group(3)), tzinfo=JST).isoformat()
            entry = None
            for u, t in anchors(detail, c["url"]):
                if "抽選販売専用サイト" in t or self.host(u) == "draw.geo-online.co.jp":
                    entry = u
                    break
            body = text[text.find(c["title"][:15]):] if c["title"][:15] in text else text
            # 「抽選結果のご案内は…専用サイトで行います」と明記されていれば結果確認先も同じ
            result = entry if re.search(r"抽選結果のご案内[^。]{0,60}専用サイト", body) else None
            self.lottery_events.extend(self.build_from_article(
                title=c["title"], body=body, url=c["url"],
                published_at=c["published_at"], entry_url=entry, result_url=result))
        if len(cands) > self.max_detail_fetch:
            self.funnel.notes.append(
                f"詳細は {self.max_detail_fetch}/{len(cands)} 件のみ取得（同一ドメイン60秒間隔）")
        return self.finish()
