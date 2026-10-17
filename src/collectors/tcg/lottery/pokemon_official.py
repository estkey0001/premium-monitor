# -*- coding: utf-8 -*-
"""ポケモンカード公式ニュースを起点にした抽選コレクター。

PcoLotteryAdapter:
  ポケモンカード公式ニュース一覧（pokemon-card.com/info/）には、ポケモンセンター
  オンライン（PCO）の抽選告知への外部リンクが掲載される。一覧から PCO の抽選告知を
  発見し、PCO の告知ページを取得して日程を読む。
  - PCO は CI（GitHub Actions）から HTTP 403 になる。bot 対策は回避しない
    （CAPTCHA 回避・stealth browser・proxy・fingerprint 偽装はしない）。
  - 取得できない／日程が画像のみの場合は「抽選告知あり（日程未取得）」として残し、
    日程は data/tcg_verified_lotteries.csv の手動確認済みデータで補う。

PokemonNewsLotteryAdapter:
  公式ニュースの記事（/info/NNNNNN.html）のうち、抽選販売に関する記事を取得する。
  公式カテゴリ「イベント」の記事（大会・ジムバトル等）は本文を取得せずに棄却する。
"""
from __future__ import annotations

import re
from datetime import datetime

from src.tcg.lottery.schema import SRC_MANUFACTURER
from src.tcg.models import JST, now_jst

from .base import (
    REJECT_NOT_CANDIDATE, REJECT_TOURNAMENT, TOURNAMENT_TERMS, LotteryAdapter, anchors,
)

NEWS_INDEX = "https://www.pokemon-card.com/info/"
PCO_HOST = "www.pokemoncenter-online.com"
_DATE_TAIL = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\s*$")
_LABELS = ("イベント", "商品", "コラム", "その他")
_PCO_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


# 一覧のタイトルだけで分かる販売の種類（Phase 27 の発見の候補。本文は読まない・日程は推測しない）
DISCOVERY_KINDS = (("LOTTERY", ("抽選",)), ("PREORDER", ("予約",)), ("FIRST_COME", ("先着",)),
                   ("RESTOCK", ("再販", "再出荷", "再生産", "追加生産")))
MAX_DISCOVERED_TITLES = 30
DISCOVERY_EXCLUDE = ("終了", "お詫び", "中止", "締め切り", "締切りました")


def discovery_kind(title: str) -> str:
    """タイトルの販売の種類（抽選 / 予約 / 先着 / 再販）。当てはまらなければ空。"""
    for kind, words in DISCOVERY_KINDS:
        if any(w in (title or "") for w in words):
            return kind
    return ""


def _parse_index_item(text: str) -> tuple[str, str, str | None]:
    """一覧のアンカーテキスト「その他 タイトル (外部リンク) 2026.9.29」を分解する。"""
    t = text.strip()
    category = ""
    for lab in _LABELS:
        if t.startswith(lab + " "):
            category, t = lab, t[len(lab) + 1:]
            break
    published = None
    m = _DATE_TAIL.search(t)
    if m:
        try:
            published = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                 tzinfo=JST).isoformat()
        except ValueError:
            published = None
        t = t[:m.start()].strip()
    t = t.replace("(外部リンク)", "").strip()
    return category, t, published


class PcoLotteryAdapter(LotteryAdapter):
    source_id = "POKEMON_CENTER_ONLINE"
    retailer = "POKEMON_CENTER_ONLINE"
    retailer_name = "ポケモンセンターオンライン"
    source_name = "ポケモンセンターオンライン（公式ニュース経由）"
    tcg = "POKEMON"
    # PCO は株式会社ポケモンの公式ストアなのでメーカー公式として扱う
    lottery_source_type = SRC_MANUFACTURER
    max_detail_fetch = 3

    def collect(self) -> list[dict]:
        self.health["last_checked"] = now_jst().isoformat()
        html = self.fetch_listing(NEWS_INDEX)
        if not html:
            return self.finish()
        self.health["last_success"] = now_jst().isoformat()
        cands: list[dict] = []
        seen: set[str] = set()
        for url, text in anchors(html, NEWS_INDEX):
            if self.host(url) != PCO_HOST or url in seen:
                continue
            seen.add(url)
            category, title, published = _parse_index_item(text)
            self.funnel.news_pages_discovered += 1
            if "抽選" not in title:
                self.funnel.reject(REJECT_NOT_CANDIDATE)
                continue
            # 大会は候補にしない。キャンペーン等の判定は本文を読んでから行う
            # （タイトルだけで正当な抽選販売を落とさないため）
            if any(w in title for w in TOURNAMENT_TERMS):
                self.funnel.reject(REJECT_TOURNAMENT)
                continue
            cands.append({"url": url, "title": title, "published_at": published})
        self.funnel.product_links_discovered = len(cands)
        self.funnel.product_pages_discovered = len(cands)

        for c in cands[:self.max_detail_fetch]:
            detail = self.fetch_detail(c["url"], referer=NEWS_INDEX)
            if not detail:
                # PCO 本体が取得できない（CI では HTTP 403）。告知の存在だけを記録する。
                # 本文で確認できないので、タイトルで大会・プレゼント等を厳しく除外する
                reason = self.screen_announcement_title(c["title"])
                if reason:
                    self.funnel.reject(reason)
                    continue
                self.announcements.append({
                    "title": c["title"], "source_url": c["url"],
                    "listed_on": NEWS_INDEX, "published_at": c["published_at"],
                    "retailer": self.retailer, "retailer_name": self.retailer_name,
                    "tcg": "POKEMON",
                    "reason": "公式ニュース一覧で抽選告知を確認。PCO 本体は取得できないため"
                              "日程は手動確認済みデータで補う",
                })
                continue
            text = self.to_text(detail)
            title = c["title"]
            m = re.search(r"<title[^>]*>(.*?)[｜|]", detail, re.S)
            if m:
                title = self.to_text(m.group(1)).strip() or title
            pub = c["published_at"]
            d = _PCO_DATE.search(text)
            if d:
                pub = datetime(int(d.group(1)), int(d.group(2)), int(d.group(3)),
                               tzinfo=JST).isoformat()
            i = text.find("トップページ\n")
            body = text[i:] if i >= 0 else text
            self.lottery_events.extend(self.build_from_article(
                title=title, body=body, url=c["url"], published_at=pub,
                tcg_hint="POKEMON"))
        return self.finish()


class PokemonNewsLotteryAdapter(LotteryAdapter):
    source_id = "POKEMON_CARD_OFFICIAL"
    retailer = "POKEMON_CARD_OFFICIAL"
    retailer_name = "ポケモンカードゲーム公式"
    source_name = "ポケモンカードゲーム公式（抽選記事）"
    tcg = "POKEMON"
    lottery_source_type = SRC_MANUFACTURER
    max_detail_fetch = 2

    def collect(self) -> list[dict]:
        self.health["last_checked"] = now_jst().isoformat()
        html = self.fetch_listing(NEWS_INDEX)
        if not html:
            return self.finish()
        self.health["last_success"] = now_jst().isoformat()
        cands: list[dict] = []
        seen: set[str] = set()
        discovered: list[dict] = []
        for url, text in anchors(html, NEWS_INDEX):
            if not re.search(r"/info/\d+\.html$", url) or url in seen:
                continue
            seen.add(url)
            category, title, published = _parse_index_item(text)
            self.funnel.news_pages_discovered += 1
            if category in ("イベント", "コラム"):
                self.funnel.reject(REJECT_TOURNAMENT)   # 大会・イベント記事は本文を取得しない
                continue
            kind = discovery_kind(title)
            if "抽選" not in title:
                self.funnel.reject(REJECT_NOT_CANDIDATE)
                # 予約・先着・再販の告知はタイトルだけを発見の候補として残す（本文は読まない。Phase 27）
                # 受付の終了・お詫び・中止の告知は候補にしない（監査 L-6）
                if kind and not self.screen_title(title) and not any(w in title for w in DISCOVERY_EXCLUDE):
                    discovered.append({"url": url, "title": title, "published_at": published, "kind": kind,
                                       "reason": "title_only_not_fetched"})
                continue
            reason = self.screen_title(title)
            if reason:
                self.funnel.reject(reason)
                continue
            cands.append({"url": url, "title": title, "published_at": published})
        self.funnel.product_links_discovered = len(cands)
        # 本文を読む件数の上限で読まなかった抽選の記事も、発見の候補として残す（次の実行まで見落とさない。Phase 27）
        for c in cands[self.max_detail_fetch:]:
            discovered.append(dict(c, kind="LOTTERY", reason="detail_fetch_limit"))
        self.health["discovered_titles"] = discovered[:MAX_DISCOVERED_TITLES]
        for c in cands[:self.max_detail_fetch]:
            detail = self.fetch_detail(c["url"], referer=NEWS_INDEX)
            if not detail:
                continue
            text = self.to_text(detail)
            self.lottery_events.extend(self.build_from_article(
                title=c["title"], body=text, url=c["url"],
                published_at=c["published_at"], tcg_hint="POKEMON"))
        return self.finish()
