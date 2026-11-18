"""二次流通（フリマ・オークション）の週次の更新。1 コマンド・既定は dry-run（何も書かない）。

    python -m src.research.secondary_refresh            # dry-run（取得可否・件数・ルート C/D を表示するだけ）
    python -m src.research.secondary_refresh --apply    # 検証に通ったときだけ公開データ・履歴・ページへ書く

camera_refresh（カメラの週次の更新）と同じ入口・同じ検証・同じ公開の許可リストを使い、二次流通の面だけを見せる。
- 市場ごとの取得状態（AVAILABLE / PARTIAL / NOT_CONFIGURED / PENDING_APPROVAL / BLOCKED / FAILED / NOT_SUPPORTED）を記録する。取得できなかった市場は
  「出品なし・成約なし」にしない（件数は未取得 = null）。一部の市場が BLOCKED でも、取れた市場のデータは反映する。
- 検索結果は取らない。入るのは公式 API のアダプター（secondary_markets.register_adapter。資格情報が無ければ NOT_CONFIGURED で通信 0）と、
  調査員が根拠 URL つきで読んだ行（research_camera_*.json）だけ。売値は SOLD_MEDIAN（件数・期間つき）だけ、手数料は CONFIRMED の市場だけ。
- 終了コード: 0=正常 / 2=一部の取得元が失敗（取れた分は有効）/ 1=検証エラー。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.research import camera_refresh as crf
from src.research import camera_routes as cr
from src.research import secondary_markets as sm

JST = crf.JST


def run(src: Path, date: str, *, now: datetime, old: Optional[dict], env=None, **kw) -> dict:
    env = os.environ if env is None else env
    extra, errs, ran, details = sm.run_adapters_full(env)
    return crf.refresh(src, date, now=now, old_market=old, extra_records=extra, adapter_errors=errs, env=env, adapters_ran=ran,
                       adapter_details=details, **kw)


def ebay_summary(state: dict) -> dict:
    """eBay の状態（dry-run の出力）。件数・状態だけ。秘密の値・自由記述を出さない。"""
    m = next((x for x in state["secondary_markets"] if x["market"] == "ebay"), None)
    if not m:
        return {}
    ad = m.get("adapter") or {}
    ap = ad.get("approval") or {}
    routes = [r for r in state["market"]["routes"] if r["profit_status"] != cr.NOT_CALCULATED and any(
        (x or {}).get("source") == "eBay" for x in (r.get("buy"), r.get("sell")))]
    return {"status": m["status"], "reason": m["reason"], "listing_status": m["listing_access"], "sold_status": m["sold_access"],
            "credentials_configured": m["credentials"] == sm.CONFIGURED,
            "approval_status": {"insights_approved": bool(ap.get("insights_approved")), "sold_license_confirmed": bool(ap.get("sold_license_confirmed")),
                                "sold_access": m["sold_access"]},
            "network_requests": ad.get("requests", 0), "items_found": ad.get("items_found"), "items_matched": ad.get("items_matched"),
            "items_rejected_identity": ad.get("rejected_identity", 0), "items_rejected_condition": ad.get("rejected_condition", 0),
            "fx": ad.get("fx", {}), "profit_routes_calculated": len(routes), "fee_status": m["fee_status"]}


def secondary_summary(state: dict, *, apply: bool, written=None, problems=None) -> dict:
    mk = state["secondary_markets"]
    routes = state["market"]["routes"]
    calc = lambda t: [r for r in routes if r["route_type"] == t and r["profit_status"] != cr.NOT_CALCULATED]
    found = state["report"]["found"]
    return {
        "mode": "APPLY" if apply else "DRY_RUN",
        "markets_attempted": [m["market"] for m in mk],
        "markets_succeeded": [m["market"] for m in mk if m["status"] in (sm.AVAILABLE, sm.PARTIAL)],
        "markets_blocked": [m["market"] for m in mk if m["status"] in sm._NO_DATA],
        "market_status": {m["market"]: {"status": m["status"], "reason": m["reason"], "credentials": m["credentials"],
                                        "listing_rows": m["listing_rows"], "sold_rows": m["sold_rows"], "fee_status": m["fee_status"]} for m in mk},
        "ebay": ebay_summary(state),
        "api_errors": state["report"]["secondary_markets"].get("api_errors", {}),
        "retail_apis": state.get("retail_apis", []),
        "products_checked": state["report"]["products_checked"],
        "listing_rows": found["listing"], "sold_rows": found["sold"],
        "routes_C_calculated": len(calc("C")), "routes_D_calculated": len(calc("D")),
        "new_profitable_routes": state["report"]["new_profitable_routes"], "lost_profitable_routes": state["report"]["routes_lost"],
        "quality": state["quality"], "validation_problems": problems or [],
        "public_files": written if written is not None else (["(検証エラーのため書かなかった)"] if (apply and problems) else
                          ["(dry-run: 書かない) exports/camera_research/camera_market.json・camera_market_history.json", "(dry-run: 書かない) docs/camera-research.html"]),
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="二次流通の週次の更新。既定は dry-run（何も書かない）")
    ap.add_argument("--apply", action="store_true", help="検証に通ったときだけ、公開データ・履歴・ページへ書き込む")
    ap.add_argument("--dir", help="調査フォルダ（既定: .private/research/weekly/<今日>。無ければ直近のもの）")
    a = ap.parse_args(argv)
    now = datetime.now(JST)
    date = now.strftime("%Y-%m-%d")
    target = Path(a.dir) if a.dir else crf.WEEKLY_ROOT / date
    if a.dir and not crf._DATE.fullmatch(target.name):
        print(json.dumps({"error": "調査フォルダの名前は YYYY-MM-DD にしてください（調査日をフォルダ名から決めます）"}, ensure_ascii=False))
        return 1
    if crf._DATE.fullmatch(target.name):
        date = target.name
    src = target if list(target.glob("research_camera_*.json")) else crf.previous_dir(crf.WEEKLY_ROOT, date)
    if not src:
        print(json.dumps({"error": "元になる調査フォルダが見つからない"}, ensure_ascii=False))
        return 1
    try:
        old = json.loads((crf.EXPORT_DIR / crf.MARKET_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if crf._DATE.fullmatch(src.name):
        date = src.name
    state = run(src, date, now=now, old=old)
    problems = crf.validate(state)
    written = None
    if a.apply and not problems:
        written = crf.write_all(state, target, export_dir=crf.EXPORT_DIR, build_page=crf._build_page)
    print(json.dumps(secondary_summary(state, apply=a.apply, written=written, problems=problems), ensure_ascii=False, indent=1, default=list))
    if problems:
        return 1
    api_failed = bool(state["report"]["secondary_markets"].get("api_errors"))
    return 0 if not state["report"]["sources_failed"] and not api_failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
