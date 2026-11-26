"""根拠（evidence）の検証: 本文の正規化・quote の位置・値の決定論的な再導出（品質ゲート G3）。

- 本文は HTML を固定の手順でテキストにしたもの（normalize_html）。根拠の位置はこのテキスト上の文字オフセット
- quote は本文の [start:end] と完全一致しなければならない
- 値は quote から決定論的に導けなければならない（日付は parse.py の _DT と年の補完の規則だけ・価格は「円（税込」の形だけ）。
  quote に無い年・時刻を補った値、quote に無い価格・JAN は落ちる（null）
- 抽出器（ルール・LLM）の出力を信用しない。ここで機械的に確かめる
"""
from __future__ import annotations

import re
from typing import Optional

from src.discovery.engine.models import Evidence, Extraction, FieldValue

_WS = re.compile(r"[ \t　\xa0\r\f\v]+")
_DROP_TAGS = ("script", "style", "noscript", "template", "svg", "iframe")


def normalize_text(raw: str) -> str:
    """空白の正規化（行ごとに前後の空白を除き、行内の空白の連続を 1 つに・空行を除く）。文字そのものは変えない（NFKC にしない）。"""
    lines = []
    for ln in (raw or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = _WS.sub(" ", ln).strip()
        if s:
            lines.append(s)
    return "\n".join(lines)


def normalize_html(html: str) -> tuple[str, str]:
    """HTML → (タイトル, 正規化テキスト)。テキストの先頭行はタイトル（タイトルにも根拠の位置を付けられるように）。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    if soup.title and soup.title.get_text():
        title = normalize_text(soup.title.get_text()).replace("\n", " ")
    for t in soup(list(_DROP_TAGS)):
        t.decompose()
    if soup.title:
        soup.title.decompose()
    body = normalize_text(soup.get_text("\n"))
    text = (title + "\n" + body) if title else body
    return title, text.strip("\n")


def locate(text: str, quote: str, start_hint: int = 0) -> Optional[tuple[int, int]]:
    """quote の本文中の位置（start_hint 以降の最初の出現）。無ければ None。"""
    if not quote:
        return None
    i = (text or "").find(quote, max(0, start_hint))
    if i < 0:
        return None
    return i, i + len(quote)


def make_evidence(doc, start: int, end: int) -> Evidence:
    return Evidence(doc_id=doc.doc_id, url=doc.url, fetched_at=doc.fetched_at, start=start, end=end,
                    quote=doc.text[start:end])


# ── 値の再導出（quote → 値）────────────────────────────────────────────
_PUB_DT = re.compile(r"(?P<y>\d{4})\s*[年/.\-]\s*(?P<m>\d{1,2})\s*[月/.\-]\s*(?P<d>\d{1,2})\s*日?")
_PRICE = re.compile(r"([0-9][0-9,]{2,8})\s*円\s*[（(]?\s*税込")
_CODE = re.compile(r"[【\[]([A-Z]{2,4}-\d{2,3})[】\]]")
_JAN = re.compile(r"JAN\s*(?:コード)?\s*[:：]?\s*(\d{13})")
EVENT_WORDS = (("購入権", "PURCHASE_RIGHT"), ("抽選", "LOTTERY"), ("予約", "PREORDER"))
TCG_WORDS = (("ポケモンカード", "POKEMON"), ("ONE PIECEカード", "ONE_PIECE"), ("ワンピースカード", "ONE_PIECE"))
STRING_FIELDS = ("title", "product_name_raw", "eligibility_text")
BOOL_FIELDS = ("membership_required", "app_required", "identity_verification_required", "purchase_history_required",
               "store_pickup_required")


def _eligibility_words() -> dict:
    from src.tcg.lottery.parse import _ELIGIBILITY_RULES
    return {k: tuple(w) for k, w in _ELIGIBILITY_RULES}


def jan_ok(code: str) -> bool:
    """JAN（EAN-13）のチェックデジット。"""
    if not re.fullmatch(r"\d{13}", code or ""):
        return False
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(code[:12]))
    return (10 - s % 10) % 10 == int(code[12])


def derive_datetime(quote: str, base: Optional[str]) -> tuple[Optional[str], bool]:
    """日時の quote（parse.py の _DT 1 個に完全一致するもの）→ (ISO8601, 時刻が書かれていたか)。年の補完は parse.py と同じ。"""
    from src.tcg.lottery.parse import _DT, _to_iso
    from src.tcg.models import parse_dt
    m = _DT.fullmatch(quote or "")
    if not m or (quote or "").strip() != quote:
        return None, False
    return _to_iso(m, parse_dt(base))


def price_unit_of(quote: str) -> str:
    """価格の quote に書かれた単位（BOX / PACK / SET）。書かれていなければ UNKNOWN（入数から作らない）。"""
    q = quote or ""
    if re.search(r"BOX|ボックス", q, re.I):
        return "BOX"
    if re.search(r"1\s*パック(?!\d)|パック単価|/\s*パック", q):
        return "PACK"
    if re.search(r"1\s*セット", q):
        return "SET"
    return "UNKNOWN"


def derive(name: str, quote: str, base: Optional[str] = None):
    """項目名と quote から値を決定論的に導く。導けなければ (None, extra)。"""
    q = quote or ""
    if name in STRING_FIELDS:
        return (q or None), {}
    if name == "published_at":
        m = _PUB_DT.fullmatch(q.strip())
        if not m or m.group(0) != q:
            return None, {}
        try:
            from datetime import date
            return date(int(m["y"]), int(m["m"]), int(m["d"])).isoformat(), {}
        except ValueError:
            return None, {}
    if name.endswith("_date") or name in ("application_start", "application_end", "winner_announcement_at",
                                          "purchase_start", "purchase_end"):
        iso, has_time = derive_datetime(q, base)
        if iso is None:
            return None, {}
        if name.endswith("_date"):
            return (iso[:10] if not has_time else None), {}
        return (iso if has_time else None), {}
    if name == "retail_price":
        ms = list(_PRICE.finditer(q))
        if len(ms) != 1:
            return None, {}
        try:
            v = int(ms[0].group(1).replace(",", ""))
        except ValueError:
            return None, {}
        return v, {"price_unit": price_unit_of(q[:ms[0].start()]), "tax": "INCL"}
    if name == "product_code":
        m = _CODE.fullmatch(q)
        return (m.group(1) if m else None), {}
    if name == "jan":
        m = _JAN.fullmatch(q)
        return (m.group(1) if m and jan_ok(m.group(1)) else None), {}
    if name == "event_type":
        return dict(EVENT_WORDS).get(q), {}
    if name == "tcg":
        return dict(TCG_WORDS).get(q), {}
    if name in BOOL_FIELDS:
        return (True if q in _eligibility_words().get(name, ()) else None), {}
    return None, {}


def verify(name: str, fv: Optional[FieldValue], text: str, *, doc_id: str, base: Optional[str] = None) -> str:
    """値の根拠を確かめる。空文字なら合格。失敗の理由（evidence_missing / offset_out_of_range / quote_mismatch /
    doc_mismatch / value_not_derivable）を返す。値が None の項目は検証しない（合格扱い）。"""
    if fv is None or fv.value is None:
        return ""
    ev = fv.evidence
    if ev is None:
        return "evidence_missing"
    if ev.doc_id != doc_id:
        return "doc_mismatch"
    t = text or ""
    if not (isinstance(ev.start, int) and isinstance(ev.end, int)) or not (0 <= ev.start < ev.end <= len(t)):
        return "offset_out_of_range"
    if t[ev.start:ev.end] != ev.quote:
        return "quote_mismatch"
    v, extra = derive(name, ev.quote, base)
    if v is None or v != fv.value:
        return "value_not_derivable"
    for k, x in extra.items():
        if fv.extra.get(k) != x:
            return "value_not_derivable"
    return ""


def verify_extraction(ext: Extraction, text: str, *, doc_id: str) -> dict:
    """抽出の全項目を検証し、通らない項目を null にする。{項目: 理由}（落とした項目だけ）を返す。

    年の補完に使う公開日（base_published_at）は、本文の根拠つきの published_at か frontier の手がかりだけ。
    published_at 自体が落ちたら base も使わない。
    """
    bad: dict = {}
    pub = ext.fields.get("published_at")
    r = verify("published_at", pub, text, doc_id=doc_id)
    if r:
        bad["published_at"] = r
        ext.fields["published_at"] = FieldValue()
        if ext.base_published_at and pub is not None and ext.base_published_at == pub.value:
            ext.base_published_at = None
    base = ext.base_published_at
    for name, fv in list(ext.fields.items()):
        if name == "published_at":
            continue
        r = verify(name, fv, text, doc_id=doc_id, base=base)
        if r:
            bad[name] = r
            ext.fields[name] = FieldValue()
    for name in bad:
        if name not in ext.unknown:
            ext.unknown.append(name)
    return bad
