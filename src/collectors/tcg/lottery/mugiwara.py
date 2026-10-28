# -*- coding: utf-8 -*-
"""MugiwaraStoreLotteryAdapter — ONE PIECE 麦わらストア（www.mugiwara-store.com）のお知らせから、ONE PIECE カードゲームの抽選販売の告知を取得する。

Coverage Wave 4。公式のお知らせ（WordPress）に、抽選販売の告知が静的 HTML のテキストで年つきで載り、抽選受付期間・抽選結果発表・商品販売期間が本文にある
（2026-10-29 の調査: robots.txt は /wp-admin/ だけを禁止。自動取得を禁じる規約・利用規約のページは確認できなかった。許可の明記でもないので、
取得日つきの記録で、変更があれば再確認する。クラウド IP からの取得は手元では確かめられない = CI で遮断されたら WORKING に数えず、回避しない）。

- 一覧: /news/（カード = <a href=".../news/<ID>/"> の中にカテゴリ・件名・期間・対象店舗）。件名に「抽選」を含むものだけを候補にする
- 詳細: 本文は <article>（無ければ <main>）の中だけ読む。本文の領域が無ければ日程を読まず、構造変化として数える
- 応募は LivePocket（外部。店舗ごとに別のページ）。公式ドメインではないので entry_url は作らない。複数店舗の1本の告知（店舗ごとの抽選にしない）
- 価格は定価にしない。ONE PIECE だけ（ポケカは扱わない）
- 取得は LotteryAdapter（polite 経由）。遮断（401/403/429・robots 禁止）されたら、その実行ではこれ以上取得しない
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter

BASE_URL = "https://www.mugiwara-store.com"
LISTING_URL = BASE_URL + "/news/"
_CARD = re.compile(r'<a href="(https://www\.mugiwara-store\.com/news/(\d+)/)"[^>]*>(.*?)</a>', re.S)
_P = re.compile(r"<p([^>]*)>(.*?)</p>", re.S)
_ARTICLE = re.compile(r"<article.*?</article>", re.S)
_MAIN = re.compile(r"<main.*?</main>", re.S)
_DATE_IN_BODY = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")
_PRODUCT = re.compile(r"[「『](.+?)[」』]")
_NAME_BAD = re.compile(r"[※。]|[：:]\s|お一人様|抽選|応募|当選|注意|期間|発売日")


def _text(frag: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", frag or "", flags=re.S)))).strip()


def parse_listing(html: str) -> list[dict]:
    """一覧のカード（詳細の URL・ID・件名・期間の表記）。件名の読めないカードは読まない。"""
    out, seen = [], set()
    for m in _CARD.finditer(html or ""):
        if m.group(2) in seen:
            continue
        ps = [(a, _text(b)) for a, b in _P.findall(m.group(3))]
        title = max((t for a, t in ps if "date" not in a and "cat" not in a and t), key=len, default="")     # カテゴリ・期間でない最も長い文字列が件名
        if not title:
            continue
        seen.add(m.group(2))
        out.append({"url": m.group(1), "post_id": m.group(2), "title": title})
    return out


def parse_detail(html: str) -> dict:
    """詳細: 本文（<article>、無ければ <main> の中のテキスト）と公開日（本文の YYYY.MM.DD）。領域が無ければ本文は空。"""
    m = _ARTICLE.search(html or "") or _MAIN.search(html or "")
    body = _text(m.group(0)) if m else ""
    d = _DATE_IN_BODY.search(body)
    published = None
    if d:
        try:
            published = datetime(int(d.group(1)), int(d.group(2)), int(d.group(3)), tzinfo=JST).isoformat()
        except ValueError:
            published = None
    return {"body": body, "published_at": published}


def product_of(title: str) -> str:
    """件名の「…」の中の商品名（最後の「…」＝商品名。シリーズ名の「」が先にあるときは商品を優先）。読めなければ空。"""
    names = [re.sub(r"\s+", " ", n).strip() for n in _PRODUCT.findall(title or "")]
    for n in reversed(names):
        if 4 <= len(n) <= 80 and not _NAME_BAD.search(n):
            return n
    return ""


class MugiwaraStoreLotteryAdapter(LotteryAdapter):
    source_id = "MUGIWARA_STORE"
    retailer = "MUGIWARA_STORE"
    retailer_name = "ONE PIECE 麦わらストア"
    source_name = "ONE PIECE 麦わらストア（お知らせの抽選販売）"
    tcg = "ONE_PIECE"
    channel = "STORE"
    max_detail_fetch = 6
    lottery_source_type = "RETAILER_OFFICIAL"

    def _stop_if_blocked(self) -> bool:
        if self.health.get("blocked"):
            self.funnel.notes.append("アクセス制限（401/403/429）を受けたので、この実行ではこれ以上取得しない")
            return True
        return False

    def collect(self) -> list[dict]:
        from src.tcg.models import now_jst
        self.health["last_checked"] = now_jst().isoformat()
        self.funnel.requires_news_pages = True
        html = self.fetch_listing(LISTING_URL)
        cands: list[dict] = []
        if html:
            self.health["last_success"] = now_jst().isoformat()
            cards = parse_listing(html)
            if not cards:
                self.health["errors"] += 1
                self.funnel.errors += 1
                self.funnel.structure_changed_pages += 1
                self.health["error_messages"].append("一覧は取得できたがカードを読めなかった（HTML の構造の変更の可能性）")
            for c in cards:
                self.funnel.news_pages_discovered += 1
                if "抽選" not in c["title"]:
                    self.funnel.reject(REJECT_NOT_CANDIDATE)               # グッズ・店舗のお知らせなど
                    continue
                cands.append(c)
        self.funnel.product_links_discovered = len(cands)
        cands.sort(key=lambda c: -int(c["post_id"]))                         # 新しい告知（ID が大きい）から
        fetched = 0
        for c in cands[:self.max_detail_fetch]:
            if self._stop_if_blocked():
                break
            fetched += 1
            page = self.fetch_detail(c["url"], referer=LISTING_URL)
            if not page:
                continue
            d = parse_detail(page)
            if not d["body"]:
                self.funnel.structure_changed_pages += 1
                self.health["error_messages"].append("詳細ページに本文の領域（article / main）が無かった（HTML の構造の変更の可能性）")
            prod = product_of(c["title"])
            self.lottery_events.extend(self.build_from_article(
                title=c["title"], body=d["body"], url=c["url"], published_at=d["published_at"], entry_url=None, result_url=None,
                tcg_hint="ONE_PIECE", targets=[{"product_name": prod, "retail_price": None}] if prod else None))
        skipped = max(0, len(cands) - self.max_detail_fetch)
        self.health.update({"detail_candidates": len(cands), "detail_fetched": fetched, "skipped_due_to_limit": skipped, "skipped_ended": 0})
        if skipped:
            self.health["truncated"] = True
            self.funnel.notes.append(f"詳細は {fetched}/{len(cands)} 件のみ取得。{skipped} 件を上限のため読めていない")
        return self.finish()
