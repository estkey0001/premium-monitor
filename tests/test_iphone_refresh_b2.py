# -*- coding: utf-8 -*-
"""段階 B2・B3: `python -m src.research.iphone_refresh`（週次の更新）。ネットワークは使わない。

守ること: dry-run は何も書かない／取得できた店・行だけ更新し、失敗した店の古い値は日付も進めない／急変した価格は採らない／
購入可否が BUYABLE でなければ BUY にしない／履歴・イベント（PRICE_DROP など）／通知は送らない。
"""
import json
from datetime import datetime, timedelta, timezone

from src.collectors import buyback_iphone_weekly as shops_mod
from src.research import iphone_refresh as R
from src.research import weekly_import as W

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 17, 17, 0, tzinfo=JST)
DATE = "2026-11-17"
OLD_FRESH = "2026-11-17 (取得日)。ページ記載: 更新日 2026-11-17"
OLD_STALE = "2026-11-13 (取得日)。ページ記載: 更新日 2026-11-13"


def _shop(name, price, *, cap="1TB", checked=OLD_STALE):
    row = {"model": "iPhone Duo", "storage": cap, "condition": "UNOPENED", "base_price": price, "color_adjustments": {}}
    return {"shop_name": name, "official_url": "https://example.com/", "price_page_url": "https://example.com/p",
            "checked_at": checked, "fetch_status": "ACTIVE", "skus": [row]}


def _research(prices=None, av=None):
    return {"apple_official": {"prices_jpy": {"iPhone Duo": prices or {"256GB": 364800, "512GB": 399800, "1TB": 469800, "2TB": 574800}},
                               "availability": av or {}}}


def _live(status="BUYABLE", prices=None, errors=None):
    prices = prices or {"256GB": 364800, "512GB": 399800, "1TB": 469800, "2TB": 574800}
    av = {f"iPhone Duo {c}": {"status": status, "parts": {"P": status == "BUYABLE"} if status != "UNKNOWN" else {"P": None},
                              "checked_at": "2026-11-17T16:00:00+09:00", "source": "https://www.apple.com/jp/shop/buyability-message"}
          for c in prices}
    return {"model": "iPhone Duo", "prices": prices, "availability": av, "bad_skus": [], "errors": errors or [],
            "checked_at": "2026-11-17T16:00:00+09:00"}


def _pastec(price, *, updated="2026-11-17"):
    return shops_mod.pastec_entry({"updated": updated, "rows": {("iPhone Duo", "1TB"): {"price": price, "reductions": {}, "colors_ok": True}}},
                                  DATE, ("iPhone Duo",))


def _rudeya(price):
    return shops_mod.rudeya_entry({"as_of": "2026-11-17 16:35", "rows": {("iPhone Duo", "1TB"): {"price": price}}}, DATE, ("iPhone Duo",))


def _fetcher(pastec=None, rudeya=None, errors=None):
    errors = errors or {}

    def f(key, *, models, now):
        entry = {"pastec": pastec, "rudeya": rudeya}[key]
        if key in errors or entry is None:
            return {"key": key, "shop_name": key, "ok": False, "entry": None, "rows": 0, "error": errors.get(key, "fetch_failed")}
        return {"key": key, "shop_name": entry["shop_name"], "ok": True, "entry": entry, "rows": 1, "error": None}
    return f


def _src(tmp_path, shops, research=None):
    d = tmp_path / "2026-11-16"
    d.mkdir()
    (d / "research_iphone.json").write_text(json.dumps(research or _research()), encoding="utf-8")
    (d / "iphone_exp_A.json").write_text(json.dumps(shops), encoding="utf-8")
    return d


def _run(tmp_path, shops, *, fetch, apple=None, research=None, skip_apple=False, history=None, old_comp=None):
    src = _src(tmp_path, shops, research)
    hp = tmp_path / "hist.json"
    if history is not None:
        hp.write_text(json.dumps(history), encoding="utf-8")
    return R.refresh(src, DATE, now=NOW, skip_apple=skip_apple, fetch_shop=fetch, apple_fn=apple or (lambda: _live()),
                     history_path=hp, old_comp=old_comp)


def _sku(state, name="iPhone Duo 1TB"):
    return next(s for s in state["comp"]["skus"] if s["sku"] == name)


OLD_SHOPS = [_shop("パステック（PASTEC）", 482000), _shop("買取ルデヤ", 481000)]


# ---- 成功 ----
def test_success_updates_both_shops_fresh_and_recalculates_profit(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(_pastec(483000), _rudeya(475000)))
    s = _sku(st)
    assert s["highest_executable"] == {"shop": "パステック（PASTEC）", "price": 483000}
    assert s["net_profit"] == 483000 - 469800 - 1800 and s["fresh_source_count"] == 2
    assert s["opportunity_status"] == "WAIT" and s["profit_status"] == "PROFITABLE"          # 黒字でも ROI 8% 未満は BUY でない
    ch = {(c["shop"], c["from"], c["to"]) for c in st["report"]["prices_changed"]}
    assert ("パステック（PASTEC）", 482000, 483000) in ch and ("買取ルデヤ", 481000, 475000) in ch
    assert "iphone_exp_live.json" in st["files"]


def test_same_price_is_unchanged_but_refetched(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(_pastec(482000), _rudeya(481000)))
    assert st["report"]["prices_changed"] == [] and len(st["report"]["rows_unchanged"]) == 2
    assert st["report"]["skus_refetched"] == ["iPhone Duo 1TB"]


# ---- 失敗・部分的な失敗 ----
def test_pastec_failure_keeps_old_row_untouched_and_not_fresh(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(None, _rudeya(475000), errors={"pastec": "robots_disallow"}))
    assert st["report"]["sources"]["pastec"] == {"attempted": True, "ok": False, "error": "robots_disallow", "rows": 0}
    old = next(sh for sh in st["comp"]["shops"] if sh["key"] == "pastec")
    assert old["checked_at"] == OLD_STALE and old["freshness"] == "STALE"                  # 日付を今日に進めない
    s = _sku(st)
    assert s["highest_executable"] is None or s["highest_executable"]["shop"] != "パステック（PASTEC）"   # 古い値は実行可能に使わない
    assert st["ok_keys"] == ["rudeya"]


def test_rudeya_failure_updates_only_pastec(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(_pastec(483000), None, errors={"rudeya": "unexpected"}))
    ru = next(sh for sh in st["comp"]["shops"] if sh["key"] == "rudeya")
    assert ru["freshness"] == "STALE" and ru["updated_on"] == "2026-11-13"
    pa = next(sh for sh in st["comp"]["shops"] if sh["key"] == "pastec")
    assert pa["freshness"] == "FRESH"


def test_all_failed_is_a_validation_problem_and_nothing_is_replaced(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(None, None), skip_apple=True)
    assert "live" not in " ".join(st["files"]) and R.validate(st)
    assert all(sh["freshness"] == "STALE" for sh in st["comp"]["shops"])


def test_apple_failure_leaves_old_values_and_never_buy(tmp_path):
    bad = lambda: {"model": "iPhone Duo", "prices": {}, "availability": {}, "bad_skus": [], "errors": ["apple_page_failed:timeout"], "checked_at": "x"}
    rich = [_shop("店A", 520000, checked=OLD_FRESH), _shop("店B", 519000, checked=OLD_FRESH)]
    st = _run(tmp_path, rich, fetch=_fetcher(None, None), apple=bad)
    assert st["report"]["sources"]["apple"]["ok"] is False
    assert _sku(st)["opportunity_status"] != "BUY"


# ---- 急変（誤取得の疑い） ----
def test_price_jump_is_not_adopted(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(_pastec(240000), _rudeya(481000)), skip_apple=True)
    assert st["report"]["sources"]["pastec"]["ok"] is False
    assert st["report"]["sources"]["pastec"]["error"].startswith("price_jump_needs_review")
    row = next(r for r in _sku(st)["rows"] if r["key"] == "pastec")
    assert row["base_price"] == 482000 and row["checked_at"] == OLD_STALE


def test_apple_price_jump_is_not_adopted(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(_pastec(482000), _rudeya(481000)),
              apple=lambda: _live(prices={"1TB": 900000}))
    assert st["report"]["sources"]["apple"]["error"].startswith("price_jump_needs_review")
    assert st["research"]["apple_official"]["prices_jpy"]["iPhone Duo"]["1TB"] == 469800


# ---- 鮮度 ----
def test_page_without_update_date_is_unknown_and_not_executable(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(_pastec(483000, updated=None), _rudeya(481000)), skip_apple=True)
    pa = next(sh for sh in st["comp"]["shops"] if sh["key"] == "pastec")
    assert pa["freshness"] == "UNKNOWN_FRESHNESS"
    assert _sku(st)["highest_executable"] is None or _sku(st)["highest_executable"]["shop"] != "パステック（PASTEC）"


# ---- 購入可否と BUY ----
def test_availability_controls_buy(tmp_path):
    rich = [_shop("店A", 520000, checked=OLD_FRESH), _shop("店B", 519000, checked=OLD_FRESH)]
    got = {}
    for name, status in (("a", "BUYABLE"), ("b", "UNKNOWN"), ("c", "UNAVAILABLE")):
        (tmp_path / name).mkdir()
        got[status] = _sku(_run(tmp_path / name, rich, fetch=_fetcher(None, None), apple=lambda st=status: _live(st)))["opportunity_status"]
    assert got == {"BUYABLE": "BUY", "UNKNOWN": "WATCH", "UNAVAILABLE": "WAIT"}


# ---- 履歴・イベント（B3） ----
def _hist(price, *, key="pastec", shop="パステック（PASTEC）", decision=None, net=None):
    return {"schema": 1, "snapshots": [{"date": "2026-11-16", "rows": [
        {"sku": "iPhone Duo 1TB", "identity": "REGISTERED", "key": key, "shop": shop, "price": price, "net": net,
         "checked_at": "2026-11-16", "condition": "UNOPENED", "freshness": "FRESH"}],
        "apple": {"iPhone Duo 1TB": {"price": 469800, "availability": "BUYABLE", "decision": decision}}}]}


def test_price_drop_rise_and_same_price_events(tmp_path):
    f = _fetcher(_pastec(482000), _rudeya(481000))
    drop = _run(tmp_path, OLD_SHOPS, fetch=f, skip_apple=True, history=_hist(492000))
    assert any(e["type"] == "PRICE_DROP" and e["from"] == 492000 and e["to"] == 482000 for e in drop["report"]["events"])
    (tmp_path / "r").mkdir()
    rise = _run(tmp_path / "r", OLD_SHOPS, fetch=f, skip_apple=True, history=_hist(470000))
    assert any(e["type"] == "BUYBACK_SURGE" for e in rise["report"]["events"])
    (tmp_path / "s").mkdir()
    same = _run(tmp_path / "s", OLD_SHOPS, fetch=f, skip_apple=True, history=_hist(482000))
    assert not any(e["type"] in ("PRICE_DROP", "BUYBACK_SURGE") for e in same["report"]["events"])
    assert same["report"]["notification_dry_run"]["sent"] == 0


def test_history_keeps_product_shop_price_condition_checked_at(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(_pastec(482000), _rudeya(481000)), skip_apple=True, history=_hist(492000))
    snaps = st["hist"]["snapshots"]
    assert [x["date"] for x in snaps] == ["2026-11-16", DATE]                          # 前日の履歴を残し、当日を足す
    row = next(r for r in snaps[-1]["rows"] if r["key"] == "pastec")
    assert row["price"] == 482000 and row["condition"] == "UNOPENED" and row["checked_at"] and row["freshness"] == "FRESH"
    assert next(r for r in snaps[0]["rows"] if r["key"] == "pastec")["price"] == 492000


def test_decision_events_wait_to_buy_and_back(tmp_path):
    rich = [_shop("店A", 520000, checked=OLD_FRESH), _shop("店B", 519000, checked=OLD_FRESH)]
    up = _run(tmp_path, rich, fetch=_fetcher(None, None), apple=lambda: _live("BUYABLE"), history=_hist(500000, key="a", shop="店A", decision="WAIT"))
    assert any(e["type"] == "WAIT_TO_BUY" and e["from"] == "WAIT" and e["to"] == "BUY" for e in up["report"]["events"])
    (tmp_path / "d").mkdir()
    down = _run(tmp_path / "d", rich, fetch=_fetcher(None, None), apple=lambda: _live("UNAVAILABLE"),
                history=_hist(500000, key="a", shop="店A", decision="BUY"))
    assert any(e["type"] == "BUY_TO_WAIT" for e in down["report"]["events"])


def test_profit_loss_events_detected():
    prev = [{"sku": "iPhone Duo 1TB", "identity": "REGISTERED", "key": "a", "shop": "A", "price": 480000, "net": 300}]
    cur = [{"sku": "iPhone Duo 1TB", "identity": "REGISTERED", "key": "a", "shop": "A", "price": 470000, "net": -9700}]
    assert "PROFIT_TO_LOSS" in {e["type"] for e in W.diff_snapshots(prev, cur)}
    assert "LOSS_TO_PROFIT" in {e["type"] for e in W.diff_snapshots(cur, prev)}
    cur2 = [{**cur[0], "key": "b", "shop": "B", "price": 471000}]
    assert "BEST_SHOP_CHANGE" in {e["type"] for e in W.diff_snapshots(prev, cur2)}


# ---- 書き込み ----
def test_dry_run_computation_writes_nothing_and_apply_writes_validated_files(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(_pastec(483000), _rudeya(475000)), skip_apple=True)
    assert not (tmp_path / "2026-11-17").exists() and not (tmp_path / "out").exists()      # refresh() は書かない
    assert R.validate(st) == []
    called = []
    target, out = tmp_path / DATE, tmp_path / "out"
    written = R.write_all(st, target, export_dir=out, build_page=lambda: called.append(1))
    assert called == [1] and "docs/iphone-buyback.html" in written
    comp = json.loads((out / "iphone_buyback_comparison.json").read_text(encoding="utf-8"))
    assert comp["research_date"] == DATE and json.loads((target / "iphone_exp_live.json").read_text(encoding="utf-8"))
    # 書いた調査フォルダは、そのまま week import できる形（別の店の元データは残る）
    assert (target / "research_iphone.json").exists() and (target / "iphone_exp_A.json").exists()
    assert json.loads((out / "iphone_buyback_history.json").read_text(encoding="utf-8"))["snapshots"][-1]["date"] == DATE


def test_summarize_has_required_dry_run_fields(tmp_path):
    st = _run(tmp_path, OLD_SHOPS, fetch=_fetcher(_pastec(483000), None, errors={"rudeya": "x"}), skip_apple=True)
    out = R.summarize(st, apply=False, problems=R.validate(st))
    for k in ("sources_attempted", "sources_succeeded", "sources_failed", "skus_updated", "rows_unchanged", "prices_changed",
              "profit_changed", "events", "public_files", "notification"):
        assert k in out
    assert out["mode"] == "DRY_RUN" and out["sources_failed"] == {"rudeya": "x"} and out["sources_succeeded"] == ["pastec"]
    assert all(p.startswith("(dry-run") for p in out["public_files"])


def test_strip_supports_all_input_shapes():
    e = {"shop_name": "パステック（PASTEC）"}
    o = {"shop_name": "買取ルデヤ"}
    assert R._strip([e, o], {"pastec"}) == [o]
    assert R._strip({"shops": [e, o], "x": 1}, {"pastec"}) == {"shops": [o], "x": 1}
    assert R._strip({"a": e, "b": o}, {"pastec"}) == {"b": o}


def test_previous_dir_picks_latest_not_after_date(tmp_path):
    for n in ("2026-11-13", "2026-11-16", "2026-11-20"):
        d = tmp_path / n
        d.mkdir()
        (d / "research_iphone.json").write_text("{}", encoding="utf-8")
        (d / "iphone_exp_A.json").write_text("[]", encoding="utf-8")
    assert R.previous_dir(tmp_path, "2026-11-17").name == "2026-11-16"
    assert R.previous_dir(tmp_path, "2026-11-12") is None
