"""品質ゲート G1〜G10（決まった規則だけ。LLM・推測を使わない）。

| # | 関門 | 落ちたとき |
| G1 | 根拠が自分で取得した一次情報（FetchedDoc がある・本文がある） | 候補にしない |
| G2 | ホストが公式（OFFICIAL_DOMAINS）か運営者の証拠のある店舗（STORE_PRIMARY_DOMAINS） | unofficial_source（publish_ready にしない） |
| G3 | 各値の quote が本文と完全一致・値が quote から導ける | その項目を null（evidence_mismatch） |
| G4 | ルールと LLM の日程・価格が一致（LLM が無ければ rules_only で通す） | 値を null（extractor_disagreement）・LLM だけの値は llm_only |
| G5 | 商品の照合が exact | product_unmapped |
| G6 | 状態（compute_lottery_status。抽出値ではない）が ENDED / UNKNOWN でない | ENDED は候補にしない・UNKNOWN は確認待ち |
| G7 | 公開日が 60 日以内・日程が前後 1 年以内 | stale_article / published_at_unknown / schedule_out_of_range |
| G8 | 既存（lotteries.json・手動 CSV・台帳）と重複しない | 候補にしない（duplicate_of） |
| G9 | 価格は単位（PACK/BOX/SET）と税込が quote にある | 価格を null（price_unit_unknown） |
| G10 | その実行で取得元が遮断（robots・403・429 等）されていない | 候補にしない |
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from src.discovery.engine.extract.evidence import verify_extraction
from src.discovery.engine.models import PRICE_FIELDS, SCHEDULE_FIELDS, FieldValue, GateResult

ARTICLE_MAX_AGE_DAYS = 60
SCHEDULE_MAX_DISTANCE_DAYS = 365
ALL_GATES = tuple(f"G{i}" for i in range(1, 11))


def _check_g4(rules, llm, res: GateResult) -> dict:
    """ルールと LLM の値をまとめる（日程・価格は一致を要求）。"""
    vals: dict = {}
    names = set(rules.fields) | (set(llm.fields) if llm else set())
    if llm is None:
        res.g4_mode = "rules_only"
    else:
        res.g4_mode = "agree"
    for name in sorted(names):
        r = rules.fields.get(name) or FieldValue()
        lv = (llm.fields.get(name) if llm else None) or FieldValue()
        if name in SCHEDULE_FIELDS or name in PRICE_FIELDS:
            if r.value is not None and lv.value is not None and r.value != lv.value:
                res.failed.append(f"G4:extractor_disagreement:{name}")
                res.private_notes.setdefault("disagreement", {})[name] = {"rules": r.value, "llm": lv.value}
                res.g4_mode = "disagree"
                continue
            if r.value is None and lv.value is not None:
                res.failed.append(f"G4:llm_only:{name}")
                vals[name] = lv
                continue
        vals[name] = r if r.value is not None else lv
    return vals


def evaluate(doc, rules, llm=None, *, now: datetime, registry: dict, existing=None,
             cut_hosts: Optional[dict] = None) -> GateResult:
    from src.discovery.engine.match import match_product
    from src.discovery.engine.urlpolicy import is_primary_host
    from src.tcg.lottery.schema import L_ENDED, L_UNKNOWN, compute_lottery_status
    from src.tcg.models import parse_dt
    res = GateResult()

    # G1: 自分で取得した一次情報
    if doc is None or not getattr(doc, "text", "") or rules is None or rules.doc_id != doc.doc_id:
        res.failed.append("G1:not_self_fetched")
        res.drop, res.drop_reason = True, "G1:not_self_fetched"
        return res
    res.passed.append("G1")

    # G10: この実行で遮断された取得元のものは使わない
    if doc.host in (cut_hosts or {}):
        res.failed.append("G10:source_blocked_in_run")
        res.drop, res.drop_reason = True, "G10:source_blocked_in_run"
        return res
    res.passed.append("G10")

    # G2: 公式・運営者の証拠のある店舗
    if is_primary_host(doc.url):
        res.passed.append("G2")
    else:
        res.failed.append("G2:unofficial_source")

    # G3: 根拠の機械的な検証（ルール・LLM とも。信用しない）
    bad = verify_extraction(rules, doc.text, doc_id=doc.doc_id)
    if llm is not None:
        bad_llm = verify_extraction(llm, doc.text, doc_id=doc.doc_id)
        bad.update({f"llm.{k}": v for k, v in bad_llm.items()})
    for k, why in sorted(bad.items()):
        res.failed.append(f"G3:evidence_mismatch:{k}")
        res.private_notes.setdefault("evidence_mismatch", {})[k] = why
    if not bad:
        res.passed.append("G3")

    # G4: ルールと LLM の一致
    vals = _check_g4(rules, llm, res)
    if not any(f.startswith("G4:") for f in res.failed):
        res.passed.append("G4")

    # G9: 価格の単位と税込（パック価格から BOX を作らない）
    price = vals.get("retail_price")
    if price is not None and price.value is not None:
        if price.extra.get("price_unit") in ("PACK", "BOX", "SET") and price.extra.get("tax") == "INCL":
            res.passed.append("G9")
        else:
            vals["retail_price"] = FieldValue()
            res.failed.append("G9:price_unit_unknown")
    else:
        res.passed.append("G9")
    res.values = {k: v for k, v in vals.items() if v is not None and v.value is not None}

    # G5: 商品の照合（exact だけ）
    name = res.values.get("product_name_raw")
    code = res.values.get("product_code")
    tcg = res.values.get("tcg")
    mt = match_product(name.value if name else None, code.value if code else None, tcg.value if tcg else None,
                       registry or {})
    res.private_notes["product_match"] = mt
    if mt.get("product_match") == "exact":
        res.passed.append("G5")
    else:
        res.failed.append("G5:product_unmapped")

    # G6: 状態は日程と現在時刻から計算する（抽出値として持たない）
    sched = {k: res.values[k].value for k in SCHEDULE_FIELDS if k in res.values}
    res.lottery_status = compute_lottery_status(sched, now)
    if res.lottery_status == L_ENDED:
        res.failed.append("G6:ended")
        res.drop, res.drop_reason = True, "G6:ended"
    elif res.lottery_status == L_UNKNOWN:
        res.failed.append("G6:status_unknown")
    else:
        res.passed.append("G6")

    # G7: 記事の古さ・日程の遠さ
    g7 = []
    pub = parse_dt(rules.base_published_at or (llm.base_published_at if llm else None))
    if pub is None:
        g7.append("G7:published_at_unknown")
    elif (now - pub) > timedelta(days=ARTICLE_MAX_AGE_DAYS):
        g7.append("G7:stale_article")
    for v in sched.values():
        d = parse_dt(v)
        if d is not None and abs((d - now).days) > SCHEDULE_MAX_DISTANCE_DAYS:
            g7.append("G7:schedule_out_of_range")
            break
    if g7:
        res.failed.extend(g7)
    else:
        res.passed.append("G7")

    # G8: 既存と重複しない
    dup = existing.find(doc.url) if existing is not None else None
    if dup:
        res.failed.append(f"G8:duplicate_of:{dup}")
        if not res.drop:
            res.drop, res.drop_reason = True, f"G8:duplicate_of:{dup}"
    else:
        res.passed.append("G8")

    has_event = "event_type" in res.values
    res.publish_ready = (not res.drop and has_event and not res.failed
                         and all(g in res.passed for g in ALL_GATES))
    return res
