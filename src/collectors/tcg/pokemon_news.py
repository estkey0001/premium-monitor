# -*- coding: utf-8 -*-
"""PokemonNewsCollector — ポケモンカード公式ニュースから販売に関する記事だけを抽出する。

取得元: https://www.pokemon-card.com/info/
  一覧の各記事には公式カテゴリ（Calendar_Label_Event = イベント /
  Calendar_Label_Products = 商品 / Calendar_Label_Column = コラム / ラベル無し）が
  付いている。

方針:
  - 公式カテゴリが「イベント」「コラム」の記事は本文を取得せずに棄却する
    （大会・ジムバトル・体験会・デッキレシピ等を販売情報にしない）。
  - タイトルが大会・キャンペーン参加・プレイヤー募集等なら棄却する。
  - 「商品」カテゴリ、またはタイトルに販売語（抽選 / 予約 / 販売 / 発売 /
    再販 / 追加販売 / 購入）を含む直近の記事だけ本文を取得する。
  - 本文でも sales_context（商品語 + 販売語、非販売告知の除外）を通す。
  - 日付はラベル近傍のみ（応募期間 / 当選発表 / 購入期限 / 発売日 等）。
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Optional
from urllib.parse import urljoin

from src.tcg.classify import classify_event_type
from src.tcg.funnel import (
    PAGE_NEWS, PAGE_NEWS_INDEX, REJECT_EVENT_CATEGORY, REJECT_NO_SALE_CONTEXT, REJECT_NON_SALE, REJECT_NOT_PRODUCT_LOTTERY,
    REJECT_UNKNOWN_METHOD,
)
from src.tcg.models import (
    BASIS_ARTICLE_DATE_ONLY, CHANNEL_UNKNOWN, EVENT_LOTTERY, JST, TCG_POKEMON,
    TcgEvent, now_jst, parse_dt,
)
from src.tcg.product_types import (
    PT_ACCESSORY, PT_OTHER, classify_pokemon_product_type,
)
from src.tcg.sales_context import (
    has_sale_context, is_non_sale_announcement, is_product_lottery,
)

from .base import BaseTcgCollector
from .keyword_page import clean_product_name, slugify

SITE_ROOT = "https://www.pokemon-card.com"
NEWS_INDEX_URL = SITE_ROOT + "/info/"

# 直近何日の記事を対象にするか
NEWS_LOOKBACK_DAYS = 45
# 1回の実行で本文を取得する記事数の上限（同一ドメイン60秒間隔のため）
MAX_ARTICLE_FETCH = 3

# 公式カテゴリ（CSS クラス名 → 表示名）
CATEGORY_EVENT = "Event"
CATEGORY_PRODUCTS = "Products"
CATEGORY_COLUMN = "Column"
CATEGORY_OTHER = "Other"          # ラベル無し（公式では「その他」扱い）
REJECTED_CATEGORIES = (CATEGORY_EVENT, CATEGORY_COLUMN)

# タイトルに含まれていれば本文を取得する販売語
TITLE_SALE_WORDS = ("抽選", "予約", "販売", "発売", "再販", "追加販売", "購入", "受注")

# 本文で要求する「カード商品」語（フィギュア・グッズ等を販売情報にしない）
CARD_PRODUCT_WORDS = (
    "拡張パック", "強化拡張パック", "ハイクラスパック", "スターターセット",
    "スタートデッキ", "デッキセット", "スペシャルBOX", "スペシャルボックス",
    "プレミアムトレーナーボックス", "カードセット", "プロモカードパック",
    "BOX", "ボックス",
)
REJECT_NON_CARD_PRODUCT = "non_card_product"
REJECT_TOO_OLD = "article_too_old"

_ITEM_RE = re.compile(
    r'<a class="List_item_inner" href="(/info/\d+\.html)">(.*?)</a>', re.S)
_LABEL_RE = re.compile(r'Calendar_Label_(\w+)">([^<]*)<')
_DATE_RE = re.compile(r'<span class="Date[^"]*">\s*(\d{4})\.(\d{1,2})\.(\d{1,2})\s*</span>')
_STRIP_RE = re.compile(
    r'<div class="Calendar_Label[^>]*>.*?</div>|<span class="Date.*?</span>|<img[^>]*>',
    re.S)


def parse_news_index(html: str) -> list[dict]:
    """ニュース一覧 HTML から記事の一覧（URL / 公式カテゴリ / 公開日 / タイトル）を返す。"""
    out: list[dict] = []
    seen: set[str] = set()
    for href, body in _ITEM_RE.findall(html or ""):
        url = urljoin(SITE_ROOT, href)
        if url in seen:
            continue
        seen.add(url)
        lab = _LABEL_RE.search(body)
        d = _DATE_RE.search(body)
        published = None
        if d:
            try:
                from datetime import datetime
                published = datetime(int(d.group(1)), int(d.group(2)), int(d.group(3)),
                                     tzinfo=JST).isoformat()
            except ValueError:
                published = None
        title = BaseTcgCollector.to_text(_STRIP_RE.sub("", body)).strip()
        out.append({
            "url": url,
            "category": lab.group(1) if lab else CATEGORY_OTHER,
            "category_label": (lab.group(2) if lab else "その他"),
            "published_at": published,
            "title": re.sub(r"\s+", " ", title),
        })
    return out


# 記事の公開日行（「2026.8.20」「2026年 3月 13日（金）更新」の2形式がある）
_ARTICLE_DATE_LINE_RE = re.compile(
    r"^\s*(?:\d{4}\.\d{1,2}\.\d{1,2}|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)")
_PRODUCT_NAME_FIELD_RE = re.compile(r"商品名\s*\n\s*([^\n]{2,80})")


def _article_region(text: str, title: str) -> str:
    """ページ本文から記事部分を切り出す。

    タイトルは <title>・パンくず・見出しに繰り返し現れるため、
    「公開日の行の直前にあるタイトル行」を記事の先頭とする。
    ナビゲーションの語（「ポケモンカードチャンネル」等）を記事と誤認しないため。
    見つからない場合は最後のタイトル出現位置から切り出す。
    """
    key = (title or "")[:12]
    lines = (text or "").split("\n")
    if key:
        for i, line in enumerate(lines):
            if (i + 1 < len(lines) and key in line
                    and _ARTICLE_DATE_LINE_RE.match(lines[i + 1])):
                return "\n".join(lines[i:])[:3000]
        starts = [m.start() for m in re.finditer(re.escape(key), text)]
        if starts:
            return text[starts[-1]:starts[-1] + 3000]
    return (text or "")[:3000]


def article_product_name(body: str) -> Optional[str]:
    """記事の「商品名」欄の値（あれば）。"""
    m = _PRODUCT_NAME_FIELD_RE.search(body or "")
    return m.group(1).strip() if m else None


def guess_api_type(name: str) -> str:
    """商品名から公式 API の productType 相当を推定する（種別判定用）。"""
    n = name or ""
    if "拡張パック" in n or "ハイクラスパック" in n:
        return "拡張パック"
    if "スターター" in n or "デッキ" in n:
        return "構築デッキ"
    return "その他の商品"


class PokemonNewsCollector(BaseTcgCollector):
    """ポケモンカード公式ニュースの販売関連記事だけをイベント化する。"""

    source_key = "POKEMON_CARD_OFFICIAL"
    source_name = "ポケモンカードゲーム公式（ニュース）"
    tcg = TCG_POKEMON
    channel = CHANNEL_UNKNOWN
    urls = (NEWS_INDEX_URL,)
    requires_news_pages = True          # 記事を1件も発見できなければ DEGRADED

    def __init__(self) -> None:
        super().__init__()
        self.articles: list[dict] = []

    def collect(self) -> list[dict]:
        self.health["last_checked"] = now_jst().isoformat()
        now = now_jst()
        self.funnel.pages_discovered += 1
        html = self._fetch(NEWS_INDEX_URL, page_type=PAGE_NEWS_INDEX)
        if not html:
            return self._finish([])
        self.health["last_success"] = now.isoformat()

        items = parse_news_index(html)
        self.funnel.news_pages_discovered = len(items)

        to_fetch: list[dict] = []
        for it in items:
            self.funnel.candidate_events += 1
            it["decision"] = None
            if it["category"] in REJECTED_CATEGORIES:
                it["decision"] = REJECT_EVENT_CATEGORY
                self.funnel.reject(REJECT_EVENT_CATEGORY)
                continue
            if is_non_sale_announcement(it["title"]):
                it["decision"] = REJECT_NON_SALE
                self.funnel.reject(REJECT_NON_SALE)
                continue
            pub = parse_dt(it["published_at"])
            if not pub or pub < now - timedelta(days=NEWS_LOOKBACK_DAYS):
                it["decision"] = REJECT_TOO_OLD
                self.funnel.reject(REJECT_TOO_OLD)
                continue
            if (it["category"] != CATEGORY_PRODUCTS
                    and not any(w in it["title"] for w in TITLE_SALE_WORDS)):
                it["decision"] = REJECT_NO_SALE_CONTEXT
                self.funnel.reject(REJECT_NO_SALE_CONTEXT)
                continue
            to_fetch.append(it)

        events: list[TcgEvent] = []
        for it in to_fetch[:MAX_ARTICLE_FETCH]:
            self.funnel.pages_discovered += 1
            art_html = self._fetch(it["url"], page_type=PAGE_NEWS, referer=NEWS_INDEX_URL)
            if not art_html:
                continue
            self.funnel.news_pages_loaded += 1
            ev = self._parse_article(it, self.to_text(art_html), now)
            if ev is not None:
                events.append(ev)
        if len(to_fetch) > MAX_ARTICLE_FETCH:
            self.funnel.notes.append(
                f"記事本文は {MAX_ARTICLE_FETCH}/{len(to_fetch)} 件のみ取得"
                "（同一ドメイン60秒間隔のため取得数を制限）")
        self.articles = items
        return self._finish([e.to_dict() for e in events])

    def _parse_article(self, it: dict, text: str, now) -> Optional[TcgEvent]:
        """記事本文から販売イベントを作る。販売文脈が無ければ棄却。"""
        page = self.funnel.pages[-1]
        page.candidate_blocks += 1
        body = _article_region(text, it["title"])
        head = it["title"] + " " + body[:600]

        def _reject(reason: str) -> None:
            it["decision"] = reason
            self.funnel.reject(reason)
            page.rejected += 1

        if is_non_sale_announcement(head):
            _reject(REJECT_NON_SALE)
            return None
        if not has_sale_context(body):
            _reject(REJECT_NO_SALE_CONTEXT)
            return None
        # フィギュア・グッズ等はカード商品の販売情報として扱わない。
        # 記事に「商品名」欄があればそれを種別判定し、無ければ記事冒頭で判定する
        # （本文中で「拡張パック○○に収録…」と言及されるだけの記事を通さない）。
        pname = article_product_name(body)
        if pname:
            ptype = classify_pokemon_product_type(guess_api_type(pname), pname)
            if ptype in (PT_ACCESSORY, PT_OTHER):
                _reject(REJECT_NON_CARD_PRODUCT)
                return None
        elif not any(w in head for w in CARD_PRODUCT_WORDS):
            _reject(REJECT_NON_CARD_PRODUCT)
            return None
        et = classify_event_type(head, store=self.source_key, channel=self.channel)
        if et is None:
            et = classify_event_type(body, store=self.source_key, channel=self.channel)
        if et is None:
            _reject(REJECT_UNKNOWN_METHOD)
            return None
        if et == EVENT_LOTTERY and not is_product_lottery(body):
            _reject(REJECT_NOT_PRODUCT_LOTTERY)
            return None

        dates = self.extract_labeled_datetimes(body)
        kwargs: dict = {}
        fields = (("application_start", "application_end", "result_date",
                   "purchase_start", "purchase_end", "shipping_date")
                  if et == EVENT_LOTTERY else ("sale_start", "sale_end"))
        for f in fields:
            if dates.get(f):
                kwargs[f] = dates[f]
        # TTL で管理するイベントは記事の公開日を報告時刻にする（取得時刻で補完しない）
        kwargs["reported_at"] = it["published_at"]

        name = (pname or clean_product_name(it["title"]) or it["title"])
        ev = self.build_event(
            product_id="pokemon-news-" + slugify(name),
            product_name=name,
            text=body[:1500],
            url=it["url"],
            event_type=et,
            price=self.extract_price(body),
            article_title=it["title"],
            article_category=it["category_label"],
            published_at=it["published_at"],
            # 記事の公開日だけが根拠（販売時刻・在庫は不明）なので AVAILABLE_NOW にしない
            availability_basis=BASIS_ARTICLE_DATE_ONLY,
            note=body[:200],
            **kwargs,
        )
        if ev is None:
            _reject(REJECT_UNKNOWN_METHOD)
            return None
        it["decision"] = "accepted"
        self.funnel.accept()
        page.accepted += 1
        return ev
