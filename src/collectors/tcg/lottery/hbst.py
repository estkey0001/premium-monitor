# -*- coding: utf-8 -*-
"""HobbyStationLotteryAdapter — ホビーステーション（hbst.net）のお知らせから、ポケカ・ONE PIECE の抽選販売の告知を取得する。

Market Research Coverage Wave 2。公式のお知らせ（WordPress）に、抽選販売の告知が静的 HTML のテキストで載り、
応募期間・当選発表・当選者購入期間が「■応募期間：…」の固定の書式で本文にある
（2026-10-28 の調査: robots.txt は /wordpress/wp-admin/ だけを禁止・PremiumMonitor への禁止なし。自動取得を禁じる規約・
利用規約のページは見当たらない。許可の明記でもないので、変更があれば再確認する）。

- 一覧: /result/?category=news（1ページ目。カード = 件名の先頭 30 文字ほど + 詳細の URL ?p=<ID>）
- 詳細: /?p=<ID>。件名は <title>、公開日は time.time-date、本文は <section id="article"> の中（数値文字参照で書かれることがある → unescape）
- 応募は Livepocket（外部のサービス）。公式ドメインではないので entry_url は作らない（応募先の URL は記録しない）
- 店舗横断の1本の告知（対象店舗から1店舗だけ応募）。店舗ごとの抽選ではない（store_specific にしない）
- 日程は本文のテキストだけ。年が不自然な日付（誤記）は共通の解析器が捨てる（日程の日付を作らない）。価格は定価にしない
  （「販売価格：各7,200円」が1個の定価か組の合計か本文だけでは分からないため）
- 取得は LotteryAdapter（polite 経由）。遮断（401/403/429・robots 禁止）されたら、その実行ではこれ以上取得しない
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter

BASE_URL = "https://www.hbst.net"
LISTING_URL = BASE_URL + "/result/?category=news"
_CARD_SPLIT = re.compile(r'(?=<div class="blogb[ "])')
_CARD_TITLE = re.compile(r'<p class="text-left">\s*(.*?)\s*</p>', re.S)
_CARD_LINK = re.compile(r'href="(https://www\.hbst\.net/\?p=(\d+))"')
_CARD_DATE = re.compile(r"【(\d{4})\.(\d{1,2})\.(\d{1,2})】")
_TITLE_TAG = re.compile(r"<title>(.*?)</title>", re.S)
_ARTICLE = re.compile(r'<section id="article".*?</section>', re.S)
_PRODUCT_IN_TITLE = re.compile(r"[「『](.+?)[」』]")
_NAME_BAD = re.compile(r"[※。]|[：:]\s|お一人様|抽選|応募|当選|注意|期間|発売日")


def _tcg_of(text: str):
    if re.search(r"ポケモンカード|ポケカ", text):
        return "POKEMON"
    if re.search(r"ONE ?PIECE|ワンピース", text, re.I):
        return "ONE_PIECE"
    return None


def parse_listing(html: str) -> list[dict]:
    """一覧のカード（件名の先頭・詳細の URL・公開日）。件名の無いカード・詳細の URL の無いカードは読まない。"""
    out = []
    for block in _CARD_SPLIT.split(html or ""):
        t = _CARD_TITLE.search(block)
        lk = _CARD_LINK.search(block)
        if not t or not lk:
            continue
        title = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", t.group(1)))).strip()
        d = _CARD_DATE.search(title)
        published = None
        if d:
            try:
                published = datetime(int(d.group(1)), int(d.group(2)), int(d.group(3)), tzinfo=JST).isoformat()
            except ValueError:
                published = None
        out.append({"url": lk.group(1), "post_id": lk.group(2), "title": title, "published_at": published})
    return out


def parse_detail(html: str) -> dict:
    """詳細ページ: 完全な件名（<title> から店名の接尾辞を除く）・本文のテキスト（数値文字参照を戻したもの）。"""
    m = _TITLE_TAG.search(html or "")
    title = re.sub(r"\s*-\s*ホビーステーション\s*$", "", unescape(m.group(1)).strip()) if m else ""
    a = _ARTICLE.search(html or "")
    # <article> に当たる本文の領域が無いページは、ページ全体（サイドバー・他の記事）の日程を読まない
    body = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(a.group(0)))).strip() if a else ""
    return {"title": title, "body": body}


def product_of(title: str) -> str:
    """件名の「…」の中の商品名。商品名として読めない（説明文・日付が混ざる・長すぎる）ときは空。"""
    m = _PRODUCT_IN_TITLE.search(title or "")
    n = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return n if 4 <= len(n) <= 80 and not _NAME_BAD.search(n) else ""


class HobbyStationLotteryAdapter(LotteryAdapter):
    source_id = "HOBBY_STATION"
    retailer = "HOBBY_STATION"
    retailer_name = "ホビーステーション"
    source_name = "ホビーステーション（公式お知らせの抽選販売）"
    tcg = "POKEMON"
    channel = "STORE"
    max_detail_fetch = 8
    lottery_source_type = "STORE_OFFICIAL"

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
                # 取得はできたが、記事のカードを1件も読めない（HTML の構造の変更の可能性）。静かに「0件」にしない
                self.health["errors"] += 1
                self.funnel.errors += 1
                self.funnel.structure_changed_pages += 1
                self.health["error_messages"].append("一覧は取得できたが記事のカードを読めなかった（HTML の構造の変更の可能性）")
            for c in cards:
                self.funnel.news_pages_discovered += 1
                if not re.search(r"抽選|予約", c["title"]) or not _tcg_of(c["title"]):
                    self.funnel.reject(REJECT_NOT_CANDIDATE)          # 抽選・予約でない告知（休業・イベント等）やカード以外
                    continue
                cands.append(c)
        self.funnel.product_links_discovered = len(cands)
        # 応募が終わった告知（件名に「応募は終了」）は後ろへ。残りは公開日の新しい順
        cands.sort(key=lambda c: ("応募は終了" not in c["title"], str(c.get("published_at") or "")[:10], c["post_id"]), reverse=True)
        for c in cands[:self.max_detail_fetch]:
            if self._stop_if_blocked():
                break
            page = self.fetch_detail(c["url"], referer=LISTING_URL)
            if not page:
                continue
            d = parse_detail(page)
            if not d["body"]:
                self.funnel.structure_changed_pages += 1         # 詳細に本文の領域が無い（HTML の構造の変更の疑い）。日程は読まない
                self.health["error_messages"].append("詳細ページに本文の領域（article）が無かった（HTML の構造の変更の可能性）")
            title = d["title"] or c["title"]
            prod = product_of(title)
            targets = [{"product_name": prod, "retail_price": None}] if prod else None
            self.lottery_events.extend(self.build_from_article(
                title=title, body=d["body"], url=c["url"], published_at=c["published_at"],
                entry_url=None, result_url=None, tcg_hint=_tcg_of(title), targets=targets))
        if len(cands) > self.max_detail_fetch:
            self.health["truncated"] = True
            self.funnel.notes.append(f"詳細は {self.max_detail_fetch}/{len(cands)} 件のみ取得（同一ドメインの間隔を守るため）")
        return self.finish()
