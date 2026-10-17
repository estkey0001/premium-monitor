"""Phase 27（新商品・新しいイベントの発見の候補）のテスト。

ネットワークには出ない（Apple のページは本物と同じ形の小さな HTML・TCG は生成物の形の JSON）。正本（config/products.yaml・
products の表）を変えないことを確かめる。各テストに否定の対照を付ける。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.discovery import apple
from src.discovery import store as st
from src.discovery import tcg
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=JST)


def prod(sku, part, price, name, cat="iphone"):
    return (f'{{"sku":"{sku}","partNumber":"{part}","price":{{"fullPrice":{price}.00}},"category":"{cat}",'
            f'"name":"{name}"}}')


def page(*items):
    return '<script>{"products":[' + ",".join(items) + "]}</script>"


LIST = ('<a href="/jp/shop/buy-iphone/iphone-17">iPhone 17</a>'
        '<a href="/jp/shop/buy-iphone/iphone-18-pro">iPhone 18 Pro</a>')
P17 = page(prod("MG6A4", "MG6A4J/A", 159800, "iPhone 17 256GB Lavender"),
           prod("MG6C4", "MG6C4J/A", 159800, "iPhone 17 256GB Sage"),
           prod("MG6D4", "MG6D4J/A", 194800, "iPhone 17 512GB Black"))
P18 = page(prod("MH1A4", "MH1A4J/A", 189800, "iPhone 18 Pro 256GB Cosmic Orange"),
           prod("MH1B4", "MH1B4J/A", 189800, "iPhone 18 Pro 256GB Deep Blue"),
           prod("MH1C4", "MH1C4J/A", 249800, "iPhone 18 Pro 1TB Silver"),
           prod("MH1D4", "MH1D4J/A", 1980, "AppleCare 18 Pro", cat="applecare"))
PRODUCTS_YAML = """products:
  - id: "prod_iphone17_256"
    genre: "iphone"
    name: "iPhone 17 256GB SIMフリー"
  - id: "prod_iphone17pro_256"
    genre: "iphone"
    name: "iPhone 17 Pro 256GB SIMフリー"
  - id: "prod_x100vi"
    genre: "camera"
    name: "FUJIFILM X100VI"
"""


@pytest.fixture
def env(tmp_path):
    y = tmp_path / "products.yaml"
    y.write_text(PRODUCTS_YAML, encoding="utf-8")
    pages = {apple.LIST_URL: LIST, apple.FAMILY_URL.format(slug="iphone-17"): P17,
             apple.FAMILY_URL.format(slug="iphone-18-pro"): P18}
    calls = []

    def fetch(url):
        calls.append(url)
        return (pages.get(url), "" if url in pages else "not_found")
    return tmp_path / "out", y, pages, fetch, calls


def cands(out):
    return st.load(out / st.PRODUCT_FILE)["candidates"]


# ── Apple ──────────────────────────────────────────────────────────────────

def test_known_sku_matched_unknown_candidate(env):
    out, y, pages, fetch, _c = env
    r = apple.run(out, y, now=NOW, fetch=fetch)
    c = {v["product_name"]: v for v in cands(out).values()}
    assert c["iPhone 17 256GB"]["status"] == st.MATCHED_EXISTING                    # 正本と一致（候補にしない）
    assert c["iPhone 17 256GB"]["match_to_existing"] == "prod_iphone17_256"
    assert c["iPhone 17 512GB"]["status"] == st.PENDING_REVIEW                      # 正本に無い容量
    assert c["iPhone 18 Pro 256GB"]["status"] == st.PENDING_REVIEW                  # 正本に無い世代
    assert r["matched"] == 1 and r["pending"] == 3


def test_capacity_and_generation_split(env):
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    names = sorted(v["product_name"] for v in cands(out).values())
    assert names == ["iPhone 17 256GB", "iPhone 17 512GB", "iPhone 18 Pro 1TB", "iPhone 18 Pro 256GB"]
    keys = {(v["model_number"], v["capacity"]) for v in cands(out).values()}
    assert ("iPhone 18 Pro", "1TB") in keys and ("iPhone 17", "512GB") in keys
    # 17 Pro（正本）と 18 Pro（新しい世代）を混同しない
    assert all(v["match_to_existing"] != "prod_iphone17pro_256" for v in cands(out).values())


def test_colors_grouped_not_separate_products(env):
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    c = {v["product_name"]: v for v in cands(out).values()}["iPhone 18 Pro 256GB"]
    assert c["colors"] == ["Cosmic Orange", "Deep Blue"] and c["part_numbers"] == ["MH1A4J/A", "MH1B4J/A"]
    assert len(cands(out)) == 4                                                     # 色で候補を増やさない


def test_official_evidence_required(env):
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    for c in cands(out).values():
        assert c["official_url"].startswith("https://www.apple.com/jp/shop/buy-iphone/")
        assert c["part_numbers"] and c["discovered_at"] and isinstance(c["official_price"], int)
    assert not any("AppleCare" in c["product_name"] for c in cands(out).values())  # iPhone 以外の商品は読まない


def test_name_only_not_detected():
    """「iPhone」という語だけ（部品番号・容量なし）では商品にしない。"""
    assert apple.parse_products('<p>新しい iPhone 19 が登場</p>"name":"iPhone 19"') == []
    assert apple.parse_name("iPhone 19") is None and apple.parse_name("iPhone Duo 256GB Black")["capacity"] == "256GB"


def test_same_candidate_dedupe_and_no_timestamp_renewal(env):
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    first = {k: dict(v) for k, v in cands(out).items()}
    apple.run(out, y, now=NOW + timedelta(days=3), fetch=fetch)
    again = cands(out)
    assert set(again) == set(first)                                                  # 同じ候補を毎回作らない
    for k in first:
        assert again[k]["discovered_at"] == first[k]["discovered_at"]                 # 最初の発見の時刻のまま
        assert again[k]["updated_at"] == first[k]["updated_at"]                       # 内容が同じなら時刻を進めない
        assert again[k]["last_seen_on"] == "2026-10-20"
    pages[apple.FAMILY_URL.format(slug="iphone-18-pro")] = P18.replace("189800", "199800")
    apple.run(out, y, now=NOW + timedelta(days=6), fetch=fetch)
    c = {v["product_name"]: v for v in cands(out).values()}["iPhone 18 Pro 256GB"]
    assert c["official_price"] == 199800 and c["updated_at"] != c["discovered_at"]  # 否定の対照: 内容が変われば進む


def test_candidate_stale_not_deleted(env):
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    pages[apple.FAMILY_URL.format(slug="iphone-18-pro")] = page(
        prod("MH1A4", "MH1A4J/A", 189800, "iPhone 18 Pro 256GB Cosmic Orange"))
    for d in (1, 4, 8):
        apple.run(out, y, now=NOW + timedelta(days=d), fetch=fetch)
    c = {v["product_name"]: v for v in cands(out).values()}
    assert c["iPhone 18 Pro 1TB"]["status"] == st.STALE                             # 消さずに STALE
    assert c["iPhone 18 Pro 256GB"]["status"] == st.PENDING_REVIEW


def test_unread_family_not_staled(env):
    """読めなかった機種の候補は STALE にしない（読めない実行で消えたことにしない）。"""
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    del pages[apple.FAMILY_URL.format(slug="iphone-18-pro")]
    for d in (2, 5, 9):
        apple.run(out, y, now=NOW + timedelta(days=d), fetch=fetch)
    c = {v["product_name"]: v for v in cands(out).values()}
    assert c["iPhone 18 Pro 1TB"]["status"] == st.PENDING_REVIEW


def test_family_page_budget(env):
    out, y, pages, fetch, calls = env
    for i in range(5):
        pages[apple.LIST_URL] += f'<a href="/jp/shop/buy-iphone/iphone-x{i}">x</a>'
    apple.run(out, y, now=NOW, fetch=fetch)
    fam = [u for u in calls if u != apple.LIST_URL]
    assert len(fam) == apple.MAX_FAMILY_PAGES and calls.count(apple.LIST_URL) == 1
    assert len(set(fam)) == len(fam)                                                  # 同じページは1回だけ


def test_failing_family_does_not_starve(env):
    out, y, pages, fetch, calls = env
    pages[apple.LIST_URL] += '<a href="/jp/shop/buy-iphone/iphone-broken">x</a>'
    for d in range(3):
        apple.run(out, y, now=NOW + timedelta(days=d), fetch=fetch)
    fam = [u for u in calls if u != apple.LIST_URL]
    assert {u.rsplit("/", 1)[1] for u in fam} == {"iphone-17", "iphone-18-pro", "iphone-broken"}


def test_unparsed_name_review_required(env):
    out, y, pages, fetch, _c = env
    pages[apple.FAMILY_URL.format(slug="iphone-17")] = P17.replace("]}", "," + prod("MZ1A4", "MZ1A4J/A", 99800,
                                                                                    "iPhone Fold Special") + "]}")
    apple.run(out, y, now=NOW, fetch=fetch)
    c = [v for v in cands(out).values() if v["part_numbers"] == ["MZ1A4J/A"]][0]
    assert c["status"] == st.REVIEW_REQUIRED and "name_unparsed" in c["reasons"]


def test_name_format_changed_no_flood(env):
    """ページの名前の形が変わって半分より多く読めないときは、部品番号ごとの候補を作らない（監査 L-2）。"""
    out, y, pages, fetch, _c = env
    pages[apple.FAMILY_URL.format(slug="iphone-17")] = P17.replace("iPhone 17 ", "iPhone&nbsp;17&nbsp;")
    r = apple.run(out, y, now=NOW, fetch=fetch)
    assert r["errors"]["iphone-17"] == "name_format_changed"
    assert not [v for v in cands(out).values() if "iphone-17" in v["families"]]


def test_block_stops_remaining_family_pages(env):
    """機種のページで 403 を受けたら、この実行では同じ取得元の残りを読まない（監査 M-1）。"""
    out, y, pages, fetch, calls = env

    def blocked(url):
        calls.append(url)
        return (pages[url], "") if url == apple.LIST_URL else (None, "site_blocked")
    r = apple.run(out, y, now=NOW, fetch=blocked)
    assert r["cutoff"] == "site_blocked" and r["requests"] == 2 and len(calls) == 2


def test_first_fetch_waits_host_interval(env, monkeypatch):
    """実際の取得では、最初の取得の前に取得元の間隔の分を待つ（前の手順が同じ取得元を読んだばかりかもしれない。監査 L-1）。"""
    out, y, pages, fetch, _c = env
    waited = []
    sys.path.insert(0, str(ROOT / "scripts"))
    import recheck_official
    monkeypatch.setattr(recheck_official, "_host_interval", lambda u: 120.0)        # robots.txt を読みに行かない
    monkeypatch.setattr(apple, "_fetch", lambda u: (None, "site_blocked"))
    apple.run(out, y, now=NOW, sleep=waited.append)
    assert waited and waited[0] >= 60
    waited.clear()
    apple.run(out, y, now=NOW, fetch=fetch, sleep=waited.append)
    assert waited == []                                                              # 偽の取得のときは待たない


def test_tcg_stale_inputs_not_seen(tmp_path):
    """TCG の収集が失敗して前回の生成物が残ったときは、候補を見つけ直したことにしない（鮮度の偽装をしない。監査 M-2）。"""
    out = tmp_path / "out"
    d = tcg_world(tmp_path, discovered=[{"url": "https://www.pokemon-card.com/info/2.html", "title": "予約受付",
                                         "kind": "PREORDER"}])
    tcg.run(d, out, now=NOW)
    seen = ev_cands(out)[0]["last_seen_on"]
    r = tcg.run(d, out, now=NOW + timedelta(days=3))                                # 生成物は3日前のまま
    assert r["inputs_stale"] and ev_cands(out)[0]["last_seen_on"] == seen
    assert ev_cands(out)[0]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED          # STALE にもしない


def test_list_failure_no_change(env):
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    before = (out / st.PRODUCT_FILE).read_text(encoding="utf-8")
    r = apple.run(out, y, now=NOW + timedelta(days=1), fetch=lambda u: (None, "site_blocked"))
    assert r["list_status"] == "site_blocked" and (out / st.PRODUCT_FILE).read_text(encoding="utf-8") == before


def test_never_writes_canonical(env, monkeypatch):
    out, y, pages, fetch, _c = env
    before = y.read_text(encoding="utf-8")
    real = ROOT / "config" / "products.yaml"
    real_before = real.read_text(encoding="utf-8")
    apple.run(out, y, now=NOW, fetch=fetch)
    assert y.read_text(encoding="utf-8") == before and real.read_text(encoding="utf-8") == real_before
    import re
    for f in ("apple.py", "tcg.py", "store.py"):
        src = (ROOT / "src" / "discovery" / f).read_text(encoding="utf-8")
        assert not re.search(r"insert\s+into\s+products\b|products\.yaml.*write|official_registry", src, re.I), f


def test_approval_rejection_records_only(env, tmp_path):
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    cid = next(k for k, v in cands(out).items() if v["product_name"] == "iPhone 18 Pro 256GB")
    rec = st.decide(out / st.PRODUCT_FILE, cid, "approve", now=NOW)
    assert rec["status"] == st.APPROVED
    apple.run(out, y, now=NOW + timedelta(days=1), fetch=fetch)
    assert cands(out)[cid]["status"] == st.APPROVED                                 # 発見で人の判断を上書きしない
    cid2 = next(k for k, v in cands(out).items() if v["product_name"] == "iPhone 17 512GB")
    st.decide(out / st.PRODUCT_FILE, cid2, "reject", now=NOW)
    for d in (2, 9, 100):
        apple.run(out, y, now=NOW + timedelta(days=d), fetch=fetch)
    assert cands(out)[cid2]["status"] == st.REJECTED
    assert st.decide(out / st.PRODUCT_FILE, "nope", "approve", now=NOW) is None


def test_cli_approve_records_ledger_without_canonical(tmp_path, monkeypatch):
    from click.testing import CliRunner
    import src.cli as cli
    led = tmp_path / "exports" / "discovery"
    s = st.empty()
    st.upsert(s, "apple-abc", {"product_name": "iPhone 18 Pro 256GB", "source": apple.SOURCE}, status=st.PENDING_REVIEW,
              now=NOW)
    st.save(led / st.PRODUCT_FILE, s)
    monkeypatch.setenv("DISCOVERY_DIR", str(led))

    class _DB:
        def init_schema(self):
            pass

        def close(self):
            pass
    monkeypatch.setattr(cli, "_get_db", lambda: _DB())
    monkeypatch.setattr(cli, "Repository", lambda db: type("R", (), {"update_product_candidate_status":
                                                                     lambda *a, **k: None})())
    real = (ROOT / "config" / "products.yaml").read_text(encoding="utf-8")
    out = CliRunner().invoke(cli.cli, ["approve-product-candidate", "--candidate-id", "apple-abc"]).output
    assert "正本（config/products.yaml）には追加していません" in out
    assert st.load(led / st.PRODUCT_FILE)["candidates"]["apple-abc"]["status"] == st.APPROVED
    assert (ROOT / "config" / "products.yaml").read_text(encoding="utf-8") == real


def test_fetch_respects_robots(monkeypatch):
    """取得は robots.txt で許されないときに通信しない（作法は recheck_official と同じ）。"""
    from src.collectors import polite
    import urllib.request
    monkeypatch.setattr(polite, "robots_allowed", lambda u: False)
    monkeypatch.setattr(polite, "robots_block_reason", lambda u: "robots_unreachable")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("通信した"))
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *a, **k: pytest.fail("通信した"))
    assert apple._fetch(apple.LIST_URL) == (None, "robots_unreachable")


def test_mirror_to_existing_product_candidates_table(env, tmp_path):
    import sqlite3
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript((ROOT / "src" / "db" / "migrations" / "003_product_candidates.sql").read_text(encoding="utf-8"))
    con.close()
    assert st.mirror_to_db(st.load(out / st.PRODUCT_FILE), db) == 3               # 正本と一致したものは写さない
    rows = sqlite3.connect(db).execute("select status, count(*) from product_candidates group by status").fetchall()
    assert rows == [("pending", 3)]


# ── TCG ───────────────────────────────────────────────────────────────────

def tcg_world(tmp_path, *, items=(), announcements=(), discovered=(), events=(), registry=()):
    d = tmp_path / "tcg"
    d.mkdir(exist_ok=True)
    g = NOW.isoformat()
    (d / "lotteries.json").write_text(json.dumps({"generated_at": g, "items": list(items),
                                                  "announcements": list(announcements)}), encoding="utf-8")
    (d / "lottery_sources.json").write_text(json.dumps({"generated_at": g, "coverage": {"configured_sources": 17, "implemented_collectors": 6,
                                                                     "not_implemented_sources": 11, "blocked_sources": 3},
                                                        "sources": [{"source_id": "POKEMON_CARD_OFFICIAL",
                                                                     "brand": ["POKEMON"],
                                                                     "discovered_titles": list(discovered)},
                                                                    {"source_id": "BICCAMERA",
                                                                     "robots": "robots_unreachable"}]}), encoding="utf-8")
    (d / "pokemon_registry.json").write_text(json.dumps({"generated_at": g, "products": list(registry)}), encoding="utf-8")
    (d / "latest.json").write_text(json.dumps({"generated_at": g, "events": list(events)}), encoding="utf-8")
    return d


def ev_cands(out):
    return list(st.load(out / st.EVENT_FILE)["candidates"].values())


def test_tcg_new_lottery_preorder_firstcome_restock(tmp_path):
    out = tmp_path / "out"
    d = tcg_world(tmp_path, discovered=[
        {"url": "https://www.pokemon-card.com/info/1.html", "title": "「X」の抽選販売について", "kind": "LOTTERY",
         "reason": "detail_fetch_limit"},
        {"url": "https://www.pokemon-card.com/info/2.html", "title": "「X」の予約受付について", "kind": "PREORDER"},
        {"url": "https://www.pokemon-card.com/info/3.html", "title": "「X」の先着販売について", "kind": "FIRST_COME"},
        {"url": "https://www.pokemon-card.com/info/4.html", "title": "「X」の再販について", "kind": "RESTOCK"}])
    r = tcg.run(d, out, now=NOW)
    kinds = sorted(c["kind"] for c in ev_cands(out))
    assert kinds == ["FIRST_COME", "LOTTERY", "PREORDER", "RESTOCK"]
    for c in ev_cands(out):
        assert c["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED and c["application_start"] is None
        assert c["missing_fields"] == ["application_start", "application_end"] and c["official_url"]
    assert r["review_required"] == 4 and r["sources"]["robots_unreachable"] == 1


def test_tcg_missing_dates_review_required_not_open(tmp_path):
    out = tmp_path / "out"
    d = tcg_world(tmp_path, announcements=[{"title": "PCO の抽選受け付けについて", "retailer": "POKEMON_CENTER_ONLINE",
                                           "source_url": "https://www.pokemoncenter-online.com/news/?id=1",
                                           "published_at": "2026-08-01T00:00:00+09:00", "tcg": "POKEMON"}])
    tcg.run(d, out, now=NOW)                                                          # 14日を過ぎた告知も捨てない
    c = ev_cands(out)[0]
    assert c["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED and c["event_status"] == ""
    assert "OPEN" not in json.dumps(c) and "schedule_not_available" in c["reasons"]


def test_tcg_release_not_lottery(tmp_path):
    out = tmp_path / "out"
    d = tcg_world(tmp_path, events=[{"store": "ONEPIECE_CARD_OFFICIAL", "event_type": "GENERAL_SALE",
                                     "status": "COMING_SOON", "product_name": "スタートデッキ【ST-38】",
                                     "product_id": "st-38", "sale_start": "2026-12-19T00:00:00+09:00",
                                     "source_url": "https://www.onepiece-cardgame.com/products/"}])
    r = tcg.run(d, out, now=NOW)
    c = ev_cands(out)[0]
    assert c["kind"] == "RELEASE" and c["status"] == st.MATCHED_EVENT and r["by_kind"]["LOTTERY"] == 0


def test_tcg_dated_event_matched_and_announcement_not_duplicated(tmp_path):
    out = tmp_path / "out"
    url = "https://www.pokemoncenter-online.com/news/?id=2"
    d = tcg_world(tmp_path, items=[{"lottery_id": "L1", "event_type": "LOTTERY", "retailer": "POKEMON_CENTER_ONLINE",
                                    "product_name": "X BOX", "source_url": url,
                                    "application_start": "2026-10-20T10:00:00+09:00",
                                    "application_end": "2026-10-25T23:59:00+09:00", "status": "UPCOMING"}],
                  announcements=[{"title": "PCO の抽選", "retailer": "POKEMON_CENTER_ONLINE", "source_url": url}])
    tcg.run(d, out, now=NOW)
    cs = ev_cands(out)
    assert len(cs) == 1 and cs[0]["status"] == st.MATCHED_EVENT                       # 日程つきのイベントだけ（告知は重ねない）


def test_tcg_same_event_dedupe(tmp_path):
    out = tmp_path / "out"
    d = tcg_world(tmp_path, discovered=[{"url": "https://www.pokemon-card.com/info/2.html", "title": "予約受付",
                                         "kind": "PREORDER"}])
    tcg.run(d, out, now=NOW)
    first = ev_cands(out)[0]["discovered_at"]
    tcg.run(d, out, now=NOW + timedelta(hours=6))
    cs = ev_cands(out)
    assert len(cs) == 1 and cs[0]["discovered_at"] == first


def test_tcg_product_code_mapping_and_name_only_rejected(tmp_path):
    out = tmp_path / "out"
    d = tcg_world(tmp_path, events=[{"store": "ONEPIECE_CARD_OFFICIAL", "event_type": "GENERAL_SALE",
                                     "status": "COMING_SOON", "product_name": "ブースターパック【OP-18】",
                                     "product_id": "op-18"}],
                  discovered=[{"url": "https://www.pokemon-card.com/info/5.html", "title": "ブースターパック【OP-18】の抽選",
                               "kind": "LOTTERY"},
                              {"url": "https://www.pokemon-card.com/info/6.html", "title": "ブースターパックの予約",
                               "kind": "PREORDER"}])
    tcg.run(d, out, now=NOW)
    by = {c["title"]: c for c in ev_cands(out)}
    assert by["ブースターパック【OP-18】の抽選"]["product_code"] == "OP-18"
    assert by["ブースターパック【OP-18】の抽選"]["product_mapping"] == "code"
    assert by["ブースターパックの予約"]["product_mapping"] == "unmapped"            # 名前だけでは結び付けない
    assert by["ブースターパックの予約"]["product_code"] == ""


def test_tcg_products_candidates_not_canonical(tmp_path):
    out = tmp_path / "out"
    d = tcg_world(tmp_path, registry=[{"product_id": "pokemon-a", "name": "拡張パック「A」",
                                       "official_url": "https://www.pokemon-card.com/ex/m6/"},
                                      {"product_id": "pokemon-b", "name": "スペシャルセット",
                                       "official_url": "https://www.pokemon-card.com/products/x.html"}])
    tcg.run(d, out, now=NOW)
    c = {v["product_name"]: v for v in cands(out).values()}
    assert c["拡張パック「A」"]["status"] == st.PENDING_REVIEW and c["拡張パック「A」"]["model_number"] == "M6"
    assert c["スペシャルセット"]["status"] == st.REVIEW_REQUIRED and "no_product_code" in c["スペシャルセット"]["reasons"]


def test_tcg_missing_inputs_do_not_stale(tmp_path):
    out = tmp_path / "out"
    d = tcg_world(tmp_path, discovered=[{"url": "https://www.pokemon-card.com/info/2.html", "title": "予約受付",
                                         "kind": "PREORDER"}])
    tcg.run(d, out, now=NOW)
    (d / "lotteries.json").unlink()
    tcg.run(d, out, now=NOW + timedelta(hours=6))
    assert ev_cands(out)[0]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED


# ── 収集の部品（ポケモン公式のニュースの一覧） ───────────────────────────────────

def test_pokemon_news_discovered_titles_no_extra_fetch(monkeypatch):
    from src.collectors.tcg.lottery import pokemon_official as po
    idx = ('<a href="https://www.pokemon-card.com/info/1.html">商品 「A」の予約受付について 2026.10.10</a>'
           '<a href="https://www.pokemon-card.com/info/2.html">商品 「A」の再販について 2026.10.11</a>'
           '<a href="https://www.pokemon-card.com/info/3.html">イベント ジムバトルの予約 2026.10.12</a>'
           '<a href="https://www.pokemon-card.com/info/4.html">商品 「B」の抽選販売について 2026.10.13</a>'
           '<a href="https://www.pokemon-card.com/info/5.html">商品 「C」の抽選販売について 2026.10.14</a>'
           '<a href="https://www.pokemon-card.com/info/6.html">商品 「D」の抽選販売について 2026.10.15</a>')
    a = po.PokemonNewsLotteryAdapter()
    fetched = []
    monkeypatch.setattr(a, "fetch_listing", lambda url: idx)
    monkeypatch.setattr(a, "fetch_detail", lambda url, referer=None: fetched.append(url) or None)
    a.collect()
    d = {x["url"].rsplit("/", 1)[1]: x for x in a.health["discovered_titles"]}
    assert d["1.html"]["kind"] == "PREORDER" and d["2.html"]["kind"] == "RESTOCK"
    assert "3.html" not in d                                                         # 大会・イベントは候補にしない
    assert d["6.html"]["reason"] == "detail_fetch_limit"                             # 読む上限で読まなかった抽選
    assert len(fetched) == a.max_detail_fetch and "https://www.pokemon-card.com/info/1.html" not in fetched


# ── ワークフロー・検査 ───────────────────────────────────────────────────

def _dc():
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_check
    return deploy_check


def test_workflow_step_and_commit_path():
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    i = wf.index("- name: Discover new products and events")
    step = wf[i:wf.index("- name:", i + 10)]
    assert "python -m src.cli discover" in step and "continue-on-error: true" in step and "secrets." not in step
    assert "exports/discovery/ \\" in wf


def test_deploy_check_862_ok():
    assert _dc()._check_phase27_discovery()[0]["level"] == "ok"


def test_tcg_exact_product_name_in_title_still_unmapped(tmp_path):
    """告知のタイトルに商品名がそのまま入っていても、商品コードが無ければ結び付けない（名前だけの照合をしない）。"""
    out = tmp_path / "out"
    d = tcg_world(tmp_path, registry=[{"product_id": "pokemon-a", "name": "拡張パック「A」",
                                       "official_url": "https://www.pokemon-card.com/ex/m6/"}],
                  events=[{"store": "ONEPIECE_CARD_OFFICIAL", "event_type": "GENERAL_SALE", "status": "COMING_SOON",
                           "product_name": "ブースターパック 神の支配【OP-18】", "product_id": "op-18"}],
                  discovered=[{"url": "https://www.pokemon-card.com/info/7.html", "title": "拡張パック「A」の予約受付",
                               "kind": "PREORDER"},
                              {"url": "https://www.pokemon-card.com/info/8.html", "title": "ブースターパック 神の支配の抽選",
                               "kind": "LOTTERY"}])
    tcg.run(d, out, now=NOW)
    for c in ev_cands(out):
        if c["kind"] != "RELEASE":
            assert c["product_mapping"] == "unmapped" and c["product_code"] == "", c["title"]


def test_unknown_families_first():
    """まだ読んでいない機種のうち、正本に無い機種（新しい機種の可能性）を先に読む。"""
    slugs = ["iphone-16", "iphone-17", "iphone-18-pro", "iphone-air"]
    got = apple.pick_families(slugs, {"families": {}}, limit=4, known_lines=["iphone 17", "iphone 17 pro"])
    assert got[-1] == "iphone-17" and set(got[:3]) == {"iphone-16", "iphone-18-pro", "iphone-air"}


def test_tcg_unknown_event_type_not_lottery(tmp_path):
    """知らない種類のイベントを抽選として扱わない（監査 L-4）。"""
    out = tmp_path / "out"
    d = tcg_world(tmp_path, items=[{"lottery_id": "L9", "event_type": "SOMETHING_NEW", "product_name": "X",
                                    "source_url": "https://www.pokemon-card.com/info/9.html"}])
    r = tcg.run(d, out, now=NOW)
    assert r["by_kind"]["LOTTERY"] == 0 and ev_cands(out) == []


# ── レビュー・監査の指摘（H-1・M-2〜M-4・L-5〜L-7） ───────────────────────

def test_announcement_only_item_is_review_not_matched(tmp_path):
    """日程の無い仮のイベント（告知）は正式なイベントにせず、要確認の候補にする（レビュー H-1）。"""
    out = tmp_path / "out"
    url = "https://www.pokemoncenter-online.com/news/?id=3"
    d = tcg_world(tmp_path, items=[{"lottery_id": "LA", "event_type": "LOTTERY", "retailer": "POKEMON_CENTER_ONLINE",
                                    "product_name": "抽選受け付けについて", "source_url": url, "announcement_only": True,
                                    "application_start": None, "application_end": None, "status": "UNKNOWN"}],
                  announcements=[{"title": "抽選受け付けについて", "retailer": "POKEMON_CENTER_ONLINE", "source_url": url}])
    r = tcg.run(d, out, now=NOW)
    cs = ev_cands(out)
    assert len(cs) == 1 and cs[0]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED and r["matched_events"] == 0


def test_apple_list_without_families_does_not_stale(env):
    """一覧の形が変わって機種が0件なら、候補を STALE にしない（レビュー M-2）。"""
    out, y, pages, fetch, _c = env
    apple.run(out, y, now=NOW, fetch=fetch)
    pages[apple.LIST_URL] = "<p>形が変わった</p>"
    for d in (3, 8, 12):
        r = apple.run(out, y, now=NOW + timedelta(days=d), fetch=fetch)
    assert r["list_status"] == "no_families"
    assert not [v for v in cands(out).values() if v["status"] == st.STALE]


def test_tcg_failed_collection_does_not_stale(tmp_path):
    """TCG の収集が失敗した日（空の生成物・error あり）・読めなかった取得元の候補は STALE にしない（レビュー M-3）。"""
    out = tmp_path / "out"
    d = tcg_world(tmp_path, discovered=[{"url": "https://www.pokemon-card.com/info/2.html", "title": "予約受付",
                                         "kind": "PREORDER"}],
                  registry=[{"product_id": "a", "name": "A", "official_url": "https://www.pokemon-card.com/ex/m6/"}])
    tcg.run(d, out, now=NOW)
    for day in (3, 8, 12):
        later = NOW + timedelta(days=day)
        g = later.isoformat()
        for f, body in (("lotteries.json", {"items": [], "announcements": []}),
                        ("lottery_sources.json", {"sources": [{"source_id": "POKEMON_CARD_OFFICIAL", "reachable": False}]}),
                        ("pokemon_registry.json", {"products": []}), ("latest.json", {"events": [], "error": "x"})):
            (d / f).write_text(json.dumps(dict(body, generated_at=g)), encoding="utf-8")
        tcg.run(d, out, now=later)
    assert ev_cands(out)[0]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED
    assert [v["status"] for v in cands(out).values()] == [st.PENDING_REVIEW]


def test_stale_records_origin_and_admin_shows_only_open(tmp_path):
    """STALE は元の状態を残し、運営者向けには確認待ちだったものだけを出す（終わった発売・正本と一致は出さない。レビュー M-4）。"""
    from src.content.ui import admin
    s = st.empty()
    st.upsert(s, "a", {"title": "発売", "kind": "RELEASE"}, status=st.MATCHED_EVENT, now=NOW)
    st.upsert(s, "b", {"title": "告知", "kind": "PREORDER"}, status=st.ANNOUNCEMENT_REVIEW_REQUIRED, now=NOW)
    st.age_out(s, [], now=NOW + timedelta(days=8))
    assert s["candidates"]["a"]["stale_from"] == st.MATCHED_EVENT
    d = admin.build_discovery({"generated_at": NOW.isoformat()}, {"candidates": {}}, s)
    assert [e["candidate_id"] for e in d["events"]] == ["b"]


def test_same_line_capacity_on_two_family_pages_stable(env):
    """同じ機種・容量が2つの機種のページに出ても、内容が同じなら時刻を進めず、1回だけ数える（レビュー L-5）。"""
    out, y, pages, fetch, _c = env
    pages[apple.FAMILY_URL.format(slug="iphone-18-pro")] = P18.replace("]}", "," + prod(
        "MG6D4", "MG6D4J/A", 194800, "iPhone 17 512GB Black") + "]}")
    r = apple.run(out, y, now=NOW, fetch=fetch)
    c = {v["product_name"]: v for v in cands(out).values()}["iPhone 17 512GB"]
    assert c["families"] == ["iphone-17", "iphone-18-pro"] and r["pending"] == 3
    u = c["updated_at"]
    apple.run(out, y, now=NOW + timedelta(days=1), fetch=fetch)
    assert {v["product_name"]: v for v in cands(out).values()}["iPhone 17 512GB"]["updated_at"] == u


def test_release_date_change_not_duplicated(tmp_path):
    out = tmp_path / "out"
    ev = {"store": "ONEPIECE_CARD_OFFICIAL", "event_type": "GENERAL_SALE", "status": "COMING_SOON",
          "product_name": "【ST-38】", "product_id": "st-38", "sale_start": "2026-12-19T00:00:00+09:00"}
    tcg.run(tcg_world(tmp_path, events=[ev]), out, now=NOW)
    tcg.run(tcg_world(tmp_path, events=[dict(ev, sale_start="2027-01-09T00:00:00+09:00")]), out,
            now=NOW + timedelta(hours=1))
    cs = ev_cands(out)
    assert len(cs) == 1 and cs[0]["release_date"].startswith("2027-01-09")


def test_tcg_not_mirrored_to_db(tmp_path):
    import sqlite3
    s = st.empty()
    st.upsert(s, "t1", {"product_name": "拡張パック", "genre": "tcg"}, status=st.PENDING_REVIEW, now=NOW)
    st.upsert(s, "a1", {"product_name": "iPhone 18 Pro 256GB", "genre": "iphone"}, status=st.PENDING_REVIEW, now=NOW)
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.executescript((ROOT / "src" / "db" / "migrations" / "003_product_candidates.sql").read_text(encoding="utf-8"))
    con.close()
    assert st.mirror_to_db(s, db) == 1


def test_tcg_collection_error_alone_does_not_stale(tmp_path):
    """取得元の行は読めていても、収集の全体が失敗した（latest.json に error）日は STALE にしない（レビュー M-3）。"""
    out = tmp_path / "out"
    d = tcg_world(tmp_path, discovered=[{"url": "https://www.pokemon-card.com/info/2.html", "title": "予約受付",
                                         "kind": "PREORDER"}])
    tcg.run(d, out, now=NOW)
    for day in (3, 8, 12):
        later = NOW + timedelta(days=day)
        g = later.isoformat()
        for f, body in (("lotteries.json", {"items": [], "announcements": []}),
                        ("lottery_sources.json", {"sources": [{"source_id": "POKEMON_CARD_OFFICIAL", "reachable": True}]}),
                        ("latest.json", {"events": [], "error": "collector crashed"})):
            (d / f).write_text(json.dumps(dict(body, generated_at=g)), encoding="utf-8")
        (d / "pokemon_registry.json").write_text(json.dumps({"generated_at": g, "products": []}), encoding="utf-8")
        tcg.run(d, out, now=later)
    assert ev_cands(out)[0]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED


def test_tcg_lottery_pipeline_failure_does_not_stale(tmp_path):
    """抽選の収集そのものが失敗した日（取得元の行が無い空の出力・error なし）も STALE にしない（レビュー M-3 の残り）。"""
    out = tmp_path / "out"
    d = tcg_world(tmp_path, discovered=[{"url": "https://www.pokemon-card.com/info/2.html", "title": "予約受付",
                                         "kind": "PREORDER"}])
    tcg.run(d, out, now=NOW)
    for day in (3, 8, 12):
        later = NOW + timedelta(days=day)
        g = later.isoformat()
        for f, body in (("lotteries.json", {"items": [], "announcements": []}), ("lottery_sources.json", {"sources": []}),
                        ("latest.json", {"events": []}), ("pokemon_registry.json", {"products": []})):
            (d / f).write_text(json.dumps(dict(body, generated_at=g)), encoding="utf-8")
        tcg.run(d, out, now=later)
    assert ev_cands(out)[0]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED


def test_blocked_but_listed_source_still_ages(tmp_path):
    """本文だけが 403 で一覧は読めた取得元（PCO など）の告知は、一覧から消えれば STALE になる（レビュー L-2）。"""
    out = tmp_path / "out"
    d = tcg_world(tmp_path, announcements=[{"title": "抽選", "retailer": "POKEMON_CENTER_ONLINE",
                                           "source_url": "https://www.pokemoncenter-online.com/news/?id=7"}])
    tcg.run(d, out, now=NOW)
    for day in (3, 8):
        later = NOW + timedelta(days=day)
        g = later.isoformat()
        for f, body in (("lotteries.json", {"items": [], "announcements": []}),
                        ("lottery_sources.json", {"sources": [{"source_id": "POKEMON_CENTER_ONLINE", "blocked": True,
                                                               "reachable": True}]}),
                        ("latest.json", {"events": []}), ("pokemon_registry.json", {"products": []})):
            (d / f).write_text(json.dumps(dict(body, generated_at=g)), encoding="utf-8")
        tcg.run(d, out, now=later)
    c = ev_cands(out)[0]
    assert c["status"] == st.STALE and c["stale_from"] == st.ANNOUNCEMENT_REVIEW_REQUIRED


def test_code_only_strips_docstrings_keeps_sql(tmp_path):
    dc = _dc()
    src = '"""insert into products の説明"""\n# insert into products のコメント\nx = ("a"\n     "insert into products values")\n'
    code = dc._code_only(src)
    assert code.count("insert into products") == 1


def test_candidate_on_two_pages_stales_when_gone_from_both(env):
    """2つの機種のページに出た候補は、両方から消えれば（読む組み合わせが固定でも）7日で STALE になる（レビュー M-1）。"""
    out, y, pages, fetch, _c = env
    extra = prod("MG6D4", "MG6D4J/A", 194800, "iPhone 17 512GB Black")
    pages[apple.FAMILY_URL.format(slug="iphone-18-pro")] = P18.replace("]}", "," + extra + "]}")
    apple.run(out, y, now=NOW, fetch=fetch)
    c = {v["product_name"]: v for v in cands(out).values()}["iPhone 17 512GB"]
    assert c["families"] == ["iphone-17", "iphone-18-pro"]
    pages[apple.FAMILY_URL.format(slug="iphone-17")] = P17.replace("," + prod("MG6D4", "MG6D4J/A", 194800,
                                                                               "iPhone 17 512GB Black"), "")
    pages[apple.FAMILY_URL.format(slug="iphone-18-pro")] = P18
    for d in (1, 3, 9):
        apple.run(out, y, now=NOW + timedelta(days=d), fetch=fetch)
    c = {v["product_name"]: v for v in cands(out).values()}["iPhone 17 512GB"]
    assert c["families"] == [] and c["status"] == st.STALE and c["stale_from"] == st.PENDING_REVIEW


def test_candidate_gone_from_one_page_stays(env):
    """片方のページから消えても、もう片方に載っていれば STALE にしない（行き来しない）。"""
    out, y, pages, fetch, _c = env
    extra = prod("MG6D4", "MG6D4J/A", 194800, "iPhone 17 512GB Black")
    pages[apple.FAMILY_URL.format(slug="iphone-18-pro")] = P18.replace("]}", "," + extra + "]}")
    apple.run(out, y, now=NOW, fetch=fetch)
    pages[apple.FAMILY_URL.format(slug="iphone-17")] = P17.replace("," + extra, "")
    for d in (1, 3, 9):
        apple.run(out, y, now=NOW + timedelta(days=d), fetch=fetch)
    c = {v["product_name"]: v for v in cands(out).values()}["iPhone 17 512GB"]
    assert c["families"] == ["iphone-18-pro"] and c["status"] == st.PENDING_REVIEW
