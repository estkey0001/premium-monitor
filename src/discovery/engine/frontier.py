"""API を使わない URL の発見: 既知の公式ドメインの sitemap・RSS/Atom・一覧ページから、前回に無かった URL を Lead にする。

設定（既定 config/discovery_frontier.yaml。人が robots.txt・規約を確認した日付と根拠を書く）:

    schema: 1
    sources:
      - id: onepiece_news
        kind: list            # sitemap / rss / list
        url: https://www.onepiece-cardgame.com/information/
        enabled: false        # 人が確認するまで false（false は読まない）
        checked_on: ""        # robots.txt・規約を確認した日（空なら読まない）
        evidence: ""          # 確認の根拠（robots.txt の該当行・規約の条項）
        include: ["抽選", "lottery", "news"]   # URL・リンクの文字で絞る語（省略時は既定の語）

- 同じホストの URL だけ（別ホストのリンク・sitemap の別ホストの loc は Lead にしない）
- 前回の既知の集合との差分だけを Lead にする。sitemap の lastmod / RSS の日付が進んだ URL も Lead にする
  （同じなら Lead にしない）
- 初回（その取得元の前回の記録が無い）は基準づくりだけで Lead にしない（bootstrap=True のときだけ Lead にする）
- sitemap index の子 sitemap はたどらない（設定に具体的な sitemap を書く）
- 取得に失敗した取得元は前回の記録を変えない（見えなくなったと判定しない）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urljoin, urlsplit

from src.discovery.engine import models as m
from src.discovery.engine.urlpolicy import UrlPolicy, host_of, is_primary_host

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "discovery_frontier.yaml"
KINDS = ("sitemap", "rss", "list")
_FOUND = {"sitemap": m.FOUND_SITEMAP, "rss": m.FOUND_RSS, "list": m.FOUND_LIST}
DEFAULT_INCLUDE = ("抽選", "予約", "再販", "応募", "lottery", "chusen", "yoyaku", "reserve", "entry", "news", "info",
                   "topics", "release")


def _bare(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def load_config(path: Optional[Path] = None) -> tuple[list[dict], list[dict]]:
    """(読む取得元, 読まない取得元と理由)。enabled: true かつ checked_on があるものだけ読む。"""
    p = Path(path) if path else DEFAULT_CONFIG
    try:
        import yaml
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return [], [{"id": "", "reason": "config_not_found"}]
    except Exception:  # noqa: BLE001 - YAML の形の誤り
        return [], [{"id": "", "reason": "config_invalid"}]
    use, skip = [], []
    for s in data.get("sources") or [] if isinstance(data, dict) else []:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "")
        if s.get("kind") not in KINDS or not s.get("url") or not sid:
            skip.append({"id": sid, "reason": "invalid_source"})
        elif s.get("enabled") is not True:
            skip.append({"id": sid, "reason": "disabled"})
        elif not str(s.get("checked_on") or "").strip():
            skip.append({"id": sid, "reason": "not_checked_by_human"})
        else:
            use.append(s)
    return use, skip


# ── 解析（通信しない）──────────────────────────────────────────────────
def _xml_root(xml: str):
    import xml.etree.ElementTree as ET
    if re.search(r"<!DOCTYPE|<!ENTITY", xml or "", re.I):
        return None                                   # DTD・実体の宣言は読まない（実体の展開をさせない）
    try:
        root = ET.fromstring((xml or "").encode("utf-8"))
    except ET.ParseError:
        return None
    for el in root.iter():                            # 名前空間を外す
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_sitemap(xml: str) -> tuple[list[tuple[str, Optional[str]]], bool]:
    """sitemap → ([(loc, lastmod)], sitemap index か)。"""
    root = _xml_root(xml)
    if root is None:
        return [], False
    if root.tag == "sitemapindex":
        return [], True
    out = []
    for u in root.iter("url"):
        loc = (u.findtext("loc") or "").strip()
        if loc:
            out.append((loc, (u.findtext("lastmod") or "").strip() or None))
    return out, False


def _feed_date(s: Optional[str]) -> Optional[str]:
    """RSS の pubDate（RFC 822）・Atom の updated（ISO）→ ISO 8601（+09:00）。読めなければ None。"""
    if not s:
        return None
    from src.tcg.models import JST, parse_dt
    d = parse_dt(s.strip())
    if d is None:
        try:
            from email.utils import parsedate_to_datetime
            d = parsedate_to_datetime(s.strip())
        except (TypeError, ValueError, IndexError):
            return None
        if d is None:
            return None
        d = d.astimezone(JST) if d.tzinfo else d.replace(tzinfo=JST)
    return d.isoformat()


def parse_feed(xml: str) -> list[tuple[str, Optional[str]]]:
    """RSS 2.0 / RSS 1.0 / Atom → [(link, 日付)]。"""
    root = _xml_root(xml)
    if root is None:
        return []
    out = []
    for it in list(root.iter("item")):
        link = (it.findtext("link") or "").strip()
        if link:
            out.append((link, _feed_date(it.findtext("pubDate") or it.findtext("date"))))
    for en in root.iter("entry"):
        link = ""
        for ln in en.findall("link"):
            if ln.get("rel") in (None, "alternate") and ln.get("href"):
                link = ln.get("href").strip()
                break
        if link:
            out.append((link, _feed_date(en.findtext("updated") or en.findtext("published"))))
    return out


def parse_list(html: str, base_url: str) -> list[tuple[str, Optional[str], str]]:
    """一覧ページ → [(絶対 URL, None, リンクの文字)]。フラグメントは外す。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        u = urljoin(base_url, href).split("#", 1)[0]
        text = " ".join(a.get_text(" ").split())
        # 「詳しくはコチラ」のようなリンクの文字だけの一覧では、題名がリンクの外（同じカードの中）にある。
        # リンクを囲む要素を、別の URL へのリンクを含まず・文字数が _CARD_TEXT_MAX を超えない範囲でさかのぼり、その文字も判定に使う
        # （隣の記事の題名・一覧全体の文字は使わない）
        card, node = "", a.parent
        while node is not None and getattr(node, "name", None) not in (None, "[document]", "body", "html"):
            others = {urljoin(base_url, str(x["href"]).strip()).split("#", 1)[0] for x in node.find_all("a", href=True)
                      if str(x["href"]).strip() and not str(x["href"]).strip().startswith(_NOT_LINK)} - {u, base_url.split("#", 1)[0]}
            t = " ".join(node.get_text(" ").split())
            if others or len(t) > _CARD_TEXT_MAX:
                break
            card, node = t, node.parent
        out.append((u, None, (text + " " + card).strip() if card and card != text else text))
    return out


_CARD_TEXT_MAX = 300
_NOT_LINK = ("#", "javascript:", "mailto:", "tel:")             # 共有ボタン等（別の記事へのリンクに数えない）


def _wanted(url: str, text: str, include) -> bool:
    hay = (unquote(url) + " " + (text or "")).lower()
    return any(str(w).lower() in hay for w in include)


def _path_matches(url: str, patterns) -> bool:
    """URL のパス（＋クエリ）が、取得元の抽選の記事の形のどれかに合うか。"""
    sp = urlsplit(url)
    target = sp.path + (("?" + sp.query) if sp.query else "")
    return any(p.search(target) for p in patterns)


def _newer(new: Optional[str], old: Optional[str]) -> bool:
    from src.tcg.models import parse_dt
    a, b = parse_dt(new), parse_dt(old)
    return bool(a and b and a > b)


@dataclass
class FrontierResult:
    leads: list = field(default_factory=list)            # Lead
    listed: dict = field(default_factory=dict)           # 取得元 id → 今回並んでいた URL（正規化）の集合
    ok_hosts: set = field(default_factory=set)           # 今回すべての取得元を読めたホスト
    failed: dict = field(default_factory=dict)           # 取得元 id → 理由
    skipped: list = field(default_factory=list)          # 読まなかった取得元と理由
    baseline: list = field(default_factory=list)         # 初回で基準づくりだけした取得元
    state: dict = field(default_factory=dict)            # 次回に渡す既知の集合


def discover(sources: list[dict], state: dict, fetcher, *, now: datetime, bootstrap: bool = False,
             policy: Optional[UrlPolicy] = None) -> FrontierResult:
    """frontier の取得元を読み、Lead（前回に無かった URL）を作る。"""
    from src.discovery.store import stable_id
    from src.tcg.lottery.pipeline import normalize_url
    res = FrontierResult(state={"schema": 1, "sources": dict((state or {}).get("sources") or {})})
    policy = policy or UrlPolicy()
    seen_leads: set[str] = set()
    hosts_failed: set[str] = set()
    hosts_seen: set[str] = set()
    for s in sources:
        sid, kind, surl = str(s["id"]), s["kind"], str(s["url"])
        shost = _bare(host_of(surl))
        hosts_seen.add(shost)
        dec, why = policy.decide(surl) if policy else (m.ACCEPT_PRIMARY, "")
        policy.seen.discard(normalize_url(surl))
        if dec != m.ACCEPT_PRIMARY or not is_primary_host(surl):
            res.failed[sid] = f"source_not_allowed:{dec}:{why}"
            hosts_failed.add(shost)
            continue
        body, reason, fstate = fetcher.get(surl)
        if body is None:
            res.failed[sid] = f"{fstate}:{reason}"
            hosts_failed.add(shost)
            continue
        if kind == "sitemap":
            items, is_index = parse_sitemap(body)
            entries = [(u, lm, "") for u, lm in items]
            if is_index:
                res.failed[sid] = "sitemap_index_not_followed"
                hosts_failed.add(shost)
                continue
        elif kind == "rss":
            entries = [(u, d, "") for u, d in parse_feed(body)]
        else:
            entries = parse_list(body, surl)
        include = s.get("include") or DEFAULT_INCLUDE
        patterns = [re.compile(p) for p in (s.get("url_patterns") or [])]
        prev_src = res.state["sources"].get(sid)
        known: dict = dict((prev_src or {}).get("urls") or {})
        current: dict = {}
        # 同じ URL へのリンクが複数ある一覧（画像のリンク＋題名のリンク）では、リンクの文字をまとめて絞り込む
        texts: dict = {}
        for u, _lm, text in entries:
            k = normalize_url(u)
            texts[k] = (texts.get(k, "") + " " + (text or "")).strip()
        entries = [(u, lm, texts.get(normalize_url(u), text)) for u, lm, text in entries]
        for u, lm, text in entries:
            if _bare(host_of(u)) != shost or urlsplit(u).scheme not in ("http", "https"):
                continue                                     # 別ホスト・http(s) でないものは Lead にしない
            if not _wanted(u, text, include):
                continue
            if patterns and not _path_matches(u, patterns):
                continue                                     # 抽選の記事の URL の形でない（一覧・タグ・カテゴリのページ）
            key = normalize_url(u)
            if key == normalize_url(surl) or key in current:
                continue
            current[key] = lm or ""
            is_new = key not in known
            advanced = (not is_new) and _newer(lm, known.get(key) or None)
            if prev_src is None and not bootstrap:
                continue                                     # 初回は基準づくりだけ
            if (is_new or advanced) and key not in seen_leads:
                seen_leads.add(key)
                lead = m.Lead(lead_id=stable_id("ld", key), url=u, host=host_of(u), found_by=_FOUND[kind],
                              first_seen_at=now.isoformat(timespec="seconds"), last_seen_on=now.strftime("%Y-%m-%d"),
                              source_url=surl, lastmod=lm or None,
                              decision_reason="lastmod_advanced" if advanced else "new_url")
                res.leads.append(lead)
        if prev_src is None:
            res.baseline.append(sid)
        res.listed[sid] = set(current)
        # 見えなくなった URL も既知のまま残す（一覧から落ちて戻ってきた URL を新規と数えない）
        merged = dict(known)
        merged.update(current)
        res.state["sources"][sid] = {"url": surl, "kind": kind, "urls": merged,
                                     "last_ok_at": now.isoformat(timespec="seconds")}
    res.ok_hosts = {h for h in hosts_seen if h not in hosts_failed}
    return res
