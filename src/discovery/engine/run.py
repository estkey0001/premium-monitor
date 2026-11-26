"""発見のエンジンの実行（frontier → 選別 → 取得 → 抽出 → 照合 → 重複 → ゲート → 台帳）。

既定は dry-run（何も書かない）。apply=True のときだけ:
- 公開の台帳 exports/discovery/event_candidates.json（store.upsert。quote・価格は書かない）
- 非公開 .private/discovery/（leads.json・frontier_state.json・engine_run.json・docs/。.gitignore 済み）
戻り値は件数の集計（標準出力に出すのは件数だけにする）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.discovery import store as st
from src.discovery.engine import models as m
from src.discovery.engine.dedupe import ENGINE_ORIGIN, build_index
from src.discovery.engine.extract.llm import NullExtractor
from src.discovery.engine.extract.rules import RulesExtractor
from src.discovery.engine.fetch import (
    FRONTIER_MAX_PER_HOST, FRONTIER_MAX_TOTAL, PAGE_MAX_PER_HOST, PAGE_MAX_TOTAL, DocStore, Fetcher,
)
from src.discovery.engine.frontier import discover, load_config
from src.discovery.engine.gate import evaluate
from src.discovery.engine.match import load_registry
from src.discovery.engine.route import candidate_id, route, touch_seen
from src.discovery.engine.search.null import NullSearchProvider
from src.discovery.engine.urlpolicy import UrlPolicy

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRIVATE_DIR = PROJECT_ROOT / ".private" / "discovery"
LEDGER_DIR = PROJECT_ROOT / "exports" / "discovery"


def _read_json(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def run_engine(*, now: datetime, fetch=None, apply: bool = False, config_path: Optional[Path] = None,
               private_dir: Path = PRIVATE_DIR, ledger_dir: Path = LEDGER_DIR, registry: Optional[dict] = None,
               existing=None, extractor=None, search_provider=None, bootstrap: bool = False,
               policy: Optional[UrlPolicy] = None,
               frontier_budget: tuple[int, int] = (FRONTIER_MAX_TOTAL, FRONTIER_MAX_PER_HOST),
               page_budget: tuple[int, int] = (PAGE_MAX_TOTAL, PAGE_MAX_PER_HOST)) -> dict:
    from src.collectors.polite import ShopCutoff
    private_dir, ledger_dir = Path(private_dir), Path(ledger_dir)
    extractor = extractor or NullExtractor()
    search_provider = search_provider or NullSearchProvider()
    policy = policy or UrlPolicy()
    sources, skipped = load_config(config_path)
    state = _read_json(private_dir / "frontier_state.json")
    cutoff = ShopCutoff()                                   # 取得元（ホスト）単位の打ち切りを frontier と本文で共有
    f_fetch = Fetcher(fetch, max_total=frontier_budget[0], max_per_host=frontier_budget[1], cutoff=cutoff)
    p_fetch = Fetcher(fetch, max_total=page_budget[0], max_per_host=page_budget[1], cutoff=cutoff)

    fr = discover(sources, state, f_fetch, now=now, bootstrap=bootstrap, policy=policy)
    fr.skipped = skipped
    # 検索 API（今回は Null。将来も URL とクエリ ID だけを受け取る）
    search_hits = search_provider.search("", query_id="", limit=0)

    ev_path = ledger_dir / st.EVENT_FILE
    evs = st.load(ev_path)
    existing = existing if existing is not None else build_index(event_store=evs)
    registry = registry if registry is not None else load_registry()
    docs = DocStore(private_dir / "docs")
    rules = RulesExtractor()

    report = {"sources": {"used": len(sources), "skipped": len(skipped), "failed": len(fr.failed),
                          "baseline_only": len(fr.baseline)},
              "search": {"provider": getattr(search_provider, "name", ""), "hits": len(search_hits)},
              "leads": len(fr.leads), "url_decision": {}, "fetch_state": {}, "routed": {}, "dropped": {},
              "publish_ready": 0, "unchanged_body": 0, "applied": bool(apply)}
    run_rows: list[dict] = []
    seen_ids: set[str] = set()
    fetched: list = []
    for lead in fr.leads:
        dec, why = policy.decide(lead.url)
        lead.url_decision, lead.decision_reason = dec, (lead.decision_reason + ";" + why).strip(";")
        report["url_decision"][dec] = report["url_decision"].get(dec, 0) + 1
        if dec != m.ACCEPT_PRIMARY:
            lead.fetch_state = m.NOT_FETCHED                 # 拒否・手がかりだけ: 取得しない
            continue
        body, reason, fstate = p_fetch.get(lead.url)
        lead.fetch_state, lead.fetch_reason = fstate, reason
        report["fetch_state"][fstate] = report["fetch_state"].get(fstate, 0) + 1
        if body is None:
            continue
        doc = docs.make_doc(lead.url, body, now=now, published_hint=lead.lastmod)
        if docs.is_known(doc):
            report["unchanged_body"] += 1                   # 本文が前回と同じ: 抽出し直さない・時刻を進めない
            if touch_seen(evs, candidate_id(doc.url), now=now):
                seen_ids.add(candidate_id(doc.url))
            continue
        fetched.append((lead, doc))

    # G10 は全部の取得が終わってから判定する（後で遮断された取得元の、先に取れたページも使わない）
    cut_final = p_fetch.cut_hosts()
    for lead, doc in fetched:
        r_ext = rules.extract(doc)
        l_ext = extractor.extract(doc)
        gate = evaluate(doc, r_ext, l_ext, now=now, registry=registry, existing=existing, cut_hosts=cut_final)
        cid, outcome = route(evs, doc, gate, now=now, found_by=lead.found_by)
        if cid:
            seen_ids.add(cid)
            report["routed"][outcome] = report["routed"].get(outcome, 0) + 1
            report["publish_ready"] += int(gate.publish_ready)
        else:
            key = ":".join(outcome.split(":")[:2])
            report["dropped"][key] = report["dropped"].get(key, 0) + 1
        if apply and doc.host not in cut_final:
            docs.save(doc)
        run_rows.append({"lead_id": lead.lead_id, "doc": doc.index_entry(), "rules": r_ext.to_dict(),
                         "llm": l_ext.to_dict() if l_ext else None, "candidate_id": cid, "outcome": outcome,
                         "gate": {"passed": gate.passed, "failed": gate.failed, "status": gate.lottery_status,
                                  "publish_ready": gate.publish_ready, "notes": gate.private_notes}})

    # 遮断された取得元（G10）のこの実行の候補は台帳から外したまま（上で drop）。一覧に今も並ぶ候補は見えている扱い
    cut = set(f_fetch.cut_hosts()) | set(p_fetch.cut_hosts())
    for sid, urls in fr.listed.items():
        for key in urls:
            cid = candidate_id(key)
            if touch_seen(evs, cid, now=now):
                seen_ids.add(cid)
    ok_hosts = {h for h in fr.ok_hosts if h not in cut and ("www." + h) not in cut}

    def _scope(rec: dict) -> bool:
        if rec.get("origin") != ENGINE_ORIGIN:
            return False
        h = str(rec.get("source") or "").split(":", 1)[-1]
        return (h[4:] if h.startswith("www.") else h) in ok_hosts
    aged = st.age_out(evs, seen_ids, now=now, scope=_scope) if ok_hosts else {"stale": 0, "dropped": 0}
    report["aged_out"] = aged
    report["cut_hosts"] = len(cut)

    # 取得枠の超過・失敗・遮断・G10 で読めなかった Lead は、frontier の既知から外す（次の実行でもう一度 Lead になる。黙って取りこぼさない）
    from src.discovery.engine.urlpolicy import host_of
    from src.tcg.lottery.pipeline import normalize_url as _norm
    retry = {_norm(ld.url) for ld in fr.leads
             if ld.url_decision == m.ACCEPT_PRIMARY and (ld.fetch_state != m.FETCHED or host_of(ld.url) in cut_final)}
    for src_state in (fr.state.get("sources") or {}).values():
        for k in retry & set((src_state.get("urls") or {})):
            src_state["urls"].pop(k, None)
    report["retry_next_run"] = len(retry)

    if apply:
        from src.utils.atomic_write import write_json_atomic
        st.save(ev_path, evs)
        private_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(private_dir / "frontier_state.json", fr.state)
        write_json_atomic(private_dir / "leads.json", {"generated_at": now.isoformat(timespec="seconds"),
                                                       "leads": [ld.to_dict() for ld in fr.leads]})
        write_json_atomic(private_dir / "engine_run.json", {
            "generated_at": now.isoformat(timespec="seconds"), "report": report, "rows": run_rows,
            "frontier_failed": fr.failed, "frontier_skipped": fr.skipped, "cut_hosts": {
                **f_fetch.cut_hosts(), **p_fetch.cut_hosts()}})
        docs.flush()
    report["_rows"] = run_rows                               # 呼び出し側（テスト）用。CLI では出さない
    report["_leads"] = [ld.to_dict() for ld in fr.leads]
    return report
