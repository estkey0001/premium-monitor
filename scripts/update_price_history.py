#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商品ごとの価格の履歴を更新する（実際に観測した値だけを積み上げる。src/market/price_history.py）。

入力: exports/normalized_price_observations/latest.json（今回の観測）、exports/price_history/latest.json（前回の履歴）
出力: exports/price_history/latest.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.market import price_history as ph  # noqa: E402
from src.tcg.models import JST  # noqa: E402
from src.utils.atomic_write import write_json_atomic  # noqa: E402

NPO_PATH = ROOT / "exports" / "normalized_price_observations" / "latest.json"
OUT_PATH = ROOT / "exports" / "price_history" / "latest.json"


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main() -> int:
    obs = (_load(NPO_PATH, {}) or {}).get("observations") or []
    prev = _load(OUT_PATH, None) if OUT_PATH.exists() else ph.empty()
    if not (isinstance(prev, dict) and isinstance(prev.get("series"), dict)):
        # 前回の履歴が読めないときは、空から作り直して上書きしない（履歴を消さない）
        print(f"[update_price_history] 前回の履歴を読めないため更新しません: {OUT_PATH.name}", file=sys.stderr)
        return 1
    hist = ph.merge(prev, obs)
    hist["updated_at"] = datetime.now(tz=JST).isoformat(timespec="seconds")   # ファイルを更新した時刻（観測時刻ではない）
    write_json_atomic(OUT_PATH, hist)
    n = sum(len(s["points"]) for s in hist["series"].values())
    print(f"[update_price_history] 系列 {len(hist['series'])} / 点 {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
