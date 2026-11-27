# -*- coding: utf-8 -*-
"""LotteryAdapter — 小売・メーカーの抽選告知を取得する共通基盤（Task16 / Task17）。

流れ: 一覧ページ → 候補リンク → 詳細ページ → 販売文脈の確認 → 抽選パーサー

誤検出の防止（Task18）:
  - タイトルが大会・イベント・キャンペーン参加等なら棄却
  - 「抽選で○○が当たる」型のプレゼント抽選は棄却
  - 「抽選」という語だけでは採用しない（抽選販売 / 購入権 / 抽選受付 等が必要）
取りこぼしの防止（Task19）:
  - 「抽選で当選された方のみ購入可能」「購入権抽選」「事前抽選」「抽選受付」は採用
  - キャンペーン語が本文にあっても、商品 + 抽選販売の文脈があれば評価する
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from src.collectors.tcg.base import BaseTcgCollector
from src.tcg.funnel import (
    PAGE_LISTING, PAGE_NEWS, REJECT_NON_SALE,
)
from src.tcg.lottery.manual import is_official_url
from src.tcg.lottery.parse import (
    detect_application_methods, detect_cancellation, extract_eligibility, extract_schedule, extract_target_products,
    product_name_from_title,
)
from src.tcg.lottery.schema import (
    LT_LOTTERY, LT_PURCHASE_RIGHT, LotteryEvent, confidence_for_source,
)
from src.tcg.models import TCG_ONE_PIECE, TCG_POKEMON, now_jst
from src.tcg.sales_context import _GIVEAWAY_RE, is_non_sale_announcement
from src.tcg.shrink import detect_shrink_status

# 棄却理由
REJECT_TOURNAMENT = "tournament_or_event"
REJECT_GIVEAWAY = "giveaway_lottery"
REJECT_NO_LOTTERY_SALE = "no_lottery_sale_context"
REJECT_NO_CARD_PRODUCT = "no_card_product"
REJECT_SCHEDULE_NOT_IN_TEXT = "schedule_not_in_text"
REJECT_NOT_CANDIDATE = "not_lottery_candidate"

# 抽選販売であることを示す語（「抽選」単独は不可）
LOTTERY_SALE_PHRASES = ("抽選販売", "購入権", "抽選受付", "抽選受け付け", "事前抽選",
                        "抽選応募", "抽選で当選された方", "抽選で当選した方", "抽選での販売")
# タイトルだけで抽選販売と判断してよい語（本文を読めない告知用）
ANNOUNCEMENT_SALE_PHRASES = ("抽選販売", "抽選受付", "抽選受け付け", "購入権", "事前抽選",
                             "抽選応募", "商品の抽選", "抽選による販売", "抽選での販売")
# 大会・参加型イベント（タイトルにあれば棄却）
TOURNAMENT_TERMS = ("大会", "トーナメント", "チャンピオンズリーグ", "シティリーグ",
                    "ジムバトル", "体験会", "参加者募集", "プレイヤー募集", "来場者",
                    "イベント参加", "エントリーキャンペーン")
_CARD_WORDS = {
    TCG_POKEMON: ("ポケモンカード", "ポケカ"),
    TCG_ONE_PIECE: ("ONE PIECEカード", "ワンピースカード", "ONE PIECE カード"),
}
_A_RE = re.compile(r'<a\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.S | re.I)


def detect_tcg(text: str) -> Optional[str]:
    """文字列がどの TCG の商品か。両方 / どちらでもなければ None。"""
    hits = [tcg for tcg, words in _CARD_WORDS.items() if any(w in (text or "") for w in words)]
    return hits[0] if len(hits) == 1 else None


def anchors(html: str, base_url: str) -> list[tuple[str, str]]:
    """(絶対 URL, アンカーテキスト) の一覧。"""
    out: list[tuple[str, str]] = []
    for href, body in _A_RE.findall(html or ""):
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)).strip()
        out.append((urljoin(base_url, href.strip()), text))
    return out



def product_code_of(name: str) -> Optional[str]:
    """商品名の【】内の型番（【EB-05】→ EB-05）。ちょうど 1 つに定まるときだけ返す（本文中の英数字は型番にしない）。"""
    from src.tcg.lottery.products import _codes
    codes = _codes(name or "")
    return next(iter(codes)) if len(codes) == 1 else None


_URL_IN_TEXT = re.compile(r"https://[A-Za-z0-9.\-]+/[A-Za-z0-9_\-./]*")


def external_form_in(body: str, retailer: str, product_name: str = "", names=()) -> Optional[str]:
    """公式の告知の本文に載った外部フォームの URL（action_url.EXTERNAL_FORM_RULES でその取得元に認めた形だけ）。

    - 対象商品が 1 つの告知: 認めた形の URL が 1 つだけならそれ
    - 対象商品が複数の告知（names が 2 つ以上）: この商品の名前（「」の中）の直後 30 字以内にあり、そのあいだにほかの商品の名前・
      ほかの URL が無く、URL の直後の括弧がほかの商品の名前でないものだけ（「URL（ほかの商品）」の書き方を取り違えない）
    決められなければ None（推測しない）。
    """
    from src.tcg.action_url import EXTERNAL_FORM_RULES, _rule_ok
    from src.tcg.lottery.parse import _product_tag
    rules = EXTERNAL_FORM_RULES.get(str(retailer or "").upper(), ())
    if not rules or not body:
        return None
    all_urls = [(m.start(), m.end(), m.group(0).rstrip(".")) for m in _URL_IN_TEXT.finditer(body)]
    found = [(s0, e0, u) for s0, e0, u in all_urls if _rule_ok(u, rules)]
    uniq = list(dict.fromkeys(u for _, _, u in found))
    multi = len([n for n in (names or ()) if n]) >= 2
    if not multi:
        return uniq[0] if len(uniq) == 1 else None
    tag = _product_tag(product_name) or ""
    others = [t for t in ((_product_tag(n) or "") for n in names if n and n != product_name) if t and t != tag]
    if not tag:
        return None
    hits = []
    for m in re.finditer(re.escape(tag), body):
        for s0, e0, u in found:
            gap = body[m.end():s0]
            if not (0 <= s0 - m.end() <= 30):
                continue
            if any(o in gap for o in others) or any(m.end() <= a0 < s0 for a0, _, _ in all_urls):
                continue
            after = body[e0:e0 + 4 + max((len(o) for o in others), default=0)]
            if any(re.match(r"\s*[（(]\s*" + re.escape(o), after) for o in others):
                continue                 # 「URL（ほかの商品）」の書き方（URL の後ろの括弧が商品名）
            hits.append(u)
            break
    hits = list(dict.fromkeys(hits))
    return hits[0] if len(hits) == 1 else None


def _cancel_fields(found) -> dict:
    """detect_cancellation の結果 → 抽選の項目（中止は cancelled・受付の早期終了は application_closed。明記が無ければ何も付けない）。"""
    from src.tcg.lottery.parse import CANCELLED
    if not found:
        return {}
    kind, word = found
    return {"cancelled": True, "cancel_text": word} if kind == CANCELLED else {"application_closed": True, "cancel_text": word}


class LotteryAdapter(BaseTcgCollector):
    """抽選告知コレクターの基底。サブクラスは collect() で発見と取得を行う。"""

    source_id: str = ""
    retailer: str = ""
    retailer_name: str = ""
    lottery_source_type: str = "RETAILER_OFFICIAL"
    channel = "ONLINE"
    max_detail_fetch: int = 4

    # 1回の実行の中で同じ一覧ページを2回取得しないためのキャッシュ
    _page_cache: dict[str, Optional[str]] = {}

    def __init__(self) -> None:
        super().__init__()
        self.source_key = self.source_id
        self.health["source"] = self.source_id
        self.funnel.source = self.source_id
        self.lottery_events: list[dict] = []
        self.announcements: list[dict] = []

    # ── 取得 ────────────────────────────────────────────────────────────
    def fetch_listing(self, url: str, *, use_cache: bool = True) -> Optional[str]:
        self.funnel.pages_discovered += 1
        if use_cache and url in LotteryAdapter._page_cache:
            html = LotteryAdapter._page_cache[url]
            self.funnel.notes.append(f"一覧ページは同一実行内の取得結果を再利用: {url}")
            if html:
                self.funnel.pages_requested += 1
                self.funnel.pages_loaded += 1
            return html
        html = self._fetch(url, page_type=PAGE_LISTING)
        LotteryAdapter._page_cache[url] = html
        return html

    def fetch_detail(self, url: str, referer: Optional[str] = None) -> Optional[str]:
        self.funnel.pages_discovered += 1
        html = self._fetch(url, page_type=PAGE_NEWS, referer=referer)
        if html:
            self.funnel.news_pages_loaded += 1
        return html

    @classmethod
    def clear_cache(cls) -> None:
        cls._page_cache = {}

    # ── 判定 ────────────────────────────────────────────────────────────
    def screen_title(self, title: str) -> Optional[str]:
        """タイトルで棄却すべきなら理由を返す。採用候補なら None。

        大会・参加型イベントは常に棄却する。タイトルに抽選販売を示す語があれば、
        「アプリ」「プレイヤーズクラブ」「特典」等の語では棄却しない（過剰棄却の防止）。
        """
        t = title or ""
        if any(w in t for w in TOURNAMENT_TERMS):
            return REJECT_TOURNAMENT
        if any(w in t for w in ANNOUNCEMENT_SALE_PHRASES):
            return None
        if is_non_sale_announcement(t):
            return REJECT_NON_SALE
        return None

    @staticmethod
    def is_lottery_sale(text: str) -> bool:
        """抽選販売・購入権の抽選と確認できるか（「抽選」単独では不可）。"""
        t = text or ""
        if not any(p in t for p in LOTTERY_SALE_PHRASES):
            return False
        # 「抽選で○○が当たる」だけで、抽選販売の明記が無いものはプレゼント抽選
        if _GIVEAWAY_RE.search(t) and "抽選販売" not in t and "購入権" not in t:
            return False
        return True

    def screen_announcement_title(self, title: str) -> Optional[str]:
        """本文を読めない告知（タイトルだけ）を「抽選告知あり」として残してよいか。

        - 大会・参加型イベントは残さない。
        - タイトルに抽選販売であることを示す語（抽選販売 / 購入権 / 抽選受付 等）があれば、
          「特典」「アプリ」「プレイヤーズクラブ」等の語があっても残す（過剰棄却しない）。
        - 抽選販売の語が無く、プレゼント・キャンペーン・キャンペーン告知だけのものは残さない。
        """
        t = title or ""
        if any(w in t for w in TOURNAMENT_TERMS):
            return REJECT_TOURNAMENT
        if any(w in t for w in ANNOUNCEMENT_SALE_PHRASES):
            if _GIVEAWAY_RE.search(t) and "抽選販売" not in t and "購入権" not in t:
                return REJECT_GIVEAWAY
            return None
        if _GIVEAWAY_RE.search(t) or any(w in t for w in ("プレゼント", "キャンペーン", "景品")):
            return REJECT_GIVEAWAY
        return REJECT_NO_LOTTERY_SALE

    def reject(self, reason: str) -> None:
        self.funnel.reject(reason)
        if self.funnel.pages:
            self.funnel.pages[-1].rejected += 1

    # ── イベント化 ──────────────────────────────────────────────────────
    def build_from_article(self, *, title: str, body: str, url: str,
                           published_at: Optional[str], entry_url: Optional[str] = None,
                           result_url: Optional[str] = None,
                           tcg_hint: Optional[str] = None,
                           source_type: Optional[str] = None,
                           store_name: Optional[str] = None, store_id: Optional[str] = None,
                           targets: Optional[list[dict]] = None) -> list[dict]:
        """記事本文から抽選イベントを作る。対象商品ごとに1件。

        store_name・store_id を渡すと、店舗ごとの抽選（store_specific）として作る（店舗のブログ・告知用）。
        """
        self.funnel.candidate_events += 1
        if self.funnel.pages:
            self.funnel.pages[-1].candidate_blocks += 1
        head = (title or "") + "\n" + (body or "")[:400]
        reason = self.screen_title(title)
        if reason:
            self.reject(reason)
            return []
        if not self.is_lottery_sale(head + "\n" + (body or "")):
            self.reject(REJECT_GIVEAWAY if _GIVEAWAY_RE.search(body or "")
                        else REJECT_NO_LOTTERY_SALE)
            return []

        # targets: 取得元の告知の書き方に合わせて、呼び出し側が本文から読んだ対象商品（無ければ共通のパーサ・件名）
        targets = targets or extract_target_products(body) or [
            {"product_name": product_name_from_title(title), "retail_price": None}]
        source_type = source_type or self.lottery_source_type
        entry = entry_url if entry_url and is_official_url(entry_url) else None
        ext_names = [str(t.get("product_name") or "") for t in targets]
        result = result_url if result_url and is_official_url(result_url) else None
        elig = extract_eligibility(body)
        from src.tcg.lottery.conditions import extract_conditions, strip_quotes
        from src.tcg.lottery.registry import NO_REPRINT, quote_allowed
        names = [str(t.get("product_name") or "") for t in targets]

        def conds_for(name: str) -> dict:
            # 複数商品の告知では、ほかの商品の名前が書かれた行を、この商品の条件にしない
            c = {k: v for k, v in extract_conditions(body, other_products=[n for n in names if n != name]).items() if v}
            # 規約で原文の転載の可否を確かめていない取得元は、根拠の行（quote・other_conditions）を出力に残さない
            return c if quote_allowed(self.retailer) else strip_quotes(c)
        if self.retailer in NO_REPRINT:
            elig = {**elig, "eligibility_text": None}       # 規約が転載を断る取得元: 応募条件の原文は出さない（真偽値の項目は残す）
        shrink = detect_shrink_status(body)
        event_type = LT_PURCHASE_RIGHT if "購入権" in head else LT_LOTTERY
        out: list[dict] = []
        no_schedule = True
        for tgt in targets:
            name = tgt["product_name"]
            tcg = detect_tcg(name) or tcg_hint or detect_tcg(title)
            if tcg is None:
                self.reject(REJECT_NO_CARD_PRODUCT)
                continue
            sched = extract_schedule(body, published_at, product_name=name)
            if not any(sched.get(k) for k in ("application_start", "application_end",
                                              "application_start_date", "application_end_date")):
                continue
            no_schedule = False
            ev = LotteryEvent(
                tcg=tcg, product_name=name, retailer=self.retailer,
                retailer_name=self.retailer_name, event_type=event_type,
                channel=self.channel, store_specific=bool(store_name), store_name=store_name, store_id=store_id,
                retail_price=tgt.get("retail_price"),
                price_unit=tgt.get("price_unit") or "UNKNOWN", product_code=tgt.get("product_code"),
                price_text=tgt.get("price_text"),
                shrink_status=shrink if shrink != "UNKNOWN" else None,
                # 公式の告知の本文に載った外部フォーム（取得元ごとに認めた形だけ）は entry_url（公式ドメインだけ）と別の項目に持つ。
                # 判定は action_url.classify が行い、外部フォームは external_entry_url になる（「応募する」のボタンにはしない）
                entry_url=entry, external_form_url=None if entry else external_form_in(body, self.retailer, name, ext_names),
                result_url=result, source_url=url, source_type=source_type,
                confidence=confidence_for_source(source_type), verified=True,
                published_at=published_at, observed_at=self._fetched_at or now_jst().isoformat(),
                last_verified_at=now_jst().isoformat(),
                collection_method="HTML", conditions=conds_for(name),
                application_methods=detect_application_methods(body),
                **_cancel_fields(detect_cancellation(title, body, product_name=name,
                                                     other_products=[n for n in names if n != name])),
                **{k: v for k, v in sched.items()},
                **{k: v for k, v in elig.items()},
            )
            out.append(ev.to_dict())
        if no_schedule and not published_at:
            self.funnel.notes.append(
                "公開日が取れない記事は、年の書かれていない日付を読まない"
                f"（推測しないため）: {url}")
        if no_schedule:
            # 告知はあるが日程が本文に無い（画像のみ等）。日程は推測しない
            self.reject(REJECT_SCHEDULE_NOT_IN_TEXT)
            self.announcements.append({
                "title": title, "source_url": url, "published_at": published_at,
                "retailer": self.retailer, "retailer_name": self.retailer_name,
                "tcg": tcg_hint or detect_tcg(title + body[:400]),
                "reason": "日程が本文テキストに無い（画像のみ等）。手動確認が必要",
            })
            return []
        self.funnel.accept(len(out))
        if self.funnel.pages:
            self.funnel.pages[-1].accepted += len(out)
        return out

    def finish(self) -> list[dict]:
        """health / funnel を確定させる（到達不能の判定を含む）。"""
        self.lottery_events = list(self.lottery_events)
        msgs = " ".join(self.health.get("error_messages") or [])
        self.health["unreachable"] = (self.funnel.pages_loaded == 0 and
                                      (bool(re.search(r"Timeout|ConnectionError|NameResolution", msgs))
                                       or self.health.get("robots") == "robots_unreachable"))
        self.health["source_id"] = self.source_id
        self.health["announcements"] = self.announcements
        self._finish(self.lottery_events)
        self.health["events_found"] = len(self.lottery_events)
        return self.lottery_events

    @staticmethod
    def host(url: str) -> str:
        return (urlparse(url or "").hostname or "").lower()
