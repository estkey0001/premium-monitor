"""eBay Browse API の Production canary（手動実行のみ・1 商品・1 リクエスト・成約 API には通信しない）。

    python scripts/ebay_browse_canary.py

資格情報（EBAY_CLIENT_ID / EBAY_CLIENT_SECRET）・ENABLE_EBAY_API=true・API_DRY_RUN=false がそろったときだけ通信する。
結果は標準出力と GITHUB_STEP_SUMMARY に出す（件数・状態・出品の公開情報だけ。リポジトリには書かない）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from src.collectors.api import ebay_insights as ei
    from src.research import ebay_adapter as ea
    rep = ea.browse_canary(os.environ)
    text = ei.redact(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    for k in ("EBAY_CLIENT_SECRET", "EBAY_CLIENT_ID"):                    # 念のため: 資格情報の値が出力に混ざっていないこと
        v = os.environ.get(k) or ""
        if len(v) >= 6 and v in text:
            print("ABORT: 出力に資格情報の値が含まれたため破棄した")
            return 3
    print(text)
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        with open(summ, "a", encoding="utf-8") as f:
            f.write("## eBay Browse canary\n\n```json\n" + text + "\n```\n")
    return 0 if str(rep.get("verdict_hint", "")).startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
