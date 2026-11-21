#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCG の国内買取価格（Route T1）を、買取店自身のページから取得して exports/tcg/buyback.json に書く。

- 取得は src/collectors/polite.py を通す（robots.txt・同じドメインの間隔・正直な User-Agent・取得元の打ち切り）。
- 取得に失敗した店・ページの古い行は、取得時刻を進めずにそのまま残す（鮮度で STALE になり、利益に使われない）。
- 履歴は exports/tcg/buyback_history.json（同じ日・同じ商品・店・単位・条件は 1 件）。
- 失敗しても終了コードは 0（古い価格が STALE になるだけ）。Daily LP を止めない。

使い方: python scripts/collect_tcg_buyback.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors import polite  # noqa: E402
from src.tcg import buyback as bb  # noqa: E402

logger = logging.getLogger("collect_tcg_buyback")
OUT = PROJECT_ROOT / "exports" / "tcg" / "buyback.json"
HIST = PROJECT_ROOT / "exports" / "tcg" / "buyback_history.json"

_LAST = {"reason": ""}


def fetch(url: str, timeout: int = 20):
    """HTML を取得する。失敗したら None（理由は _LAST["reason"]）。ブロックされたら別の手段で取り直さない。"""
    _LAST["reason"] = ""
    if not polite.robots_allowed(url):
        _LAST["reason"] = polite.robots_block_reason(url)
        return None
    polite.polite_wait(url)
    try:
        import requests
        resp = requests.get(url, headers={"User-Agent": polite.HONEST_UA, "Accept-Language": "ja,en;q=0.9"}, timeout=timeout, allow_redirects=False)       # リダイレクト先は robots.txt を確認していないので追わない
    except Exception as e:  # noqa: BLE001
        _LAST["reason"] = "timeout" if "timeout" in type(e).__name__.lower() else "connection_error"
        return None
    if resp.status_code != 200:
        _LAST["reason"] = polite.status_reason(resp.status_code)
        return None
    if len(resp.text) < 500:
        _LAST["reason"] = "empty_html"
        return None
    return resp.text


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def collect(cfg: dict, prev_rows: list, now: datetime, fetcher=fetch) -> tuple[list, dict]:
    """(新しい行, 店ごとの状態)。失敗した URL の行は前回のまま引き継ぐ。"""
    cutoff = polite.ShopCutoff()
    rows: list = []
    state: dict = {}
    jobs: list = []                                    # (shop, url)
    for key, shop in (cfg.get("shops") or {}).items():
        for u in shop.get("pages") or []:
            jobs.append((key, u))
    for t in cfg.get("targets") or []:
        for key, u in (t.get("pages") or {}).items():
            jobs.append((key, u))
    for key, url in jobs:
        st = state.setdefault(key, {"pages_ok": 0, "pages_failed": 0, "rows": 0, "reason": None})
        keep_prev = [{**r, "carried_over": True} for r in prev_rows if r.get("shop") == key and r.get("source_url") == url]
        if cutoff.is_cut(key):
            cutoff.skip(key, url)
            st["pages_failed"] += 1
            st["reason"] = cutoff.cut[key]["reason"]
            rows.extend(keep_prev)
            continue
        html = fetcher(url)
        observed = datetime.now(bb.JST) if fetcher is fetch else now
        if html is None:
            reason = _LAST["reason"] or "fetch_failed"
            cutoff.record(key, False, reason)
            st["pages_failed"] += 1
            st["reason"] = reason
            rows.extend(keep_prev)                     # 取れなかったページの行は前回のまま（時刻を進めない）
            continue
        if key == "rudeya":
            got = bb.parse_rudeya(html, url, observed)["rows"]
        elif key == "kaitorishouten":
            r = bb.parse_kaitorishouten(html, url, observed)
            got = [r] if r else []
        else:
            got = []
        if not got:
            cutoff.record(key, False, "price_not_found")
            st["pages_failed"] += 1
            st["reason"] = "price_not_found"
            rows.extend(keep_prev)
            continue
        cutoff.record(key, True)
        st["pages_ok"] += 1
        st["rows"] += len(got)
        rows.extend(got)
    for key, st in state.items():
        st["state"] = ("OK" if st["pages_failed"] == 0 and st["pages_ok"] else
                       "PARTIAL" if st["pages_ok"] else "FAILED")
        st["checked_at"] = now.isoformat()
    return rows, state


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = bb.load_config()
    now = datetime.now(bb.JST)
    prev = _load(OUT, {})
    prev_rows = [r for r in prev.get("rows", []) if isinstance(r, dict)] if isinstance(prev, dict) else []
    rows, state = collect(cfg, prev_rows, now)
    export, hist = bb.build_export(rows, _load(HIST, []), state, cfg, now)
    c = export["counts"]
    print(f"TCG 買取: 行 {c['rows']} / 同一性確認 {c['confirmed']} / 実行可能 {c['executable']} / "
          f"買取のある商品 {c['products_listed']}（うち実行可能 {c['products_with_executable']}）")
    for k, s in state.items():
        print(f"  {k}: {s['state']} ページ OK {s['pages_ok']} / 失敗 {s['pages_failed']}" + (f"（{s['reason']}）" if s["reason"] else ""))
    if args.dry_run:
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(export, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    HIST.write_text(json.dumps(hist, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
