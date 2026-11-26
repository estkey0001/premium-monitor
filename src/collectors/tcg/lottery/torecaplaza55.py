# -*- coding: utf-8 -*-
"""TorecaPlaza55LotteryAdapter — トレカプラザ55（torecaplaza55.com。通販店・大須アメ横店）のトップの「抽選販売一覧」から、ポケカ・ONE PIECE の抽選の締切を取得する。

Coverage Wave 8。トップページ（EUC-JP）の「抽選販売一覧」に、締切（「11.22」「終日締切」）・ゲーム名・題名が静的 HTML で並ぶ。詳細ページは無い
（リンクは javascript:void(0) で、応募先の Google フォームは data-ref に符号化されている。応募先は取得も復号もしない）。
2026-11-26 の調査: robots.txt は User-agent: * に /cart/ だけを禁止で、トップは禁止していない（一部のクローラーは全面禁止だが、この取得器の
User-Agent は名乗りのとおり該当しない）。利用規約のページは見つからず、自動取得を許可も禁止も未確認。許可の明記でもないので、取得日つきの記録で、変更があれば再確認する。

- 応募の開始日は書かれていない（作らない）。**締切だけの抽選**として application_end_date（「終日締切」= その日のうち。時刻は補わない）だけを持つ
- 締切に年が無い。**取得した日の年（前後の年も候補）で補い、取得日の 120 日前～ 90 日後に入る年**がちょうど1つのときだけ使う（締切が取得日より大きく過去なら翌年にしない）。
  各項目の data-ts（サイトのスクリプトが「この時刻以前は非表示」に使う公開の時刻）より前の締切や、公開から半年を超える締切は矛盾として日程にしない
- data-ts が取得時刻より先の項目は、サイトが表示していない（未公開）ので読まない
- ゲーム名がポケモンカードゲーム・ONE PIECE カードゲーム以外（ユニオンアリーナ等）は除外
- 取得はトップ1ページだけ（LotteryAdapter・polite 経由）。遮断（401/403/429・robots 禁止）されたら何も作らない
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from html import unescape
from typing import Optional

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter, product_code_of
from .plant import as_deadline_only

BASE_URL = "https://torecaplaza55.com"
LISTING_URL = BASE_URL + "/"
REJECT_SCHEDULE_MISMATCH = "schedule_parse_mismatch"
REJECT_NOT_YET_PUBLIC = "not_yet_public"
YEAR_WINDOW_DAYS = 183           # 公開の時刻から締切までの上限
PAST_DAYS = 120                  # 取得日より前の締切として認める範囲（一覧には締切を過ぎた項目も残る）
FUTURE_DAYS = 90                 # 取得日より後の締切として認める範囲（遠い先の締切は翌年と決めつけない）

_BLOCK = re.compile(r'id="common-lottery-calendar-template".*?</template>', re.S)
_ITEM = re.compile(r'<li class="calendar-list__item"([^>]*)>(.*?)</li>', re.S)
_TS = re.compile(r'data-ts="(\d{10,14})"')
_SPAN = r'<span class="calendar-list__{name}[^"]*"[^>]*>(.*?)</span>'
_MD = re.compile(r"^\s*(\d{1,2})\s*[./]\s*(\d{1,2})\s*$")
_HM = re.compile(r"(\d{1,2})\s*[:：]\s*(\d{2})")


def _text(frag: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", frag or ""))).strip()


def _span(blk: str, name: str) -> str:
    m = re.search(_SPAN.format(name=name), blk, re.S)
    return _text(m.group(1)) if m else ""


def _tcg_of(game: str) -> Optional[str]:
    if re.search(r"ポケモンカード|ポケカ", game or ""):
        return "POKEMON"
    if re.search(r"ONE ?PIECE|ワンピース", game or "", re.I):
        return "ONE_PIECE"
    return None


def parse_listing(html: str) -> Optional[list[dict]]:
    """「抽選販売一覧」の項目（締切の月日・締切の表記・ゲーム名・題名・公開の時刻）。一覧の枠が無ければ None（構造の変更）。"""
    m = _BLOCK.search(html or "")
    if not m or "抽選販売一覧" not in m.group(0):     # 枠が無い・見出しが読めない（文字コードの取り違えを含む）
        return None
    out = []
    for attrs, blk in _ITEM.findall(m.group(0)):
        ts = _TS.search(attrs)
        published = None
        if ts:
            v = int(ts.group(1))
            published = datetime.fromtimestamp(v / 1000 if v > 10**11 else v, JST)
        out.append({"day": _span(blk, "day"), "deadline_label": _span(blk, "weekday"), "game": _span(blk, "title"),
                    "title": _span(blk, "product"), "published": published})
    return out


def resolve_deadline(day: str, label: str, fetched: datetime, published: Optional[datetime]) -> Optional[tuple]:
    """「11.22」「終日締切」を (年, 月, 日, 時?, 分?) にする。年は取得日の年・前後の年のうち、取得日の 120 日前～ 90 日後に入るものが
    ちょうど1つのときだけ（締切が取得日より大きく過去でも翌年にしない）。公開の時刻より前・公開から半年を超える締切は矛盾として None。
    「締切」の語が無ければ None。"""
    md = _MD.match(day or "")
    if not md or "締切" not in (label or ""):
        return None
    mo, d = int(md.group(1)), int(md.group(2))
    hits = []
    for y in (fetched.year - 1, fetched.year, fetched.year + 1):
        try:
            dt = datetime(y, mo, d, tzinfo=JST)
        except ValueError:
            continue
        if -PAST_DAYS <= (dt.date() - fetched.date()).days <= FUTURE_DAYS:
            hits.append(dt)
    if len(hits) != 1:
        return None
    dt = hits[0]
    if published is not None and not (0 <= (dt.date() - published.date()).days <= YEAR_WINDOW_DAYS):
        return None
    hm = _HM.search(label or "")
    if "終日" not in label and hm and 0 <= int(hm.group(1)) <= 23 and 0 <= int(hm.group(2)) <= 59:
        return (dt.year, dt.month, dt.day, int(hm.group(1)), int(hm.group(2)))
    return (dt.year, dt.month, dt.day, None, None)


def product_of(title: str) -> str:
    """題名から末尾の「抽選販売」を除いた残り（2次・再入荷などの語は残す）。読めなければ空。"""
    t = re.sub(r"\s*抽選販売\s*$", "", title or "").strip()
    return t if 2 <= len(t) <= 80 else ""


class TorecaPlaza55LotteryAdapter(LotteryAdapter):
    source_id = "TORECAPLAZA55"
    retailer = "TORECAPLAZA55"
    retailer_name = "トレカプラザ55"
    source_name = "トレカプラザ55（トップの抽選販売一覧）"
    tcg = "POKEMON"
    channel = "ONLINE"
    max_detail_fetch = 0                                # 詳細ページは無い（トップ1ページだけ）
    lottery_source_type = "RETAILER_OFFICIAL"

    def collect(self, now: Optional[datetime] = None) -> list[dict]:
        from src.tcg.models import now_jst, parse_dt
        from .plant import deadline_line
        self.health["last_checked"] = now_jst().isoformat()
        html = self.fetch_listing(LISTING_URL)
        items: Optional[list[dict]] = None
        if html:
            self.health["last_success"] = now_jst().isoformat()
            items = parse_listing(html)
            if items is None:
                self.health["errors"] += 1
                self.funnel.errors += 1
                self.funnel.structure_changed_pages += 1
                self.health["error_messages"].append("トップは取得できたが「抽選販売一覧」の枠を読めなかった（HTML の構造・文字コードの変更の可能性）")
        fetched = now or parse_dt(self._fetched_at) or now_jst()
        cands = []
        for it in items or []:
            self.funnel.news_pages_discovered += 1
            tcg = _tcg_of(it["game"])
            if not tcg or not it["title"]:
                self.funnel.reject(REJECT_NOT_CANDIDATE)                     # ユニオンアリーナ等
                continue
            if it["published"] is not None and it["published"] > fetched:
                self.funnel.reject(REJECT_NOT_YET_PUBLIC)                    # サイトが表示していない（公開前）
                continue
            cands.append({**it, "tcg": tcg})
        self.funnel.product_links_discovered = len(cands)
        for c in cands:
            deadline = resolve_deadline(c["day"], c["deadline_label"], fetched, c["published"])
            if deadline is None:
                self.funnel.notes.append(f"締切の年・日付を決められなかった（日程は作らない）: {c['game']} {c['title']} {c['day']}")
            line, end_key, end_val = deadline_line(deadline) if deadline else ("", "", "")
            prod = product_of(c["title"])
            title = f"{c['game']} {c['title']}"
            # 締切の行は後ろに置く（題名の日付（「11月27日発売商品」など）を共通の解析器が終了として読まないように）
            body = f"抽選販売一覧：{c['game']} {c['title']} {c['day']} {c['deadline_label']} {line}".strip()
            evs = self.build_from_article(
                title=title, body=body, url=LISTING_URL,
                published_at=c["published"].isoformat() if c["published"] else None,
                entry_url=None, result_url=None, tcg_hint=c["tcg"],
                targets=[{"product_name": prod, "retail_price": None, "product_code": product_code_of(prod)}] if prod else None)
            if line:
                ok = [e for e in (as_deadline_only(e, end_key, end_val) for e in evs) if e]
                if len(ok) < len(evs):
                    self.reject(REJECT_SCHEDULE_MISMATCH)
                    self.funnel.accepted_sales_events -= len(evs) - len(ok)
                    if self.funnel.pages:
                        self.funnel.pages[-1].accepted -= len(evs) - len(ok)
                evs = ok
            self.lottery_events.extend(evs)
        self.health.update({"detail_candidates": 0, "detail_fetched": 0, "skipped_due_to_limit": 0, "skipped_ended": 0})
        return self.finish()
