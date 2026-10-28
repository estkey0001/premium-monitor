# -*- coding: utf-8 -*-
"""CardLaboLotteryAdapter — カードラボ（c-labo.jp）の店舗ブログから、ポケカ・ONE PIECE の抽選販売の告知を取得する。

Market Research Coverage Wave 1。店舗ごとのブログ（/shop/<店>/blog/<ID>/）に、抽選・抽選予約の告知が静的 HTML で載り、
応募期間・当選発表・購入期間・商品名・価格が本文のテキストにある（2026-10-24 に robots 許可・規約に自動取得の禁止の記述が
無いことを確認。調査: 合成した例では 15 件のカードから抽選の告知を選ぶ）。

- 一覧: /blog/filter/tcg:25/（ポケカ）・/blog/filter/tcg:184/（ONE PIECE）。1枚のカード = 1件の告知（件名・店・公開日）
- 応募は店舗の X（旧 Twitter）のフォロー＆リポスト。公式ドメインの応募ページは無いので entry_url は空（応募ページの
  リンクを作らない・推測しない）
- 店舗ごとの抽選（store_specific）として作る。日程が本文に無い告知は、日程を推測せず要確認として残す（base の既定）
- 取得は LotteryAdapter（polite 経由: robots・同じドメインの間隔・正直な User-Agent）。ログイン・検索結果は使わない
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter

BASE_URL = "https://www.c-labo.jp"
LISTINGS = (("POKEMON", BASE_URL + "/blog/filter/tcg:25/"), ("ONE_PIECE", BASE_URL + "/blog/filter/tcg:184/"))
_CARD_SPLIT = re.compile(r'(?=<div class="claboCard[ "])')
_TITLE_RE = re.compile(r'class="claboCard_title">\s*<a [^>]*href="([^"]+)"[^>]*title="([^"]*)"', re.S)
_SHOP_RE = re.compile(r'class="claboCard_shop">\s*<a [^>]*href="/shop/([^/"]+)/"[^>]*>\s*([^<]*?)\s*</a>', re.S)
_DATE_RE = re.compile(r'class="claboCard_date">\s*(\d{4})\.(\d{1,2})\.(\d{1,2})')
_ARTICLE_RE = re.compile(r"<article.*?</article>", re.S)
_DETAIL_PATH = re.compile(r"^/shop/[^/]+/blog/\d+/$")
# 告知の本文の書き方（2026-10-24 の実例）: 「対象商品 <商品名> お一人様 20pack：7,200円（税込）」「商品名：<商品名> ※…」
_TARGET_A = re.compile(r"対象商品[〉】」』]?\s+((?:(?!対象商品).)+?)\s+お一人様([^：:]{0,30})[：:]\s*([\d,]{3,})\s*円")
_TARGET_B = re.compile(r"商品名[：:]\s*(.+?)\s*(?=※|発売日|お一人様|抽選期間|応募期間|当選|販売価格|価格[：:]|$)")
_NAME_BAD = re.compile(r"[※。]|[：:]\s|お一人様|抽選|応募|当選|注意|発売日|対象商品|期間")
_PACK_RE = re.compile(r"pack|パック|枚", re.I)


def _clean_name(name: str) -> str:
    """商品名として読めるときだけ返す（説明文・日付・条件が混ざった長い文字列は使わない。空なら件名から補う）。"""
    n = re.sub(r"\s+", " ", name or "").strip(" 　・")
    return n if 4 <= len(n) <= 80 and not _NAME_BAD.search(n) else ""


def parse_targets(body: str) -> list[dict]:
    """本文の対象商品（商品名・価格）。決まった書き方で、商品名として読めるものだけ（読めなければ空 = 件名から補う。推測しない）。

    「お一人様 20pack：7,200円」の価格は、パックの組（20パック）の合計なので、定価として使わない（retail_price=None。
    パックの価格から BOX の価格を作らない・BOX の価格から1パックの価格も作らない）。
    """
    t = re.sub(r"\s+", " ", body or "")
    out = []
    for m in _TARGET_A.finditer(t):
        name = _clean_name(m.group(1))
        if not name:
            continue
        qty = re.match(r"\s*(\d+)", m.group(2) or "")
        # パックの組・2個以上の合計は定価にしない（単価が明示されたときだけ採用）
        price = None if _PACK_RE.search(m.group(2) or "") or (qty and int(qty.group(1)) >= 2) else int(m.group(3).replace(",", ""))
        out.append({"product_name": name, "retail_price": price})
    if not out:
        for m in _TARGET_B.finditer(t):
            name = _clean_name(m.group(1))
            if name:
                out.append({"product_name": name, "retail_price": None})
    seen, uniq = set(), []
    for x in out:
        if x["product_name"] not in seen:
            seen.add(x["product_name"])
            uniq.append(x)
    return uniq


def parse_listing(html: str) -> list[dict]:
    """一覧のカード（件名・詳細の URL・店・公開日）。カードの形でないものは読まない。"""
    out = []
    for block in _CARD_SPLIT.split(html or ""):
        t = _TITLE_RE.search(block)
        if not t:
            continue
        href, title = t.group(1).strip(), re.sub(r"\s+", " ", t.group(2)).strip()
        if not _DETAIL_PATH.match(href):
            continue                      # 店舗ブログの詳細以外（外部のリンクなど）は使わない
        shop = _SHOP_RE.search(block)
        d = _DATE_RE.search(block)
        published = None
        if d:
            try:
                published = datetime(int(d.group(1)), int(d.group(2)), int(d.group(3)), tzinfo=JST).isoformat()
            except ValueError:
                published = None
        out.append({"url": BASE_URL + href, "title": title, "shop_slug": shop.group(1) if shop else "",
                    "shop_name": (shop.group(2).strip() if shop else ""), "published_at": published})
    return out


class CardLaboLotteryAdapter(LotteryAdapter):
    source_id = "CARD_LABO"
    retailer = "CARD_LABO"
    retailer_name = "カードラボ"
    source_name = "カードラボ（店舗ブログの抽選・予約の告知）"
    tcg = "POKEMON"
    channel = "STORE"
    max_detail_fetch = 10
    # 店舗のブログで、公式ドメインの応募ページは無い。メーカー・小売本社の公式（RETAILER_OFFICIAL）ではなく、店舗の告知（STORE_OFFICIAL）
    lottery_source_type = "STORE_OFFICIAL"

    def _stop_if_blocked(self) -> bool:
        """403・429 などで遮断されたら、その実行の中ではこの取得元を取りに行かない（回避しない・別の経路で取り直さない）。"""
        if self.health.get("blocked"):
            self.funnel.notes.append("アクセス制限（401/403/429）を受けたので、この実行ではこれ以上取得しない")
            return True
        return False

    def collect(self) -> list[dict]:
        from src.tcg.models import now_jst
        self.health["last_checked"] = now_jst().isoformat()
        self.funnel.requires_news_pages = True       # 一覧は取れたのにカードを1件も読めないときは、正常ではなく劣化と判定する
        cands: list[tuple[str, dict]] = []
        loaded = False
        for tcg, url in LISTINGS:
            if self._stop_if_blocked():
                break
            html = self.fetch_listing(url)
            if not html:
                continue
            loaded = True
            cards = parse_listing(html)
            if not cards and "claboCard" not in html and url == LISTINGS[0][1]:
                # 取得はできたが、記事のカードが1件も無い（HTML の構造が変わった可能性）。静かに「0件」にしない
                self.health["errors"] += 1
                self.funnel.errors += 1
                self.health["error_messages"].append("一覧は取得できたが記事のカードを読めなかった（HTML の構造の変更の可能性）")
            seen = {c["url"] for _t, c in cands}
            for card in cards:
                if card["url"] in seen:
                    continue
                seen.add(card["url"])
                self.funnel.news_pages_discovered += 1
                # 抽選・予約の告知だけを候補にする（買取情報・大会の結果などは入れない）
                if not re.search(r"抽選|購入権", card["title"]):
                    self.funnel.reject(REJECT_NOT_CANDIDATE)
                    continue
                cands.append((tcg, card))
        if loaded:
            self.health["last_success"] = now_jst().isoformat()
        self.funnel.product_links_discovered = len(cands)
        # 公開日の新しい順に、詳細を取る（同じドメインは60秒間隔なので、上限を決める）
        # 同じ公開日の告知は、日ごとに順序を変える（毎日同じ店だけが先に取られ、後ろの店が取りこぼされ続けるのを防ぐ）
        today = now_jst().strftime("%Y-%m-%d")
        cands.sort(key=lambda tc: (str(tc[1].get("published_at") or "")[:10],
                                   hashlib.sha1(f"{today}|{tc[1]['url']}".encode()).hexdigest()), reverse=True)
        for tcg, card in cands[:self.max_detail_fetch]:
            if self._stop_if_blocked():
                break
            store = card["shop_name"]
            if not store:
                # 店舗が分からない告知は、店舗ごとの抽選として表せない（全国の抽選に見せない）。取らずに棄却する
                self.funnel.reject("store_not_identified")
                continue
            detail = self.fetch_detail(card["url"], referer=LISTINGS[0][1])
            if not detail:
                continue
            m = _ARTICLE_RE.search(detail)
            # 記事の本体（<article>）が無いページは、ページ全体（サイドバー・他の記事）の日程を読まない。本文を空にして要確認へ回す
            body = self.to_text(m.group(0)) if m else ""
            store_name = store if store.startswith("カードラボ") else f"カードラボ{store}"
            self.lottery_events.extend(self.build_from_article(
                title=card["title"], body=body, url=card["url"], published_at=card["published_at"],
                entry_url=None, result_url=None, tcg_hint=tcg, store_name=store_name,
                store_id=card["shop_slug"] or None, targets=parse_targets(body) or None))
        if len(cands) > self.max_detail_fetch:
            self.health["truncated"] = True          # 見つけた告知を全部は読めていない（取得元の穴として数える）
            self.funnel.notes.append(
                f"詳細は {self.max_detail_fetch}/{len(cands)} 件のみ取得（同一ドメイン60秒間隔）")
        return self.finish()
