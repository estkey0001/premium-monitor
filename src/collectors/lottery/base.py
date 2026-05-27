"""
BaseLotteryCollector — 抽選販売コレクター基底クラス

調査日: 2026-05-27
取得方式: requests → Playwright フォールバック
"""

from __future__ import annotations

import re
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# 日本標準時
JST = timezone(timedelta(hours=9))

# 日付パターン
_DATE_PATTERNS = [
    # YYYY年M月D日 HH:MM
    re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日\s*(?:（[日月火水木金土]）)?\s*(\d{1,2}):(\d{2})"),
    # YYYY年M月D日（曜日）
    re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日"),
    # YYYY/M/D HH:MM
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})"),
    # YYYY/M/D
    re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})"),
    # YYYY-M-D HH:MM
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})"),
    # YYYY-M-D
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
]

# 受付期間を示すキーワード
_PERIOD_KEYWORDS = [
    "受付期間", "申込期間", "応募期間", "エントリー期間",
    "販売期間", "抽選期間", "受付開始", "受付終了",
]


def _match_to_str(m: re.Match) -> str:
    """re.Match から "YYYY-MM-DD HH:MM" 文字列を生成する。"""
    groups = m.groups()
    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
    if len(groups) >= 5:
        hour, minute = int(groups[3]), int(groups[4])
    else:
        hour, minute = 0, 0
    return f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"


class BaseLotteryCollector:
    """抽選販売コレクターの基底クラス。"""

    SHOP_ID: str = ""
    SHOP_NAME: str = ""
    REQUIRES_JS: bool = False
    REQUEST_INTERVAL: float = 1.5  # 秒

    # ======================================================================
    # 公開インターフェース
    # ======================================================================

    def collect(self) -> list[dict]:
        """取得処理。成功分のみリストで返す（空リスト可）。"""
        raise NotImplementedError

    # ======================================================================
    # HTTP 取得
    # ======================================================================

    def _fetch_html(self, url: str) -> Optional[str]:
        """requests で HTML を取得して返す。失敗時は None。"""
        try:
            import requests
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 200:
                return resp.text
            logger.warning("[%s] HTTP %s: %s", self.SHOP_ID, resp.status_code, url)
            return None
        except Exception as e:
            logger.warning("[%s] requests 失敗: %s — %s", self.SHOP_ID, url, e)
            return None

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """Playwright で本文テキストを取得して返す。失敗時は None。"""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                text = page.inner_text("body")
                browser.close()
                return text
        except ImportError:
            logger.warning("[%s] Playwright が未インストールのためスキップ: %s", self.SHOP_ID, url)
            return None
        except Exception as e:
            logger.warning("[%s] Playwright 失敗: %s — %s", self.SHOP_ID, url, e)
            return None

    def _fetch_page_text(self, url: str) -> Optional[str]:
        """requests → Playwright の順でページテキストを取得する。"""
        # まず requests を試みる
        html = self._fetch_html(url)
        if html:
            # HTML タグを除去してテキスト化（簡易）
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > 100:
                return text

        # requests が失敗 or テキストが短すぎる場合は Playwright にフォールバック
        if self.REQUIRES_JS or not html:
            logger.info("[%s] Playwright にフォールバック: %s", self.SHOP_ID, url)
            return self._fetch_with_playwright(url)

        return html  # HTML のみ返す（短くてもそのまま）

    # ======================================================================
    # 日付パース
    # ======================================================================

    def _parse_dates_from_text(self, text: str) -> tuple[str, str]:
        """
        テキストから (entry_start_at, entry_end_at) を返す。
        「受付期間」近傍を優先。取得失敗時は空文字。
        """
        # 受付期間キーワード近傍を優先
        for keyword in _PERIOD_KEYWORDS:
            idx = text.find(keyword)
            if idx == -1:
                continue
            # キーワード前後 500 文字を対象にする
            chunk = text[max(0, idx - 50): idx + 500]
            dates = self._extract_all_dates(chunk)
            if len(dates) >= 2:
                return dates[0], dates[1]
            if len(dates) == 1:
                return "", dates[0]

        # フォールバック: テキスト全体から日付を探す
        dates = self._extract_all_dates(text)
        if len(dates) >= 2:
            return dates[0], dates[1]
        if len(dates) == 1:
            return "", dates[0]
        return "", ""

    def _extract_all_dates(self, text: str) -> list[str]:
        """テキストから日付文字列リストを返す（重複除去・順序保持）。

        前処理として「正午」→「 12:00」、「深夜」→「 00:00」に変換する。
        また年なし「M月D日」パターンも対応し、直前の YYYY年 から年を推定する。

        NOTE: 同一テキスト位置を複数のパターンがマッチする場合（例: 時刻付きパターンと
        日付のみパターン）、先に登録された範囲（より具体的なパターン）を優先して
        後続パターンの重複マッチを除外する。
        """
        # ---------- 前処理 ----------
        # 「正午」→「 12:00」（「午前0時」等との混同を避けるため先に処理）
        text = re.sub(r'正午', ' 12:00', text)
        # 「深夜」「深夜0時」→「 00:00」
        text = re.sub(r'深夜(?:0時|零時)?(?=[^0-9]|$)', ' 00:00', text)

        # (start, end, date_str) のリスト
        found: list[tuple[int, int, str]] = []

        # ---------- 年付きパターン ----------
        for pat in _DATE_PATTERNS:
            for m in pat.finditer(text):
                s = _match_to_str(m)
                m_start, m_end = m.start(), m.end()
                # 既存マッチと範囲が重複する場合はスキップ（先勝ち = より具体的なパターン優先）
                overlaps = any(
                    not (m_end <= ex_start or m_start >= ex_end)
                    for ex_start, ex_end, _ in found
                )
                if not overlaps:
                    found.append((m_start, m_end, s))

        # ---------- 年なし「M月D日」パターン（年は直前の YYYY年 から推定）----------
        # テキスト中の YYYY年 の位置を収集
        _year_positions: list[tuple[int, int]] = [
            (m.start(), int(m.group(1)))
            for m in re.finditer(r'(\d{4})年', text)
        ]
        _default_year = datetime.now(tz=JST).year

        # 時刻あり: M月D日（曜）HH:MM
        _noyr_with_time = re.compile(
            r"(\d{1,2})月\s*(\d{1,2})日\s*(?:（[日月火水木金土]）)?\s*(\d{1,2}):(\d{2})"
        )
        # 時刻なし: M月D日
        _noyr_date_only = re.compile(r"(\d{1,2})月\s*(\d{1,2})日")

        for pat in (_noyr_with_time, _noyr_date_only):
            for m in pat.finditer(text):
                m_start, m_end = m.start(), m.end()
                # 既存マッチと重複していればスキップ
                overlaps = any(
                    not (m_end <= ex_start or m_start >= ex_end)
                    for ex_start, ex_end, _ in found
                )
                if overlaps:
                    continue

                # 直前の YYYY年 から年を推定（見つからなければ当年）
                yr = _default_year
                for ypos, yval in reversed(_year_positions):
                    if ypos <= m_start:
                        yr = yval
                        break

                groups = m.groups()
                month, day = int(groups[0]), int(groups[1])
                if len(groups) >= 4:
                    hour, minute = int(groups[2]), int(groups[3])
                else:
                    hour, minute = 0, 0

                # 有効な日付かチェック
                try:
                    datetime(yr, month, day, hour, minute)
                except ValueError:
                    continue

                s = f"{yr:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
                found.append((m_start, m_end, s))

        # 出現位置順にソート
        found.sort(key=lambda x: x[0])
        return [s for _, _, s in found]

    # ======================================================================
    # フォーム URL 抽出
    # ======================================================================

    def _extract_form_url(self, text: str) -> str:
        """forms.gle または応募フォーム URL を抽出する。"""
        # Google Forms 短縮 URL
        m = re.search(r"https://forms\.gle/[A-Za-z0-9]+", text)
        if m:
            return m.group(0)
        # Google Forms 通常 URL
        m = re.search(r"https://docs\.google\.com/forms/[^\s\"'<>]+", text)
        if m:
            return m.group(0)
        # サイト内フォーム URL（/form/ や /entry/ を含む）
        m = re.search(r"https?://[^\s\"'<>]*(?:form|entry|apply|lottery)[^\s\"'<>]*", text, re.IGNORECASE)
        if m:
            return m.group(0)
        return ""

    # ======================================================================
    # ステータス判定
    # ======================================================================

    def _determine_status(self, entry_start_at: str, entry_end_at: str) -> str:
        """
        "active" / "closed" / "upcoming" を返す。
        - entry_end_at が過去 → "closed"
        - entry_start_at が未来 → "upcoming"
        - entry_end_at が未来 → "active"
        - 不明 → "active"（保守的に active）
        """
        now = datetime.now(tz=JST)

        def _parse(s: str) -> Optional[datetime]:
            if not s:
                return None
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(s, fmt)
                    return dt.replace(tzinfo=JST)
                except ValueError:
                    continue
            return None

        end_dt = _parse(entry_end_at)
        start_dt = _parse(entry_start_at)

        if end_dt and end_dt < now:
            return "closed"
        if start_dt and start_dt > now:
            return "upcoming"
        if end_dt and end_dt >= now:
            return "active"
        return "active"  # 不明は保守的に active

    # ======================================================================
    # ユーティリティ
    # ======================================================================

    def _now_jst_str(self) -> str:
        """現在の JST 時刻を "YYYY-MM-DD HH:MM" で返す。"""
        return datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M")

    def _make_event(self, **kwargs) -> dict:
        """CSV スキーマに合った dict を生成する。未指定カラムは空文字。"""
        base = {
            "product_name": "",
            "brand": "",
            "product_code": "",
            "official_price": "",
            "sale_method": "抽選販売",
            "status": "active",
            "entry_start_at": "",
            "entry_end_at": "",
            "url": "",
            "entry_form_url": "",
            "source_url": "",
            "checked_at": self._now_jst_str(),
            "data_source": "auto_scraped",
            "note": "",
        }
        base.update(kwargs)
        return base

    def _sleep(self) -> None:
        """リクエスト間のスリープ。"""
        time.sleep(self.REQUEST_INTERVAL)
