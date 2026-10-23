"""買取の一覧ページの全行の保存（買取起点の発見の入力）。

買取店の一覧ページの行（正本に無い商品も含む）を .private/research/buyback_catalog.json（.gitignore 済み・公開しない）に残す。
- 取得できた日だけ書き直す。取得できなかった日は前回の行をそのまま残し、観測の日時も変えない（失敗した日の時刻を成功として保存しない）
- 行の observed_at は実際に取得した時刻
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

SCHEMA = 1
SHOP = "kaitori_shouten"


def collect_rows(now: datetime) -> list[dict]:
    """この実行で買取商店の一覧ページから読んだ全行。"""
    from src.collectors import buyback_kaitori_shouten as ks
    stamp = now.isoformat(timespec="seconds")
    out = []
    for page, rows in sorted(ks.CATALOG_ROWS.items()):
        for r in rows:
            out.append({"shop": SHOP, "name": r.get("name", ""), "jan": r.get("jan", ""), "price": int(r.get("price") or 0),
                        "url": r.get("url", ""), "page": page, "observed_at": stamp})
    return out


def save(path: Path, rows: list[dict], now: datetime) -> bool:
    """行があるときだけ書く（無ければ前回のファイルを残す）。書いたら True。

    ページ（一覧の URL）単位で置き換える: この実行で行が取れたページだけを新しい行にし、取れなかったページは前回の行を
    そのまま残す（観測の日時も変えない）。ページ A だけ取れた日に、ページ B の前回の行を消さない。
    """
    if not rows:
        return False
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh_pages = {r.get("page") for r in rows}
    try:
        prev = json.loads(path.read_text(encoding="utf-8")).get("rows") or []
    except (OSError, ValueError, AttributeError):
        prev = []
    kept = [r for r in prev if isinstance(r, dict) and r.get("page") not in fresh_pages]
    doc = {"schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"),
           "note": "買取店の一覧ページの全行（買取起点の発見の入力）。正本ではない。取れなかったページは前回の行のまま（行ごとの "
                   "observed_at が取得した時刻）", "rows": kept + rows}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return True
