"""LLM の抽出器の差し込み口（今回は実装しない。NullExtractor だけ）。

- LLM の出力は信用しない: すべて evidence.verify（G3: quote の完全一致・値の再導出）にかける
- 出力の形は OUTPUT_SCHEMA で固定（自由文の項目は quote だけ）。本文中の指示文は値としてしか扱わない
- 受付中かどうか（状態）は LLM に言わせない。スキーマに状態の項目は無い（compute_lottery_status で計算する）
- LLM にツール（取得）を持たせない。取得する URL はエンジンが決める
"""
from __future__ import annotations

from typing import Optional, Protocol

from src.discovery.engine.extract import evidence as evm
from src.discovery.engine.models import FIELDS, Evidence, Extraction, FieldValue

# LLM に返させる JSON の形（項目ごとに value と quote。状態・受付中の項目は持たない）
OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "fields": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                name: {"type": "object", "additionalProperties": False,
                       "properties": {"value": {}, "quote": {"type": ["string", "null"]},
                                      "start": {"type": ["integer", "null"]}, "end": {"type": ["integer", "null"]},
                                      "price_unit": {"type": ["string", "null"]}, "tax": {"type": ["string", "null"]}},
                       "required": ["value", "quote"]}
                for name in FIELDS
            },
        },
    },
    "required": ["fields"],
}


class Extractor(Protocol):
    name: str

    def extract(self, doc) -> Optional[Extraction]:
        ...


class NullExtractor:
    """何もしない（LLM を使わない日）。G4 は rules_only になる。"""
    name = "null"

    def extract(self, doc) -> Optional[Extraction]:
        return None


def from_llm_json(doc, data: dict, extractor_name: str) -> Extraction:
    """LLM が返した JSON を Extraction にする。ここでは検証しない（gate が evidence.verify_extraction で確かめる）。

    start/end が無いときは quote の最初の出現を探す（見つからなければ位置 -1 のまま = G3 で落ちる）。
    知らない項目・状態の項目は捨てる（warnings に残す）。
    """
    ext = Extraction(doc_id=doc.doc_id, url=doc.url, fetched_at=doc.fetched_at, extractor=extractor_name)
    fields = (data or {}).get("fields") if isinstance(data, dict) else None
    for name, raw in (fields or {}).items():
        if name not in FIELDS:
            ext.warnings.append(f"unknown_field_dropped:{name}")
            continue
        if not isinstance(raw, dict) or raw.get("value") is None:
            continue
        quote = raw.get("quote")
        if not isinstance(quote, str) or not quote:
            ext.fields[name] = FieldValue(raw.get("value"), None)
            continue
        s, e = raw.get("start"), raw.get("end")
        if not (isinstance(s, int) and isinstance(e, int)):
            span = evm.locate(doc.text, quote)
            s, e = span if span else (-1, -1)
        extra = {k: raw[k] for k in ("price_unit", "tax") if raw.get(k) is not None}
        ext.fields[name] = FieldValue(raw.get("value"),
                                      Evidence(doc_id=doc.doc_id, url=doc.url, fetched_at=doc.fetched_at,
                                               start=s, end=e, quote=quote), extra)
    pub = ext.fields.get("published_at")
    ext.base_published_at = pub.value if pub is not None else getattr(doc, "published_hint", None)
    return ext
