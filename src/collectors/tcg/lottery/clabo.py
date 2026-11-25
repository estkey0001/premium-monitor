# -*- coding: utf-8 -*-
"""CardLaboLotteryAdapter — カードラボ（c-labo.jp）の店舗ブログから、ポケカ・ONE PIECE の抽選販売の告知を取得する。

Market Research Coverage Wave 1。店舗ごとのブログ（/shop/<店>/blog/<ID>/）に、抽選・抽選予約の告知が静的 HTML で載り、
応募期間・当選発表・購入期間・商品名・価格が本文のテキストにある（robots.txt は対象ページを禁止していない（確認日 2026-10-24）。
利用規約の本文は未読で、許可も禁止も未確認。調査: 合成した例では 15 件のカードから抽選の告知を選ぶ）。

- 一覧: /blog/filter/tcg:25/（ポケカ）・/blog/filter/tcg:184/（ONE PIECE）。1枚のカード = 1件の告知（件名・店・公開日）
- 応募は店舗の X（旧 Twitter）のフォロー＆リポスト。公式ドメインの応募ページは無いので entry_url は空（応募ページの
  リンクを作らない・推測しない）
- 店舗ごとの抽選（store_specific）として作る。日程が本文に無い告知は、日程を推測せず要確認として残す（base の既定）
- 取得は LotteryAdapter（polite 経由: robots・同じドメインの間隔・正直な User-Agent）。ログイン・検索結果は使わない

販売価格（既存の取得 HTML から同時に読む。取得は増やさない）:
- 対象商品欄の「発売日：… → 商品名【型番】 → お一人様 1BOX：5,760円（税込）」から、商品名・型番・単位・価格を読む（parse_targets）。
  価格を使えるのは「単位 BOX かつ 1 個」だけ。「20pack」などの組・2 個以上の合計・パック・枚は価格なし（単位は PACK / SET / BOX のまま保持）
- 「抽選期間」欄の「販売期間：」「当選者店頭販売期間：」は、当選者の購入期間として読む（normalize_body）

規約確認の状況・BLOCKED 理由（2026-11-25）:
- カードラボ: robots.txt は対象ページを禁止していない（確認日 2026-10-24）。利用規約の本文は未読で、許可も禁止も未確認。
  自動取得は既存の polite 経由の取得 HTML の解析のみで、取得を増やしていない。
  「要規約確認」の扱いを機械的に強制する仕組みはまだ無い（規約本文を読んだら、この記述と取得可否を見直す）
- 三洋堂: 規約本文が未読のため collector は作らない（手動台帳 config/tcg_retailer_box_prices.yaml のまま）。BLOCKED 理由 = 規約未確認
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from src.tcg.models import JST

from .base import REJECT_NOT_CANDIDATE, LotteryAdapter, product_code_of

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
# 実ページの対象商品欄（2026-11 の池袋・難波）: 「〈対象商品〉 発売日：2026年10月31日(土) <商品名【型番】> お一人様 1BOX：5,760円(税込)」。
# 発売日の行が間に入る。金額はカンマあり・なし（5760円）の両方がある。数量と単位（1BOX / 20pack）を分けて読む。
_TARGET_C = re.compile(
    r"対象商品[〉】」』]?\s+(?:発売日[：:]\s*[\d年月日/.\-]+\s*(?:[(（][^)）]{1,4}[)）])?\s+)?"
    r"((?:(?!対象商品).)+?)\s+お一人様\s*(\d+)\s*([A-Za-zァ-ヶー]{1,6}|セット|組|枚)?\s*[：:]\s*(\d[\d,]{2,})\s*円")
_TARGET_B = re.compile(r"商品名[：:]\s*(.+?)\s*(?=※|発売日|お一人様|抽選期間|応募期間|当選|販売価格|価格[：:]|$)")
_NAME_BAD = re.compile(r"[※。]|[：:]\s|お一人様|抽選|応募|当選|注意|発売日|対象商品|期間")
# BOX 価格の下限。ポケカ・ONE PIECE の BOX の定価は 4,000 円台以上。1,000 円未満は 1 パックの価格・桁落ち・誤読の疑いが強いので採用しない
MIN_BOX_PRICE_JPY = 1000
_PACK_RE = re.compile(r"pack|パック|枚", re.I)


def _unit_of(word: str) -> str:
    """単位の語 → PACK / BOX / SET / UNKNOWN。"""
    w = (word or "").strip().lower()
    if w in ("box", "ボックス"):
        return "BOX"
    if w in ("pack", "パック", "枚"):
        return "PACK"
    if w in ("set", "セット", "組"):
        return "SET"
    return "UNKNOWN"


def _target(**kw) -> dict:
    """対象商品の辞書。値が無い項目（None）・既定の単位（UNKNOWN）は入れない（従来の {product_name, retail_price} の形を保つ）。"""
    d = {k: v for k, v in kw.items() if v is not None and v != "UNKNOWN"}
    d.setdefault("retail_price", None)
    return d


def _clean_name(name: str) -> str:
    """商品名として読めるときだけ返す（説明文・日付・条件が混ざった長い文字列は使わない。空なら件名から補う）。"""
    n = re.sub(r"\s+", " ", name or "").strip(" 　・")
    return n if 4 <= len(n) <= 80 and not _NAME_BAD.search(n) else ""


# 販売期間の見出し（fail-closed）。「購入期間」に読み替えてよいのは、当選者向けと明確な見出しの完全一致だけ
# （「販売期間」「当選者(の方)(の)(店頭)販売期間」）。行頭または改行・句点の直後の見出しだけを見る。
# 前置きのあるもの（落選者・未当選・外れ・余剰・当選者以外・通常・予約・一般・商品・店頭のみ …）は、一覧に無いので書き換えない。
_PERIOD_LABEL = re.compile(r"(?:(?<=\n)|^|(?<=。))(?P<lead>[ \t\u3000]*)(?P<label>[^\n：:。]{0,40}?販売期間)(?P<colon>\s*[：:])", re.M)
_WINNER_LABEL = re.compile(r"販売期間|当選者(?:の方)?の?(?:店頭)?販売期間")


_QUALIFIER = re.compile(r"先着|通常|一般|予約")


_ENTRY_LINE = re.compile(r"[ \t\u3000]*(?:応募期間|当選発表)")


def _after_lottery_heading(text: str, start: int) -> bool:
    """この見出しが、同じ記事の「抽選期間」の見出しの直後（応募期間・当選発表の行だけを挟んだ次の行）にあるか。行の途中（「。」の後など）は False。"""
    line_start = text.rfind("\n", 0, start) + 1
    if text[line_start:start].strip():
        return False
    lines = text[:line_start].split("\n")[:-1]
    for ln in reversed(lines):
        if "抽選期間" in ln:
            return True
        if not _ENTRY_LINE.match(ln):
            return False
    return False


def _relabel(m: "re.Match") -> str:
    label = m.group("label").strip()
    if not _WINNER_LABEL.fullmatch(label):
        return m.group(0)
    if label == "販売期間":
        # 見出しが「販売期間」だけのときは、当選者向けと言える根拠が要る（fail-closed）。根拠は構造だけ:
        # 同じ記事の「抽選期間」の見出しの直後（応募期間・当選発表の行だけを挟んだ次の行）にある販売期間だけを購入期間にする（抽選ページの当選者向けの欄）。
        # それ以外（当選の語が近くにあるだけ・抽選期間の見出しから離れた位置・行の途中）は書き換えない。
        # さらに、同じ行・次の行に先着・通常・一般・予約があれば一般向けの販売期間なので書き換えない。
        text = m.string
        line_end = text.find("\n", m.end())
        rest = text[m.end(): line_end if line_end >= 0 else len(text)]
        if _QUALIFIER.search(rest):
            return m.group(0)
        if not _after_lottery_heading(text, m.start()):
            return m.group(0)
        if line_end >= 0:
            nxt_end = text.find("\n", line_end + 1)
            nxt = text[line_end + 1: nxt_end if nxt_end >= 0 else len(text)]
            if _QUALIFIER.search(nxt):
                return m.group(0)
    return f'{m.group("lead")}購入期間{m.group("colon")}'


def normalize_body(body: str) -> str:
    """抽選期間の欄の「販売期間：」「当選者店頭販売期間：」を、共通の解析器が読む「購入期間：」にそろえる（当選者の購入期間）。

    「抽選期間」の見出しがある告知だけ。見出しが当選者向けと明確なもの（完全一致）だけを書き換える fail-closed。
    落選者・外れ・余剰・当選者以外・通常・予約・一般・商品・店頭のみ等の前置きがある販売期間は購入期間にしない。日付・時刻は書き換えない。
    """
    if not body or "抽選期間" not in body:
        return body or ""
    return _PERIOD_LABEL.sub(_relabel, body)


def parse_targets(body: str) -> list[dict]:
    """本文の対象商品（商品名・価格）。決まった書き方で、商品名として読めるものだけ（読めなければ空 = 件名から補う。推測しない）。

    「お一人様 20pack：7,200円」の価格は、パックの組（20パック）の合計なので、定価として使わない（retail_price=None。
    パックの価格から BOX の価格を作らない・BOX の価格から1パックの価格も作らない）。
    """
    t = re.sub(r"\s+", " ", body or "")
    out = []
    # C（発売日の行を挟む実ページの書き方）→ A（従来）→ B（商品名のみ）の順。先に商品名が読めたものを使う
    for m in _TARGET_C.finditer(t):
        name = _clean_name(m.group(1))
        if not name:
            continue
        qty, unit = int(m.group(2)), _unit_of(m.group(3) or "")
        amount = int(m.group(4).replace(",", ""))
        # 価格を使えるのは「お一人様 1BOX」（単位 BOX かつ 1 個）だけ。パック・組・2 個以上の合計は定価にしない
        usable = unit == "BOX" and qty == 1 and amount >= MIN_BOX_PRICE_JPY
        out.append(_target(product_name=name, retail_price=amount if usable else None, price_unit=unit, product_code=product_code_of(name),
                           price_text=f"お一人様 {qty}{m.group(3) or ''}：{amount:,}円" if usable else None))
    if not out:
        for m in _TARGET_A.finditer(t):
            name = _clean_name(m.group(1))
            if not name:
                continue
            word = m.group(2) or ""
            qty = re.match(r"\s*(\d+)", word)
            # パックの組・2個以上の合計は定価にしない（単価が明示されたときだけ採用）
            price = None if _PACK_RE.search(word) or (qty and int(qty.group(1)) >= 2) else int(m.group(3).replace(",", ""))
            if price is not None and _unit_of(re.sub(r"[\d\s]", "", word)) == "BOX" and price < MIN_BOX_PRICE_JPY:
                price = None
            unit = _unit_of(re.sub(r"[\d\s]", "", word))      # 単位の語が無い・読めなければ UNKNOWN（価格があっても利益には使わない）
            out.append(_target(product_name=name, retail_price=price, price_unit=unit, product_code=product_code_of(name)))
    if not out:
        for m in _TARGET_B.finditer(t):
            name = _clean_name(m.group(1))
            if name:
                out.append(_target(product_name=name, retail_price=None, product_code=product_code_of(name)))
    seen, uniq = set(), []
    for x in out:
        if x["product_name"] not in seen:
            seen.add(x["product_name"])
            uniq.append(x)
    return uniq


_TITLE_RANGE = re.compile(r"(\d{1,2})/(\d{1,2})\s*[~〜～\-－]\s*(?:(\d{1,2})/)?(\d{1,2})")


def _title_deadline_soon(title: str, today: str, days: int = 2) -> bool:
    """件名の応募期間の終わりが、今日から days 日以内（終了前）なら True。読めなければ False。"""
    m = _TITLE_RANGE.search(title or "")
    if not m or _title_ended(title, today):
        return False
    try:
        y, today_m = int(today[:4]), int(today[5:7])
        start_m, end_m = int(m.group(1)), int(m.group(3) or m.group(1))
        end_y = y + 1 if (end_m < start_m and today_m >= start_m) else y
        end = datetime(end_y, end_m, int(m.group(4)), tzinfo=JST)
        t0 = datetime(y, today_m, int(today[8:10]), tzinfo=JST)
    except ValueError:
        return False
    return (end - t0).days <= days


def _title_ended(title: str, today: str) -> bool:
    """件名の「(抽選応募期間:10/22~10/25)」の終わりが今日より前なら True。読めないときは False（応募中かもしれないので後ろにしない）。

    年をまたぐ期間（12/28~1/3）は、今日が開始月以降なら終わりを翌年と読む（12 月に「終了済み」と誤判定しない）。
    """
    m = _TITLE_RANGE.search(title or "")
    if not m:
        return False
    try:
        y, today_m = int(today[:4]), int(today[5:7])
        start_m, end_m = int(m.group(1)), int(m.group(3) or m.group(1))
        if end_m < start_m and end_m < today_m < start_m:
            return False                                       # 年またぎの期間がこれから始まる（11 月に見る 12/28~1/3）。終了していない
        end_y = y + 1 if (end_m < start_m and today_m >= start_m) else y
        end = datetime(end_y, end_m, int(m.group(4)), tzinfo=JST).strftime("%Y-%m-%d")
    except ValueError:
        return False
    return end < today


def _fetch_priority(card: dict, today: str) -> tuple:
    """詳細を取る優先順（大きいほど先）: 応募中（終了していない）> 期限が近い > 新しい告知（公開日）> 日ごとに変わる順（毎日同じ店だけが先にならない）。"""
    return (not _title_ended(card["title"], today), _title_deadline_soon(card["title"], today),
            str(card.get("published_at") or "")[:10], hashlib.sha1(f"{today}|{card['url']}".encode()).hexdigest())


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
    max_detail_fetch = 24
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
            if not cards and "claboCard" not in html:
                # 取得はできたが、記事のカードが1件も無い（HTML の構造が変わった可能性）。静かに「0件」にしない（どの一覧でも検知する）
                self.health["errors"] += 1
                self.funnel.errors += 1
                self.funnel.structure_changed_pages += 1
                self.health["error_messages"].append(f"一覧（{tcg}）は取得できたが記事のカードを読めなかった（HTML の構造の変更の可能性）")
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
        # 件名の応募期間が終わっている告知は後ろへ（応募中の告知を先に読む）
        # 優先: 応募中（終了していない）> 期限が近い > 新しい告知（公開日）。同点は日ごとに順序を変える
        cands.sort(key=lambda tc: _fetch_priority(tc[1], today), reverse=True)
        # 取りこぼしの数（黙って切り捨てない）: 応募中らしい告知で、上限のため読めなかったものだけを skipped_due_to_limit に数える
        # （件名で応募が終わっている告知は、上限に余裕があるときだけ読む。読まなかった分は skipped_ended）
        n_open = sum(1 for tc in cands if not _title_ended(tc[1]["title"], today))
        fetched = 0
        for tcg, card in cands[:self.max_detail_fetch]:
            if self._stop_if_blocked():
                break
            fetched += 1
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
            body = normalize_body(self.to_text(m.group(0)) if m else "")
            if not m:
                self.funnel.structure_changed_pages += 1         # 詳細に本文の領域が無い（HTML の構造の変更の疑い）。日程は読まない
                self.health["error_messages"].append("詳細ページに本文の領域（article）が無かった（HTML の構造の変更の可能性）")
            store_name = store if store.startswith("カードラボ") else f"カードラボ{store}"
            self.lottery_events.extend(self.build_from_article(
                title=card["title"], body=body, url=card["url"], published_at=card["published_at"],
                entry_url=None, result_url=None, tcg_hint=tcg, store_name=store_name,
                store_id=card["shop_slug"] or None, targets=parse_targets(body) or None))
        skipped_open = max(0, n_open - self.max_detail_fetch)
        self.health.update({"detail_candidates": len(cands), "detail_fetched": fetched, "skipped_due_to_limit": skipped_open,
                            "skipped_ended": max(0, (len(cands) - n_open) - max(0, self.max_detail_fetch - n_open))})
        if skipped_open > 0:
            self.health["truncated"] = True          # 応募中らしい告知を全部は読めていない（取得元の穴として数える）
            self.funnel.notes.append(
                f"詳細は {fetched}/{len(cands)} 件のみ取得。応募中らしい告知 {skipped_open} 件を上限のため読めていない（同一ドメイン60秒間隔）")
        return self.finish()
