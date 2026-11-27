"""店舗の台帳の追加候補（固定の店舗リストの外で見つけたドメイン）。非公開（.private/discovery/store_candidates.json）。

- 入力は、検索で見つけた URL のうち一次情報として扱えないもの（UrlPolicy の ACCEPT_HINT_ONLY）。取得しない
- 持つもの: 登録ドメイン・ホスト・見つけた回数・日数・クエリ ID・商品 ID・初めて見た日。URL の一覧・タイトル・スニペットは持たない
- 台帳に足すには、人が次を確かめる（REQUIRED_EVIDENCE）。自動で一次情報（ACCEPT_PRIMARY）に上げない:
  operator（法人名）・evidence_url（会社概要か特定商取引法の表記）・strength（company_profile / tokusho）・
  chain_or_branch（チェーン本体 / 支店・加盟店）・robots_checked_on・terms_checked_on（規約を読んだ日）
- 状態: NEW → （人が確認）→ REGISTERED / REJECTED（403・CAPTCHA・規約の禁止は回避しないで REJECTED）
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from src.discovery.engine import models as m
from src.discovery.engine.urlpolicy import host_of

REQUIRED_EVIDENCE = ("operator", "evidence_url", "strength", "chain_or_branch", "robots_checked_on", "terms_checked_on")
ST_NEW, ST_REGISTERED, ST_REJECTED = "NEW", "REGISTERED", "REJECTED"
_TWO_LEVEL = ("co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp", "ed.jp", "gr.jp", "lg.jp", "co.uk", "com.au")


def registrable_domain(host: str) -> str:
    """ホスト → 登録ドメイン（簡易: co.jp 等の 2 段の後ろは 3 ラベル、それ以外は 2 ラベル）。"""
    h = (host or "").lower().strip(".")
    if h.startswith("www."):
        h = h[4:]
    parts = h.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _TWO_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else h


def collect_host_hints(leads: Iterable) -> dict:
    """一次情報として扱えない検索の手掛かり（ACCEPT_HINT_ONLY）→ {登録ドメイン: {hosts, queries, products, hits}}。"""
    from src.tcg.lottery.registry import LOTTERY_SOURCES, source_profile
    registered = {registrable_domain(d) for src in LOTTERY_SOURCES for d in source_profile(src["source_id"])["official_domains"]}
    out: dict = {}
    for ld in leads:
        if getattr(ld, "url_decision", None) != m.ACCEPT_HINT_ONLY:
            continue
        dom = registrable_domain(host_of(ld.url))
        if not dom or dom in registered:
            continue                       # 登録済みの取得元のドメインは追加候補にしない（運営者の証拠の不足は台帳の側で扱う）
        r = out.setdefault(dom, {"hosts": set(), "queries": set(), "products": set(), "hits": 0})
        r["hosts"].add(host_of(ld.url))
        if ld.query_id:
            r["queries"].add(ld.query_id)
        if ld.seed_id:
            r["products"].add(ld.seed_id)
        r["hits"] += 1
    return out


def upsert_store_candidates(store: dict, hints: dict, *, now: datetime) -> dict:
    """台帳（{"schema": 1, "candidates": {登録ドメイン: {...}}}）を更新して、件数を返す。人の判断（REGISTERED / REJECTED）は変えない。"""
    store.setdefault("schema", 1)
    cands = store.setdefault("candidates", {})
    day = now.strftime("%Y-%m-%d")
    added = updated = 0
    for dom, h in sorted(hints.items()):
        c = cands.get(dom)
        if c is None:
            c = cands[dom] = {"domain": dom, "status": ST_NEW, "first_seen_on": day, "days_seen": [],
                              "hosts": [], "query_ids": [], "product_ids": [], "hits": 0,
                              # 人が確かめて書く欄（法人・チェーンと支店を分ける・公式 SNS・告知の一覧）
                              "chain_name": None, "branch_name": None, "official_sns": [], "notice_list_url": None,
                              **{k: None for k in REQUIRED_EVIDENCE}}
            added += 1
        else:
            updated += 1
        c["hosts"] = sorted(set(c["hosts"]) | set(h["hosts"]))
        c["query_ids"] = sorted(set(c["query_ids"]) | set(h["queries"]))[:50]
        c["product_ids"] = sorted(set(c["product_ids"]) | set(h["products"]))
        c["hits"] = int(c.get("hits") or 0) + int(h["hits"])
        if day not in c["days_seen"]:
            c["days_seen"] = (c["days_seen"] + [day])[-30:]
        c["last_seen_on"] = day
        c["missing_evidence"] = [k for k in REQUIRED_EVIDENCE if not c.get(k)]
    return {"added": added, "updated": updated, "total": len(cands)}
