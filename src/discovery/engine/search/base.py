"""検索 API の Provider の窓口。

返すのは URL とどのクエリで出たかだけ（タイトル・スニペットは持たない。規約上の保存の禁止に備える）。
検索由来の URL はその実行の中で取得まで進め、取得できた URL だけを残す（設計書 §2.2）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchHit:
    url: str
    query_id: str


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, *, query_id: str, limit: int) -> list[SearchHit]:
        ...
