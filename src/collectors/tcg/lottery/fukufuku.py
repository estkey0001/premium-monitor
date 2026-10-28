# -*- coding: utf-8 -*-
"""FukufukuLotteryAdapter — 福福トレカ（pokemon.fukufukutoreka.com）の抽選販売の一覧・詳細から、ポケカの抽選の告知を取得する。

Coverage Wave 3（小規模な通販店。条件つきの取得元）。静的 HTML の一覧（/lottery）に受付中・終了済みの抽選が並び、詳細（/lottery/<連番>）に
応募期間・抽選日・購入期限が文字である（2026-10-29 の調査: robots.txt は /*.csv$・/cart・/shopping・/mypage だけを禁止で /lottery は許可。
自動取得を禁じる規約の記述は見つからなかった。許可の明記でもないので、取得日つきの記録で、変更があれば再確認する）。

- 応募は会員ログインが必要（会員登録・購入履歴 1 回以上）。応募そのものは取らない。公式ドメインの応募ページは作らない（entry_url は空）
- 詳細の「応募期間 10.23 — 10.29 23:59」は年が省略される。**同じ一覧の「応募締切 2026.10.29」の年**で補う（開始の月が終了より大きければ前の年）。
  読めない日付は日程にしない。本文に無い値は作らない
- 取得は LotteryAdapter（polite 経由）。遮断されたら、その実行ではこれ以上取得しない
"""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter

BASE_URL = "https://pokemon.fukufukutoreka.com"
LISTING_URL = BASE_URL + "/lottery"
_CARD = re.compile(r'<article class="lp-card[^"]*">(.*?)</article>', re.S)
_LINK = re.compile(r'<h3 class="lp-card__title">\s*<a href="(https://pokemon\.fukufukutoreka\.com/lottery/\d+)">(.*?)</a>', re.S)
_META = re.compile(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", re.S)
_YMD = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})")
_PERIOD = re.compile(r"応募期間\s*(\d{1,2})\.(\d{1,2})\s*[—\-~〜～－]+\s*(\d{1,2})\.(\d{1,2})(?:\s*(\d{1,2}):(\d{2}))?")
_DEADLINE = re.compile(r"購入期限[^0-9]{0,20}(\d{1,2})\.(\d{1,2})(?:\s*(\d{1,2}):(\d{2}))?")


def _text(frag: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", frag or "", flags=re.S)))).strip()


def parse_listing(html: str) -> list[dict]:
    """一覧のカード（詳細の URL・タイトル・応募締切・抽選日・受付中か）。タイトル・応募締切（年つき）の読めないカードは読まない。"""
    out = []
    for m in _CARD.finditer(html or ""):
        blk = m.group(1)
        lk = _LINK.search(blk)
        if not lk:
            continue
        meta = {_text(k): _text(v) for k, v in _META.findall(blk)}
        end = _YMD.search(meta.get("応募締切", ""))
        if not end:
            continue
        draw = _YMD.search(meta.get("抽選日", ""))
        out.append({"url": lk.group(1), "title": _text(lk.group(2)), "end_ymd": tuple(int(x) for x in end.groups()),
                    "draw_ymd": tuple(int(x) for x in draw.groups()) if draw else None,
                    "active": "lp-card--ended" not in m.group(0)[:80] and "受付中" in blk[:600]})
    return out


def _date(y, mo, d):
    try:
        return datetime(int(y), int(mo), int(d), tzinfo=JST)
    except ValueError:
        return None


def schedule_text(card: dict, detail_text: str) -> str:
    """詳細の本文の日程（年が省略）を、一覧の年で補った、共通の解析器が読める書式の1行にする。読めない値は入れない。"""
    ey = card["end_ymd"][0]
    parts = []
    # 日程は「応募期間」の欄の近く（250 文字）だけから読む（サイドバー・他の抽選の購入期限を拾わない）
    full = detail_text or ""
    i = full.find("応募期間")
    detail_text = full[i:i + 250] if i >= 0 else ""
    m = _PERIOD.search(detail_text or "")
    if m:
        sm, sd, em, ed = (int(m.group(i)) for i in range(1, 5))
        sy = ey if sm <= em else ey - 1
        if _date(sy, sm, sd) and _date(ey, em, ed) and (em, ed) == card["end_ymd"][1:]:     # 詳細の終了日が一覧の応募締切と同じときだけ使う
            et = f"{int(m.group(5)):02d}:{m.group(6)}" if m.group(5) else "23:59"
            parts.append(f"応募期間：{sy}年{sm}月{sd}日 ～ {ey}年{em}月{ed}日 {et}")
    if card.get("draw_ymd") and _date(*card["draw_ymd"]):
        y, mo, d = card["draw_ymd"]
        parts.append(f"当選発表：{y}年{mo}月{d}日")
    dm = _DEADLINE.search(detail_text or "")
    if dm and _date(ey if int(dm.group(1)) >= card["end_ymd"][1] else ey + 1, dm.group(1), dm.group(2)):
        y = ey if int(dm.group(1)) >= card["end_ymd"][1] else ey + 1
        parts.append(f"購入期限：{y}年{int(dm.group(1))}月{int(dm.group(2))}日まで")
    return " ".join(parts)


class FukufukuLotteryAdapter(LotteryAdapter):
    source_id = "FUKUFUKU_TOREKA"
    retailer = "FUKUFUKU_TOREKA"
    retailer_name = "福福トレカ"
    source_name = "福福トレカ（ポケカ通販の抽選販売）"
    tcg = "POKEMON"
    channel = "ONLINE"
    max_detail_fetch = 4
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
            if not cards:                               # カードを1件も読めない（枠が残っていても、項目が変わって読めない場合も含む）
                self.health["errors"] += 1
                self.funnel.errors += 1
                self.funnel.structure_changed_pages += 1
                self.health["error_messages"].append("一覧は取得できたがカードを読めなかった（HTML の構造の変更の可能性）")
            for c in cards:
                self.funnel.news_pages_discovered += 1
                if (re.search(r"遊戯王|ワンピース|ONE ?PIECE|デュエル|ヴァイス|ガンダム|ドラゴンボール", c["title"], re.I)
                        or not re.search(r"ポケモン|ポケカ|CELEBRATION|拡張パック|BOX|カード", c["title"], re.I)):
                    self.funnel.reject(REJECT_NOT_CANDIDATE)
                    continue
                cands.append(c)
        self.funnel.product_links_discovered = len(cands)
        cands.sort(key=lambda c: (not c["active"], tuple(-x for x in c["end_ymd"])))         # 受付中を先に、新しい順
        n_open = sum(1 for c in cands if c["active"])
        fetched = 0
        for c in cands[:self.max_detail_fetch]:
            if self._stop_if_blocked():
                break
            fetched += 1
            page = self.fetch_detail(c["url"], referer=LISTING_URL)
            if not page:
                continue
            text = _text(page)
            sched = schedule_text(c, text)
            if not sched:
                self.funnel.structure_changed_pages += 1 if "応募期間" not in text else 0     # 応募期間の欄が無い（構造の変更の疑い）
            body = f"{sched} {text}".strip() if sched else text
            self.lottery_events.extend(self.build_from_article(
                title=f"{c['title']}（抽選販売）", body=body, url=c["url"], published_at=None,     # サイトに公開日が無い（応募締切日を公開日として保存しない）

                entry_url=None, result_url=None, tcg_hint="POKEMON",
                targets=[{"product_name": re.sub(r"\s*抽選販売\s*$", "", c["title"]).strip(), "retail_price": None}]))
        skipped_open = max(0, n_open - self.max_detail_fetch)
        self.health.update({"detail_candidates": len(cands), "detail_fetched": fetched, "skipped_due_to_limit": skipped_open,
                            "skipped_ended": max(0, (len(cands) - n_open) - max(0, self.max_detail_fetch - n_open))})
        if skipped_open:
            self.health["truncated"] = True
            self.funnel.notes.append(f"詳細は {fetched}/{len(cands)} 件のみ取得。受付中の抽選 {skipped_open} 件を上限のため読めていない")
        return self.finish()
