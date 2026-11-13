"""週次リサーチの取り込み（src/research/weekly_import.py）と、店舗の公式ドメインの証拠登録のテスト。

守ること: 一次情報で確認できたものだけが公開データに入る・AI の申告は下げる方向にだけ使う・期限切れは入れない・
「無し」の意味（NO_EVENT_FOUND と CONFIRMED_NO_CURRENT_EVENT）・必須ソースの大半が失敗なら成功にしない・既存の行を壊さない。
"""
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.research import weekly_import as W
from src.tcg.lottery import manual as M

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 13, 23, 30, tzinfo=JST)


def _ev(**kw):
    base = {
        "kind": "LOTTERY_OPEN", "product_name": "ハドウシーカー テスト商品 BOX", "tcg": "POKEMON", "retailer": "カードラボ",
        "application_start": "2026-11-10", "application_end": "2026-11-15T23:59",
        "winner_announcement": "2026-11-18", "purchase_start": "2026-11-19", "purchase_end": "2026-11-25",
        "official_url": "https://www.c-labo.jp/shop/x/blog/1/", "source_url": "https://www.c-labo.jp/shop/x/blog/1/",
        "classification": "VERIFIED", "eligibility": "テスト", "retail_price": 7200,
    }
    base.update(kw)
    return base


# ---- 一次情報の証拠 ----
def test_store_primary_domains_all_have_evidence():
    for domain, ev in M.STORE_PRIMARY_DOMAINS.items():
        for k in ("operator", "evidence", "evidence_url", "checked_on"):
            assert ev.get(k), f"{domain}: {k} が無い（運営者の証拠なしに店舗の公式ドメインにしない）"
        assert domain in ev["evidence_url"]


def test_unconfirmed_operators_are_not_primary():
    # 運営者を確認できなかったドメイン（2026-11-13 の確認）は公式扱いにしない
    for url in ("https://edion-cp.com/poke112701", "https://www.mugiwara-store.com/news/3061/",
                "https://select-type.com/e/?id=x", "https://nyuka-now.com/archives/2459"):
        assert W.primary_evidence(url) is None


def test_primary_event_is_verified_and_row_is_not_human_confirmed():
    c = W.classify_event(_ev(), NOW)
    assert c["decision"] == "VERIFIED" and c["evidence_kind"] == "store_primary_domain"
    row = W.csv_row_for(_ev(), c, now=NOW)
    assert row["human_confirmed"] == "false"          # AI は人の確認を名乗らない
    assert "人の確認は未了" in row["verified_by"] and row["source_url"].startswith("https://www.c-labo.jp/")


def test_aggregator_source_is_not_verified_even_with_official_looking_url():
    # 集約サイトで見つけて公式のトップ・一覧の URL を添えただけ（調査自身も UNVERIFIED と申告）
    ev = _ev(source_url="https://nyuka-now.com/archives/2459", official_url="https://www.c-labo.jp/blog/", classification="UNVERIFIED")
    c = W.classify_event(ev, NOW)
    assert c["decision"] == "UNVERIFIED" and "no_primary_evidence" in c["reasons"]


def test_ai_claim_is_only_used_to_downgrade():
    ev = _ev(classification="UNVERIFIED")           # 根拠のドメインは一次情報でも、調査が UNVERIFIED としたら入れない
    assert W.classify_event(ev, NOW)["decision"] == "UNVERIFIED"
    ev2 = _ev(source_url="https://nyuka-now.com/x", official_url="https://www.c-labo.jp/shop/x/blog/1/", classification="VERIFIED")
    assert W.classify_event(ev2, NOW)["decision"] == "UNVERIFIED"   # source_url があり一次情報でないなら、official_url で救わない


def test_official_url_alone_never_verifies():
    # official_url（公式のトップ・一覧を添えただけのことが多い）や AI の VERIFIED の申告で救済しない（下げる方向にだけ使う）
    ev = _ev(source_url=None, official_url="https://www.pokemon-card.com/info/x", classification="VERIFIED")
    assert W.classify_event(ev, NOW)["decision"] == "UNVERIFIED"


def test_ended_event_is_not_imported():
    ev = _ev(application_end="2026-11-05T23:59", purchase_end="2026-11-10")
    assert W.classify_event(ev, NOW)["decision"] == "ENDED"
    ev2 = _ev(application_end="2026-11-05T23:59", purchase_end="2026-11-25")   # 応募は終了でも購入期間が未来なら現在のイベント
    assert W.classify_event(ev2, NOW)["decision"] == "VERIFIED"


def test_missing_dates_or_unknown_retailer_is_incomplete():
    assert "missing_application_dates" in W.classify_event(_ev(application_end=None), NOW)["reasons"]
    assert "retailer_unmapped" in W.classify_event(_ev(retailer="どこかの店"), NOW)["reasons"]


def test_date_only_deadline_is_assumed_end_of_day_and_flagged():
    c = W.classify_event(_ev(application_end="2026-11-15"), NOW)
    assert c["application_end"] == "2026-11-15T23:59:00+09:00" and "application_end" in c["time_assumed"]
    row = W.csv_row_for(_ev(application_end="2026-11-15"), c, now=NOW)
    assert "23:59 とみなした" in row["notes"]


# ---- CSV への追記 ----
HEADER = ",".join(M.CSV_COLUMNS)


def _csv_with(tmp_path, body=""):
    p = tmp_path / "t.csv"
    p.write_bytes((HEADER + "\r\n" + body).encode("utf-8"))
    return p


def test_import_appends_without_touching_existing_rows_and_is_idempotent(tmp_path):
    p = _csv_with(tmp_path, "POKEMON,既存の行,POKEMON_CENTER_ONLINE,PCO,LOTTERY,false,,,,2026-10-02T12:00:00+09:00,2026-10-05T16:59:00+09:00,,,,,,x,false,,,,,,,https://www.pokemoncenter-online.com/news/?id=1,2026-10-01T00:00:00+09:00,test,n\r\n")
    before = p.read_bytes()
    research = {"events": [_ev()]}
    r1 = W.import_tcg(research, now=NOW, csv_path=p, apply=True)
    assert len(r1["verified"]) == 1 and r1["applied"]
    after = p.read_bytes()
    assert after.startswith(before)                   # 既存の行は 1 バイトも変えない
    r2 = W.import_tcg(research, now=NOW, csv_path=p, apply=True)
    assert r2["duplicates_skipped"] == 1 and not r2["applied"] and p.read_bytes() == after
    ev, errs = M.load_manual_lotteries(p)
    assert not errs and len(ev) == 2
    new = [e for e in ev if e["retailer"] == "CARD_LABO"][0]
    assert new["verified"] is False and new["confidence"] == "medium" and new["source_type"] == M.SRC_MANUAL


def test_dry_run_writes_nothing(tmp_path):
    p = _csv_with(tmp_path)
    before = p.read_bytes()
    r = W.import_tcg({"events": [_ev()]}, now=NOW, csv_path=p, apply=False)
    assert len(r["verified"]) == 1 and not r["applied"] and p.read_bytes() == before


def test_unverified_goes_to_candidates_not_csv(tmp_path):
    p = _csv_with(tmp_path)
    ev = _ev(source_url="https://nyuka-now.com/x", official_url="https://nyuka-now.com/x", classification="UNVERIFIED")
    r = W.import_tcg({"events": [ev]}, now=NOW, csv_path=p, apply=True)
    assert r["verified"] == [] and len(r["candidates"]) == 1 and r["candidates"][0]["final_class"] == "UNVERIFIED"
    assert p.read_text(encoding="utf-8").strip() == HEADER


# ---- TCG の 5 区分（VERIFIED / UNVERIFIED / DUPLICATE_EXISTING / STALE / FAILED_VERIFICATION） ----
def _ver(ev, *, verdict="PRIMARY_VERIFIED", status="OK", url="https://www.sanyodo.co.jp/news/x", operator="株式会社三洋堂書店", **facts):
    pf = {"product": "ハドウシーカー テスト拡張パック BOX", "application_start": "2026-11-04", "application_end": "2026-11-15",
          "winner_announcement": "2026-11-25", "purchase_start": "2026-11-27", "purchase_end": "2026-11-29",
          "price": "1BOX 6,000円(税込)", "eligibility": "会員限定"}
    pf.update(facts)
    return {"_retailer": ev["retailer"], "_product": ev["product_name"], "primary_page_url": url, "page_fetch_status": status,
            "page_facts": pf, "operator_evidence": {"url": "https://www.sanyodo.co.jp/", "operator_name": operator}, "verdict": verdict}


def _agg(**kw):
    base = {"retailer": "三洋堂書店", "source_url": "https://nyuka-now.com/x", "official_url": "https://select-type.com/e/?id=x", "classification": "VERIFIED"}
    base.update(kw)
    return _ev(**base)


def _fin(events, vers=(), covered=(), collectors=()):
    return W.finalize_tcg({"events": events}, list(vers), now=NOW, covered=set(covered), collectors=set(collectors))


def test_final_classes_cover_all_five():
    agg = _agg(product_name="ハドウシーカー 集約だけの商品")
    ok_ev = _agg(product_name="ハドウシーカー 検証できる商品")
    failed_ev = _agg(product_name="ハドウシーカー 検証できない商品", retailer="どこかの店")
    ended = _ev(product_name="ハドウシーカー 終了した商品", application_end="2026-11-05T23:59", purchase_end="2026-11-10",
                source_url="https://www.c-labo.jp/shop/ended/blog/9/", official_url="https://www.c-labo.jp/shop/ended/blog/9/")
    dup = _ev(product_name="ハドウシーカー 既存の商品")
    res = _fin([agg, ok_ev, failed_ev, ended, dup],
               [_ver(ok_ev), _ver(failed_ev, verdict="UNVERIFIED", status="NOT_FOUND", url=None)],
               covered={W._norm_url(dup["source_url"])})
    cls = {r["event"]["product_name"]: r["final_class"] for r in res}
    assert cls[agg["product_name"]] == "UNVERIFIED"
    assert cls["ハドウシーカー 検証できる商品"] == "VERIFIED" and cls["ハドウシーカー 検証できない商品"] == "FAILED_VERIFICATION"
    assert cls["ハドウシーカー 既存の商品"] == "DUPLICATE_EXISTING" and cls[ended["product_name"]] == "STALE"


def test_aggregator_only_stays_unverified():
    res = _fin([_agg()])
    assert res[0]["final_class"] == "UNVERIFIED" and "no_primary_evidence" in res[0]["reasons"]


def test_verification_uses_page_facts_not_ai_dates():
    ev = _agg(application_end="2026-12-31")                 # AI の日付（誤り）
    res = _fin([ev], [_ver(ev, application_end="2026-11-15")])
    eff = res[0]["effective"]
    assert res[0]["final_class"] == "VERIFIED" and eff["application_end"] == "2026-11-15" and eff["retail_price"] == 6000
    assert eff["source_url"].startswith("https://www.sanyodo.co.jp/") and res[0]["classification"]["application_end"].startswith("2026-11-15")


def test_verification_on_unregistered_domain_fails():
    ev = _agg()
    res = _fin([ev], [_ver(ev, url="https://unknown-shop.example/news/1")])       # 運営者の証拠つきのドメインに無い
    assert res[0]["final_class"] == "FAILED_VERIFICATION"
    res2 = _fin([ev], [_ver(ev, operator="")])                                    # 運営者の記載なし
    assert res2[0]["final_class"] == "FAILED_VERIFICATION"


def test_existing_collector_source_is_duplicate_not_new_csv():
    ev = _ev()                                              # カードラボ（既存の収集の取得元）。URL は未掲載でも収集が拾う
    res = _fin([ev], collectors={"CARD_LABO"})
    assert res[0]["final_class"] == "DUPLICATE_EXISTING" and res[0]["reasons"] == ["collector_covers_source"]


def test_import_counts_five_classes_and_writes_only_verified(tmp_path):
    p = _csv_with(tmp_path)
    ok_ev = _agg(product_name="ハドウシーカー 検証できる商品")
    bad = _agg(product_name="ハドウシーカー 集約だけの商品")
    r = W.import_tcg({"events": [ok_ev, bad]}, now=NOW, csv_path=p, apply=True, verifications=[_ver(ok_ev)])
    assert r["counts"]["VERIFIED"] == 1 and r["counts"]["UNVERIFIED"] == 1 and sum(r["counts"].values()) == 2
    ev, errs = M.load_manual_lotteries(p)
    assert not errs and len(ev) == 1 and ev[0]["retailer"] == "SANYODO" and ev[0]["verified"] is False       # 人の確認は未了


def test_committed_csv_has_only_primary_evidence_rows():
    # 「確認済み抽選」の CSV には、一次情報（公式ドメイン・運営者の証拠つきの店舗ドメイン）の行だけがある（集約サイト 0）
    ev, errs = M.load_manual_lotteries()
    assert not errs
    for e in ev:
        assert M.is_official_url(e["source_url"]) or M.is_store_primary_url(e["source_url"]), e["source_url"]
        assert e["verified"] is False or e["source_type"] == M.SRC_MANUAL_OFFICIAL


# ---- ソースごとの結果の意味・網羅度 ----
def test_top_page_only_is_no_event_found_not_confirmed():
    assert W.normalize_source_result({"result": "NO_CURRENT_EVENT", "reason": "トップのみ"}) == W.NO_EVENT_FOUND
    assert W.normalize_source_result({"result": "CHECKED"}) == W.NO_EVENT_FOUND


def test_confirmed_requires_list_page_and_search():
    ok = {"result": "NO_CURRENT_EVENT", "evidence": {"event_list_pages": ["https://x/news/"], "searches": 2}}
    assert W.normalize_source_result(ok) == W.CONFIRMED_NO_CURRENT_EVENT
    assert W.normalize_source_result({"result": "NO_CURRENT_EVENT", "evidence": {"event_list_pages": ["https://x/"], "searches": 0}}) == W.NO_EVENT_FOUND
    assert W.normalize_source_result({"result": "NO_EVENT_FOUND", "evidence": {"event_list_pages": ["x"], "searches": 3}}) == W.NO_EVENT_FOUND
    assert W.normalize_source_result({"result": "BLOCKED"}) == W.BLOCKED and W.normalize_source_result({"result": "FAILED"}) == W.FAILED


def test_coverage_is_incomplete_when_most_required_sources_failed():
    results = [{"source": name, "result": "FAILED"} for _k, _l, words in W.TCG_REQUIRED_SOURCES for name in words[:1]]
    results[0]["result"] = "FOUND"
    cov = W.coverage(results)
    assert cov["verdict"] == "RESEARCH_INCOMPLETE" and cov["coverage_pct"] < 20
    assert cov["required_sources"] == len(W.TCG_REQUIRED_SOURCES)


def test_missing_sources_count_as_not_researched_and_empty_is_incomplete():
    cov = W.coverage([])
    assert cov["counts"][W.NOT_RESEARCHED] == len(W.TCG_REQUIRED_SOURCES) and cov["verdict"] == "RESEARCH_INCOMPLETE"


def test_coverage_success_needs_80_percent_researched():
    results = [{"source": words[0], "result": "NO_CURRENT_EVENT"} for _k, _l, words in W.TCG_REQUIRED_SOURCES]
    assert W.coverage(results)["verdict"] == "RESEARCH_SUCCESS"      # 全部 NO_EVENT_FOUND でも「調べた」が 100%
    assert W.coverage(results)["confirmed_scope_pct"] == 0.0         # ただし「確認済みの無し」は 0%（混ぜない）
    bad = [dict(r, result="FAILED") for r in results[:4]] + results[4:]
    assert W.coverage(bad)["verdict"] == "RESEARCH_INCOMPLETE"       # 13/17 = 76% < 80%


def test_event_already_on_the_site_is_not_added_again(tmp_path):
    # 既存の自動収集が同じ URL を載せているなら、手動の CSV に重ねない（店舗名・商品名の表記の違いで重複表示されるため）
    p = _csv_with(tmp_path)
    cov = W.covered_urls({"items": [{"source_url": "https://www.c-labo.jp/shop/x/blog/1", "source_urls": []}]})
    r = W.import_tcg({"events": [_ev()]}, now=NOW, csv_path=p, apply=True, covered=cov)
    assert r["verified"] == [] and len(r["already_covered"]) == 1 and not r["applied"]
    assert p.read_text(encoding="utf-8").strip() == HEADER


# ---- iPhone の買取比較 ----
import copy

RD = "2026-11-13"
APPLE = {"iPhone Duo": {"256GB": 364800, "1TB": 469800}}
FRESH_TXT = "2026-11-13 (取得日)。ページ記載: 更新日 2026-11-13"


def _cfg(**over):
    c = copy.deepcopy(W.DEFAULT_CONFIG)
    for k, v in over.items():
        c[k].update(v) if isinstance(v, dict) else c.__setitem__(k, v)
    return c


def _shop(name, price, *, checked=FRESH_TXT, cond="UNOPENED", status="ACTIVE", cap="1TB", colors=None, **extra):
    row = {"model": "iPhone Duo", "storage": cap, "condition": cond, "base_price": price, "color_adjustments": colors if colors is not None else {}}
    row.update(extra)
    return {"shop_name": name, "official_url": "https://example.com/", "price_page_url": "https://example.com/p", "checked_at": checked,
            "fetch_status": status, "skus": [row]}


def _comp(shops, cfg=None):
    return W.build_iphone_comparison(shops, APPLE, research_date=RD, now=NOW, cfg=cfg or _cfg())


def _sku(comp, name="iPhone Duo 1TB"):
    return next(s for s in comp["skus"] if s["sku"] == name)


def test_page_updated_on_ignores_the_fetch_date():
    assert W.page_updated_on("2026-11-13 (JST・時刻未記録)。ページ記載の価格表更新日: 2026/11/11") == "2026-11-11"
    assert W.page_updated_on("2026-11-13 23:22 (ページ表示の時点)") == "2026-11-13"
    assert W.page_updated_on("2026-11-13 (取得日。ページに更新日時の記載なし)") is None
    assert W.page_updated_on("") is None


def test_freshness_has_three_states_and_is_configurable_per_source():
    cfg = _cfg()
    assert W.freshness_of("x", "2026-11-13", RD, cfg)[0] == W.FRESH
    assert W.freshness_of("x", "2026-11-11", RD, cfg)[0] == W.STALE
    assert W.freshness_of("x", None, RD, cfg)[0] == W.UNKNOWN_FRESHNESS
    cfg2 = _cfg(freshness={"sources": {"akimoba": {"fresh_days": 2, "note": "休業日あり"}}})
    assert W.freshness_of("akimoba", "2026-11-11", RD, cfg2)[0] == W.FRESH        # 店ごとに長くできる（休業日を誤価格にしない）
    assert W.freshness_of("other", "2026-11-11", RD, cfg2)[0] == W.STALE


def test_stale_price_is_displayed_as_listed_but_not_used_as_executable():
    old = "2026-11-13 (取得)。ページ記載の更新日: 2026/11/11"
    s = _sku(_comp([_shop("新しい店A", 480000), _shop("新しい店B", 481000), _shop("古い店", 502000, checked=old)]))
    assert s["highest_listed"]["shop"] == "古い店" and s["highest_listed"]["price"] == 502000      # 掲載の最高値は捨てない
    assert s["highest_listed"]["freshness"] == W.STALE and s["highest_listed"]["executable"] is False
    assert s["highest_executable"]["shop"] == "新しい店B"
    assert s["net_profit"] == 481000 - 469800 - 1800
    assert s["source_count"] == 3 and s["fresh_source_count"] == 2


def test_unknown_freshness_is_a_candidate_only_when_configured():
    shops = [_shop("日付なしA", 480000, checked="2026-11-13 (取得日。更新日時の記載なし)"), _shop("日付なしB", 481000, checked="2026-11-13 (取得日。更新日時の記載なし)")]
    assert _sku(_comp(shops))["highest_executable"]["shop"] == "日付なしB"
    s2 = _sku(_comp(shops, _cfg(freshness={"unknown_freshness_executable": False})))
    assert s2["highest_executable"] is None and s2["highest_listed"]["price"] == 481000


def test_outlier_keeps_the_highest_price_but_does_not_use_it_for_profit():
    # 例: A 420000 / B 400000 / C 398000（A が他店より大きく高い）
    comp = _comp([_shop("店A", 420000 + 49800), _shop("店B", 400000 + 49800), _shop("店C", 398000 + 49800)])
    s = _sku(comp)
    assert s["outlier_status"] == "OUTLIER_REVIEW"
    assert s["highest_listed"]["price"] == 469800                                  # 値は捨てない（420,000 + 49,800）
    assert s["highest_listed"]["shop"] == "店A"
    assert s["highest_executable"] is None and s["net_profit"] is None and s["roi_pct"] is None and s["best_route"] is None
    assert s["highest_unconfirmed"]["shop"] == "店A" and s["highest_unconfirmed"]["status"] == "OUTLIER_REVIEW"
    assert s["second"]["shop"] == "店B"                                # 比較用の 2 位は出すが、最高の実行可能価格とは呼ばない
    assert s["reference_net_at_second"]["shop"] == "店B" and "最高の実行可能価格ではない" in s["reference_net_at_second"]["note"]
    assert any(r["shop"] == "店A" and r["listed_price"] == 469800 for r in s["rows"])         # 保存もされている


def test_outlier_example_prices_exactly():
    # SKU の Apple 定価に関係なく、掲載の最高値 420,000 を削除しない
    apple = {"iPhone Duo": {"1TB": 380000}}
    shops = [_shop("A", 420000), _shop("B", 400000), _shop("C", 398000)]
    s = _sku(W.build_iphone_comparison(shops, apple, research_date=RD, now=NOW, cfg=_cfg()))
    assert s["highest_listed"]["price"] == 420000 and s["outlier_status"] == "OUTLIER_REVIEW"
    assert s["highest_executable"] is None and s["net_profit"] is None and s["second"]["price"] == 400000 and s["third"]["price"] == 398000


def test_reviewed_outlier_becomes_executable():
    apple = {"iPhone Duo": {"1TB": 380000}}
    shops = [_shop("A", 420000), _shop("B", 400000), _shop("C", 398000)]
    key = W.shop_key("A")
    cfg = _cfg(outlier={"reviewed": [{"sku": "iPhone Duo 1TB", "shop_key": key, "price": 420000, "reviewed_on": RD}]})
    s = _sku(W.build_iphone_comparison(shops, apple, research_date=RD, now=NOW, cfg=cfg))
    assert s["outlier_status"] == "REVIEWED" and s["highest_executable"]["price"] == 420000 and s["net_profit"] == 420000 - 380000 - 1800
    # 別の日・別の価格の確認は使わない
    cfg2 = _cfg(outlier={"reviewed": [{"sku": "iPhone Duo 1TB", "shop_key": key, "price": 419000, "reviewed_on": RD}]})
    assert _sku(W.build_iphone_comparison(shops, apple, research_date=RD, now=NOW, cfg=cfg2))["outlier_status"] == "OUTLIER_REVIEW"


def test_single_source_is_not_used_for_profit():
    s = _sku(_comp([_shop("店A", 500000)]))
    assert s["outlier_status"] == "SINGLE_SOURCE" and s["highest_executable"] is None and s["net_profit"] is None
    assert s["highest_listed"]["price"] == 500000


def test_color_adjustment_unknown_is_listed_but_not_executable():
    comp = _comp([_shop("店A", 480000), _shop("店B", 481000),
                  _shop("色不明", 495000, executable_price={"no_reduction": 495000, "max_reduction_color": "UNKNOWN"}, color_adjustments="UNKNOWN")])
    s = _sku(comp)
    row = next(r for r in s["rows"] if r["shop"] == "色不明")
    assert row["basis"] == "colors_unverified" and row["executable_price"] is None and not row["eligible"] and row["listed_price"] == 495000
    assert s["highest_listed"]["shop"] == "色不明" and s["highest_executable"]["shop"] == "店B"


def test_worst_color_price_is_the_executable_one():
    comp = _comp([_shop("店A", 480000, executable_price_no_reduction=480000, executable_price_max_deduction=470000, colors={"シルバー": -10000}),
                  _shop("店B", 475000)])
    s = _sku(comp)
    a = next(r for r in s["rows"] if r["shop"] == "店A")
    assert a["executable_price"] == 470000 and a["best_price"] == 480000 and a["basis"] == "worst_color"
    assert s["highest_executable"]["shop"] == "店B" and s["highest_listed"]["shop"] == "店A"


def test_conditions_are_never_mixed():
    comp = _comp([_shop("開封店", 520000, cond="OPENED_NEW"), _shop("中古店", 530000, cond="USED"), _shop("店A", 480000), _shop("店B", 481000)])
    s = _sku(comp)
    assert s["highest_listed"]["shop"] == "店B" and s["highest_executable"]["shop"] == "店B"      # 新品未開封だけを比べる
    assert all(r["listed_price"] is None and not r["eligible"] for r in s["rows"] if r["condition"] != "UNOPENED")
    assert s["source_count"] == 2


def test_range_only_and_indicative_prices_are_not_prices():
    rng = _shop("範囲店", None, range_new=[500000, 585000])
    ind = _shop("目安店", 495000)
    ind["conditions_page"] = "相場の最大価格。実際は増減"
    s = _sku(_comp([_shop("店A", 480000), _shop("店B", 481000), rng, ind]))
    assert s["highest_listed"]["shop"] == "店B" and s["highest_executable"]["shop"] == "店B"
    assert {r["basis"] for r in s["rows"] if r["shop"] in ("範囲店", "目安店")} <= {"range_only", "indicative"}


def test_failed_blocked_shops_are_listed_and_counted_not_priced():
    shops = [_shop("店A", 480000), {"shop_name": "失敗店", "fetch_status": "FAILED", "checked_at": "2026-11-13", "reason": "公式サイト不明"},
             {"shop_name": "拒否店", "fetch_status": "BLOCKED 403", "checked_at": "2026-11-13"}]
    comp = _comp(shops)
    assert comp["counts"]["FAILED"] == 1 and comp["counts"]["BLOCKED"] == 1 and comp["counts"]["ACTIVE"] == 1
    assert {s["shop"] for s in comp["shops"]} == {"店A", "失敗店", "拒否店"}


def test_registered_vs_discovered_identity():
    comp = _comp([_shop("店A", 365000, cap="256GB"), _shop("店B", 366000, cap="256GB")])
    assert _sku(comp, "iPhone Duo 256GB")["identity"] == "REGISTERED" and _sku(comp)["identity"] == "DISCOVERED"


def test_costs_use_the_shared_profit_formula():
    from src.market import profit_formula
    s = _sku(_comp([_shop("店A", 480000), _shop("店B", 481000)]))
    assert s["costs"] == profit_formula.fixed_costs() + 0          # Apple の購入送料は無料（確認済みの記録）


def test_history_events_best_shop_change_and_surge_and_loss_to_profit():
    prev = [{"sku": "S", "key": "a", "shop": "A", "price": 390000, "net": -100}, {"sku": "S", "key": "b", "shop": "B", "price": 398000, "net": None}]
    cur = [{"sku": "S", "key": "a", "shop": "A", "price": 400000, "net": 500}, {"sku": "S", "key": "b", "shop": "B", "price": 385000, "net": None}]
    types = {e["type"] for e in W.diff_snapshots(prev, cur)}
    assert "BEST_SHOP_CHANGE" in types and "BUYBACK_SURGE" in types
    prev2 = [{"sku": "S", "key": "a", "shop": "A", "price": 390000, "net": -100}]
    cur2 = [{"sku": "S", "key": "a", "shop": "A", "price": 391000, "net": 900}]
    assert {e["type"] for e in W.diff_snapshots(prev2, cur2)} == {"LOSS_TO_PROFIT"}
    assert {e["type"] for e in W.diff_snapshots([{"sku": "S", "key": "a", "shop": "A", "price": 390000, "net": None}],
                                                [{"sku": "S", "key": "a", "shop": "A", "price": 395000, "net": None}])} == {"BUYBACK_SURGE"}


def test_history_is_idempotent_for_the_same_day_and_first_run_has_no_events(tmp_path):
    comp = _comp([_shop("店A", 480000), _shop("店B", 481000)])
    h = tmp_path / "h.json"
    hist = W.update_history(comp, h)
    assert comp["events"] == [] and len(hist["snapshots"]) == 1
    h.write_text(json.dumps(hist), encoding="utf-8")
    hist2 = W.update_history(_comp([_shop("店A", 480000), _shop("店B", 481000)]), h)
    assert len(hist2["snapshots"]) == 1                 # 同じ日の再実行で二重にしない


def test_config_file_loads_and_broken_config_falls_back(tmp_path):
    cfg = W.load_config()
    assert cfg["outlier"]["rate"] == 0.03 and cfg["freshness"]["default"]["fresh_days"] == 1
    bad = tmp_path / "bad.yaml"
    bad.write_text("outlier: [broken", encoding="utf-8")
    assert W.load_config(bad)["outlier"]["rate"] == 0.03
    assert W.load_config(tmp_path / "none.yaml")["freshness"]["default"]["fresh_days"] == 1


def test_page_shows_the_separated_prices_and_escapes_html():
    from src.content import iphone_buyback_page as P
    evil = _shop("<script>alert(1)</script>店", 420000)
    evil["price_page_url"] = "javascript:alert(1)"
    html = P.render(_comp([evil, _shop("店B", 400000), _shop("店C", 398000)]))
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html and 'href="javascript:' not in html
    for label in ("掲載の最高値", "最高の実行可能買取", "実行可能 2位", "実行可能 3位", "買取店の数", "外れ値の判定", "OUTLIER_REVIEW"):
        assert label in html
    assert "参考・正本に未登録" in html and ">BUY<" not in html and "ACTIONABLE" not in html
    assert "最高の実行可能価格ではありません" in html


# ---- コミット済みの比較データの不変条件（データ品質の関門） ----
def _committed():
    p = Path(__file__).resolve().parents[1] / "exports" / "iphone_buyback" / "iphone_buyback_comparison.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def test_committed_comparison_invariants():
    comp = _committed()
    if comp is None:
        pytest.skip("週次の比較データがまだ無い")
    for s in comp["skus"]:
        for r in s["rows"]:
            if r["eligible"]:                              # 利益計算の候補は、新品未開封・取得できた店・STALE でない・色減額が分かる行だけ
                assert r["condition"] == "UNOPENED" and r["shop_status"] == "ACTIVE" and r["freshness"] != "STALE"
                assert r["basis"] in ("uniform", "worst_color") and isinstance(r["executable_price"], int)
            if r["condition"] != "UNOPENED":
                assert r["listed_price"] is None and not r["eligible"]       # 状態を混ぜない
            if r["listed_price"] and r["executable_price"]:
                assert r["listed_price"] >= r["executable_price"]
        hx = s["highest_executable"]
        if hx:                                             # 最高の実行可能価格は、外れ値でない（または確認済み）ときだけ
            assert s["outlier_status"] in ("NONE", "REVIEWED") and s["highest_unconfirmed"] is None
            assert hx["price"] == max(r["executable_price"] for r in s["rows"] if r["eligible"])
        if s["outlier_status"] in ("OUTLIER_REVIEW", "SINGLE_SOURCE", "NO_DATA"):
            assert s["net_profit"] is None and s["roi_pct"] is None and s["best_route"] is None
        if s["net_profit"] is not None:
            assert s["highest_executable"] and s["net_profit"] == s["highest_executable"]["price"] - s["apple_price"] - s["costs"]
        if s["identity"] != "REGISTERED":
            assert "参考" in s["identity_note"]
        names = [r["shop"] for r in s["rows"] if r["condition"] == "UNOPENED"]
        assert len(names) == len(set(names))               # 同じ店・同じ SKU を二重に入れない（誤った統合なし）
    assert comp["generated_at"][:10] >= comp["research_date"]         # 調査日より前の生成日時ではない（鮮度の偽装なし）


# ---- カメラ ----
NOW_CAM = datetime(2026, 11, 13, 23, 40, tzinfo=JST)


def _camera_research():
    return {
        "items": [{"kind": "LOTTERY_OPEN", "product_name": "RICOH GR IV", "retailer": "GR SPACE TOKYO", "application_start": "2026-10-21",
                   "application_end": "2026-11-22（時刻は記載なし）", "winner_announcement": "2026-12-05",
                   "official_url": "https://www.ricoh-imaging.co.jp/japan/community/grspace_tokyo/camerasales/"}],
        "price_routes": [
            {"kind": "PRICE_ROUTE", "route": "A", "product": "RICOH GR IV",
             "buy": {"where": "GR SPACE TOKYO 抽選（当選すれば）", "price": 190620, "stock": "抽選のため確定せず"},
             "sell": [{"where": "買取（店名非公開・査定サイト・新品未開封・2026-09-16）", "price": 205000},
                      {"where": "カメラ専門店買取（新品・既存パイプライン 2026-11-12 20:18）", "price": 151000},
                      {"where": "買取（同サイト・美品・2026-10-01）", "price": 240000},
                      {"where": "ゲオ買取（日付なし）", "price": 160000}],
             "net_profit_inference": [{"sell": 205000, "net_before_purchase_shipping": 12580, "roi_pct": 6.6}]},
            {"kind": "PRICE_ROUTE", "route": "A-secondary", "product": "RICOH GR IV",
             "sold_new": {"low": 223000, "high": 235000, "median": None, "n": 17, "period": "UNKNOWN"}, "listing_new": {"low": 230000, "high": None, "n": 6}},
            {"kind": "PRICE_ROUTE", "route": "A", "product": "FUJIFILM X100VI", "buy": {"where": "フジフイルムモール", "price": 315700, "stock": "SOLD OUT（購入不可）"}, "sell": []},
        ],
    }


def test_camera_lottery_dependent_is_never_an_immediate_buy():
    summary = W.build_camera_summary(_camera_research(), research_date=RD, now=NOW_CAM)
    gr = next(p for p in summary["products"] if p["product"] == "RICOH GR IV")
    assert gr["status"] == "LOTTERY_DEPENDENT" and gr["immediate_buy"] is False
    x100 = next(p for p in summary["products"] if "X100VI" in p["product"])
    assert x100["status"] == "OUT_OF_STOCK" and x100["immediate_buy"] is False
    assert "INFERENCE" in gr["reference_label"]                       # 純利益は参考の推定。確定のルートではない


def test_camera_sell_candidates_require_named_fresh_new_condition():
    gr = next(p for p in W.build_camera_summary(_camera_research(), research_date=RD, now=NOW_CAM)["products"] if p["product"] == "RICOH GR IV")
    by = {c["where"][:6]: c for c in gr["sell_candidates"]}
    assert by["買取（店名非"]["executable_candidate"] is False and "店名が分からない" in by["買取（店名非"]["reasons"] and "価格が古い" in by["買取（店名非"]["reasons"]
    assert by["買取（同サイ"]["executable_candidate"] is False and "新品の条件を確認できない（状態が違う可能性）" in by["買取（同サイ"]["reasons"]
    assert by["ゲオ買取（日"]["executable_candidate"] is False and "価格の新しさを確認できない" in by["ゲオ買取（日"]["reasons"]   # 日付が分からない価格は「新しい」と言わない
    assert by["カメラ専門店"]["executable_candidate"] is True


def test_camera_dated_named_new_condition_price_is_a_candidate():
    c = W._sell_candidate({"where": "カメラ専門店買取（新品・2026-11-12）", "price": 151000}, RD)
    assert c["executable_candidate"] is True and c["reasons"] == [] and c["age_days"] == 1
    for where in ("フジヤカメラ買取（新品同様・2026-11-12）", "フジヤカメラ買取（既存パイプライン 2026-11-12）"):       # 新品と確認できない（新品同様は中古の最上位）
        assert W._sell_candidate({"where": where, "price": 151000}, RD)["executable_candidate"] is False


def test_camera_secondary_never_makes_an_expected_sell_price():
    summary = W.build_camera_summary(_camera_research(), research_date=RD, now=NOW_CAM)
    assert len(summary["secondary_market"]) == 1
    sec = summary["secondary_market"][0]
    assert sec["expected_sell_price"] is None and sec["sold"]["median"] is None
    assert sec["listing"]["low"] == 230000 and sec["sold"]["low"] == 223000 and sec["sold"]["high"] == 235000      # 出品と成約を混ぜない


def test_camera_lottery_state_is_computed_when_the_page_is_built_not_stored():
    from src.content import camera_research_page as P
    summary = W.build_camera_summary(_camera_research(), research_date=RD, now=NOW_CAM)
    lot = summary["lotteries"][0]
    assert "live_status" not in lot and lot["evidence"] == "メーカーまたは店舗の公式ページ"      # 状態を JSON に焼き込まない
    assert "受付中・予定" in P.render(summary, now=NOW_CAM)
    late = datetime(2026, 11, 23, 0, 5, tzinfo=JST)                    # 期限（11/22 23:59）の後にビルドしたページは「終了」
    html = P.render(summary, now=late)
    assert "終了" in html and "受付中・予定" not in html
    summary["lotteries"][0]["application_end"] = None                   # 期限不明は受付中にしない
    assert "応募期限を確認できません" in P.render(summary, now=NOW_CAM)


def test_primary_evidence_is_by_hostname_not_substring():
    assert W.primary_evidence("https://www.ricoh-imaging.co.jp/japan/x") == "official_domain"
    for u in ("https://evil.example/?ricoh-imaging.co.jp", "https://ricoh-imaging.co.jp.evil.com/x", "https://nyuka-now.com/?u=c-labo.jp"):
        assert W.primary_evidence(u) is None, u


def test_camera_unverified_things_are_not_public_only_counted():
    r = _camera_research()
    r["items"].append({"kind": "LOTTERY_UPCOMING", "product_name": "フジヤ抽選", "retailer": "フジヤカメラ", "application_end": "2026-11-01", "official_url": "https://www.fujiya-camera.co.jp/x"})
    r["items"].append({"kind": "NEW_PRODUCT", "product_name": "Sony α7 V", "classification": "UNVERIFIED"})
    r["price_routes"][0]["sell"].append({"where": "マップカメラ（検索結果の要約のみ）", "price": 180000, "classification": "UNVERIFIED"})
    summary = W.build_camera_summary(r, research_date=RD, now=NOW_CAM)
    text = json.dumps(summary, ensure_ascii=False)
    assert "Sony α7 V" not in text and "フジヤ抽選" not in text and "マップカメラ" not in text
    assert summary["hidden_counts"] == {"unverified_sell_candidates": 1, "unverified_lotteries": 1, "discovered_products_unverified": 1}


def test_camera_headline_uses_only_usable_sell_prices():
    gr = next(p for p in W.build_camera_summary(_camera_research(), research_date=RD, now=NOW_CAM)["products"] if p["product"] == "RICOH GR IV")
    # 使える売却先はフジヤ 151,000 円だけ。名前のない査定 205,000 円（古い）から利益を作らない
    assert [n["sell"] for n in gr["reference_net"]] == [151000]       # 日付つき・店名つき・新品の売却先だけ
    assert gr["reference_net"][0]["net_before_purchase_shipping"] == 151000 - 190620 - 1800
    assert "+1.3万" not in gr["note"] and "抽選に当たらなければ仕入れられません" in gr["note"]


def test_iphone_page_warns_when_the_research_is_old_and_labels_reference_route():
    from src.content import iphone_buyback_page as P
    apple = {"iPhone Duo": {"1TB": 440000}}
    comp = W.build_iphone_comparison([_shop("店A", 480000), _shop("店B", 481000)], apple, research_date=RD, now=NOW, cfg=_cfg())
    fresh = P.render(comp, now=datetime(2026, 11, 14, tzinfo=JST))
    assert "調査から" not in fresh
    old = P.render(comp, now=datetime(2026, 11, 25, tzinfo=JST))
    assert "調査から 12 日たっています" in old
    assert "参考の最大ルート（正本に未登録のため確定ではない）" in fresh and "最大利益ルート:" not in fresh


def test_public_build_creates_the_linked_pages(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bpl", Path(__file__).resolve().parents[1] / "scripts" / "build_public_lp.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._build_iphone_buyback_html(tmp_path)
    mod._build_camera_research_html(tmp_path)
    for name in ("iphone-buyback.html", "camera-research.html"):      # HOME・メニューのリンク先がビルドで実在する
        assert (tmp_path / name).exists() and "<html" in (tmp_path / name).read_text(encoding="utf-8")
    from src.content.ui import pages
    assert "./iphone-buyback.html" in pages._quick_links() and "./camera-research.html" not in pages._quick_links()


def test_camera_page_escapes_and_does_not_claim_buy():
    from src.content import camera_research_page as P
    r = _camera_research()
    r["price_routes"][0]["product"] = "<img src=x onerror=alert(1)>"
    html = P.render(W.build_camera_summary(r, research_date=RD, now=NOW_CAM), now=NOW_CAM)
    assert "<img src=x" not in html and "&lt;img" in html
    assert "LOTTERY_DEPENDENT" in html and "即時の BUY ではない" in html and "期待売値" in html and ">BUY<" not in html


def test_verification_product_mismatch_fails():
    ev = _agg(product_name="ハドウシーカー 検証できる商品")
    res = _fin([ev], [_ver(ev, product="まったく別の商品（ストームエメラルダ）")])
    assert res[0]["final_class"] == "FAILED_VERIFICATION" and res[0]["reasons"] == ["product_mismatch"]


def test_conflicting_verifications_fail():
    ev = _agg(product_name="ハドウシーカー 検証できる商品")
    res = _fin([ev], [_ver(ev), _ver(ev, verdict="UNVERIFIED", status="NOT_FOUND")])
    assert res[0]["final_class"] == "FAILED_VERIFICATION"


def test_date_only_winner_is_start_of_day_so_purchase_does_not_precede_it():
    c = W.classify_event(_ev(winner_announcement="2026-11-23", purchase_start="2026-11-23"), NOW)
    assert c["winner_announcement_at"] <= c["purchase_start"]
    assert "winner_announcement" in c["time_assumed"]


def test_page_updated_on_does_not_fabricate_a_date():
    for t in ("2026-11-13 ページ更新日の記載なし。取得日: 2026-11-13", "2026-11-13 (更新なし。取得日 2026-11-13)",
              "2026-11-13 JST（更新日時の記載なし。関連記事は 2026-11-04 投稿）", "2026-11-13 (ページ記載は日付のみ。時刻なし)",
              "2026-11-13 (取得日)", "2026-11-13 更新日不明"):
        assert W.page_updated_on(t) is None, t
    assert W.page_updated_on("2026-11-13 (取得)。ページ記載: 更新日 2026-11-12") == "2026-11-12"
    assert W.page_updated_on("2026-11-13 23:22-23:23 (ページ表示の時点。ページ自身の表記)") == "2026-11-13"


def test_same_shop_rows_count_as_one_source():
    # 同じ店の 2 行（通常価格・版違い）だけでは「2 店で裏が取れた」と数えない。保守的に最低の価格を採る
    two = _shop("A店", 365000, cap="256GB")
    two["skus"].append(dict(two["skus"][0], base_price=363000))
    s = _sku(_comp([two]), "iPhone Duo 256GB")
    assert s["eligible_shops"] == 1 and s["outlier_status"] == "SINGLE_SOURCE" and s["highest_executable"] is None
    assert s["highest_listed"]["price"] == 365000                      # 掲載の最高値は捨てない


def test_discovered_sku_has_reference_route_not_best_route():
    apple = {"iPhone Duo": {"1TB": 440000}}
    s = _sku(W.build_iphone_comparison([_shop("店A", 480000), _shop("店B", 481000)], apple, research_date=RD, now=NOW, cfg=_cfg()))
    assert s["identity"] == "DISCOVERED" and s["net_profit"] > 0
    assert s["best_route"] is None and s["reference_route"] == "Apple → 店B"
    apple2 = {"iPhone Duo": {"256GB": 330000}}
    r = _sku(W.build_iphone_comparison([_shop("店A", 365000, cap="256GB"), _shop("店B", 366000, cap="256GB")], apple2, research_date=RD, now=NOW, cfg=_cfg()), "iPhone Duo 256GB")
    assert r["identity"] == "REGISTERED" and r["best_route"] == "Apple → 店B" and r["reference_route"] is None


def test_worst_color_above_listed_is_inconsistent_not_executable():
    s = _sku(_comp([_shop("店A", 480000, executable_price_no_reduction=480000, executable_price_max_deduction=490000), _shop("店B", 470000)]))
    row = next(r for r in s["rows"] if r["shop"] == "店A")
    assert row["basis"] == "colors_unverified" and not row["eligible"]


def test_outlier_and_single_source_prices_are_not_history_changes():
    comp = _comp([_shop("A", 420000), _shop("B", 400000), _shop("C", 398000)])
    assert _sku(comp)["outlier_status"] == "OUTLIER_REVIEW"
    rows = W.snapshot_rows(comp)
    assert all(r["shop"] != "A" for r in rows if r["sku"] == "iPhone Duo 1TB")


def test_condition_matching_is_exact():
    assert W._condition("UNOPENED") == "UNOPENED" and W._condition("OPENED_NEW (指示により)") == "OPENED_NEW" and W._condition("UNOPENED_X") is None
    assert W._condition("OPENED") is None and W._condition("USED") == "USED"


def test_config_null_values_fall_back(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("outlier:\n  rate: null\nfreshness:\n  default:\n    fresh_days: null\nsurge:\n  yen: null\n", encoding="utf-8")
    cfg = W.load_config(p)
    s = _sku(W.build_iphone_comparison([_shop("A", 480000), _shop("B", 481000)], APPLE, research_date=RD, now=NOW, cfg=cfg))
    assert s["outlier_status"] == "NONE"
    assert W.freshness_of("x", "2026-11-13", RD, cfg)[0] == W.FRESH


def test_series_name_alone_does_not_match_a_different_product():
    assert not W._same_product("ポケモンカードゲーム MEGA 拡張パック「ハドウシーカー」（1BOX）", "ポケモンカードゲーム MEGA 拡張パック「インフェルノX」BOX")
    assert not W._same_product("ONE PIECEカードゲーム 新弾 OP-15 BOX", "ONE PIECEカードゲーム ブースターパック OP-13")
    assert W._same_product("ハドウシーカー BOX（三洋堂書店）", "ポケモンカードゲーム MEGA 拡張パック「ハドウシーカー」（1BOX）")
    assert W._same_product("ブースターパック 神の支配 OP-18", "ONE PIECE ブースターパック「神の支配」【OP-18】")


def test_history_has_one_row_per_shop_and_duplicate_rows_are_not_adopted():
    two = _shop("A店", 400000)
    two["skus"].append(dict(two["skus"][0], base_price=380000))
    comp = _comp([two, _shop("B店", 381000), _shop("C店", 379000)])
    s = _sku(comp)
    a_rows = [r for r in s["rows"] if r["shop"] == "A店"]
    assert sorted(r["eligible"] for r in a_rows) == [False, True] and any(r.get("duplicate_row") for r in a_rows)   # 高い方の行は採用しない
    assert next(r for r in a_rows if r["eligible"])["executable_price"] == 380000
    snap = [r for r in W.snapshot_rows(comp) if r["sku"] == "iPhone Duo 1TB" and r["shop"] == "A店"]
    assert [r["price"] for r in snap] == [380000]          # 履歴にも 1 店 1 行（保守的な価格）
    assert s["highest_listed"]["price"] == 400000 and s["highest_listed"]["executable"] is False     # 掲載の最高値は残るが、利益計算に使わない


def test_campaign_row_is_not_an_executable_price():
    s = _sku(_comp([_shop("店A", 480000, campaign="期間限定 +20,000円"), _shop("店B", 470000), _shop("店C", 469000)]))
    assert s["highest_executable"]["shop"] == "店B" and s["highest_listed"]["shop"] == "店A"
    assert next(r for r in s["rows"] if r["shop"] == "店A")["campaign"]            # キャンペーンは別欄に残す


def test_future_update_date_is_not_fresh():
    cfg = _cfg()
    assert W.freshness_of("x", "2026-11-20", RD, cfg) == (W.UNKNOWN_FRESHNESS, None)


def test_marketplace_domains_are_not_primary_evidence():
    for u in ("https://www.amazon.co.jp/dp/B0X", "https://item.rakuten.co.jp/some-shop/x/", "https://books.rakuten.co.jp/rb/1/"):
        assert W.primary_evidence(u) is None


def test_camera_article_buy_price_is_not_public_and_makes_no_profit():
    r = _camera_research()
    r["price_routes"][0]["buy"]["price_note"] = "価格は記事。公式ページには金額なし"
    gr = next(p for p in W.build_camera_summary(r, research_date=RD, now=NOW_CAM)["products"] if p["product"] == "RICOH GR IV")
    assert gr["buy"]["price"] is None and gr["reference_net"] == [] and "公開しない" in gr["buy"]["price_note"]
    assert "190620" not in json.dumps(gr, ensure_ascii=False)


def test_pages_show_when_they_were_built_and_reference_profit_is_not_green():
    from src.content import iphone_buyback_page as P, camera_research_page as C
    apple = {"iPhone Duo": {"1TB": 440000}}
    comp = W.build_iphone_comparison([_shop("店A", 480000), _shop("店B", 481000)], apple, research_date=RD, now=NOW, cfg=_cfg())
    t = datetime(2026, 11, 14, 9, 30, tzinfo=JST)
    html = P.render(comp, now=t)
    assert "2026-11-14 09:30" in html and 'class="pos"' not in html            # 未登録の参考の黒字は緑にしない
    assert "2026-11-14 09:30" in C.render(W.build_camera_summary(_camera_research(), research_date=RD, now=NOW_CAM), now=t)


def test_host_of_handles_userinfo_and_ports():
    assert W._host_of("https://www.ricoh-imaging.co.jp:443/x") == "www.ricoh-imaging.co.jp"
    assert W._host_of("https://ricoh-imaging.co.jp@evil.example/x") == "evil.example"        # userinfo で公式に見せかけない
    assert W.primary_evidence("https://ricoh-imaging.co.jp@evil.example/x") is None
    assert W._host_of("javascript:alert(1)") == "" and W._host_of("") == ""
