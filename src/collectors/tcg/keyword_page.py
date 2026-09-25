# -*- coding: utf-8 -*-
"""KeywordPageCollector — 告知ページ本文から TCG 販売イベントを抽出する共通実装。

各サイトの HTML 構造に依存せず、
「商品名キーワード」×「販売方式キーワード」が同一ブロックに現れた箇所だけを
イベント化する。判定できない場合は何も作らない（推測しない）。
"""
from __future__ import annotations

import re
import unicodedata

from src.tcg.classify import classify_event_type
from src.tcg.freshness import TTL_SECONDS
from src.tcg.models import EVENT_LOTTERY, TcgEvent, now_jst, parse_dt
from src.tcg.sales_context import is_product_lottery, is_sales_block

from .base import BaseTcgCollector

# 1ブロックの最大長（長すぎる塊は誤判定の元なので切る）
_BLOCK_MAX = 400
_SPLIT_RE = re.compile(r"\n{1,}")


# 商品名から取り除く定型句（日付・価格・メタ情報の混入を防ぐ）
_NAME_NOISE = (
    re.compile(r"\d{4}[年.\-/]\s*\d{1,2}[月.\-/]?\s*\d{0,2}日?.*$"),
    re.compile(r"[¥￥][0-9,]+.*$"),
    re.compile(r"(発売日|メーカー希望小売価格|価格|税込|税抜|販売価格).*$"),
    re.compile(r"^[】」』）\)\]]+"),
)


def _is_future(value) -> bool:
    """未来の販売開始日か（記事日付が読めない場合の代替根拠）。"""
    dt = parse_dt(value)
    return bool(dt and dt > now_jst())


def clean_product_name(name: str) -> str:
    """商品名から日付・価格・定型句を取り除く。"""
    s = (name or "").strip()
    for pat in _NAME_NOISE:
        s = pat.sub("", s).strip()
    s = s.strip("　 -–—|/／")
    # 短すぎる断片は商品名として採用しない
    return s if len(s) >= 4 else ""


_RELEASE_RE = re.compile(r"発売日?\s*[:：]?\s*(\d{4}[./年]\s*\d{1,2}(?:[./月]\s*\d{1,2}日?)?)")


def _release_text(block: str) -> str:
    """「発売日 2026.10」のような表記をそのまま保持する。

    月までしか分からない場合に日付を補完しない（推測しない）。
    """
    m = _RELEASE_RE.search(block or "")
    return m.group(1).strip() if m else ""


def _norm_name(name: str) -> str:
    """近似重複を判定するための正規化キー。"""
    s = unicodedata.normalize("NFKC", name or "").lower()
    return re.sub(r"[^a-z0-9ぁ-んァ-ヶ一-龠]", "", s)


def slugify(name: str) -> str:
    """商品名から product_id 用のスラッグを作る。"""
    s = unicodedata.normalize("NFKC", name or "").lower()
    s = re.sub(r"[^a-z0-9ぁ-んァ-ヶ一-龠ー]+", "-", s)
    return s.strip("-")[:80] or "unknown"


class KeywordPageCollector(BaseTcgCollector):
    """商品キーワードを含むブロックから販売イベントを抽出するコレクター。"""

    # 監視対象の商品キーワード（1件でも一致すればブロック採用）
    product_keywords: tuple[str, ...] = ()
    # ブロックを結合する行数（告知は複数行に分かれるため）
    block_lines: int = 6
    # 既定の販売方式（ページ性質上明らかな場合のみ設定。None なら本文判定）
    default_event_type: str | None = None

    def _windows(self, text: str) -> list[tuple[str, list[str]]]:
        """本文を「連続する数行」の窓に区切る。(結合テキスト, 行リスト) を返す。"""
        lines = [ln.strip() for ln in _SPLIT_RE.split(text or "") if ln.strip()]
        out: list[tuple[str, list[str]]] = []
        for i in range(len(lines)):
            window = lines[i:i + self.block_lines]
            chunk = " ".join(window)[:_BLOCK_MAX]
            if chunk:
                out.append((chunk, window))
        return out

    def _match_product(self, window: list[str]) -> str | None:
        """窓の先頭行に商品キーワードがある場合のみ採用する。

        先頭行を商品名の行に固定することで、隣接商品の価格・発売日を
        取り違えるのを防ぐ。
        """
        head = window[0] if window else ""
        for kw in self.product_keywords:
            if kw and kw in head:
                return kw
        return None

    def parse(self, text: str, url: str, html: str = "") -> list[TcgEvent]:
        events: list[TcgEvent] = []
        seen: set[tuple] = set()
        for block, window in self._windows(text):
            kw = self._match_product(window)
            if not kw:
                continue
            # 大会・イベント告知や、商品が特定できないブロックは取り込まない
            if not is_sales_block(block):
                continue
            et = self.default_event_type or classify_event_type(
                block, store=self.source_key, channel=self.channel)
            if et is None:
                continue   # 販売方式が読み取れないブロックはイベント化しない
            # 「エントリー」「応募」だけを根拠に抽選販売としない
            if et == EVENT_LOTTERY and not is_product_lottery(block):
                continue

            dates = self.extract_labeled_datetimes(block)
            product_name = self._product_name(kw, window)
            if not product_name:
                continue
            key = (_norm_name(product_name), et)
            if key in seen:
                continue

            kwargs: dict = {}
            if et == EVENT_LOTTERY:
                for f in ("application_start", "application_end", "result_date",
                          "purchase_start", "purchase_end"):
                    if dates.get(f):
                        kwargs[f] = dates[f]
            else:
                for f in ("sale_start", "sale_end"):
                    if dates.get(f):
                        kwargs[f] = dates[f]

            # TTL で鮮度管理するイベント（再入荷・突発販売など）は、
            # 記事の日付が読めない限り取り込まない。取得時刻を報告時刻の
            # 代わりに使うと、古い記事が常に「今買える」になってしまうため。
            if et in TTL_SECONDS:
                reported = dates.get("article_date")
                # 「発売日」「販売開始」ラベル由来の未来日だけを代替根拠にする
                future_sale = ("sale_start" in (dates.get("_labels") or [])
                               and _is_future(kwargs.get("sale_start")))
                if not reported and not future_sale:
                    continue
                if reported:
                    kwargs["reported_at"] = reported

            seen.add(key)
            price = self.extract_price(block)
            release = _release_text(block)
            if release:
                kwargs.setdefault("release_date", release)
            ev = self.build_event(
                product_id=slugify(product_name),
                product_name=product_name,
                text=block,
                url=url,
                event_type=et,
                price=price,
                note=block[:200],
                **kwargs,
            )
            if ev:
                events.append(ev)
        return events

    def _product_name(self, keyword: str, window: list[str]) -> str:
        """商品名らしい行を取り出す。取れなければ空文字（推測しない）。

        キーワードを含む行をそのまま商品名候補とする（前方の修飾語も保つ）。
        """
        for line in window:
            if keyword in line:
                name = clean_product_name(line)
                if name:
                    return name
        return ""
