# -*- coding: utf-8 -*-
"""KidsRepublicLotteryAdapter — キッズリパブリック（イオンリテール）のキャンペーン情報から、ポケカ・ONE PIECE の抽選販売の告知を取得する。

Coverage Wave 3。キャンペーン情報（/campaign）に、アプリ抽選の告知が静的な HTML のテキストで載り、応募受付期間・当選発表日・購入期間が
本文にある（2026-10-29 の調査: robots.txt は 404 = 制限の記載なし。利用規約は自動取得を禁じる記述を読み取れなかった。許可の明記でもないので、
取得日つきの記録で、変更があれば再確認する）。

- 一覧: /campaign（1ページ 12 件・カードに公開日 YYYY.MM.DD とタイトル。詳細の URL は /campaign/campaign_detail/<スラッグ>）。ポケモンカード・ONE PIECE だけを候補にする
- 詳細: 本文は <main> の中だけ読む（ページ全体のスクリプト・他の記事の日程を読まない）。年が書かれていない日付は公開日の年で補う（共通の解析器）
- 応募はキッズリパブリックのアプリ（iAEON ID 連携）。公式ドメインの応募ページは無いので entry_url は作らない
- 対象は本州・四国の直営おもちゃ売場（店舗横断の1本の告知）。価格は定価にしない（BOX の本体価格・税込が混在し、一覧の表記で確かめられないため）
- 取得は LotteryAdapter（polite 経由）。遮断（401/403/429・robots 禁止）されたら、その実行ではこれ以上取得しない
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter

BASE_URL = "https://www.kidsrepublic.jp"
LISTING_URL = BASE_URL + "/campaign"
_CARD = re.compile(r'<li><a [^>]*href="(/campaign/campaign_detail/[A-Za-z0-9_\-]+)"[^>]*>(.*?)</a></li>', re.S)
_DATE = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")
_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_MAIN = re.compile(r"<main.*?</main>", re.S)
_TITLE_TAG = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)


def _text(frag: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", frag or "", flags=re.S)))).strip()


def _tcg_of(text: str):
    if re.search(r"ポケモンカード|ポケカ", text):
        return "POKEMON"
    if re.search(r"ONE ?PIECE|ワンピース", text, re.I):
        return "ONE_PIECE"
    return None


def parse_listing(html: str) -> list[dict]:
    """一覧のカード（詳細の URL・公開日・タイトル）。日付・タイトルの読めないカードは読まない。"""
    out = []
    for m in _CARD.finditer(html or ""):
        ps = [_text(p) for p in _P.findall(m.group(2))]
        date = next((p for p in ps if _DATE.fullmatch(p)), "")
        title = next((p for p in ps if p and p != date), "")
        d = _DATE.fullmatch(date)
        if not d or not title:
            continue
        try:
            published = datetime(int(d.group(1)), int(d.group(2)), int(d.group(3)), tzinfo=JST).isoformat()
        except ValueError:
            continue
        out.append({"url": BASE_URL + m.group(1), "title": title, "published_at": published})
    return out


def parse_detail(html: str) -> dict:
    """詳細: 本文（<main> の中のテキスト）。<main> が無ければ本文は空（ページ全体の日程を読まない）。"""
    m = _MAIN.search(html or "")
    return {"body": _text(m.group(0)) if m else ""}


def product_of(title: str, body: str) -> str:
    """商品名: 件名の「【…】」の接頭辞・「応募手続き」を除いた残り。読めない（長すぎる・説明文が混ざる）ときは空。"""
    t = re.sub(r"^(?:【[^】]{1,20}】\s*)+", "", title or "")
    t = re.sub(r"\s*応募手続き\s*", " ", t)
    t = re.sub(r"^【(.+)】$", r"\1", t.strip()).strip()
    return t if 4 <= len(t) <= 90 and not re.search(r"[※。]|応募期間|当選|抽選販売のお知らせ", t) else ""


class KidsRepublicLotteryAdapter(LotteryAdapter):
    source_id = "KIDS_REPUBLIC"
    retailer = "KIDS_REPUBLIC"
    retailer_name = "キッズリパブリック（イオン）"
    source_name = "キッズリパブリック（キャンペーン情報のアプリ抽選）"
    tcg = "POKEMON"
    channel = "APP"
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
                if not _tcg_of(c["title"]):
                    self.funnel.reject(REJECT_NOT_CANDIDATE)                # 遊戯王・トミカ等、ポケカ・ONE PIECE 以外
                    continue
                cands.append(c)
        self.funnel.product_links_discovered = len(cands)
        cands.sort(key=lambda c: str(c.get("published_at") or ""), reverse=True)     # 新しい告知から
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
                self.health["error_messages"].append("詳細ページに本文の領域（main）が無かった（HTML の構造の変更の可能性）")
            prod = product_of(c["title"], d["body"])
            self.lottery_events.extend(self.build_from_article(
                title=c["title"], body=d["body"], url=c["url"], published_at=c["published_at"], entry_url=None, result_url=None,
                tcg_hint=_tcg_of(c["title"]), targets=[{"product_name": prod, "retail_price": None}] if prod else None))
        skipped = max(0, len(cands) - self.max_detail_fetch)
        self.health.update({"detail_candidates": len(cands), "detail_fetched": fetched, "skipped_due_to_limit": skipped, "skipped_ended": 0})
        if skipped:
            self.health["truncated"] = True
            self.funnel.notes.append(f"詳細は {fetched}/{len(cands)} 件のみ取得。{skipped} 件を上限のため読めていない")
        return self.finish()
