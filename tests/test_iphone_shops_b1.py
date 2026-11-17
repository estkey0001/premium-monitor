# -*- coding: utf-8 -*-
"""段階 B1: PASTEC・ルデヤの決定論的取得（パーサーと店エントリ）。ネットワークは使わない。"""
from datetime import datetime

from src.collectors import buyback_iphone_weekly as w
from src.research import weekly_import as wi

NOW = datetime(2026, 11, 17, 17, 0, tzinfo=w.JST)


def _html(lines):
    return "<html><body>" + "".join(f"<p>{x}</p>" for x in lines) + "</body></html>"


PASTEC_LINES = [
    "買取価格更新日：2026/11/17",
    "iPhoneDuo", "iPhoneDuo 256GB", "未開封品買取価格", "358,000円", "中古買取価格", "284,000円〜227,500円", "郵送買取申込", "買取価格詳細",
    "iPhoneDuo 1TB", "未開封品買取価格", "483,000円", "中古買取価格", "360,000円〜287,000円", "郵送買取申込", "買取価格詳細",
    "iPhoneDuo 2TB", "未開封品買取価格", "581,000円", "中古買取価格", "442,500円〜351,000円", "郵送買取申込", "買取価格詳細",
    "iPhone18 Pro", "iPhone18 Pro 256GB", "グレイシャー-1,500(開封済・未開封)", "シルバー-4,000(開封済・未開封)",
    "未開封品買取価格", "206,500円", "中古買取価格", "164,000円〜132,500円", "買取価格詳細",
]
RUDEYA_LINES = [
    "2026年11月17日 16時35分現在の買取価格です。", "掲載している iPhone Duo は、未開封・SIMフリーの新品の買取価格です。",
    "iPhone Duo", "iPhone Duoの全商品の買取価格を見る ›", "容量", "買取価格（色によって違います）",
    "256GB", "360,000〜360,500円", "512GB", "402,000円", "1TB", "475,000円", "2TB", "580,000円",
    "買取の条件",
]


def test_pastec_unopened_price_only_not_used_price():
    p = w.parse_pastec(_html(PASTEC_LINES))
    assert p["updated"] == "2026-11-17"
    assert p["rows"][("iPhone Duo", "1TB")]["price"] == 483000          # 中古の範囲（360,000〜）を読まない
    assert p["rows"][("iPhone Duo", "2TB")]["price"] == 581000
    assert ("iPhone Duo", "512GB") not in p["rows"]                      # ページに無い容量は返さない


def test_pastec_color_reduction_applies_to_unopened():
    r = w.parse_pastec(_html(PASTEC_LINES))["rows"][("iPhone 18 Pro", "256GB")]
    assert r["reductions"] == {"グレイシャー": 1500, "シルバー": 4000} and r["colors_ok"]
    e = w.pastec_entry(w.parse_pastec(_html(PASTEC_LINES)), "2026-11-17", ("iPhone 18 Pro",))
    assert e["prices"][0]["executable_price"] == {"no_reduction": 206500, "max_reduction_color": 202500}


def test_pastec_unparsable_color_line_is_not_executable():
    lines = ["買取価格更新日：2026/11/17", "iPhoneDuo 1TB", "色によって減額あり", "未開封品買取価格", "483,000円", "買取価格詳細"]
    p = w.parse_pastec(_html(lines))
    assert p["rows"][("iPhone Duo", "1TB")]["colors_ok"] is False
    e = w.pastec_entry(p, "2026-11-17", ("iPhone Duo",))
    sh = wi.normalize_iphone_shops([e], "2026-11-17")[0]
    assert sh["rows"][0]["executable_price"] is None                     # 実行可能価格にしない


def test_pastec_row_without_price_is_dropped():
    p = w.parse_pastec(_html(["買取価格更新日：2026/11/17", "iPhoneDuo 1TB", "買取価格詳細", "iPhoneDuo 2TB", "未開封品買取価格", "581,000円"]))
    assert list(p["rows"]) == [("iPhone Duo", "2TB")]


def test_pastec_no_update_date_is_unknown_freshness_not_fetch_date():
    lines = [x for x in PASTEC_LINES if "更新日" not in x]
    e = w.pastec_entry(w.parse_pastec(_html(lines)), "2026-11-17", ("iPhone Duo",))
    assert "記載なし" in e["checked_at"]
    sh = wi.normalize_iphone_shops([e], "2026-11-17")[0]
    assert sh["freshness"] == "UNKNOWN_FRESHNESS" and sh["updated_on"] is None


def test_rudeya_single_price_and_range():
    p = w.parse_rudeya(_html(RUDEYA_LINES))
    assert p["as_of"] == "2026-11-17 16:35"
    assert p["rows"][("iPhone Duo", "1TB")] == {"price": 475000}
    assert p["rows"][("iPhone Duo", "256GB")] == {"range": (360000, 360500)}
    e = w.rudeya_entry(p, "2026-11-17", ("iPhone Duo",))
    sh = wi.normalize_iphone_shops([e], "2026-11-17")[0]
    rows = {r["sku"]: r for r in sh["rows"]}
    assert rows["iPhone Duo 256GB"]["basis"] == "range_only" and rows["iPhone Duo 256GB"]["executable_price"] is None
    assert rows["iPhone Duo 1TB"]["executable_price"] == 475000 and rows["iPhone Duo 1TB"]["condition"] == "UNOPENED"
    assert sh["freshness"] == "FRESH" and sh["updated_on"] == "2026-11-17"


def test_models_other_than_requested_are_not_returned():
    e = w.pastec_entry(w.parse_pastec(_html(PASTEC_LINES)), "2026-11-17", ("iPhone Duo",))
    assert {r["sku"] for r in e["prices"]} == {"iPhone Duo 256GB", "iPhone Duo 1TB", "iPhone Duo 2TB"}


def test_unknown_model_names_are_ignored():
    p = w.parse_pastec(_html(["買取価格更新日：2026/11/17", "iPhone17 Pro 256GB", "未開封品買取価格", "172,000円"]))
    assert p["rows"] == {}


def test_fetch_failure_returns_no_entry_and_never_raises():
    r = w.fetch_shop("pastec", fetch=lambda u: (None, "robots_disallow"), now=NOW)
    assert r["ok"] is False and r["entry"] is None and r["error"] == "robots_disallow"
    r = w.fetch_shop("rudeya", fetch=lambda u: (None, ""), now=NOW)
    assert r["ok"] is False and r["error"] == "fetch_failed"


def test_fetch_layout_change_is_failure_not_old_value():
    r = w.fetch_shop("rudeya", fetch=lambda u: (_html(["まったく違うページ"]), ""), now=NOW)
    assert r["ok"] is False and r["error"] == "no_rows_parsed" and r["entry"] is None


def test_fetch_success_reports_row_count_and_uses_given_fetcher():
    seen = []
    r = w.fetch_shop("pastec", fetch=lambda u: (seen.append(u) or _html(PASTEC_LINES), ""), now=NOW)
    assert r["ok"] and r["rows"] == 3 and seen == [w.PASTEC_URL]
    r = w.fetch_shop("rudeya", fetch=lambda u: (_html(RUDEYA_LINES), ""), now=NOW)
    assert r["ok"] and r["rows"] == 4 and r["entry"]["shop_name"] == w.SHOP_RUDEYA


def test_shop_keys_match_weekly_import_shop_keys():
    assert wi.shop_key(w.SHOP_PASTEC) == "pastec" and wi.shop_key(w.SHOP_RUDEYA) == "rudeya"


# ---- 監査・レビューの指摘への回帰 ----
def test_pastec_reduction_of_unknown_scope_or_after_price_is_not_executable():
    a = w.parse_pastec(_html(["買取価格更新日：2026/11/17", "iPhoneDuo 1TB", "ブルー-3,000円(全商品)", "未開封品買取価格", "483,000円", "買取価格詳細"]))
    assert a["rows"][("iPhone Duo", "1TB")]["colors_ok"] is False            # 何に効く減額か分からない
    b = w.parse_pastec(_html(["買取価格更新日：2026/11/17", "iPhoneDuo 1TB", "未開封品買取価格", "483,000円", "ブルー-3,000(未開封)", "買取価格詳細"]))
    assert b["rows"][("iPhone Duo", "1TB")]["colors_ok"] is False            # 価格の後ろの減額を読み落とさない
    c = w.parse_pastec(_html(["買取価格更新日：2026/11/17", "iPhoneDuo 1TB", "ブルー-3,000(開封済)", "未開封品買取価格", "483,000円", "買取価格詳細"]))
    assert c["rows"][("iPhone Duo", "1TB")]["colors_ok"] is True and c["rows"][("iPhone Duo", "1TB")]["reductions"] == {}


def test_pastec_block_without_price_does_not_borrow_next_block_price():
    p = w.parse_pastec(_html(["買取価格更新日：2026/11/17", "iPhoneDuo 1TB", "iPad Pro 256GB", "未開封品買取価格", "99,000円", "買取価格詳細"]))
    assert ("iPhone Duo", "1TB") not in p["rows"]


def test_rudeya_requires_unopened_statement_ignores_used_table_and_first_wins():
    no_stmt = [x for x in RUDEYA_LINES if "新品の買取価格" not in x]
    assert w.parse_rudeya(_html(no_stmt))["rows"] == {}
    dup = RUDEYA_LINES[:-1] + ["iPhone Duo", "iPhone Duoの全商品の買取価格を見る ›", "容量", "買取価格（色によって違います）", "1TB", "300,000円", "買取の条件"]
    assert w.parse_rudeya(_html(dup))["rows"][("iPhone Duo", "1TB")] == {"price": 475000}
    used = RUDEYA_LINES[:-1] + ["iPhone Duoの全商品の買取価格を見る ›", "容量", "買取価格（中古）", "2TB", "100,000円", "買取の条件"]
    assert w.parse_rudeya(_html(used))["rows"][("iPhone Duo", "2TB")] == {"price": 580000}
