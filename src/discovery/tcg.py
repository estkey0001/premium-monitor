"""TCG の新商品・新しいイベントの発見の候補（Phase 27）。読むだけ（新しい取得はしない）・正本に登録しない。

入力は TCG の収集の生成物（exports/tcg/）だけ:
- 抽選の告知（lotteries.json の announcements）: 日程が本文に無い・本体が読めない（PCO 403 など）告知
- 一覧のタイトルだけで見つけた販売の告知（lottery_sources.json の discovered_titles）: 予約・先着・再販・
  本文を読む上限で読まなかった抽選
- 正式な抽選のイベント（lotteries.json の items。日程がある）・発売の予定（latest.json の events の GENERAL_SALE）
- 公式の商品の一覧（pokemon_registry.json・ONE PIECE の商品の一覧のイベント）

日程が無い告知は捨てずに ANNOUNCEMENT_REVIEW_REQUIRED の候補にする（日程は推測しない・画像の文字を読まない・
受付中 = OPEN にしない）。発売の予定は RELEASE（抽選にしない）。商品との結び付けは商品コード（【ST-38】・公式の
商品ページのコード）だけ（名前だけでは結び付けない）。TCG は利益・今すぐ行動・通知に接続しない。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from src.discovery import store as st

KINDS = ("LOTTERY", "PREORDER", "FIRST_COME", "RESTOCK", "RELEASE")
_OP_CODE = re.compile(r"[【\[]([A-Z]{2,4}-\d{2,3})[】\]]")
_PKM_CODE = re.compile(r"pokemon-card\.com/ex/([a-z0-9]{1,8})/?$")


def _load(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _norm_url(url: str) -> str:
    from src.tcg.lottery.pipeline import normalize_url
    return normalize_url(url or "")


def product_codes(registry: dict | None, events: list) -> dict:
    """公式の商品コード → 商品（ポケモン: 公式の商品ページ /ex/<コード>/・ONE PIECE: 商品名の【XX-NN】）。"""
    out = {}
    for p in (registry or {}).get("products") or []:
        m = _PKM_CODE.search(str(p.get("official_url") or "").rstrip("/") + "/") if isinstance(p, dict) else None
        if m:
            out[m.group(1).upper()] = {"tcg": "POKEMON", "name": p.get("name"), "product_id": p.get("product_id")}
    for e in events or []:
        if isinstance(e, dict) and e.get("store") == "ONEPIECE_CARD_OFFICIAL":
            m = _OP_CODE.search(str(e.get("product_name") or ""))
            if m:
                out[m.group(1)] = {"tcg": "ONE_PIECE", "name": e.get("product_name"), "product_id": e.get("product_id")}
    return out


def map_product(text: str, codes: dict) -> tuple[str, str]:
    """告知のタイトルを商品に結び付ける（商品コードが書かれているときだけ。名前だけでは結び付けない）。"""
    for m in _OP_CODE.finditer(text or ""):
        if m.group(1) in codes:
            return m.group(1), "code"
    return "", "unmapped"


def _event_kind(ev: dict) -> str:
    """抽選の系統のイベントの種類。知らない種類は空（抽選として扱わない。監査 L-4）。"""
    t = str(ev.get("event_type") or "")
    return {"LOTTERY": "LOTTERY", "PURCHASE_RIGHT": "LOTTERY", "PREORDER": "PREORDER",
            "FIRST_COME": "FIRST_COME", "RESTOCK": "RESTOCK"}.get(t, "")


INPUT_MAX_AGE_HOURS = 3              # 今回の実行の TCG の収集の生成物とみなす古さの上限（同じ実行の直前の手順の出力だけ）


def _fresh(d, now: datetime) -> bool:
    """入力が今回の実行の生成物か（generated_at が now から INPUT_MAX_AGE_HOURS 以内）。読めなければ古い扱い。"""
    from src.tcg.models import parse_dt
    g = parse_dt(str((d or {}).get("generated_at") or "")) if isinstance(d, dict) else None
    return g is not None and 0 <= (now - g).total_seconds() <= INPUT_MAX_AGE_HOURS * 3600


def run(tcg_dir: Path, out_dir: Path, *, now: datetime) -> dict:
    """TCG の生成物から、イベントの候補（event_candidates.json）と商品の候補（product_candidates.json）を更新する。

    入力が今回の実行の生成物でなければ（TCG の収集が失敗して前回の生成物が残った）、候補を見つけ直したことにしない
    （last_seen_on を進めない・STALE にもしない。鮮度を偽装しない。監査 M-2）。
    """
    tcg_dir, out_dir = Path(tcg_dir), Path(out_dir)
    lots = _load(tcg_dir / "lotteries.json")
    srcs = _load(tcg_dir / "lottery_sources.json")
    reg = _load(tcg_dir / "pokemon_registry.json")
    latest = _load(tcg_dir / "latest.json")
    stale_inputs = [n for n, d in (("lotteries", lots), ("lottery_sources", srcs), ("pokemon_registry", reg),
                                   ("latest", latest)) if d is not None and not _fresh(d, now)]
    if stale_inputs:
        lots = srcs = reg = latest = None                    # 古い入力では何も見つけ直さない
    events = (latest or {}).get("events") or []
    codes = product_codes(reg, events)
    ev_path = out_dir / st.EVENT_FILE
    evs = st.load(ev_path)
    seen: set[str] = set()
    report = {"inputs": {"lotteries": lots is not None, "sources": srcs is not None, "registry": reg is not None,
                         "latest": latest is not None}, "inputs_stale": stale_inputs,
              "review_required": 0, "matched_events": 0, "release": 0, "by_kind": {k: 0 for k in KINDS}}
    dated_urls = set()
    # 正式な抽選のイベント（日程がある）: 発見できて正式なイベントになったもの
    pending_ann = []
    for it in (lots or {}).get("items") or []:
        if not isinstance(it, dict) or not it.get("lottery_id"):
            continue
        kind = _event_kind(it)
        if not kind:
            continue
        if it.get("announcement_only") or not any(it.get(k) for k in (
                "application_start", "application_end", "application_start_date", "application_end_date")):
            # 日程の無い仮のイベント（告知）: 正式なイベントにしない・告知として人の確認の候補にする（レビュー H-1）
            pending_ann.append(it)
            continue
        for u in [it.get("source_url")] + list(it.get("source_urls") or []):
            if u:
                dated_urls.add(_norm_url(u))
        cid = st.stable_id("tcg-event", it["lottery_id"])
        code, how = map_product(str(it.get("product_name") or ""), codes)
        st.upsert(evs, cid, {"source": str(it.get("retailer") or ""), "kind": kind, "tcg": it.get("tcg"),
                             "title": str(it.get("product_name") or ""),
                             "official_url": str(it.get("source_url") or ""),
                             "product_code": code, "product_mapping": how,
                             "application_start": it.get("application_start") or it.get("application_start_date"),
                             "application_end": it.get("application_end") or it.get("application_end_date"),
                             "event_status": str(it.get("status") or ""), "missing_fields": []},
                  status=st.MATCHED_EVENT, now=now)
        seen.add(cid)
        report["matched_events"] += 1
        report["by_kind"][kind] += 1

    def review(source: str, kind: str, title: str, url: str, published: str | None, reason: str, tcg=None):
        if not url:
            return
        cid = st.stable_id("tcg-ann", source, _norm_url(url), kind)
        if _norm_url(url) in dated_urls:
            return                                        # 同じ告知が日程つきの正式なイベントになっている
        code, how = map_product(title, codes)
        first_time = cid not in seen                         # 同じ告知が2つの経路から来ても1回だけ数える（レビュー L-4）
        st.upsert(evs, cid, {"source": source, "kind": kind, "tcg": tcg, "title": title, "official_url": url,
                             "published_at": published or "", "product_code": code, "product_mapping": how,
                             "application_start": None, "application_end": None, "event_status": "",
                             "missing_fields": ["application_start", "application_end"]},
                  status=st.ANNOUNCEMENT_REVIEW_REQUIRED, now=now, reasons=[reason])
        seen.add(cid)
        report["review_required"] += first_time
        report["by_kind"][kind] += first_time

    for it in pending_ann:
        review(str(it.get("retailer") or ""), _event_kind(it), str(it.get("product_name") or ""),
               str(it.get("source_url") or ""), it.get("published_at"), "schedule_not_available", it.get("tcg"))
    # 日程の無い告知（本文に日程が無い・本体が読めない）: 捨てずに人の確認の候補にする（14日を過ぎても残す）
    for an in (lots or {}).get("announcements") or []:
        if isinstance(an, dict):
            review(str(an.get("retailer") or ""), "LOTTERY", str(an.get("title") or ""),
                   str(an.get("source_url") or ""), an.get("published_at"), "schedule_not_available", an.get("tcg"))
    # 一覧のタイトルだけで見つけた販売の告知（予約・先着・再販・読む上限で読まなかった抽選）
    for s in (srcs or {}).get("sources") or []:
        for d in (s.get("discovered_titles") or []) if isinstance(s, dict) else []:
            if isinstance(d, dict) and d.get("kind") in KINDS:
                review(str(s.get("source_id") or ""), d["kind"], str(d.get("title") or ""), str(d.get("url") or ""),
                       d.get("published_at"), str(d.get("reason") or "title_only_not_fetched"),
                       (s.get("brand") or [None])[0])
    # 発売の予定（RELEASE。抽選にしない）
    for e in events:
        if isinstance(e, dict) and e.get("event_type") == "GENERAL_SALE" and e.get("status") == "COMING_SOON":
            key = str(e.get("product_id") or e.get("product_name") or "")
            cid = st.stable_id("tcg-release", e.get("store"), key)   # 発売日の変更で重複させない（レビュー L-6）
            code = (_OP_CODE.search(str(e.get("product_name") or "")) or [None, ""])[1] if e.get(
                "store") == "ONEPIECE_CARD_OFFICIAL" else ""
            st.upsert(evs, cid, {"source": str(e.get("store") or ""), "kind": "RELEASE", "tcg": e.get("tcg"),
                                 "title": str(e.get("product_name") or ""),
                                 "official_url": str(e.get("source_url") or e.get("url") or ""),
                                 "product_code": code or "", "product_mapping": "code" if code else "unmapped",
                                 "release_date": str(e.get("sale_start") or e.get("release_date") or ""),
                                 "application_start": None, "application_end": None, "event_status": "COMING_SOON",
                                 "missing_fields": []},
                      status=st.MATCHED_EVENT, now=now)
            seen.add(cid)
            report["release"] += 1
            report["by_kind"]["RELEASE"] += 1
    # 入力を読めた実行だけ、見つからなくなった候補を STALE にする（読めない実行で消したことにしない）。収集が失敗した実行・
    # 読めなかった取得元の候補は対象にしない（空の生成物で「見えなくなった」と判定しない。レビュー M-3）
    # 一覧を読めなかった取得元だけを外す（本文だけが 403 でも一覧を読めた取得元は外さない。レビュー L-2）
    failing = {str(r.get("source_id") or "") for r in (srcs or {}).get("sources") or [] if isinstance(r, dict)
               and (r.get("unreachable") or r.get("health") == "FAILED" or r.get("reachable") is False)}
    # 抽選の収集そのものが失敗した日（取得元の行が1件も無い空の出力）も STALE にしない（レビュー M-3 の残り）
    if lots is not None and srcs is not None and latest is not None and not (latest or {}).get("error") \
            and (srcs or {}).get("sources"):
        st.age_out(evs, seen, now=now, scope=lambda r: str(r.get("source") or "") not in failing)
    st.save(ev_path, evs)

    # TCG の商品の候補（TCG の正本は無いので、公式の一覧の商品はすべて人の確認の候補。商品コードが無ければ要確認）
    pc_path = out_dir / st.PRODUCT_FILE
    pcs = st.load(pc_path)
    pseen: set[str] = set()
    n_new = 0
    for p in (reg or {}).get("products") or []:
        if not isinstance(p, dict):
            continue
        m = _PKM_CODE.search(str(p.get("official_url") or "").rstrip("/") + "/")
        code = m.group(1).upper() if m else ""
        cid = st.stable_id("tcg-pokemon", code) if code else st.stable_id("tcg-pokemon-nocode", p.get("product_id"))
        st.upsert(pcs, cid, {"source": "pokemon_card_official", "brand": "Pokemon", "genre": "tcg",
                             "product_name": str(p.get("name") or ""), "model_number": code, "sku": "", "jan": "",
                             "capacity": "", "edition": str(p.get("api_product_type") or ""), "colors": [],
                             "official_url": str(p.get("official_url") or ""),
                             "official_price": p.get("retail_price"), "release_date": str(p.get("release_date") or ""),
                             "match_to_existing": ""},
                  status=st.PENDING_REVIEW if code else st.REVIEW_REQUIRED, now=now,
                  reasons=["tcg_not_in_canonical"] + ([] if code else ["no_product_code"]))
        pseen.add(cid)
        n_new += 1
    for e in events:
        if not (isinstance(e, dict) and e.get("store") == "ONEPIECE_CARD_OFFICIAL"):
            continue
        m = _OP_CODE.search(str(e.get("product_name") or ""))
        if not m:
            continue
        cid = st.stable_id("tcg-onepiece", m.group(1))
        st.upsert(pcs, cid, {"source": "onepiece_card_official", "brand": "ONE PIECE CARD GAME", "genre": "tcg",
                             "product_name": str(e.get("product_name") or ""), "model_number": m.group(1), "sku": "",
                             "jan": "", "capacity": "", "edition": "", "colors": [],
                             "official_url": str(e.get("source_url") or ""), "official_price": e.get("price"),
                             "release_date": str(e.get("sale_start") or ""), "match_to_existing": ""},
                  status=st.PENDING_REVIEW, now=now, reasons=["tcg_not_in_canonical"])
        pseen.add(cid)
        n_new += 1
    if reg is not None and latest is not None and not (latest or {}).get("error"):
        has_pkm = bool((reg or {}).get("products"))
        st.age_out(pcs, pseen, now=now, scope=lambda r: r.get("genre") == "tcg"
                   and (has_pkm or r.get("source") != "pokemon_card_official"))
    st.save(pc_path, pcs)
    report["tcg_products"] = n_new
    cov = (srcs or {}).get("coverage") or {}
    rows = (srcs or {}).get("sources") or []
    report["sources"] = {
        "configured": cov.get("configured_sources"), "implemented": cov.get("implemented_collectors"),
        "unimplemented": cov.get("not_implemented_sources"), "blocked": cov.get("blocked_sources"),
        "robots_unreachable": sum(1 for r in rows if isinstance(r, dict) and r.get("robots") == "robots_unreachable"),
        "unreachable": cov.get("unreachable_sources"),
        "table": [{k: r.get(k) for k in ("source_id", "retailer", "adapter", "state", "health", "blocked", "robots",
                                         "unreachable")} for r in rows if isinstance(r, dict)]}
    return report
