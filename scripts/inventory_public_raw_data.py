#!/usr/bin/env python3
"""公開リポジトリ・公開サイトに出ている「商品単位の価格・取得元・除外理由」を含むファイルの一覧（Wave 1 Stage J）。

第三者が公開済みの観測・診断から調査候補を再計算できるかの判断材料。**一覧を作るだけで、削除・変更はしない**。
値（商品名・価格）は出力に含めない（ファイルの場所・種類・件数だけ）。

    python scripts/inventory_public_raw_data.py            # Markdown を標準出力へ
    python scripts/inventory_public_raw_data.py --write    # internal/audits/PUBLIC_RAW_DATA_INVENTORY.md を書く
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIRS = ("exports", "docs", "data", "audit_health")
OUT = ROOT / "internal" / "audits" / "PUBLIC_RAW_DATA_INVENTORY.md"

PRODUCT_KEYS = {"product_id", "product", "product_name", "product_alias", "alias", "name"}
PRICE_KEYS = {"price", "buyback_price", "official_price", "retail_price", "observed_price", "min_price", "max_price",
              "sell_price", "buy_price", "profit", "net_profit_jpy", "spread", "official_price_jpy"}
SOURCE_KEYS = {"source", "source_id", "source_name", "shop", "shop_id", "retailer", "store", "buyback_shop", "source_url",
               "item_url", "url", "official_url", "target_url"}
REASON_KEYS = {"reason", "reasons", "exclusion_reasons", "rejection_reason", "primary", "missing_requirements",
               "needed", "blocked_reason", "primary_reason", "main_blocked_reason"}
KINDS = (("商品別の価格", PRICE_KEYS), ("取得元・URL", SOURCE_KEYS), ("除外・不足の理由", REASON_KEYS))


def _walk(obj, found: dict, depth: int = 0) -> None:
    """商品らしいキーを持つオブジェクトのうち、価格・取得元・理由のキーも持つものを数える。"""
    if depth > 8:
        return
    if isinstance(obj, dict):
        keys = set(obj)
        if keys & PRODUCT_KEYS:
            for label, kk in KINDS:
                if keys & kk:
                    found[label] = found.get(label, 0) + 1
        for v in obj.values():
            _walk(v, found, depth + 1)
    elif isinstance(obj, list):
        for v in obj[:5000]:
            _walk(v, found, depth + 1)


def tracked_public_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", *PUBLIC_DIRS], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    return [ROOT / p for p in out if p.endswith(".json") and (ROOT / p).is_file()]


def inventory() -> list[dict]:
    rows = []
    for f in tracked_public_files():
        rel = str(f.relative_to(ROOT))
        if "/history/" in rel:
            continue                      # 日次の履歴は同じ形のコピー。本体のファイルだけ数える
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found: dict = {}
        _walk(data, found)
        if found:
            rows.append({"path": rel, "kinds": found, "total": sum(found.values())})
    rows.sort(key=lambda r: (-r["total"], r["path"]))
    return rows


def render(rows: list[dict]) -> str:
    lines = ["# 公開成果物の商品単位データの一覧（Raw Data Exposure Inventory）", "",
             "公開リポジトリ・GitHub Pages に出ている JSON のうち、**商品ごとの価格・取得元（店・URL）・除外・不足の理由**を持つもの。",
             "第三者が公開済みの観測・診断から調査候補を再計算できるかの判断材料である。**一覧を作るだけで、削除・変更はしない**。",
             "値（商品名・価格）はここに書かない。件数は、商品らしいキー（`product_id`・`name` など）を持つオブジェクトのうち、",
             "各種類のキーも持つものの数（同じオブジェクトが複数の種類に数えられる）。日次の `history/` は同じ形のコピーなので除く。",
             "生成: `python scripts/inventory_public_raw_data.py --write`。", "",
             "| ファイル | 商品別の価格 | 取得元・URL | 除外・不足の理由 |", "|---|---:|---:|---:|"]
    for r in rows:
        k = r["kinds"]
        lines.append(f"| `{r['path']}` | {k.get('商品別の価格', 0)} | {k.get('取得元・URL', 0)} | {k.get('除外・不足の理由', 0)} |")
    both = [r for r in rows if r["kinds"].get("商品別の価格") and r["kinds"].get("除外・不足の理由")]
    lines += ["", f"- 対象のファイル: {len(rows)} 件。うち、商品別の価格と除外・不足の理由の両方を持つもの: {len(both)} 件。",
              "- 調査候補の再計算に直接使えるのは、`exports/normalized_price_observations/latest.json`（商品別の価格・売却元・鮮度）と "
              "`exports/opportunity_diagnostics/latest.json`（商品別の除外理由・公式価格）。",
              "- これらは既存の画面・診断・テスト・通知の入力でもあるため、公開粒度を変えるには別の判断（運営者）が要る。今回は変更しない。", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    text = render(inventory())
    if "--write" in argv:
        OUT.write_text(text, encoding="utf-8")
        print(f"書いた: {OUT.relative_to(ROOT)}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
