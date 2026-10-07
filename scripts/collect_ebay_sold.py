#!/usr/bin/env python3
"""eBay の成約（Marketplace Insights API）を取り、成約の履歴（exports/sold_history）に足す（Phase 12・13）。

CI（Daily LP Update）の「eBay SOLD (Marketplace Insights)」のステップから毎回呼ぶ。条件がそろわなければ通信0で
状態だけを書いて終わる（CI を失敗にしない）。

取りに行くのは、次がすべてそろったときだけ（ebay_insights.status() == OK）:
1. 資格情報（Secrets: EBAY_CLIENT_ID・EBAY_CLIENT_SECRET）          → 無ければ PENDING_USER_CONFIGURATION
2. Marketplace Insights API の承認を人が確認（EBAY_INSIGHTS_APPROVED=true） → 無ければ PENDING_EBAY_APPROVAL
3. 成約を公開リポジトリに保存してよいと人が確認（EBAY_SOLD_LICENSE_CONFIRMED=true）
                                                                     → 無ければ PENDING_LICENSE_CONFIRMATION
4. 取得の明示（ENABLE_EBAY_API=true）・dry-run でない（API_DRY_RUN=false）

段階:
- canary（EBAY_SOLD_CANARY=true が既定）: 1商品（EBAY_SOLD_CANARY_PRODUCT。既定 prod_ps5_pro）だけ取り、変換して
  報告（exports/sold_history/canary.json）を書く。成約の履歴には書かない（ルート・利益商品に入らない）
- 履歴（EBAY_SOLD_CANARY=false かつ canary の合格の記録あり）: EBAY_SOLD_STAGE の商品数（1 → 3 → 10）だけ取り、
  関門（誤った成約・同一性の誤り・秘密の値・アクセス制限・重複がすべて0）を通ったときだけ履歴に書く。
  前の段階を通っていなければ段階を上げない（exports/sold_history/rollout.json）。10商品より先には広げない

使い方:
  python scripts/collect_ebay_sold.py --dry-run          # 送るリクエストの一覧だけ（ネットワークに出ない）
  python scripts/collect_ebay_sold.py                    # 条件がそろっていれば canary または段階の取得
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JST = timezone(timedelta(hours=9))
STATUS_PATH = ROOT / "exports" / "sold_history" / "collect_status.json"
CANARY_PATH = ROOT / "exports" / "sold_history" / "canary.json"
ROLLOUT_PATH = ROOT / "exports" / "sold_history" / "rollout.json"
HISTORY_PATH = ROOT / "exports" / "sold_history" / "latest.json"     # 成約の履歴（sold_history.HISTORY_PATH と同じ）

# 段階の商品（上から順に広げる）。検索語は型番・版を含める（商品名だけで検索しない）。
# canary の既定は PS5 Pro。ただし eBay US の出品は地域の型番（CFI-7000 / CFI-7100 / CFI-7014 など）が混ざるので、
# 実際の canary の報告（返ってきた件数・同一性で落ちた件数）を見て決める（EBAY_SOLD_CANARY_PRODUCT で変えられる）
STAGED = [
    ("prod_ps5_pro", "PlayStation 5 Pro CFI-7000"),
    ("prod_x100vi", "Fujifilm X100VI"),
    ("prod_gfx100rf", "Fujifilm GFX100RF"),
    ("prod_a1ii", "Sony Alpha 1 II ILCE-1M2"),
    ("prod_a7cr", "Sony a7CR ILCE-7CR"),
    ("prod_z8", "Nikon Z8"),
    ("prod_q3", "Leica Q3"),
    ("prod_gr4", "Ricoh GR IV"),
    ("prod_xt5", "Fujifilm X-T5"),
    ("prod_fx3", "Sony FX3 ILME-FX3"),
]
# 段階の関門の同一性の再確認（ProductIdentityResolver とは別の、独立の確認。レビュー M-2）。
# 使えた成約の取得元の商品名に、その商品の名前・型番の目印が無ければ「同一性の誤り」として関門を通さない
IDENTITY_MARKERS = {
    "prod_ps5_pro": (r"ps\s*5\s*pro", r"playstation\s*5\s*pro"),
    "prod_x100vi": (r"x100\s*vi\b",),
    "prod_gfx100rf": (r"gfx\s*100\s*rf",),
    "prod_a1ii": (r"ilce-1m2", r"(\balpha|α|\ba)\s*1\s*(ii|2)\b"),
    "prod_a7cr": (r"ilce-7cr", r"(\balpha|α|\ba)\s*7\s*cr\b"),
    "prod_z8": (r"\bz\s*8\b",),
    "prod_q3": (r"\bq3\b",),
    "prod_gr4": (r"\bgr\s*(iv|4)\b",),
    "prod_xt5": (r"\bx-?t5\b",),
    "prod_fx3": (r"ilme-fx3", r"\bfx3\b"),
}
# 目印に一致しても、型・版の違う商品の語があれば同じ商品にしない（監査 Low-C）
IDENTITY_EXCLUDE = {
    "prod_q3": (r"q3\s*43",),
    "prod_gr4": (r"\bhdf\b", r"monochrome"),
    "prod_ps5_pro": (r"\bslim\b", r"digital\s*edition"),
}
STAGE_SIZES = {"1": 1, "3": 3, "10": 10}
STAGE_PREV = {"3": "1", "10": "3"}       # この段階に上げるには、前の段階を通っている必要がある
CANARY = STAGED[:1]                      # Phase 12 の名前（既定の canary）


def _load_json(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def canary_passed(path: Path | None = None, product_id: str | None = None) -> bool:
    """canary（1商品）が合格した記録があるか（無ければ履歴に書かない・段階を上げない）。

    product_id を渡すと、その商品で合格したときだけ True（合格の後に canary の商品を変えたら、やり直す。レビュー L-5）。
    """
    d = _load_json(path or CANARY_PATH)
    return bool(d.get("passed")) and (product_id is None or d.get("product_id") == product_id)


def _strip_volatile(o, volatile: tuple):
    """入れ子の中の時刻のキーも除く（rollout.json の stages[*].checked_at など。レビュー L-4）。"""
    if isinstance(o, dict):
        return {k: _strip_volatile(v, volatile) for k, v in o.items() if k not in volatile}
    if isinstance(o, list):
        return [_strip_volatile(v, volatile) for v in o]
    return o


def _write_if_changed(path: Path, obj: dict, volatile: tuple = ("generated_at", "checked_at")) -> bool:
    """中身（時刻以外）が変わったときだけ書く（時刻だけの更新で生成物を毎日変えない）。"""
    from src.collectors.api.ebay_insights import dumps_safe
    old = _load_json(path)
    if old and _strip_volatile(old, volatile) == _strip_volatile(json.loads(dumps_safe(obj)), volatile):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_safe(obj), encoding="utf-8")
    return True


def canary_target() -> tuple[str, str]:
    """canary の商品（EBAY_SOLD_CANARY_PRODUCT が段階の一覧の中ならそれ。違えば既定）。"""
    want = (os.environ.get("EBAY_SOLD_CANARY_PRODUCT") or "").strip()
    for pid, q in STAGED:
        if pid == want:
            return pid, q
    return STAGED[0]


def is_canary_mode() -> bool:
    """canary の実行か（EBAY_SOLD_CANARY が false と明示され、canary の合格の記録があるときだけ履歴の実行）。"""
    v = (os.environ.get("EBAY_SOLD_CANARY") or "true").strip().lower()
    return v not in ("false", "0", "no", "off") or not canary_passed(product_id=canary_target()[0])


def allowed_stage(requested: str, rollout: dict | None = None) -> str:
    """使ってよい段階（前の段階を通っていなければ、通っている段階まで下げる）。"""
    stages = (rollout if rollout is not None else _load_json(ROLLOUT_PATH)).get("stages") or {}
    s = requested if requested in STAGE_SIZES else "1"
    while s in STAGE_PREV and not (stages.get(STAGE_PREV[s]) or {}).get("passed"):
        s = STAGE_PREV[s]
    return s


def history_targets(stage: str) -> list[tuple[str, str]]:
    """履歴の実行の対象（canary の商品を先頭に、段階の商品数だけ）。"""
    first = canary_target()
    rest = [t for t in STAGED if t[0] != first[0]]
    return ([first] + rest)[: STAGE_SIZES[stage]]


def stage_gate(records: list, rejected: dict, stats: dict, text: str) -> dict:
    """段階の関門（誤った成約・同一性の誤り・秘密の値・アクセス制限・重複・取得の失敗がすべて0、使える成約が1件以上）。"""
    from src.collectors.api.ebay_insights import redact
    from src.market.sold_history import dedupe_key, record_reasons
    keys = [dedupe_key(r) for r in records]
    checks = {
        "false_sold": sum(1 for r in records if record_reasons(r)),
        # resolver の判定に加えて、取得元の商品名に名前・型番の目印があるかを独立に確かめる（目印の無い商品は数えない）
        "identity_errors": sum(1 for r in records if not r.identity_verified or r.identity != r.product_id
                               or not _marker_ok(r)),
        "secret_leaks": int(redact(text) != text),
        "rate_violations": sum(v for k, v in rejected.items() if k.startswith("request_rate_limited")),
        "duplicates": len(keys) - len(set(keys)),
        "request_errors": sum(v for k, v in rejected.items() if k.startswith("request_")),
    }
    checks["accepted"] = len(records)
    checks["passed"] = all(v == 0 for k, v in checks.items() if k != "accepted") and len(records) > 0
    return checks


def _marker_ok(r) -> bool:
    import re as _re
    pats = IDENTITY_MARKERS.get(r.product_id)
    if not pats:
        return True
    title = str(r.title or "").lower()
    if any(_re.search(p, title) for p in IDENTITY_EXCLUDE.get(r.product_id, ())):
        return False
    return any(_re.search(p, title) for p in pats)


def canary_report(pid: str, query: str, records: list, rejected: dict, stats: dict, gate: dict,
                  now: datetime) -> dict:
    """canary の報告（秘密の値を含めない。生の応答は保存しない）。"""
    from src.collectors.api import ebay_insights as ei
    sold = sorted(r.sold_at for r in records)
    jpy = [r.sold_price for r in records]
    usd = [r.sold_price_original for r in records if r.sold_price_original is not None]
    return {
        "checked_at": now.isoformat(timespec="seconds"), "passed": bool(gate["passed"]),
        "product_id": pid, "query": query, "marketplace": ei.MARKETPLACE_ID,
        "returned": int(stats.get("returned") or 0), "accepted": len(records),
        "rejected": sum(v for k, v in rejected.items() if not k.startswith("request_")),
        "rejection_reasons": rejected, "requests": int(stats.get("requests") or 0),
        "sold_dates": {"first": sold[0] if sold else None, "last": sold[-1] if sold else None},
        "conditions": dict(Counter(r.condition for r in records)),
        "price_range_jpy": [min(jpy), max(jpy)] if jpy else None,
        "price_range_usd": [min(usd), max(usd)] if usd else None,
        "item_ids": [r.item_url.rsplit("/", 1)[-1] for r in records][:50],
        "licence": "CONFIRMED" if ei.gates()["licence"] else ei.ST_PENDING_LICENSE,
        "gate": gate,
        "note": "canary は履歴に書かない（ルート・利益商品に入らない）。合格の後に EBAY_SOLD_CANARY=false で段階の取得へ",
    }


def _http_get(url: str, headers: dict) -> dict:
    """api_runtime.retry_with_backoff の形の結果（例外の文言から秘密の値を伏せる）。"""
    from src.collectors.api.ebay_insights import redact
    try:
        from src.collectors.polite import HONEST_UA
        req = urllib.request.Request(url, headers={**headers, "User-Agent": HONEST_UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return {"status": r.getcode(), "data": json.loads(r.read().decode("utf-8")), "retry_after": None,
                    "exc": None}
    except urllib.error.HTTPError as e:
        # Retry-After は秒数・HTTP-date のどちらも api_runtime.parse_retry_after が読む
        ra = e.headers.get("Retry-After") if e.headers else None
        return {"status": e.code, "data": None, "retry_after": ra, "exc": RuntimeError(redact(str(e)))}
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
        from src.collectors.polite import HONEST_UA
        r = urllib.request.Request(url, data=body, headers={**headers, "User-Agent": HONEST_UA}, method="POST")
        with urllib.request.urlopen(r, timeout=30) as resp:
            tok = json.loads(resp.read().decode("utf-8")).get("access_token")
            return (tok, ei.ST_OK) if tok else (None, ei.ST_ERROR)
    except urllib.error.HTTPError as e:
        # 401: 資格情報が違う。400（invalid_scope）・403: 許可（承認）が無い。どちらも再試行しない
        return None, ei.status_from_error(f"permanent_{e.code}") if e.code in (400, 401, 403) else ei.ST_ERROR
    except Exception:  # noqa: BLE001
        return None, ei.ST_ERROR


def _status_body(now: datetime, status: str, *, mode: str, stage: str, targets: list, **kw) -> dict:
    from src.collectors.api import ebay_insights as ei
    return {"generated_at": now.isoformat(timespec="seconds"), "status": status, "gates": ei.gates(),
            "mode": mode, "stage": stage, "targets": [p for p, _ in targets],
            "network_used": bool(kw.pop("network_used", False)), **kw}


def main(argv=None) -> int:
    from src.collectors.api import ebay_insights as ei
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="送るリクエストの一覧だけを出す（ネットワークに出ない）")
    args = ap.parse_args(argv)
    now = datetime.now(tz=JST)
    canary = is_canary_mode()
    requested = (os.environ.get(ei.STAGE_ENV) or "1").strip()
    stage = "canary" if canary else allowed_stage(requested)
    targets = [canary_target()] if canary else history_targets(stage)
    st = ei.status()
    mode = "canary" if canary else "history"
    if args.dry_run or st != ei.ST_OK:
        out = ei.dry_run_plan(targets, now)
        out.update({"mode": mode, "stage": stage, "skipped": st != ei.ST_OK})
        print(ei.dumps_safe(out))
        if not args.dry_run:
            # 条件がそろっていない: 通信0。状態だけを書く（中身が変わったときだけ）
            _write_if_changed(STATUS_PATH, _status_body(now, st, mode=mode, stage=stage, targets=targets,
                                                        skipped=True))
        return 0
    token, tst = _fetch_token()
    if not token:
        print(ei.dumps_safe({"status": tst, "note": "token を取得できない（承認・資格情報を確認）"}))
        _write_if_changed(STATUS_PATH, _status_body(now, tst, mode=mode, stage=stage, targets=targets,
                                                    skipped=True, network_used=True))
        return 0
    from src.collectors.api.market_apis import load_fx_rate
    from src.market import sold_history as sh
    from src.market.product_identity_resolver import ProductIdentityResolver, build_products_index
    resolver = ProductIdentityResolver(build_products_index(ROOT / "data" / "premium_monitor.db"))
    fx = load_fx_rate("USD")
    budget = [ei.MAX_REQUESTS_PER_RUN]
    new, rejected, stats = [], {}, {}
    for pid, q in targets:
        recs, rej = ei.collect(pid, q, resolver=resolver, now=now, fx_rate=fx.get("rate"), http_get=_http_get,
                               token=token, request_budget=budget, fx_meta=fx, stats=stats)
        new.extend(recs)
        for k, v in rej.items():
            rejected[k] = rejected.get(k, 0) + v
        if stats.get("error_kind"):
            # アクセス制限（429）・認証（401）・許可（403）・連続の失敗で止まったら、残りの商品へ送らない
            # （長い待ちを商品の数だけ重ねて CI を延ばさない・同じ token で送り続けない。監査 M-1）
            break
    # 秘密の値の検査は、伏せる前の文字列で行う（成約の記録に token などが混ざっていないか）
    from dataclasses import asdict
    gate = stage_gate(new, rejected, stats, json.dumps([asdict(r) for r in new], ensure_ascii=False))
    run_status = ei.status_from_error(stats["error_kind"]) if stats.get("error_kind") else ei.ST_OK
    merge_stats = None
    if canary:
        # canary: 取得・変換・報告だけ（履歴に書かない）
        _write_if_changed(CANARY_PATH, canary_report(targets[0][0], targets[0][1], new, rejected, stats, gate, now))
    else:
        rollout = _load_json(ROLLOUT_PATH)
        stages = rollout.setdefault("stages", {})
        stages[stage] = {"passed": bool(gate["passed"]), "checked_at": now.isoformat(timespec="seconds"),
                         "gate": gate, "targets": [p for p, _ in targets]}
        if gate["passed"] and ei.gates()["licence"]:
            hist, merge_stats = sh.merge(sh.load(HISTORY_PATH), new)
            if merge_stats["added"] or merge_stats["updated"] or not HISTORY_PATH.exists():
                sh.save(hist, now, HISTORY_PATH)       # 増えた・置き換えたときだけ書く（時刻だけの更新をしない）
        _write_if_changed(ROLLOUT_PATH, rollout)
    _write_if_changed(STATUS_PATH, _status_body(
        now, run_status, mode=mode, stage=stage, targets=targets, skipped=False, network_used=True,
        requests_used=ei.MAX_REQUESTS_PER_RUN - budget[0], returned=stats.get("returned", 0),
        accepted=len(new), rejected=rejected, gate=gate, merge=merge_stats))
    print(f"成約の取得（{mode}・段階 {stage}）: 使える {len(new)} / 使わなかった "
          f"{sum(v for k, v in rejected.items() if not k.startswith('request_'))} / 関門 "
          f"{'通過' if gate['passed'] else '不通過'}"
          + (f" / 履歴 追加 {merge_stats['added']}・更新 {merge_stats['updated']}・重複 {merge_stats['duplicate']}"
             if merge_stats else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
