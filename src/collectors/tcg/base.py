# -*- coding: utf-8 -*-
"""BaseTcgCollector — TCG 販売情報コレクターの基底クラス。

方針:
  - robots.txt を尊重し、拒否されたら collect しない（blocked として記録）。
  - 取得失敗は例外を投げず health に記録する（Task27）。
  - ページから読み取れない項目は推測で埋めず None / UNKNOWN のまま残す。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from src.collectors.rate_limiter import RateLimiter
from src.collectors.robots_checker import RobotsChecker
from src.tcg.classify import classify_event_type, classify_source_type
from src.tcg.models import (
    TcgEvent, now_jst, CHANNEL_UNKNOWN,
)
from src.tcg.funnel import (
    CollectorFunnel, PageDiagnostic, PAGE_OTHER,
)
from src.tcg.shrink import detect_shrink_status, shrink_policy_note

logger = logging.getLogger(__name__)

# 正直な User-Agent（ブラウザを名乗らない。robots.txt の判定もこの名前で行う。Phase 12）
from src.collectors.polite import HONEST_UA as USER_AGENT  # noqa: E402
FETCH_TIMEOUT = 30
# 同一ドメインへのアクセス間隔（秒）。
# src/collectors/rate_limiter.py の RateLimiter が「安全のため最低60秒」を
# 強制するため、ここで 60 未満を指定しても実際には 60 秒になる（Task28 監査）。
# サイト負荷と ToS を優先し、アクセス頻度を上げる方向には変えない。
MIN_INTERVAL_SEC = 60

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_HREF_RE = re.compile(r"""<a\b[^>]*\bhref\s*=\s*["']([^"']+)["']""", re.I)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t　]+")

# 日時パターン（JST）
_DATETIME_PATTERNS = (
    re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日[^\d]{0,12}?(\d{1,2}):(\d{2})"),
    re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})[^\d]{0,12}?(\d{1,2}):(\d{2})"),
)
_DATE_PATTERNS = (
    re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日"),
    re.compile(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})"),
)
# 購入制限（「1会計5パックまで」等）
_LIMIT_RE = re.compile(
    r"(?:お?一人様|1会計|一会計|お1人様)[^。\n]{0,20}?(\d+)\s*(パック|個|点|BOX|ボックス)[^。\n]{0,6}?(?:まで|限り)?"
)
_PRICE_RE = re.compile(r"[¥￥]\s?([0-9][0-9,]{1,8})|([0-9][0-9,]{1,8})\s?円")


# 日時トークン（年を含むものだけを採用。年が無い日付は補完しない）
_DT_TOKEN = re.compile(
    r"(\d{4})\s*[年./\-]\s*(\d{1,2})\s*[月./\-]\s*(\d{1,2})\s*日?"
    r"(?:\s*[（(][^）)]{0,3}[）)])?"
    r"(?:[^\d]{0,6}(\d{1,2})\s*[:：]\s*(\d{2}))?"
)

# 日時に付くラベル。ラベルの直後（一定文字数内）に現れた日時だけを採用する。
_DT_LABELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("application_period", ("応募期間", "受付期間", "申込期間", "エントリー期間",
                            "抽選期間")),
    ("application_start", ("応募開始", "受付開始", "申込開始", "エントリー開始")),
    ("application_end", ("応募締切", "応募終了", "受付終了", "受付締切",
                         "申込締切", "締切", "エントリー終了")),
    ("result_date", ("当選発表", "抽選結果", "結果発表")),
    ("purchase_period", ("購入期間", "購入手続き期間")),
    ("purchase_end", ("購入期限", "購入手続き期限", "お支払い期限")),
    ("shipping_date", ("発送時期", "発送予定", "お届け時期", "お届け予定")),
    ("sale_period", ("販売期間", "受注期間")),
    # 「発売」は「発売中」「発売済」に部分一致して無関係な日付を拾うため入れない
    ("sale_start", ("発売日", "販売開始", "発売開始", "販売日")),
    ("sale_end", ("販売終了", "受注終了", "販売締切")),
    ("article_date", ("更新日", "掲載日", "公開日", "投稿日", "配信日")),
)
# ラベルからどれだけ後ろまでを見るか
_LABEL_WINDOW = 40
# 期間ラベル（開始と終了の2つを拾う）は余白を挟むことがあるため広めに見る
_PERIOD_LABEL_WINDOW = 90
_PERIOD_FIELDS = ("application_period", "purchase_period", "sale_period")


class TcgCollectorError(Exception):
    """コレクター内部エラー（呼び出し側が health に記録する）。"""


class BaseTcgCollector:
    """TCG 販売情報コレクターの基底。

    サブクラスは source_key / tcg / urls を定義し、parse() を実装する。
    """

    source_key: str = ""
    source_name: str = ""
    tcg: str = ""
    urls: tuple[str, ...] = ()
    channel: str = CHANNEL_UNKNOWN
    respect_robots: bool = True
    # 商品一覧を JavaScript で描画するページは Playwright で取得する。
    # （Playwright 未導入の環境では取得をスキップし health に記録する）
    requires_js: bool = False
    # Task31: 商品ページ / ニュース記事を発見できなければ DEGRADED とするか
    requires_product_pages: bool = False
    requires_news_pages: bool = False
    # collect() の既定ループで記録するページ種別
    default_page_type: str = PAGE_OTHER

    def __init__(self) -> None:
        # robots.txt の照合は名前（PremiumMonitor/1.0）で行う（UA の全文だと Mozilla として判定される。監査 H3）
        from src.collectors.polite import ROBOTS_AGENT
        self._robots = RobotsChecker(user_agent=ROBOTS_AGENT)
        self._rate = RateLimiter()
        self.health: dict = {
            "source": self.source_key,
            "source_name": self.source_name,
            "tcg": self.tcg,
            "last_checked": None,
            "last_success": None,
            "events_found": 0,
            "errors": 0,
            "blocked": False,
            "error_messages": [],
        }
        self.funnel = CollectorFunnel(
            source=self.source_key,
            requires_product_pages=self.requires_product_pages,
            requires_news_pages=self.requires_news_pages,
        )

    # ── 取得 ────────────────────────────────────────────────────────────
    def _record_error(self, diag: PageDiagnostic, message: str) -> None:
        self.health["errors"] += 1
        self.health["error_messages"].append(message)
        self.funnel.errors += 1
        diag.error = message

    def _fetch(self, url: str, page_type: str = PAGE_OTHER,
               referer: Optional[str] = None) -> Optional[str]:
        """URL を取得して HTML を返す。失敗・拒否時は None。

        Task3: 1ページごとに HTTP status / 最終 URL / タイトル / 本文長 /
        発見リンク数 / robots 判定根拠 を funnel に記録する。
        """
        diag = self.funnel.add_page(PageDiagnostic(url=url, page_type=page_type))
        self.funnel.pages_requested += 1

        # Task27: robots.txt の判定根拠を記録する（取得失敗 = 許可 と誤解させない）
        try:
            diag.robots_status = self._robots.robots_status(url)
        except Exception:  # noqa: BLE001 - 判定根拠の取得失敗は致命的でない
            diag.robots_status = "unknown"
        # robots.txt を取得できない（unknown）ときも取りに行かない（RFC 9309。監査 M7）
        if self.respect_robots and diag.robots_status == "disallowed":
            self.health["blocked"] = True
            self.health["robots"] = "robots_disallowed"
            self.funnel.blocked_pages += 1
            self._record_error(diag, f"robots.txt disallow: {url}")
            logger.warning("robots.txt で禁止のため取得をスキップ: %s", url)
            return None
        if self.respect_robots and diag.robots_status == "unknown":
            # 到達できない（タイムアウト・5xx など）は禁止と混ぜない（Phase 13）。取りには行かない（RFC 9309）が、
            # アクセス拒否ではなく「接続できない」として記録する
            self.health["unreachable"] = True
            self.health["robots"] = "robots_unreachable"
            self.funnel.robots_unreachable_pages += 1
            self._record_error(diag, f"robots.txt unreachable: {url}")
            logger.warning("robots.txt に到達できないため取得をスキップ: %s", url)
            return None

        delay = None
        try:
            delay = self._robots.get_crawl_delay(url)
        except Exception:  # noqa: BLE001 - crawl-delay 取得失敗は致命的でない
            delay = None
        self._rate.wait_if_needed(url, min_interval_sec=max(MIN_INTERVAL_SEC, delay or 0))

        if self.requires_js:
            html = self._fetch_with_playwright(url)
            if html:
                self._fill_page_diag(diag, html, status=200, final_url=url)
            else:
                diag.error = diag.error or "playwright fetch failed"
            return html

        try:
            import requests
            headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.8"}
            if referer:
                headers["Referer"] = referer
            resp = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
        except Exception as exc:  # noqa: BLE001 - ネットワーク失敗を health に集約
            self._record_error(diag, f"{type(exc).__name__}: {url}")
            logger.warning("取得失敗 %s: %s", url, exc)
            return None

        diag.http_status = resp.status_code
        diag.final_url = resp.url
        if resp.status_code != 200:
            if resp.status_code in (401, 403, 429):
                # bot 対策・アクセス制限。回避はせず BLOCKED として記録する
                self.health["blocked"] = True
                self.funnel.blocked_pages += 1
            self._record_error(diag, f"HTTP {resp.status_code}: {url}")
            return None
        resp.encoding = resp.apparent_encoding or resp.encoding
        self._fill_page_diag(diag, resp.text, status=200, final_url=resp.url)
        return resp.text

    def _fetch_json(self, url: str, page_type: str = PAGE_OTHER,
                    referer: Optional[str] = None) -> Optional[dict]:
        """JSON を返す URL（公式サイト自身が使う API 等）を取得する。"""
        text = self._fetch(url, page_type=page_type, referer=referer)
        if text is None:
            return None
        diag = self.funnel.pages[-1]
        try:
            import json
            data = json.loads(text)
        except ValueError as exc:
            self._record_error(diag, f"JSON parse error {url}: {exc}")
            self.funnel.pages_loaded -= 1   # 読めなかったので loaded から外す
            return None
        return data

    def _fill_page_diag(self, diag: PageDiagnostic, html: str, *, status: int,
                        final_url: str) -> None:
        """取得できたページの診断値を埋める。"""
        diag.http_status = diag.http_status or status
        diag.final_url = diag.final_url or final_url
        diag.html_length = len(html or "")
        m = _TITLE_RE.search(html or "")
        diag.page_title = self.to_text(m.group(1))[:120] if m else None
        diag.text_length = len(self.to_text(html))
        diag.links_discovered = len(_HREF_RE.findall(html or ""))
        self.funnel.links_discovered += diag.links_discovered
        self.funnel.pages_loaded += 1

    @staticmethod
    def extract_links(html: str) -> list[str]:
        """HTML 内の a[href] を列挙する。"""
        return _HREF_RE.findall(html or "")

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """JavaScript 描画ページを Playwright で取得する。

        Playwright が無い環境では取得せず health に記録する
        （requirements.txt に含まれており CI では利用できる）。
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.health["errors"] += 1
            self.funnel.errors += 1
            self.health["error_messages"].append(
                f"playwright 未導入のため取得をスキップ: {url}")
            logger.warning("playwright 未導入のため取得をスキップ: %s", url)
            return None
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(user_agent=USER_AGENT,
                                        locale="ja-JP")
                # networkidle は過去に他コレクターでタイムアウトしたため
                # domcontentloaded + 明示待機にする。
                resp = page.goto(url, wait_until="domcontentloaded",
                                 timeout=FETCH_TIMEOUT * 2000)
                # 拒否の応答（401/403/429）は本文として扱わない（Phase 12 再監査 M-A）
                if resp is not None and resp.status in (401, 403, 429):
                    browser.close()
                    self.health["blocked"] = True
                    self.health["errors"] += 1
                    self.funnel.errors += 1
                    self.health["error_messages"].append(f"playwright HTTP {resp.status}: {url}")
                    logger.warning("Playwright 取得が拒否された %s: HTTP %s", url, resp.status)
                    return None
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
            return html
        except Exception as exc:  # noqa: BLE001 - 描画失敗を health に集約
            self.health["errors"] += 1
            self.funnel.errors += 1
            self.health["error_messages"].append(
                f"playwright {type(exc).__name__}: {url}")
            logger.warning("Playwright 取得失敗 %s: %s", url, exc)
            return None

    @staticmethod
    def to_text(html: str) -> str:
        """HTML からテキストを抽出する。"""
        if not html:
            return ""
        s = _TAG_RE.sub(" ", html)
        s = _ANY_TAG_RE.sub("\n", s)
        s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
             .replace("&lt;", "<").replace("&gt;", ">").replace("&#039;", "'"))
        s = _WS_RE.sub(" ", s)
        return "\n".join(line.strip() for line in s.splitlines() if line.strip())

    # ── 抽出ヘルパー（読み取れない場合は None を返す） ──────────────────
    @staticmethod
    def extract_datetimes(text: str, limit: int = 8) -> list[str]:
        """本文から ISO8601(JST) の日時候補を抽出する。"""
        out: list[str] = []
        for pat in _DATETIME_PATTERNS:
            for m in pat.finditer(text or ""):
                y, mo, d, h, mi = (int(g) for g in m.groups())
                try:
                    out.append(datetime(y, mo, d, h, mi,
                                        tzinfo=now_jst().tzinfo).isoformat())
                except ValueError:
                    continue
        if not out:
            for pat in _DATE_PATTERNS:
                for m in pat.finditer(text or ""):
                    y, mo, d = (int(g) for g in m.groups())
                    try:
                        out.append(datetime(y, mo, d,
                                            tzinfo=now_jst().tzinfo).isoformat())
                    except ValueError:
                        continue
        # 重複を保ったまま順序を維持
        seen: set[str] = set()
        uniq = [x for x in out if not (x in seen or seen.add(x))]
        return uniq[:limit]

    @classmethod
    def extract_labeled_datetimes(cls, text: str) -> dict:
        """ラベルの近くにある日時だけを項目に割り当てる。

        「応募期間」「発売日」等のラベルが無い日時は採用しない
        （出現順で application_start / sale_start に機械的に入れると、
          更新日や隣の商品の発売日を取り違えるため）。
        期間表記（A〜B）はラベル1つから開始・終了の2つを取る。
        """
        raw = text or ""
        out: dict = {}
        for field, labels in _DT_LABELS:
            for label in labels:
                pos = raw.find(label)
                if pos < 0:
                    continue
                span = (_PERIOD_LABEL_WINDOW if field in _PERIOD_FIELDS
                        else _LABEL_WINDOW)
                window = raw[pos + len(label): pos + len(label) + span]
                found = [cls._dt_from_match(m) for m in _DT_TOKEN.finditer(window)]
                found = [f for f in found if f]
                if not found:
                    continue
                if field == "application_period":
                    out.setdefault("application_start", found[0])
                    if len(found) > 1:
                        out.setdefault("application_end", found[1])
                elif field == "purchase_period":
                    out.setdefault("purchase_start", found[0])
                    if len(found) > 1:
                        out.setdefault("purchase_end", found[1])
                elif field == "sale_period":
                    out.setdefault("sale_start", found[0])
                    if len(found) > 1:
                        out.setdefault("sale_end", found[1])
                else:
                    out.setdefault(field, found[0])
                out.setdefault("_labels", []).append(field)
                break
        return cls._drop_inconsistent(out)

    @staticmethod
    def _drop_inconsistent(dates: dict) -> dict:
        """終了が開始より前になっている組は破棄する（取り違えを残さない）。"""
        for start_key, end_key in (("application_start", "application_end"),
                                   ("sale_start", "sale_end"),
                                   ("purchase_start", "purchase_end")):
            st, en = dates.get(start_key), dates.get(end_key)
            if st and en and en < st:
                dates.pop(end_key, None)
                dates.pop(start_key, None)
        return dates

    @staticmethod
    def _dt_from_match(m: "re.Match") -> Optional[str]:
        y, mo, d, h, mi = m.groups()
        try:
            return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0),
                            tzinfo=now_jst().tzinfo).isoformat()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def extract_purchase_limit(text: str) -> Optional[str]:
        """購入制限の記載を抜き出す。記載が無ければ None（推測しない）。"""
        m = _LIMIT_RE.search(text or "")
        if not m:
            return None
        return f"1会計{m.group(1)}{m.group(2)}まで"

    @staticmethod
    def extract_price(text: str) -> Optional[int]:
        """価格の記載を抜き出す。無ければ None。"""
        m = _PRICE_RE.search(text or "")
        if not m:
            return None
        raw = m.group(1) or m.group(2) or ""
        try:
            value = int(raw.replace(",", ""))
        except ValueError:
            return None
        return value if 0 < value < 10_000_000 else None

    # ── イベント生成 ────────────────────────────────────────────────────
    def build_event(self, *, product_id: str, product_name: str, text: str,
                    url: str, store: Optional[str] = None,
                    event_type: Optional[str] = None,
                    **kwargs) -> Optional[TcgEvent]:
        """テキストから TcgEvent を構築する。

        販売方式が判定できない場合は None を返す（推測で LOTTERY 等にしない）。
        """
        store = store or self.source_key
        et = event_type or classify_event_type(text, store=store, channel=self.channel)
        if et is None:
            return None

        shrink = detect_shrink_status(text, store_key=store)
        note = shrink_policy_note(store)
        notes = list(kwargs.pop("notes", []) or [])
        if note:
            notes.append(note)

        ev = TcgEvent(
            tcg=self.tcg,
            product_id=product_id,
            product_name=product_name,
            event_type=et,
            store=store,
            channel=self.channel,
            source_url=url,
            source_type=classify_source_type(url, store_key=store),
            shrink_status=shrink,
            purchase_limit=kwargs.pop("purchase_limit", None)
            or self.extract_purchase_limit(text),
            price=kwargs.pop("price", None),
            notes=notes,
            observed_at=now_jst().isoformat(),
            **kwargs,
        )
        return ev

    # ── 実行 ────────────────────────────────────────────────────────────
    def collect(self) -> list[dict]:
        """URL を巡回してイベントを収集する。失敗しても例外を投げない。"""
        self.health["last_checked"] = now_jst().isoformat()
        events: list[dict] = []
        self.funnel.pages_discovered += len(self.urls)
        for url in self.urls:
            html = self._fetch(url, page_type=self.default_page_type)
            if not html:
                continue
            try:
                parsed = self.parse(self.to_text(html), url, html)
            except Exception as exc:  # noqa: BLE001 - 1URLの失敗で全体を止めない
                self.health["errors"] += 1
                self.health["error_messages"].append(f"parse error {url}: {exc}")
                self.funnel.errors += 1
                logger.exception("parse 失敗: %s", url)
                continue
            self.health["last_success"] = now_jst().isoformat()
            events.extend(e.to_dict() if isinstance(e, TcgEvent) else e for e in parsed)
        return self._finish(events)

    def _finish(self, events: list[dict]) -> list[dict]:
        """health と funnel を確定させる。"""
        self.health["events_found"] = len(events)
        self.funnel.current_events = len(events)
        self.health["status"] = self.funnel.status()
        self.health["status_reason"] = self.funnel.status_reason()
        self.health["funnel"] = self.funnel.to_dict()
        return events

    def parse(self, text: str, url: str, html: str = "") -> list:
        """サブクラスで実装。"""
        raise NotImplementedError
