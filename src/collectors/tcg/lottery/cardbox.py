# -*- coding: utf-8 -*-
"""CardBoxLotteryAdapter — CARD BOX（cardbox.online）加盟店の店舗ニュースから、ポケカ・ONE PIECE の抽選販売（購入権の抽選）の告知を取得する。

Coverage Wave 8。CARD BOX は加盟店（公式サイト上の表記で 107 店）の店舗ニュースを1つの一覧（/news/shop_list/。1ページ 15 件・新しい順）に載せる。
各項目に店名・ゲーム名（taxonomy）・件名・掲載日があり、詳細（/news/detail/?id=<連番>）の本文に「抽選受付期間」「当選番号の発表」が年の無い日付のテキストで載る
（2026-11-26 の調査: robots.txt は「User-agent: * / Allow:/」で全体を許可。利用規約のページは見つからず、自動取得を許可も禁止も未確認。
許可の明記でもないので、取得日つきの記録で、変更があれば再確認する）。

- 一覧: 1回の実行で 1〜2 ページ（2 ページ目は一覧の「次へ」のリンクから。リンクが無ければ取らない）
- 候補: taxonomy がポケモンカードゲーム／ONE PIECEカードゲームで、件名に「抽選」か「購入権」を含むもの。「当選者発表」など結果だけの告知は受付にしない
- 詳細: 本文は news-detail-content の中だけ読む（他の記事・フッターの日程を読まない）。年の無い日付は詳細の投稿日時（無ければ一覧の掲載日）の年で補い、
  曜日が書かれていれば一致を確かめる（共通の解析器。合わなければ日程にしない）。「当選番号の発表」は当選発表として読む
- 店ごとの抽選（store_specific）。店名は詳細の店舗欄（無ければ一覧の news-list-item-shop）、store_id は詳細の /shop/detail/<番号>
- 応募は店ごとの外部フォーム（公式ドメインではない）なので entry_url は作らない。価格は定価にしない
- 取得は LotteryAdapter（polite 経由）。遮断（401/403/429・robots 禁止）されたら、その実行ではこれ以上取得しない
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from typing import Optional

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter, product_code_of

BASE_URL = "https://cardbox.online"
LISTING_URL = BASE_URL + "/news/shop_list/"
DETAIL_URL = BASE_URL + "/news/detail/?id={id}"
MAX_LIST_PAGES = 2
TAXONOMY_TCG = {"ポケモンカードゲーム": "POKEMON", "ONE PIECEカードゲーム": "ONE_PIECE"}
REJECT_RESULT_ONLY = "result_announcement_only"
REJECT_IMPLAUSIBLE_YEAR = "schedule_far_from_publish_date"

_ITEM = re.compile(r'<a class="news-list-item"[^>]*?href="/news/detail/\?id=(\d+)[^"]*"[^>]*>(.*?)</a>', re.S)
_NEXT = re.compile(r'<a href="(/news/shop_list/\?[^"]*page=(\d+))"[^>]*rel="next"')
_YMD = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")
_POSTED = re.compile(r'news-detail-post-time.{0,400}?(\d{4})\.(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})', re.S)
_SHOP = re.compile(r'class="news-detail-shop[^"]*".{0,400}?<a href="/shop/detail/(\d+)">(.*?)</a>', re.S)
_H1 = re.compile(r'<h1 class="news-detail-title">(.*?)</h1>', re.S)
_LOTTERY_TITLE = re.compile(r"抽選|購入権")
_RESULT_TITLE = re.compile(r"当選者?発表|当選番号|抽選結果|結果発表|当選者の?方へ")
_PRODUCT = re.compile(r"[「『](.+?)[」』]")
_NAME_BAD = re.compile(r"[※。]|[：:]\s|お一人様|抽選|応募|当選|注意|期間")
_TITLE_TAIL = re.compile(r"\s*の?\s*(?:購入権)?\s*(?:抽選)\s*(?:購入|販売|受付)?\s*(?:につきまして|について|のお知らせ|のご案内)?\s*[!！]*\s*$")
_TITLE_HEAD = re.compile(r"^\s*(?:【[^】]{1,20}】\s*)*(?:\d{1,2}/\d{1,2}\s*発売の\s*)?")


def _text(frag: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", frag or "", flags=re.S)))).strip()


def _field(blk: str, name: str) -> str:
    m = re.search(r'<p class="news-list-item-' + name + r'"[^>]*>(.*?)</p>', blk, re.S)
    return _text(m.group(1)) if m else ""


def _iso(y, mo, d, h=0, mi=0) -> Optional[str]:
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), tzinfo=JST).isoformat()
    except ValueError:
        return None


def parse_listing(html: str) -> list[dict]:
    """一覧の項目（詳細の id・URL・件名・ゲーム名・掲載日・店名）。件名・掲載日の読めない項目は読まない。"""
    out, seen = [], set()
    for m in _ITEM.finditer(html or ""):
        nid, blk = m.group(1), m.group(2)
        title, date = _field(blk, "title"), _YMD.search(_field(blk, "date"))
        if nid in seen or not title or not date:
            continue
        published = _iso(*date.groups())
        if not published:
            continue
        seen.add(nid)
        out.append({"id": int(nid), "url": DETAIL_URL.format(id=nid), "title": title, "taxonomy": _field(blk, "taxonomy"),
                    "published_at": published, "shop": _field(blk, "shop")})
    return out


def next_page_url(html: str) -> Optional[str]:
    """一覧の「次へ」（rel="next"）のリンク。無ければ None（推測で URL を作らない）。"""
    m = _NEXT.search(html or "")
    return BASE_URL + unescape(m.group(1)) if m else None


def parse_detail(html: str) -> dict:
    """詳細: 件名・本文（news-detail-content の中だけ）・投稿日時・店名・店の番号。本文の領域が無ければ本文は空。"""
    h = html or ""
    i = h.find('class="news-detail-content"')
    body = ""
    if i >= 0:
        j = h.find("news-detail-tag-list", i)
        j = h.rfind("<", i, j) if j > 0 else h.find("</section>", i)          # タグ一覧の開始タグの手前まで
        body = _text(h[h.find(">", i) + 1: j if j > 0 else len(h)])
    pm = _POSTED.search(h)
    sm = _SHOP.search(h)
    tm = _H1.search(h)
    return {"body": body, "published_at": _iso(*pm.groups()) if pm else None,
            "shop": _text(sm.group(2)) if sm else "", "shop_id": sm.group(1) if sm else None,
            "title": _text(tm.group(1)) if tm else ""}


def normalize_body(body: str) -> str:
    """店ごとの書き方を共通の解析器のラベルにそろえる（値は変えない）。「当選番号の発表は」→「当選発表は」。"""
    return re.sub(r"当選番号の?発表", "当選発表", body or "")


def plausible(ev: dict, published_at: Optional[str]) -> bool:
    """応募期間の日付が掲載日の 31 日前～ 183 日後に入っているか。共通の解析器は、曜日の合わない日付を捨てたうえで、
    残りの日付を曜日の合う翌年に置くことがある（「10月1日（月）～10月5日（火）」→ 翌年の 10月5日だけが残る）。
    掲載日から離れすぎた日程は年の補い方が決まらないので採用しない（推測で作らない）。"""
    from src.tcg.models import parse_dt
    base = parse_dt(published_at)
    if base is None:
        return True
    for k in ("application_start", "application_end", "application_start_date", "application_end_date"):
        dt = parse_dt(ev.get(k))
        if dt is not None and not (-31 <= (dt.date() - base.date()).days <= 183):
            return False
    return True


def product_of(title: str) -> str:
    """件名の「…」『…』の中の商品名（最後のもの）。無ければ件名から「の購入権抽選につきまして」等を除いた残り。読めなければ空。"""
    for n in reversed([re.sub(r"\s+", " ", x).strip() for x in _PRODUCT.findall(title or "")]):
        if 2 <= len(n) <= 80 and not _NAME_BAD.search(n):
            return n
    t = _TITLE_TAIL.sub("", _TITLE_HEAD.sub("", title or "")).strip()
    return t if 4 <= len(t) <= 80 and not _NAME_BAD.search(t) else ""


class CardBoxLotteryAdapter(LotteryAdapter):
    source_id = "CARDBOX"
    retailer = "CARDBOX"
    retailer_name = "CARD BOX（加盟店）"
    source_name = "CARD BOX 加盟店の店舗ニュース（抽選販売・購入権）"
    tcg = "POKEMON"
    channel = "STORE"
    max_detail_fetch = 6
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
        items: list[dict] = []
        url: Optional[str] = LISTING_URL
        pages = 0
        while url and pages < MAX_LIST_PAGES:
            if pages and self._stop_if_blocked():
                break
            html = self.fetch_listing(url)
            pages += 1
            if not html:
                break
            self.health["last_success"] = now_jst().isoformat()
            got = parse_listing(html)
            if not got:
                self.health["errors"] += 1
                self.funnel.errors += 1
                self.funnel.structure_changed_pages += 1
                self.health["error_messages"].append("一覧は取得できたが項目を読めなかった（HTML の構造の変更の可能性）")
                break
            items.extend(got)
            url = next_page_url(html)
        cands: list[dict] = []
        seen: set[int] = set()
        for c in items:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            self.funnel.news_pages_discovered += 1
            tcg = TAXONOMY_TCG.get(c["taxonomy"])
            if not tcg or not _LOTTERY_TITLE.search(c["title"]):
                self.funnel.reject(REJECT_NOT_CANDIDATE)                     # 買取・大会・他のゲームなど
                continue
            if _RESULT_TITLE.search(c["title"]):
                self.funnel.reject(REJECT_RESULT_ONLY)                       # 当選者発表だけの告知は受付にしない
                continue
            cands.append({**c, "tcg": tcg})
        self.funnel.product_links_discovered = len(cands)
        cands.sort(key=lambda c: (c["published_at"], c["id"]), reverse=True)      # 新しい告知から
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
                self.health["error_messages"].append("詳細ページに本文の領域（news-detail-content）が無かった（HTML の構造の変更の可能性）")
            title = d["title"] or c["title"]
            prod = product_of(title)
            store = d["shop"] or c["shop"] or None
            published = d["published_at"] or c["published_at"]
            evs = self.build_from_article(
                title=title, body=normalize_body(d["body"]), url=c["url"], published_at=published,
                entry_url=None, result_url=None, tcg_hint=c["tcg"], store_name=store, store_id=d["shop_id"],
                targets=[{"product_name": prod, "retail_price": None, "product_code": product_code_of(prod)}] if prod else None)
            ok = [e for e in evs if plausible(e, published)]
            if len(ok) < len(evs):
                n = len(evs) - len(ok)
                self.reject(REJECT_IMPLAUSIBLE_YEAR)
                self.funnel.accepted_sales_events -= n
                if self.funnel.pages:
                    self.funnel.pages[-1].accepted -= n
                if not ok:
                    self.announcements.append({
                        "title": title, "source_url": c["url"], "published_at": published,
                        "retailer": self.retailer, "retailer_name": self.retailer_name, "tcg": c["tcg"],
                        "reason": "日程が掲載日から離れすぎていて年を決められない（曜日の誤記の可能性）。手動確認が必要"})
            self.lottery_events.extend(ok)
        skipped = max(0, len(cands) - self.max_detail_fetch)
        self.health.update({"detail_candidates": len(cands), "detail_fetched": fetched, "skipped_due_to_limit": skipped, "skipped_ended": 0,
                            "listing_pages": pages})
        if skipped:
            self.health["truncated"] = True
            self.funnel.notes.append(f"詳細は {fetched}/{len(cands)} 件のみ取得。{skipped} 件を上限のため読めていない")
        return self.finish()
