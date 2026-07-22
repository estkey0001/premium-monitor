#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Profit Health Dashboard — システム健康状態の日次集計。

利益ロジックは変更しない。データ品質・取得状況・利益発見率を可視化する。
出力: audit_health/health_report.json / health_report.md（前日比較・スコア・異常検知・改善TOP10）
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "audit_health"
HIST = OUT / "history"


def _load(p):
    try:
        return json.loads((ROOT / p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pct(a, b):
    return round(a / b, 4) if b else 0.0


def _data_quality(obs):
    n = len(obs)
    usable = sum(1 for o in obs if o.get("is_usable_for_pro") or o.get("is_usable_for_beginner"))
    stale = sum(1 for o in obs if not o.get("is_fresh"))
    zero = sum(1 for o in obs if (o.get("price") or 0) <= 0)
    item = sum(1 for o in obs if o.get("item_url") or o.get("link_type") in ("item", "item_unverified"))
    search = sum(1 for o in obs if o.get("link_type") == "search")
    methods = Counter((o.get("collector_method") or o.get("extraction_method") or "?") for o in obs)
    manual = sum(v for k, v in methods.items() if "manual" in str(k).lower())
    api = sum(v for k, v in methods.items() if str(k).lower() == "api")
    html = sum(v for k, v in methods.items() if "html" in str(k).lower() or str(k) == "overseas_history")
    return {
        "total_obs": n, "usable_obs": usable,
        "stale_count": stale, "stale_rate": _pct(stale, n),
        "zero_count": zero, "zero_rate": _pct(zero, n),
        "item_url_rate": _pct(item, n), "search_url_rate": _pct(search, n),
        "manual_rate": _pct(manual, n), "api_rate": _pct(api, n), "html_rate": _pct(html, n),
    }


def _profit(pr):
    s = pr.get("summary", {})
    mains = pr.get("main_routes", [])
    profits = [r.get("net_profit", 0) for r in mains]
    rois = [r.get("roi", 0) for r in mains]
    return {
        "main_route_count": s.get("main_route_count", 0),
        "reference_route_count": s.get("reference_route_count", 0),
        "max_profit": (max(profits) if profits else 0),
        "avg_profit": (round(sum(profits) / len(profits)) if profits else 0),
        "avg_roi": (round(sum(rois) / len(rois), 4) if rois else 0),
        "main_route_products": sorted({r.get("product_id") for r in mains}),
    }


def _sources(obs):
    src = defaultdict(lambda: {"success": 0, "stale": 0, "zero": 0, "item": 0,
                               "conf": Counter(), "fresh": 0, "n": 0})
    for o in obs:
        s = src[o.get("source_name", "?")]
        s["n"] += 1
        if (o.get("price") or 0) > 0:
            s["success"] += 1
        else:
            s["zero"] += 1
        if not o.get("is_fresh"):
            s["stale"] += 1
        else:
            s["fresh"] += 1
        if o.get("item_url") or o.get("link_type") in ("item", "item_unverified"):
            s["item"] += 1
        s["conf"][o.get("confidence", "?")] += 1
    out = {}
    for name, s in src.items():
        n = s["n"]
        out[name] = {
            "success_count": s["success"], "stale_count": s["stale"], "zero_count": s["zero"],
            "item_url_rate": _pct(s["item"], n), "freshness": _pct(s["fresh"], n),
            "success_rate": _pct(s["success"], n), "confidence": dict(s["conf"]), "n": n,
        }
    return dict(sorted(out.items(), key=lambda kv: kv[1]["n"], reverse=True))


def _score(dq, pf, sources):
    # Data Quality 35: usable率20 + (1-stale率)10 + (1-0円率)5
    n = dq["total_obs"] or 1
    dq_score = round(_pct(dq["usable_obs"], n) * 20 + (1 - dq["stale_rate"]) * 10
                     + (1 - dq["zero_rate"]) * 5, 1)
    # Profit Discovery 25: main有無15 + reference10（潜在）
    pd_score = round((15 if pf["main_route_count"] > 0 else 0)
                     + min(10, pf["reference_route_count"] * 2.5), 1)
    # Source Health 20: 平均success_rate * 20
    srates = [v["success_rate"] for v in sources.values()]
    sh_score = round((sum(srates) / len(srates) if srates else 0) * 20, 1)
    # Link Quality 10: item_url率 * 10
    lq_score = round(dq["item_url_rate"] * 10, 1)
    # Freshness 10: (1-stale率) * 10
    fr_score = round((1 - dq["stale_rate"]) * 10, 1)
    total = round(dq_score + pd_score + sh_score + lq_score + fr_score, 1)
    return {"data_quality": dq_score, "profit_discovery": pd_score, "source_health": sh_score,
            "link_quality": lq_score, "freshness": fr_score, "total": total}


def _diff(cur, prev):
    """前日レポートとの差分を計算する。"""
    if not prev:
        return {"available": False, "note": "前日レポートなし（初回）"}
    pdq = prev.get("data_quality", {})
    ppf = prev.get("profit", {})
    cdq = cur["data_quality"]
    cpf = cur["profit"]
    d = {
        "available": True,
        "stale_rate": {"prev": pdq.get("stale_rate"), "cur": cdq["stale_rate"]},
        "zero_rate": {"prev": pdq.get("zero_rate"), "cur": cdq["zero_rate"]},
        "item_url_rate": {"prev": pdq.get("item_url_rate"), "cur": cdq["item_url_rate"]},
        "main_route_count": {"prev": ppf.get("main_route_count"), "cur": cpf["main_route_count"]},
        "reference_route_count": {"prev": ppf.get("reference_route_count"), "cur": cpf["reference_route_count"]},
    }
    # 新規/消失 main
    prev_mains = set(ppf.get("main_route_products", []))
    cur_mains = set(cpf.get("main_route_products", []))
    d["new_main"] = sorted(cur_mains - prev_mains)
    d["lost_main"] = sorted(prev_mains - cur_mains)
    # ソース成功率の急変
    psrc = prev.get("sources", {})
    src_changes = []
    for name, cv in cur["sources"].items():
        pv = psrc.get(name)
        if pv and pv.get("success_rate") is not None:
            delta = cv["success_rate"] - pv["success_rate"]
            if abs(delta) >= 0.2:
                src_changes.append({"source": name, "prev": pv["success_rate"],
                                    "cur": cv["success_rate"], "delta": round(delta, 3)})
    d["source_success_changes"] = sorted(src_changes, key=lambda x: x["delta"])
    return d


def _anomalies(cur, diff):
    dq = cur["data_quality"]; pf = cur["profit"]
    crit, warn, info = [], [], []
    if dq["stale_rate"] >= 0.5:
        crit.append(f"stale率 {dq['stale_rate']*100:.0f}% (>=50%)")
    if dq["zero_rate"] >= 0.3:
        crit.append(f"0円率 {dq['zero_rate']*100:.0f}% (>=30%)")
    # main route 半減
    if diff.get("available"):
        pm = diff["main_route_count"]["prev"] or 0
        cm = diff["main_route_count"]["cur"] or 0
        if pm >= 2 and cm <= pm / 2:
            crit.append(f"main route 半減 {pm}→{cm}")
        elif cm < pm:
            warn.append(f"main route 減少 {pm}→{cm}")
        if diff["new_main"]:
            info.append(f"新規 main: {', '.join(diff['new_main'])}")
        pr_prev = diff["reference_route_count"]["prev"] or 0
        pr_cur = diff["reference_route_count"]["cur"] or 0
        if pr_cur > pr_prev * 1.5 and pr_prev > 0:
            warn.append(f"reference 急増 {pr_prev}→{pr_cur}")
        if diff["item_url_rate"]["prev"] is not None and dq["item_url_rate"] < diff["item_url_rate"]["prev"]:
            warn.append("item_url率 低下")
    # ソース取得成功率
    for name, v in cur["sources"].items():
        if v["n"] >= 3 and v["success_rate"] < 0.5:
            crit.append(f"取得成功率 {v['success_rate']*100:.0f}%: {name}")
    if dq["item_url_rate"] < 0.5:
        warn.append(f"item_url率 {dq['item_url_rate']*100:.0f}% (<50%)")
    if pf["main_route_count"] > 0:
        info.append(f"検証済み利益ルート {pf['main_route_count']}件 / 最大 +¥{pf['max_profit']:,}")
    for c in diff.get("source_success_changes", []):
        if c["delta"] <= -0.2:
            warn.append(f"{c['source']} 取得成功率 {c['prev']*100:.0f}%→{c['cur']*100:.0f}%")
    return {"critical": crit, "warning": warn, "info": info}


def _improvements(pr, cur):
    imp = []
    refs = pr.get("reference_routes", [])
    ref_pot = sum(r.get("net_profit", 0) for r in refs)
    if not _load("exports/overseas_prices/latest.json").get("ebay_app_id_configured"):
        imp.append({"stars": 5, "action": "EBAY_APP_ID 設定", "effect": f"+¥{ref_pot:,}（参考{len(refs)}→main昇格）", "effort": "1時間"})
    # 取得成功率が低いソース（買取¥0）
    low = [(n, v) for n, v in cur["sources"].items() if v["n"] >= 3 and v["success_rate"] < 0.5]
    low.sort(key=lambda x: x[1]["zero_count"], reverse=True)
    for n, v in low[:4]:
        imp.append({"stars": 4, "action": f"取得失敗修正: {n}", "effect": f"0円{v['zero_count']}件の解消でsell候補復活", "effort": "4時間"})
    imp.append({"stars": 4, "action": "Mercari/Yahoo sold 手動CSV追加", "effect": "国内買取ルートの裾拡大", "effort": "1時間"})
    imp.append({"stars": 3, "action": "official_price を products.yaml 登録", "effect": "差益基準の信頼性向上", "effort": "4時間"})
    imp.append({"stars": 3, "action": "買取/販売リンクの item_url 個別化", "effect": "再現性スコア+30・確認導線", "effort": "1日"})
    imp.append({"stars": 3, "action": "ヤフオク closedsearch 半自動取得", "effect": "同条件sold≥3で再現性向上", "effort": "1日"})
    imp.append({"stars": 2, "action": "freshness横断監視＋自動再取得", "effect": "stale率恒常低下", "effort": "1週間"})
    imp.sort(key=lambda x: x["stars"], reverse=True)
    return imp[:10]


def main() -> int:
    print(f"[generate_health_report] 開始: {NOW.strftime('%Y-%m-%d %H:%M')} JST")
    obs = _load("exports/normalized_price_observations/latest.json").get("observations", [])
    pr = _load("exports/profit_routes/latest.json")
    if not obs:
        print("[WARN] NPO 観測なし", file=sys.stderr)

    dq = _data_quality(obs)
    pf = _profit(pr)
    sources = _sources(obs)
    score = _score(dq, pf, sources)

    OUT.mkdir(exist_ok=True)
    prev = _load("audit_health/health_report.json")  # 上書き前 = 前日
    cur = {"data_quality": dq, "profit": pf, "sources": sources, "health_score": score}
    diff = _diff(cur, prev)
    anomalies = _anomalies(cur, diff)
    improvements = _improvements(pr, cur)

    report = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "date": NOW.strftime("%Y-%m-%d"),
        "health_score": score,
        "data_quality": dq,
        "profit": pf,
        "sources": sources,
        "diff_vs_prev": diff,
        "anomalies": anomalies,
        "improvements_top10": improvements,
    }
    (OUT / "health_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    HIST.mkdir(exist_ok=True)
    (HIST / f"{report['date']}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(report)
    print(f"  Health Score: {score['total']}/100 / main {pf['main_route_count']} / "
          f"stale {dq['stale_rate']*100:.0f}% / 0円 {dq['zero_rate']*100:.0f}%")
    print(f"  Critical {len(anomalies['critical'])} / Warning {len(anomalies['warning'])} / Info {len(anomalies['info'])}")
    return 0


def _write_md(r):
    s = r["health_score"]; dq = r["data_quality"]; pf = r["profit"]; a = r["anomalies"]
    o = ["# Profit Health Dashboard", "", f"生成: {r['generated_at']}", "",
         f"## Health Score: **{s['total']} / 100**", "",
         "| 観点 | 配点 | スコア |", "|---|---|---|",
         f"| Data Quality | 35 | {s['data_quality']} |",
         f"| Profit Discovery | 25 | {s['profit_discovery']} |",
         f"| Source Health | 20 | {s['source_health']} |",
         f"| Link Quality | 10 | {s['link_quality']} |",
         f"| Freshness | 10 | {s['freshness']} |", "",
         "## Data Quality KPI", "",
         f"- 総観測 {dq['total_obs']} / usable {dq['usable_obs']}",
         f"- stale {dq['stale_count']}（{dq['stale_rate']*100:.0f}%） / 0円 {dq['zero_count']}（{dq['zero_rate']*100:.0f}%）",
         f"- item_url率 {dq['item_url_rate']*100:.0f}% / search {dq['search_url_rate']*100:.0f}%",
         f"- manual {dq['manual_rate']*100:.0f}% / API {dq['api_rate']*100:.0f}% / HTML {dq['html_rate']*100:.0f}%", "",
         "## Profit KPI", "",
         f"- main route **{pf['main_route_count']}** / reference {pf['reference_route_count']}",
         f"- 最大利益 +¥{pf['max_profit']:,} / 平均利益 +¥{pf['avg_profit']:,} / 平均ROI {pf['avg_roi']*100:.1f}%", ""]
    d = r["diff_vs_prev"]
    o += ["## 前日比較", ""]
    if not d.get("available"):
        o.append(f"- {d.get('note','')}")
    else:
        def _fmt(k, label, pct=True):
            p = d[k]["prev"]; c = d[k]["cur"]
            if p is None:
                return f"- {label}: {c}"
            if pct:
                return f"- {label}: {p*100:.0f}% → {c*100:.0f}%"
            return f"- {label}: {p} → {c}"
        o += [_fmt("main_route_count", "main route", False),
              _fmt("reference_route_count", "reference", False),
              _fmt("stale_rate", "stale率"), _fmt("zero_rate", "0円率"),
              _fmt("item_url_rate", "item_url率")]
        if d["new_main"]:
            o.append(f"- 🆕 新規main: {', '.join(d['new_main'])}")
        if d["lost_main"]:
            o.append(f"- ⚠️ 消失main: {', '.join(d['lost_main'])}")
        for c in d.get("source_success_changes", []):
            o.append(f"- {c['source']} 取得成功率 {c['prev']*100:.0f}%→{c['cur']*100:.0f}%（{c['delta']*100:+.0f}pt）")
    o += ["", "## 異常検知", "",
          "### 🔴 Critical", *([f"- {x}" for x in a["critical"]] or ["- なし"]),
          "", "### 🟡 Warning", *([f"- {x}" for x in a["warning"]] or ["- なし"]),
          "", "### ℹ️ Info", *([f"- {x}" for x in a["info"]] or ["- なし"]),
          "", "## ソース別品質", "",
          "| ソース | 件数 | 成功率 | stale | 0円 | item_url率 | freshness |",
          "|---|---|---|---|---|---|---|"]
    for name, v in r["sources"].items():
        o.append(f"| {name[:18]} | {v['n']} | {v['success_rate']*100:.0f}% | {v['stale_count']} | "
                 f"{v['zero_count']} | {v['item_url_rate']*100:.0f}% | {v['freshness']*100:.0f}% |")
    o += ["", "## 改善提案 TOP10", "", "| 優先 | 施策 | 効果 | 工数 |", "|---|---|---|---|"]
    for i in r["improvements_top10"]:
        o.append(f"| {'★'*i['stars']}{'☆'*(5-i['stars'])} | {i['action']} | {i['effect']} | {i['effort']} |")
    (OUT / "health_report.md").write_text("\n".join(o) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
