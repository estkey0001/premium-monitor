# -*- coding: utf-8 -*-
"""camera_refresh（週次の更新）のテスト。取り込み・失敗した取得元の引き継ぎ・書き込み・履歴・ページ。"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.research import camera_refresh as cf
from src.research import camera_routes as cr

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=JST)
CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "camera_routes.yaml").read_text(encoding="utf-8"))
NAMES = {"RICOH GR IV HDF": "prod_gr4_hdf", "RICOH GR IV": "prod_gr4"}
SHIP0 = lambda pid, url, price: {"fee": 0, "source": "t"}


def research(buyback=None, official_price=200000, stock="AVAILABLE", brand="RICOH"):
    bb = buyback if buyback is not None else [
        {"shop": "買取商店", "item_title": "コンパクトデジタルカメラ RICOH GR IV HDF", "price_jpy": 240000, "condition": "UNOPENED",
         "url": "https://www.kaitorishouten-co.jp/products/detail/1", "is_product_page": True, "checked_at": "2026-11-18",
         "source_updated_at": "2026-11-17", "result": "FOUND"},
        {"shop": "買取B", "item_title": "RICOH GR IV HDF", "price_jpy": 238000, "condition": "UNOPENED",
         "url": "https://www.netoff.co.jp/kaden/detail/2", "is_product_page": True, "checked_at": "2026-11-18", "source_updated_at": "2026-11-18", "result": "FOUND"}]
    return {"brand": brand, "products": [{
        "product": "RICOH GR IV HDF", "registered": True,
        "official": {"shop": "リコーイメージングストア", "price_jpy": official_price, "price_kind": "OFFICIAL_RETAIL", "stock": stock, "stock_evidence": "購入ボタンあり",
                     "url": "https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid=S0001566&cat=002010", "checked_at": "2026-11-18", "purchase_shipping_jpy": 0},
        "retail": [], "buyback": bb, "listing": [], "sold": []}],
        "discovered": [{"name": "未登録の新機種", "status": "DISCOVERED"}],
        "source_results": [{"source": "買取商店", "result": "FOUND", "reason": ""}, {"source": "ヨドバシ.com", "result": "FAILED", "reason": "timeout"},
                           {"source": "ヨドバシ・ビック・マップカメラ", "result": "FAILED", "reason": "未取得"}],
        "lotteries": [{"product": "記事の抽選", "retailer": "x", "official_url": "https://www.ricoh-imaging.co.jp/y", "evidence": "公式ページ自体は未取得。記事の記載"}]}


def write_dir(tmp_path, doc):
    d = tmp_path / "2026-11-18"
    d.mkdir(parents=True)
    (d / "research_camera_RICOH.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return d


def run(tmp_path, doc, old=None, obs=None, now=NOW):
    d = write_dir(tmp_path, doc) if not (tmp_path / "2026-11-18").exists() else tmp_path / "2026-11-18"
    return cf.refresh(d, "2026-11-18", now=now, old_market=old, cfg=CFG, obs_doc=obs or {}, names=NAMES,
                      official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800)


def test_refresh_buy_route_and_quality_zero(tmp_path):
    st = run(tmp_path, research())
    r = next(x for x in st["market"]["routes"] if x["route_type"] == "A")
    assert r["profit_status"] == "PROFITABLE" and r["decision"] == "BUY" and r["net_profit"] == 240000 - 200000 - 1800
    assert not any(st["quality"].values()) and cf.validate(st) == []


def test_lottery_dependent_is_not_buy(tmp_path):
    st = run(tmp_path, research(stock="LOTTERY_DEPENDENT"))
    r = next(x for x in st["market"]["routes"] if x["route_type"] == "A")
    assert r["decision"] == "WAIT" and not r["executable"]


def test_failed_rows_are_not_prices(tmp_path):
    doc = research(buyback=[{"shop": "買取X", "item_title": None, "price_jpy": None, "condition": "UNKNOWN", "url": "", "result": "FAILED"}])
    st = run(tmp_path, doc)
    assert st["report"]["found"]["buyback"] == 0
    assert all(x["profit_status"] == "NOT_CALCULATED" for x in st["market"]["routes"])


def test_source_matrix_names_and_lumps():
    mx = cf.source_matrix(research()["source_results"] + [{"source": "ヨドバシ", "result": "FOUND", "brand": "Sony"}])
    keys = {(v["shop"], v["role"]) for v in mx.values()}
    assert ("ヨドバシ", "retail") in keys
    lump = [v for v in mx.values() if v["shop"] in ("マップカメラ", "ビックカメラ")]
    assert lump and all(v["result"] == "FAILED" for v in lump)       # まとめた記載は読めたことにしない


def test_existing_pipeline_rows_only_strict_product_pages():
    obs = {"observations": [
        {"price_type": "buyback_price", "link_type": "item", "item_url": "https://www.kaitorishouten-co.jp/products/detail/9", "is_fresh": True,
         "rejection_reason": "", "product_id": "prod_gr4", "is_exact_product_match": True, "product_match_reason": "strict_model_match",
         "is_body_only": True, "price": 205000, "condition": "new_unopened", "observed_at": "2026-11-18T00:45:05+09:00", "source_name": "買取商店"},
        {"price_type": "buyback_price", "link_type": "shop_home", "item_url": "https://x/", "is_fresh": False, "rejection_reason": "stale_over_14d",
         "product_id": "prod_gr4", "is_exact_product_match": False, "price": 190000, "condition": "new_unopened", "observed_at": "2026-08-22T00:00:00+09:00"}]}
    rows = cf.existing_buyback_rows(obs, NAMES)
    assert list(rows) == ["RICOH GR IV"] and len(rows["RICOH GR IV"]) == 1 and rows["RICOH GR IV"][0]["condition"] == "UNOPENED"


def test_carry_over_keeps_old_checked_at_and_goes_stale(tmp_path):
    st1 = run(tmp_path, research())
    old = cf._public_market(st1)
    # 翌々週: 買取の取得が全部失敗（行が無い）。前回の行を引き継ぐが、日付は今日にしない
    later = NOW + timedelta(days=14)
    import shutil
    shutil.rmtree(tmp_path / "2026-11-18")
    d = write_dir(tmp_path, research(buyback=[]))
    st2 = cf.refresh(d, "2026-12-02", now=later, old_market=old, cfg=CFG, obs_doc={}, names=NAMES, official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800)
    carried = [o for p in st2["market"]["products"] for o in p["observations"] if o.get("carried")]
    assert carried and all(o["checked_at"] == "2026-11-18" for o in carried)
    assert all(o["freshness"] == cr.STALE for o in carried)
    assert st2["report"]["carried_rows"] and not any(st2["quality"].values())
    assert all(r["decision"] != "BUY" for r in st2["market"]["routes"])


def test_validate_blocks_on_quality_problem(tmp_path):
    st = run(tmp_path, research())
    st["quality"]["double_count_fee"] = 1
    assert cf.validate(st)


def test_write_all_history_overwrites_same_day_and_hides_discovered(tmp_path):
    st = run(tmp_path, research())
    exp = tmp_path / "exp"
    cf.write_all(st, tmp_path / "2026-11-18", export_dir=exp, build_page=None)
    cf.write_all(st, tmp_path / "2026-11-18", export_dir=exp, build_page=None)
    hist = json.loads((exp / cf.HISTORY_FILE).read_text(encoding="utf-8"))
    assert len(hist["snapshots"]) == 1 and hist["snapshots"][0]["observations"]
    pub = (exp / cf.MARKET_FILE).read_text(encoding="utf-8")
    assert "未登録の新機種" not in pub                               # 未確認の新商品の名前は公開しない
    assert json.loads(pub)["hidden_counts"]["discovered_products_unverified"] == 1
    assert "未登録の新機種" in (tmp_path / "2026-11-18" / "camera_candidates.json").read_text(encoding="utf-8")
    assert json.loads(pub)["notification_dry_run"]["sent"] == 0
    assert json.loads(pub)["lotteries"] == []                                   # 記事・未取得の抽選・登録機種に照合できない抽選は公開しない


def test_history_keeps_26(tmp_path):
    old = {"snapshots": [{"date": f"2026-01-{i:02d}"} for i in range(1, 29)]}
    out = cf.merge_history(old, {"date": "2026-11-18"})
    assert len(out["snapshots"]) == 26 and out["snapshots"][-1]["date"] == "2026-11-18"


def test_name_key_merges_body_variants():
    assert cr.name_key("Nikon Z8 ボディ") == cr.name_key("Nikon Z8")
    assert cr.name_key("Canon EOS R5 Mark II ボディー") == cr.name_key("Canon EOS R5 Mark II")


def test_page_renders_zero_routes_honestly_and_escapes(tmp_path):
    from src.content.camera_market_page import render
    st = run(tmp_path, research(buyback=[]))
    m = cf._public_market(st)
    m["products"][0]["product"] = "<script>alert(1)</script>"
    html = render(m, now=NOW)
    assert "<script>alert(1)" not in html and "計算できる利益ルートは 0 件" in html
    # 調査が古いと BUY を出さない
    st2 = run(tmp_path / "b", research())
    old_html = render(cf._public_market(st2), now=NOW + timedelta(days=20))
    assert "調査が古い" in old_html and "BUY（買う）" not in old_html


def test_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    d = write_dir(tmp_path, research())
    monkeypatch.setattr(cf, "EXPORT_DIR", tmp_path / "exp")
    monkeypatch.setattr(cf, "WEEKLY_ROOT", tmp_path)
    cf.main(["--dir", str(d)])
    assert not (tmp_path / "exp").exists() and not (d / "camera_candidates.json").exists()
    assert '"mode": "DRY_RUN"' in capsys.readouterr().out


# ---- 独立レビューの指摘の回帰 ----
def test_rows_from_a_source_reported_failed_are_dropped(tmp_path):
    doc = research()
    doc["source_results"] = [{"source": "買取商店", "result": "FAILED", "reason": "403"}]       # 単一の店の失敗報告
    st = run(tmp_path, doc)
    bb = [o for p in st["market"]["products"] for o in p["observations"] if o["kind"] == "buyback" and o["source"] == "買取商店"]
    assert bb == []                                                                              # FOUND と書かれていても今日の確認にしない


def test_lottery_cross_check_marks_lottery_dependent(tmp_path):
    doc = research(stock="AVAILABLE")
    doc["lotteries"] = [{"product": "RICOH GR IV HDF 抽選販売", "retailer": "リコーイメージングストア", "application_end": "2026-11-30",
                         "official_url": "https://www.ricoh-imaging.co.jp/x", "evidence": "公式ページ"}]
    st = run(tmp_path, doc)
    r = next(x for x in st["market"]["routes"] if x["route_type"] == "A")
    assert r["buy"]["stock"] == "LOTTERY_DEPENDENT" and r["decision"] == "WAIT"


def test_unregistered_products_are_not_public(tmp_path):
    doc = research()
    doc["products"].append({"product": "Leica SL4 Prototype", "official": None, "retail": [], "listing": [], "sold": [],
                            "buyback": [{"shop": "買取商店", "item_title": "Leica SL4 Prototype", "price_jpy": 900000, "condition": "NEW",
                                         "url": "https://www.kaitorishouten-co.jp/products/detail/5", "is_product_page": True, "checked_at": "2026-11-18", "source_updated_at": "2026-11-18", "result": "FOUND"}]})
    st = run(tmp_path, doc)
    pub = cf._public_market(st)
    assert "Leica SL4" not in json.dumps(pub, ensure_ascii=False) and pub["hidden_counts"]["unregistered_or_unpriced_products_not_shown"] >= 1


def test_carried_rows_do_not_keep_available_stock(tmp_path):
    st1 = run(tmp_path, research())
    old = cf._public_market(st1)
    import shutil
    shutil.rmtree(tmp_path / "2026-11-18")
    d = write_dir(tmp_path, {**research(buyback=[]), "products": [{**research()["products"][0], "official": None, "buyback": [], "retail": []}]})
    st2 = cf.refresh(d, "2026-11-18", now=NOW, old_market=old, cfg=CFG, obs_doc={}, names=NAMES, official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800)
    for p in st2["market"]["products"]:
        for o in p["observations"]:
            if o.get("carried"):
                assert o.get("stock") in (None, "UNKNOWN")
    assert not any(st2["quality"].values())            # 同じ日の再実行で引き継いだ行が品質違反にならない


def test_validate_blocks_private_strings(tmp_path):
    st = run(tmp_path, research())
    st["report"]["sources_failed"]["ヨドバシ"] = "RICOH/retail: /Users/someone/x"
    assert any("絶対パス" in p for p in cf.validate(st))


def test_lottery_is_published_only_for_registered_product_names(tmp_path):
    doc = research()
    doc["lotteries"] = [{"product": "RICOH GR IV / GR IV HDF（GR SPACE TOKYO）", "retailer": "GR SPACE TOKYO", "application_end": "2026-11-30",
                         "official_url": "https://www.ricoh-imaging.co.jp/x", "evidence": "公式ページで確認"},
                        {"product": "未発表の新機種 XYZ-9999", "retailer": "公式", "application_end": "2026-11-30",
                         "official_url": "https://www.ricoh-imaging.co.jp/x", "evidence": "公式ページで確認"}]
    st = run(tmp_path, doc)
    pub = cf._public_market(st)
    assert [x["product"] for x in pub["lotteries"]] == ["RICOH GR IV HDF"] and "XYZ-9999" not in json.dumps(pub, ensure_ascii=False)


def test_carried_sell_price_is_never_buy(tmp_path):
    st1 = run(tmp_path, research())
    old = cf._public_market(st1)
    import shutil
    shutil.rmtree(tmp_path / "2026-11-18")
    # 翌日: 買取の取得が全部失敗（行なし）。仕入れは今日の公式・在庫あり
    nxt = NOW + timedelta(days=1)
    doc = research(official_price=200000)
    doc["products"][0]["buyback"] = []
    doc["products"][0]["official"]["checked_at"] = "2026-11-19"
    d = write_dir(tmp_path, doc)
    st2 = cf.refresh(d, "2026-11-19", now=nxt, old_market=old, cfg=CFG, obs_doc={}, names=NAMES, official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800)
    a = next(x for x in st2["market"]["routes"] if x["route_type"] == "A")
    assert a["sell"] and a["sell"]["carried"] is True
    assert a["decision"] != "BUY" and not a["executable"] and not any(st2["quality"].values())


def test_pipeline_rows_alone_are_not_used_and_only_confirm_same_url(tmp_path):
    obs = {"observations": [{"price_type": "buyback_price", "link_type": "item", "item_url": "https://www.kaitorishouten-co.jp/products/detail/77",
                             "is_fresh": True, "rejection_reason": "", "product_id": "prod_gr4", "is_exact_product_match": True,
                             "product_match_reason": "strict_model_match", "is_body_only": True, "price": 205000, "condition": "new_unopened",
                             "observed_at": "2026-11-18T00:45:05+09:00", "source_name": "買取商店"}]}
    st = run(tmp_path, research(), obs=obs)
    assert st["pipeline_rows_unused"] == 1
    assert not any(o.get("from_pipeline") for p in st["market"]["products"] for o in p["observations"])


def test_buyback_shops_not_inflated_by_name_variants(tmp_path):
    bb = [{"shop": "買取商店", "item_title": "RICOH GR IV HDF", "price_jpy": 240000, "condition": "UNOPENED", "url": "https://www.kaitorishouten-co.jp/products/detail/5", "is_product_page": True,
           "checked_at": "2026-11-18", "source_updated_at": "2026-11-18", "result": "FOUND"},
          {"shop": "買取商店（本店）", "item_title": "RICOH GR IV HDF", "price_jpy": 238000, "condition": "UNOPENED", "url": "https://www.kaitorishouten-co.jp/products/detail/6", "is_product_page": True,
           "checked_at": "2026-11-18", "source_updated_at": "2026-11-18", "result": "FOUND"}]
    st = run(tmp_path, research(buyback=bb))
    a = next(x for x in st["market"]["routes"] if x["route_type"] == "A")
    assert a["sell"]["evidence"]["shops"] == 1 and a["decision"] != "BUY"


def test_public_json_has_no_rejected_rows_aggregators_or_free_text(tmp_path):
    doc = research()
    doc["products"][0]["identity_note"] = "メモ foo@bar.com /Users/x"
    doc["products"][0]["listing"] = [{"market": "みんなのカメラ（集約サイト。店名不明）", "item_title": "RICOH GR IV HDF", "price_jpy": 290000, "condition": "NEW",
                                      "url": "https://www.minnacamera.com/1", "checked_at": "2026-11-18", "purchasable_now": True, "result": "FOUND"}]
    doc["source_results"].append({"source": "買取商店", "result": "FAILED", "reason": "/Users/x/log 検索要約 123,456円 foo@bar.com"})
    st = run(tmp_path, doc)
    txt = json.dumps(cf._public_market(st), ensure_ascii=False)
    for bad in ("foo@bar.com", "/Users/", "290000", "minnano"):
        assert bad not in txt
    assert cf.validate(st) == [] or all("絶対パス" not in p for p in cf.validate(st))


@pytest.mark.parametrize("stock", ["在庫ありません", "在庫あり（お取り寄せ・納期未定）", "店頭在庫あり", "在庫あり 抽選"])
def test_stock_strings_not_available(stock):
    assert cr.stock_of({"stock": stock}) != cr.AVAILABLE


def test_bool_and_implausible_prices_are_not_buy(tmp_path):
    assert not any(o["price"] for o in cr.observations({"product": "RICOH GR IV HDF", "buyback": [{"shop": "x", "item_title": "RICOH GR IV HDF", "price_jpy": True,
                                                         "condition": "NEW", "url": "https://x", "checked_at": "2026-11-18"}]}, NOW, CFG))
    st = run(tmp_path, research(official_price=15000))                 # 桁落ち（200,000 円のはずが 15,000 円）
    a = next(x for x in st["market"]["routes"] if x["route_type"] == "A")
    assert a["decision"] != "BUY" and "price_implausible" in a["reasons"] or a["profit_status"] == "NOT_CALCULATED"


def test_freshness_basis_is_the_older_date_and_future_is_unknown():
    row = {"checked_at": "2026-10-01", "source_updated_at": "2026-11-18"}
    assert cr.freshness(row, NOW, CFG)[0] == cr.UNKNOWN_FRESHNESS            # 更新日が確認日より新しい = 不整合
    assert cr.freshness({"checked_at": "2026-11-19"}, NOW, CFG)[0] == cr.UNKNOWN_FRESHNESS
    assert cr.freshness({"checked_at": "2026-11-18", "source_updated_at": "2026-11-01"}, NOW, CFG)[0] == cr.STALE


def test_input_carried_flag_is_ignored(tmp_path):
    doc = research()
    for r in doc["products"][0]["buyback"]:
        r["carried"] = True
        r["checked_at"] = "2027-05-01"
    st = run(tmp_path, doc)
    assert all(not o["carried"] for p in st["market"]["products"] for o in p["observations"] if o["kind"] == "buyback")


@pytest.mark.parametrize("title", ["RICOH GR IV HDF + 保護フィルム", "RICOH GR IV HDF 海外版", "RICOH GR IV HDF（2025）", "RICOH GR IV HDF バッテリー"])
def test_accessory_and_overseas_titles_rejected(title):
    assert cr.identity_ok("RICOH GR IV HDF", title)[0] is False


def test_failed_sold_rows_are_not_used():
    rec = {"brand": "x", "products": [{"product": "RICOH GR IV HDF", "retail": [], "buyback": [], "listing": [],
           "sold": [{"market": "メルカリ", "item_title": "RICOH GR IV HDF", "price_jpy": 250000, "condition": "NEW", "sold_at": "2026-11-10",
                     "url": "https://jp.mercari.com/item/m123456789", "result": "FAILED"}]}]}
    out = cf.clean_records(rec["products"])
    assert out[0]["sold"] == []


def test_research_date_follows_source_folder(tmp_path, monkeypatch, capsys):
    d = tmp_path / "2026-10-01"
    d.mkdir()
    (d / "research_camera_RICOH.json").write_text(json.dumps(research(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cf, "EXPORT_DIR", tmp_path / "exp")
    monkeypatch.setattr(cf, "WEEKLY_ROOT", tmp_path)
    cf.main([])
    out = capsys.readouterr().out
    assert "年" not in out.split('"mode"')[0]            # 出力が JSON として読めること
    st_date = json.loads(out)
    assert st_date["mode"] == "DRY_RUN"


def test_page_hides_buy_when_dates_are_old_or_future(tmp_path):
    from src.content.camera_market_page import render
    st = run(tmp_path, research())
    pub = cf._public_market(st)
    assert "BUY（買う）" in render(pub, now=NOW)
    assert "BUY（買う）" not in render(pub, now=NOW + timedelta(days=3))
    assert "BUY（買う）" not in render({**pub, "research_date": "2027-01-01"}, now=NOW)


# ---- 再レビューの指摘の回帰（取り込み側） ----
@pytest.mark.parametrize("res", ["ERROR", "TIMEOUT", "PARTIAL", "SKIPPED", "UNREADABLE", "BLOCKED", "FAILED"])
def test_unknown_or_bad_result_words_are_failures(tmp_path, res):
    doc = research()
    doc["source_results"] = [{"source": "リコーイメージングストア", "result": res, "reason": "x"}]
    st = run(tmp_path, doc)
    assert all(o["kind"] != "official" for p in st["market"]["products"] for o in p["observations"]) or all(
        r["decision"] != "BUY" for r in st["market"]["routes"])
    assert "リコー公式" in st["report"]["sources_failed"] or "リコーイメージングストア" in st["report"]["sources_failed"]


def test_official_row_with_bad_result_is_dropped(tmp_path):
    doc = research()
    doc["products"][0]["official"]["result"] = "BLOCKED"
    st = run(tmp_path, doc)
    assert all(r["decision"] != "BUY" for r in st["market"]["routes"])


def test_sold_rows_from_failed_market_are_dropped():
    recs = [{"brand": "x", "product": "RICOH GR IV HDF", "retail": [], "buyback": [], "listing": [], "official": None,
             "sold": [{"market": "メルカリ", "price_jpy": 250000, "url": "https://jp.mercari.com/item/m1"}]}]
    out, dropped = cf.drop_failed_source_rows(recs, [{"brand": "x", "source": "メルカリ", "result": "BLOCKED", "reason": "403"}])
    assert out[0]["sold"] == [] and dropped


def test_lottery_same_brand_official_row_is_lottery_even_if_shop_names_differ(tmp_path):
    doc = research()
    doc["brand"] = "RICOH"
    doc["products"][0]["brand"] = "RICOH"
    doc["lotteries"] = [{"product": "RICOH GR IV / GR IV HDF", "retailer": "GR SPACE TOKYO", "brand": "RICOH", "application_end": "2026-11-30",
                         "official_url": "https://www.ricoh-imaging.co.jp/x", "evidence": "公式ページ"}]
    st = run(tmp_path, doc)
    a = next(x for x in st["market"]["routes"] if x["route_type"] == "A")
    assert a["buy"]["stock"] == "LOTTERY_DEPENDENT" and a["decision"] == "WAIT"


def test_validate_requires_fresh_rows(tmp_path):
    st = run(tmp_path, research(buyback=[]))
    for p in st["market"]["products"]:
        for o in p["observations"]:
            o["carried"] = True
    assert any("新しく確認できた" in p for p in cf.validate(st))


def test_dir_name_must_be_a_date(tmp_path, monkeypatch, capsys):
    d = tmp_path / "old_research"
    d.mkdir()
    (d / "research_camera_RICOH.json").write_text(json.dumps(research(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cf, "EXPORT_DIR", tmp_path / "exp")
    assert cf.main(["--dir", str(d)]) == 1
    assert "YYYY-MM-DD" in capsys.readouterr().out


def test_public_source_names_are_canonical_only(tmp_path):
    doc = research()
    doc["source_results"].append({"source": "価格.com 最安 98,000円 まとめ https://a.example/x?tok=abc", "result": "FOUND", "reason": ""})
    txt = json.dumps(cf._public_market(run(tmp_path, doc)), ensure_ascii=False)
    assert "98,000" not in txt and "tok=abc" not in txt


# ---- 3 回目のレビューの回帰（取り込み側） ----
def test_public_labels_come_from_domain_not_free_text(tmp_path):
    doc = research()
    doc["brand"] = "未発表機 α9 IV"
    doc["products"][0]["buyback"][0]["shop"] = "Sony α9 IV 後継の噂 ¥1,200,000"
    doc["lotteries"] = [{"product": "RICOH GR IV HDF", "retailer": "未発表の噂 ¥9,999,999", "application_end": "2026-11-30",
                         "official_url": "https://www.ricoh-imaging.co.jp/x", "evidence": "公式ページ"}]
    st = run(tmp_path, doc)
    txt = json.dumps(cf._public_market(st), ensure_ascii=False)
    for bad in ("α9 IV", "1,200,000", "9,999,999", "未発表"):
        assert bad not in txt


def test_failed_sibling_source_with_product_hint_drops_only_that_product():
    recs = [{"brand": "RICOH", "product": "RICOH GR IV HDF", "official": None, "retail": [], "listing": [], "sold": [],
             "buyback": [{"shop": "ネットオフ", "price_jpy": 1, "url": "https://www.netoff.co.jp/a"}]},
            {"brand": "RICOH", "product": "RICOH GR IV", "official": None, "retail": [], "listing": [], "sold": [],
             "buyback": [{"shop": "ネットオフ", "price_jpy": 2, "url": "https://www.netoff.co.jp/b"}]}]
    out, dropped = cf.drop_failed_source_rows(recs, [{"brand": "RICOH", "source": "ネットオフ買取（HDF）", "result": "FAILED"}])
    by = {r["product"]: r["buyback"] for r in out}
    assert by["RICOH GR IV HDF"] == [] and len(by["RICOH GR IV"]) == 1


def test_english_shop_names_and_both_roles_are_dropped():
    recs = [{"brand": "Sony", "product": "SONY α7R V", "official": None, "listing": [], "sold": [],
             "retail": [{"shop": "ヨドバシ", "price_jpy": 1, "url": "https://www.yodobashi.com/x"}],
             "buyback": [{"shop": "ヨドバシ", "price_jpy": 1, "url": "https://www.yodobashi.com/y"}]}]
    out, _ = cf.drop_failed_source_rows(recs, [{"brand": "Sony", "source": "Yodobashi Camera（販売・買取）", "result": "TIMEOUT"}])
    assert out[0]["retail"] == [] and out[0]["buyback"] == []


def test_validate_refuses_stale_research_and_rollback(tmp_path):
    st = run(tmp_path, research(), now=NOW + timedelta(days=30))                # 全部の行が古い
    assert any("7 日以内" in p for p in cf.validate(st))
    st2 = run(tmp_path / "b", research())
    st2["old_market"] = {"research_date": "2026-12-01"}
    assert any("上書きしない" in p for p in cf.validate(st2))


def test_kpi_excludes_carried_rows(tmp_path):
    st1 = run(tmp_path, research())
    old = cf._public_market(st1)
    import shutil
    shutil.rmtree(tmp_path / "2026-11-18")
    d = write_dir(tmp_path, research(buyback=[]))
    st2 = cf.refresh(d, "2026-11-19", now=NOW + timedelta(days=1), old_market=old, cfg=CFG, obs_doc={}, names=NAMES, official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800)
    assert st2["report"]["found"]["buyback"] == 0 and st2["report"]["carried_rows"]


def test_lottery_alias_keyword_is_covered():
    assert cf._lottery_covers("RICOH GR IV", "リコー GR4 抽選販売（現状受付中）")
    assert not cf._lottery_covers("RICOH GR IV", "リコー GR4 HDF")
    assert cf._lottery_covers("RICOH GR IV HDF", "リコー GR4 HDF")


def test_page_link_rejects_confusing_urls():
    from src.content.camera_market_page import _link
    assert "<a " not in _link("https://evil.example\\@kaitorishouten-co.jp/x", "x")
    assert "<a " in _link("https://www.kaitorishouten-co.jp/x", "x")


# ---- 4 回目のレビューの回帰（取り込み側） ----
def test_history_is_public_safe(tmp_path):
    doc = research()
    doc["products"].append({"product": "Canon EOS R6 Mark III", "official": None, "retail": [], "listing": [], "sold": [],
                            "buyback": [{"shop": "買取商店", "item_title": "Canon EOS R6 Mark III", "price_jpy": 310000, "condition": "NEW",
                                         "url": "https://www.kaitorishouten-co.jp/products/detail/9", "is_product_page": True,
                                         "checked_at": "2026-11-18", "source_updated_at": "2026-11-18", "result": "FOUND"}]})
    doc["products"][0]["official"]["shop"] = "リコーイメージングストア（ricohimagingstore.com 製品ページ・自由記述）"
    st = run(tmp_path, doc)
    txt = json.dumps(cf.history_snapshot(st), ensure_ascii=False)
    assert "R6 Mark III" not in txt and "自由記述" not in txt and "ricohimagingstore.com" not in txt


def test_price_change_events_work_across_weeks_with_public_previous(tmp_path):
    st1 = run(tmp_path, research())
    old = cf._public_market(st1)
    import shutil
    shutil.rmtree(tmp_path / "2026-11-18")
    doc = research()
    for r in doc["products"][0]["buyback"]:
        r["price_jpy"] += 10000
    d = write_dir(tmp_path, doc)
    st2 = cf.refresh(d, "2026-11-18", now=NOW, old_market=old, cfg=CFG, obs_doc={}, names=NAMES, official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800)
    assert st2["report"]["buyback_prices_changed"] == 2
    assert {e["type"] for e in st2["events"]} >= {"BUYBACK_SURGE"}
    assert all(e.get("source") in ("", "kaitorishouten-co.jp", "netoff.co.jp") or e.get("source") for e in st2["events"])


def test_public_events_use_labels_and_registered_products_only(tmp_path):
    st = run(tmp_path, research())
    st["events"] = [{"type": "BUYBACK_SURGE", "product": "RICOH GR IV HDF", "source": "kaitorishouten-co.jp"},
                    {"type": "BUYBACK_SURGE", "product": "未登録の機種", "source": "kaitorishouten-co.jp"}]
    ev = cf._public_market(st)["events"]
    assert len(ev) == 1 and ev[0]["source"] == "買取商店"


def test_public_lottery_dates_and_url_are_sanitized(tmp_path):
    doc = research()
    doc["lotteries"] = [{"product": "RICOH GR IV HDF", "retailer": "x", "application_start": "2026-11-20 山田太郎が応募 /Users/x", "application_end": "2026/11/30",
                         "official_url": "https://www.ricoh-imaging.co.jp/x?memo=YamadaTaro#frag", "evidence": "公式ページ"}]
    lot = cf._public_market(run(tmp_path, doc))["lotteries"][0]
    assert lot["application_start"] is None and lot["application_end"] == "2026-11-30" and "?" not in lot["official_url"] and "#" not in lot["official_url"]


def test_price_strings_with_separators_are_accepted_but_ranges_are_not():
    recs = [{"product": "RICOH GR IV HDF", "retail": [], "listing": [], "sold": [],
             "buyback": [{"shop": "x", "price_jpy": "280,000", "url": "https://www.netoff.co.jp/kaden/detail/1", "result": "FOUND"},
                         {"shop": "x", "price_jpy": "約280,000", "url": "https://www.netoff.co.jp/kaden/detail/2", "result": "FOUND"},
                         {"shop": "x", "price_jpy": "200,000〜250,000", "url": "https://www.netoff.co.jp/kaden/detail/3", "result": "FOUND"}]}]
    out = cf.clean_records(recs)
    assert [r["price_jpy"] for r in out[0]["buyback"]] == [280000]


def test_reason_code_does_not_match_numbers_inside_prices():
    assert cf.reason_code("1,403,000円で") != "アクセスを拒否された（403）"
    assert cf.reason_code("HTTP 403 Forbidden") == "アクセスを拒否された（403）"


# ---- 5 回目のレビューの回帰（取り込み側） ----
def test_public_values_are_scrubbed(tmp_path):
    doc = research()
    doc["products"][0]["official"]["purchase_shipping_jpy"] = "無料（社内メモ: 山田さん確認）"
    doc["products"][0]["buyback"][0]["url"] = "https://www.kaitorishouten-co.jp/products/detail/5?memo=GR5試作機#note-秘密"
    st = run(tmp_path, doc)
    txt = json.dumps(cf._public_market(st), ensure_ascii=False) + json.dumps(cf.history_snapshot(st), ensure_ascii=False)
    for bad in ("山田", "試作機", "note-秘密", "社内メモ"):
        assert bad not in txt


def test_public_url_keeps_only_product_pointing_query():
    u = cf._pub_url("https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid=S0001566&cat=002010&memo=abc#x")
    assert u == "https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid=S0001566&cat=002010"


def test_same_url_with_different_price_is_not_confirmed():
    recs = [{"product": "RICOH GR IV", "buyback": [{"shop": "買取商店", "price_jpy": 250000, "url": "https://www.kaitorishouten-co.jp/products/detail/9", "condition": "UNOPENED",
                                                    "is_product_page": False}]}]
    extra = {"RICOH GR IV": [{"shop": "買取商店", "price_jpy": 205000, "url": "https://www.kaitorishouten-co.jp/products/detail/9", "condition": cr.UNOPENED}]}
    out, unused = cf.merge_pipeline(recs, extra, {"RICOH GR IV": "prod_gr4"})
    assert out[0]["buyback"] == [] and unused == 1


def test_official_price_string_is_parsed():
    out = cf.clean_records([{"product": "x", "official": {"price_jpy": "211,800", "shop": "s"}, "retail": [], "buyback": [], "listing": [], "sold": []}])
    assert out[0]["official"]["price_jpy"] == 211800


def test_same_product_in_two_files_does_not_duplicate_carried_rows(tmp_path):
    """同じブランドの同じ機種が 2 ファイル（調査員の分と別の取得元の分）にあっても、前回の行を二重に引き継がない。"""
    st1 = run(tmp_path, research())
    old = st1["market"]
    d = tmp_path / "2026-11-18"
    extra = research(buyback=[{"shop": "買取ルデヤ", "item_title": "RICOH(リコー) GR IV HDF", "price_jpy": 205000, "condition": "NEW",
                               "url": "https://kaitori-rudeya.com/product/item/6509", "is_product_page": True, "checked_at": "2026-11-18",
                               "source_updated_at": "2026-11-18", "result": "FOUND"}])
    extra["products"][0]["official"] = None
    extra["source_results"] = []
    (d / "research_camera_RICOH_rudeya.json").write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
    st2 = cf.refresh(d, "2026-11-18", now=NOW, old_market=old, cfg=CFG, obs_doc={}, names=NAMES, official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800)
    rows = [o for p in st2["market"]["products"] if p["product"] == "RICOH GR IV HDF" for o in p["observations"] if o["kind"] == "buyback"]
    urls = [o.get("url") for o in rows]
    assert len(urls) == len(set(urls)), urls
    assert any("kaitori-rudeya.com" in (u or "") for u in urls)
    assert st2["carried"] == [], st2["carried"]       # 買取商店の行は今回の調査にあるので「取れなかった」ことにして前回の行を引き継がない（統合を戻すとここで落ちる）


def test_withdrawn_rows_are_not_carried_over_but_failed_fetches_are(tmp_path):
    """取得元が意図して不採用にした (機種・種類・店) は前回の行から復活しない。withdrawn が無ければ、これまでどおり引き継ぐ。"""
    st1 = run(tmp_path, research())
    old = st1["market"]
    d = tmp_path / "2026-11-18"
    empty = {"brand": "RICOH", "products": [], "discovered": [], "lotteries": [], "source_results": []}
    (d / "research_camera_RICOH.json").write_text(json.dumps({**research(buyback=[]), "source_results": []}, ensure_ascii=False), encoding="utf-8")

    def shops(withdrawn):
        doc = {**empty, "withdrawn": withdrawn}
        (d / "research_camera_RICOH_x.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        st = cf.refresh(d, "2026-11-18", now=NOW, old_market=old, cfg=CFG, obs_doc={}, names=NAMES, official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800)
        return {o["source"] for p in st["market"]["products"] if p["product"] == "RICOH GR IV HDF" for o in p["observations"] if o["kind"] == "buyback"}

    kept = shops([])
    assert "買取商店" in kept
    gone = shops([{"product": "RICOH GR IV HDF", "shop": "買取商店", "kind": "buyback", "reason": "意図した不採用"}])
    assert "買取商店" not in gone


def test_price_basis_is_public_and_shown_on_the_page(tmp_path):
    """売値が「保証書に店舗印ありの価格」であることを、公開データとページに出す。"""
    doc = research()
    doc["products"][0]["buyback"] = [{"shop": "買取ルデヤ", "item_title": "RICOH(リコー) GR IV HDF", "price_jpy": 205000, "condition": "NEW", "price_basis": "STAMPED_WARRANTY",
                                      "url": "https://kaitori-rudeya.com/product/item/6509", "is_product_page": True, "checked_at": "2026-11-18",
                                      "source_updated_at": "2026-11-18", "result": "FOUND"}]
    st = run(tmp_path, doc)
    pub = cf._public_market(st)
    obs = [o for p in pub["products"] if p["product"] == "RICOH GR IV HDF" for o in p["observations"] if o["kind"] == "buyback"]
    assert obs and obs[0]["basis"] == "STAMPED_WARRANTY"
    from src.content import camera_market_page as pg
    assert "店舗印あり" in pg.BASIS["STAMPED_WARRANTY"] and pg._basis({"basis": "STAMPED_WARRANTY"})
    assert pg._basis({"basis": "x"}) == "" and pg._basis(None) == ""


def test_found_counts_only_fresh_rows_and_history_keeps_the_price_basis(tmp_path):
    """「買取価格を確認」の件数は鮮度を満たす行だけ（今週取り直していない古い行を数えない）。履歴にも売値の基準を残す。"""
    doc = research()
    doc["products"][0]["buyback"] = [
        {"shop": "買取ルデヤ", "item_title": "RICOH(リコー) GR IV HDF", "price_jpy": 205000, "condition": "NEW", "price_basis": "STAMPED_WARRANTY",
         "url": "https://kaitori-rudeya.com/product/item/6509", "is_product_page": True, "checked_at": "2026-11-18", "source_updated_at": "2026-11-18", "result": "FOUND"},
        {"shop": "買取商店", "item_title": "コンパクトデジタルカメラ RICOH GR IV HDF", "price_jpy": 240000, "condition": "UNOPENED",
         "url": "https://www.kaitorishouten-co.jp/products/detail/1", "is_product_page": True, "checked_at": "2026-10-01", "source_updated_at": "2026-10-01", "result": "FOUND"}]
    st = run(tmp_path, doc)
    assert st["report"]["found"]["buyback"] == 1                       # 古い買取商店の行（STALE）は数えない
    snap = cf.history_snapshot(st)
    assert [o["basis"] for o in snap["observations"] if o["source"] == "買取ルデヤ"] == ["STAMPED_WARRANTY"]


def _stamped_doc():
    doc = research()
    doc["products"][0]["buyback"] = [{"shop": "買取ルデヤ", "item_title": "RICOH(リコー) GR IV HDF", "price_jpy": 205000, "condition": "NEW", "price_basis": "STAMPED_WARRANTY",
                                      "url": "https://kaitori-rudeya.com/product/item/6509", "is_product_page": True, "checked_at": "2026-11-18",
                                      "source_updated_at": "2026-11-18", "result": "FOUND"}]
    return doc


def test_page_html_shows_the_price_basis_note(tmp_path):
    """売値が店舗印ありの価格であることが、ページの HTML に出る（カード・表・根拠のどれにも）。"""
    from src.content import camera_market_page as pg
    st = run(tmp_path, _stamped_doc())
    html = pg.render(cf._public_market(st), now=NOW)
    assert html.count("保証書に店舗印ありの価格（完品より減額）") >= 3, html.count("保証書に店舗印ありの価格（完品より減額）")     # カード・表・根拠の 3 か所


def test_carried_rows_keep_the_price_basis(tmp_path):
    """通信の失敗で前回の行を引き継いだときも、売値の基準の開示（basis）を落とさない。"""
    st1 = run(tmp_path, _stamped_doc())
    old = cf._public_market(st1)
    d = tmp_path / "2026-11-18"
    for f in d.glob("research_camera_*.json"):
        f.unlink()
    (d / "research_camera_RICOH.json").write_text(json.dumps({"brand": "RICOH", "products": [], "discovered": [], "lotteries": [], "source_results": []}), encoding="utf-8")
    st2 = cf.refresh(d, "2026-11-19", now=NOW + timedelta(days=1), old_market=old, cfg=CFG, obs_doc={}, names=NAMES, official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800)
    rows = [o for p in st2["market"]["products"] for o in p["observations"] if o["source"] == "買取ルデヤ"]
    assert rows and all(o["carried"] and o["basis"] == "STAMPED_WARRANTY" for o in rows)


def test_uncalculated_table_also_shows_the_price_basis(tmp_path):
    """買う側が無くて計算できない機種の表（確認できた売る側）にも、売値の基準の注記を出す。"""
    from src.content import camera_market_page as pg
    doc = _stamped_doc()
    doc["products"][0]["official"] = None
    st = run(tmp_path, doc)
    html = pg.render(cf._public_market(st), now=NOW)
    cell = html[html.index("計算できなかった機種の表を開く"):]
    assert "買取ルデヤ" in cell and "店舗印ありの価格" in cell.split("</details>")[0]
