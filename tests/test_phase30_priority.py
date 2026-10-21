"""Phase 30（候補の優先順位と1件だけの登録）のテスト。

点は決まった計算式（同じ入力なら同じ点）・売値は実際の行だけ（無ければ差の点を付けない）・色は全色がそろったときだけ最も
低い色・登録済み / 一致 / STALE は順位から除く・取得は上位の機種だけ。ネットワークには出ない。各テストに否定の対照を付ける。
"""
from __future__ import annotations

import copy
import random
from datetime import datetime
from pathlib import Path

import pytest

from src.discovery import priority as pr
from src.discovery import store as st
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=JST)
DUO = {"candidate_id": "apple-duo256", "source": "apple_jp_official", "status": st.PENDING_REVIEW,
       "product_name": "iPhone Duo 256GB", "model_number": "iPhone Duo", "capacity": "256GB",
       "part_numbers": ["MK244J/A", "MK254J/A"], "official_url": "https://www.apple.com/jp/shop/buy-iphone/iphone-duo",
       "official_price": 364800, "official_prices": [364800], "last_seen_on": "2026-10-19", "match_to_existing": ""}
ROWS = [["iPhone Duo 256GB ナイトスカイ MK254J/A SIMフリー", 395000, "/products/detail/27089", "category"],
        ["iPhone Duo 256GB スターホワイト MK244J/A SIMフリー", 395000, "/products/detail/27090", "category"],
        ["iPhone Duo 512GB ナイトスカイ MK274J/A SIMフリー", 430000, "/products/detail/27091", "category"]]
EV = {"index_status": "ok", "rows": ROWS + [[ROWS[0][0], 395000, ROWS[0][2], "index"]],
      "families": {"iphoneduo": {"category_url": "https://www.kaitorishouten-co.jp/category/1/748",
                                 "listed_in_index": True, "status": "ok"}}}


def score(c=None, ev=None):
    return pr.score_candidate(c or dict(DUO), EV if ev is None else ev, now=NOW)


# ── 点の項目 ───────────────────────────────────────────────────────────────

def test_full_evidence_scores_and_spread_from_real_rows():
    r = score()
    assert r["points"] == {"official": 20, "buyback": 25, "spread": 17, "identity": 15, "market": 10, "readiness": 5}
    assert r["score"] == 92 and r["buyback_state"] == "CONFIRMED" and r["official_state"] == "CONFIRMED"
    assert r["buyback_sell"] == 395000 and r["known_costs"] == 1800 and r["spread"] == 395000 - 364800 - 1800
    assert len(r["buyback_rows"]) == 2                     # まとめと価格表に同じ行があっても重ねない


def test_official_evidence_partial_loses_points():
    assert score(dict(DUO, official_prices=[364800, 369800]))["points"]["official"] == 15     # 色で価格が違う
    assert score(dict(DUO, part_numbers=["MK244"]))["points"]["official"] == 15               # 部品番号の形が違う
    assert score(dict(DUO, official_url="https://shop.example.com/duo"))["points"]["official"] == 15


def test_missing_buyback_gives_no_buyback_or_spread_points():
    r = score(ev={"index_status": "not_fetched", "rows": [], "families": {}})
    assert r["buyback_state"] == "UNKNOWN" and r["points"]["buyback"] == 0
    assert r["spread"] is None and r["points"]["spread"] == 0 and r["buyback_sell"] is None   # 売値を作らない
    other_capacity = dict(EV, rows=[ROWS[2]])                                                 # 他の容量の価格から推測しない
    r2 = score(ev=other_capacity)
    assert r2["buyback_state"] == "NOT_LISTED" and r2["spread"] is None and r2["points"]["spread"] == 0


def test_partial_colors_do_not_confirm_or_compute_spread():
    r = score(ev=dict(EV, rows=[ROWS[0]]))
    assert r["buyback_state"] == "PARTIAL" and r["points"]["buyback"] == 10 and r["spread"] is None


def test_color_safe_lowest_price_not_highest():
    rows = [[ROWS[0][0], 395000, ROWS[0][2], "category"], [ROWS[1][0], 380000, ROWS[1][2], "category"]]
    r = score(ev=dict(EV, rows=rows))
    assert r["buyback_sell"] == 380000 and r["spread"] == 380000 - 364800 - 1800


def test_carrier_used_and_wrong_part_rows_not_matched():
    bad = [["iPhone Duo 256GB ナイトスカイ MK254J/A au", 500000, "/products/detail/1", "category"],
           ["iPhone Duo 256GB ナイトスカイ MK254J/A", 500000, "/products/detail/2", "category"],
           ["iPhone Duo 256GB ナイトスカイ MK254J/A docomo SIMフリー", 500000, "/products/detail/7", "category"],
           ["iPhone Duo 256GB ナイトスカイ MK254J/A SIMフリー ソフトバンク", 500000, "/products/detail/8", "category"],
           ["iPhone Duo 256GB ナイトスカイ MK254J/A SIMフリー 中古", 500000, "/products/detail/3", "category"],
           ["iPhone Duo 256GB ナイトスカイ MZZZ9J/A SIMフリー", 500000, "/products/detail/4", "category"],
           ["iPhone Duo Pro 256GB ナイトスカイ MK254J/A SIMフリー", 500000, "/products/detail/5", "category"],
           ["iPhone Duo 256GB ナイトスカイ MK254J/A SIMフリー", 500000, "/keitai", "category"]]   # 商品ページでない
    assert pr.match_buyback_rows(DUO, bad) == []
    assert len(pr.match_buyback_rows(DUO, ROWS)) == 2                                          # 対照


def test_identity_ambiguous_penalty():
    r = score(dict(DUO, product_name="iPhone Duo"))
    assert r["points"]["identity"] == 10 and "identity_ambiguous" in r["reasons"]


def test_blocked_source_is_blocked_zero():
    ev = dict(EV, rows=[], families={"iphoneduo": dict(EV["families"]["iphoneduo"], status="blocked")})
    r = score(ev=ev)
    assert r["buyback_state"] == "BLOCKED" and r["points"]["buyback"] == 0 and r["spread"] is None


def test_no_profit_at_current_prices_scores_zero_spread():
    r = score(ev=dict(EV, rows=[[x[0], 300000, x[2], "category"] for x in ROWS[:2]]))
    assert r["spread"] < 0 and r["points"]["spread"] == 0 and "no_profit_at_current_prices" in r["reasons"]


def test_unknown_shipping_gives_no_spread(monkeypatch):
    from src.market import official_shipping as osh
    monkeypatch.setattr(osh, "purchase_shipping", lambda *a, **k: {"fee": None})
    r = score()
    assert r["known_costs"] is None and r["spread"] is None and r["points"]["spread"] == 0   # 送料を 0 とみなさない


# ── 順位 ──────────────────────────────────────────────────────────────────

def cands():
    c = {"apple-duo256": dict(DUO),
         "apple-duo512": dict(DUO, candidate_id="apple-duo512", product_name="iPhone Duo 512GB", capacity="512GB",
                              part_numbers=["MK264J/A", "MK274J/A"], official_price=399800, official_prices=[399800]),
         "apple-reg": dict(DUO, candidate_id="apple-reg", status=st.REGISTERED),
         "apple-match": dict(DUO, candidate_id="apple-match", status=st.MATCHED_EXISTING),
         "apple-rej": dict(DUO, candidate_id="apple-rej", status=st.REJECTED),
         "apple-stale": dict(DUO, candidate_id="apple-stale", last_seen_on="2026-10-01"),
         "tcg-x": {"source": "pokemon_card_official", "status": st.PENDING_REVIEW, "genre": "tcg"}}
    return c


def test_rank_excludes_registered_matched_rejected_stale_and_tcg():
    res = pr.rank(cands(), EV, now=NOW)
    assert [r["candidate_id"] for r in res["ranked"]] == ["apple-duo256", "apple-duo512"]
    ex = {e["candidate_id"]: e["reason"] for e in res["excluded"]}
    assert ex == {"apple-reg": "not_pending_review", "apple-match": "not_pending_review",
                  "apple-rej": "not_pending_review", "apple-stale": "stale"}


def test_rank_is_deterministic_and_tie_breaks_on_lower_price():
    ev512 = dict(EV, rows=EV["rows"] + [["iPhone Duo 512GB スターホワイト MK264J/A SIMフリー", 430000,
                                          "/products/detail/27092", "category"]])
    a = pr.rank(cands(), ev512, now=NOW)
    shuffled = dict(random.Random(7).sample(list(cands().items()), len(cands())))
    ev2 = copy.deepcopy(ev512)
    ev2["rows"] = list(reversed(ev2["rows"]))
    b = pr.rank(shuffled, ev2, now=NOW)
    assert a == b                                                                          # 同じ入力なら同じ結果
    assert a["ranked"][0]["score"] == a["ranked"][1]["score"] and a["ranked"][0]["candidate_id"] == "apple-duo256"
    # 同点は仕入れ値の低い順（候補の ID の順ではない）: ID の順が逆でも 256GB が先
    c2 = {"apple-zz256": dict(DUO, candidate_id="apple-zz256"),
          "apple-aa512": dict(cands()["apple-duo512"], candidate_id="apple-aa512")}
    r2 = pr.rank(c2, ev512, now=NOW)
    assert [x["candidate_id"] for x in r2["ranked"]] == ["apple-zz256", "apple-aa512"]


# ── CLI（取得は上位の機種だけ・登録しない）─────────────────────────────────────

INDEX = ('<a href="/category/1/748">iPhone Duoの買取価格表を見る →</a>'
         '<a href="/category/1/709">iPhone Airの買取価格表を見る →</a>'
         '<ul><li><a href="/products/detail/27089">iPhone Duo 256GB ナイトスカイ MK254J/A SIMフリー</a>'
         '<span class="num">¥395,000</span></li></ul>')
DUO_PAGE = ("<table><tr><th>品目</th><th>新品買取</th><th>中古買取</th></tr>" + "".join(
    f'<tr><td><a href="{h}">{n}</a></td><td class="num">¥{p:,}</td><td>¥1,000</td></tr>' for n, p, h, _k in ROWS)
    + "</table>")


@pytest.fixture
def led(tmp_path, monkeypatch):
    d = tmp_path / "led"
    s = st.empty()
    s["candidates"] = {k: v for k, v in cands().items()}
    st.save(d / st.PRODUCT_FILE, s)
    monkeypatch.setenv("DISCOVERY_DIR", str(d))
    return d


def run(*args):
    from click.testing import CliRunner
    import src.cli as cli
    return CliRunner().invoke(cli.cli, ["rank-product-candidates", *args])


def test_cli_without_fetch_has_no_buyback(led, monkeypatch):
    import src.cli as cli
    monkeypatch.setattr(cli, "_priority_fetch", lambda u: (_ for _ in ()).throw(AssertionError("fetched")))
    before = (led / st.PRODUCT_FILE).read_text(encoding="utf-8")
    real = (ROOT / "config" / "products.yaml").read_text(encoding="utf-8")
    (led / "priority.json").write_text('{"keep": 1}', encoding="utf-8")
    r = run()
    assert r.exit_code == 0, r.output and "UNKNOWN" in r.output
    assert (led / "priority.json").read_text(encoding="utf-8") == '{"keep": 1}'          # 前回の取得の記録を上書きしない
    assert (led / st.PRODUCT_FILE).read_text(encoding="utf-8") == before                  # 台帳を変えない
    assert (ROOT / "config" / "products.yaml").read_text(encoding="utf-8") == real         # 正本を変えない


def test_cli_fetches_index_and_only_top_family(led, monkeypatch):
    import json
    import src.cli as cli
    calls = []
    pages = {pr.INDEX_URL: INDEX, "https://www.kaitorishouten-co.jp/category/1/748": DUO_PAGE,
             "https://www.kaitorishouten-co.jp/category/1/709": "<table></table>"}
    monkeypatch.setattr(cli, "_priority_fetch", lambda u: calls.append(u) or (pages.get(u), ""))
    r = run("--fetch-buyback")
    assert r.exit_code == 0, r.output
    assert calls == [pr.INDEX_URL, "https://www.kaitorishouten-co.jp/category/1/748"]       # 上位の1機種だけ
    rep = json.loads((led / "priority.json").read_text(encoding="utf-8"))
    top = rep["ranked"][0]
    assert top["candidate_id"] == "apple-duo256" and top["buyback_state"] == "CONFIRMED" and top["spread"] == 28400
    assert all(f["fetched_at"] and f["status"] == "ok" for f in rep["evidence"]["fetches"])
    assert "rows" not in rep["evidence"] and rep["evidence"]["rows_count"] > 0            # 取得元の行を丸ごと残さない
    calls.clear()
    (led / "priority.json").unlink()                       # 前回の取得の記録を消す（間隔の守りは別のテスト）
    assert run("--fetch-buyback", "--max-family-pages", "0").exit_code == 0 and calls == [pr.INDEX_URL]


def test_cli_blocked_category_stops_reading_that_source(led, monkeypatch):
    import src.cli as cli
    calls = []
    two = INDEX + '<ul><li><a href="/products/detail/24681">iPhone Air 256GB スカイブルー MG2A4J/A SIMフリー</a>' \
                  '<span class="num">¥133,000</span></li></ul>'
    s = st.load(led / st.PRODUCT_FILE)
    s["candidates"]["apple-air512"] = dict(DUO, candidate_id="apple-air512", product_name="iPhone Air 512GB",
                                           model_number="iPhone Air", capacity="512GB", part_numbers=["MG2C4J/A"],
                                           official_url="https://www.apple.com/jp/shop/buy-iphone/iphone-air")
    st.save(led / st.PRODUCT_FILE, s)

    def fetch(u):
        calls.append(u)
        return (two, "") if u == pr.INDEX_URL else (None, "site_blocked")
    monkeypatch.setattr(cli, "_priority_fetch", fetch)
    assert run("--fetch-buyback", "--max-family-pages", "2").exit_code == 0
    assert len(calls) == 2                                  # 価格表がブロックされたら同じ取得元の2つ目を読まない
    import json
    fams = json.loads((led / "priority.json").read_text(encoding="utf-8"))["evidence"]["families"]
    assert fams["iphoneduo"]["status"] == "blocked" and fams["iphoneair"]["status"] == "blocked"   # 記録を残す


def test_cli_blocked_index_stops_and_scores_zero(led, monkeypatch):
    import json
    import src.cli as cli
    calls = []
    monkeypatch.setattr(cli, "_priority_fetch", lambda u: calls.append(u) or (None, "site_blocked"))
    assert run("--fetch-buyback").exit_code == 0 and calls == [pr.INDEX_URL]               # 回避しない・それ以上読まない
    rep = json.loads((led / "priority.json").read_text(encoding="utf-8"))
    assert rep["evidence"]["index_status"] == "blocked"
    assert all(x["points"]["buyback"] == 0 and x["spread"] is None for x in rep["ranked"])


def test_admin_priority_uses_current_ledger_status():
    from src.content.ui import admin
    rep = pr.rank(cands(), EV, now=NOW)
    rep.update(generated_at=NOW.isoformat(), evidence={"fetches": [{"fetched_at": NOW.isoformat()}]})
    pc = {"candidates": dict(cands(), **{"apple-duo256": dict(DUO, status=st.REGISTERED)})}
    b = admin.build_priority(rep, pc, now=NOW)
    assert b["rows"][0]["status"] == st.REGISTERED and b["fetches"] == 1
    html = admin._discovery({"priority": b, "metrics": {}})
    visible = html.replace(html[html.find("<caption"):html.find("</caption>")] if "<caption" in html else "", "")
    assert "顧客向けの利益ではありません" in visible and NOW.isoformat() in visible and "<button" not in html  # 見える注記
    assert admin.build_priority({}, pc) == {}
    from datetime import timedelta
    old = admin.build_priority(rep, pc, now=NOW + timedelta(days=8))
    assert old["stale"] and old["rows"] == [] and "作り直す" in admin._discovery({"priority": old, "metrics": {}})


# ── 選んだ1件（iPhone Duo 256GB）の登録と有効化 ───────────────────────────────────

DPID, DALIAS = "prod_iphoneduo_256", "iphoneduo_256"
DPARTS = ["MK244J/A", "MK254J/A"]


def canon():
    import yaml
    return yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))["products"]


def test_only_selected_candidate_registered_with_capacity_and_parts():
    import json
    prods = canon()
    reg_entries = [p["id"] for p in prods if p.get("price_observed_on")]
    assert DPID in reg_entries and not [x for x in reg_entries if x.startswith("prod_iphoneduo_") and x != DPID]
    e = next(p for p in prods if p["id"] == DPID)
    assert e["capacity"] == "256GB" and e["part_numbers"] == DPARTS and e["name"] == "iPhone Duo 256GB SIMフリー"
    led = json.loads((ROOT / "exports" / "discovery" / st.PRODUCT_FILE).read_text(encoding="utf-8"))["candidates"]
    assert led["apple-419a47e495b5"]["status"] == st.REGISTERED and led["apple-419a47e495b5"]["registered_id"] == DPID
    for other in ("apple-dc7090c0276a", "apple-88de14d448ca", "apple-d11a8e24b990"):                 # 他の容量は登録しない
        assert led.get(other, {}).get("status") != st.REGISTERED
    assert sum(1 for x in led.values() if x.get("product_name") == "iPhone Duo 256GB") == 1          # 重複なし


def test_duo_official_evidence_and_gate():
    from src.market import official_registry as reg
    e = next(p for p in canon() if p["id"] == DPID)
    v, ev, o = reg.VERIFIED_URLS[DPID], reg.IDENTITY_EVIDENCE[DPID], reg.OFFICIAL_DIRECT_OFFERS[DPID]
    assert v["price"] == o["price"] == 364800 and v["url"] == e["official_url"] and v["price_kind"] == "official_direct"
    assert set(ev["variant_skus"]) == set(DPARTS) and o["stock"] == "UNKNOWN"
    assert reg.official_direct_gate(DPID, e) == (True, ())
    assert reg.official_direct_gate(DPID, dict(e, part_numbers=DPARTS[:1]))[0] is False                 # 組が違えば通らない


def test_duo_buyback_rule_exact_and_color_safe():
    from src.collectors import buyback_kaitori_shouten as ks
    rows = [("iPhone Duo 256GB ナイトスカイ MK254J/A SIMフリー", 395000, "/products/detail/27089"),
            ("iPhone Duo 256GB スターホワイト MK244J/A SIMフリー", 390000, "/products/detail/27090"),
            ("iPhone Duo 512GB ナイトスカイ MK274J/A SIMフリー", 430000, "/products/detail/27091"),
            ("iPhone Duo 256GB ナイトスカイ MK254J/A au", 500000, "/products/detail/1")]
    assert [r[2] for r in ks.match_rows(rows, DALIAS)] == ["/products/detail/27089", "/products/detail/27090"]
    c = ks.KaitoriShoutenCsvCollector.__new__(ks.KaitoriShoutenCsvCollector)
    html = "<table><tr><th>品目</th><th>新品買取</th><th>中古買取</th></tr>" + "".join(
        f'<tr><td><a href="{h}">{n}</a></td><td class="num">¥{p:,}</td><td>¥1</td></tr>' for n, p, h in rows) + "</table>"
    assert c._parse_price(html, DALIAS, "") == 390000                              # 最高値の色（395,000）を使わない
    assert c._parse_detail_url(html, "x").endswith("/products/detail/27090")


def _deal(**kw):
    from src.content.ui import opportunity as opp
    from src.market.official_shipping import purchase_shipping
    ship = purchase_shipping(DPID, "https://www.apple.com/jp/shop/buy-iphone/iphone-duo", 364800)
    d = {"product_id": DPID, "title": "iPhone Duo 256GB SIMフリー", "genre": "iphone", "brand": "Apple",
         "official_price": 364800, "sell_price": 395000, "sell_shop": "買取商店",
         "sell_checked_at": "2026-10-21T09:21:00+09:00", "official_checked_at": "2026-10-21T09:21:00+09:00",
         "msrp_evidence": "VERIFIED_CURRENT", "sell_identity_verified": True, "purchase_shipping": ship["fee"],
         "purchase_shipping_status": ship["status"], "condition": "new_unopened",
         "sell_url": "https://www.kaitorishouten-co.jp/products/detail/27089", "user_level": "beginner_watch"}
    d.update(kw)
    v0 = opp.from_deal(d)
    d.setdefault("net_profit", d["sell_price"] - d["official_price"] - sum(a for _l, a in v0.cost_lines))
    return d


def test_duo_profit_states():
    from src.content.ui import opportunity as opp
    from src.market import actionability as act
    from src.market.opportunity_diagnostics import ACTIONABLE_AVAILABILITY
    d = _deal(stock_status="")
    assert d["net_profit"] == 395000 - 364800 - 1800 and opp.deal_reasons(d, NOW) == ()    # 正の利益（既存の計算）
    v = opp.from_deal(d)
    opp._apply_stock_freshness(v, NOW)
    assert v.availability not in ACTIONABLE_AVAILABILITY                                    # 在庫が不明なら行動できない
    a = act.evaluate(profitable=True, identity_ok=True, stock="UNKNOWN", stock_checked_at="", sale_method="normal",
                     buy_url="https://www.apple.com/jp/shop/buy-iphone/iphone-duo", now=NOW)
    assert a.actionable is False and "stock_unknown" in a.reasons
    assert "no_profit" in opp.deal_reasons(_deal(sell_price=360000), NOW)                    # 売値が安ければ no_profit
    assert opp.deal_reasons(_deal(sell_identity_verified=False), NOW) != ()                  # 売値が未確認なら確定にしない


def test_production_rule_requires_all_colors():
    """本番の照合も全色の行がそろうときだけ（最も安い色の行が消えた日に高い色の価格を使わない）。"""
    from src.collectors import buyback_kaitori_shouten as ks
    c = ks.KaitoriShoutenCsvCollector.__new__(ks.KaitoriShoutenCsvCollector)
    one = "<table><tr><th>品目</th><th>新品買取</th><th>中古買取</th></tr>" \
          '<tr><td><a href="/products/detail/27089">iPhone Duo 256GB ナイトスカイ MK254J/A SIMフリー</a></td>' \
          '<td class="num">¥395,000</td><td>¥1</td></tr></table>'
    assert c._parse_price(one, DALIAS, "") is None and c.last_failure_reason == "colors_incomplete"


def test_shipping_unknown_reason(monkeypatch):
    from src.market import official_shipping as osh
    monkeypatch.setattr(osh, "purchase_shipping", lambda *a, **k: {"fee": None})
    assert "shipping_unknown" in score()["reasons"]


# ── 監査の指摘への対応 ─────────────────────────────────────────────────────

def _tamper_root(tmp_path, mutate):
    import json
    import shutil
    root = tmp_path / "root"
    for rel in ("src/cli.py", ".github/workflows/daily_lp.yml", "config/products.yaml",
                "exports/discovery/product_candidates.json", "exports/discovery/priority.json"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, root / rel)
    p = root / "exports" / "discovery" / "priority.json"
    rep = json.loads(p.read_text(encoding="utf-8"))
    mutate(rep)
    p.write_text(json.dumps(rep, ensure_ascii=False), encoding="utf-8")
    return root


def _by(rep, name):
    return next(x for x in rep["ranked"] if x["product_name"] == name)


def _fix_total(x):
    x["score"] = sum(x["points"].values())


def test_865_catches_tampered_priority(tmp_path):
    sys_path = str(ROOT / "scripts")
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import deploy_check as dc
    assert dc._check_phase30_priority(_tamper_root(tmp_path / "ok", lambda r: None))[0]["level"] == "ok"   # 対照

    def spread(rep):
        x = _by(rep, "iPhone Duo 1TB")
        x["spread"], x["points"]["spread"] = 200000, 25
        _fix_total(x)

    def fake_row(rep):
        x = _by(rep, "iPhone 17e 512GB")
        x.update(buyback_state="CONFIRMED", buyback_sell=300000, spread=138400,
                 buyback_rows=[["iPhone 17e 512GB 黒 MZZZ9J/A SIMフリー", 300000, "/products/detail/9"]])
        x["points"].update(buyback=25, spread=25)
        _fix_total(x)

    def over_weight(rep):
        x = rep["ranked"][-1]
        x["points"]["official"] = 90
        _fix_total(x)

    def rank_order(rep):
        rep["ranked"].insert(0, rep["ranked"].pop())

    def future(rep):
        rep["evidence"]["fetches"][0]["fetched_at"] = "2099-12-31T00:00:00+09:00"

    def loss_to_profit(rep):
        x = _by(rep, "iPhone 17e 256GB")
        x["spread"], x["points"]["spread"] = 50000, 25
        _fix_total(x)
    def spread_only(rep):                                  # 点・順位は変えずに差の値だけを変える（差の式でしか捕まらない）
        _by(rep, "iPhone Duo 1TB")["spread"] += 100

    def rank_value(rep):                                   # 並びはそのまま、順位の値だけを書き換える
        rep["ranked"][-1]["rank"] = 1
    for i, f in enumerate((spread, fake_row, over_weight, rank_order, future, loss_to_profit, spread_only, rank_value)):
        res = dc._check_phase30_priority(_tamper_root(tmp_path / str(i), f))[0]
        assert res["level"] == "error", f.__name__


def test_cli_refuses_fetch_within_interval(led, monkeypatch):
    import json
    import src.cli as cli
    from datetime import datetime as _dt
    calls = []
    monkeypatch.setattr(cli, "_priority_fetch", lambda u: calls.append(u) or (None, "connection_error"))
    (led / "priority.json").write_text(json.dumps({"evidence": {"fetches": [
        {"fetched_at": _dt.now(tz=JST).isoformat(timespec="seconds")}]}}), encoding="utf-8")
    r = run("--fetch-buyback")
    assert r.exit_code == 1 and "間隔があいていません" in r.output and calls == []


def test_cli_failed_category_stops_further_pages(led, monkeypatch):
    import src.cli as cli
    calls = []
    two = INDEX
    s = st.load(led / st.PRODUCT_FILE)
    s["candidates"]["apple-air512"] = dict(DUO, candidate_id="apple-air512", product_name="iPhone Air 512GB",
                                           model_number="iPhone Air", capacity="512GB", part_numbers=["MG2C4J/A"],
                                           official_url="https://www.apple.com/jp/shop/buy-iphone/iphone-air")
    st.save(led / st.PRODUCT_FILE, s)
    monkeypatch.setattr(cli, "_priority_fetch",
                        lambda u: calls.append(u) or ((two, "") if u == pr.INDEX_URL else (None, "timeout")))
    assert run("--fetch-buyback", "--max-family-pages", "2").exit_code == 0 and len(calls) == 2


def test_admin_priority_skips_malformed_rows():
    from src.content.ui import admin
    rep = {"generated_at": NOW.isoformat(), "ranked": [{"candidate_id": "x", "points": "bad"},
                                                        {"candidate_id": "y", "points": {}, "spread": "1"}]}
    b = admin.build_priority(rep, {"candidates": {}}, now=NOW)
    assert [r["candidate_id"] for r in b["rows"]] == ["y"] and b["rows"][0]["spread"] is None
    admin._discovery({"priority": b, "metrics": {}})                                   # 落ちない


# ── 再レビューの指摘への対応 ───────────────────────────────────────────────

def test_865_independent_of_daily_ledger_changes(tmp_path):
    """台帳は毎日の発見で変わる（公式の価格の改定・候補の削除）。#865 は priority.json に保存した入力で確かめる（再レビュー H）。"""
    import json
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import deploy_check as dc
    root = _tamper_root(tmp_path, lambda r: None)
    led = root / "exports" / "discovery" / st.PRODUCT_FILE
    d = json.loads(led.read_text(encoding="utf-8"))
    d["candidates"]["apple-0e3db9718bb3"]["official_price"] = 259800                 # 値上げ
    d["candidates"].pop("apple-a43f61f54dc6")                                          # 90日で消えた
    led.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert dc._check_phase30_priority(root)[0]["level"] == "ok"
    root2 = _tamper_root(tmp_path / "x", lambda r: r["ranked"][0].pop("inputs"))
    assert dc._check_phase30_priority(root2)[0]["level"] == "error"                   # 入力が無ければ確かめられない
    root3 = _tamper_root(tmp_path / "y", lambda r: r["ranked"][0]["inputs"].pop("source"))
    assert dc._check_phase30_priority(root3)[0]["level"] == "error"                   # 入力の項目が欠けても確かめない


def test_cli_refuses_for_a_day_after_block(led, monkeypatch):
    import json
    import src.cli as cli
    from datetime import datetime as _dt
    from datetime import timedelta
    calls = []
    monkeypatch.setattr(cli, "_priority_fetch", lambda u: calls.append(u) or (None, "connection_error"))
    t = (_dt.now(tz=JST) - timedelta(hours=2)).isoformat(timespec="seconds")
    (led / "priority.json").write_text(json.dumps({"evidence": {"fetches": [{"fetched_at": t, "status": "blocked"}]}}),
                                       encoding="utf-8")
    r = run("--fetch-buyback")
    assert r.exit_code == 1 and calls == []
    (led / "priority.json").write_text(json.dumps({"evidence": {"fetches": [{"fetched_at": t, "status": "ok"}]}}),
                                       encoding="utf-8")
    assert run("--fetch-buyback").exit_code == 0 and calls                             # 対照（ブロックでなければ取得する）


def test_colors_incomplete_does_not_cut_off_shop():
    from src.collectors import polite
    c = polite.ShopCutoff()
    for _ in range(3):
        c.record("kaitori_shouten", False, "colors_incomplete")       # Air・Duo で全色がそろわない日
    assert not c.is_cut("kaitori_shouten")                            # カメラの買取は取りに行く
    c2 = polite.ShopCutoff()
    for _ in range(2):
        c2.record("kaitori_shouten", False, "timeout")
    assert c2.is_cut("kaitori_shouten")                                                  # 対照


def test_admin_priority_naive_time_does_not_crash():
    from src.content.ui import admin
    b = admin.build_priority({"generated_at": "2026-10-21T09:20:21", "ranked": [{"candidate_id": "x", "points": {}}]},
                             {"candidates": {}}, now=NOW)
    assert b["rows"] and not b["stale"]
