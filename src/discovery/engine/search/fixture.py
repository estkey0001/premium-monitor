"""通信しない検索の Provider（サンプルデータでの一連の検証用）。JSON {query_id: [url, ...]} を返すだけ。

検索の結果は URL だけ（タイトル・スニペットは読まない・持たない）。キーが無いクエリは 0 件。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.discovery.engine.search.base import SearchHit


class FixtureSearchProvider:
    name = "fixture"

    def __init__(self, path):
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        self.hits = {str(k): [str(u) for u in v if isinstance(u, str)] for k, v in (d or {}).items() if isinstance(v, list)}

    def search(self, query: str, *, query_id: str, limit: int) -> list[SearchHit]:
        return [SearchHit(url=u, query_id=query_id) for u in self.hits.get(query_id, [])[:max(0, limit)]]
