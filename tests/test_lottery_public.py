"""抽選の公開の出口（src/tcg/lottery/public.py）と、公開 JSON・公開ページ・deploy-check #898 の漏れの検出。"""
import json
from datetime import datetime
from pathlib import Path

from src.tcg.lottery.public import PRIVATE_FREE_TEXT, leaked_fields, public_event, public_events
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parents[1]
SECRET = "告知より: 「プレイヤーズクラブ：本人認証済み枠」の方は"
EV = {"lottery_id": "lot-x", "tcg": "POKEMON", "product_name": "拡張パック「テスト」", "retailer": "POKEMON_CENTER_ONLINE",
      "retailer_name": "ポケモンセンターオンライン", "status": "OPEN", "channel": "ONLINE",
      "application_start": "2026-11-25T10:00:00+09:00", "application_end": "2026-11-30T23:59:00+09:00",
      "source_url": "https://www.pokemon-card.com/info/1.html", "source_urls": ["https://www.pokemon-card.com/info/1.html"],
      "source_type": "MANUAL_VERIFIED", "verified": True, "membership_required": True,
      "eligibility_text": SECRET, "payment_method_requirement": "本人認証済み枠: クレジットカード決済",
      "price_text": "お一人様 1BOX：5,760円（税込）", "shipping_period": "12月10日（木）～12月25日（金）発送予定",
      "retail_price": 5760, "price_unit": "BOX",
      "conditions": {"membership_required": {"value": True, "type": "プレイヤーズクラブ", "quote": SECRET},
                     "other_conditions": [SECRET]}}


def test_public_event_drops_free_text_and_quotes_but_keeps_values():
    p = public_event(EV)
    assert all(p[k] is None for k in PRIVATE_FREE_TEXT)
    assert p["conditions"] == {"membership_required": {"value": True, "type": "プレイヤーズクラブ"}}
    assert p["membership_required"] is True and p["source_url"] == EV["source_url"]
    assert (p["retail_price"], p["price_unit"]) == (5760, "BOX")        # 金額は値として残す
    assert leaked_fields(p) == [] and set(leaked_fields(EV)) == {
        "eligibility_text", "payment_method_requirement", "price_text", "shipping_period",
        "conditions.other_conditions", "conditions.membership_required.quote"}
    assert EV["eligibility_text"] == SECRET                              # 元の記録は変えない
    assert public_events([EV, None, "x"]) == [p]


def test_collect_script_writes_lotteries_only_through_the_public_exit():
    src = (ROOT / "scripts" / "collect_tcg_events.py").read_text(encoding="utf-8")
    assert '"items": public_events(lottery["lotteries"])' in src
    assert '"lotteries": public_events(lottery["lotteries"])' in src
    assert 'lottery["lotteries"],' not in src.replace('public_events(lottery["lotteries"]),', "")


def test_rendered_pages_do_not_contain_free_text_even_from_an_old_export():
    from src.content.tcg_hub_page import render_pages_from_json
    lot = {"generated_at": "2026-11-26T20:00:00+09:00", "items": [EV], "coverage": {}, "announcements": []}
    pages = render_pages_from_json(lot, {"products": []}, {}, now=datetime(2026, 11, 26, 20, 0, tzinfo=JST))
    for html in pages.values():
        assert SECRET not in html and "クレジットカード決済" not in html and "発送予定" not in html


def test_deploy_check_898_detects_a_leak(tmp_path, monkeypatch):
    import scripts.deploy_check as dc
    (tmp_path / "exports" / "tcg").mkdir(parents=True)
    (tmp_path / "exports" / "tcg" / "lotteries.json").write_text(json.dumps({"items": [EV]}), encoding="utf-8")
    monkeypatch.setattr(dc, "PROJECT_ROOT", tmp_path)
    [r] = dc._check_tcg_lottery_public_text()
    assert r["level"] == "error" and "lot-x" in r["message"]
    (tmp_path / "exports" / "tcg" / "lotteries.json").write_text(json.dumps({"items": [public_event(EV)]}), encoding="utf-8")
    [r] = dc._check_tcg_lottery_public_text()
    assert r["level"] == "ok"


def test_manual_ledger_eligibility_becomes_structured_values_only():
    from src.tcg.lottery.manual import _manual_conditions
    c = _manual_conditions("三洋堂サイト会員登録必須（8桁会員番号）。1人1回。購入期間内に来店しないと当選無効。")
    assert c["membership_required"]["value"] is True and all("quote" not in v for v in c.values())


def test_premium_alert_is_labelled_as_an_estimate_and_never_says_buy_now():
    from src.tcg.alerts import build_premium_message
    msg = build_premium_message({"product_name": "テストBOX", "status": "AVAILABLE_NOW",
                                 "premium": {"premium_percent": 25.0, "premium_yen": 1500, "retail_price": 6000,
                                             "market_median": 7500, "sealed_sample_count": 4, "window_days": 14}})
    assert "想定" in msg and "成約の中央値（4件・直近14日）" in msg
    assert "現在購入可能" not in msg and "YES" not in msg


def test_lp_lottery_view_also_goes_through_the_public_exit():
    from src.content.ui import lottery_view as lv
    from src.content.ui import runtime as rt
    vm = rt.tcg_vm(EV, 0)
    v = lv._from_tcg(vm, EV)
    blob = json.dumps(getattr(v, "__dict__", {}) or str(v), ensure_ascii=False, default=str)
    assert SECRET not in blob and "クレジットカード決済" not in blob


def test_deploy_check_898_detects_the_free_text_section_in_pages(tmp_path, monkeypatch):
    import scripts.deploy_check as dc
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.html").write_text("<dt>条件の詳細（公式の告知より）</dt><dd>x</dd>", encoding="utf-8")
    monkeypatch.setattr(dc, "PROJECT_ROOT", tmp_path)
    [r] = dc._check_tcg_lottery_public_text()
    assert r["level"] == "error" and "docs/index.html" in r["message"]


def test_product_name_source_separates_master_names_from_announcement_headlines():
    assert public_event({**EV, "product_id": "pkm-a", "product_match": "exact"})["product_name_source"] == "master"
    assert public_event({**EV, "product_id": None, "product_match": "none"})["product_name_source"] == "announcement"
    assert public_event({**EV, "product_id": "pkm-a", "product_match": "exact", "provisional_product": True})[
        "product_name_source"] == "announcement"


def test_archive_redaction_removes_only_the_free_text_parts():
    from scripts.redact_archive_free_text import redact
    html = ('<dl><dt>応募条件</dt><dd>会員登録が必要・本人確認あり</dd><dt>条件の詳細（公式の告知より）</dt><dd>告知の文</dd>'
            '<dt>応募条件</dt><dd>支払い: クレジットカード決済のみ</dd></dl>'
            '<div class="tcg-row"><span>お届け</span><b>12月10日発送予定</b></div><a href="https://x">公式</a>')
    out, c = redact(html)
    assert c == {"condition_detail": 1, "payment": 1, "delivery": 1, "old_eligibility": 0}
    old, c2 = redact('<details class="tcg-elig"><summary>応募条件の原文</summary><div>告知の文</div></details><p>x</p>')
    assert c2["old_eligibility"] == 1 and old == "<p>x</p>"
    assert "告知の文" not in out and "クレジットカード" not in out and "発送予定" not in out
    assert "会員登録が必要・本人確認あり" in out and '<a href="https://x">公式</a>' in out        # 構造化した要約とリンクは残す


def test_redact_apply_is_limited_to_the_archive_or_a_copy(tmp_path):
    import subprocess
    import sys
    d = tmp_path / "other"
    d.mkdir()
    (d / "a.html").write_text("<dt>条件の詳細（公式の告知より）</dt><dd>x</dd>", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "redact_archive_free_text.py"), "--apply", "--dir", str(d)],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "条件の詳細" in (d / "a.html").read_text(encoding="utf-8")       # 書き換えない
    c = tmp_path / "archive_copy"
    c.mkdir()
    (c / "a.html").write_text("<dt>条件の詳細（公式の告知より）</dt><dd>x</dd><p>y</p>", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "redact_archive_free_text.py"), "--apply", "--dir", str(c)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and (c / "a.html").read_text(encoding="utf-8") == "<p>y</p>"


def test_cancelled_lottery_gets_no_deadline_notification(tmp_path):
    from src.tcg.lottery.history import notification_candidates
    ev = {"lottery_id": "lot-c", "source_type": "RETAILER_OFFICIAL", "tcg": "POKEMON", "product_name": "x", "retailer": "GEO",
          "application_end": "2026-11-27T12:00:00+09:00", "status": "OPEN", "verified": True}
    now = datetime(2026, 11, 26, 13, 0, tzinfo=JST)
    base, _ = notification_candidates([ev], now=now, ledger_path=tmp_path / "l.json")
    cancelled, _ = notification_candidates([{**ev, "cancelled": True}], now=now, ledger_path=tmp_path / "l2.json")
    assert base and cancelled == []                             # 中止でなければ締切前の候補ができ、中止なら作らない


def test_early_closed_lottery_keeps_post_deadline_notifications(tmp_path):
    from src.tcg.lottery.history import notification_candidates
    ev = {"lottery_id": "lot-e", "source_type": "RETAILER_OFFICIAL", "tcg": "POKEMON", "product_name": "x", "retailer": "GEO",
          "application_end": "2026-11-30T12:00:00+09:00", "winner_announcement_at": "2026-11-26T12:00:00+09:00",
          "application_closed": True, "status": "RESULT_PENDING", "verified": True}
    got, _ = notification_candidates([ev], now=datetime(2026, 11, 26, 13, 0, tzinfo=JST), ledger_path=tmp_path / "l.json")
    assert [c["milestone"] for c in got] == ["winner_announcement"]     # 締切前の通知は出さず、当選発表の通知は残す


def test_committed_public_lottery_json_has_no_private_free_text():
    """リポジトリに入っている公開の抽選 JSON（exports/tcg/lotteries.json の items・latest.json の lotteries）に、公開対象外の原文が無い。
    Daily LP の収集（continue-on-error）が JSON を書き出す前に落ちて、コミット済みの JSON がそのまま残った日でも、
    deploy-check #898 が原文の残りを理由に止めないための前提（収集が書き直すときは public_events を通る）。"""
    import json as _json
    from src.tcg.lottery.public import leaked_fields
    for name, key in (("lotteries.json", "items"), ("latest.json", "lotteries")):
        p = ROOT / "exports" / "tcg" / name
        if not p.exists():
            continue
        items = (_json.loads(p.read_text(encoding="utf-8")) or {}).get(key) or []
        leaks = [f"{e.get('lottery_id')}:{','.join(leaked_fields(e))}" for e in items if isinstance(e, dict) and leaked_fields(e)]
        assert leaks == [], (name, leaks[:5])


def test_deploy_check_898_passes_on_the_committed_json_without_running_the_collector():
    """収集を動かさずに（＝収集が書き出す前に落ちた日と同じ状態で）、#898 がコミット済みの JSON と公開ページで通る。"""
    import scripts.deploy_check as dc
    r = [x for x in dc._check_tcg_lottery_public_text() if x["check"] == "tcg_lottery_public_text"]
    assert r and r[0]["level"] == "ok", r
