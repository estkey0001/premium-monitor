#!/usr/bin/env python3
"""買取起点の候補の小売（公式直販）の価格を照会し、非公開の記録（.private/research/retail_lookups.json）に残す（Coverage Wave 2）。

- 入力: .private/research/buyback_catalog.json（買取店の一覧ページの全行。update_buyback_prices.py が残す）
- 取得は scripts/recheck_official._fetch（polite: robots.txt・取得元ごとの間隔・正直な User-Agent・リダイレクトを追わない）経由だけ。
  遮断（403・429・robots 禁止）された取得元は、その実行では取りに行かない。回避しない
- 出力は個別の価格・商品を含むので非公開（.gitignore 済み）。標準出力には件数だけ（公開ログに商品名・価格を出さない）
- 確定の利益ではない。ここで引けた価格は調査候補の「小売の価格のヒント」で、正本には入れない。失敗しても LP の更新は止めない
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _private_dir() -> Path:
    return Path(os.environ.get("RESEARCH_PRIVATE_DIR") or ROOT / ".private" / "research")


def _products() -> list[dict]:
    import yaml
    doc = yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8")) or {}
    return [{"id": p["id"], "name": p.get("name", ""), "genre": p.get("genre", ""), "jan": str(p.get("jan_code") or ""),
             "part_numbers": list(p.get("part_numbers") or [])} for p in doc.get("products") or [] if isinstance(p, dict) and p.get("id")]


def main(argv=None, fetch=None, now: datetime | None = None) -> int:
    from src.market import official_registry as reg
    from src.research import candidates as rc
    from src.research import retail_lookup as rl
    from src.tcg.models import now_jst
    now = now or now_jst()
    priv = _private_dir()
    try:
        rows = json.loads((priv / "buyback_catalog.json").read_text(encoding="utf-8")).get("rows") or []
    except (OSError, ValueError):
        print("[retail-lookup] 買取の一覧が無い・読めないので何もしない")
        return 0
    if fetch is None:
        import recheck_official
        fetch = recheck_official._fetch
    try:
        _matched, unmatched = rc.match_catalog(rows, _products(), getattr(reg, "IDENTITY_EVIDENCE", {}))
        dps, _stats = rc.rank_product_candidates(unmatched, now, {}, limit=None)
        rec = rl.run_lookups(dps, now, fetch)
    except Exception as exc:  # noqa: BLE001 - 付加の情報。失敗しても LP の更新は止めない（公開ログに値を出さない）
        print(f"[retail-lookup] 失敗（{type(exc).__name__}）。記録は更新しない（前回の記録は、結果ごとの取得時刻が36時間以内のものだけ使われる）")
        return 0
    priv.mkdir(parents=True, exist_ok=True)
    tmp = priv / "retail_lookups.json.tmp"
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(priv / "retail_lookups.json")
    print(f"[retail-lookup] 候補 {len(dps)} 件 / 照会の結果 {rec['status_counts']} / 取得した取得器 {rec['fetched_adapters']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
