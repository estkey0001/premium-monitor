"""公式ソースのレジストリ（区分・公式ドメイン・お知らせ一覧・抽選の記事の URL の形）と、変更検知（frontier）への接続。通信しない。"""
import re
from datetime import datetime

from src.discovery.engine.fetch import Fetcher
from src.discovery.engine.frontier import discover
from src.discovery.engine.urlpolicy import UrlPolicy
from src.tcg.lottery import registry as r
from src.tcg.models import JST

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=JST)
LIST = "https://www.pokemon-card.com/info/"


class FakeFetch:
    def __init__(self, pages):
        self.pages = pages

    def __call__(self, url):
        v = self.pages.get(url)
        return (v, "") if v is not None else (None, "http_404")


def test_every_registered_source_has_a_tier():
    for s in r.LOTTERY_SOURCES:
        p = r.source_profile(s["source_id"])
        assert p["tier"] in r.TIERS + ("",), s["source_id"]
        assert p["official_domains"], s["source_id"]
    assert set(r.SOURCE_PROFILE) <= set(r.SOURCE_BY_ID)          # 登録に無い取得元の情報を持たない
    # 運営者の証拠が見つからない取得元には区分を付けない（表示もしない）
    assert r.source_profile("MUGIWARA_STORE")["tier"] == "" and r.source_profile("ONEPIECE_CARD_OFFICIAL_SHOP")["tier"] == ""


def test_patterns_are_valid_regex_and_list_urls_are_on_official_domains():
    for sid in r.SOURCE_PROFILE:
        p = r.source_profile(sid)
        for pat in p["lottery_url_patterns"]:
            re.compile(pat)
        for u in p["list_urls"]:
            assert r._domain_of(u) in p["official_domains"], (sid, u)


def test_frontier_sources_only_from_checked_working_sources():
    fs = r.frontier_sources()
    ids = {s["source_id"] for s in fs}
    assert fs and len({s["url"] for s in fs}) == len(fs)          # 同じ一覧を二重に読まない
    for s in fs:
        src = r.SOURCE_BY_ID[s["source_id"]]
        assert src["adapter"] and src["verified"] and not src.get("policy_excluded")
        assert s["checked_on"] and s["enabled"] is True and s["kind"] == "list"
    # 遮断（GEO）・取得しない方針（PLANT・Amazon）・URL の差分で検知できない（トレカプラザ55）は読まない
    assert not ids & {"GEO", "PLANT", "AMAZON", "TORECAPLAZA55", "POKEMON_CENTER_ONLINE"}


def test_url_patterns_keep_only_lottery_articles():
    html = """
      <a href="/info/123456.html"><img src="x.png"></a><a href="/info/123456.html">抽選販売のお知らせ</a>
      <a href="/info/category/lottery/">抽選カテゴリ</a>
      <a href="/info/654321.html">大会のお知らせ</a>
      <a href="/info/777777.html">予約受付について</a>"""
    src = {"id": "registry:POKEMON_CARD_OFFICIAL", "kind": "list", "url": LIST, "enabled": True,
           "checked_on": "2026-11-26", "include": list(r.LOTTERY_KEYWORDS), "url_patterns": [r"^/info/\d+\.html$"]}
    f = Fetcher(FakeFetch({LIST: html}), max_total=5, max_per_host=5)
    res = discover([src], {}, f, now=NOW, bootstrap=True, policy=UrlPolicy(excluded={}))
    urls = sorted(ld.url for ld in res.leads)
    # 画像だけのリンクも、同じ URL の題名のリンクの文字で判定する。カテゴリの一覧・抽選でない記事は Lead にしない
    assert urls == ["https://www.pokemon-card.com/info/123456.html", "https://www.pokemon-card.com/info/777777.html"]


def test_card_title_outside_the_link_is_used_but_not_the_neighbors():
    from pathlib import Path

    from src.discovery.engine.frontier import parse_list
    html = (Path(__file__).parent / "fixtures" / "hbst" / "list_news.html").read_text(encoding="utf-8")
    texts = {u: t for u, _, t in parse_list(html, "https://www.hbst.net/result/?category=news") if "?p=" in u}
    assert "抽選販売" in texts["https://www.hbst.net/?p=900001"]           # リンクの文字は「詳しくはコチラ」だけ
    assert "休業" in texts["https://www.hbst.net/?p=900003"] and "抽選" not in texts["https://www.hbst.net/?p=900003"]


def test_second_run_detects_only_new_announcements():
    src = {"id": "registry:POKEMON_CARD_OFFICIAL", "kind": "list", "url": LIST, "enabled": True,
           "checked_on": "2026-11-26", "include": list(r.LOTTERY_KEYWORDS), "url_patterns": [r"^/info/\d+\.html$"]}
    first = '<a href="/info/1.html">抽選のお知らせ</a>'
    res1 = discover([src], {}, Fetcher(FakeFetch({LIST: first}), max_total=5, max_per_host=5), now=NOW,
                    policy=UrlPolicy(excluded={}))
    assert res1.leads == [] and res1.baseline == ["registry:POKEMON_CARD_OFFICIAL"]   # 初回は基準づくりだけ
    second = first + '<a href="/info/2.html">再販の抽選受付</a>'
    res2 = discover([src], res1.state, Fetcher(FakeFetch({LIST: second}), max_total=5, max_per_host=5), now=NOW,
                    policy=UrlPolicy(excluded={}))
    assert [ld.url for ld in res2.leads] == ["https://www.pokemon-card.com/info/2.html"]
    assert res2.leads[0].first_seen_at == NOW.isoformat(timespec="seconds")          # 検出の時刻（検出遅延の計測に使う）


def test_share_buttons_in_a_card_do_not_hide_the_title():
    from src.discovery.engine.frontier import parse_list
    html = ('<div class="card"><h3>ポケモンカード抽選販売のお知らせ</h3><a href="/?p=1">詳しくはコチラ</a>'
            '<a href="#">共有</a><a href="javascript:void(0)">閉じる</a></div>'
            '<div class="card"><h3>店休日のお知らせ</h3><a href="/?p=2">詳しくはコチラ</a></div>')
    t = {u: x for u, _, x in parse_list(html, "https://www.hbst.net/result/?category=news")}
    assert "抽選販売" in t["https://www.hbst.net/?p=1"] and "抽選" not in t["https://www.hbst.net/?p=2"]


def test_run_engine_reads_registry_lists_once_each_without_budget_cut(tmp_path):
    from src.discovery.engine.run import run_engine
    calls = []

    def fetch(url):
        calls.append(url)
        return "<html></html>", ""
    cfg = tmp_path / "f.yaml"
    cfg.write_text("schema: 1\nsources:\n  - {id: dup, kind: list, url: \"https://www.pokemon-card.com/info/\", enabled: true, "
                   "checked_on: \"2026-11-26\", evidence: x}\n", encoding="utf-8")
    rep = run_engine(now=NOW, fetch=fetch, config_path=cfg, private_dir=tmp_path / "p", ledger_dir=tmp_path / "l",
                     registry={}, existing=None, use_registry=True, policy=UrlPolicy(excluded={}))
    lists = [u for u in calls if u in {s["url"] for s in r.frontier_sources()}]
    assert len(lists) == len(set(lists))                                    # 設定と同じ一覧は1回だけ
    assert rep["sources"]["used"] == len(r.frontier_sources())              # 設定の1件＋レジストリ（同じ URL を除く）
    assert not any("budget" in str(v) for v in rep.get("frontier_failed", {}).values())


def test_store_master_separates_chain_and_branches_and_counts_findings():
    hist = [{"retailer": "CARD_LABO", "store_specific": True, "store_name": "カードラボ池袋店", "source_url": "https://www.c-labo.jp/shop/i/blog/1/"},
            {"retailer": "CARD_LABO", "store_specific": True, "store_name": "カードラボ池袋店", "source_url": "https://www.c-labo.jp/shop/i/blog/1/?utm_source=x"},
            {"retailer": "CARD_LABO", "store_specific": True, "store_name": "カードラボ難波店", "source_url": "https://www.c-labo.jp/shop/n/blog/2/"}]
    rows = {x["source_id"]: x for x in r.store_master(hist)}
    cl = rows["CARD_LABO"]
    assert cl["branches"] == 2 and cl["lotteries_found"] == 2              # 計測用のパラメータの違いは 1 件
    assert r._drop_tracking("https://www.hbst.net/?p=1&utm_medium=x") == "https://www.hbst.net/?p=1"   # 記事のクエリは残す
    assert cl["primary_evidence"] == "company_profile" and cl["tier_label"] == "大手チェーン"
    assert rows["MUGIWARA_STORE"]["primary_evidence"] is None and rows["MUGIWARA_STORE"]["tier_label"] == ""
    assert rows["PLANT"]["collection"] == "停止（方針）" and rows["CARDBOX"]["official_sns"] == []
