# -*- coding: utf-8 -*-
"""BnamOnePieceShopLotteryAdapter — ONE PIECEカードゲーム 公式ショップ（バンダイナムコ アミューズメント。bandainamco-am.co.jp）の
重要なお知らせから、事前抽選（抽選販売）の告知を取得する。

Coverage Wave 8。公式ショップのトップ（/official_shop/onepiece-cardgame/）の「重要なお知らせ」に、告知の詳細
（news/important/YYYYMMDD.html）へのリンクが掲載日・対象店舗（「全店」等）つきで並ぶ。詳細の表に「申込受付期間」（年つき）と
「抽選販売日」がテキストで載る（2026-11-26 の調査: robots.txt は「User-agent: *」と Sitemap だけで禁止の行が無い。
/news/ の一覧の URL は 404 なのでトップから辿る。サイトポリシーは私的使用を超える複製を禁じる（本文は保存・転載せず、期間・商品名・出典の URL だけを残す）。
自動取得を禁じる条項は見当たらないが、許可の明記でもないので、取得日つきの記録で、変更があれば再確認する）。

- 候補: トップのお知らせ（important / information）のうち、件名に「抽選」を含むもの。当選発表だけの告知は受付にしない
- 「申込受付期間 2026年11月11日(水) 10:00 ～ 15日(日) 23:59」の終了側は年・月が省略される。**開始の年・月で補い**、
  終了の日が開始の日より小さければ翌月とする。曜日が書かれていれば一致を確かめ、合わなければ日程にしない（推測で作らない）
- 「抽選販売日」は当選者が店頭で購入する期間なので、購入期間（日付だけ）として読む
- 応募は会員制の購入権チケットのページ（parks2.bandainamco-am.co.jp）。取得しない。公式ドメインの許可リスト（src/tcg/lottery/manual.py の
  OFFICIAL_DOMAINS）に無いので entry_url は作らない
- 全店共通の1本の告知（対象店舗の欄が「全店」以外の1店だけなら、その店の抽選として扱う）
- 取得は LotteryAdapter（polite 経由）。遮断（401/403/429・robots 禁止）されたら、その実行ではこれ以上取得しない
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from typing import Optional

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter, product_code_of

BASE_URL = "https://bandainamco-am.co.jp"
LISTING_URL = BASE_URL + "/official_shop/onepiece-cardgame/"
STORE_PREFIX = "ONE PIECEカードゲーム公式ショップ "
REJECT_RESULT_ONLY = "result_announcement_only"
REJECT_SCHEDULE_MISMATCH = "schedule_parse_mismatch"

_ITEM = re.compile(
    r'<time datetime="(\d{4})-(\d{2})-(\d{2})">[^<]*</time>\s*</dt>\s*'
    r'<dd class="info_list_label[^"]*">(.*?)</dd>\s*<dd>\s*'
    r'<a href="(/official_shop/onepiece-cardgame/news/(?:important|information)/(\d{8})\.html)"[^>]*>(.*?)</a>', re.S)
_STORE_LABEL = re.compile(r'<li class="store">(.*?)</li>', re.S)
_ARTICLE = re.compile(r"<article.*?</article>", re.S)
_ROW = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_W = r"\s*(?:[（(]\s*([月火水木金土日])(?:・祝)?\s*[）)])?"
_T = r"(?:\s*(\d{1,2})\s*[:：]\s*(\d{2}))?"
_PERIOD = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日" + _W + _T +
                     r"\s*[～〜~\-－]\s*(?:(\d{4})年\s*)?(?:(\d{1,2})月\s*)?(\d{1,2})日" + _W + _T)
_PRODUCT = re.compile(r"[『「](.+?)[』」]")
_RESULT_TITLE = re.compile(r"当選者?発表|抽選結果|結果発表|当選者の?方へ")
_WEEKDAYS = "月火水木金土日"
APPLICATION_LABELS = ("申込受付期間", "応募受付期間", "申込期間", "応募期間", "受付期間")
PURCHASE_LABELS = ("抽選販売日", "販売期間", "購入期間")


def _text(frag: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", frag or "", flags=re.S)))).strip()


def parse_listing(html: str) -> list[dict]:
    """トップのお知らせ（掲載日・対象店舗・詳細の URL・件名）。掲載日・件名の読めない項目は読まない。"""
    out, seen = [], set()
    for m in _ITEM.finditer(html or ""):
        y, mo, d, labels, path, _key, title = m.groups()
        title = _text(title)
        try:
            published = datetime(int(y), int(mo), int(d), tzinfo=JST).isoformat()
        except ValueError:
            continue
        if not title or path in seen:
            continue
        seen.add(path)
        out.append({"url": BASE_URL + path, "title": title, "published_at": published,
                    "stores": [_text(s) for s in _STORE_LABEL.findall(labels) if _text(s)]})
    return out


def parse_detail(html: str) -> dict:
    """詳細: 件名（h1）・本文（<article> の中のテキスト）・表の行（見出し → 値）。<article> が無ければ本文・表は空。"""
    m = _ARTICLE.search(html or "")
    art = m.group(0) if m else ""
    t = _H1.search(art)
    return {"title": _text(t.group(1)) if t else "", "body": _text(art),
            "rows": {_text(k): _text(v) for k, v in _ROW.findall(art)}}


def _dt(y: int, mo: int, d: int, w: Optional[str]) -> Optional[datetime]:
    try:
        dt = datetime(y, mo, d, tzinfo=JST)
    except ValueError:
        return None
    if w and _WEEKDAYS[dt.weekday()] != w:
        return None                                    # 曜日が合わない（誤記・読み違い）。日付を作らない
    return dt


def read_period(value: str) -> Optional[dict]:
    """「YYYY年M月D日(曜) HH:MM ～ [YYYY年][M月]D日(曜) HH:MM」を読む。終了の年・月が省略されていれば開始から補う
    （終了の日が開始の日より小さければ翌月）。曜日が合わない・終了が開始より前なら None。時刻の無い側は日付だけ。"""
    m = _PERIOD.search(value or "")
    if not m:
        return None
    sy, smo, sd, sw, sh, smi, ey, emo, ed, ew, eh, emi = m.groups()
    sy, smo, sd = int(sy), int(smo), int(sd)
    start = _dt(sy, smo, sd, sw)
    if start is None:
        return None
    if emo is None:
        emo_i, ey_i = smo, sy
        if int(ed) < sd:                               # 「30日 ～ 2日」= 翌月
            emo_i, ey_i = (1, sy + 1) if smo == 12 else (smo + 1, sy)
    else:
        emo_i = int(emo)
        ey_i = int(ey) if ey else (sy + 1 if emo_i < smo else sy)
    end = _dt(ey_i, emo_i, int(ed), ew)
    if end is None or end.date() < start.date():
        return None
    return {"start": (start.year, start.month, start.day, sh and int(sh), smi and int(smi)),
            "end": (end.year, end.month, end.day, eh and int(eh), emi and int(emi))}


def _fmt(p: tuple) -> str:
    y, mo, d, h, mi = p
    return f"{y}年{mo}月{d}日" + (f" {h:02d}:{mi:02d}" if h is not None and mi is not None else "")


def _iso(p: tuple) -> tuple[str, str]:
    """(キー接尾辞, 値)。時刻があれば ISO、無ければ日付だけ。"""
    y, mo, d, h, mi = p
    if h is not None and mi is not None:
        return "", datetime(y, mo, d, h, mi, tzinfo=JST).isoformat()
    return "_date", f"{y:04d}-{mo:02d}-{d:02d}"


def schedule_text(rows: dict) -> tuple[str, dict]:
    """表の行から、共通の解析器が読める書式の日程の行と、読んだ値（照合用）を作る。読めない値は入れない。"""
    parts, expect = [], {}
    app = next((read_period(rows[k]) for k in APPLICATION_LABELS if k in rows and read_period(rows[k])), None)
    if app:
        parts.append(f"応募期間：{_fmt(app['start'])} ～ {_fmt(app['end'])}")
        for side, key in (("start", "application_start"), ("end", "application_end")):
            suf, v = _iso(app[side])
            expect[key + suf] = v
    pur = next((read_period(rows[k]) for k in PURCHASE_LABELS if k in rows and read_period(rows[k])), None)
    if pur:
        parts.append(f"購入期間：{_fmt(pur['start'])} ～ {_fmt(pur['end'])}")
    return " ".join(parts), expect


def product_of(title: str) -> str:
    """件名の『…』「…」の中の商品名（最初のもの）。無ければ空。"""
    m = _PRODUCT.search(title or "")
    n = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
    return n if 2 <= len(n) <= 80 else ""


def matches_expected(ev: dict, expect: dict) -> bool:
    """共通の解析器が読んだ応募期間が、この取得器が表から読んだ値と同じか（別のラベルを拾っていないか）。
    表から期間を読めなかったとき（expect が空）は照合できないので採用しない（購入期間などを応募期間として出さない）。"""
    return bool(expect) and all(ev.get(k) == v for k, v in expect.items())


class BnamOnePieceShopLotteryAdapter(LotteryAdapter):
    source_id = "ONEPIECE_CARD_OFFICIAL_SHOP"
    retailer = "ONEPIECE_CARD_OFFICIAL_SHOP"
    retailer_name = "ONE PIECEカードゲーム公式ショップ"
    source_name = "ONE PIECEカードゲーム 公式ショップ（重要なお知らせの事前抽選）"
    tcg = "ONE_PIECE"
    channel = "STORE"
    max_detail_fetch = 3
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
            items = parse_listing(html)
            if not items:
                self.health["errors"] += 1
                self.funnel.errors += 1
                self.funnel.structure_changed_pages += 1
                self.health["error_messages"].append("トップは取得できたがお知らせを読めなかった（HTML の構造の変更の可能性）")
            for c in items:
                self.funnel.news_pages_discovered += 1
                if "抽選" not in c["title"]:
                    self.funnel.reject(REJECT_NOT_CANDIDATE)                 # 販売方法・本人確認・店舗の販売商品の案内など
                    continue
                if _RESULT_TITLE.search(c["title"]):
                    self.funnel.reject(REJECT_RESULT_ONLY)
                    continue
                cands.append(c)
        self.funnel.product_links_discovered = len(cands)
        cands.sort(key=lambda c: (c["published_at"], c["url"]), reverse=True)
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
                self.health["error_messages"].append("詳細ページに本文の領域（article）が無かった（HTML の構造の変更の可能性）")
            sched, expect = schedule_text(d["rows"])
            if d["body"] and not sched:
                self.funnel.notes.append(f"表から申込受付期間を読めなかった（日程は作らない）: {c['url']}")
            title = d["title"] or c["title"]
            prod = product_of(title)
            stores = [s for s in c["stores"] if s != "全店"]
            store = STORE_PREFIX + stores[0] if len(stores) == 1 and "全店" not in c["stores"] else None
            evs = self.build_from_article(
                title=title, body=f"{sched} {d['body']}".strip(), url=c["url"], published_at=c["published_at"],
                entry_url=None, result_url=None, tcg_hint="ONE_PIECE", store_name=store,
                targets=[{"product_name": prod, "retail_price": None, "product_code": product_code_of(prod)}] if prod else None)
            ok = [e for e in evs if matches_expected(e, expect)]
            if len(ok) < len(evs):
                self.reject(REJECT_SCHEDULE_MISMATCH)
                self.funnel.accepted_sales_events -= len(evs) - len(ok)
                if self.funnel.pages:
                    self.funnel.pages[-1].accepted -= len(evs) - len(ok)
                self.funnel.notes.append(f"共通の解析器の応募期間が表の値と食い違ったので採用しない: {c['url']}")
            for e in ok:                        # サイトポリシーが私的使用を超える複製を禁じる。応募条件の原文は公開の出力に残さない（構造化したフラグだけ）
                e["eligibility_text"] = ""
            self.lottery_events.extend(ok)
        skipped = max(0, len(cands) - self.max_detail_fetch)
        self.health.update({"detail_candidates": len(cands), "detail_fetched": fetched, "skipped_due_to_limit": skipped, "skipped_ended": 0})
        if skipped:
            self.health["truncated"] = True
            self.funnel.notes.append(f"詳細は {fetched}/{len(cands)} 件のみ取得。{skipped} 件を上限のため読めていない")
        return self.finish()
