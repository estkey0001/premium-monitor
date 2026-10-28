"""Market Research Coverage Wave 2: 買取起点の選別（triage）・小売の価格の照会（retail_lookup）・調査候補への結び付け。

HTML は構造を保った合成の文字列（第三者のページの全文は入れない）。通信はしない（fetch を差し替える）。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.research import candidates as rc
from src.research import retail_lookup as rl
from src.research import triage as tr

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 28, 21, 0, tzinfo=JST)
FRESH = "2026-10-28T20:00:00+09:00"
ROOT = Path(__file__).resolve().parent.parent


def _row(name, price, jan="", shop="s", at=FRESH, url="u"):
    return {"shop": shop, "name": name, "jan": jan, "price": price, "url": url + name, "observed_at": at}


# ── 合成の小売のページ ───────────────────────────────────────────────────────────

NIKON_LIST = """<html><body>
<dl class="block-thumbnail-t--goods js-enhanced-ecommerce-item"><dt><a href="/shop/g/g4960759900001/" title="Z テスト1" class="x">x</a></dt>
<dd><div class="block-thumbnail-t--goods-name"><a href="/shop/g/g4960759900001/" title="Z テスト1">Z テスト1</a></div>
<div class="block-thumbnail-t--price-infos"><div class="block-thumbnail-t--price price js-enhanced-ecommerce-goods-price"> 300,000円</div></div></dd></dl>
<dl class="block-thumbnail-t--goods js-enhanced-ecommerce-item"><dt><a href="/shop/g/g4960759900002/" title="Z テスト2" class="x">x</a></dt>
<dd><div class="block-thumbnail-t--price price js-enhanced-ecommerce-goods-price"> 400,000円</div></dd></dl>
<dl class="block-thumbnail-t--goods js-enhanced-ecommerce-item"><dt><a href="/shop/g/g4960759900002/" title="Z テスト2(重複)" class="x">x</a></dt>
<dd><div class="block-thumbnail-t--price price js-enhanced-ecommerce-goods-price"> 410,000円</div></dd></dl>
<dl class="block-thumbnail-t--goods"><dt><a href="/shop/g/g4960759900003/" title="価格なし">x</a></dt></dl>
</body></html>"""

SAMSUNG_LIST = """<html><head><script type="application/ld+json">{"@type":"ItemList","itemListElement":[
{"@type":"ListItem","item":{"@type":"Product","@id":"https://www.samsung.com/jp/smartphones/galaxy-x/buy/?modelCode=SM-T100QZVASJP","name":"Galaxy テスト (SIMフリー)","url":"https://www.samsung.com/jp/smartphones/galaxy-x/buy/?modelCode=SM-T100QZVASJP","offers":{"price":"100000","availability":"https://schema.org/InStock"}}},
{"@type":"ListItem","item":{"@type":"Product","@id":"https://www.samsung.com/jp/smartphones/galaxy-y/buy/?modelCode=SM-T200QZVASJP","name":"Galaxy 旧","url":"https://www.samsung.com/jp/smartphones/galaxy-y/buy/?modelCode=SM-T200QZVASJP","offers":{"price":"38900","availability":"https://schema.org/OutOfStock"}}},
{"@type":"ListItem","item":{"@type":"Product","name":"型番なし","offers":{"price":"1000"}}}]}</script></head><body></body></html>"""

SONY_PAGE = """<html><body><div>ILCE-9TEST 翌日出荷 500,000 円(税込)</div><span>4548736100009</span></body></html>"""
SONY_PAGE_NO_JAN = """<html><body><div>ILCE-9TEST 翌日出荷 500,000 円(税込)</div></body></html>"""
SONY_PAGE_TWO = """<html><body><div>ILCE-9TEST 翌日出荷 500,000 円(税込)</div><div>ILCE-9TEST 在庫あり 510,000 円(税込)</div><b>4548736100009</b></body></html>"""
SONY_OUT = """<html><body><div>ILCE-9TEST 販売終了 500,000 円(税込)</div><b>4548736100009</b></body></html>"""


# ── triage ─────────────────────────────────────────────────────────────────────

def test_category_classification_puts_accessories_and_bundles_aside():
    assert tr.classify_category("iPhone 17 Pro 256GB") == tr.CAT_SMARTPHONE
    assert tr.classify_category("iPhone 17 Pro 用 ケース") == tr.CAT_ACCESSORY            # スマホの付属品を「スマホ」にしない
    assert tr.classify_category("Nikon Z6III ボディ") == tr.CAT_CAMERA
    assert tr.classify_category("プレイステーション5 Pro") == tr.CAT_GAME
    assert tr.classify_category("カメラ まとめ売り") == tr.CAT_BUNDLE
    assert tr.classify_category("炊飯器 NW-YD10") == tr.CAT_OTHER


def test_triage_rejects_name_only_stale_accessory_and_unknown_dates():
    t = lambda **k: tr.triage_row(**{"name": "Nikon Z6III ボディ", "ident_basis": "JAN", "price": 280000, "observed_at": FRESH, "now": NOW, **k})  # noqa: E731
    assert t(ident_basis="")["tier"] == tr.REJECTED and "no_exact_identity" in t(ident_basis="")["why"]      # 名前だけ
    assert t(observed_at="2026-09-01T00:00:00+09:00")["tier"] == tr.REJECTED                                  # 古い買取
    assert t(observed_at="")["tier"] == tr.REJECTED and t(observed_at="not a date")["tier"] == tr.REJECTED   # 取得日が読めない
    assert t(observed_at="2026-11-30T00:00:00+09:00")["tier"] == tr.REJECTED                                  # 未来（新しく見せない）
    assert t(name="Z6III 用 ストラップ")["tier"] == tr.REJECTED


def test_triage_tiers_follow_evidence_not_just_points():
    base = {"name": "Nikon Z6III ボディ", "ident_basis": "JAN", "price": 280000, "observed_at": FRESH, "now": NOW}
    assert tr.triage_row(**base, lookup_ready=True)["tier"] == tr.HIGH
    assert tr.triage_row(**base, lookup_matched=True)["tier"] == tr.HIGH
    assert tr.triage_row(**{**base, "price": 30000}, lookup_ready=True)["tier"] == tr.MEDIUM        # 小さい価格は HIGH にしない
    assert tr.triage_row(**{**base, "ident_basis": "MODEL_CODE"}, lookup_ready=True)["tier"] == tr.MEDIUM   # 型番だけは HIGH にしない
    assert tr.triage_row(**{**base, "name": "炊飯器 NW-YD10"}, lookup_ready=True)["tier"] == tr.LOW       # 優先カテゴリ外
    assert tr.triage_row(**{**base, "observed_at": "2026-10-20T00:00:00+09:00"}, lookup_ready=True)["tier"] == tr.MEDIUM  # 新しくない


def test_triage_builds_a_deterministic_top_50_queue():
    cands = [{"candidate_id": f"dp_{i:03d}", "name": f"Nikon Z9 テスト{i} ボディ", "identity_basis": "JAN", "observed_sell_price": 100000 + i,
              "observed_at": FRESH} for i in range(80)]
    a = tr.triage(cands, NOW, lookup_ready_of=lambda c: True)
    b = tr.triage(list(reversed(cands)), NOW, lookup_ready_of=lambda c: True)
    assert len(a["queue"]) == 50 == a["stats"]["top_queue"]
    assert [r["candidate_id"] for r in a["queue"]] == [r["candidate_id"] for r in b["queue"]]      # 入力の順序に依らない
    assert a["queue"][0]["queue_rank"] == 1 and a["stats"]["tier_counts"]["HIGH"] == 80


# ── retail_lookup: 一覧の読み取り ──────────────────────────────────────────────────

def test_nikon_index_parses_jan_name_and_price_and_skips_unreadable_rows():
    e = rl.NikonDirectAdapter().parse_index(NIKON_LIST)
    assert [(x["jan"], x["price"]) for x in e] == [("4960759900001", 300000), ("4960759900002", 400000)]   # 重複の JAN・価格なしは読まない
    assert rl.NikonDirectAdapter().parse_index("<html>構造が変わった</html>") == []


def test_samsung_index_reads_model_codes_and_marks_out_of_stock():
    e = {x["model"]: x for x in rl.SamsungAdapter().parse_index(SAMSUNG_LIST)}
    assert set(e) == {"SM-T100QZVASJP", "SM-T200QZVASJP"}                                       # 型番の無い行は読まない
    assert e["SM-T100QZVASJP"]["availability"] == rl.AVAIL_IN_STOCK and e["SM-T200QZVASJP"]["availability"] == rl.AVAIL_OUT


def test_sony_item_requires_one_price_line_and_one_jan():
    a = rl.SonyStoreAdapter()
    ok = a.parse_item(SONY_PAGE, "ILCE-9TEST")
    assert ok and ok[0]["price"] == 500000 and ok[0]["jan"] == "4548736100009" and ok[0]["availability"] == rl.AVAIL_IN_STOCK
    assert a.parse_item(SONY_PAGE_NO_JAN, "ILCE-9TEST") == []                                   # JAN が決まらないページは使わない
    assert a.parse_item(SONY_PAGE_TWO, "ILCE-9TEST") == []                                      # 価格が2種類 → どれかを選ばない
    assert a.parse_item(SONY_OUT, "ILCE-9TEST")[0]["availability"] == rl.AVAIL_OUT
    assert a.item_key({"name": "SONY ILCE-9TEST ボディ"}) == "ILCE-9TEST" and a.item_key({"name": "ILCE-1 と ILCE-9"}) == ""


# ── retail_lookup: 同一性 ─────────────────────────────────────────────────────────

def _idx(adapter_id="nikon_direct", **kw):
    ad = {a.adapter_id: a for a in rl.ADAPTERS}[adapter_id]
    html = {"nikon_direct": NIKON_LIST, "samsung_jp": SAMSUNG_LIST}[adapter_id]
    return {adapter_id: {"entries": ad.parse_index(html), "observed_at": FRESH, **kw}}


def test_lookup_matches_by_exact_jan_only_and_never_by_name():
    ident = {"basis": "JAN", "value": "4960759900001", "name": "Nikon Z9 テスト1 ボディ"}
    r = rl.lookup(ident, _idx())
    assert r["status"] == rl.MATCHED and r["price"] == 300000 and r["retailer"] == "ニコンダイレクト" and r["observed_at"] == FRESH
    assert r["identity_evidence"]["method"] == "jan_exact"
    # 名前は同じでも JAN が違う → 一致にしない
    assert rl.lookup({**ident, "value": "4960759999999"}, _idx())["status"] == rl.NO_MATCH
    # 識別子が名前だけ（basis なし）→ 一致にしない
    assert rl.lookup({"basis": "", "value": "", "name": "Nikon Z9 テスト1 ボディ"}, _idx())["status"] == rl.NO_MATCH


def test_lookup_rejects_wrong_brand_and_ambiguous_and_unsupported():
    # 別メーカーの名前の商品の JAN がニコンの行と偶然一致しても、ブランドが対応しないので照会の対象外
    assert rl.lookup({"basis": "JAN", "value": "4960759900001", "name": "Canon EOS テスト"}, _idx())["status"] == rl.UNSUPPORTED
    # 同じ JAN が価格の違う2行にあれば AMBIGUOUS
    idx = {"nikon_direct": {"entries": [{"name": "Z a", "price": 1, "url": "u1", "jan": "4960759900009", "model": "Z"},
                                        {"name": "Z b", "price": 2, "url": "u2", "jan": "4960759900009", "model": "Z"}], "observed_at": FRESH}}
    assert rl.lookup({"basis": "JAN", "value": "4960759900009", "name": "Nikon Z9"}, idx)["status"] == rl.AMBIGUOUS
    assert rl.lookup({"basis": "JAN", "value": "4960759900001", "name": "Nikon Z9"}, {})["status"] == rl.UNSUPPORTED      # 一覧を取れていない


def test_lookup_identity_mismatch_when_matched_row_belongs_to_another_brand():
    idx = {"nikon_direct": {"entries": [{"name": "Galaxy テスト", "price": 1, "url": "u", "jan": "4960759900001", "model": "X"}],
                            "observed_at": FRESH}}
    assert rl.lookup({"basis": "JAN", "value": "4960759900001", "name": "Nikon Z9 テスト"}, idx)["status"] == rl.IDENTITY_MISMATCH


def test_out_of_stock_price_is_not_purchasable_and_not_used_as_cost():
    ident = {"basis": "MODEL_CODE", "value": "SM-T200QZVASJP", "name": "Galaxy 旧 SM-T200QZVASJP"}
    r = rl.lookup(ident, _idx("samsung_jp"))
    assert r["status"] == rl.NOT_PURCHASABLE and r["availability_state"] == rl.AVAIL_OUT     # 販売終了・在庫なしの価格は仕入れ値にしない


def test_per_item_adapter_only_answers_for_models_actually_fetched():
    ad = rl.SonyStoreAdapter()
    idx = {"sony_store": {"entries": ad.parse_item(SONY_PAGE, "ILCE-9TEST"), "covered": ["ILCE-9TEST"], "observed_at": FRESH}}
    ok = rl.lookup({"basis": "JAN", "value": "4548736100009", "name": "SONY ILCE-9TEST ボディ"}, idx)
    assert ok["status"] == rl.MATCHED and ok["price"] == 500000
    other = rl.lookup({"basis": "JAN", "value": "4548736100099", "name": "SONY ILCE-1M9 ボディ"}, idx)
    assert other["status"] == rl.UNSUPPORTED                                                # 取っていない型番を NO_MATCH にしない
    # 取った型番でも JAN が違えば一致にしない
    assert rl.lookup({"basis": "JAN", "value": "4548736100077", "name": "SONY ILCE-9TEST ボディ"}, idx)["status"] == rl.NO_MATCH


# ── retail_lookup: 取得（遮断・上限） ───────────────────────────────────────────────

def test_build_indexes_skips_an_adapter_when_any_index_page_fails():
    calls = []

    def fetch(url):
        calls.append(url)
        return (NIKON_LIST, "") if url.endswith("r1010/") else (None, "site_blocked")
    out = rl.build_indexes([rl.NikonDirectAdapter()], fetch, NOW)
    assert out == {} and len(calls) == 2                                                    # 途中の一覧だけで引かない（取れた一覧の価格を捨てる）


def test_build_item_index_stops_after_a_block_and_caps_the_number_of_fetches():
    ad = rl.SonyStoreAdapter()
    calls = []

    def fetch(url):
        calls.append(url)
        return (SONY_PAGE, "") if len(calls) == 1 else (None, "site_blocked")
    idx = rl.build_item_index(ad, ["ILCE-9TEST", "ILCE-1M9", "ILCE-7M9"], fetch, NOW)
    assert len(calls) == 2 and idx["covered"] == ["ILCE-9TEST"]                            # 遮断された後は取らない
    calls.clear()
    rl.build_item_index(ad, [f"ILCE-{i}M9" for i in range(10)], lambda u: calls.append(u) or (None, "timeout"), NOW)
    assert len(calls) == ad.MAX_ITEMS                                                       # 取得数の上限


def test_run_lookups_fetches_only_what_the_queue_needs_and_records_status_counts():
    cands = [{"candidate_id": "dp_a", "name": "Nikon Z9 テスト1 ボディ", "identity_basis": "JAN", "jan": "4960759900001",
              "observed_sell_price": 280000, "observed_at": FRESH},
             {"candidate_id": "dp_b", "name": "炊飯器 テスト", "identity_basis": "JAN", "jan": "4900000000001",
              "observed_sell_price": 20000, "observed_at": FRESH}]
    calls = []

    def fetch(url):
        calls.append(url)
        return (NIKON_LIST, "")
    rec = rl.run_lookups(cands, NOW, fetch)
    assert rec["lookups"]["dp_a"]["status"] == rl.MATCHED and "dp_b" not in rec["lookups"]
    assert all("nikon" in u for u in calls) and rec["fetched_adapters"] == ["nikon_direct"]   # ニコン以外の取得器の一覧は取らない
    assert rec["status_counts"]["UNSUPPORTED"] == 1


# ── apply_lookups: 調査候補への結び付け ─────────────────────────────────────────────

def _dp(price=400000, retail_hint=None, basis="JAN", cid="dp_x", at=FRESH):
    return {"candidate_id": cid, "observed_at": at, "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": rc.DISCOVERED, "name": "Nikon Z9 テスト1 ボディ",
            "identity_basis": basis, "observed_sell_price": price, "retail_price_hint": retail_hint,
            "missing_requirements": ["CANONICAL_UNREGISTERED", "OFFICIAL_PRICE_UNKNOWN"]}


def _lk(price=300000, at=FRESH, status="MATCHED"):
    return {"status": status, "retailer": "ニコンダイレクト", "product_url": "https://nij.nikon.com/shop/g/g1/", "price": price,
            "availability_state": "UNKNOWN", "observed_at": at, "identity_evidence": {"basis": "JAN"}}


def test_positive_spread_becomes_research_candidate_never_confirmed():
    r = rc.apply_lookups([_dp(price=400000)], {"dp_x": _lk(300000)}, NOW, FRESH)[0]
    assert r["status"] == rc.RESEARCH_CANDIDATE and r["status"] != rc.VERIFIED
    assert r["raw_spread_hint"] == 100000 and r["retail_price"] == 300000
    assert {rc.OFFICIAL_UNVERIFIED, rc.PURCHASE_SHIPPING_UNKNOWN, "CANONICAL_UNREGISTERED"} <= set(r["missing_requirements"])
    assert rc.RETAIL_PRICE_MISSING not in r["missing_requirements"]


def test_high_priority_only_for_a_clean_lookup_with_a_plausible_spread():
    hp = rc.apply_lookups([_dp(price=330000)], {"dp_x": _lk(300000)}, NOW, FRESH)[0]
    assert hp["research_class"] == rc.HIGH_PRIORITY_RESEARCH
    anomaly = rc.apply_lookups([_dp(price=900000)], {"dp_x": _lk(300000)}, NOW, FRESH)[0]      # 差が小売の 50% 超 → 誤一致の疑い
    assert rc.PRICE_ANOMALY_SUSPECTED in anomaly["missing_requirements"] and anomaly["research_class"] == rc.STANDARD_RESEARCH
    partial = rc.apply_lookups([_dp(price=330000, basis="MODEL_CODE")], {"dp_x": _lk(300000)}, NOW, FRESH)[0]
    assert rc.IDENTITY_PARTIAL in partial["missing_requirements"] and partial["research_class"] == rc.STANDARD_RESEARCH


def test_zero_or_negative_spread_is_rejected_with_no_spread():
    r = rc.apply_lookups([_dp(price=280000)], {"dp_x": _lk(396000)}, NOW, FRESH)[0]
    assert r["status"] == rc.REJECTED and rc.NO_SPREAD in r["missing_requirements"] and r["research_class"] == rc.STANDARD_RESEARCH


def test_stale_or_unreadable_lookups_are_never_used():
    for gen, at in ((FRESH, "2026-10-20T00:00:00+09:00"),        # 結果の取得時刻が古い
                    ("2026-10-20T00:00:00+09:00", FRESH),        # 記録全体の生成時刻が古い
                    (None, FRESH), ("garbage", FRESH),            # 生成時刻が読めない
                    ("2026-12-01T00:00:00+09:00", FRESH),         # 未来
                    (FRESH, "")):                                  # 結果の取得時刻が無い
        r = rc.apply_lookups([_dp()], {"dp_x": _lk(at=at)}, NOW, gen)[0]
        assert r["status"] == rc.DISCOVERED and "retail_price" not in r and rc.RETAIL_PRICE_MISSING in r["missing_requirements"], (gen, at)


def test_non_matched_statuses_are_not_prices():
    for st in ("AMBIGUOUS", "IDENTITY_MISMATCH", "NO_MATCH", "UNSUPPORTED"):
        r = rc.apply_lookups([_dp()], {"dp_x": _lk(status=st)}, NOW, FRESH)[0]
        assert r["status"] == rc.DISCOVERED and "retail_price" not in r, st
    nv = rc.apply_lookups([_dp()], {"dp_x": _lk(status="NOT_PURCHASABLE")}, NOW, FRESH)[0]
    assert "retail_price" not in nv and rc.OFFICIAL_NOT_SOLD in nv["missing_requirements"]       # 販売終了は公式の価格を仕入れ値に使わない


def test_official_discovery_hint_still_makes_a_research_candidate_when_positive():
    r = rc.apply_lookups([_dp(price=400000, retail_hint=300000)], {}, NOW, None)[0]
    assert r["status"] == rc.RESEARCH_CANDIDATE and r["retail_basis"] == "official_discovery_hint"
    assert r["research_class"] == rc.STANDARD_RESEARCH                                         # ヒントだけでは高優先にしない


# ── build() への結合・公開境界 ──────────────────────────────────────────────────────

def _build(rows, lookups=None, gen=FRESH):
    products = [{"id": "p1", "name": "既存商品", "genre": "camera", "jan": "4900000000011", "part_numbers": []}]
    return rc.build(products=products, observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW,
                    catalog=rows, identity={}, retail_lookups=lookups, retail_lookups_generated_at=gen)


def test_build_counts_triage_and_lookup_and_keeps_research_out_of_verified():
    rows = [_row("Nikon Z9 テスト1 ボディ", 400000, jan="4960759900001"), _row("Nikon Z9 テスト2 ボディ", 250000, jan="4960759900002"),
            _row("炊飯器 テスト", 20000, jan="4900000000099"), _row("名前だけの商品", 99000)]
    first = _build(rows)[0]
    cid = {c["jan"]: c["candidate_id"] for c in first["product_candidates"]}
    lookups = {cid["4960759900001"]: _lk(300000), cid["4960759900002"]: _lk(300000)}
    rep, _ = _build(rows, lookups)
    bf = rep["buyback_first"]
    assert bf["lookup_matched"] == 2 and bf["research_candidates"] == 1 and bf["name_only_rejected"] == 1
    assert sum(bf["triage"].values()) == 3 and bf["top_queue"] >= 1
    assert rep["counts"]["research_candidates"] == 1 and rep["counts"]["verified"] == 0       # 確定にしない
    summary = rc.public_summary(rep)
    assert summary["research_candidate_count"] == 1 and summary["product_research_candidate_count"] == 1
    assert summary["retail_lookup_matched"] == 2 and set(summary["buyback_triage"]) == {"HIGH", "MEDIUM", "LOW", "REJECTED"}


def test_public_summary_has_no_individual_buyback_candidate_fields():
    rows = [_row("Nikon Z9 テスト1 ボディ", 400000, jan="4960759900001")]
    first = _build(rows)[0]
    cid = first["product_candidates"][0]["candidate_id"]
    rep, _ = _build(rows, {cid: _lk(300000)})
    text = json.dumps(rc.public_summary(rep), ensure_ascii=False)
    for secret in ("Nikon", "4960759900001", cid, "ニコンダイレクト", "nij.nikon.com", "400000", "300000", "テスト1"):
        assert secret not in text, secret
    assert not rc.find_private_keys(rc.public_summary(rep))
    for k in ("retail_price", "retail_url", "retail_retailer", "identity_value", "triage", "queue_rank", "lookup_status"):
        assert k in rc.PRIVATE_KEYS, k


def test_build_ignores_stale_lookup_record():
    rows = [_row("Nikon Z9 テスト1 ボディ", 400000, jan="4960759900001")]
    cid = _build(rows)[0]["product_candidates"][0]["candidate_id"]
    rep, _ = _build(rows, {cid: _lk(300000)}, gen="2026-10-20T00:00:00+09:00")
    assert rep["buyback_first"]["lookup_matched"] == 0 and rep["counts"]["research_candidates"] == 0


# ── scripts/research_retail_lookup.py ──────────────────────────────────────────────

def test_script_writes_private_record_prints_only_counts_and_survives_failures(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / "scripts"))
    import research_retail_lookup as script
    priv = tmp_path / "research"
    priv.mkdir()
    monkeypatch.setenv("RESEARCH_PRIVATE_DIR", str(priv))
    # 買取の一覧が無い → 何もしない（失敗にしない）
    assert script.main(fetch=lambda u: (None, "")) == 0 and not (priv / "retail_lookups.json").exists()
    rows = [_row("Nikon Z9 テスト1 ボディ", 280000, jan="4960759900001")]
    (priv / "buyback_catalog.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    assert script.main(fetch=lambda u: (NIKON_LIST, ""), now=NOW) == 0
    out = capsys.readouterr().out
    assert "Nikon" not in out and "4960759900001" not in out and "280000" not in out        # 公開ログに商品・価格を出さない
    rec = json.loads((priv / "retail_lookups.json").read_text(encoding="utf-8"))
    assert rec["generated_at"] == NOW.isoformat(timespec="seconds") and [v["status"] for v in rec["lookups"].values()] == ["MATCHED"]
    # 取得が全部失敗しても、例外にしない・古い一覧の価格を作らない
    (priv / "retail_lookups.json").unlink()
    assert script.main(fetch=lambda u: (None, "site_blocked"), now=NOW) == 0
    rec = json.loads((priv / "retail_lookups.json").read_text(encoding="utf-8"))
    assert rec["lookups"] == {} and rec["fetched_adapters"] == []


def test_private_lookup_record_is_not_tracked_and_workflow_runs_it_without_secrets():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".private" in ignore
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    i = wf.index("name: Research retail lookup")
    step = wf[i:wf.index("\n      # ", i) if "\n      # " in wf[i:] else len(wf)]
    assert "scripts/research_retail_lookup.py" in step and "continue-on-error: true" in step and "secrets." not in step


def test_retail_modules_only_fetch_through_the_polite_path():
    for f in ("src/research/retail_lookup.py", "src/research/triage.py", "scripts/research_retail_lookup.py"):
        t = (ROOT / f).read_text(encoding="utf-8")
        for bad in ("import requests", "urllib.request", "playwright", "proxies", '"User-Agent"', "stealth"):
            assert bad not in t, (f, bad)
    assert "recheck_official._fetch" in (ROOT / "scripts" / "research_retail_lookup.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("name,expected", [("Nikon Z6III ボディ", "nikon"), ("Galaxy S26 256GB", "samsung"),
                                           ("SONY ILCE-7M5", "sony"), ("EOS R6 Mark II", "canon"), ("iPhone 17 Pro", "apple"),
                                           ("名前だけの商品", ""), ("Nikon と SONY の比較", "")])
def test_brand_of_is_conservative(name, expected):
    assert rl.brand_of(name) == expected                                                    # 複数のブランドに当たる・当たらない名前は対象外


def test_deploy_check_873_passes_and_detects_unsafe_retail_and_collector_code(tmp_path):
    import shutil

    from scripts import deploy_check as dc
    assert [r["level"] for r in dc._check_coverage_wave2()] == ["ok"]
    root = tmp_path / "repo"
    for rel in ("src/research", "src/collectors/tcg/lottery", "src/tcg/event_quality.py", "scripts/research_retail_lookup.py",
                ".github/workflows/daily_lp.yml"):
        src = ROOT / rel
        if src.is_dir():
            shutil.copytree(src, root / rel, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(src, root / rel)
    mutations = (("src/research/retail_lookup.py", "import requests"),
                 ("src/research/retail_lookup.py", "proxies = {'http': 'x'}"),
                 ("src/research/triage.py", "from urllib.request import urlopen"),
                 ("scripts/research_retail_lookup.py", "HEADERS = {'User-Agent': 'Mozilla/5.0'}"),
                 ("src/collectors/tcg/lottery/hbst.py", "entry_url = 'https://x.example/apply'"),
                 ("src/collectors/tcg/lottery/hbst.py", "import httpx"))
    for rel, bad_line in mutations:
        f = root / rel
        orig = f.read_text(encoding="utf-8")
        f.write_text(orig + "\n" + bad_line + "\n", encoding="utf-8")
        assert dc._check_coverage_wave2(root)[0]["level"] == "error", (rel, bad_line)
        f.write_text(orig, encoding="utf-8")
    assert dc._check_coverage_wave2(root)[0]["level"] == "ok"
    wf = root / ".github/workflows/daily_lp.yml"
    orig = wf.read_text(encoding="utf-8")
    wf.write_text(orig.replace("        continue-on-error: true\n        env:\n          PYTHONPATH: .\n\n      # 6. Update alerts",
                               "        env:\n          PYTHONPATH: .\n\n      # 6. Update alerts"), encoding="utf-8")
    assert dc._check_coverage_wave2(root)[0]["level"] == "error"                             # 照会の step が失敗で止まる


# ── 最終レビューへの対応（引ける見込みの水増し・価格差なしの行・割引込み価格・年またぎ・詳細の構造変化） ─────────────

@pytest.mark.parametrize("name,ready", [("Nikon Z9 ボディ", True), ("Nikon Z f ボディ", True), ("Nikon D850 ボディ", False), ("NIKKOR Z 24-70mm f/4 S", False), ("Nikon Z6III 24-120 レンズキット", True), ("Nikon Z50II ボディ", True), ("Z 8 ボディ", True), ("Nikon Z fc ボディ", True),
                                        ("Nikon COOLPIX P1100", False), ("PlayStation 5 Pro", False), ("Xperia 1 VII", False),
                                        ("SONY ILCE-7M5 ボディ", False), ("Galaxy Z Fold7 SM-F966", True)])
def test_lookup_ready_counts_only_what_one_fetch_can_actually_look_up(name, ready):
    # 引けない商品（一覧に載らない一眼レフ・型番の無い Sony 製品）・取得数に上限のある商品ごとの取得器は「引ける見込み」にしない
    assert rl.ready_for_triage({"name": name}) is ready


def test_sony_supports_only_when_a_single_model_code_is_in_the_name():
    ad = rl.SonyStoreAdapter()
    assert ad.supports({"name": "SONY ILCE-7M5 ボディ"}) and not ad.supports({"name": "PlayStation 5 Pro"})
    assert not ad.supports({"name": "SONY ILCE-1 / ILCE-9"})                                     # 型番が複数 → どれか決められない


def test_candidates_without_spread_after_lookup_do_not_enter_the_queue_or_high():
    rows = [_row("Nikon Z9 テスト1 ボディ", 250000, jan="4960759900001"), _row("Nikon Z9 テスト2 ボディ", 330000, jan="4960759900002")]
    first = _build(rows)[0]
    cid = {c["jan"]: c["candidate_id"] for c in first["product_candidates"]}
    rep, _ = _build(rows, {cid["4960759900001"]: _lk(300000), cid["4960759900002"]: _lk(300000)})
    by = {c["jan"]: c for c in rep["product_candidates"]}
    assert by["4960759900001"]["status"] == rc.REJECTED and by["4960759900001"]["triage"]["tier"] == tr.REJECTED   # 価格差なし
    assert by["4960759900001"]["triage"]["why"] == ["lookup_no_spread"] and "queue_rank" not in by["4960759900001"]
    assert by["4960759900002"]["status"] == rc.RESEARCH_CANDIDATE and by["4960759900002"]["triage"]["tier"] == tr.HIGH
    assert rep["buyback_first"]["triage"]["REJECTED"] == 1 and rep["buyback_first"]["triage"]["HIGH"] == 1


def test_discounted_listing_price_never_becomes_high_priority_research():
    lk = {**_lk(300000), "price_caveat": "一覧の価格はキャンペーン割引込みの可能性（定価ではない）"}
    r = rc.apply_lookups([_dp(price=330000)], {"dp_x": lk}, NOW, FRESH)[0]
    assert r["status"] == rc.RESEARCH_CANDIDATE and r["research_class"] == rc.STANDARD_RESEARCH and r["retail_caveat"]
    assert rl.lookup({"basis": "MODEL_CODE", "value": "SM-T100QZVASJP", "name": "Galaxy テスト SM-T100QZVASJP"},
                     _idx("samsung_jp"))["price_caveat"]                                         # Samsung の結果には注意の印が付く


def test_title_ended_handles_a_range_that_crosses_the_new_year():
    from src.collectors.tcg.lottery import clabo
    assert clabo._title_ended("抽選(応募期間:12/28~1/3)", "2026-12-30") is False                 # 年またぎの途中は終了していない
    assert clabo._title_ended("抽選(応募期間:12/28~1/3)", "2027-01-10") is True
    assert clabo._title_ended("抽選(応募期間:12/28~1/3)", "2027-01-02") is False


def test_stale_buyback_side_is_never_high_priority_even_with_a_fresh_lookup():
    old = rc.apply_lookups([_dp(price=330000, at="2026-10-20T00:00:00+09:00")], {"dp_x": _lk(300000)}, NOW, FRESH)[0]
    assert old["status"] == rc.RESEARCH_CANDIDATE and old["research_class"] == rc.STANDARD_RESEARCH and rc.BUY_STALE in old["missing_requirements"]
    unknown = rc.apply_lookups([_dp(price=330000, at="")], {"dp_x": _lk(300000)}, NOW, FRESH)[0]
    assert unknown["research_class"] == rc.STANDARD_RESEARCH
    fresh = rc.apply_lookups([_dp(price=330000)], {"dp_x": _lk(300000)}, NOW, FRESH)[0]
    assert fresh["research_class"] == rc.HIGH_PRIORITY_RESEARCH and rc.BUY_STALE not in fresh["missing_requirements"]


def test_item_index_also_stops_after_429_and_robots_unreachable():
    ad = rl.SonyStoreAdapter()
    for reason in ("rate_limited_429", "http_403", "robots_unreachable", "blocked_cloud_ip"):
        calls = []
        rl.build_item_index(ad, ["ILCE-1M9", "ILCE-7M9", "ILCE-9M9"], lambda u, r=reason: calls.append(u) or (None, r), NOW)
        assert len(calls) == 1, reason


def test_title_ended_future_new_year_range_is_not_ended():
    from src.collectors.tcg.lottery import clabo
    assert clabo._title_ended("抽選(応募期間:12/28~1/3)", "2026-11-20") is False                 # これから始まる年またぎの期間
