"""振り分け: 品質ゲートの結果を既存の台帳（src/discovery/store.py の event_candidates.json）に入れる。

- 状態は既存の語彙だけ。エンジンが付けるのは ANNOUNCEMENT_REVIEW_REQUIRED（日程まで全関門を通ったものは
  publish_ready=true の印つき）と REVIEW_REQUIRED（本文が読めない）だけ。APPROVED / REGISTERED / VERIFIED にしない
- 人の判断（APPROVED / REJECTED / REGISTERED）は store.upsert が上書きしない
- 公開の台帳（commit される）に quote 本文・価格（未確定の値）を書かない。根拠は doc_id・URL・取得時刻・位置だけ
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.discovery import store as st
from src.discovery.engine.dedupe import ENGINE_ORIGIN
from src.discovery.engine.models import SCHEDULE_FIELDS

MIN_BODY_CHARS = 40
_KIND = {"LOTTERY": "LOTTERY", "PURCHASE_RIGHT": "LOTTERY", "PREORDER": "PREORDER"}
# 公開の台帳に書いてよい抽出値（価格・JAN・quote 本文・応募条件の原文は書かない）
_PUBLIC_VALUES = ("product_code",)


def candidate_id(url: str) -> str:
    from src.discovery.engine.urlpolicy import host_of
    from src.tcg.lottery.pipeline import normalize_url
    return st.stable_id("ev-engine", host_of(url), normalize_url(url))


def _sched(values: dict, key: str):
    fv = values.get(key) or values.get(key + "_date")
    return fv.value if fv is not None else None


def candidate_fields(doc, gate, *, found_by: str = "") -> dict:
    v = gate.values
    mt = gate.private_notes.get("product_match") or {}
    code = v.get("product_code").value if v.get("product_code") else ""
    title = v.get("title").value if v.get("title") else ""
    tcg = v.get("tcg").value if v.get("tcg") else None
    ev_type = v.get("event_type").value if v.get("event_type") else ""
    missing = [k for k in ("application_start", "application_end") if _sched(v, k) is None]
    pub = v.get("published_at").value if v.get("published_at") else ""
    return {
        "origin": ENGINE_ORIGIN,
        "source": f"engine:{doc.host}",
        "found_by": found_by,
        "kind": _KIND.get(ev_type, ""),
        "tcg": tcg,
        "title": title,
        "official_url": doc.url,
        "published_at": pub,
        "product_code": code or "",
        "product_mapping": "exact" if mt.get("product_match") == "exact" else "unmapped",
        "product_id": mt.get("product_id") if mt.get("product_match") == "exact" else None,
        # 告知の候補（ANNOUNCEMENT_REVIEW_REQUIRED）の application_start / application_end は空のまま（deploy-check #862:
        # 日程の無い告知に日程を入れない。日程は人が確かめて register-event-candidate --start/--end で入れる）。
        # エンジンが根拠つきで読めた日程は engine_schedule に分けて持つ（人の確認の手がかり。正式な値ではない）
        "application_start": None,
        "application_end": None,
        "engine_schedule": {k: v[k].value for k in SCHEDULE_FIELDS if k in v},
        "event_status": gate.lottery_status or "",
        "missing_fields": missing,
        "publish_ready": bool(gate.publish_ready),
        "gate": {"passed": sorted(gate.passed), "failed": sorted(gate.reasons()), "g4": gate.g4_mode},
        "engine_evidence": {"doc_id": doc.doc_id, "url": doc.url, "fetched_at": doc.fetched_at,
                            "positions": {k: fv.evidence.position() for k, fv in sorted(v.items())
                                          if fv.evidence is not None and k != "retail_price"}},
    }


def route(store: dict, doc, gate, *, now: datetime, found_by: str = "") -> tuple[Optional[str], str]:
    """(候補 ID | None, 振り分けの結果)。None は候補にしなかった（理由は 2 つ目）。"""
    if gate.drop:
        return None, gate.drop_reason or "dropped"
    cid = candidate_id(doc.url)
    if len((doc.text or "").strip()) < MIN_BODY_CHARS:
        st.upsert(store, cid, {"origin": ENGINE_ORIGIN, "source": f"engine:{doc.host}", "found_by": found_by,
                               "kind": "", "title": "", "official_url": doc.url, "publish_ready": False,
                               "missing_fields": ["application_start", "application_end"]},
                  status=st.REVIEW_REQUIRED, now=now, reasons=["unreadable_body"])
        return cid, st.REVIEW_REQUIRED
    if "event_type" not in gate.values:
        return None, "no_event_kind"
    reasons = ["engine_discovered"] + gate.reasons()
    st.upsert(store, cid, candidate_fields(doc, gate, found_by=found_by),
              status=st.ANNOUNCEMENT_REVIEW_REQUIRED, now=now, reasons=reasons)
    return cid, st.ANNOUNCEMENT_REVIEW_REQUIRED


def touch_seen(store: dict, cid: str, *, now: datetime) -> bool:
    """一覧に今も並んでいる（今回は取得し直していない）エンジンの候補の last_seen_on だけを進める（updated_at は進めない）。"""
    rec = store["candidates"].get(cid)
    if rec is None or rec.get("origin") != ENGINE_ORIGIN:
        return False
    rec["last_seen_on"] = now.strftime("%Y-%m-%d")
    return True
