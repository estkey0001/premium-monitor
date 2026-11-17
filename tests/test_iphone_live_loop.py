"""iPhone の価格更新ループ（段階 A）: Apple の購入可否・利益の状態と BUY の分離・価格の上昇/下落・履歴・ページ。

守ること: 購入できると確認できたときだけ BUY の候補になる（不明・購入不可・古い確認は BUY にならない）／黒字は自動的に BUY にならない／
STALE・UNKNOWN_FRESHNESS は実行可能価格に使わない／履歴を二重にしない／通知は送らない（dry-run の記録だけ）。
"""
import json
from datetime import datetime, timedelta, timezone

from src.collectors.official import apple_buyability as AB
from src.content import iphone_buyback_page as P
from src.research import weekly_import as W

JST = timezone(timedelta(hours=9))
RD = "2026-11-16"
NOW = datetime(2026, 11, 16, 21, 0, tzinfo=JST)
APPLE = {"iPhone Duo": {"256GB": 364800, "512GB": 399800, "1TB": 469800, "2TB": 574800}}
FRESH_TXT = "2026-11-16 (取得日)。ページ記載: 更新日 2026-11-16"
STALE_TXT = "2026-11-13 (取得日)。ページ記載: 更新日 2026-11-13"
UNKNOWN_TXT = "2026-11-16 (取得日。ページに更新日時の記載なし)"
REG = {"iPhone Duo 1TB": "prod_iphoneduo_1tb", "iPhone Duo 2TB": "prod_iphoneduo_2tb"}


def _shop(name, price, *, cap="1TB", checked=FRESH_TXT):
    row = {"model": "iPhone Duo", "storage": cap, "condition": "UNOPENED", "base_price": price, "color_adjustments": {}}
    return {"shop_name": name, "official_url": "https://example.com/", "price_page_url": "https://example.com/p", "checked_at": checked,
            "fetch_status": "ACTIVE", "skus": [row]}


def _av(status="BUYABLE", checked="2026-11-16T20:00:00+09:00"):
    return {"status": status, "checked_at": checked, "source": "https://www.apple.com/jp/shop/buyability-message", "parts": {"MK284J/A": True} if status == "BUYABLE" else {"MK284J/A": False}}


def _comp(shops, *, availability=None, registered=REG, cap_av=("iPhone Duo 1TB", "iPhone Duo 2TB")):
    if availability is None:
        availability = {k: _av() for k in cap_av}
    return W.build_iphone_comparison(shops, APPLE, research_date=RD, now=NOW, cfg=W.load_config(), registered=registered,
                                     availability=availability)


def _sku(comp, name="iPhone Duo 1TB"):
    return next(s for s in comp["skus"] if s["sku"] == name)


# ---- Duo 1TB / 2TB の現在の値（11-16 の実測）で、黒字でも BUY ではない ----
def test_profitable_duo_below_roi_threshold_is_not_buy():
    s = _sku(_comp([_shop("パステック（PASTEC）", 482000), _shop("買取ルデヤ", 481000)]))
    assert s["net_profit"] == 10400 and s["roi_pct"] == 2.21
    assert s["profit_status"] == "PROFITABLE" and s["opportunity_status"] == "WAIT"        # 黒字だが ROI 8% 未満 → BUY ではない
    s2 = _sku(_comp([_shop("PASTEC", 586000, cap="2TB"), _shop("ルデヤ", 585000, cap="2TB")]), "iPhone Duo 2TB")
    assert s2["net_profit"] == 9400 and s2["profit_status"] == "PROFITABLE" and s2["opportunity_status"] == "WAIT"


def test_buy_needs_every_condition():
    ok = _sku(_comp([_shop("店A", 520000), _shop("店B", 519000)]))
    assert ok["opportunity_status"] == "BUY" and ok["roi_pct"] >= W.BUY_ROI_MIN_PCT
    # 購入可否が分からない / 購入できない / 古い確認 → BUY にならない（黒字・ROI は十分でも）
    shops = [_shop("店A", 520000), _shop("店B", 519000)]
    assert _sku(_comp(shops, availability={}))["opportunity_status"] == "WATCH"
    assert _sku(_comp(shops, availability={"iPhone Duo 1TB": _av("UNKNOWN")}))["opportunity_status"] == "WATCH"
    assert _sku(_comp(shops, availability={"iPhone Duo 1TB": _av("UNAVAILABLE")}))["opportunity_status"] == "WAIT"
    old = _comp(shops, availability={"iPhone Duo 1TB": _av("BUYABLE", checked="2026-11-13T20:00:00+09:00")})
    assert _sku(old)["apple_availability"]["status"] == "UNKNOWN" and _sku(old)["opportunity_status"] == "WATCH"     # 日付を付け替えない
    # 1 店だけ（比較できない）・未登録 → BUY にならない
    single = _sku(_comp([_shop("店A", 520000)]))
    assert single["opportunity_status"] == "PASS" and single["net_profit"] is None and single["outlier_status"] == "SINGLE_SOURCE"
    unreg = _sku(_comp(shops, registered={}))
    assert unreg["opportunity_status"] == "WATCH" and unreg["profit_status"] == "REFERENCE_PROFIT" and unreg["best_route"] is None


def test_profit_still_shown_when_availability_unknown_or_unavailable():
    for av in ("UNKNOWN", "UNAVAILABLE"):
        s = _sku(_comp([_shop("パステック（PASTEC）", 482000), _shop("買取ルデヤ", 481000)], availability={"iPhone Duo 1TB": _av(av)}))
        assert s["net_profit"] == 10400 and s["profit_status"] == "PROFITABLE"          # 利益は表示する
        assert s["opportunity_status"] in ("WATCH", "WAIT") and s["opportunity_status"] != "BUY"


def test_loss_and_no_data_are_pass():
    assert _sku(_comp([_shop("店A", 460000), _shop("店B", 459000)]))["profit_status"] == "LOSS"
    assert _sku(_comp([_shop("店A", 460000), _shop("店B", 459000)]))["opportunity_status"] == "PASS"
    nd = _sku(_comp([]))
    assert nd["profit_status"] == "NO_DATA" and nd["opportunity_status"] == "PASS"


# ---- 鮮度: STALE・UNKNOWN は実行可能価格にならない（BUY にも利益にもならない）----
def test_stale_and_unknown_freshness_never_executable_or_buy():
    for txt in (STALE_TXT, UNKNOWN_TXT):
        s = _sku(_comp([_shop("店A", 540000, checked=txt), _shop("店B", 539000, checked=txt)]))
        assert s["highest_executable"] is None and s["net_profit"] is None and s["opportunity_status"] == "PASS"
        assert s["highest_listed"] is not None                                           # 表示はする
    mixed = _sku(_comp([_shop("店A", 540000, checked=STALE_TXT), _shop("店B", 482000), _shop("店C", 481000)]))
    assert mixed["highest_executable"]["price"] == 482000 and mixed["highest_listed"]["price"] == 540000


# ---- イベント: 価格低下 / 上昇 / 黒字↔赤字 / 最高店の変更 ----
def _r(price, net=None, key="pastec", sku="iPhone Duo 1TB", ident="REGISTERED"):
    return {"sku": sku, "identity": ident, "key": key, "shop": key.upper(), "price": price, "net": net}


def test_price_drop_and_rise_events_for_duo_1tb():
    drop = W.diff_snapshots([_r(492000, 20400)], [_r(482000, 10400)])
    assert [e["type"] for e in drop] == ["PRICE_DROP"] and drop[0]["from"] == 492000 and drop[0]["to"] == 482000
    rise = W.diff_snapshots([_r(482000, 10400)], [_r(492000, 20400)])
    assert [e["type"] for e in rise] == ["BUYBACK_SURGE"]
    small = W.diff_snapshots([_r(482000, 10400)], [_r(480000, 8400)])
    assert small == []                                                                   # 閾値（5,000 円）未満は出さない
    p2 = W.diff_snapshots([_r(586000, 9400, sku="iPhone Duo 2TB")], [_r(575000, -1600, sku="iPhone Duo 2TB")])
    assert {e["type"] for e in p2} == {"PRICE_DROP", "PROFIT_TO_LOSS"}


def test_profit_to_loss_and_loss_to_profit_and_unregistered_excluded():
    assert {e["type"] for e in W.diff_snapshots([_r(480000, 300)], [_r(470000, -9700)])} >= {"PROFIT_TO_LOSS"}
    assert "LOSS_TO_PROFIT" in {e["type"] for e in W.diff_snapshots([_r(470000, -9700)], [_r(480000, 300)])}
    assert W.diff_snapshots([_r(492000, 20400, ident="DISCOVERED")], [_r(470000, -9700, ident="DISCOVERED")]) == []


# ---- 履歴 ----
def test_history_rows_have_product_shop_price_checked_at_condition_freshness_and_no_duplicates(tmp_path):
    comp = _comp([_shop("パステック（PASTEC）", 482000), _shop("買取ルデヤ", 481000)])
    h = tmp_path / "h.json"
    hist = W.update_history(comp, h)
    row = next(r for r in hist["snapshots"][-1]["rows"] if r["key"] == "pastec" and r["sku"] == "iPhone Duo 1TB")
    assert row["price"] == 482000 and row["condition"] == "UNOPENED" and row["freshness"] == "FRESH" and row["checked_at"]
    assert hist["snapshots"][-1]["apple"]["iPhone Duo 1TB"] == {"price": 469800, "availability": "BUYABLE", "decision": "WAIT"}
    h.write_text(json.dumps(hist), encoding="utf-8")
    again = W.update_history(_comp([_shop("パステック（PASTEC）", 482000), _shop("買取ルデヤ", 481000)]), h)
    assert len(again["snapshots"]) == 1                                                  # 同じ日の再実行で二重にしない


def test_weekly_price_change_is_captured_and_notifications_are_dry_run_only(tmp_path):
    h = tmp_path / "h.json"
    d13 = "2026-11-13 ページ記載: 更新日 2026-11-13"
    prev = W.build_iphone_comparison([_shop("パステック（PASTEC）", 492000, checked=d13), _shop("買取ルデヤ", 480000, checked=d13)], APPLE,
                                     research_date="2026-11-13", now=NOW, cfg=W.load_config(), registered=REG, availability={})
    h.write_text(json.dumps(W.update_history(prev, h)), encoding="utf-8")
    comp = _comp([_shop("パステック（PASTEC）", 482000), _shop("買取ルデヤ", 481000)])
    W.update_history(comp, h)
    assert "PRICE_DROP" in {e["type"] for e in comp["events"]}
    assert comp["notification_dry_run"]["mode"] == "DRY_RUN" and comp["notification_dry_run"]["sent"] == 0


# ---- ページ ----
def test_page_shows_availability_status_checked_at_and_does_not_call_watch_a_buy():
    comp = _comp([_shop("パステック（PASTEC）", 482000), _shop("買取ルデヤ", 481000)])
    html = P.render(comp, now=NOW)
    assert "Apple の購入可否" in html and "購入できる（Apple で確認）" in html and "PROFITABLE" in html and "WAIT（待ち）" in html
    assert "確認: 2026-11-16" in html and "BUY（週次の判定）" not in html
    unknown = P.render(_comp([_shop("パステック（PASTEC）", 482000), _shop("買取ルデヤ", 481000)], availability={}), now=NOW)
    assert "購入可否 未確認" in unknown and "BUY（週次の判定）" not in unknown
    buy = P.render(_comp([_shop("店A", 520000), _shop("店B", 519000)]), now=NOW)
    assert "BUY（週次の判定）" in buy


def test_page_events_show_price_drop():
    comp = _comp([_shop("パステック（PASTEC）", 482000), _shop("買取ルデヤ", 481000)])
    comp["events"] = [{"type": "PRICE_DROP", "sku": "iPhone Duo 1TB", "shop": "PASTEC", "from": 492000, "to": 482000}]
    html = P.render(comp, now=NOW)
    assert "買取価格の下落" in html and "¥492,000 → ¥482,000" in html and "通知は送信していません" in html


# ---- Apple の購入可否の取得 ----
PARTS = ["MK284J/A", "MK294J/A"]
OK_BODY = '{"head":{"status":"200"},"body":{"content":{"buyabilityMessage":{"sth":{"MK284J/A":{"isBuyable":true},"MK294J/A":{"isBuyable":true}},"order":["sth"]}}}}'


def test_parse_buyability_and_sku_status():
    assert AB.parse_buyability(OK_BODY, PARTS) == {"MK284J/A": True, "MK294J/A": True}
    mixed = OK_BODY.replace('"MK294J/A":{"isBuyable":true}', '"MK294J/A":{"isBuyable":false}')
    flags = AB.parse_buyability(mixed, PARTS)
    assert AB.sku_status(list(flags.values())) == "UNAVAILABLE"                           # 1 色でも買えなければ「買える」にしない
    assert AB.parse_buyability("<html>", PARTS) == {p: None for p in PARTS}
    assert AB.parse_buyability(None, PARTS) == {p: None for p in PARTS}
    missing = AB.parse_buyability(OK_BODY.replace('"MK294J/A":{"isBuyable":true}', ""), PARTS)
    assert missing["MK294J/A"] is None and AB.sku_status(list(missing.values())) == "UNKNOWN"
    assert AB.sku_status([]) == "UNKNOWN" and AB.sku_status([True, True]) == "BUYABLE"


def test_fetch_failure_is_unknown_not_buyable():
    res = AB.fetch_buyability(PARTS, fetch=lambda u: (None, "http_403"), now=NOW)
    assert res["error"] == "http_403" and all(v is None for v in res["parts"].values())
    av = AB.availability_by_sku({"iPhone Duo 1TB": PARTS}, res)
    assert av["iPhone Duo 1TB"]["status"] == "UNKNOWN"
    bad = AB.fetch_buyability(PARTS, fetch=lambda u: ("{}", ""), now=NOW)
    assert bad["error"] == "unexpected_format"


def test_apple_live_reads_prices_parts_and_availability_with_fakes():
    page = ('"sku":"MK284","partNumber":"MK284J/A","price":{"fullPrice":469800},"category":"iphone","name":"iPhone Duo 1TB Star White"')
    from src.discovery import apple
    fake_products = [{"sku": "MK284", "part_number": "MK284J/A", "price": 469800, "name": "iPhone Duo 1TB Star White",
                      "parsed": {"line": "iPhone Duo", "line_key": "iphone duo", "capacity": "1TB", "color": "Star White"}},
                     {"sku": "MK294", "part_number": "MK294J/A", "price": 469800, "name": "iPhone Duo 1TB Night Sky",
                      "parsed": {"line": "iPhone Duo", "line_key": "iphone duo", "capacity": "1TB", "color": "Night Sky"}}]
    orig = apple.parse_products
    apple.parse_products = lambda html: fake_products
    try:
        live = AB.apple_live(fetch_page=lambda u: (page, ""), fetch=lambda u: (OK_BODY, ""), now=NOW)
    finally:
        apple.parse_products = orig
    assert live["prices"] == {"1TB": 469800} and live["sku_parts"] == {"iPhone Duo 1TB": PARTS}
    assert live["availability"]["iPhone Duo 1TB"]["status"] == "BUYABLE" and live["errors"] == []


def test_committed_comparison_buy_requires_every_condition():
    """コミット済みの比較データでも、BUY は全条件（登録済み・購入可能・2 店以上・外れ値なし・ROI 8% 以上）を満たすものだけ。"""
    from pathlib import Path
    d = json.loads((Path(__file__).resolve().parents[1] / "exports" / "iphone_buyback" / "iphone_buyback_comparison.json").read_text(encoding="utf-8"))
    assert d["notification_dry_run"]["sent"] == 0
    for s in d["skus"]:
        assert s["opportunity_status"] in ("BUY", "WATCH", "WAIT", "PASS") and s["profit_status"] in ("PROFITABLE", "LOSS", "NO_DATA", "REFERENCE_PROFIT")
        assert s["apple_availability"]["status"] in ("BUYABLE", "UNAVAILABLE", "UNKNOWN")
        if s["profit_status"] == "PROFITABLE":
            assert s["net_profit"] > 0 and s["identity"] == "REGISTERED"
        if s.get("opportunity_status") == "BUY":
            assert s["identity"] == "REGISTERED" and s["apple_availability"]["status"] == "BUYABLE"
            assert s["eligible_shops"] >= 2 and s["outlier_status"] in ("NONE", "REVIEWED") and s["roi_pct"] >= W.BUY_ROI_MIN_PCT
        if s.get("apple_availability", {}).get("status") != "BUYABLE":
            assert s.get("opportunity_status") != "BUY"


def test_price_differs_by_color_is_not_buyable_and_old_price_is_not_kept(tmp_path):
    from src.discovery import apple
    prods = [{"sku": "A", "part_number": "MK284J/A", "price": 469800, "name": "x", "parsed": {"line": "iPhone Duo", "capacity": "1TB", "color": "a"}},
             {"sku": "B", "part_number": "MK294J/A", "price": 479800, "name": "x", "parsed": {"line": "iPhone Duo", "capacity": "1TB", "color": "b"}},
             {"sku": "C", "part_number": "MK244J/A", "price": 364800, "name": "x", "parsed": {"line": "iPhone Duo", "capacity": "256GB", "color": "a"}}]
    body = ('{"body":{"content":{"buyabilityMessage":{"sth":{"MK284J/A":{"isBuyable":true},"MK294J/A":{"isBuyable":true},'
            '"MK244J/A":{"isBuyable":true}}}}}}')
    orig = apple.parse_products
    apple.parse_products = lambda html: prods
    try:
        live = AB.apple_live(fetch_page=lambda u: ("x", ""), fetch=lambda u: (body, ""), now=NOW)
    finally:
        apple.parse_products = orig
    assert live["availability"]["iPhone Duo 1TB"]["status"] == "UNKNOWN" and live["availability"]["iPhone Duo 256GB"]["status"] == "BUYABLE"
    assert "1TB" not in live["prices"] and live["bad_skus"] == ["iPhone Duo 1TB"]
    # --apply は古い 1TB の価格を残さず、機種ごとの確認日も（エラーがあるので）更新しない
    d = tmp_path / "2026-11-16"
    d.mkdir()
    (d / "research_iphone.json").write_text(json.dumps({"apple_official": {"checked_at": "2026-11-13", "prices_jpy": {"iPhone Duo": {"1TB": 469800}}}}), encoding="utf-8")
    orig_live = AB.apple_live
    AB.apple_live = lambda *a, **k: live
    try:
        AB.main(["--dir", str(d), "--apply"])
    finally:
        AB.apple_live = orig_live
    out = json.loads((d / "research_iphone.json").read_text(encoding="utf-8"))["apple_official"]
    assert "1TB" not in out["prices_jpy"]["iPhone Duo"] and out["checked_at"] == "2026-11-13" and "checked_at_by_model" not in out


def test_availability_status_without_part_evidence_is_not_trusted():
    base = {"status": "BUYABLE", "checked_at": "2026-11-16T20:00:00+09:00", "source": "s"}
    assert W.normalize_availability({"iPhone Duo 1TB": dict(base)}, RD)["iPhone Duo 1TB"]["status"] == "UNKNOWN"                 # parts なし
    assert W.normalize_availability({"iPhone Duo 1TB": dict(base, parts={"X": False})}, RD)["iPhone Duo 1TB"]["status"] == "UNKNOWN"   # 根拠と矛盾
    assert W.normalize_availability({"iPhone Duo 1TB": dict(base, parts={"X": True})}, RD)["iPhone Duo 1TB"]["status"] == "BUYABLE"
    un = dict(base, status="UNAVAILABLE", parts={"X": True})
    assert W.normalize_availability({"iPhone Duo 1TB": un}, RD)["iPhone Duo 1TB"]["status"] == "UNKNOWN"


def test_history_has_discovered_sku_excluded_from_events_through_update_history(tmp_path):
    h = tmp_path / "h.json"
    d13 = "2026-11-13 ページ記載: 更新日 2026-11-13"
    prev = W.build_iphone_comparison([_shop("パステック（PASTEC）", 500000, checked=d13), _shop("買取ルデヤ", 499000, checked=d13)], APPLE,
                                     research_date="2026-11-13", now=NOW, cfg=W.load_config(), registered={}, availability={})
    h.write_text(json.dumps(W.update_history(prev, h)), encoding="utf-8")
    cur = _comp([_shop("パステック（PASTEC）", 470000), _shop("買取ルデヤ", 469000)], registered={})
    W.update_history(cur, h)
    assert cur["events"] == []                                                          # 未登録（DISCOVERED）の SKU の変動は出さない
