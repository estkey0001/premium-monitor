"""iPhone Product Hub（src/content/iphone_hub_model.py と iphone_buyback_page.render の拡張）の表示テスト。

表示層だけ。5 つの問い・推測の価格を出さない・参考の扱い・履歴 0/1/3 件・シグナルが diff_snapshots と一致・新製品・
エスケープ・公開物に絶対パスを出さない・render(comp) の後方互換を固定する。
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.content import iphone_buyback_page as P
from src.content import iphone_hub_model as H
from src.research.weekly_import import diff_snapshots

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 18, 10, 0, tzinfo=JST)
ROOT = Path(__file__).resolve().parents[1]


def _row(sku, key, shop, price, *, eligible=True, freshness="FRESH"):
    return {"sku": sku, "condition": "UNOPENED", "executable_price": price if eligible else None, "listed_price": price,
            "shop": shop, "key": key, "shop_status": "ACTIVE", "freshness": freshness, "eligible": eligible,
            "basis": "uniform", "color_adjustments": {}, "price_page_url": "https://example.com/", "checked_at": "2026-11-17",
            "updated_on": "2026-11-17", "age_days": 0}


def _sku(sku, *, identity="REGISTERED", hx=None, net=None, roi=None, opp="WAIT", rows=None, hl=None, unc=None):
    return {"sku": sku, "apple_price": 400000, "identity": identity,
            "apple_availability": {"status": "BUYABLE", "checked_at": "2026-11-17T10:00:00+09:00"},
            "profit_status": "PROFITABLE" if net else "NO_DATA", "opportunity_status": opp, "opportunity_reason": "テスト",
            "identity_note": "", "source_count": len(rows or []), "fresh_source_count": 0, "outlier_status": "NONE",
            "highest_listed": hl, "highest_executable": hx, "highest_unconfirmed": unc, "second": None, "third": None,
            "costs": 1800, "net_profit": net, "roi_pct": roi, "rows": rows or []}


def _comp(skus, events=None):
    return {"research_date": "2026-11-17", "generated_at": "2026-11-17T10:00:00+09:00", "note": "週次", "shops_researched": 3,
            "counts": {"ACTIVE": 3, "FRESH": 3, "STALE": 0, "UNKNOWN_FRESHNESS": 0, "NO_PRICE": 0, "FAILED": 0, "BLOCKED": 0},
            "shops": [], "skus": skus, "events": events or [], "events_note": "前回の週次の調査との比較"}


def _simple():
    good = _sku("iPhone Duo 1TB", hx={"shop": "店A", "price": 483000}, net=11400, roi=2.4,
                rows=[_row("iPhone Duo 1TB", "a", "店A", 483000), _row("iPhone Duo 1TB", "b", "店B", 475000)])
    none = _sku("iPhone Duo 256GB", hx=None, opp="PASS", rows=[_row("iPhone Duo 256GB", "z", "古い店", 371000, eligible=False, freshness="STALE")],
                hl={"shop": "古い店", "price": 371000, "freshness": "STALE", "executable": False})
    ref = _sku("iPhone 18 Pro 256GB", identity="DISCOVERED", hx={"shop": "店A", "price": 230000}, net=9000, roi=4.0,
               rows=[_row("iPhone 18 Pro 256GB", "a", "店A", 230000)])
    return _comp([good, none, ref])


def _snap(date, rows):
    return {"date": date, "rows": rows}


def _hr(sku, key, shop, price, net=None, identity="REGISTERED"):
    return {"sku": sku, "identity": identity, "key": key, "shop": shop, "price": price, "net": net}


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.split("</style>")[-1]))


# ---- 5 つの問い ----
def test_five_questions_are_answered_in_the_page():
    html = P.render(_simple(), now=NOW)
    t = _text(html)
    assert "どの容量を買うか" in t and "1TB を買い" not in t                  # 判定が WAIT の黒字を「買い」と断定しない
    assert "様子見" in t and "「買い」とは案内しません" in t                     # 代わりに様子見として理由つきで案内する
    assert "1TB" in t
    assert "店A" in t and "¥483,000" in t                                       # どの店へ売る
    assert "+¥11,400" in t and "ROI 2.4%" in t                                  # 利益
    assert "前回比" in t                                                         # 前回比
    assert "WAIT（待ち）" in t and "BUY か WAIT か" in t                          # 判断
    assert ">BUY<" not in html and "BUY（週次の判定）" not in html


def test_no_executable_price_shows_waiting_without_guessing_price_or_profit():
    c = _simple()
    c["skus"] = [c["skus"][1]]                                                  # 実行可能価格が無い SKU だけ
    html = P.render(c, now=NOW)
    ans = html[html.index("今の結論"):html.index("モデル別・容量別の詳細")]
    t = _text(ans)
    assert "確認待ち" in t and "データ無し" in t and "売り先として案内しない" in t
    assert "古い店" not in t and "371,000" not in t                             # STALE の掲載最高値を売り先にしない
    assert "+¥" not in t and "−¥" not in t                                      # 推測の利益を出さない
    assert H.model_conclusion(c["skus"])["status"] == "WAITING"


def test_reference_sku_is_labeled_and_never_green():
    html = P.render(_simple(), now=NOW)
    assert "参考・正本に未登録" in html
    ref_cards = html[html.index("iPhone 18 Pro（参考"):]
    assert 'class="pos"' not in ref_cards                                        # 参考の黒字は緑にしない
    ref_only = _comp([_simple()["skus"][2]])
    h2 = P.render(ref_only, now=NOW)
    assert "参考・正本に未登録" in h2 and 'class="pos"' not in h2
    assert H.model_conclusion(ref_only["skus"])["status"] == "REFERENCE_ONLY"
    assert '<details class="model">' in h2 and '<details class="model" open>' not in h2      # 参考のモデルは折りたたみ


def test_registered_positive_profit_is_green_only_for_registered():
    html = P.render(_simple(), now=NOW)
    assert html.count('class="pos"') >= 1
    first = html[html.index("今の結論"):html.index("iPhone 18 Pro")]
    assert 'class="pos"' in first


# ---- 履歴 0 / 1 / 3 件 ----
def test_history_none_is_no_data():
    html = P.render(_simple(), now=NOW)                                          # history=None
    t = _text(html)
    assert "履歴データ無し" in t and "過去分は履歴データ無し" in t
    assert "新製品・予約情報" in t and "データ無し（新製品・予約情報を読めない）" in t


def test_history_one_snapshot_says_single_record():
    h = {"schema": 1, "snapshots": [_snap("2026-11-17", [_hr("iPhone Duo 1TB", "a", "店A", 483000, 11400)])]}
    t = _text(P.render(_simple(), now=NOW, history=h))
    assert "記録 1 件のみ" in t
    assert "前回の記録なし（初回）" in t


def test_history_three_snapshots_compare_same_shops_only():
    sku = "iPhone Duo 1TB"
    h = {"schema": 1, "snapshots": [
        _snap("2026-11-10", [_hr(sku, "a", "店A", 490000), _hr(sku, "b", "店B", 480000), _hr(sku, "c", "店C", 495000)]),
        _snap("2026-11-14", [_hr(sku, "a", "店A", 486000), _hr(sku, "b", "店B", 476000)]),
        _snap("2026-11-17", [_hr(sku, "a", "店A", 483000, 11400), _hr(sku, "b", "店B", 475000)])]}
    c = _simple()
    tl = H.build_timeline(c, h)
    cmp_ = H.prev_compare(tl, sku)
    assert cmp_["status"] == "OK" and cmp_["prev_date"] == "2026-11-14" and cmp_["common"] == 2
    assert (cmp_["prev_best"], cmp_["cur_best"], cmp_["delta"]) == (486000, 483000, -3000)
    # 3 店あった日（店 C が最高）と今日を、店数の違うまま比べない
    tr = H.sku_trend(tl, sku)
    assert [t["shops"] for t in tr[:2]] == [3, 2] and tr[0]["best_price"] == 495000
    t = _text(P.render(c, now=NOW, history=h))
    assert "取得店数" in t and "2026-11-10" in t and "−¥3,000" in t


def test_history_skips_dates_with_no_common_shop():
    sku = "iPhone Duo 1TB"
    h = {"schema": 1, "snapshots": [_snap("2026-11-10", [_hr(sku, "x", "別の店", 490000)])]}
    cmp_ = H.prev_compare(H.build_timeline(_simple(), h), sku)
    assert cmp_["status"] == "NO_DATA" and "同じ店の過去の記録なし" in cmp_["reason"]


def test_malformed_history_does_not_break_page():
    for bad in ({}, {"snapshots": "x"}, {"snapshots": [1, None, {"date": "2026-11-01"}]}, []):
        html = P.render(_simple(), now=NOW, history=bad)
        assert "iPhone Product Hub" in html


# ---- シグナル ----
def test_signals_match_diff_snapshots():
    s1, s2 = "iPhone Duo 1TB", "iPhone Duo 2TB"
    d1 = [_hr(s1, "a", "店A", 490000, 20000), _hr(s1, "b", "店B", 480000), _hr(s2, "a", "店A", 590000, 5000)]
    d2 = [_hr(s1, "a", "店A", 482000, 12000), _hr(s1, "b", "店B", 481000), _hr(s2, "a", "店A", 599000, 5000)]
    d3 = [_hr(s1, "a", "店A", 483000, 12000), _hr(s1, "b", "店B", 481000), _hr(s2, "a", "店A", 599000, 5000)]
    h = {"schema": 1, "snapshots": [_snap("2026-11-10", d1), _snap("2026-11-14", d2), _snap("2026-11-17", d3)]}
    comp = _comp([_sku(s1, hx={"shop": "店A", "price": 483000}, net=12000, rows=[_row(s1, "a", "店A", 483000), _row(s1, "b", "店B", 481000)])],
                 events=[{"type": "BUYBACK_SURGE", "sku": s1, "shop": "店A", "from": 482000, "to": 483000}])
    sg = H.signals(comp, H.build_timeline(comp, h))
    past = [g for g in sg["groups"] if g["date"] == "2026-11-14"]
    assert len(past) == 1 and past[0]["events"] == diff_snapshots(d1, d2)         # 店の組が同じ日は diff_snapshots と完全に一致
    assert {e["type"] for e in past[0]["events"]} >= {"PRICE_DROP", "BUYBACK_SURGE"}
    cur = [g for g in sg["groups"] if g["date"] == "2026-11-17"]
    assert cur and cur[0]["events"] == comp["events"]                            # 今回分は comp["events"] をそのまま
    t = _text(P.render(comp, now=NOW, history=h))
    assert "買取価格の下落" in t and "2026-11-14" in t


def test_signals_ignore_unregistered_and_say_none_when_empty():
    sku = "iPhone Duo 512GB"
    h = {"schema": 1, "snapshots": [_snap("2026-11-10", [_hr(sku, "a", "店A", 400000, identity="DISCOVERED")]),
                                    _snap("2026-11-14", [_hr(sku, "a", "店A", 380000, identity="DISCOVERED")])]}
    comp = _comp([_sku(sku, identity="DISCOVERED")])
    tl = H.build_timeline(comp, h)
    assert H.signals(comp, tl)["groups"] == []                                   # REGISTERED のみ（diff_snapshots の方針）
    assert "検出なし" in _text(P.render(comp, now=NOW, history=h))


def test_signals_for_past_pairs_with_different_shop_sets_are_not_compared():
    sku = "iPhone Duo 1TB"
    h = {"schema": 1, "snapshots": [_snap("2026-11-10", [_hr(sku, "a", "店A", 490000, 1), _hr(sku, "c", "店C", 520000)]),
                                    _snap("2026-11-14", [_hr(sku, "a", "店A", 489000, 1), _hr(sku, "b", "店B", 500000)])]}
    comp = _comp([_sku(sku)])
    assert H.signals(comp, H.build_timeline(comp, h))["groups"] == []            # 共通の店 A だけで比べる（−1,000 円は閾値未満）


# ---- 新製品・予約情報 ----
def _cands():
    def c(name, status, price):
        return {"brand": "Apple", "genre": "iphone", "product_name": name, "status": status, "official_price": price,
                "discovered_at": "2026-10-17T17:34:02+09:00", "last_seen_on": "2026-11-18", "candidate_id": "apple-secret123",
                "review": {"decision": "APPROVED", "reason": "内部メモ"}, "decisions": [{"reason": "内部メモ"}]}
    return {"schema": 1, "candidates": {"x1": c("iPhone Duo 1TB", "REGISTERED", 469800), "x2": c("iPhone Duo 512GB", "PENDING_REVIEW", 399800),
                                        "x3": c("iPhone Air 256GB", "REGISTERED", 189800),
                                        "x4": {"brand": "Pokemon", "genre": "tcg", "product_name": "BOX", "status": "PENDING_REVIEW"}}}


def test_new_product_section_labels_and_release_date_is_no_data():
    html = P.render(_simple(), now=NOW, candidates=_cands())
    t = _text(html)
    sec = t[t.index("新製品・予約情報"):]
    assert "登録済み" in sec and "未登録（確認待ち）" in sec and "iPhone Air" in sec and "¥469,800" in sec
    assert "2026-10-17" in sec and "2026-11-18" in sec
    assert "発売日・予約日" in sec and sec.count("データ無し") >= 3
    assert "apple-secret123" not in html and "内部メモ" not in html and "BOX" not in html
    assert H.apple_candidates({"candidates": {}}) is None and H.apple_candidates(None) is None


# ---- 安全性 ----
def test_escaping_and_no_javascript_links_and_no_local_paths():
    c = _simple()
    c["skus"][0]["rows"][0]["shop"] = "<script>alert(1)</script>"
    c["skus"][0]["rows"][0]["price_page_url"] = "javascript:alert(1)"
    c["skus"][0]["highest_executable"] = {"shop": "<img src=x onerror=1>", "price": 483000}
    c["events"] = [{"type": "PRICE_DROP", "sku": "<b>x</b>", "shop": "<i>y</i>", "from": 2, "to": 1}]
    cand = _cands()
    cand["candidates"]["x1"]["product_name"] = "<u>iPhone Duo</u> 1TB"
    html = P.render(c, now=NOW, candidates=cand)
    assert "<script>alert(1)" not in html and "<img src=x" not in html and "<b>x</b>" not in html and "<u>iPhone" not in html
    assert "&lt;script&gt;" in html and 'href="javascript:' not in html
    assert "/Users/" not in html and ".private" not in html


def test_backward_compatible_signature_and_css_exports():
    html = P.render(_simple())                                                    # 追加引数なし・now なし
    assert "<!doctype html>" in html and "iPhone Product Hub" in html
    assert isinstance(P.CSS, str) and isinstance(P.HUB_CSS, str) and P.HUB_CSS not in P.CSS
    assert P.age_banner("2026-11-01", NOW).startswith('<div class="note">')
    row = P._row_html({"shop": "店", "shop_status": "ACTIVE", "condition": "UNOPENED", "freshness": "FRESH", "basis": "uniform",
                       "listed_price": 1, "executable_price": 1, "eligible": True})
    assert "<tr" in row


def test_rank_numbers_only_eligible_rows():
    s = _simple()["skus"][0]
    s["rows"].append(_row(s["sku"], "c", "対象外", 999000, eligible=False))
    html = P.render(_comp([s]), now=NOW)
    assert "1 位" in html and "2 位" in html and "3 位" not in html
    ranks = H.rank_rows(s)
    assert sorted(ranks.values()) == [1, 2]


def test_models_are_grouped_and_registered_first():
    g = H.group_models([_sku("iPhone 18 Pro 512GB", identity="DISCOVERED"), _sku("iPhone Duo 1TB"), _sku("iPhone Duo 256GB"),
                        _sku("iPhone 18 Pro 256GB", identity="DISCOVERED")])
    assert [x["model"] for x in g] == ["iPhone Duo", "iPhone 18 Pro"] and [x["primary"] for x in g] == [True, False]
    assert [s["sku"] for s in g[0]["skus"]] == ["iPhone Duo 256GB", "iPhone Duo 1TB"]
    assert H.split_sku("iPhone Duo 1TB") == ("iPhone Duo", "1TB") and H.split_sku("謎") == ("謎", "")


# ---- コミット済みの実データ ----
def test_committed_data_renders_with_history_and_candidates():
    load = lambda p: json.loads((ROOT / p).read_text(encoding="utf-8")) if (ROOT / p).exists() else None   # noqa: E731
    comp = load("exports/iphone_buyback/iphone_buyback_comparison.json")
    if comp is None:
        return
    html = P.render(copy.deepcopy(comp), now=NOW, history=load("exports/iphone_buyback/iphone_buyback_history.json"),
                    candidates=load("exports/discovery/product_candidates.json"))
    t = _text(html)
    assert "今の結論" in t and "新製品・予約情報" in t and "シグナル" in t
    assert "/Users/" not in html and ".private" not in html and 'href="javascript:' not in html
    for s in comp["skus"]:                                   # 実行可能価格が無い SKU を売り先として案内しない
        if not s.get("highest_executable"):
            a = H.sku_answer(s)
            assert a["sell_shop"] is None and a["net"] is None and a["sell_reason"]


def test_conclusion_says_buy_only_when_decision_is_buy_and_apple_is_buyable():
    c = _simple()
    c["skus"][0]["opportunity_status"] = "BUY"
    html = P.render(c, now=NOW)
    assert "1TB</b> を買い" in html and H.model_conclusion(c["skus"])["status"] == "PROFIT"
    c["skus"][0]["apple_availability"] = {"status": "OUT_OF_STOCK", "checked_at": "2026-11-17T10:00:00+09:00"}   # Apple で買えない
    assert H.model_conclusion(c["skus"])["status"] == "PROFIT_WATCH" and "を買い" not in P.render(c, now=NOW).split("モデル別・容量別の詳細")[0].split("今の結論")[1]
