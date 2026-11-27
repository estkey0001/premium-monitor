"""発見のエンジン: frontier（sitemap・RSS・一覧の差分）・URL の選別・取得の枠（通信しない）。"""
from datetime import datetime
from pathlib import Path

import pytest

from src.discovery.engine import models as m
from src.discovery.engine.fetch import DocStore, Fetcher
from src.discovery.engine.frontier import discover, load_config, parse_feed, parse_list, parse_sitemap
from src.discovery.engine.urlpolicy import SOURCE_CANDIDATES, UrlPolicy, policy_excluded_domains
from src.tcg.models import JST

FIX = Path(__file__).parent / "fixtures" / "discovery_engine"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=JST)
SITEMAP = "https://www.pokemon-card.com/sitemap.xml"
PKM = "https://www.pokemon-card.com/info/2026/11/"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


class FakeFetch:
    """URL → 本文 か (None, 理由)。呼ばれた URL を記録する（通信しない）。"""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        v = self.pages.get(url)
        if isinstance(v, tuple):
            return v
        if v is None:
            return None, "http_404"
        return v, ""


def _src(kind="sitemap", url=SITEMAP, **kw):
    return dict({"id": f"s_{kind}", "kind": kind, "url": url, "enabled": True, "checked_on": "2026-11-26"}, **kw)


def _fetcher(pages, total=10, per_host=2):
    return Fetcher(FakeFetch(pages), max_total=total, max_per_host=per_host)


# ── 解析 ───────────────────────────────────────────────────────────────
def test_parse_sitemap_and_index():
    items, is_index = parse_sitemap(_read("sitemap.xml"))
    assert not is_index and (PKM + "lottery_new.html", "2026-11-20") in items
    assert parse_sitemap(_read("sitemap_index.xml")) == ([], True)


def test_xml_with_doctype_is_not_parsed():
    xml = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><urlset><url><loc>&a;</loc></url></urlset>'
    assert parse_sitemap(xml) == ([], False)


def test_parse_rss_and_atom():
    rss = parse_feed(_read("feed.xml"))
    assert rss[0] == ("https://www.onepiece-cardgame.com/information/news_lottery_01.php", "2026-11-20T10:00:00+09:00")
    atom = parse_feed(_read("atom.xml"))
    assert atom == [("https://www.onepiece-cardgame.com/information/yoyaku_02.php", "2026-11-21T09:00:00+09:00")]


def test_parse_list_resolves_and_strips_fragment():
    out = parse_list(_read("list_page.html"), "https://www.pokemon-card.com/info/")
    urls = [u for u, _d, _t in out]
    assert PKM + "lottery_new.html" in urls                       # 相対 → 絶対・#top を外す
    assert not any(u.startswith("javascript:") for u in urls)


# ── 設定 ───────────────────────────────────────────────────────────────
def test_load_config_reads_only_enabled_and_checked():
    use, skip = load_config(FIX / "frontier.yaml")
    assert [s["id"] for s in use] == ["pkm_sitemap", "op_rss"]
    assert {s["id"]: s["reason"] for s in skip} == {"disabled_one": "disabled", "unchecked_one": "not_checked_by_human"}
    assert load_config(FIX / "missing.yaml") == ([], [{"id": "", "reason": "config_not_found"}])


# ── 差分 ───────────────────────────────────────────────────────────────
def _state(urls):
    return {"sources": {"s_sitemap": {"url": SITEMAP, "kind": "sitemap", "urls": urls}}}


def test_sitemap_diff_new_and_lastmod_advanced_only():
    prev = _state({PKM + "lottery_old.html": "2026-10-01", PKM + "lottery_updated.html": "2026-11-01"})
    res = discover([_src(include=["lottery"])], prev, _fetcher({SITEMAP: _read("sitemap.xml")}), now=NOW)
    got = {ld.url: ld.decision_reason for ld in res.leads}
    assert got == {PKM + "lottery_new.html": "new_url", PKM + "lottery_updated.html": "lastmod_advanced"}
    assert all(ld.found_by == m.FOUND_SITEMAP and ld.host == "www.pokemon-card.com" for ld in res.leads)
    # 別ホストの loc・語で絞られた URL は Lead にしない
    assert not any("other.example.com" in u or "company" in u for u in got)
    assert res.ok_hosts == {"pokemon-card.com"}


def test_same_lastmod_is_not_a_lead():
    prev = _state({PKM + "lottery_old.html": "2026-10-01", PKM + "lottery_new.html": "2026-11-20",
                   PKM + "lottery_updated.html": "2026-11-21"})
    res = discover([_src(include=["lottery"])], prev, _fetcher({SITEMAP: _read("sitemap.xml")}), now=NOW)
    assert res.leads == []


def test_first_run_is_baseline_only_unless_bootstrap():
    res = discover([_src(include=["lottery"])], {}, _fetcher({SITEMAP: _read("sitemap.xml")}), now=NOW)
    assert res.leads == [] and res.baseline == ["s_sitemap"]
    assert set(res.state["sources"]["s_sitemap"]["urls"]) == {PKM + "lottery_old.html", PKM + "lottery_new.html",
                                                             PKM + "lottery_updated.html"}
    res2 = discover([_src(include=["lottery"])], {}, _fetcher({SITEMAP: _read("sitemap.xml")}), now=NOW, bootstrap=True)
    assert len(res2.leads) == 3


def test_rss_drops_other_host_and_marketplace():
    src = _src("rss", "https://www.onepiece-cardgame.com/rss.xml")
    res = discover([src], {"sources": {"s_rss": {"urls": {}}}},
                   _fetcher({src["url"]: _read("feed.xml")}), now=NOW)
    assert [ld.url for ld in res.leads] == ["https://www.onepiece-cardgame.com/information/news_lottery_01.php"]
    assert res.leads[0].lastmod == "2026-11-20T10:00:00+09:00"


def test_list_only_same_host():
    src = _src("list", "https://www.pokemon-card.com/info/")
    res = discover([src], {"sources": {"s_list": {"urls": {}}}},
                   _fetcher({src["url"]: _read("list_page.html")}), now=NOW)
    urls = {ld.url for ld in res.leads}
    assert PKM + "lottery_new.html" in urls
    assert not any(h in u for u in urls for h in ("x.com", "cardchusen", "company", "javascript"))


def test_failed_source_keeps_previous_state_and_host_not_ok():
    prev = _state({PKM + "lottery_old.html": "2026-10-01"})
    res = discover([_src()], prev, _fetcher({SITEMAP: (None, "http_403")}), now=NOW)
    assert res.leads == [] and res.failed["s_sitemap"].startswith("BLOCKED")
    assert res.state["sources"]["s_sitemap"]["urls"] == {PKM + "lottery_old.html": "2026-10-01"}
    assert res.ok_hosts == set()


def test_sitemap_index_is_not_followed():
    res = discover([_src()], _state({}), _fetcher({SITEMAP: _read("sitemap_index.xml")}), now=NOW)
    assert res.failed["s_sitemap"] == "sitemap_index_not_followed" and res.leads == []


def test_non_official_or_excluded_source_is_not_fetched():
    ff = FakeFetch({})
    f = Fetcher(ff, max_total=10, max_per_host=2)
    res = discover([_src("list", "https://www.pokemoncenter-online.com/news/", id="pco"),
                    _src("list", "https://blog.example.com/news/", id="blog")], {}, f, now=NOW)
    assert ff.calls == [] and set(res.failed) == {"pco", "blog"}
    assert "policy_excluded" in res.failed["pco"]


# ── URL の選別 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("url", [
    "https://jp.mercari.com/item/m123", "https://fril.jp/item/1", "https://item.fril.jp/abc",
    "https://www.amazon.co.jp/dp/B000", "https://auctions.yahoo.co.jp/search/search?p=x",
    "https://page.auctions.yahoo.co.jp/jp/auction/x1", "https://www.ebay.com/itm/1",
    "https://item.rakuten.co.jp/shop/item/", "https://books.rakuten.co.jp/rb/1/", "https://search.rakuten.co.jp/search/mall/x/",
])
def test_marketplaces_are_rejected(url):
    assert UrlPolicy(excluded={}).decide(url)[0] == m.REJECT_MARKETPLACE


@pytest.mark.parametrize("url", ["https://x.com/pokemon_cojp/status/1", "https://twitter.com/a/status/1",
                                 "https://cardchusen.com/pokemon", "https://www.cardchusen.com/onepiece/"])
def test_sns_and_comparison_site_are_rejected(url):
    assert UrlPolicy(excluded={}).decide(url)[0] == m.REJECT_POLICY


def test_every_policy_excluded_source_is_rejected():
    import yaml
    excluded = policy_excluded_domains()
    data = yaml.safe_load(SOURCE_CANDIDATES.read_text(encoding="utf-8"))
    targets = [c["url"] for c in data["candidates"] if c.get("policy_excluded") and c.get("url")]
    assert len(targets) >= 10
    pol = UrlPolicy(excluded=excluded)
    for u in targets:
        dec, why = pol.decide(u.rstrip("/") + "/news/lottery.html")
        assert dec in (m.REJECT_POLICY, m.REJECT_MARKETPLACE), (u, dec, why)
    # OFFICIAL_DOMAINS に入っていても拒否が先（ポケモンセンターオンライン・ヨドバシ）
    assert pol.decide("https://www.pokemoncenter-online.com/lottery/")[0] == m.REJECT_POLICY
    assert pol.decide("https://www.yodobashi.com/ec/lottery/")[0] == m.REJECT_POLICY


def test_search_results_and_non_http_are_rejected():
    pol = UrlPolicy(excluded={})
    assert pol.decide("https://www.pokemon-card.com/search/?q=box") == (m.REJECT_POLICY, "search_results_page")
    assert pol.decide("https://www.onepiece-cardgame.com/products/?keyword=op")[0] == m.REJECT_POLICY
    assert pol.decide("ftp://www.pokemon-card.com/x")[0] == m.REJECT_POLICY


def test_robots_and_accept():
    pol = UrlPolicy(excluded={}, robots_fn=lambda u: "robots_disallowed" if "/private/" in u else
                    ("robots_unreachable" if "geo-online" in u else ""))
    assert pol.decide("https://www.pokemon-card.com/private/a.html") == (m.REJECT_ROBOTS, "robots_disallowed")
    assert pol.decide("https://www.geo-online.co.jp/a.html") == (m.REJECT_ROBOTS, "robots_unreachable")
    assert pol.decide(PKM + "lottery_new.html")[0] == m.ACCEPT_PRIMARY
    assert pol.decide(PKM + "lottery_new.html/")[0] == m.REJECT_DUP
    assert pol.decide("https://www.c-labo.jp/news/1")[0] == m.ACCEPT_PRIMARY      # 運営者の証拠のある店舗
    assert pol.decide("https://blog.example.com/a")[0] == m.ACCEPT_HINT_ONLY


# ── 取得の枠・打ち切り ─────────────────────────────────────────────────
def test_fetcher_budget_and_cutoff():
    ff = FakeFetch({"https://a.example/1": "x", "https://a.example/2": "x", "https://a.example/3": "x",
                    "https://b.example/1": (None, "http_403"), "https://b.example/2": "x"})
    f = Fetcher(ff, max_total=4, max_per_host=2)
    assert f.get("https://a.example/1")[2] == m.FETCHED
    assert f.get("https://a.example/2")[2] == m.FETCHED
    assert f.get("https://a.example/3")[2] == m.SKIPPED_BUDGET         # 同じホストの枠
    assert f.get("https://b.example/1")[2] == m.BLOCKED                # 403 → その実行では打ち切り
    assert f.get("https://b.example/2")[2] == m.SKIPPED_CUTOFF         # 取りに行かない（回避しない）。要求していないので遮断とは区別する
    assert "https://b.example/2" not in ff.calls
    assert f.cut_hosts() == {"b.example": "http_403"}


def test_docstore_keeps_first_fetched_at_for_same_body(tmp_path):
    ds = DocStore(tmp_path)
    d1 = ds.make_doc(PKM + "a.html", "<title>t</title><p>本文</p>", now=NOW)
    ds.save(d1)
    later = datetime(2026, 11, 27, 12, 0, tzinfo=JST)
    d2 = ds.make_doc(PKM + "a.html", "<title>t</title><p>本文</p>", now=later)
    assert d2.doc_id == d1.doc_id and d2.fetched_at == d1.fetched_at and d2.last_fetched_at != d1.fetched_at
    assert ds.is_known(d2)
    d3 = ds.make_doc(PKM + "a.html", "<title>t</title><p>本文が変わった</p>", now=later)
    assert d3.fetched_at == later.isoformat(timespec="seconds") and not ds.is_known(d3)


def test_engine_modules_do_not_send_http_directly():
    """HTTP は polite（scripts/recheck_official._fetch）経由だけ。requests・urllib の通信・通知・登録を import しない。"""
    root = Path(__file__).resolve().parents[1] / "src" / "discovery" / "engine"
    import re
    for p in root.rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import requests|from requests|import urllib\.request|from urllib\.request|"
                             r"import httpx|from httpx|import aiohttp)", src, re.M), p
        assert not re.search(r"from src\.(notifiers|notifications)|from src\.discovery\.register|import register", src), p
