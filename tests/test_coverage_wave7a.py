"""Coverage Wave 7a: TCG の応募先（告知の URL と応募の URL の分離）・応募の経路・要件・完成度・定価との同一性。

通信はしない（合成のイベントだけ）。**告知のページがあるだけでは応募できると扱わない。**
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from src.research import candidates as rc
from src.tcg import action_url as au
from src.tcg import detection_delay as dd
from src.tcg import profit_dense as pdn

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=JST)


_REAL_RULES = dict(au.APPLICATION_PATH_RULES)


@pytest.fixture(autouse=True)
def _synthetic_application_rules(monkeypatch):
    """汎用の検証（正規化・告知との区別・経路・完成度）は、合成の許可パス（c-labo.jp の /entry/…）で行う。実際の許可表は別のテストで検証する。"""
    rules = dict(_REAL_RULES)
    pat = re.compile(r"^/(entry|e|lot)/[A-Za-z0-9]+/?$")
    rules["CARD_LABO"] = tuple((h, pat) for h in ("c-labo.jp", "www.c-labo.jp", "shop.c-labo.jp"))        # ホストは完全一致
    rules["PREMIUM_BANDAI"] = (("p-bandai.jp", re.compile(r"^/item/item-\d+/?$")),)
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", rules)


def _e(**k):
    base = {"status": "OPEN", "event_type": "LOTTERY", "retailer": "CARD_LABO", "source_type": "STORE_OFFICIAL", "tcg": "POKEMON", "product_name": "商品",
            "product_id": "pid-1", "product_match": "exact", "store_name": "テスト店", "region": "JP",
            "application_start": "2026-10-30T09:00:00+09:00", "application_end": "2026-11-02T23:59:00+09:00",
            "winner_announcement_date": "2026-11-04", "purchase_start_date": "2026-11-05", "purchase_end_date": "2026-11-08",
            "entry_url": "https://www.c-labo.jp/entry/1", "source_url": "https://www.c-labo.jp/news/1"}
    base.update(k)
    return base


# ── 応募の URL は公式ドメインの https だけ ──────────────────────────────────────────────

def test_application_url_is_only_an_official_domain_https_entry_url():
    ok = au.classify(_e(), NOW)
    assert ok["application_url"] == "https://www.c-labo.jp/entry/1" and ok["channel"] == au.CH_WEB_OFFICIAL
    assert ok["announcement_url"] == "https://www.c-labo.jp/news/1" and ok["quality"] == au.Q_COMPLETE and ok["actionable_event"]
    sub = au.classify(_e(entry_url="https://shop.c-labo.jp/e/2"), NOW)                  # 公式ドメインのサブドメイン
    assert sub["application_url"] == "https://shop.c-labo.jp/e/2"


def test_lookalike_http_userinfo_and_foreign_domains_are_not_application_urls():
    for bad in ("http://www.c-labo.jp/entry/1",                       # https でない
                "https://c-labo.jp.evil.example/entry",               # 公式ドメインを前に置いた別ドメイン
                "https://evil-c-labo.jp/entry",                       # 末尾が似ているだけ
                "https://user:pw@www.c-labo.jp/entry",                # 認証情報つき
                "https://livepocket.jp/e/abc",                        # 外部フォーム
                "javascript:alert(1)", "not a url", ""):
        c = au.classify(_e(entry_url=bad), NOW)
        assert c["application_url"] is None, bad
        assert not c["actionable_event"], bad


def test_parser_differential_and_unsafe_authorities_are_rejected_allowlist_style():
    """ブラウザとパーサーでホストの読みが分かれる入力・正規化できない入力を認めない（監査 H1 / M1）。"""
    for bad in ("https://evil.com\\.c-labo.jp/e", "https://evil.com\\x.c-labo.jp/e",          # バックスラッシュ
                "https://evil.com .c-labo.jp/e", "https://evil.com\t.c-labo.jp/e",             # 空白・タブ
                "https://evil.com%2f.c-labo.jp/e", "https://evil.com\x00.c-labo.jp/",          # %2f・NUL
                "https://ｗｗｗ.c-labo.jp/e",                                                    # 全角
                "HTTPS://www.c-labo.jp/e",                                                       # 大文字のスキーム
                "https://www.c-labo.jp:8443/e", "https://www.c-labo.jp:badport/e", "https://www.c-labo.jp:/e",
                "https://@www.c-labo.jp/e", "https://:@www.c-labo.jp/e", "https://u@www.c-labo.jp/e",
                "//www.c-labo.jp/e", "/entry/1", "www.c-labo.jp/e"):                             # https でない・相対
        assert au.safe_https(bad) is None, bad
        assert au.classify(_e(entry_url=bad), NOW)["application_url"] is None, bad


def test_returned_application_url_is_the_normalized_verified_string():
    c = au.classify(_e(entry_url="https://WWW.C-LABO.JP./entry/9?x=1#frag"), NOW)
    assert c["application_url"] == "https://www.c-labo.jp/entry/9"                              # ホストを小文字・末尾のドット・fragment・query を除く
    assert au.classify(_e(entry_url="https://www.c-labo.jp:443/entry/9"), NOW)["application_url"] == "https://www.c-labo.jp/entry/9"


def test_announcement_listing_or_top_page_is_not_an_application_url():
    same = au.classify(_e(entry_url="https://www.c-labo.jp/news/1", source_url="https://www.c-labo.jp/news/1/"), NOW)   # 告知ページそのもの
    assert same["application_url"] is None and not same["actionable_event"]
    top = au.classify(_e(entry_url="https://www.c-labo.jp/"), NOW)                                  # トップページ
    assert top["application_url"] is None
    lst = au.classify(_e(entry_url="https://www.c-labo.jp/blog/filter/tcg:25/"), NOW)               # 告知の一覧（news_url）
    assert lst["application_url"] is None


def test_application_url_needs_an_official_source_type():
    for st in (None, "", "COMMUNITY", "MANUAL_VERIFIED"):
        c = au.classify(_e(source_type=st), NOW)
        assert c["application_url"] is None and not c["actionable_event"], st
    assert au.classify(_e(source_type="MANUAL_VERIFIED_OFFICIAL"), NOW)["application_url"]


def test_news_host_alone_is_not_an_official_application_host():
    assert "pokemon-card.com" not in au.official_hosts("POKEMON_CENTER_ONLINE")                    # 告知の一覧のホストは公式の応募先にしない
    c = au.classify(_e(retailer="POKEMON_CENTER_ONLINE", entry_url="https://www.pokemon-card.com/entry/1"), NOW)
    assert c["application_url"] is None


def test_winner_and_purchase_must_be_readable_dates_not_just_non_empty_strings():
    for k in ({"winner_announcement_date": "TBD"}, {"purchase_start_date": "未定"}, {"purchase_end_date": "xx"}):
        c = au.classify(_e(**k), NOW)
        assert c["quality"] != au.Q_COMPLETE and not c["actionable_event"], k


def test_channel_ready_is_a_separate_operator_count_and_never_actionable():
    sns = au.classify(_e(entry_url=None), NOW)                                                      # SNS 経路・応募の URL なし・他は完成
    assert sns["channel_ready"] and not sns["actionable_event"] and sns["quality"] == au.Q_PARTIAL
    assert not au.classify(_e(entry_url=None, winner_announcement_date=None), NOW)["channel_ready"]   # 他にも欠ける
    assert not au.classify(_e(retailer="TOYSRUS", entry_url=None), NOW)["channel_ready"]            # 経路が不明
    assert not au.classify(_e(entry_url=None, application_start="2026-11-03T09:00:00+09:00"), NOW)["channel_ready"]  # review_required
    full = au.classify(_e(), NOW)
    assert full["actionable_event"] and not full["channel_ready"]
    c = pdn.evaluate([_e(entry_url=None), _e()], None, NOW)["counts"]
    assert c["tcg_channel_ready"] == 1 and c["tcg_actionable_events"] == 1


def test_external_form_is_kept_apart_and_not_counted_as_application_url():
    c = au.classify(_e(retailer="HOBBY_STATION", entry_url="https://livepocket.jp/e/abc", source_url="https://www.hbst.net/?p=1"), NOW)
    assert c["application_url"] is None and c["external_entry_url"] == "https://livepocket.jp/e/abc"
    assert c["channel"] == au.CH_EXTERNAL_FORM and not c["actionable_event"]
    counts = pdn.evaluate([_e(retailer="HOBBY_STATION", entry_url="https://livepocket.jp/e/abc", source_url="https://www.hbst.net/?p=1")], None, NOW)["counts"]
    assert counts["tcg_external_entry_form"] == 1 and counts["tcg_application_url_confirmed"] == 0


def test_announcement_only_has_no_application_url_and_is_not_actionable():
    c = au.classify(_e(entry_url=None), NOW)
    assert c["application_url"] is None and c["announcement_url"] and not c["actionable_event"] and c["quality"] == au.Q_PARTIAL
    assert "application_url" in c["missing"]
    p = pdn.completeness(_e(entry_url=None, purchase_url="https://www.c-labo.jp/buy"), NOW)
    assert not p["actionable_event"] and p["announcement_url_only"]                      # 購入の URL（当選後）は応募の URL ではない
    r = pdn.evaluate([_e(entry_url=None)], None, NOW)["counts"]
    assert r["tcg_announcement_url_only"] == 1 and r["tcg_application_url_confirmed"] == 0 and r["tcg_actionable_events"] == 0


def test_unregistered_retailer_never_gets_an_application_url():
    c = au.classify(_e(retailer="UNKNOWN_SHOP", entry_url="https://unknown.example/entry"), NOW)
    assert c["application_url"] is None and au.official_hosts("UNKNOWN_SHOP") == frozenset()


# ── 応募の経路と要件（アプリ・SNS・店頭・会員）─────────────────────────────────────────

def test_channels_come_from_the_investigated_source_or_the_event_itself():
    sns = au.classify(_e(entry_url=None), NOW)
    assert sns["channel"] == au.CH_SNS and au.R_SNS in sns["requirements"]
    app = au.classify(_e(retailer="KIDS_REPUBLIC", entry_url=None, channel="APP"), NOW)
    assert app["channel"] == au.CH_APP and au.R_APP in app["requirements"]
    login = au.classify(_e(retailer="FUKUFUKU_TOREKA", entry_url=None), NOW)
    assert login["channel"] == au.CH_MEMBER_LOGIN and au.R_MEMBERSHIP in login["requirements"]
    unknown = au.classify(_e(retailer="TOYSRUS", entry_url=None), NOW)
    assert unknown["channel"] == au.CH_UNKNOWN and unknown["requirements"] == []          # 経路を推測しない
    counter = au.classify(_e(retailer="TOYSRUS", entry_url=None, store_pickup_required=True), NOW)
    assert counter["channel"] == au.CH_STORE_COUNTER and au.R_STORE_PICKUP in counter["requirements"]
    kept = au.classify(_e(entry_url=None, store_pickup_required=True), NOW)                  # 調べた経路（SNS）は店頭の明記で上書きしない
    assert kept["channel"] == au.CH_SNS and au.R_STORE_PICKUP in kept["requirements"] and au.R_SNS in kept["requirements"]


def test_requirements_are_listed_only_when_stated_and_never_assumed_false():
    c = au.classify(_e(membership_required=True, purchase_history_required=True, identity_verification_required=False, app_required=None), NOW)
    assert au.R_MEMBERSHIP in c["requirements"] and au.R_PURCHASE_HISTORY in c["requirements"]
    assert au.R_IDENTITY not in c["requirements"] and au.R_APP not in c["requirements"]   # False・不明は要件に入れない
    assert c["region"] == "JP" and c["store"] == "テスト店"
    assert au.classify({}, NOW)["channel"] == au.CH_UNKNOWN                                # 壊れた入力でも例外にしない
    assert au.classify(None, NOW)["application_url"] is None


# ── 完成度（complete / partial / review_required）──────────────────────────────────────

def test_quality_complete_partial_and_review_required():
    assert au.classify(_e(), NOW)["quality"] == au.Q_COMPLETE
    assert au.classify(_e(winner_announcement_date=None), NOW)["quality"] == au.Q_PARTIAL
    assert au.classify(_e(product_id=None, product_match="none"), NOW)["quality"] == au.Q_PARTIAL
    # 日程の矛盾（応募の終了が開始より前）は推測で直さず review_required（actionable にしない）
    bad = au.classify(_e(application_start="2026-11-03T09:00:00+09:00", application_end="2026-11-02T23:59:00+09:00"), NOW)
    assert bad["quality"] == au.Q_REVIEW and not bad["actionable_event"]
    early_winner = au.classify(_e(winner_announcement_date="2026-11-01"), NOW)              # 当選発表が応募の終了より前
    assert early_winner["quality"] == au.Q_REVIEW
    ambiguous = au.classify(_e(product_match="ambiguous"), NOW)                             # 商品の同一性が曖昧
    assert ambiguous["quality"] == au.Q_REVIEW and not ambiguous["actionable_event"]
    provisional = au.classify(_e(provisional_product=True), NOW)
    assert not provisional["actionable_event"]
    for m in ("partial", "none", None, ""):                                                  # exact 以外は商品を確認済みにしない
        c = au.classify(_e(product_match=m), NOW)
        assert "product" in c["missing"] and not c["actionable_event"], m


def test_date_only_same_day_winner_is_not_a_conflict():
    c = au.classify(_e(application_end=None, application_end_date="2026-11-02", winner_announcement_date="2026-11-02"), NOW)
    assert c["quality"] == au.Q_COMPLETE                                                    # 23:59:59 に補った終了と同じ日の発表を矛盾にしない


def test_counts_cover_every_active_event_exactly_once():
    items = [_e(), _e(entry_url=None), _e(application_start="2026-11-03T09:00:00+09:00"),
             _e(status="ENDED"), _e(retailer="HOBBY_STATION", entry_url="https://livepocket.jp/x", source_url="https://www.hbst.net/?p=2")]
    c = pdn.evaluate(items, None, NOW)["counts"]
    assert c["tcg_quality_complete"] + c["tcg_quality_partial"] + c["tcg_quality_review_required"] == 4   # ENDED は数えない
    assert (c["tcg_quality_complete"], c["tcg_quality_review_required"]) == (1, 1)
    assert c["tcg_actionable_events"] == c["tcg_quality_complete"]                          # actionable は complete だけ
    assert c["tcg_announcement_url"] == 4


# ── 定価との結び付き（商品 ID の完全一致 + TCG の種類の一致）──────────────────────────

_MSRP = {"verified": [{"product_id": "pid-1", "tcg": "POKEMON", "name": "商品", "retail_price": 5500, "source": "official_product_api",
                       "official_url": "https://www.pokemon-card.com/products/x.html", "release_date": "2026-10-20T00:00:00+09:00"}]}


def test_msrp_link_needs_exact_product_id_and_same_tcg_never_the_name():
    r = pdn.evaluate([_e()], _MSRP, NOW)
    assert r["counts"]["tcg_msrp_linked_active"] == 1 and r["events"][0]["msrp_link_basis"] == "product_id_exact"
    assert r["events"][0]["msrp_price"] == 5500
    name_only = pdn.evaluate([_e(product_id=None, product_match="none", product_name="商品")], _MSRP, NOW)
    assert name_only["counts"]["tcg_msrp_linked_active"] == 0 and name_only["events"][0]["msrp_link_basis"] is None
    wrong_tcg = pdn.evaluate([_e(tcg="ONE_PIECE")], _MSRP, NOW)                              # 商品 ID が同じでも TCG が違う
    assert wrong_tcg["counts"]["tcg_msrp_linked_active"] == 0 and wrong_tcg["counts"]["tcg_msrp_link_rejected"] == 1
    ambiguous = pdn.evaluate([_e(product_match="ambiguous")], _MSRP, NOW)
    assert ambiguous["counts"]["tcg_msrp_linked_active"] == 0
    prov = pdn.evaluate([_e(provisional_product=True)], _MSRP, NOW)
    assert prov["counts"]["tcg_msrp_linked_active"] == 0


# ── 日付だけの公開日は UNKNOWN（検知の遅れ）──────────────────────────────────────────────

def test_date_only_published_at_stays_unknown_for_detection_delay():
    for v in ("2026-10-02", "2026-10-02T00:00:00+09:00"):
        assert dd._date_only(v) is True
    assert dd._date_only("2026-10-02T07:30:00+09:00") is False


# ── 公開 / 非公開の境界 ───────────────────────────────────────────────────────────────

def test_public_counts_hold_numbers_only_and_private_rows_hold_urls():
    r = pdn.evaluate([_e(), _e(entry_url=None)], _MSRP, NOW)
    assert all(isinstance(v, int) for v in r["counts"].values())
    pub = json.dumps(r["counts"], ensure_ascii=False)
    assert "http" not in pub and "c-labo" not in pub and "テスト店" not in pub
    assert r["events"][0]["announcement_url"] and "application_url" in r["events"][0]      # 個別の URL は非公開の行にだけある
    keys = set(rc.COVERAGE_KEYS["tcg_profit_dense"])
    assert set(r["counts"]) <= keys and {"tcg_announcement_url", "tcg_quality_complete", "tcg_quality_review_required",
                                         "tcg_external_entry_form", "tcg_msrp_link_rejected"} <= keys


def test_actionable_events_do_not_become_notifications_or_purchases():
    """応募先の分類は件数と非公開の行を作るだけで、通知・購入・応募の自動実行の経路を持たない。"""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "src" / "tcg" / "action_url.py").read_text(encoding="utf-8")
    for banned in ("requests", "urllib.request", "httpx", "notif", "send_", "playwright", "selenium"):
        assert banned not in src, banned


# ══ URL の安全（Wave 7a 最終ゲート: M1 告知の回避 / M2 正規化 / M3 外部フォーム）═══════════════════════════

ANN = "https://www.c-labo.jp/blog/1"


def _app(entry, **k):
    return au.classify(_e(source_url=ANN, entry_url=entry, **k), NOW)["application_url"]


def test_m1_announcement_variants_never_become_application_urls():
    for v in (ANN + "?x=1", ANN + "?entry=1", ANN + "?apply=true", ANN + "?foo=bar", ANN + "/", ANN + "#entry",
              "https://www.c-labo.jp/blog/1/../1", "https://www.c-labo.jp/blog/./1", "https://www.c-labo.jp//blog//1",
              ANN + "/index.html", ANN + "/index.php", "https://WWW.C-LABO.JP/blog/1", "https://www.c-labo.jp/BLOG/1",
              "https://www.c-labo.jp/Blog/1/Index.HTML?x=1"):
        assert _app(v) is None, v
    assert _app("https://www.c-labo.jp/entry/12") == "https://www.c-labo.jp/entry/12"                 # 別の個別ページは応募の URL


def test_m1_generic_and_listing_urls_are_rejected_even_with_query():
    for v in ("https://www.c-labo.jp/", "https://www.c-labo.jp/?x=1", "https://c-labo.jp//",
              "https://www.c-labo.jp/blog/filter/tcg:25/", "https://www.c-labo.jp/blog/filter/tcg:25/?p=1",
              "https://www.c-labo.jp/news/", "https://www.c-labo.jp/search?q=1", "https://www.c-labo.jp/category/1",
              "https://www.c-labo.jp/campaign/2",                                                   # お知らせ・キャンペーンは固有でも応募ではない
              "https://www.c-labo.jp/news/2?id=2"):                                                 # 別のニュース記事
        assert _app(v) is None, v


def test_m1_self_application_needs_an_explicitly_confirmed_source(monkeypatch):
    same = "https://p-bandai.jp/item/item-1000/"
    c = au.classify(_e(retailer="PREMIUM_BANDAI", source_url=same, entry_url=same), NOW)
    assert c["application_url"] is None and not c["actionable_event"]                               # 告知と同じ URL は応募の URL にしない
    monkeypatch.setattr(au, "SELF_APPLICATION_SOURCES", frozenset({"PREMIUM_BANDAI"}))
    assert au.classify(_e(retailer="PREMIUM_BANDAI", source_url=same, entry_url=same), NOW)["application_url"] == same
    other = au.classify(_e(retailer="CARD_LABO", source_url=ANN, entry_url=ANN), NOW)               # 確認していない取得元には効かない
    assert other["application_url"] is None


def test_m2_normalization_and_invisible_or_dangerous_forms():
    assert au.safe_https("https://www.c-labo.jp/a/./b/c/../d")[1] == "https://www.c-labo.jp/a/b/d"   # dot segment を解決
    assert au.safe_https("https://www.c-labo.jp/a//b") is None and au.safe_https("https://www.c-labo.jp//a") is None   # 連続スラッシュは拒否
    assert au.safe_https("https://www.c-labo.jp/a/b/")[1] == "https://www.c-labo.jp/a/b/"            # 末尾のスラッシュは残す
    assert au.safe_https("https://www.c-labo.jp/Entry/9")[1] == "https://www.c-labo.jp/Entry/9"       # パスの大文字小文字は変えない
    assert au.safe_https("https://www.c-labo.jp/e#frag") == au.safe_https("https://www.c-labo.jp/e")  # fragment は同一性に影響しない
    assert au.safe_https("https://www.c-labo.jp:443/e")[1] == "https://www.c-labo.jp/e"               # 既定のポートを除く
    for bad in ("https://www.c-labo.jp/../x", "https://www.c-labo.jp/a/../../x",                      # ルートより上
                "https://www.c-labo.jp/%2e%2e/x", "https://www.c-labo.jp/%2E/x", "https://www.c-labo.jp/a%2fb",
                "https://www.c-labo.jp/a%5cb", "https://www.c-labo.jp/a%00b", "https://www.c-labo.jp/a?x=%0d%0a",
                "https://www.c-labo.jp/x​", "https://www.c-labo.jp/x?q=‮", "https://www.c-labo.jp/⁠x",
                "https://www.c-labo.jp/﻿x", "https://www.c-labo.jp/　x", "https://www.c-labo.jp/ x",
                "https://www.c-labo.jp/x\x07", "https://www.c-labo.jp/x\r\ny"):
        assert au.safe_https(bad) is None, repr(bad)                                                # 削って通さず、拒否する
    assert au.classify(_e(entry_url="https://www.c-labo.jp/x​"), NOW)["application_url"] is None


def test_m3_ip_literals_and_confusable_hosts_are_rejected():
    for bad in ("https://127.0.0.1/entry/1", "https://10.0.0.1/x/1", "https://192.168.1.1/x/1", "https://169.254.169.254/x/1",
                "https://8.8.8.8/x/1", "https://[::1]/x/1", "https://2130706433/x/1", "https://localhost/x/1",
                "https://xn--c-labo-9x4.jp/x/1", "https://-.c-labo.jp/x/1", "https://a-.c-labo.jp/x/1",
                "https://" + "a" * 64 + ".c-labo.jp/x/1"):
        assert au.safe_https(bad) is None, bad                                                      # ホストの形式の時点で拒否（登録の有無に関わらず）
    for bad in ("https://www.c-labo.jp.evil.com/x/1", "https://evil-c-labo.jp/x/1", "https://c-labo.jp.evil/x/1"):
        assert not au._is_official(bad, "CARD_LABO"), bad                                          # 似たホストは公式でない
    for bad in ("https://127.0.0.1/entry/1", "https://[::1]/x/1", "https://www.c-labo.jp.evil.com/x/1", "https://evil-c-labo.jp/x/1"):
        c = au.classify(_e(entry_url=bad), NOW)
        assert c["application_url"] is None and c["external_entry_url"] is None, bad


def test_defence_in_depth_each_layer_rejects_on_its_own(monkeypatch):
    """防御が二重になっている層を、片方を無効にしても単独で拒否できること（変異で片方を外しても見逃さない）。"""
    import re
    bs = "https://evil.com\\.c-labo.jp/e"
    assert au.safe_https(bs) is None
    monkeypatch.setattr(au, "_AUTHORITY", re.compile(r".*"))                                        # ホストの許可リストを外しても
    monkeypatch.setattr(au, "_host_ok", lambda h: True)
    for bad in (bs, "https://evil.com .c-labo.jp/e", "https://evil.com\t.c-labo.jp/e", "https://www.c-labo.jp/x\x07"):
        assert au.safe_https(bad) is None, repr(bad)                                                # 空白・制御文字・バックスラッシュの層が拒否する
    monkeypatch.undo()
    monkeypatch.setattr(au, "_BAD_CHARS", re.compile(r"(?!x)x"))                                    # 逆に空白・制御文字の層を外しても
    for bad in (bs, "https://evil.com .c-labo.jp/e"):
        assert au.safe_https(bad) is None, repr(bad)                                                # ホストの許可リストが拒否する


def test_m3_external_form_needs_source_specific_allowlist_and_official_source():
    ok = au.classify(_e(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1", entry_url="https://livepocket.jp/e/abc", source_type="STORE_OFFICIAL"), NOW)
    assert ok["external_entry_url"] == "https://livepocket.jp/e/abc" and ok["channel"] == au.CH_EXTERNAL_FORM and ok["application_url"] is None
    sub = au.classify(_e(retailer="MUGIWARA_STORE", source_url="https://www.mugiwara-store.com/news/1", entry_url="https://t.livepocket.jp/e/xyz1", source_type="STORE_OFFICIAL"), NOW)
    assert sub["external_entry_url"] == "https://t.livepocket.jp/e/xyz1"                              # 許可ホストのサブドメイン
    wrong_source = au.classify(_e(retailer="CARD_LABO", entry_url="https://livepocket.jp/e/abc"), NOW)  # 別の取得元のフォームのホストを使い回さない
    assert wrong_source["external_entry_url"] is None and wrong_source["channel"] == au.CH_SNS
    for bad in ("https://evil.com/f/abc", "https://docs.google.com/forms/d/abc", "https://forms.gle/abc", "https://livepocket.jp.evil.com/e/abc",
                "https://livepocket.jp/", "https://livepocket.jp/e/", "https://127.0.0.1/e/abc"):  # 一般のフォーム・似たホスト・入口
        c = au.classify(_e(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1", entry_url=bad), NOW)
        assert c["external_entry_url"] is None and c["application_url"] is None, bad
    for st in (None, "", "COMMUNITY", "MANUAL_VERIFIED"):                                           # 公式の情報元でなければ外部フォームも認めない
        c = au.classify(_e(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1", entry_url="https://livepocket.jp/e/abc", source_type=st), NOW)
        assert c["external_entry_url"] is None, st
    assert "HOBBY_STATION" in au.EXTERNAL_FORM_HOSTS and "CARD_LABO" not in au.EXTERNAL_FORM_HOSTS


def test_regression_existing_semantics_still_hold_after_url_hardening():
    assert not au.classify(_e(entry_url=None), NOW)["actionable_event"]                              # 告知だけ
    assert au.classify(_e(entry_url=None), NOW)["application_url"] is None
    assert au.classify(_e(winner_announcement_date="TBD"), NOW)["quality"] != au.Q_COMPLETE         # 日付が読めない
    assert au.classify(_e(application_start="2026-11-03T09:00:00+09:00"), NOW)["quality"] == au.Q_REVIEW
    assert _app("https://www.c-labo.jp/entry/12") and au.classify(_e(), NOW)["actionable_event"]    # 正しい応募の URL は通る


def test_m1_variants_of_an_event_specific_announcement_each_checked_on_their_own():
    """お知らせ系のパス規則に頼らず、告知の同一性の比較だけで拒否できること（告知の URL を `/lot/777` のように固有にして確かめる）。"""
    ann = "https://www.c-labo.jp/lot/777"
    for v in (ann, ann + "/", ann + "?x=1", ann + "?entry=1&apply=true", ann + "#e", "https://WWW.c-labo.jp/lot/777",
              "https://www.c-labo.jp/LOT/777", "https://www.c-labo.jp/Lot/777/", ann + "/index.html", ann + "/INDEX.HTML?x=1",
              "https://www.c-labo.jp/lot/x/../777", "https://www.c-labo.jp/lot//777", "https://www.c-labo.jp/lot/./777"):
        c = au.classify(_e(source_url=ann, entry_url=v), NOW)
        assert c["application_url"] is None and not c["actionable_event"], v
    assert au.classify(_e(source_url=ann, entry_url="https://www.c-labo.jp/lot/778"), NOW)["application_url"]   # 別の個別ページは応募の URL


def test_ip_like_hosts_with_numeric_tld_are_rejected():
    for bad in ("https://evil.123/x/1", "https://a.b.1/x/1", "https://www.c-labo.jp.123/x/1"):
        assert au.safe_https(bad) is None, bad


def test_m1_announcement_that_itself_ends_with_index_html_matches_the_directory_url():
    ann = "https://www.c-labo.jp/lot/777/index.html"
    for v in ("https://www.c-labo.jp/lot/777", "https://www.c-labo.jp/lot/777/", "https://www.c-labo.jp/lot/777/index.html?x=1"):
        assert au.classify(_e(source_url=ann, entry_url=v), NOW)["application_url"] is None, v


# ══ 最終ゲート（auditor H-1 / M-1 / M-2・reviewer M-1 / M-2）══════════════════════════════════════════

def _geo(entry, **k):
    return au.classify(_e(retailer="GEO", source_type="RETAILER_OFFICIAL", source_url="https://geo-online.co.jp/news/123", entry_url=entry, **k), NOW)


def test_real_application_path_table_accepts_only_listed_shapes(monkeypatch):
    """実際の許可表（今は GEO だけ・形は暫定）。公式ドメインというだけでは応募の URL にしない（商品ページ・記事・店舗ページは不可）。"""
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", _REAL_RULES)
    assert set(_REAL_RULES) == {"GEO"}
    assert _geo("https://draw.geo-online.co.jp/lottery/456")["application_url"] == "https://draw.geo-online.co.jp/lottery/456"
    for bad in ("https://draw.geo-online.co.jp/product/456", "https://draw.geo-online.co.jp/lottery/", "https://draw.geo-online.co.jp/lottery/abc",
                "https://geo-online.co.jp/shop/12", "https://geo-online.co.jp/lottery/456",            # ホストが違う（応募の許可ホストは draw.）
                "https://shop.draw.geo-online.co.jp/lottery/1", "https://evil.draw.geo-online.co.jp/lottery/1",   # サブドメインは完全一致で拒否
                "https://draw.geo-online.co.jp/lottery/１２３", "https://draw.geo-online.co.jp/lottery/12٣"):  # 全角・アラビア数字
        assert _geo(bad)["application_url"] is None, bad
    amazon = au.classify(_e(retailer="AMAZON", source_type="RETAILER_OFFICIAL", entry_url="https://www.amazon.co.jp/dp/B0123"), NOW)
    assert amazon["application_url"] is None                                                           # 許可表に無い取得元は応募の URL を持たない
    for r in ("CARD_LABO", "HOBBY_STATION", "MUGIWARA_STORE", "KIDS_REPUBLIC", "PREMIUM_BANDAI", "TSUTAYA", "POKEMON_CENTER_ONLINE", "FUKUFUKU_TOREKA"):
        assert au.classify(_e(retailer=r, entry_url="https://www.c-labo.jp/entry/12"), NOW)["application_url"] is None, r
    ff = au.classify(_e(retailer="FUKUFUKU_TOREKA", source_url="https://pokemon.fukufukutoreka.com/lottery",
                        entry_url="https://pokemon.fukufukutoreka.com/lottery/91"), NOW)               # 会員ログインの取得元は応募の URL を持たない
    assert ff["application_url"] is None and ff["channel"] == au.CH_MEMBER_LOGIN and au.R_MEMBERSHIP in ff["requirements"]


def test_h1_www_percent_encoding_and_path_params_do_not_split_announcement_from_application():
    ann = "https://www.c-labo.jp/entry/ab123"
    for v in ("https://c-labo.jp/entry/ab123", "https://www.c-labo.jp/entry/%61b123", "https://www.c-labo.jp/entry/%61%62123",
              "https://WWW.c-labo.jp/entry/ab123", "https://www.c-labo.jp/entry/ab123/"):
        assert au.classify(_e(source_url=ann, entry_url=v), NOW)["application_url"] is None, v
    assert au.classify(_e(source_url="https://c-labo.jp/entry/ab123", entry_url=ann), NOW)["application_url"] is None   # 逆向きも
    assert au.safe_https("https://www.c-labo.jp/entry/ab123;x=1") is None                              # パスのパラメータは拒否
    assert au.safe_https("https://www.c-labo.jp/entry/..;/abc") is None
    assert au.safe_https("https://www.c-labo.jp/e/%61")[1] == "https://www.c-labo.jp/e/a"              # 英数字の %XX は復号
    assert au.safe_https("https://www.c-labo.jp/e/%e3%81%82")[1] == "https://www.c-labo.jp/e/%E3%81%82"   # 残りは大文字にそろえる
    assert au.safe_https("https://www.c-labo.jp/e/%252e") is None                                      # 二重符号化は拒否


def test_embedded_urls_in_query_or_path_are_rejected():
    for bad in ("https://www.c-labo.jp/r/12?url=https://evil.example/x", "https://www.c-labo.jp/r/12?next=http://evil.example",
                "https://www.c-labo.jp/https://evil.example/x"):
        assert au.safe_https(bad) is None, bad
    assert au.safe_https("https://www.c-labo.jp/r/12?x=1")                                             # ふつうの query は通る


def test_retailer_is_normalized_to_the_registry_key(monkeypatch):
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", _REAL_RULES)
    for r in ("geo", " GEO ", "Geo"):
        c = au.classify(_e(retailer=r, source_type="RETAILER_OFFICIAL", source_url="https://geo-online.co.jp/news/123",
                           entry_url="https://draw.geo-online.co.jp/lottery/456"), NOW)
        assert c["application_url"] == "https://draw.geo-online.co.jp/lottery/456", r                  # 小文字・空白でも登録簿の取得元を引く
    assert au.classify(_e(retailer="card_labo", entry_url=None), NOW)["channel"] == au.CH_SNS
    assert au.classify(_e(retailer=" Hobby_Station ", source_url="https://www.hbst.net/?p=1", entry_url="https://livepocket.jp/e/abc"), NOW)["external_entry_url"]


def test_external_form_path_must_be_an_individual_event_form():
    hb = dict(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1")
    assert au.classify(_e(entry_url="https://livepocket.jp/e/abc", **hb), NOW)["external_entry_url"] == "https://livepocket.jp/e/abc"
    assert au.classify(_e(entry_url="https://t.livepocket.jp/e/abc1/", **hb), NOW)["external_entry_url"]
    for bad in ("https://livepocket.jp/login", "https://livepocket.jp/mypage", "https://livepocket.jp/t/hbst", "https://livepocket.jp/e/",
                "https://livepocket.jp/e/ab", "https://livepocket.jp/e/abc/extra", "https://livepocket.jp/",
                "https://livepocket.jp/e/abc?next=http://evil.example", "https://livepocket.jp/e/%2e%2e/login"):
        assert au.classify(_e(entry_url=bad, **hb), NOW)["external_entry_url"] is None, bad


def _update_alerts_module():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("update_alerts_w7a_links", Path(__file__).resolve().parent.parent / "scripts" / "update_alerts.py")
    ua = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ua)
    return ua


def test_legacy_csv_links_never_claim_an_unverified_form_and_fall_back_to_the_announcement():
    ua = _update_alerts_module()
    ann, form = "https://shop.example/news/1", "https://shop.example/entry/1?id=9#f"
    label = "応募先の候補を確認（公式ドメイン未照合）"
    assert ua._lottery_links({"url": ann, "entry_form_url": form}) == (ann, "https://shop.example/entry/1?id=9", label)   # 断定せず・query は残す・fragment は捨てる
    assert ua._lottery_links({"url": ann, "entry_form_url": ""}) == (ann, ann, "告知ページを確認")
    assert ua._lottery_links({"url": ann, "entry_form_url": ann}) == (ann, ann, "告知ページを確認")                          # 告知と同じ URL は告知として扱う
    assert ua._lottery_links({"url": ann, "entry_form_url": "http://shop.example/e"}) == (ann, ann, "告知ページを確認")   # 読めないフォームは告知へ
    assert ua._lottery_links({"url": "", "entry_form_url": form})[0] == "https://shop.example/entry/1?id=9"                  # 告知が無ければ product_url はフォーム
    assert ua._lottery_links({"url": "javascript:alert(1)", "entry_form_url": "http://x"}) == ("", "", "")                  # どちらも読めなければ空（ラベルも空）
    for bad in ("http://shop.example/n", "https://127.0.0.1/n", "https://shop.example/n;x", "https://shop.example/n?u=https://evil.example",
                "https://shop.example/n?next=//evil.example", "\u200bhttps://shop.example/n", 'https://shop.example/a"b', "https://shop.example/a<b>"):
        assert ua._lottery_links({"url": bad, "entry_form_url": ""}) == ("", "", ""), bad                                   # `url` も検証する


def test_legacy_csv_real_data_shapes_keep_their_query():
    """実データ（data/lottery_events.csv）の形: 商品 ID・検索語は query にあるので、検証した URL でも落とさない。"""
    ua = _update_alerts_module()
    for u in ("https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid=S0001580&cat=002010",
              "https://books.rakuten.co.jp/search?sgenre=101&keyword=Switch+2"):
        assert ua._lottery_links({"url": u, "entry_form_url": u}) == (u, u, "告知ページを確認"), u


def test_event_quality_action_url_count_uses_verified_application_urls_only(monkeypatch):
    from src.tcg import event_quality as eq
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", _REAL_RULES)
    base = dict(_e(retailer="GEO", source_type="RETAILER_OFFICIAL", source_url="https://geo-online.co.jp/news/123"))
    items = [dict(base, entry_url="https://draw.geo-online.co.jp/lottery/456"),
             dict(base, entry_url=None, purchase_url="https://geo-online.co.jp/buy/1"),          # 購入の URL は行動の URL に数えない
             dict(base, entry_url="https://geo-online.co.jp/news/123")]                          # 告知の URL は数えない
    assert eq.evaluate(items, NOW)["quality"]["with_action_url"] == 1


def test_each_url_layer_rejects_on_its_own_with_a_permissive_path_rule(monkeypatch):
    """許可パス表を全許可にしても、公式ドメイン・告知との同一性・出来事固有・お知らせ系のパスの各層が単独で拒否する（層ごとの検証）。"""
    anyp = re.compile(r"^/.*$")
    rules = dict(_REAL_RULES)
    rules["CARD_LABO"] = (("c-labo.jp", anyp), ("www.c-labo.jp", anyp), ("evil.example", anyp))
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", rules)
    ann = "https://www.c-labo.jp/lot/777"

    def app(entry, src=ann):
        return au.classify(_e(source_url=src, entry_url=entry), NOW)["application_url"]

    assert app("https://www.c-labo.jp/entry/12") == "https://www.c-labo.jp/entry/12"                    # 比較のための正しい例
    assert app("https://evil.example/entry/12") is None                                                # 公式ドメインでない（表に載っていても）
    for v in ("https://www.c-labo.jp/LOT/777", "https://www.c-labo.jp/lot/777?x=1", "https://c-labo.jp/lot/777",
              "https://www.c-labo.jp/lot/777/index.html", "https://www.c-labo.jp/lot/%37%37%37"):
        assert app(v) is None, v                                                                       # 告知との同一性（大文字小文字・query・www・index・符号化）
    for v in ("https://www.c-labo.jp/entry/abc", "https://www.c-labo.jp/entry/", "https://www.c-labo.jp/"):
        assert app(v) is None, v                                                                       # 出来事固有でない（数字のない最後のパス・入口）
    for v in ("https://www.c-labo.jp/campaign/2", "https://www.c-labo.jp/info/9/x", "https://www.c-labo.jp/news/9"):
        assert app(v) is None, v                                                                       # お知らせ・キャンペーン系のパス（数字があっても）
    hb = dict(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1")
    assert au.classify(_e(entry_url="https://evil.com/e/abc", **hb), NOW)["external_entry_url"] is None  # パスの形が合っても、許可ホストでなければ不可
    assert au.classify(_e(entry_url="https://livepocket.jp/login", **hb), NOW)["external_entry_url"] is None   # 許可ホストでも、パスの形が合わなければ不可


def test_unreadable_source_url_means_no_application_url_fail_closed(monkeypatch):
    """告知の URL が、あるのに安全に読めない（http・大文字のスキーム・ポート・`;`・ゼロ幅・全角）と、同じページかを判定できないので確定しない（監査 H1）。"""
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", _REAL_RULES)
    entry = "https://draw.geo-online.co.jp/lottery/5"
    ok = au.classify(_e(retailer="GEO", source_type="RETAILER_OFFICIAL", source_url="https://geo-online.co.jp/news/5", entry_url=entry), NOW)
    assert ok["application_url"] == entry
    for src in ("http://draw.geo-online.co.jp/lottery/5", "HTTPS://draw.geo-online.co.jp/lottery/5", "https://draw.geo-online.co.jp:8443/lottery/5",
                "https://draw.geo-online.co.jp/lottery/5;x", "https://draw.geo-online.co.jp/lottery/5\u200b", "https://draw.geo-online.co.jp/lottery/\uff15",
                "https://draw.geo-online.co.jp//lottery/5"):
        c = au.classify(_e(retailer="GEO", source_type="RETAILER_OFFICIAL", source_url=src, entry_url=entry), NOW)
        assert c["application_url"] is None and not c["actionable_event"], src
    c = au.classify(_e(retailer="GEO", source_type="RETAILER_OFFICIAL", source_url="https://geo-online.co.jp/news/5",
                       source_urls=["https://geo-online.co.jp/news/5", "http://geo-online.co.jp/news/6"], entry_url=entry), NOW)   # 追加の情報元が読めない
    assert c["application_url"] is None
    hb = au.classify(_e(retailer="HOBBY_STATION", source_url="http://www.hbst.net/?p=1", entry_url="https://livepocket.jp/e/abc"), NOW)
    assert hb["external_entry_url"] is None                                                            # 外部フォームも同じ


def test_application_url_never_carries_a_query_or_non_ascii_digits(monkeypatch):
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", _REAL_RULES)
    base = "https://draw.geo-online.co.jp/lottery/123"
    for q in ("?next=//evil.com", "?u=http%3a//x", "?utm_source=x", "?x=%", "?x=\u00e9", "?\uff03"):
        c = _geo(base + q)
        assert c["application_url"] in (None, base), q                                                 # query は残さない（拒否するか、捨てる）
        assert not c["application_url"] or "?" not in c["application_url"], q
    assert _geo(base + "?utm_source=x")["application_url"] == base                                     # ふつうの query は捨てて通す
    ext = au.classify(_e(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1", entry_url="https://livepocket.jp/e/abc?utm=1"), NOW)
    assert ext["external_entry_url"] == "https://livepocket.jp/e/abc"
    for bad in ("https://www.c-labo.jp/lot/1\uff11", "https://www.c-labo.jp/lot/1\u0661"):
        assert au.safe_https(bad) is None, bad                                                         # 非 ASCII は拒否


def test_legacy_csv_alerts_use_only_a_safely_readable_entry_form_url():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("update_alerts_w7a", Path(__file__).resolve().parent.parent / "scripts" / "update_alerts.py")
    ua = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ua)
    assert ua._entry_form_url({"entry_form_url": "https://shop.example/entry/1"}) == "https://shop.example/entry/1"
    for bad in ("http://shop.example/e", "https://127.0.0.1/e", "https://shop.example/e;x", "javascript:alert(1)", "https://shop.example/\u200be", ""):
        assert ua._entry_form_url({"entry_form_url": bad}) == "", bad                                  # 未検証の URL を「フォーム」として通知に出さない
    assert ua._entry_form_url({}) == ""


def test_application_path_patterns_match_ascii_digits_only_on_their_own():
    """許可パスの正規表現そのものが ASCII の数字だけに一致する（非 ASCII の拒否に頼らない）。"""
    pat = _REAL_RULES["GEO"][0][1]
    assert pat.fullmatch("/lottery/123") and pat.fullmatch("/lottery/123/")
    for bad in ("/lottery/\uff11\uff12\uff13", "/lottery/12\u0663", "/lottery/", "/lottery/12a", "/lottery/12\n"):
        assert pat.fullmatch(bad) is None, repr(bad)                                                 # 末尾の改行にも一致しない
    from src.tcg.action_url import _LIVEPOCKET_EVENT
    assert _LIVEPOCKET_EVENT.fullmatch("/e/abc") and _LIVEPOCKET_EVENT.fullmatch("/e/\uff41\uff42\uff43") is None
    assert _LIVEPOCKET_EVENT.fullmatch("/e/abc\n") is None



def test_missing_or_nonstring_announcements_are_not_confirmed(monkeypatch):
    """告知の URL が無い・文字列でない要素が混ざるときは、告知との突き合わせができないので応募の URL を確定しない（監査 L1 / L2）。"""
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", _REAL_RULES)
    base = dict(retailer="GEO", source_type="RETAILER_OFFICIAL", entry_url="https://draw.geo-online.co.jp/lottery/12")
    assert au.classify(_e(source_url="https://geo-online.co.jp/news/12", **base), NOW)["application_url"]
    for k in ({"source_url": None}, {"source_url": ""}, {"source_url": "https://geo-online.co.jp/news/12", "source_urls": [{"u": "x"}]},
              {"source_url": "https://geo-online.co.jp/news/12", "source_urls": [None]}):
        assert au.classify(_e(**base, **k), NOW)["application_url"] is None, k


def test_malformed_percent_sequences_and_reserved_livepocket_words_are_rejected():
    for bad in ("https://www.c-labo.jp/%", "https://www.c-labo.jp/e/%ZZ1", "https://www.c-labo.jp/e/1?x=%", "https://www.c-labo.jp/e/1%2"):
        assert au.safe_https(bad) is None, bad
    hb = dict(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1")
    for bad in ("https://livepocket.jp/e/login", "https://livepocket.jp/e/abc/../login", "https://livepocket.jp/e/mypage/", "https://livepocket.jp/e/signup"):
        assert au.classify(_e(entry_url=bad, **hb), NOW)["external_entry_url"] is None, bad
    assert au.classify(_e(entry_url="https://livepocket.jp/e/login1", **hb), NOW)["external_entry_url"]    # 予約語で始まるだけのイベント ID は通る


def test_channel_comes_from_the_registry_only_for_an_official_source():
    base = dict(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1", entry_url=None)
    assert au.classify(_e(**base), NOW)["channel"] == au.CH_EXTERNAL_FORM
    for st in ("AGGREGATOR", "COMMUNITY", None, ""):
        c = au.classify(_e(source_type=st, **base), NOW)
        assert c["channel"] == au.CH_UNKNOWN and not c["channel_ready"], st                          # 非公式の情報元では経路も channel_ready も立てない


def test_announcement_host_must_belong_to_the_retailer(monkeypatch):
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", _REAL_RULES)
    entry = "https://draw.geo-online.co.jp/lottery/456"
    base = dict(retailer="GEO", source_type="RETAILER_OFFICIAL", entry_url=entry)
    assert au.classify(_e(source_url="https://geo-online.co.jp/news/9", **base), NOW)["application_url"] == entry
    assert au.classify(_e(source_url="https://www.geo-online.co.jp/news/9", **base), NOW)["application_url"] == entry
    for src in ("https://example.com/x/1", "https://geo-online.co.jp.evil.com/news/9", "https://evil-geo-online.co.jp/news/9"):
        assert au.classify(_e(source_url=src, **base), NOW)["application_url"] is None, src         # 無関係なホストの告知は根拠にしない


def test_html_quote_and_shell_characters_are_rejected_and_livepocket_reserved_words_ignore_case():
    for ch in '<>"\'`|^{}':
        assert au.safe_https("https://www.c-labo.jp/a" + ch + "b") is None, ch
        assert au.safe_https("https://www.c-labo.jp/a?x=" + ch) is None, ch
    hb = dict(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1")
    for bad in ("https://livepocket.jp/e/LOGIN", "https://livepocket.jp/e/MyPage", "https://livepocket.jp/e/SignUp/"):
        assert au.classify(_e(entry_url=bad, **hb), NOW)["external_entry_url"] is None, bad


def test_source_urls_given_as_a_string_is_one_url_not_characters(monkeypatch):
    """`source_urls` が文字列でも 1 つの URL として告知との同一性を比べる（文字を 1 つずつ回して迂回させない）。"""
    monkeypatch.setattr(au, "APPLICATION_PATH_RULES", _REAL_RULES)
    entry = "https://draw.geo-online.co.jp/lottery/123"
    base = dict(retailer="GEO", source_type="RETAILER_OFFICIAL", source_url="https://geo-online.co.jp/news/12345", entry_url=entry)
    assert au.classify(_e(source_urls=[entry], **base), NOW)["application_url"] is None
    assert au.classify(_e(source_urls=entry, **base), NOW)["application_url"] is None                  # 文字列でも同じ
    assert au.classify(_e(source_urls=(entry,), **base), NOW)["application_url"] is None               # tuple も同じ
    assert au.classify(_e(source_urls=["https://geo-online.co.jp/news/12345"], **base), NOW)["application_url"] == entry


def test_channel_hints_and_channel_ready_need_an_official_source_and_a_confirmed_entry():
    for hint in ({"app_required": True}, {"channel": "APP"}, {"store_pickup_required": True}):
        official = au.classify(_e(retailer="TOYSRUS", entry_url=None, **hint), NOW)
        assert official["channel"] in (au.CH_APP, au.CH_STORE_COUNTER), hint
        for st in ("COMMUNITY", "AGGREGATOR", None, ""):
            c = au.classify(_e(retailer="TOYSRUS", entry_url=None, source_type=st, **hint), NOW)
            assert c["channel"] == au.CH_UNKNOWN and not c["channel_ready"], (hint, st)             # 非公式の明記は経路にしない
    hb = dict(retailer="HOBBY_STATION", source_url="https://www.hbst.net/?p=1")
    assert au.classify(_e(entry_url=None, **hb), NOW)["channel_ready"]                              # 応募先が無い・経路は登録簿（公式の情報元）
    assert au.classify(_e(entry_url="https://livepocket.jp/e/abc", **hb), NOW)["channel_ready"]     # 許可した外部フォーム
    for bad in ("https://livepocket.jp/e/login", "https://livepocket.jp/e/ab", "http://livepocket.jp/e/abc", "https://evil.example/e/abc"):
        assert not au.classify(_e(entry_url=bad, **hb), NOW)["channel_ready"], bad                  # 応募先が渡されたのに拒否された
    assert not au.classify(_e(entry_url=None, retailer="HOBBY_STATION", source_url="http://www.hbst.net/?p=1"), NOW)["channel_ready"]   # 告知が読めない
    assert not au.classify(_e(entry_url=None, retailer="CARD_LABO", source_url="https://evil.example/x/1"), NOW)["channel_ready"]       # 告知のホストが違う


def test_safe_https_rejects_double_slash_in_query_too():
    for bad in ("https://www.c-labo.jp/e/1?redirect=//evil.com", "https://www.c-labo.jp/e/1?a=1&next=//x"):
        assert au.safe_https(bad) is None, bad
    assert au.safe_https("https://www.c-labo.jp/e/1?a=1&b=2")


def test_legacy_csv_form_differing_only_by_trailing_slash_is_the_announcement():
    ua = _update_alerts_module()
    assert ua._lottery_links({"url": "https://a.example/x", "entry_form_url": "https://a.example/x/"}) == ("https://a.example/x", "https://a.example/x", "告知ページを確認")


def test_channel_ready_needs_a_known_channel_even_for_a_registered_official_source():
    """登録簿にある取得元でも、経路が不明（SOURCE_CHANNEL に無い）なら channel_ready を立てない（GEO は応募の経路を調べていない）。"""
    c = au.classify(_e(retailer="GEO", source_type="RETAILER_OFFICIAL", source_url="https://geo-online.co.jp/news/9", entry_url=None), NOW)
    assert c["channel"] == au.CH_UNKNOWN and not c["channel_ready"] and c["quality"] == au.Q_PARTIAL
