# -*- coding: utf-8 -*-
"""iPhone（Duo）の週次の更新を 1 コマンドで行う。

    python -m src.research.iphone_refresh            # dry-run（何も書かない。内容を表示するだけ）
    python -m src.research.iphone_refresh --apply    # 検証に通ったときだけ書く

流れ: Apple（価格・購入可否）→ PASTEC・ルデヤの取得 → 同一性（機種・容量・条件）→ 鮮度 → 利益 → 履歴 → 公開データ・ページ → 判定。

守ること:
- 取得は polite 取得だけ（robots.txt・間隔・正直な UA）。24 時間の監視ではなく、週 1 回の手動実行を想定する。
- **取得できた店・行だけ**を新しい値にする。失敗した店の古い値は、そのまま（日付も進めず）残る＝鮮度で STALE になる。
- 直前の価格から 25% 以上動いた行は「誤取得かもしれない」ので、その店の更新を採らない（確認待ち）。
- 通知は送らない（イベントは dry-run の記録だけ）。本体の BUY・通知・outbox には接続しない。
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from src.collectors import buyback_iphone_weekly as shops_mod
from src.research import weekly_import as wi

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEEKLY_ROOT = PROJECT_ROOT / ".private" / "research" / "weekly"
EXPORT_DIR = PROJECT_ROOT / "exports" / "iphone_buyback"
LIVE_FILE = "iphone_exp_live.json"
MODELS = ("iPhone Duo",)
JUMP_RATIO = 0.25            # 直前の価格からこの割合以上動いた行は、その店の更新を採らない
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


# ---------- 入力の読み書き ----------
def _flatten(data) -> list:
    if isinstance(data, dict) and isinstance(data.get("shops"), list):
        data = data["shops"]
    return list(data) if isinstance(data, list) else [v for v in data.values() if isinstance(v, dict)]


def _strip(data, keys: set):
    """店エントリのうち、keys の店を取り除いた同じ形のデータ（list / {"shops": list} / {名前: エントリ} に対応）。"""
    def _drop(e):
        return isinstance(e, dict) and wi.shop_key(str(e.get("shop_name") or "")) in keys
    if isinstance(data, dict) and isinstance(data.get("shops"), list):
        return {**data, "shops": [e for e in data["shops"] if not _drop(e)]}
    if isinstance(data, list):
        return [e for e in data if not _drop(e)]
    return {k: v for k, v in data.items() if not _drop(v)}


def previous_dir(root: Path, date: str) -> Optional[Path]:
    """調査の JSON が揃っている、date 以前で最新のフォルダ（date 自身を含む）。"""
    c = sorted(d for d in root.iterdir() if d.is_dir() and _DATE.fullmatch(d.name) and d.name <= date
               and (d / "research_iphone.json").exists() and list(d.glob("iphone_exp_*.json"))) if root.exists() else []
    return c[-1] if c else None


def load_dir(d: Path) -> tuple[dict, dict]:
    research = json.loads((d / "research_iphone.json").read_text(encoding="utf-8"))
    files = {f.name: json.loads(f.read_text(encoding="utf-8")) for f in sorted(d.glob("iphone_exp_*.json"))}
    return research, files


def _jump(old: Optional[int], new: Optional[int]) -> bool:
    return bool(old and new and abs(new - old) / old >= JUMP_RATIO)


def _base_prices(entries: list) -> dict:
    out = {}
    for sh in wi.normalize_iphone_shops(entries, "2000-01-01"):
        for r in sh["rows"]:
            out[(sh["key"], r["sku"], r["condition"])] = r.get("base_price")
    return out


# ---------- 本体 ----------
def refresh(src_dir: Path, date: str, *, now: datetime, skip_apple: bool = False,
            fetch_shop: Optional[Callable] = None, apple_fn: Optional[Callable] = None,
            history_path: Optional[Path] = None, old_comp: Optional[dict] = None, cfg: Optional[dict] = None) -> dict:
    """メモリの上で更新を計算して結果を返す（ファイルには書かない）。state に書き込む内容が入る。"""
    fetch_shop = fetch_shop or shops_mod.fetch_shop
    cfg = cfg or wi.load_config()
    research, files = load_dir(src_dir)
    research, files = copy.deepcopy(research), copy.deepcopy(files)
    old_entries = [e for d in files.values() for e in _flatten(d)]
    old_base = _base_prices(old_entries)
    report: dict = {"sources": {}, "prices_changed": [], "rows_unchanged": [], "skus_refetched": set()}

    # --- Apple ---
    if skip_apple:
        report["sources"]["apple"] = {"attempted": False}
    else:
        if apple_fn is None:
            from src.collectors.official import apple_buyability
            apple_fn = apple_buyability.apple_live
        live = apple_fn()
        old_apple = (research.get("apple_official") or {}).get("prices_jpy", {}).get(live.get("model"), {})
        jumped = [c for c, p in (live.get("prices") or {}).items() if _jump(old_apple.get(c), p)]
        if not live.get("prices"):
            report["sources"]["apple"] = {"attempted": True, "ok": False, "error": ";".join(live.get("errors") or ["no_prices"])}
        elif jumped:
            report["sources"]["apple"] = {"attempted": True, "ok": False, "error": f"price_jump_needs_review:{','.join(jumped)}"}
        else:
            from src.collectors.official import apple_buyability
            apple_buyability.merge_live(research, live)
            report["sources"]["apple"] = {"attempted": True, "ok": not live.get("errors"), "error": ";".join(live.get("errors") or []) or None,
                                          "prices": live["prices"], "availability": {k: v["status"] for k, v in live["availability"].items()}}

    # --- PASTEC・ルデヤ ---
    new_entries: list = []
    for key in ("pastec", "rudeya"):
        r = fetch_shop(key, models=MODELS, now=now)
        info = {"attempted": True, "ok": r["ok"], "error": r.get("error"), "rows": r.get("rows", 0)}
        if r["ok"]:
            new_base = _base_prices([r["entry"]])
            jumps = [f"{sku}:{old_base[(k, sku, c)]}→{p}" for (k, sku, c), p in new_base.items()
                     if _jump(old_base.get((k, sku, c)), p)]
            if jumps:
                info.update(ok=False, error="price_jump_needs_review:" + ",".join(jumps))
            else:
                new_entries.append(r["entry"])
                for (k, sku, c), p in sorted(new_base.items()):
                    report["skus_refetched"].add(sku)
                    o = old_base.get((k, sku, c))
                    (report["prices_changed"] if o != p else report["rows_unchanged"]).append(
                        {"shop": r["shop_name"], "sku": sku, "from": o, "to": p})
        report["sources"][key] = info
    ok_keys = {wi.shop_key(e["shop_name"]) for e in new_entries}
    if ok_keys:
        files = {n: _strip(d, ok_keys) for n, d in files.items()}
        files[LIVE_FILE] = new_entries            # 取得できた店だけ入れ替える（失敗した店の古い行は、日付もそのまま残る）

    # --- 比較・履歴・判定 ---
    raw_shops = [e for d in files.values() for e in _flatten(d)]
    apple_doc = research.get("apple_official", {})
    comp = wi.build_iphone_comparison(raw_shops, apple_doc.get("prices_jpy", {}), research_date=date, now=now, cfg=cfg,
                                      availability=apple_doc.get("availability"))
    hist = wi.update_history(comp, history_path or EXPORT_DIR / "iphone_buyback_history.json",
                             surge_yen=int(cfg["surge"].get("yen") or 5000))
    report["skus_refetched"] = sorted(report["skus_refetched"])
    report["profit_changed"] = _profit_changes(old_comp, comp)
    report["events"] = comp["events"]
    report["notification_dry_run"] = comp["notification_dry_run"]
    return {"report": report, "comp": comp, "hist": hist, "research": research, "files": files, "ok_keys": sorted(ok_keys)}


def _view(s: dict) -> dict:
    return {"net": s.get("net_profit"), "roi": s.get("roi_pct"), "profit_status": s.get("profit_status"),
            "decision": s.get("opportunity_status"), "top": ((s.get("highest_executable") or {}).get("shop"),
                                                             (s.get("highest_executable") or {}).get("price"))}


def _profit_changes(old_comp: Optional[dict], comp: dict) -> list:
    old = {s["sku"]: _view(s) for s in (old_comp or {}).get("skus", [])}
    out = []
    for s in comp["skus"]:
        if not any(m in s["sku"] for m in MODELS):
            continue
        new = _view(s)
        out.append({"sku": s["sku"], "before": old.get(s["sku"]), "after": new, "changed": old.get(s["sku"]) != new})
    return out


def validate(state: dict) -> list:
    """書き込む前の検証。問題の説明の一覧（空なら通る）。"""
    problems = []
    comp = state["comp"]
    if not state["ok_keys"] and not state["report"]["sources"].get("apple", {}).get("ok"):
        problems.append("更新できた取得元が 1 つも無い")
    for s in comp["skus"]:
        he = s.get("highest_executable")
        if he:
            rows = [r for r in s["rows"] if r["shop"] == he["shop"] and r["executable_price"] == he["price"]]
            if not rows or not all(r["freshness"] == wi.FRESH and r["eligible"] for r in rows[:1]):
                problems.append(f"{s['sku']}: 最高の実行可能買取が FRESH の行に対応しない")
        if s.get("opportunity_status") == wi.OPP_BUY and (s.get("apple_availability") or {}).get("status") != wi.AV_BUYABLE:
            problems.append(f"{s['sku']}: 購入可能が確認できないのに BUY")
    return problems


def write_all(state: dict, target_dir: Path, *, export_dir: Path, build_page: Optional[Callable] = None) -> list:
    """検証済みの state を書き込む。書いたファイル名の一覧を返す。"""
    from src.utils.atomic_write import write_json_atomic
    target_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, data in state["files"].items():
        (target_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (target_dir / "research_iphone.json").write_text(json.dumps(state["research"], ensure_ascii=False, indent=1), encoding="utf-8")
    export_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(export_dir / "iphone_buyback_comparison.json", state["comp"])
    write_json_atomic(export_dir / "iphone_buyback_history.json", state["hist"])
    written += ["exports/iphone_buyback/iphone_buyback_comparison.json", "exports/iphone_buyback/iphone_buyback_history.json"]
    if build_page:
        build_page()
        written.append("docs/iphone-buyback.html")
    return written


def _build_page():
    import sys
    if str(PROJECT_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import build_public_lp
    build_public_lp._build_iphone_buyback_html(build_public_lp.PUBLIC_DIR)


def summarize(state: dict, *, apply: bool, written: Optional[list] = None, problems: Optional[list] = None) -> dict:
    r = state["report"]
    srcs = r["sources"]
    attempted = [k for k, v in srcs.items() if v.get("attempted")]
    return {
        "mode": "APPLY" if apply else "DRY_RUN",
        "sources_attempted": attempted,
        "sources_succeeded": [k for k in attempted if srcs[k].get("ok")],
        "sources_failed": {k: srcs[k].get("error") for k in attempted if not srcs[k].get("ok")},
        "skus_updated": r["skus_refetched"],
        "prices_changed": r["prices_changed"],
        "rows_unchanged": r["rows_unchanged"],
        "profit_changed": [p for p in r["profit_changed"] if p["changed"]],
        "profit_now": [{"sku": p["sku"], **p["after"]} for p in r["profit_changed"]],
        "events": r["events"],
        "notification": "DRY_RUN（送信 0）",
        "validation_problems": problems or [],
        "public_files": written if written is not None else ["(dry-run: 書かない) exports/iphone_buyback/*.json", "(dry-run: 書かない) docs/iphone-buyback.html"],
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="iPhone（Duo）の週次の更新。既定は dry-run（何も書かない）")
    ap.add_argument("--apply", action="store_true", help="検証に通ったときだけ、調査フォルダ・公開データ・ページへ書き込む")
    ap.add_argument("--skip-apple", action="store_true", help="Apple の取得を省く（約 2 分かかるため。購入可否は更新されない）")
    ap.add_argument("--dir", help="調査フォルダ（既定: .private/research/weekly/<今日>。無ければ直近のものを元にする）")
    a = ap.parse_args(argv)
    now = datetime.now(JST)
    date = now.strftime("%Y-%m-%d")
    target = Path(a.dir) if a.dir else WEEKLY_ROOT / date
    if _DATE.fullmatch(target.name):
        date = target.name
    src = target if (target / "research_iphone.json").exists() else previous_dir(WEEKLY_ROOT, date)
    if not src:
        print(json.dumps({"error": "元になる調査フォルダが見つからない"}, ensure_ascii=False))
        return 1
    try:
        old_comp = json.loads((EXPORT_DIR / "iphone_buyback_comparison.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old_comp = None
    state = refresh(src, date, now=now, skip_apple=a.skip_apple, old_comp=old_comp)
    problems = validate(state)
    written = None
    if a.apply and not problems:
        written = write_all(state, target, export_dir=EXPORT_DIR, build_page=_build_page)
    out = summarize(state, apply=a.apply, written=written, problems=problems)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=list))
    if problems:
        return 1
    return 0 if not out["sources_failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
