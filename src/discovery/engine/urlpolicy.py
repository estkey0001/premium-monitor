"""URL の選別（取得してよいか・根拠にしてよいか）。

判定の順（拒否が許可より先。OFFICIAL_DOMAINS に amazon.co.jp・rakuten.co.jp・yodobashi.com 等が入っていても拒否する）:
1. http(s) でない・ホストが無い → REJECT_POLICY
2. マーケットプレイス（メルカリ・ラクマ・Amazon・ヤフオク・eBay・楽天）→ REJECT_MARKETPLACE（公式 API だけを使う方針）
3. SNS（x.com・twitter.com）・比較サイト（cardchusen.com）・config/tcg_source_candidates.yaml の policy_excluded の取得元
   → REJECT_POLICY（403・Cloudflare・規約の禁止。検索で見つかっても取得しない・回避しない）
4. 検索結果のページ（/search・?q= 等）→ REJECT_POLICY（検索結果は取得しない）
5. 同じ実行の中で既に判定した URL → REJECT_DUP
6. robots.txt の禁止・到達不能（robots_fn を渡したときだけ。取得の直前にも fetch が確かめる）→ REJECT_ROBOTS
7. 公式ドメイン（manual.OFFICIAL_DOMAINS）・運営者の証拠のある店舗（STORE_PRIMARY_DOMAINS）→ ACCEPT_PRIMARY
8. それ以外 → ACCEPT_HINT_ONLY（根拠にしない。今回は取得もしない）
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import parse_qs, urlsplit

from src.discovery.engine import models as m

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_CANDIDATES = PROJECT_ROOT / "config" / "tcg_source_candidates.yaml"

# マーケットプレイス（スクレイピングしない。公式 API だけ）
MARKETPLACE_DOMAINS: tuple[str, ...] = (
    "mercari.com", "mercari.jp", "merpay.com",          # メルカリ（jp.mercari.com を含む）
    "fril.jp", "rakuma.rakuten.co.jp",                  # ラクマ
    "amazon.co.jp", "amazon.com", "amazon.jp", "amzn.to", "amzn.asia",
    "auctions.yahoo.co.jp", "page.auctions.yahoo.co.jp", "paypayfleamarket.yahoo.co.jp",   # ヤフオク・Yahoo!フリマ
    "ebay.com", "ebay.co.jp", "ebay.co.uk",
    "rakuten.co.jp", "rakuten.com", "r10.to",           # 楽天（楽天市場・楽天ブックス等すべて）
)
# 取得しない方針の取得元（SNS・比較サイト）
POLICY_DENY_DOMAINS: tuple[str, ...] = (
    "x.com", "twitter.com", "t.co",
    "cardchusen.com",
)
_SEARCH_PATH = re.compile(r"/(search|find|query)(/|$|\.)", re.I)
_SEARCH_QUERY_KEYS = frozenset({"q", "query", "keyword", "keywords", "kw", "search", "word", "k", "searchword"})


def host_of(url: str) -> str:
    return (urlsplit(url or "").hostname or "").lower()


def _in(host: str, domains: Iterable[str]) -> Optional[str]:
    for d in domains:
        if host == d or host.endswith("." + d):
            return d
    return None


def policy_excluded_domains(path: Path = SOURCE_CANDIDATES) -> dict:
    """tcg_source_candidates.yaml の policy_excluded の取得元のドメイン → 理由。
    読めないときは例外にしてエンジンを止める（拒否リストが黙って空になり、除外した取得元を取りに行くのを防ぐ）。"""
    import yaml
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"取得しない取得元の一覧（{Path(path).name}）が読めない。発見のエンジンを止める: {e}") from e
    out = {}
    for c in data.get("candidates") or []:
        if not isinstance(c, dict) or not c.get("policy_excluded"):
            continue
        h = host_of(str(c.get("url") or ""))
        if h:
            out[h[4:] if h.startswith("www.") else h] = str(c.get("id") or "")
    return out


def is_search_results(url: str) -> bool:
    sp = urlsplit(url or "")
    if _SEARCH_PATH.search(sp.path or ""):
        return True
    keys = {k.lower() for k in parse_qs(sp.query or "")}
    return bool(keys & _SEARCH_QUERY_KEYS)


def is_primary_host(url: str) -> bool:
    from src.tcg.lottery.manual import is_official_url, is_store_primary_url
    return is_official_url(url) or is_store_primary_url(url)


class UrlPolicy:
    def __init__(self, *, excluded: Optional[dict] = None, robots_fn: Optional[Callable[[str], str]] = None):
        self.excluded = policy_excluded_domains() if excluded is None else excluded
        self.robots_fn = robots_fn
        self.seen: set[str] = set()

    def decide(self, url: str) -> tuple[str, str]:
        """(判定, 理由)。"""
        from src.tcg.lottery.pipeline import normalize_url
        sp = urlsplit(url or "")
        host = (sp.hostname or "").lower()
        if sp.scheme not in ("http", "https") or not host:
            return m.REJECT_POLICY, "not_http_url"
        d = _in(host, MARKETPLACE_DOMAINS)
        if d:
            return m.REJECT_MARKETPLACE, f"marketplace:{d}"
        d = _in(host, POLICY_DENY_DOMAINS)
        if d:
            return m.REJECT_POLICY, f"policy_deny:{d}"
        d = _in(host, self.excluded)
        if d:
            return m.REJECT_POLICY, f"policy_excluded:{self.excluded[d] or d}"
        if is_search_results(url):
            return m.REJECT_POLICY, "search_results_page"
        key = normalize_url(url)
        if key in self.seen:
            return m.REJECT_DUP, "duplicate_in_run"
        self.seen.add(key)
        if self.robots_fn is not None:
            r = self.robots_fn(url)
            if r:
                return m.REJECT_ROBOTS, r
        if is_primary_host(url):
            return m.ACCEPT_PRIMARY, "official_or_store_primary"
        return m.ACCEPT_HINT_ONLY, "not_official_domain"
