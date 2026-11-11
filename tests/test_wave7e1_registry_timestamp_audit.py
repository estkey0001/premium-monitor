"""Wave 7e-1: 登録簿 VERIFIED_URLS の checked_on / stock_checked_at の「根拠の無い日付だけの前進」の検知。通信しない。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parent.parent / "scripts" / "audit_timestamp_only_updates.py"
_spec = importlib.util.spec_from_file_location("audit_timestamp_only_updates_w7e1", _p)
aud = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aud)
find = aud.registry_timestamp_findings

URL = "https://www.example.com/p/a"


def _src(*, price=100000, url=URL, on="2026-10-08", stock="在庫あり", stock_at="2026-10-08T10:00:00+09:00", comment="", extra=""):
    return (
        "VERIFIED_URLS_CHECKED_ON = '2026-08-23'\n\n"
        "VERIFIED_URLS = {\n"
        "    # ---- テスト ----\n"
        f"{comment}"
        f'    "prod_a": {{"source": "s", "url": "{url}", "link_type": "item", "price": {price}, "conf": "high",\n'
        f'               "checked_on": "{on}", "price_kind": "official_direct", "stock": "{stock}", "stock_checked_at": "{stock_at}"}},\n'
        '    "prod_b": {"source": "s", "url": "https://www.example.com/p/b", "link_type": "item", "price": 5, "conf": "high",\n'
        '               "checked_on": "2026-10-01", "price_kind": "msrp"},\n'
        f"{extra}"
        "}\n"
        "UNVERIFIED = {}\n"
    )


def test_date_only_advance_is_detected():
    f = find(_src(), _src(on="2026-11-09"))
    assert len(f) == 1 and f[0]["kind"] == aud.TIMESTAMP_ONLY_REGISTRY
    assert (f[0]["product_id"], f[0]["field"], f[0]["old"], f[0]["new"]) == ("prod_a", "checked_on", "2026-10-08", "2026-11-09")


def test_stock_checked_at_only_advance_is_detected():
    f = find(_src(), _src(stock_at="2026-11-09T10:00:00+09:00"))
    assert [(x["product_id"], x["field"], x["kind"]) for x in f] == [("prod_a", "stock_checked_at", aud.TIMESTAMP_ONLY_REGISTRY)]


def test_changed_price_url_or_stock_is_allowed():
    assert find(_src(), _src(on="2026-11-09", price=110000)) == []
    assert find(_src(), _src(on="2026-11-09", url="https://www.example.com/p/a2")) == []
    assert find(_src(), _src(on="2026-11-09", stock="在庫なし")) == []


def test_added_comment_with_the_new_date_is_a_human_verification():
    c = "    # 2026-11-09（Coverage Wave 3）: 公式ページで 100,000円を再確認\n"
    assert find(_src(), _src(on="2026-11-09", comment=c)) == []


def test_comment_with_an_old_date_or_for_another_product_is_not_evidence():
    old_c = "    # 2026-10-08: 前回の確認\n"
    assert len(find(_src(), _src(on="2026-11-09", comment=old_c))) == 1
    # 別の商品（prod_b）の後ろに付いたコメントは prod_a の根拠にしない
    assert len(find(_src(), _src(on="2026-11-09", extra="    # 2026-11-09: prod_b だけの確認\n"))) == 1
    # 既存のコメント（差分で追加されていない）は根拠にならない
    c = "    # 2026-11-09: 既に有る\n"
    assert find(_src(comment=c), _src(on="2026-11-09", comment=c)) != []


def test_checked_on_going_back_is_reported_separately():
    f = find(_src(on="2026-11-09"), _src(on="2026-10-01"))
    assert [(x["kind"], x["product_id"]) for x in f] == [(aud.CHECKED_ON_REGRESSED, "prod_a")]


def test_new_product_is_allowed_and_unchanged_is_clean():
    extra = '    "prod_c": {"source": "s", "url": "u", "price": 1, "checked_on": "2026-11-09", "price_kind": "msrp"},\n'
    assert find(_src(), _src(extra=extra)) == []
    assert find(_src(), _src()) == []


def test_broken_or_empty_sources_never_raise():
    for old, new in (("", ""), ("", _src()), (_src(), ""), (_src(), "VERIFIED_URLS = {"), ("def (:", "x ="), (None, None),
                     ("VERIFIED_URLS = 5", "VERIFIED_URLS = 5"), (_src(), "VERIFIED_URLS = {'a': foo(), 'b': 1}")):
        assert find(old, new) == []


def test_cli_wrapper_exposes_key_and_dates():
    v = aud._registry_violations(_src(), _src(on="2026-11-09"))
    assert len(v) == 1 and "prod_a.checked_on" in v[0].key and v[0].old_ts == "2026-10-08" and v[0].new_ts == "2026-11-09"


def test_real_registry_has_no_unevidenced_advance_against_itself():
    reg = Path(__file__).resolve().parent.parent / "src" / "market" / "official_registry.py"
    text = reg.read_text(encoding="utf-8")
    assert find(text, text) == []
    assert aud._registry_entries(text)                  # 実際の登録簿を読める（形が変わって検査が空振りしていない）
