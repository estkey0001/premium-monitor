"""検索しない Provider（無料・外部契約なしの最小の基盤）。常にゼロ件。"""
from __future__ import annotations

from src.discovery.engine.search.base import SearchHit


class NullSearchProvider:
    name = "null"

    def search(self, query: str, *, query_id: str, limit: int) -> list[SearchHit]:
        return []
