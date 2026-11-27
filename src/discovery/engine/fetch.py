"""一次情報の取得（polite 経由）と本文の保存（.private/discovery/docs/）。

- 実際の HTTP は scripts/recheck_official._fetch（robots.txt の確認・polite_wait の 60 秒以上の間隔・正直な User-Agent・
  リダイレクトをたどらない・403 で止める・文字コード）。このモジュールは HTTP を直接送らない
- fetch は差し替えられる（テストはネットワークに出ない）。形は _fetch と同じ (本文 | None, 失敗の理由)
- 取得の枠: 1 実行の総数・同じホストの数。超えたら SKIPPED_BUDGET（取りに行かない）
- 取得元（ホスト）単位の打ち切りは polite.ShopCutoff（403・429・robots はその実行の残りを取りに行かない。回避しない）
- 同じ本文（doc_id が同じ）なら fetched_at は最初の取得のまま（再取得で時刻だけを進めない。鮮度を偽装しない）
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from src.discovery.engine import models as m
from src.discovery.engine.urlpolicy import host_of

FetchFn = Callable[[str], tuple]

# 取得の枠（設計書 §4.2）
FRONTIER_MAX_TOTAL = 10
FRONTIER_MAX_PER_HOST = 2
PAGE_MAX_TOTAL = 20
PAGE_MAX_PER_HOST = 4

# この理由で失敗したら BLOCKED（それ以外は FAILED）
_BLOCK_REASONS = frozenset({"robots_disallowed", "robots_unreachable", "site_blocked", "http_401", "http_403",
                            "rate_limited_429", "cloudflare_blocked", "access_denied", "blocked_cloud_ip"})


def default_fetch(url: str):
    """既定の取得（polite。robots・間隔・正直な UA・リダイレクトをたどらない）。"""
    from scripts.recheck_official import _fetch  # noqa: PLC0415
    return _fetch(url)


class Fetcher:
    """取得の枠と取得元の打ち切りを守って取得する。"""

    def __init__(self, fetch: Optional[FetchFn] = None, *, max_total: int, max_per_host: int, cutoff=None):
        from src.collectors.polite import ShopCutoff
        self.fetch = fetch or default_fetch
        self.max_total = max_total
        self.max_per_host = max_per_host
        self.cutoff = cutoff if cutoff is not None else ShopCutoff()
        self.total = 0
        self.per_host: dict[str, int] = {}
        self.log: list[dict] = []

    def get(self, url: str) -> tuple[Optional[str], str, str]:
        """(本文 | None, 理由, 取得の状態)。"""
        host = host_of(url)
        if self.cutoff.is_cut(host):
            return None, self.cutoff.skip(host, url), m.SKIPPED_CUTOFF     # 要求していない（遮断された URL とは区別する）
        if self.total >= self.max_total or self.per_host.get(host, 0) >= self.max_per_host:
            return None, "budget_exhausted", m.SKIPPED_BUDGET
        self.total += 1
        self.per_host[host] = self.per_host.get(host, 0) + 1
        try:
            body, reason = self.fetch(url)
        except Exception as e:  # noqa: BLE001 - 1 件の失敗で実行を止めない
            body, reason = None, "connection_error" if "timeout" not in type(e).__name__.lower() else "timeout"
        ok = body is not None
        self.cutoff.record(host, ok, None if ok else (reason or "connection_error"))
        state = m.FETCHED if ok else (m.BLOCKED if reason in _BLOCK_REASONS else m.FAILED)
        self.log.append({"host": host, "state": state, "reason": "" if ok else reason})
        return body, ("" if ok else reason), state

    def cut_hosts(self) -> dict:
        return {h: v.get("reason") for h, v in self.cutoff.cut.items()}


class DocStore:
    """取得した本文の索引（.private/discovery/docs/index.json）と本文ファイル。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.index_path = self.root / "index.json"
        try:
            self.index = json.loads(self.index_path.read_text(encoding="utf-8"))
            if not isinstance(self.index, dict):
                self.index = {}
        except (OSError, ValueError):
            self.index = {}

    def make_doc(self, url: str, html: str, *, now: datetime, published_hint: Optional[str] = None) -> m.FetchedDoc:
        from src.discovery.engine.extract.evidence import normalize_html
        _title, text = normalize_html(html)
        doc_id = hashlib.sha256(text.encode("utf-8")).hexdigest()
        at = now.isoformat(timespec="seconds")
        prev = self.index.get(doc_id) or {}
        first = prev.get("fetched_at") if prev.get("url") == url else None
        return m.FetchedDoc(doc_id=doc_id, url=url, host=host_of(url), fetched_at=first or at, last_fetched_at=at,
                            text=text, text_path=str(Path(".private/discovery/docs") / f"{doc_id}.txt"),
                            published_hint=published_hint)

    def is_known(self, doc: m.FetchedDoc) -> bool:
        prev = self.index.get(doc.doc_id) or {}
        return prev.get("url") == doc.url

    def save(self, doc: m.FetchedDoc) -> None:
        from src.utils.atomic_write import write_text_atomic
        self.root.mkdir(parents=True, exist_ok=True)
        p = self.root / f"{doc.doc_id}.txt"
        if not p.exists():
            write_text_atomic(p, doc.text)
        self.index[doc.doc_id] = doc.index_entry()

    def flush(self) -> None:
        from src.utils.atomic_write import write_json_atomic
        self.root.mkdir(parents=True, exist_ok=True)
        write_json_atomic(self.index_path, self.index)
