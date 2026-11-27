"""商品起点の発見: クエリの生成・上限と持ち越し・検索の手掛かり → 公式ページの取り直し → 関門・店舗の追加候補（サンプルデータ。通信しない）。"""
import json
from datetime import date, datetime
from pathlib import Path

from src.discovery.engine import models as m
from src.discovery.engine.dedupe import ExistingIndex
from src.discovery.engine.run import run_engine
from src.discovery.engine.search import queries as q
from src.discovery.engine.search.fixture import FixtureSearchProvider
from src.discovery.engine.store_candidates import REQUIRED_EVIDENCE, registrable_domain
from src.discovery.engine.urlpolicy import UrlPolicy
from src.tcg.models import JST

FIX = Path(__file__).parent / "fixtures" / "discovery_engine"
NOW = datetime(2026, 11, 26, 12, 0, tzinfo=JST)
TODAY = date(2026, 11, 26)
PRODUCTS = [
    {"product_id": "pkm-test", "name": "拡張パック「テストフレア」BOX", "release_date": "2026-12-05"},       # 段 1（発売 9 日前）
    {"product_id": "op-19", "name": "ブースターパック 新世界【OP-19】", "release_date": "2027-02-27"},      # 段 2 か 3
    {"product_id": "old", "name": "拡張パック「むかし」", "release_date": "2025-01-01"},                    # 段 3
]
OFFICIAL = "https://www.pokemon-card.com/info/005700.html"
UNKNOWN = "https://www.example-tcg-shop.co.jp/news/1"
MERCARI = "https://jp.mercari.com/item/m123"


def test_seeds_use_core_name_code_and_registered_aliases_only():
    assert q.seeds_of(PRODUCTS[0]) == [("name", "テストフレア")]
    assert q.seeds_of(PRODUCTS[1]) == [("name", "ブースターパック 新世界"), ("code", "OP-19")]
    assert ("alias", "テスフレ") in q.seeds_of({**PRODUCTS[0], "aliases": ["テスフレ"]})


def test_tiers_words_and_buyback_is_a_separate_purpose():
    sel = dict((p["product_id"], t) for p, t in q.select_products(PRODUCTS, [], today=TODAY))
    assert sel["pkm-test"] == 1 and sel["old"] == 3
    active = q.select_products(PRODUCTS, [{"product_id": "old", "status": "OPEN"}], today=TODAY)
    assert dict((p["product_id"], t) for p, t in active)["old"] == 1             # 受付中の抽選がある商品は段 1
    qs = q.build_queries([(PRODUCTS[0], 1)], today=TODAY)
    assert {x.word for x in qs} == set(q.QUERY_WORDS) and all(x.text.startswith('"テストフレア"') for x in qs)
    assert [x.purpose for x in qs if x.word == "買取"] == ["buyback"]


def test_budget_rotates_so_overflow_is_used_on_later_days():
    qs = q.build_queries([(PRODUCTS[0], 1)], today=TODAY)
    lot = [x for x in qs if x.purpose == "lottery"]
    use1, later1 = q.apply_budget(qs, max_per_day=5, today=TODAY)
    assert len(use1) == 5 and len(later1) == len(lot) - 5
    assert all(x.purpose == "lottery" for x in use1 + later1)                 # 買取のクエリは抽選の枠を使わない
    used = {x.query_id for x in use1}
    for d in range(1, 10):
        used |= {x.query_id for x in q.apply_budget(qs, max_per_day=5, today=date.fromordinal(TODAY.toordinal() + d))[0]}
    assert used == {x.query_id for x in lot}                                  # 何日かで全部のクエリが使われる


def test_lower_tiers_keep_a_minimum_share_of_the_budget():
    many = [{"product_id": f"p{i}", "name": f"拡張パック「新{i}」", "release_date": "2026-12-01"} for i in range(10)]
    qs = [x for x in q.build_queries([(p, 1) for p in many], today=TODAY)]
    qs += [q.SearchQuery(query_id=f"t2-{i}", text="x", product_id="o", word="抽選", form="name", tier=2, purpose="lottery")
           for i in range(20)]
    qs += [q.SearchQuery(query_id=f"t3-{i}", text="x", product_id="o", word="再販", form="name", tier=3, purpose="lottery")
           for i in range(20)]
    use, _ = q.apply_budget(qs, max_per_day=40, today=TODAY)
    tiers = [x.tier for x in use]
    assert len(use) == 40 and tiers.count(2) >= 10 and tiers.count(3) >= 6     # 段 1 だけで枠を埋めない


def test_registrable_domain():
    assert registrable_domain("www.example-tcg-shop.co.jp") == "example-tcg-shop.co.jp"
    assert registrable_domain("shop.example.com") == "example.com"


class FakeFetch:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url):
        self.calls.append(url)
        v = self.pages.get(url)
        return (v, "") if v is not None else (None, "http_404")


def test_search_hits_flow_through_the_existing_gates_and_store_candidates(tmp_path):
    qs = q.build_queries([(PRODUCTS[0], 1)], today=TODAY)
    lot_q = next(x for x in qs if x.word == "抽選")
    buy_q = next(x for x in qs if x.word == "買取")
    hits = tmp_path / "hits.json"
    hits.write_text(json.dumps({lot_q.query_id: [OFFICIAL, UNKNOWN, MERCARI], buy_q.query_id: [UNKNOWN + "?b=1"]}), encoding="utf-8")
    cfg = tmp_path / "f.yaml"
    cfg.write_text("schema: 1\nsources: []\n", encoding="utf-8")
    ff = FakeFetch({OFFICIAL: (FIX / "lottery_page.html").read_text(encoding="utf-8")})
    rep = run_engine(now=NOW, fetch=ff, apply=True, config_path=cfg, private_dir=tmp_path / "p", ledger_dir=tmp_path / "l",
                     registry={"POKEMON": [{"product_id": "pkm-test", "name": "拡張パック「テストフレア」BOX"}], "ONE_PIECE": []},
                     existing=ExistingIndex(), policy=UrlPolicy(excluded={}), search_provider=FixtureSearchProvider(hits),
                     queries=qs)
    s = rep["search"]
    assert s["provider"] == "fixture" and s["skipped_buyback"] == 1 and s["leads"] == 3
    assert ff.calls == [OFFICIAL]                                             # 公式だけを取り直す（未知の店・メルカリは取得しない）
    assert rep["url_decision"] == {m.ACCEPT_PRIMARY: 1, m.ACCEPT_HINT_ONLY: 1, m.REJECT_MARKETPLACE: 1}
    assert sum(rep["routed"].values()) == 1                                    # 本文の根拠で関門を通り、候補の台帳へ
    sc = json.loads((tmp_path / "p" / "store_candidates.json").read_text(encoding="utf-8"))["candidates"]
    c = sc["example-tcg-shop.co.jp"]
    assert c["status"] == "NEW" and c["product_ids"] == ["pkm-test"] and set(c["missing_evidence"]) == set(REQUIRED_EVIDENCE)
    for ld in rep["_search_leads"]:                                            # スニペット・タイトルは持たない
        assert not {"title", "snippet", "description"} & set(ld)
        assert ld["found_by"] == "search:fixture" and ld["seed_id"] == "pkm-test"
    assert "jp.mercari.com" not in json.dumps(sc)


def test_pokemon_discovery_ignores_one_piece_rows_merged_into_the_registry(tmp_path):
    from src.discovery import store as st
    from src.discovery import tcg as tg
    d = tmp_path / "tcg"
    d.mkdir()
    g = NOW.isoformat()
    (d / "pokemon_registry.json").write_text(json.dumps({"generated_at": g, "products": [
        {"product_id": "pkm-a", "tcg": "POKEMON", "name": "拡張パック「A」", "official_url": "https://www.pokemon-card.com/ex/m9/"},
        {"product_id": "op-18", "tcg": "ONE_PIECE", "name": "ブースターパック 神の支配【OP-18】"}]}), encoding="utf-8")
    for f in ("lotteries.json", "lottery_sources.json", "latest.json"):
        (d / f).write_text(json.dumps({"generated_at": g, "items": [], "sources": [], "events": [], "announcements": []}), encoding="utf-8")
    tg.run(d, tmp_path, now=NOW)
    pcs = st.load(tmp_path / st.PRODUCT_FILE)["candidates"].values() if hasattr(st, "PRODUCT_FILE") else []
    assert not [c for c in pcs if c.get("source") == "pokemon_card_official" and "OP-18" in json.dumps(c, ensure_ascii=False)]


def test_search_leads_skip_stopped_urls_across_runs(tmp_path):
    from src.tcg.lottery.pipeline import normalize_url
    qs = [x for x in q.build_queries([(PRODUCTS[0], 1)], today=TODAY) if x.word == "抽選"]
    hits = tmp_path / "hits.json"
    hits.write_text(json.dumps({qs[0].query_id: [OFFICIAL]}), encoding="utf-8")
    cfg = tmp_path / "f.yaml"
    cfg.write_text("schema: 1\nsources: []\n", encoding="utf-8")
    priv = tmp_path / "p"
    priv.mkdir()
    (priv / "frontier_state.json").write_text(json.dumps({"schema": 1, "sources": {},
                                                          "stopped": {normalize_url(OFFICIAL): "2026-11-25T12:00:00+09:00"}}),
                                              encoding="utf-8")
    ff = FakeFetch({OFFICIAL: "<html>x</html>"})
    rep = run_engine(now=NOW, fetch=ff, apply=True, config_path=cfg, private_dir=priv, ledger_dir=tmp_path / "l", registry={},
                     existing=ExistingIndex(), policy=UrlPolicy(excluded={}), search_provider=FixtureSearchProvider(hits), queries=qs)
    assert ff.calls == [] and rep["search"]["skipped_known_or_stopped"] == 1      # 前回に遮断された URL を叩き直さない
    state = json.loads((priv / "frontier_state.json").read_text(encoding="utf-8"))
    assert normalize_url(OFFICIAL) in state["stopped"]                             # 停止の記録は次の実行に引き継ぐ


def test_blocked_search_lead_is_recorded_as_stopped(tmp_path):
    from src.tcg.lottery.pipeline import normalize_url
    qs = [x for x in q.build_queries([(PRODUCTS[0], 1)], today=TODAY) if x.word == "抽選"]
    hits = tmp_path / "hits.json"
    hits.write_text(json.dumps({qs[0].query_id: [OFFICIAL]}), encoding="utf-8")
    cfg = tmp_path / "f.yaml"
    cfg.write_text("schema: 1\nsources: []\n", encoding="utf-8")

    def blocked(url):
        return None, "http_403"
    run_engine(now=NOW, fetch=blocked, apply=True, config_path=cfg, private_dir=tmp_path / "p", ledger_dir=tmp_path / "l",
               registry={}, existing=ExistingIndex(), policy=UrlPolicy(excluded={}),
               search_provider=FixtureSearchProvider(hits), queries=qs)
    state = json.loads((tmp_path / "p" / "frontier_state.json").read_text(encoding="utf-8"))
    assert normalize_url(OFFICIAL) in state["stopped"]


def test_registered_source_domains_are_not_store_candidates():
    from src.discovery.engine.store_candidates import collect_host_hints
    from src.discovery.engine import models as mm
    leads = [mm.Lead(lead_id="a", url="https://www.mugiwara-store.com/news/1/", host="www.mugiwara-store.com", found_by="search:x",
                     first_seen_at="", last_seen_on="", url_decision=mm.ACCEPT_HINT_ONLY),
             mm.Lead(lead_id="b", url="https://shop.example-new.co.jp/n/1", host="shop.example-new.co.jp", found_by="search:x",
                     first_seen_at="", last_seen_on="", url_decision=mm.ACCEPT_HINT_ONLY)]
    assert list(collect_host_hints(leads)) == ["example-new.co.jp"]
