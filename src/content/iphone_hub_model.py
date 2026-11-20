"""iPhone Product Hub（docs/iphone-buyback.html）の整形ロジック（純関数）。

表示層だけ。collector・利益計算・鮮度・BUY/WAIT の計算は作り直さない（comp の値をそのまま読む）。
- 入力は comp（iphone_buyback_comparison.json）・history（iphone_buyback_history.json）・candidates（product_candidates.json）。
  history / candidates が None（読めない・渡されない）なら、その欄は「データ無し」にする（推測で埋めない）。
- 前回比は「同じ店・同じ SKU の組」だけで比べる（店数が違う日を同列に比べない。diff_snapshots と同じ方針）。
- シグナルは weekly_import.diff_snapshots を連続スナップショットに再適用する（新しいロジックは作らない・REGISTERED のみ）。
"""
from __future__ import annotations

import re

CAP_ORDER = {"128GB": 128, "256GB": 256, "512GB": 512, "1TB": 1024, "2TB": 2048}
_SKU_RE = re.compile(r"^(?P<model>.+?)\s+(?P<cap>\d+\s*(?:GB|TB))$", re.I)

NO_HISTORY = "履歴データ無し"


def split_sku(sku) -> tuple[str, str]:
    """「iPhone Duo 256GB」→（「iPhone Duo」,「256GB」）。容量が読めなければ（全体, ""）。"""
    m = _SKU_RE.match(str(sku or "").strip())
    if not m:
        return str(sku or "").strip(), ""
    return m.group("model").strip(), m.group("cap").replace(" ", "").upper()


def cap_key(cap: str) -> int:
    if cap in CAP_ORDER:
        return CAP_ORDER[cap]
    m = re.match(r"(\d+)(GB|TB)", cap or "")
    return int(m.group(1)) * (1024 if m.group(2) == "TB" else 1) if m else 10**9


def group_models(skus: list) -> list[dict]:
    """モデルごとにまとめる。正本に登録済みの SKU を含むモデル（primary）を先に、全部が DISCOVERED のモデルを後に（参考）。"""
    order: list[str] = []
    by: dict[str, list] = {}
    for s in skus or []:
        model, _ = split_sku(s.get("sku"))
        if model not in by:
            by[model] = []
            order.append(model)
        by[model].append(s)
    out = []
    for m in order:
        items = sorted(by[m], key=lambda s: cap_key(split_sku(s.get("sku"))[1]))
        out.append({"model": m, "skus": items, "primary": any(s.get("identity") == "REGISTERED" for s in items)})
    return sorted(out, key=lambda g: not g["primary"])          # sorted は安定。primary の中の順序は入力順


# ---- 履歴（スナップショット列） ----
def _snaps(history) -> list[dict] | None:
    if not isinstance(history, dict) or not isinstance(history.get("snapshots"), list):
        return None
    out = []
    for s in history["snapshots"]:
        if isinstance(s, dict) and isinstance(s.get("rows"), list) and s.get("date"):
            out.append(s)
    return sorted(out, key=lambda s: str(s["date"]))


def build_timeline(comp: dict, history) -> dict | None:
    """過去のスナップショット + 今回（comp から snapshot_rows で作る）。history が None なら None。

    今回と同じ日付の履歴は、今回の comp から作り直したもので置き換える（update_history と同じ扱い）。
    """
    snaps = _snaps(history)
    if snaps is None:
        return None
    rd = str(comp.get("research_date") or "")
    past = [s for s in snaps if str(s["date"]) != rd]
    cur_rows = None
    try:
        from src.research.weekly_import import snapshot_rows
        cur_rows = snapshot_rows(comp)
    except Exception:  # noqa: BLE001 — 形の違う comp でページ全体を壊さない
        same = [s for s in snaps if str(s["date"]) == rd]
        cur_rows = same[-1]["rows"] if same else None
    seq = [{"date": str(s["date"]), "rows": s["rows"], "apple": s.get("apple") or {}} for s in past]
    if cur_rows is not None:
        seq.append({"date": rd, "rows": cur_rows,
                    "apple": next((s.get("apple") or {} for s in snaps if str(s["date"]) == rd), {})})
    return {"snaps": seq, "current_date": rd if cur_rows is not None else None}


def _best(rows: list, sku: str):
    c = [r for r in rows if r.get("sku") == sku and isinstance(r.get("price"), int)]
    return max(c, key=lambda r: r["price"]) if c else None


def sku_trend(timeline: dict | None, sku: str) -> list[dict]:
    """スナップショットごとの {date, best_price, best_shop, shops, net}。net は net のある行（最高買取の行）の値。"""
    if not timeline:
        return []
    out = []
    for sn in timeline["snaps"]:
        rows = [r for r in sn["rows"] if r.get("sku") == sku and isinstance(r.get("price"), int)]
        if not rows:
            out.append({"date": sn["date"], "best_price": None, "best_shop": None, "shops": 0, "net": None})
            continue
        b = max(rows, key=lambda r: r["price"])
        nets = [r["net"] for r in rows if isinstance(r.get("net"), int)]
        out.append({"date": sn["date"], "best_price": b["price"], "best_shop": b.get("shop"), "shops": len(rows),
                    "net": nets[0] if nets else None})
    return out


def prev_compare(timeline: dict | None, sku: str) -> dict:
    """同じ店・同じ SKU の組だけで、今回と「共通の店がある直近の過去」を比べる。比べられなければ NO_DATA と理由。"""
    if timeline is None:
        return {"status": "NO_DATA", "reason": NO_HISTORY}
    if not timeline.get("current_date"):
        return {"status": "NO_DATA", "reason": "今回の記録を作れない"}
    snaps = timeline["snaps"]
    cur, past = snaps[-1], snaps[:-1]
    if not past:
        return {"status": "NO_DATA", "reason": "前回の記録なし（初回）"}
    cur_by = {r["key"]: r for r in cur["rows"] if r.get("sku") == sku and isinstance(r.get("price"), int) and r.get("key")}
    if not cur_by:
        return {"status": "NO_DATA", "reason": "今回は比較できる価格なし"}
    for sn in reversed(past):
        prev_by = {r["key"]: r for r in sn["rows"] if r.get("sku") == sku and isinstance(r.get("price"), int) and r.get("key")}
        common = sorted(set(prev_by) & set(cur_by))
        if not common:
            continue
        p0 = max(prev_by[k]["price"] for k in common)
        p1 = max(cur_by[k]["price"] for k in common)
        return {"status": "OK", "prev_date": sn["date"], "common": len(common), "prev_shops": len(prev_by), "cur_shops": len(cur_by),
                "prev_best": p0, "cur_best": p1, "delta": p1 - p0}
    return {"status": "NO_DATA", "reason": "同じ店の過去の記録なし（店が違う日は比べない）"}


def _restrict_common(prev_rows: list, cur_rows: list) -> tuple[list, list]:
    pk = {(r.get("sku"), r.get("key")) for r in prev_rows}
    ck = {(r.get("sku"), r.get("key")) for r in cur_rows}
    both = pk & ck
    return ([r for r in prev_rows if (r.get("sku"), r.get("key")) in both],
            [r for r in cur_rows if (r.get("sku"), r.get("key")) in both])


def signals(comp: dict, timeline: dict | None) -> dict:
    """{"groups": [{"date", "events"}...（新しい順）], "history_note": str|None}。

    今回分は comp["events"]（update_history が diff_snapshots と decision_events で作った）。
    過去分は diff_snapshots を連続スナップショット（同じ店・同じ SKU の組だけ）に再適用する。
    """
    groups = []
    rd = str(comp.get("research_date") or "")
    cur_events = list(comp.get("events") or [])
    if cur_events:
        groups.append({"date": rd, "events": cur_events})
    note = None
    if timeline is None:
        note = "過去分は履歴データ無し"
    else:
        from src.research.weekly_import import diff_snapshots
        snaps = timeline["snaps"]
        past = snaps[:-1] if timeline.get("current_date") else snaps
        for i in range(len(past) - 1, 0, -1):
            a, b = _restrict_common(past[i - 1]["rows"], past[i]["rows"])
            ev = diff_snapshots(a, b) if a and b else []
            if ev:
                groups.append({"date": past[i]["date"], "events": ev})
    return {"groups": groups, "history_note": note}


def apple_trend(history, sku: str, comp: dict | None = None) -> dict:
    """Apple 公式価格の記録（履歴スナップショットの apple と今回の comp）。{"status": NO_DATA|ONE|MANY, "points": [(date, price)]}"""
    snaps = _snaps(history)
    if snaps is None:
        return {"status": "NO_DATA", "points": []}
    pts = {}
    for s in snaps:
        p = (s.get("apple") or {}).get(sku, {}).get("price") if isinstance(s.get("apple"), dict) else None
        if isinstance(p, int):
            pts[str(s["date"])] = p
    if comp:
        cur = next((x.get("apple_price") for x in comp.get("skus") or [] if x.get("sku") == sku), None)
        if isinstance(cur, int) and comp.get("research_date"):
            pts[str(comp["research_date"])] = cur
    ordered = sorted(pts.items())
    return {"status": "NO_DATA" if not ordered else "ONE" if len(ordered) == 1 else "MANY", "points": ordered}


# ---- 今の結論（5 つの問い） ----
def rank_rows(s: dict) -> dict:
    """買取店の表の順位。eligible の行だけ 1 位から（外れ値の確認待ちの行・重複行は数えない）。{id(row): 順位}"""
    unc = s.get("highest_unconfirmed") or {}
    cand = [r for r in s.get("rows") or []
            if r.get("eligible") and not r.get("duplicate_row") and isinstance(r.get("executable_price"), int)
            and not (unc and r.get("shop") == unc.get("shop") and r.get("executable_price") == unc.get("price"))]
    cand.sort(key=lambda r: -r["executable_price"])
    return {id(r): i + 1 for i, r in enumerate(cand)}


def unavailable_reason(s: dict) -> str:
    """実行可能価格が無い理由（推測の価格・売り先は出さない）。"""
    unc, hl = s.get("highest_unconfirmed"), s.get("highest_listed")
    if unc:
        return "最高値は確認待ち（外れ値・比較できる店が少ない）で、売り先として案内しない"
    if hl and not hl.get("executable"):
        return "掲載の最高値は更新が古い（STALE）などで、売り先として案内しない"
    if not s.get("source_count"):
        return "データ無し（買取価格を取得できていない）"
    return "確定できる実行可能価格が無い"


def sku_answer(s: dict) -> dict:
    """1 SKU の 5 つの問いへの答え。答えが出せない項目は None と理由（推測しない）。"""
    hx = s.get("highest_executable")
    model, cap = split_sku(s.get("sku"))
    net = s.get("net_profit")
    out = {"sku": s.get("sku"), "capacity": cap, "reference": s.get("identity") != "REGISTERED",
           "sell_shop": hx.get("shop") if hx else None, "sell_price": hx.get("price") if hx else None,
           "net": net if hx else None, "roi": s.get("roi_pct") if hx else None,
           "decision": s.get("opportunity_status"), "decision_reason": s.get("opportunity_reason"),
           "profit_status": s.get("profit_status")}
    out["sell_reason"] = None if hx else unavailable_reason(s)
    out["net_reason"] = None if (hx and net is not None) else ("データ無し（実行可能な買取価格が無いため計算しない）" if not hx
                                                             else "データ無し（利益を計算できない）")
    return out


def model_conclusion(skus: list) -> dict:
    """モデルの見出しの答え: どの容量を買うか。正本に登録済みで、実行可能価格と純利益がある SKU の中で純利益が最大のもの。

    純利益が 0 以下なら「黒字の容量なし」。登録済みが無い・価格が無いときは「確認待ち」（参考の SKU から結論を出さない）。
    """
    reg = [s for s in skus if s.get("identity") == "REGISTERED"]
    if not reg:
        return {"status": "REFERENCE_ONLY", "reason": "正本に未登録のため結論を出さない（参考表示のみ）"}
    cand = [s for s in reg if s.get("highest_executable") and isinstance(s.get("net_profit"), int)]
    if not cand:
        return {"status": "WAITING", "reason": "確定できる実行可能価格がある容量がない（確認待ち）"}
    best = max(cand, key=lambda s: s["net_profit"])
    a = sku_answer(best)
    if best["net_profit"] > 0:
        buy_ok = (str(best.get("opportunity_status") or "").upper() == "BUY"
                  and (best.get("apple_availability") or {}).get("status") == "BUYABLE")
        if not buy_ok:                                     # 黒字でも、週次の判定が BUY でない（ROI が条件未満・Apple で購入可と確認できない）なら「買い」と断定しない
            return {"status": "PROFIT_WATCH", "answer": a}
        return {"status": "PROFIT", "answer": a}
    return {"status": "NO_PROFIT", "answer": a, "reason": "計算上の黒字になる容量がない"}


# ---- 新製品・予約情報（product_candidates.json の Apple 候補。表示だけで、正本へは登録しない） ----
CAND_STATUS = {"REGISTERED": "登録済み", "MATCHED_EXISTING": "登録済み（既存の商品と一致）", "PENDING_REVIEW": "未登録（確認待ち）"}


def apple_candidates(candidates) -> list[dict] | None:
    """Apple の候補をモデル別に。{"model", "items": [{capacity, status_label, registered, price, first_seen, last_seen}]}。
    読めない・Apple 候補が無いなら None（データ無し）。内部の候補 ID・review の詳細は出さない。"""
    if not isinstance(candidates, dict) or not isinstance(candidates.get("candidates"), dict):
        return None
    by: dict[str, list] = {}
    for c in candidates["candidates"].values():
        if not isinstance(c, dict) or c.get("brand") != "Apple" or c.get("genre", "iphone") != "iphone":
            continue
        model, cap = split_sku(c.get("product_name"))
        st = c.get("status")
        by.setdefault(model, []).append({
            "capacity": cap or "—", "registered": st in ("REGISTERED", "MATCHED_EXISTING"),
            "status_label": CAND_STATUS.get(st, "未登録（確認待ち）"),
            "price": c.get("official_price") if isinstance(c.get("official_price"), int) else None,
            "first_seen": str(c.get("discovered_at") or "")[:10] or None, "last_seen": c.get("last_seen_on") or None})
    if not by:
        return None
    return [{"model": m, "items": sorted(v, key=lambda x: cap_key(x["capacity"]))} for m, v in by.items()]
