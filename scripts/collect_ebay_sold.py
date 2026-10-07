#!/usr/bin/env python3
"""eBay の成約（Marketplace Insights API）を取り、成約の履歴（exports/sold_history）に足す（Phase 12）。

今は CI から呼ばない（Secret が無いので PENDING_USER_CONFIGURATION）。手順:
1. eBay の開発者アカウントで Marketplace Insights API の利用許可を得る（審査制）
2. GitHub Secrets に EBAY_CLIENT_ID・EBAY_CLIENT_SECRET を登録する（値はログに出さない）
3. まず `--dry-run` で送るリクエストを確かめ、次に canary（既定は1商品: PS5 Pro）で生の応答の形・成約日時・
   商品ページ・状態・同一性を確かめてから、商品を増やす（EBAY_API_STAGE）。canary が通るまで全商品にしない

使い方:
  python scripts/collect_ebay_sold.py --dry-run          # 送るリクエストの一覧だけ（ネットワークに出ない）
  python scripts/collect_ebay_sold.py                    # 資格情報があれば canary（1商品）
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JST = timezone(timedelta(hours=9))
STATUS_PATH = ROOT / "exports" / "sold_history" / "collect_status.json"
CANARY_PATH = ROOT / "exports" / "sold_history" / "canary.json"


def canary_passed(path: Path | None = None) -> bool:
    """canary（1商品）が合格した記録があるか（無ければ段階を上げても1商品だけ。監査 M6）。"""
    try:
        return bool(json.loads((path or CANARY_PATH).read_text(encoding="utf-8")).get("passed"))
    except (OSError, ValueError):
        return False

# canary の1商品（同一性がはっきりしている商品から始める）と、段階ごとの対象
CANARY = [("prod_ps5_pro", "PlayStation 5 Pro CFI-7000")]
STAGED = CANARY + [("prod_gr4", "Ricoh GR IV"), ("prod_iphone17_256", "iPhone 17 256GB")]


def _http_get(url: str, headers: dict) -> dict:
    """api_runtime.retry_with_backoff の形の結果（例外の文言から秘密の値を伏せる）。"""
    from src.collectors.api.ebay_insights import redact
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return {"status": r.getcode(), "data": json.loads(r.read().decode("utf-8")), "retry_after": None,
                    "exc": None}
    except urllib.error.HTTPError as e:
        ra = e.headers.get("Retry-After") if e.headers else None
        return {"status": e.code, "data": None, "retry_after": int(ra) if ra and ra.isdigit() else None,
                "exc": RuntimeError(redact(str(e)))}
    except Exception as e:  # noqa: BLE001
        return {"status": None, "data": None, "retry_after": None, "exc": RuntimeError(redact(str(e)))}


def _fetch_token() -> tuple[str | None, str]:
    """(token, 状態)。token は戻り値だけで扱い、保存・表示しない。"""
    from src.collectors.api import ebay_insights as ei
    req = ei.token_request()
    if req is None:
        return None, ei.ST_PENDING
    url, headers, body = req
    try:
        r = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(r, timeout=30) as resp:
            tok = json.loads(resp.read().decode("utf-8")).get("access_token")
            return (tok, ei.ST_OK) if tok else (None, ei.ST_ERROR)
    except urllib.error.HTTPError as e:
        # 許可（scope）が無い・資格情報が違う → 取りに行かない（再試行しない）
        return None, ei.ST_ACCESS if e.code in (400, 401, 403) else ei.ST_ERROR
    except Exception:  # noqa: BLE001
        return None, ei.ST_ERROR


def main(argv=None) -> int:
    from src.collectors.api import api_runtime as rt
    from src.collectors.api import ebay_insights as ei
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="送るリクエストの一覧だけを出す（ネットワークに出ない）")
    args = ap.parse_args(argv)
    now = datetime.now(tz=JST)
    stage = rt.api_stage("ebay")
    if stage != "0" and not canary_passed():
        stage = "0"                 # canary が通るまで全商品にしない
    targets = CANARY if stage == "0" else STAGED[: (rt.stage_product_limit(stage) or len(STAGED))]
    st = ei.status()
    if args.dry_run or st != ei.ST_OK:
        out = ei.dry_run_plan(targets, now)
        out["stage"] = stage
        print(ei.dumps_safe(out))
        return 0
    token, tst = _fetch_token()
    if not token:
        print(ei.dumps_safe({"status": tst, "note": "token を取得できない（許可・資格情報を確認）"}))
        return 0
    from src.collectors.api.market_apis import load_fx_rate
    from src.market import sold_history as sh
    from src.market.product_identity_resolver import ProductIdentityResolver, build_products_index
    resolver = ProductIdentityResolver(build_products_index(ROOT / "data" / "premium_monitor.db"))
    fx = load_fx_rate("USD").get("rate")
    budget = [ei.MAX_REQUESTS_PER_RUN]
    new, rejected = [], {}
    for pid, q in targets:
        recs, rej = ei.collect(pid, q, resolver=resolver, now=now, fx_rate=fx, http_get=_http_get,
                               token=token, request_budget=budget)
        new.extend(recs)
        for k, v in rej.items():
            rejected[k] = rejected.get(k, 0) + v
    hist, stats = sh.merge(sh.load(), new)
    sh.save(hist, now)
    if stage == "0":
        # canary の合格: 検索のリクエストが通り（request_* の失敗が無い）、使える成約が1件以上あること
        passed = bool(new) and not any(k.startswith("request_") for k in rejected)
        CANARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        CANARY_PATH.write_text(ei.dumps_safe({"checked_at": now.isoformat(timespec="seconds"), "passed": passed,
                                              "product_id": targets[0][0], "valid_records": len(new),
                                              "rejected": rejected}), encoding="utf-8")
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(ei.dumps_safe({
        "generated_at": now.isoformat(timespec="seconds"), "status": ei.ST_OK, "stage": stage,
        "targets": [p for p, _ in targets], "requests_used": ei.MAX_REQUESTS_PER_RUN - budget[0],
        "merge": stats, "rejected": rejected}), encoding="utf-8")
    print(f"成約の取得: 追加 {stats['added']} / 重複 {stats['duplicate']} / 使わなかった {sum(rejected.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
