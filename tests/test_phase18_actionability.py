"""Phase 18（今すぐ行動できるか）のテスト。

利益があるだけでは「今すぐ行動できる」にしない。通常販売は在庫ありを確認してから3時間以内、抽選・予約・先着は受付中
（公式の確認が7日以内・締切が分かる）、購入・申込のページが公式の具体的なページのときだけ。画面は判定し直さず、
行動できるときだけ「購入する」「抽選に申し込む」「予約する」のボタンを出す。各テストに否定の対照を付ける。
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=JST)
SONY = "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/"
RICOH = "https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid=S0001566&cat=002010"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


DC = _load("p18_dc", ROOT / "scripts" / "deploy_check.py")


def _ev(start_days=-1, end_days=1, *, kind="抽選販売", status="active", checked_hours=-1, url=RICOH, end=True):
    return {"product_code": "S0001566", "sale_method": kind, "status": status,
            "entry_start_at": (NOW + timedelta(days=start_days)).strftime("%Y-%m-%d %H:%M"),
            "entry_end_at": (NOW + timedelta(days=end_days)).strftime("%Y-%m-%d %H:%M") if end else "",
            "checked_at": (NOW + timedelta(hours=checked_hours)).strftime("%Y-%m-%d %H:%M"),
            "entry_form_url": url, "data_source": "auto_scraped"}


def _eval(**kw):
    from src.market import actionability as act
    base = dict(profitable=True, identity_ok=True, stock="IN_STOCK", stock_checked_at=NOW - timedelta(hours=1),
                buy_url=SONY, event=None, now=NOW)
    base.update(kw)
    return act.evaluate(**base)


# ── 正本の判定 ──────────────────────────────────────────────────────────

def test_profitable_in_stock_is_actionable():
    a = _eval()
    assert a.actionable and a.availability == "IN_STOCK" and a.cta_label == "購入する" and a.cta_url == SONY
    assert a.until_ms == int((NOW + timedelta(hours=2)).timestamp() * 1000)     # 確認から3時間まで


@pytest.mark.parametrize("kw,availability,reason", [
    ({"stock": "OUT_OF_STOCK"}, "OUT_OF_STOCK", "stock_out"),
    ({"stock": "UNKNOWN"}, "UNKNOWN", "stock_unknown"),
    ({"stock_checked_at": NOW - timedelta(hours=4)}, "STOCK_STALE", "availability_stale"),   # 7日以内でも3時間超
    ({"stock_checked_at": NOW - timedelta(days=3)}, "STOCK_STALE", "availability_stale"),
    ({"stock_checked_at": NOW + timedelta(hours=5)}, "UNKNOWN", "stock_unknown"),   # 未来の確認は信用しない
    ({"stock_checked_at": ""}, "UNKNOWN", "stock_unknown"),                         # 確認時刻が無い
    ({"sale_method": "discontinued"}, "SALE_ENDED", "sale_ended"),
])
def test_profitable_but_not_available_is_not_actionable(kw, availability, reason):
    a = _eval(**kw)
    assert not a.actionable and a.availability == availability and reason in a.reasons
    assert a.cta_label == "" and a.cta_url == "" and a.until_ms is None


def test_profit_negative_in_stock_is_not_actionable():
    a = _eval(profitable=False)
    assert not a.actionable and "not_profitable" in a.reasons and a.cta_url == ""


@pytest.mark.parametrize("url", ["", "https://www.apple.com/jp/shop/", "https://www.kaitorishouten-co.jp/x",
                                 "http://pur.store.sony.jp/x", "https://ricohimagingstore.com/Page/GR.aspx"])
def test_missing_or_generic_action_url_is_not_actionable(url):
    a = _eval(buy_url=url)
    assert not a.actionable and "missing_action_url" in a.reasons


def test_lottery_open_is_actionable_with_deadline():
    a = _eval(stock="LOTTERY", event=_ev(-1, 1))
    assert a.actionable and a.availability == "LOTTERY_OPEN" and a.cta_label == "抽選に申し込む"
    assert a.cta_url == RICOH and a.deadline.startswith("2026-10-10")
    assert a.until_ms == int((NOW + timedelta(days=1)).replace(second=0).timestamp() * 1000)   # 締切まで


@pytest.mark.parametrize("ev,availability,reason", [
    (_ev(-10, -3), "LOTTERY_CLOSED", "lottery_closed"),                         # 締切後
    (_ev(-1, 1, status="closed"), "LOTTERY_CLOSED", "lottery_closed"),          # ページで受付終了
    (_ev(1, 3), "LOTTERY_UPCOMING", "lottery_not_open"),                        # 受付前
    (_ev(-1, 1, end=False), "LOTTERY_UNKNOWN", "lottery_deadline_unknown"),     # 締切不明（OPEN と推測しない）
    (_ev(-1, 1, checked_hours=-24 * 10), "LOTTERY_UNKNOWN", "lottery_evidence_stale"),   # 確認が古い
    (_ev(-1, 1, url="https://example.com/x"), "LOTTERY_OPEN", "missing_action_url"),     # 公式でない申込ページ
])
def test_lottery_not_open_is_not_actionable(ev, availability, reason):
    a = _eval(stock="LOTTERY", event=ev)
    assert not a.actionable and a.availability == availability and reason in a.reasons and a.cta_url == ""


def test_lottery_without_event_is_not_actionable():
    a = _eval(stock="LOTTERY", event=None, sale_method="lottery")
    assert not a.actionable and a.availability == "LOTTERY_UNKNOWN"


def test_winner_purchase_period_is_not_actionable():
    ev = dict(_ev(-10, -5), purchase_start=(NOW - timedelta(days=1)).isoformat(),
              purchase_end=(NOW + timedelta(days=2)).isoformat())
    ev["status"] = "active"
    a = _eval(stock="LOTTERY", event=ev)
    assert not a.actionable and a.availability == "PURCHASE_PERIOD_OPEN" and "winner_only_period" in a.reasons


@pytest.mark.parametrize("kind,open_type,cta", [("予約", "PREORDER_OPEN", "予約する"),
                                               ("先着販売", "FIRST_COME_OPEN", "購入する")])
def test_preorder_and_first_come(kind, open_type, cta):
    a = _eval(stock="RESERVATION", event=_ev(-1, 1, kind=kind))
    assert a.actionable and a.availability == open_type and a.cta_label == cta
    closed = _eval(stock="RESERVATION", event=_ev(-5, -1, kind=kind))
    assert not closed.actionable and closed.availability.endswith("CLOSED")


def test_event_link_by_product_code_or_id_not_name():
    from src.market import actionability as act
    evs = [dict(_ev(), product_name="RICOH GR IV HDF"), {"product_name": "RICOH GR IV HDF", "status": "active"}]
    assert act.find_event(evs, "prod_gr4_hdf", "S0001566")["product_code"] == "S0001566"
    assert act.find_event([{"product_name": "RICOH GR IV HDF", "status": "active"}], "prod_gr4_hdf", "S0001566") is None
    assert act.find_event([dict(_ev(), product_code="S0001551")], "prod_gr4_hdf", "S0001566") is None   # 別の版
    assert act.find_event([dict(_ev(), product_code="", product_id="prod_gr4_hdf")], "prod_gr4_hdf", "") is not None
    assert act.find_event([dict(_ev(), reference_only=True)], "prod_gr4_hdf", "S0001566") is None


def test_real_hdf_event_is_closed():
    """本番の抽選の記録（data/lottery_events.csv）で、GR IV HDF は受付終了（2026-09-28 締切）。"""
    from src.market import actionability as act
    evs = list(csv.DictReader((ROOT / "data" / "lottery_events.csv").open(encoding="utf-8")))
    ev = act.find_event(evs, "prod_gr4_hdf", "S0001566")
    assert ev is not None and ev["product_code"] == "S0001566"
    a = _eval(stock="LOTTERY", event=ev)
    assert not a.actionable and a.availability == "LOTTERY_CLOSED" and a.deadline.startswith("2026-09-28")


# ── 案件・診断・画面 ──────────────────────────────────────────────────────

def _deal(pid="prod_ps5_pro", **kw):
    from src.content.ui import opportunity as opp
    d = {"product_id": pid, "title": "PlayStation 5 Pro", "genre": "game_console", "brand": "Sony",
         "model": "CFI-7100B01", "official_price": 137980, "sell_price": 195200, "sell_shop": "買取商店",
         "sell_checked_at": (NOW - timedelta(hours=2)).isoformat(), "official_checked_at": "2026-10-08",
         "msrp_evidence": "VERIFIED_CURRENT", "sell_identity_verified": True, "purchase_shipping": 550,
         "purchase_shipping_status": "PAID", "condition": "new_unopened", "official_url": SONY,
         "sell_url": "https://www.kaitorishouten-co.jp/products/detail/1", "user_level": "beginner_watch",
         "stock_status": "入荷待ち", "stock_checked_at": (NOW - timedelta(hours=1)).isoformat(), "sale_method": "normal"}
    d.update(kw)
    v0 = opp.from_deal(d)
    d["net_profit"] = d["sell_price"] - d["official_price"] - sum(a for _l, a in v0.cost_lines)
    return d


def _set(deals, events=None):
    from src.content.ui import opportunity as opp
    return opp.build(deals=deals, routes=[], product_genres={}, now=NOW, availability_events=events)


def test_ps5_pro_profit_kept_but_not_actionable():
    s = _set([_deal()])
    v = s.eligible[0]
    assert v.net_profit > 0 and v.eligible and not v.actionable
    assert v.action.availability == "OUT_OF_STOCK" and "stock_out" in v.action.reasons
    # 在庫ありになれば行動できる（構造の確認）
    s2 = _set([_deal(stock_status="カートに入れる")])
    assert s2.eligible[0].actionable and s2.eligible[0].action.cta_url == SONY


def test_hdf_profit_kept_lottery_closed_and_reopens():
    hdf = _deal("prod_gr4_hdf", title="RICOH GR IV HDF", genre="camera", model="S0001566", official_price=222000,
                sell_price=240000, official_url=RICOH, stock_status="SOLD OUT", sale_method="lottery",
                purchase_shipping=0, purchase_shipping_status="FREE_VERIFIED")
    closed = _set([hdf], [_ev(-14, -11, status="closed")])
    v = closed.eligible[0]
    assert v.eligible and not v.actionable and v.action.availability == "LOTTERY_CLOSED"
    reopened = _set([hdf], [_ev(-14, -11, status="closed"), _ev(-1, 2)])
    assert reopened.eligible[0].actionable and reopened.eligible[0].action.cta_label == "抽選に申し込む"


def test_diagnostics_actionability_and_transitions():
    from src.market import opportunity_diagnostics as od
    s = _set([_deal(), _deal("prod_b", stock_status="カートに入れる")])
    d = od.build(products=[], msrp_evidence={}, official_meta={}, observations=[], opportunity_set=s,
                 home_count=2, list_count=2, sold_exports=None, now=NOW, prev_actionable=[])
    ac = d["actionability"]
    assert d["actionable"]["count"] == 1 and ac["actionable"] == 1 and ac["blocked_by_stock"] == 1
    assert ac["newly_actionable"] == ["prod_b"]
    # 同じ状態では毎回出さない（前回も行動できた）・前回が無いときは基準日（出さない）
    d2 = od.build(products=[], msrp_evidence={}, official_meta={}, observations=[], opportunity_set=s,
                  home_count=2, list_count=2, sold_exports=None, now=NOW,
                  prev_actionable=[{"product_id": "prod_b"}])
    assert d2["actionability"]["newly_actionable"] == []
    d3 = od.build(products=[], msrp_evidence={}, official_meta={}, observations=[], opportunity_set=s,
                  home_count=2, list_count=2, sold_exports=None, now=NOW, prev_actionable=None)
    assert d3["actionability"]["newly_actionable"] == []


def test_list_cta_only_when_actionable():
    from src.content.ui import opportunities_page as op
    s = _set([_deal(), _deal("prod_b", stock_status="カートに入れる")])
    by = {v.product_id: v for v in s.eligible}
    out_card = op._card(by["prod_ps5_pro"], 0)
    in_card = op._card(by["prod_b"], 1)
    assert 'data-actionable="0"' in out_card and "opportunity_action" not in out_card and "在庫切れ" in out_card
    assert 'data-actionable="1"' in in_card and "購入する" in in_card and SONY in in_card
    assert 'data-nu-pd-stale-hide="1"' in in_card and "data-nu-pd-until" in in_card     # 期限を過ぎたら消す


def test_list_shows_closed_lottery_with_deadline():
    from src.content.ui import opportunities_page as op
    hdf = _deal("prod_gr4_hdf", title="RICOH GR IV HDF", model="S0001566", official_url=RICOH,
                stock_status="SOLD OUT", sale_method="lottery", purchase_shipping=0,
                purchase_shipping_status="FREE_VERIFIED", official_price=222000, sell_price=240000)
    v = _set([hdf], [_ev(-14, -11, status="closed")]).eligible[0]
    card = op._card(v, 0)
    assert "抽選終了" in card and "（終了）" in card and "抽選に申し込む" not in card and "+¥" in card


def test_product_detail_action_item():
    from src.content.ui import product_page
    s = _set([_deal()])
    lbl, val, sub, extra, _cls = product_page._action_item(s.eligible[0])
    assert (lbl, val) == ("今すぐ行動", "できない") and "在庫切れ" in sub and extra == ""
    s2 = _set([_deal(stock_status="カートに入れる")])
    lbl, val, sub, extra, _cls = product_page._action_item(s2.eligible[0])
    assert val[0] == "できる" and "購入する" in extra and 'data-nu-pd-stale-hide="1"' in extra


@pytest.mark.parametrize("n", [0, 1, 10, 50])
def test_scale_opportunities(n):
    from src.content.ui import opportunities_page as op
    deals = [_deal(f"prod_{i}", stock_status="カートに入れる" if i % 2 else "入荷待ち") for i in range(n)]
    s = _set(deals)
    html = "".join(op._card(v, i) for i, v in enumerate(s.eligible))
    assert html.count('data-actionable="1"') == sum(1 for v in s.eligible if v.actionable)
    assert "NaN" not in html and "undefined" not in html


@pytest.mark.parametrize("n", [0, 20, 100])
def test_scale_events(n):
    from src.market import actionability as act
    evs = [dict(_ev(-1, 1), product_code=f"C{i}") for i in range(n)]
    assert (act.find_event(evs, "x", "C5") is not None) is (n > 5)


def test_home_actionable_count_uses_untils():
    from src.content.ui import pages
    s = _set([_deal(), _deal("prod_b", stock_status="カートに入れる")])
    line = pages._actionable_line(SimpleNamespace(opportunity_set=s))
    assert "1件" in line and "data-nu-act-untils=" in line


def test_deploy_check_actionability_ok_and_mutation(monkeypatch):
    assert DC._check_phase18_actionability("")[0]["level"] == "ok"
    from src.market import actionability as act
    monkeypatch.setattr(act, "ACTIONABLE_TYPES", act.ACTIONABLE_TYPES | {"OUT_OF_STOCK", "LOTTERY_CLOSED"})
    monkeypatch.setattr(act, "CTA_LABELS", dict(act.CTA_LABELS, OUT_OF_STOCK="購入する"))
    # 在庫切れ → 行動できる、の誤りを入れても、理由（stock_out）があるので行動できないまま（二重の守り）
    assert not _eval(stock="OUT_OF_STOCK").actionable


# ── レビュー・監査の指摘への対応 ─────────────────────────────────────────────

def test_status_conflict_is_not_open():
    """ページに受付終了とあるのに日付では受付中（収集側の status_conflict）は受付中にしない（H）。"""
    a = _eval(stock="LOTTERY", event=dict(_ev(-1, 1), status_conflict="true"))
    assert not a.actionable and "lottery_status_conflict" in a.reasons
    a = _eval(stock="LOTTERY", event=dict(_ev(-1, 1), status="受付終了"))
    assert not a.actionable and a.availability == "LOTTERY_CLOSED"


def test_missing_start_is_not_open():
    """開始が分からず締切だけ未来の行は受付中にしない（受付前の可能性。H）。"""
    a = _eval(stock="LOTTERY", event=dict(_ev(-1, 1), entry_start_at=""))
    assert not a.actionable and a.availability == "LOTTERY_UNKNOWN"


def test_date_only_start_is_not_open_on_that_day():
    """時刻の無い開始日の当日は、まだ受付中と言わない（その日の中の時刻を推測しない。M）。"""
    ev = dict(_ev(), entry_start_at=NOW.strftime("%Y-%m-%d"), entry_end_at=(NOW + timedelta(days=3)).strftime("%Y-%m-%d"))
    a = _eval(stock="LOTTERY", event=ev)
    assert not a.actionable and a.availability == "LOTTERY_UPCOMING"
    a2 = _eval(stock="LOTTERY", event=dict(ev, entry_start_at=(NOW - timedelta(days=2)).strftime("%Y-%m-%d")))
    assert a2.actionable and len(a2.deadline) == 10                 # 締切は日付のまま（時刻を作らない）


@pytest.mark.parametrize("url,ok", [
    (SONY, True), ("https://www.apple.com/jp/shop/buy-iphone/iphone-17", True),
    ("https://store.canon.jp/online/g/g6536C001/", True), ("https://nij.nikon.com/shop/g/g4960759909947/", True),
    ("https://mall-jp.fujifilm.com/shop/g/g16941878/", True),
    ("https://store-jp.nintendo.com/item/hardware-accessory/VM_BEE_S_KB6CA", True), (RICOH, True),
    ("https://ricohimagingstore.com/Form/Product/ProductList.aspx?shop=0&cat=002010", False),   # 一覧
    ("https://www.apple.com/jp/", False), ("https://www.apple.com/jp/iphone/", False),          # トップ・紹介
    ("https://www.apple.com/jp/shop/?a=1", False), ("https://ricohimagingstore.com/page/gr.aspx", False),
    ("https://store-jp.nintendo.com/list/hardware/switch2.html", False),
    ("https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0", False),           # 商品の指定なし
])
def test_action_page_allowlist(url, ok):
    from src.market.actionability import _official_url
    assert _official_url(url) is ok
    assert _eval(buy_url=url).actionable is ok


def test_lottery_uses_entry_form_only():
    """申込の URL が無ければ、商品・一覧のページに切り替えず行動できないにする（M）。"""
    ev = dict(_ev(-1, 1), entry_form_url="", url=RICOH)
    a = _eval(stock="LOTTERY", event=ev)
    assert not a.actionable and "missing_action_url" in a.reasons


@pytest.mark.parametrize("stock,days,availability", [
    ("OUT_OF_STOCK", 20, "UNKNOWN"), ("IN_STOCK", 20, "UNKNOWN"), ("OUT_OF_STOCK", 2, "OUT_OF_STOCK"),
    ("IN_STOCK", 2, "STOCK_STALE")])
def test_seven_day_rule_for_stock_display(stock, days, availability):
    """7日を過ぎた在庫の表示は在庫未確認（Phase 15 の規則。レビュー M1）。"""
    a = _eval(stock=stock, stock_checked_at=NOW - timedelta(days=days))
    assert a.availability == availability and not a.actionable


def test_event_does_not_override_direct_in_stock():
    """通常販売で在庫ありのとき、結び付いた過去の抽選で「抽選終了」にしない（レビュー M2・監査 L-3）。"""
    a = _eval(event=_ev(-10, -5, status="closed"))
    assert a.availability == "IN_STOCK" and a.actionable
    unknown_kind = dict(_ev(-1, 1), sale_method="soldout")
    a = _eval(stock="LOTTERY", event=unknown_kind)
    assert not a.actionable and a.availability == "LOTTERY_UNKNOWN"


def test_lottery_until_is_capped_by_evidence_age():
    """申込のボタンの期限は締切か、確認から7日の早いほう（監査 L-2）。"""
    ev = _ev(-1, 30, checked_hours=-24 * 6)
    a = _eval(stock="LOTTERY", event=ev)
    checked = datetime.strptime(ev["checked_at"], "%Y-%m-%d %H:%M").replace(tzinfo=JST)
    assert a.actionable and a.until_ms == int((checked + timedelta(days=7)).timestamp() * 1000)


def test_future_stock_check_beyond_tolerance_is_unknown():
    a = _eval(stock_checked_at=NOW + timedelta(minutes=30))
    assert not a.actionable
    ok = _eval(stock_checked_at=NOW + timedelta(minutes=2))      # 時計のずれ（5分まで）
    assert ok.actionable and ok.until_ms == int((NOW + timedelta(hours=3)).timestamp() * 1000)


def test_texts_fall_back_after_expiry():
    """期限を過ぎたら「できる」「購入可能」を落とす印が、商品詳細・一覧の詳細の文言にもある（M）。"""
    from src.content.ui import opportunities_page as op
    from src.content.ui import product_page
    v = _set([_deal(stock_status="カートに入れる")]).eligible[0]
    _l, val, sub, _x, _c = product_page._action_item(v)
    assert isinstance(val, tuple) and 'data-nu-pd-stale-text="できない"' in val[1]
    assert isinstance(sub, tuple) and "data-nu-pd-until" in sub[1]
    detail = op._detail(v)
    assert 'data-nu-pd-stale-text="できない・更新待ち"' in detail


def test_deploy_check_detects_mutation(monkeypatch):
    from src.market import actionability as act
    monkeypatch.setattr(act, "_official_url", lambda url: True)          # 一般のページ → 公式の購入ページ
    assert DC._check_phase18_actionability("")[0]["level"] == "error"


def test_deploy_check_detects_cta_on_non_actionable_row():
    html = ('<section data-nu-page="opportunities"><table><tbody>'
            '<tr class="nu-orow" data-actionable="0"><td><a data-track="opportunity_action">購入する</a></td></tr>'
            '</tbody></table></section><section data-nu-page="home"></section>')
    assert DC._check_phase18_actionability(html)[0]["level"] == "error"


def test_newest_event_wins_and_english_preorder():
    """同じ商品の情報は確認の新しい行を使う（新しい行が受付終了なら終了。レビュー L-a）。英語の予約も予約（L-c）。"""
    from src.market import actionability as act
    old_open = dict(_ev(-1, 1), checked_at=(NOW - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"))
    new_closed = dict(_ev(-1, 1, status="closed"), checked_at=(NOW - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"))
    assert act.find_event([old_open, new_closed], "x", "S0001566")["status"] == "closed"
    a = _eval(stock="UNKNOWN", sale_method="preorder", event=_ev(-1, 1, kind="予約"))
    assert a.actionable and a.availability == "PREORDER_OPEN"
    assert act.is_date_only("2026-10-9") and not act.is_date_only("2026-10-09 10:00")


def test_date_only_deadline_day_is_not_open():
    """時刻の無い締切の当日は、締切を過ぎたかもしれないので受付中と言わない（診断にも行動できると記録しない。監査 M-a）。"""
    ev = dict(_ev(), entry_start_at=(NOW - timedelta(days=4)).strftime("%Y-%m-%d"), entry_end_at=NOW.strftime("%Y-%m-%d"))
    a = _eval(stock="LOTTERY", event=ev)
    assert not a.actionable and a.until_ms is None and a.cta_label == ""
    nxt = dict(ev, entry_end_at=(NOW + timedelta(days=1)).strftime("%Y-%m-%d"))
    assert _eval(stock="LOTTERY", event=nxt).actionable                  # 締切の前日までは受付中


def test_unparseable_start_is_unknown():
    a = _eval(stock="LOTTERY", event=dict(_ev(-1, 1), entry_start_at="2026/10/05 10:00ごろ"))
    assert not a.actionable and a.availability == "LOTTERY_UNKNOWN"


def test_expired_until_is_never_actionable(monkeypatch):
    """期限がすでに過ぎている判定は行動できない（生成の判定と画面を食い違わせない）。"""
    from src.market import actionability as act
    monkeypatch.setattr(act, "STOCK_FRESH_SECONDS", {"official_store": 0}, raising=False)
    from src.market import stock_state as ss
    monkeypatch.setitem(ss.STOCK_FRESH_SECONDS, "official_store", 1)
    a = _eval(stock_checked_at=NOW - timedelta(seconds=1))
    assert not a.actionable
