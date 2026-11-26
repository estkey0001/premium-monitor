# -*- coding: utf-8 -*-
"""PlantLotteryAdapter — スーパーセンター PLANT（www.plant-co.jp）のお知らせ・キャンペーンから、ポケカ・ONE PIECE の抽選販売の告知を取得する。

Coverage Wave 8。お知らせの一覧（/campaign.html）に、詳細（/campaign/detail/<番号>.html）へのリンクが公開日（「2026年11月12日公開」）と件名つきで並ぶ。
詳細に「公開日：」「【応募期間】… まで」「応募締切：M月D日（曜）HH：MM まで」「購入期間：」がテキストで載る（2026-11-26 の調査: robots.txt は
/app/・/app2/・/app3/・/app4/・/signage/ だけを禁止で、対象ページは禁止していない。サイトの利用規約に自動取得を禁じる条項は見当たらず、
転載・商標の無断使用は禁じている（本文は保存・転載せず、期間・商品名・出典の URL だけを残す）。許可の明記でもないので、取得日つきの記録で、変更があれば再確認する）。

- 候補: 件名にポケモンカード／ONE PIECE カード（ワンピースカード）と「抽選」を含むものだけ（灯油・食品などのキャンペーンは読まない）
- 応募の開始日は書かれていない。**締切だけの抽選**として、application_end（時刻があれば）か application_end_date だけを持つ（開始日を作らない）
- 年の無い日付は詳細の公開日（無ければ一覧の公開日）の年で補う。締切は公開日以後・半年以内で、曜日が書かれていれば一致するものだけ。
  「応募締切」と「【応募期間】… まで」の日付が食い違えば日程にしない（推測で選ばない）
- 対象商品は詳細の商品枠（archive-tt1）の名前。価格（パックの本体価格など）は定価にしない
- 応募は外部のフォーム（公式ドメインではない）なので entry_url は作らない。対象は複数店舗の1本の告知（店舗ごとの抽選にしない）
- 取得は LotteryAdapter（polite 経由）。遮断（401/403/429・robots 禁止）されたら、その実行ではこれ以上取得しない
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from typing import Optional

from src.tcg.lottery.schema import lottery_id_of
from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter, product_code_of

BASE_URL = "https://www.plant-co.jp"
LISTING_URL = BASE_URL + "/campaign.html"
REJECT_SCHEDULE_MISMATCH = "schedule_parse_mismatch"
REJECT_RESULT_ONLY = "result_announcement_only"
_WEEKDAYS = "月火水木金土日"

_ITEM = re.compile(r'<a class="click-element click-campaign"\s*href="(https://www\.plant-co\.jp/campaign/detail/(\d+)\.html[^"]*)"[^>]*>(.*?)</a>', re.S)
_DAY = re.compile(r'<p class="day">\s*(\d{4})年(\d{1,2})月(\d{1,2})日公開\s*</p>')
_TITLE = re.compile(r'<p class="title">(.*?)</p>', re.S)
_DETAIL_TITLE = re.compile(r'<h3 class="blogmaintitle">(.*?)</h3>', re.S)
_PUBLISHED = re.compile(r'class="blogdate">\s*公開日\s*[:：]\s*(\d{4})年(\d{1,2})月(\d{1,2})日')
_PRODUCT = re.compile(r'<h3 class="archive-tt1"[^>]*>(.*?)</h3>', re.S)
_MD = r"(?:(\d{4})年\s*)?(\d{1,2})月\s*(\d{1,2})日\s*(?:[（(]\s*([月火水木金土日])(?:・祝)?\s*[）)])?"
_DEADLINE = re.compile(r"応募締切\s*[:：]?\s*" + _MD + r"\s*(?:(\d{1,2})\s*[:：]\s*(\d{2}))?")
_PERIOD_UNTIL = re.compile(r"【応募期間】\s*" + _MD + r"\s*(?:(\d{1,2})\s*[:：]\s*(\d{2}))?\s*まで")
_PERIOD_RANGE = re.compile(r"【応募期間】\s*" + _MD + r"[^【]{0,30}?[～〜~]")
_TCG_TITLE = re.compile(r"ポケモンカード|ポケカ|ONE ?PIECE ?カード|ワンピースカード", re.I)
_RESULT_TITLE = re.compile(r"当選者?発表|抽選結果|結果発表")


def _text(frag: str) -> str:
    frag = re.sub(r"<!--.*?-->", " ", frag or "", flags=re.S)                # コメントアウトされた古い文言は読まない
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", frag, flags=re.S)))).strip()


def _tcg_of(text: str) -> Optional[str]:
    if re.search(r"ポケモンカード|ポケカ", text or ""):
        return "POKEMON"
    if re.search(r"ONE ?PIECE|ワンピース", text or "", re.I):
        return "ONE_PIECE"
    return None


def parse_listing(html: str) -> list[dict]:
    """一覧の項目（詳細の URL・番号・件名・公開日）。件名・公開日の読めない項目は読まない。"""
    out, seen = [], set()
    for m in _ITEM.finditer(html or ""):
        url, no, blk = m.groups()
        t, d = _TITLE.search(blk), _DAY.search(blk)
        title = _text(t.group(1)) if t else ""
        if no in seen or not title or not d:
            continue
        try:
            published = datetime(*(int(x) for x in d.groups()), tzinfo=JST).isoformat()
        except ValueError:
            continue
        seen.add(no)
        out.append({"url": unescape(url), "no": int(no), "title": title, "published_at": published})
    return out


def parse_detail(html: str) -> dict:
    """詳細: 件名・公開日・本文（customcate の中のテキスト。コメントは除く）・商品枠の名前。本文の領域が無ければ本文は空。"""
    h = html or ""
    t, p = _DETAIL_TITLE.search(h), _PUBLISHED.search(h)
    i = h.find('class="customcate')
    j = h.find("<!-- .inner -->", i) if i >= 0 else -1
    i = h.find(">", i) + 1 if i >= 0 else -1                                  # customcate の開始タグの後から
    region = h[i:j] if i >= 0 and j > i else (h[i:] if i >= 0 else "")
    published = None
    if p:
        try:
            published = datetime(*(int(x) for x in p.groups()), tzinfo=JST).isoformat()
        except ValueError:
            published = None
    # 商品名は入れ子の span で切られている（「拡張<span>パック</span>」）。タグは空白にせず取り除く
    names = [re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", x))).strip() for x in _PRODUCT.findall(region)]
    return {"title": _text(t.group(1)) if t else "", "published_at": published, "body": _text(region),
            "products": [n for n in names if 4 <= len(n) <= 90]}


def resolve_deadline(groups: tuple, base: Optional[datetime]) -> Optional[tuple]:
    """(年?, 月, 日, 曜日?, 時?, 分?) の締切を (年, 月, 日, 時?, 分?) にする。年が無ければ base の年か翌年で、
    base 以後・半年以内、曜日が書かれていれば一致するものだけ。決まらなければ None（日付を作らない）。"""
    y, mo, d, w, h, mi = groups
    if base is None and not y:
        return None
    hit = []
    for cand in ([int(y)] if y else [base.year, base.year + 1]):
        try:
            dt = datetime(cand, int(mo), int(d), tzinfo=JST)
        except ValueError:
            continue
        if w and _WEEKDAYS[dt.weekday()] != w:
            continue
        if base is not None and not (0 <= (dt.date() - base.date()).days <= 183):
            continue
        hit.append(dt)
    if len(hit) != 1:
        return None
    if h is not None and mi is not None and not (0 <= int(h) <= 23 and 0 <= int(mi) <= 59):
        return None
    dt = hit[0]
    return (dt.year, dt.month, dt.day, int(h) if h is not None else None, int(mi) if mi is not None else None)


def deadline_line(p: tuple) -> tuple[str, str, str]:
    """締切を、共通の解析器が読める「応募期間：YYYY年M月D日[ HH:MM]」の行にする。戻り: (行, 終了のキー, 値)。"""
    y, mo, d, h, mi = p
    if h is not None and mi is not None:
        return (f"応募期間：{y}年{mo}月{d}日 {h:02d}:{mi:02d}", "application_end",
                datetime(y, mo, d, h, mi, tzinfo=JST).isoformat())
    return f"応募期間：{y}年{mo}月{d}日", "application_end_date", f"{y:04d}-{mo:02d}-{d:02d}"


def as_deadline_only(ev: dict, end_key: str, end_val: str) -> Optional[dict]:
    """共通の解析器は「応募期間：<日付1つ>」を開始に入れる。締切だけの告知なので、その値を終了へ移す（開始は空）。
    解析器が別の値を読んでいた（別のラベルを拾った等）ときは None（採用しない）。"""
    start_key = "application_start_date" if end_key.endswith("_date") else "application_start"
    others = [k for k in ("application_start", "application_start_date", "application_end", "application_end_date") if k != start_key]
    if ev.get(start_key) != end_val or any(ev.get(k) for k in others):
        return None
    out = dict(ev)
    out[start_key] = None
    out[end_key] = end_val
    out["lottery_id"] = lottery_id_of(out)
    return out


def deadline_of(body: str, base: Optional[datetime]) -> tuple[Optional[tuple], str]:
    """本文の締切。戻り: (締切, 理由)。「応募締切」と「【応募期間】… まで」が両方あって食い違えば (None, "conflict")。
    【応募期間】が開始～終了の範囲で書かれていれば (None, "range")（共通の解析器に任せる）。"""
    if _PERIOD_RANGE.search(body or ""):
        return None, "range"
    a = _DEADLINE.search(body or "")
    b = _PERIOD_UNTIL.search(body or "")
    da = resolve_deadline(a.groups(), base) if a else None
    db = resolve_deadline(b.groups(), base) if b else None
    if da and db and da[:3] != db[:3]:
        return None, "conflict"
    if a and not da:
        return None, "unreadable"
    d = da or db
    return (d, "ok") if d else (None, "missing")


class PlantLotteryAdapter(LotteryAdapter):
    source_id = "PLANT"
    retailer = "PLANT"
    retailer_name = "スーパーセンター PLANT"
    source_name = "スーパーセンター PLANT（お知らせの抽選販売）"
    tcg = "POKEMON"
    channel = "STORE"
    max_detail_fetch = 3
    lottery_source_type = "RETAILER_OFFICIAL"

    def _stop_if_blocked(self) -> bool:
        if self.health.get("blocked"):
            self.funnel.notes.append("アクセス制限（401/403/429）を受けたので、この実行ではこれ以上取得しない")
            return True
        return False

    def _drop(self, n: int, note: str) -> None:
        self.reject(REJECT_SCHEDULE_MISMATCH)
        self.funnel.accepted_sales_events -= n
        if self.funnel.pages:
            self.funnel.pages[-1].accepted -= n
        self.funnel.notes.append(note)

    def collect(self) -> list[dict]:
        from src.tcg.models import now_jst, parse_dt
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
                self.health["error_messages"].append("一覧は取得できたが項目を読めなかった（HTML の構造の変更の可能性）")
            for c in items:
                self.funnel.news_pages_discovered += 1
                if not (_TCG_TITLE.search(c["title"]) and "抽選" in c["title"]):
                    self.funnel.reject(REJECT_NOT_CANDIDATE)                 # 灯油・食品・ポイントのキャンペーンなど
                    continue
                if _RESULT_TITLE.search(c["title"]):
                    self.funnel.reject(REJECT_RESULT_ONLY)
                    continue
                cands.append(c)
        self.funnel.product_links_discovered = len(cands)
        cands.sort(key=lambda c: (c["published_at"], c["no"]), reverse=True)
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
                self.health["error_messages"].append("詳細ページに本文の領域（customcate）が無かった（HTML の構造の変更の可能性）")
            published = d["published_at"] or c["published_at"]
            title = d["title"] or c["title"]
            tcg = _tcg_of(title)
            deadline, why = deadline_of(d["body"], parse_dt(published))
            if why in ("conflict", "unreadable"):
                self.funnel.notes.append(f"応募締切を決められなかった（{why}。日程は作らない）: {c['url']}")
            line, end_key, end_val = deadline_line(deadline) if deadline else ("", "", "")
            # 「【応募期間】11月19日（木）まで」は締切の1日だけ。共通の解析器は1つ目の日付を開始に入れるので、範囲の書き方でなければ
            # 見出しを読み替えて開始として読ませない（値は変えない。締切は上の行だけから読む）
            body = d["body"] if why == "range" else d["body"].replace("【応募期間】", "【応募期限】")
            targets = [{"product_name": n, "retail_price": None, "product_code": product_code_of(n)} for n in d["products"]] or None
            evs = self.build_from_article(
                # 締切の行は本文の後ろに置く（行の後ろに本文の日付（発売日など）が続くと、共通の解析器が終了として読んでしまうため）
                title=title, body=f"{body} {line}".strip() if line else body, url=c["url"], published_at=published,
                entry_url=None, result_url=None, tcg_hint=tcg, targets=targets)
            if why not in ("ok", "range") and evs:              # 締切を決められない（conflict・unreadable・missing）: 共通の解析器の日付も使わない
                self._drop(len(evs), f"応募締切を決められないので日程を作らない（{why}）: {c['url']}")
                evs = []
            if line:
                fixed = [as_deadline_only(e, end_key, end_val) for e in evs]
                ok = [e for e in fixed if e]
                if len(ok) < len(evs):
                    self._drop(len(evs) - len(ok), f"共通の解析器が締切以外の日付を応募期間に読んだので採用しない: {c['url']}")
                evs = ok
            self.lottery_events.extend(evs)
        skipped = max(0, len(cands) - self.max_detail_fetch)
        self.health.update({"detail_candidates": len(cands), "detail_fetched": fetched, "skipped_due_to_limit": skipped, "skipped_ended": 0})
        if skipped:
            self.health["truncated"] = True
            self.funnel.notes.append(f"詳細は {fetched}/{len(cands)} 件のみ取得。{skipped} 件を上限のため読めていない")
        return self.finish()
