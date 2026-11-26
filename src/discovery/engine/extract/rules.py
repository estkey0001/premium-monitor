"""ルールの抽出器: 既存の src/tcg/lottery/parse.py の結果に、本文中の根拠の位置を付けて Extraction にする。

新しい抽出の規則は作らない。parse.py が出した値ごとに、同じラベルの近く（parse.py と同じ区間）で同じ値を生む
日時の表記を探し、その位置を根拠にする。位置が見つからない値は捨てる（evidence_not_located）。
年の補完に使う公開日は、本文中の「公開日」等のラベルつきの日付か、日付だけの行（ニュースの見出しの日付）。
本文に無ければ frontier の手がかり（sitemap の lastmod・RSS の pubDate）。どれも無ければ年の無い日付は読まない。
"""
from __future__ import annotations

import re
from typing import Optional

from src.discovery.engine.extract import evidence as evm
from src.discovery.engine.models import Extraction, FieldValue

NAME = "rules@parse.py"

_PUB_LABEL = re.compile(r"(?:公開日|掲載日|更新日|投稿日|配信日|発表日)\s*[:：]?\s*")
_PUB_LINE_MAX = 15                       # 日付だけの行を公開日とみなすのは先頭からこの行数まで

# parse.extract_schedule の出力のキー → ラベルの組（parse._LABELS の名前）
_KEY_GROUP = {
    "application_start": "application", "application_end": "application",
    "application_start_date": "application", "application_end_date": "application",
    "winner_announcement_at": "winner_announcement_at", "winner_announcement_date": "winner_announcement_at",
    "purchase_start": "purchase", "purchase_start_date": "purchase",
    "purchase_end": "purchase", "purchase_end_date": "purchase",
}


def _published(doc) -> tuple[Optional[FieldValue], Optional[str], str]:
    """(published_at の FieldValue, 年の補完に使う日付, その出所 page/feed/none)。"""
    text = doc.text
    for m in _PUB_LABEL.finditer(text):
        dm = evm._PUB_DT.match(text, m.end())
        if dm:
            v, _ = evm.derive("published_at", dm.group(0))
            if v:
                return FieldValue(v, evm.make_evidence(doc, dm.start(), dm.end())), v, "page"
    pos = 0
    for i, ln in enumerate(text.split("\n")):
        if i >= _PUB_LINE_MAX:
            break
        dm = evm._PUB_DT.fullmatch(ln)
        if dm:
            v, _ = evm.derive("published_at", ln)
            if v:
                return FieldValue(v, evm.make_evidence(doc, pos, pos + len(ln))), v, "page"
        pos += len(ln) + 1
    hint = getattr(doc, "published_hint", None)
    if hint:
        return None, hint, "feed"
    return None, None, "none"


def _locate_schedule(doc, key: str, value: str, base: Optional[str]) -> Optional[tuple[int, int]]:
    from src.tcg.lottery.parse import _DT, _LABELS, _SEGMENT_MAX
    groups = dict(_LABELS)
    labels = list(groups.get(_KEY_GROUP.get(key, ""), ()))
    if key in ("purchase_end", "purchase_end_date"):
        labels += list(groups.get("purchase_end", ()))
    text = doc.text
    for label in labels:
        pos = text.find(label)
        if pos < 0:
            continue
        lo = pos + len(label)
        for m in _DT.finditer(text, lo, min(len(text), lo + _SEGMENT_MAX)):
            q = m.group(0).rstrip()                      # 時刻の後ろの空白は根拠に含めない
            v, _ = evm.derive(key, q, base)
            if v == value:
                return m.start(), m.start() + len(q)
    return None


def _first(doc, words, limit: Optional[int] = None) -> Optional[tuple[str, int]]:
    hay = doc.text if limit is None else doc.text[:limit]
    best = None
    for w, _v in words:
        i = hay.find(w)
        if i >= 0 and (best is None or i < best[1]):
            best = (w, i)
    return best


def _eligibility_spans(doc) -> list[tuple[int, str]]:
    """応募条件を述べている行（parse.extract_eligibility と同じ判定）の (開始位置, 行)。"""
    from src.tcg.lottery.parse import _BARE_HEAD, _ELIG_CONTEXT, _ELIG_HEAD, _LABELS, _SECTION_HEAD
    lines, pos = [], 0
    for ln in doc.text.split("\n"):
        lines.append((pos, ln))
        pos += len(ln) + 1
    out: list[tuple[int, str]] = []
    for i, (p, ln) in enumerate(lines):
        if _ELIG_HEAD.search(ln) and (_SECTION_HEAD.match(ln) or _BARE_HEAD.match(ln)):
            out.append((p, ln))
            for p2, nxt in lines[i + 1:i + 9]:
                if (_SECTION_HEAD.match(nxt) or _BARE_HEAD.match(nxt)
                        or any(lab in nxt for _f, labels in _LABELS for lab in labels)):
                    break
                out.append((p2, nxt))
        elif _ELIG_HEAD.search(ln) or _ELIG_CONTEXT.search(ln):
            out.append((p, ln))
    seen, uniq = set(), []
    for p, ln in out:
        if p not in seen:
            seen.add(p)
            uniq.append((p, ln))
    return uniq


class RulesExtractor:
    name = NAME

    def extract(self, doc) -> Extraction:
        from src.tcg.lottery.parse import (
            extract_eligibility, extract_schedule, extract_target_products, product_name_from_title,
        )
        ext = Extraction(doc_id=doc.doc_id, url=doc.url, fetched_at=doc.fetched_at, extractor=NAME)
        text = doc.text
        f = ext.fields
        first_line = text.split("\n", 1)[0] if text else ""
        if first_line:
            f["title"] = FieldValue(first_line, evm.make_evidence(doc, 0, len(first_line)))
        pub_fv, base, base_src = _published(doc)
        if pub_fv:
            f["published_at"] = pub_fv
        ext.base_published_at = base
        if base_src == "feed":
            ext.warnings.append("year_base_from_feed_date")
        elif base_src == "none":
            ext.warnings.append("published_at_unknown")

        # 日程（parse.py の値に根拠を付ける。根拠の無い値は捨てる）
        sched = extract_schedule(text, base)
        for key, value in sched.items():
            span = _locate_schedule(doc, key, value, base)
            if span is None:
                ext.warnings.append(f"evidence_not_located:{key}")
                continue
            f[key] = FieldValue(value, evm.make_evidence(doc, *span))

        # 種類・TCG・商品コード（タイトル優先）
        hit = _first(doc, evm.EVENT_WORDS, limit=len(first_line))
        if hit:
            f["event_type"] = FieldValue(dict(evm.EVENT_WORDS)[hit[0]], evm.make_evidence(doc, hit[1], hit[1] + len(hit[0])))
        hit = _first(doc, evm.TCG_WORDS)
        if hit:
            f["tcg"] = FieldValue(dict(evm.TCG_WORDS)[hit[0]], evm.make_evidence(doc, hit[1], hit[1] + len(hit[0])))
        m = evm._CODE.search(first_line) or evm._CODE.search(text)
        if m:
            f["product_code"] = FieldValue(m.group(1), evm.make_evidence(doc, m.start(), m.end()))

        # 商品名・価格（【対象商品】の箇条書き。価格は「円（税込」が同じ行にあるものだけ）
        targets = extract_target_products(text)
        if targets:
            name = targets[0]["product_name"]
            want_price = targets[0].get("retail_price") is not None
            span, hint = None, len(first_line)
            while True:                                  # 箇条書きの行（価格が同じ行にある出現）を優先する
                sp = evm.locate(text, name, hint)
                if sp is None:
                    break
                span = span or sp
                eol = text.find("\n", sp[1])
                eol = len(text) if eol < 0 else eol
                pm = evm._PRICE.search(text, sp[1], eol) if want_price else None
                if pm:
                    span = sp
                    quote = text[sp[0]:pm.end()]
                    v, extra = evm.derive("retail_price", quote)
                    if v is not None:
                        f["retail_price"] = FieldValue(v, evm.make_evidence(doc, sp[0], pm.end()), dict(extra))
                    break
                hint = sp[1]
            if span:
                f["product_name_raw"] = FieldValue(name, evm.make_evidence(doc, *span))
        if "product_name_raw" not in f and first_line:
            name = product_name_from_title(first_line)
            span = evm.locate(first_line, name)
            if name and span:
                f["product_name_raw"] = FieldValue(name, evm.make_evidence(doc, *span))

        # JAN（ラベルつき・チェックデジットが合うものだけ）
        m = evm._JAN.search(text)
        if m and evm.jan_ok(m.group(1)):
            f["jan"] = FieldValue(m.group(1), evm.make_evidence(doc, m.start(), m.end()))

        # 応募条件（parse.py が True にした項目だけ、条件の行の中の語を根拠にする）
        elig = extract_eligibility(text)
        spans = _eligibility_spans(doc)
        words = evm._eligibility_words()
        for k in evm.BOOL_FIELDS:
            if not elig.get(k):
                continue
            loc = None
            for p, ln in spans:
                for w in words.get(k, ()):
                    j = ln.find(w)
                    if j >= 0:
                        loc = (p + j, p + j + len(w))
                        break
                if loc:
                    break
            if loc:
                f[k] = FieldValue(True, evm.make_evidence(doc, *loc))
            else:
                ext.warnings.append(f"evidence_not_located:{k}")
        if spans:
            from src.tcg.lottery.parse import _BARE_HEAD, _SECTION_HEAD
            body_lines = [(p, ln) for p, ln in spans if not (_SECTION_HEAD.match(ln) or _BARE_HEAD.match(ln))]
            p, ln = (body_lines or spans)[0]
            f["eligibility_text"] = FieldValue(ln, evm.make_evidence(doc, p, p + len(ln)))

        from src.discovery.engine.models import FIELDS
        ext.unknown = [k for k in FIELDS if f.get(k) is None or f[k].value is None]
        return ext
