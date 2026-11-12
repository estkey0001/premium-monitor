"""公式の再確認の観測性（A7RV の失敗の調査を受けて）: 再確認が failed になったとき、parser の段階で
「型番が無い・価格候補が無い・価格候補が複数・在庫語が無い」を区別できるようにする診断のテスト。

**診断は観測性だけ**。判定（unchanged / changed / sale_ended / failed / blocked）には使わない・履歴と latest.json の形は変えない・
CI ログには failed の行だけ固定形式で出す（許可リスト: 真偽・整数・固定の在庫語・none）。
ページ上部の汎用の表示「現在、選択した商品が購入いただけません。」は、正常な Sony のページ（A1 II・A7CR）にもあり、販売状態の根拠にしない。
データはすべて架空（実際のページではない）。
"""

from __future__ import annotations

import importlib.util
import inspect
import itertools
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load("recheck_official_diag_test", ROOT / "scripts" / "recheck_official.py")
BANNER = "現在、選択した商品が購入いただけません。"
DIAG_KEYS = ("model_found", "price_candidate_count", "stock_phrase_found", "matched_stock_phrase")
LEGACY_KEYS = ("model_found", "price", "stock", "ended")
A7RV, A1II, A7CR = "ILCE-7RM5", "ILCE-1M2", "ILCE-7CR"


def page(body: str, *, banner: str = "top") -> str:
    b = f"<p>{BANNER}</p>"
    return f"<html><body>{b if banner == 'top' else ''}<h1>α</h1>{body}{b if banner == 'bottom' else ''}</body></html>"


def rec(price: int) -> dict:
    return {"price": price}


# ── 診断を足す前の parser（HEAD の実装を固定したもの。判定が変わっていないことの比較の基準） ─────────────────────────
_text, _STOCK_WORDS, _STOCK_ALIAS = R._text, R._STOCK_WORDS, R._STOCK_ALIAS


def old_parse_sony_store(h: str, model: str) -> dict:
    """Sony Store の購入ページ: 「<型番> <在庫の表示> <価格> 円(税込)」の並び。

    在庫の欄が決まった語（入荷待ち・在庫切れ・在庫あり・販売終了）のときだけ価格を採用する（型番の後に別の商品の
    価格が並んでも拾わない）。販売終了は、この商品の在庫の欄が「販売終了」のときだけ（ページの別の場所の
    「販売終了」では判定しない。Phase 15 監査 M-1・M-2）。
    """
    t = _text(h)
    # 型番の後ろに色の型番（/S・/B）と色名（（シルバー））が付く形も読む（α7CR: 「ILCE-7CR/S（シルバー） 翌日出荷 449,900円(税込)」）。
    # 色ごとの価格が食い違えば、下の「1 種類だけ」の条件で読み取らない
    ms = list(re.finditer(re.escape(model) + r"(?:/[A-Z]{1,2})?(?:（[^）]{1,10}）)?\s+(" + "|".join(_STOCK_WORDS) + r")\s*([\d,]{4,})\s*円\s*\(税込\)", t))
    # 並びが無い・2つ以上ある（どれがこの商品か決められない）ときは読み取らない（監査 N-1）
    if len({(x.group(1), x.group(2)) for x in ms}) != 1:
        return {"model_found": model in t, "price": None, "stock": "", "ended": False}
    m = ms[0]
    stock = _STOCK_ALIAS.get(m.group(1), m.group(1))
    return {"model_found": True, "price": int(m.group(2).replace(",", "")),
            "stock": "" if stock == "販売終了" else stock, "ended": stock == "販売終了"}


def old_parse_sony_product(h: str, model: str) -> dict:
    """Sony Store の商品ページ（_product）: 「ソニーストアで購入すると <価格> 円(税込) … <在庫の表示>」。

    型番がページにあり、価格と在庫の表示がそれぞれ1種類のときだけ読む（購入ページ _purchase と同じ商品の価格）。
    在庫の表示が決まった語（入荷待ち・在庫切れ・在庫あり）でなければ在庫は記録しない。販売終了は在庫の欄が
    「販売終了」のときだけ。
    """
    t = _text(h)
    if model not in t:
        return {"model_found": False, "price": None, "stock": "", "ended": False}
    ms = list(re.finditer(r"ソニーストアで購入すると\s*([\d,]{4,})\s*円\s*\(税込\)"
                          r"(?:\s*クーポン適用額をチェック\s*\(サインイン/新規登録\))?\s*(" + "|".join(_STOCK_WORDS) + r")?", t))
    if not ms:
        return old_parse_sony_store(h, model)            # 購入ページ（_purchase）の並び（型番 在庫 価格）の形
    if len({m.group(1) for m in ms}) != 1:
        return {"model_found": True, "price": None, "stock": "", "ended": False}
    stocks = {_STOCK_ALIAS.get(m.group(2) or "", m.group(2) or "") for m in ms}
    stock = stocks.pop() if len(stocks) == 1 else ""
    return {"model_found": True, "price": int(ms[0].group(1).replace(",", "")),
            "stock": "" if stock == "販売終了" else stock, "ended": stock == "販売終了"}


# ── 1〜7: 診断の値と判定 ─────────────────────────────────────────────────────────

def test_1_normal_sony_known_stock_single_price():
    p = R.parse_sony_store(page(f"<div>{A1II} 当日出荷 990,000円(税込)</div>"), A1II)
    assert R.classify(rec(990000), p) == "unchanged"
    assert (p["price"], p["stock"]) == (990000, "在庫あり")
    assert (p["model_found"], p["price_candidate_count"], p["stock_phrase_found"], p["matched_stock_phrase"]) == (True, 1, True, "当日出荷")


def test_2_a7rv_current_shape_no_known_stock_phrase_is_failed_with_diagnostics():
    p = R.parse_sony_store(page(f"<div>{A7RV} 533,500円(税込)</div>"), A7RV)
    assert R.classify(rec(533500), p) == "failed"                       # fail-close（unchanged でも sale_ended でもない）
    assert p["price"] is None and p["stock"] == "" and p["ended"] is False
    assert (p["model_found"], p["price_candidate_count"], p["stock_phrase_found"], p["matched_stock_phrase"]) == (True, 1, False, "")


def test_3_model_missing():
    p = R.parse_sony_store(page(f"<div>{A1II} 当日出荷 990,000円(税込)</div>"), A7RV)
    assert R.classify(rec(533500), p) == "failed"
    assert (p["model_found"], p["price_candidate_count"], p["stock_phrase_found"]) == (False, 0, False)


def test_4_price_missing():
    p = R.parse_sony_store(page(f"<div>{A7RV} 在庫あり</div>"), A7RV)
    assert R.classify(rec(533500), p) == "failed"
    assert (p["model_found"], p["price_candidate_count"], p["stock_phrase_found"]) == (True, 0, False)


def test_5_multiple_price_candidates_keep_existing_fail_close():
    h = page(f"<div>{A7RV} 在庫あり 533,500円(税込)</div><div>{A7RV} 入荷待ち 499,000円(税込)</div>")
    p = R.parse_sony_store(h, A7RV)
    assert R.classify(rec(533500), p) == "failed" and p["price"] is None
    assert p["price_candidate_count"] >= 2 and p["model_found"] is True
    assert p["matched_stock_phrase"] == ""                              # 在庫語が 2 種類（どれとも決められない）→ 空


def test_6_sale_ended_known_phrase():
    p = R.parse_sony_store(page(f"<div>{A7RV} 販売終了 533,500円(税込)</div>"), A7RV)
    assert R.classify(rec(533500), p) == "sale_ended"
    assert (p["stock_phrase_found"], p["matched_stock_phrase"], p["price_candidate_count"]) == (True, "販売終了", 1)


@pytest.mark.parametrize("model,row,price", [(A1II, "ILCE-1M2 当日出荷 990,000円(税込)", 990000),
                                             (A7CR, "ILCE-7CR/S 当日出荷 449,900円(税込)", 449900)])
@pytest.mark.parametrize("banner", ["top", "bottom", "none"])
def test_7_generic_banner_does_not_influence_a_normal_page(model, row, price, banner):
    p = R.parse_sony_store(page(f"<div>{row}</div>", banner=banner), model)
    assert R.classify(rec(price), p) == "unchanged" and p["price"] == price and p["stock"] == "在庫あり"
    assert p["stock_phrase_found"] is True and p["matched_stock_phrase"] == "当日出荷"


def test_7b_banner_never_becomes_a_sale_state_or_a_guard():
    """バナーがあっても、商品行に在庫語が無ければ従来どおり failed（バナーの有無で結果が変わらない）。バナーを根拠にした分岐はソースに無い。"""
    with_b = R.parse_sony_store(page(f"<div>{A7RV} 533,500円(税込)</div>", banner="top"), A7RV)
    without = R.parse_sony_store(page(f"<div>{A7RV} 533,500円(税込)</div>", banner="none"), A7RV)
    assert with_b == without
    assert "購入いただけません" not in inspect.getsource(R) and "購入いただけません" not in (ROOT / "src" / "market" / "official_registry.py").read_text(encoding="utf-8")


def test_product_page_form_diagnostics():
    h = f"<html><body>{A7RV} ソニーストアで購入すると 533,500円(税込) クーポン適用額をチェック (サインイン/新規登録) 在庫あり</body></html>"
    p = R.parse_sony_product(h, A7RV)
    assert R.classify(rec(533500), p) == "unchanged"
    assert (p["model_found"], p["price_candidate_count"], p["stock_phrase_found"], p["matched_stock_phrase"]) == (True, 1, True, "在庫あり")
    two = R.parse_sony_product(f"<html>{A7RV} ソニーストアで購入すると 533,500円(税込) 在庫あり ソニーストアで購入すると 499,000円(税込)</html>", A7RV)
    assert R.classify(rec(533500), two) == "failed" and two["price_candidate_count"] == 2
    none = R.parse_sony_product("<html>別の商品</html>", A7RV)
    assert R.classify(rec(533500), none) == "failed" and none["model_found"] is False and none["price_candidate_count"] == 0


# ── 8: 判定の不変（診断を足す前の実装との比較） ─────────────────────────────────────────

def _corpus() -> list[tuple[str, str]]:
    out = []
    stocks = ["", "在庫あり", "当日出荷", "翌日出荷", "入荷待ち", "在庫切れ", "販売終了", "予約受付中", "ご注文受付中（お届け未定）"]
    colors = ["", "/S（シルバー）", "/B", "/B（ブラック）"]
    for banner, st, color, price, extra in itertools.product(
            ("top", "bottom", "none"), stocks, colors, ("533,500", "990,000", "449,900", ""), ("", "dup", "dup2", "other_model")):
        row = f"{A7RV}{color} {st} {price}円(税込)".replace("  ", " ") if price else f"{A7RV}{color} {st}"
        body = f"<div>{row}</div>"
        if extra == "dup":
            body += f"<div>{row}</div>"
        elif extra == "dup2":
            body += f"<div>{A7RV}{color} 入荷待ち 499,000円(税込)</div>"
        elif extra == "other_model":
            body += f"<div>{A1II} 当日出荷 990,000円(税込)</div>"
        out.append((page(body, banner=banner), A7RV))
    out.append((page(f"<div>{A1II} 当日出荷 990,000円(税込)</div>"), A7RV))          # 型番が無い
    out.append(("", A7RV))
    out.append((page(""), A7RV))
    return out


def _product_corpus() -> list[tuple[str, str]]:
    out = []
    for stock, coupon, n in itertools.product(("", "在庫あり", "入荷待ち", "販売終了", "予約受付中"),
                                               ("", " クーポン適用額をチェック (サインイン/新規登録)"), (0, 1, 2)):
        body = "".join(f"ソニーストアで購入すると {p}円(税込){coupon} {stock} " for p in ("533,500", "499,000")[:n])
        out.append((f"<html>{A7RV} {body}</html>", A7RV))
    out.append((f"<html>{A7RV} {A7RV}/S 当日出荷 449,900円(税込)</html>", A7RV))        # 購入ページの形への戻り
    out.append(("<html>x</html>", A7RV))
    return out


def test_8_classification_invariance_against_the_pre_diagnostics_implementation():
    n = 0
    for h, model in _corpus():
        old, new = old_parse_sony_store(h, model), R.parse_sony_store(h, model)
        assert {k: new[k] for k in LEGACY_KEYS} == {k: old[k] for k in LEGACY_KEYS}, (h[:200], old, new)
        assert R.classify(rec(533500), new) == R.classify(rec(533500), old)
        assert R.classify(rec(1), new) == R.classify(rec(1), old)
        assert set(new) - set(old) == set(DIAG_KEYS) - set(old)          # 追加されたのは診断のキーだけ（model_found は既存）
        n += 1
    for h, model in _product_corpus():
        old, new = old_parse_sony_product(h, model), R.parse_sony_product(h, model)
        assert {k: new[k] for k in LEGACY_KEYS} == {k: old[k] for k in LEGACY_KEYS}, (h[:200], old, new)
        assert R.classify(rec(533500), new) == R.classify(rec(533500), old)
        n += 1
    assert n > 1000                                                      # 組み合わせが少なすぎて素通りしていない


def test_8b_diagnostics_cannot_affect_classification():
    """classify は診断のキーを読まない（ソース）。診断の値を書き換えても結果は変わらない。"""
    src = inspect.getsource(R.classify)
    for k in ("price_candidate_count", "stock_phrase_found", "matched_stock_phrase", "DIAG_KEYS"):
        assert k not in src
    for h, model in _corpus()[:400]:
        p = R.parse_sony_store(h, model)
        base = R.classify(rec(533500), p)
        for tamper in ({"stock_phrase_found": True, "matched_stock_phrase": "在庫あり", "price_candidate_count": 1},
                       {"stock_phrase_found": False, "matched_stock_phrase": "", "price_candidate_count": 9}):
            assert R.classify(rec(533500), {**p, **tamper}) == base
        stripped = {k: v for k, v in p.items() if k not in ("price_candidate_count", "stock_phrase_found", "matched_stock_phrase")}
        assert R.classify(rec(533500), stripped) == base


def test_recheck_call_signature_is_unchanged():
    """既存の呼び出し・テストの差し替え（`lambda now: …`）に影響しない（診断は引数ではなく LAST_DIAG に入れる）。"""
    assert list(inspect.signature(R.recheck).parameters) == ["now", "fetch", "sleep", "wait_first"]


def test_stale_diagnostics_from_a_previous_run_are_never_logged(monkeypatch, tmp_path, capsys):
    R.LAST_DIAG["prod_a7rv"] = {"model_found": False, "price_candidate_count": 9, "stock_phrase_found": True, "matched_stock_phrase": "在庫あり"}
    monkeypatch.setattr(R, "OUT", tmp_path / "official_recheck")
    monkeypatch.setattr(R, "recheck", lambda now: [_row("prod_a7rv", "failed")])      # 診断を入れない差し替え
    R.main([])
    assert "diag=" not in capsys.readouterr().out


def test_diagnostics_are_fixed_vocabulary_only():
    for h, model in _corpus()[::7] + _product_corpus():
        for fn in (R.parse_sony_store, R.parse_sony_product):
            p = fn(h, model)
            assert isinstance(p["model_found"], bool) and isinstance(p["stock_phrase_found"], bool)
            assert isinstance(p["price_candidate_count"], int) and not isinstance(p["price_candidate_count"], bool) and p["price_candidate_count"] >= 0
            assert p["matched_stock_phrase"] == "" or p["matched_stock_phrase"] in R._STOCK_WORDS


def test_parse_is_fast_on_a_large_page_with_many_models_and_no_price():
    """診断の正規表現が、型番の多いページ（価格が無い＝探索が失敗する形）で遅くならない（型番の直後 30 文字だけを見る。
    上限を外すと、型番ごとにページの末尾まで探して二次的に遅くなる: 3000 回で約 11 秒）。"""
    big = page("".join(f"<div>{A7RV} 説明 {'あ' * 40} </div>" for _ in range(3000)))
    t0 = time.monotonic()
    p = R.parse_sony_store(big, A7RV)
    assert time.monotonic() - t0 < 1.0
    assert (p["model_found"], p["price_candidate_count"], p["stock_phrase_found"]) == (True, 0, False)


def test_stock_vocabulary_and_aliases_are_pinned():
    """販売状態を確定する語彙（判定の契約）は変えない。診断のログの許可リストも同じ語彙。変えるときは、実際のページの確認と
    テストを伴う別の変更にする（診断の追加では変えない）。バナー「現在、選択した商品が購入いただけません。」は語彙に入れない。"""
    assert R._STOCK_WORDS == ("入荷待ち", "在庫切れ", "在庫あり", "販売終了", "翌日出荷", "当日出荷")
    assert R._STOCK_ALIAS == {"翌日出荷": "在庫あり", "当日出荷": "在庫あり"}
    assert not any("購入いただけません" in w for w in R._STOCK_WORDS)


# ── 2（続き）: 失敗しても確認日は進まない（recheck → 最終状態） ───────────────────────────────

def _fake_fetch(html_by_model: dict[str, str]):
    def fetch(url: str):
        for model, h in html_by_model.items():
            if f"/{model}/" in url:
                return h, ""
        return None, "timeout"
    return fetch


def _recheck(now: datetime, html: str, sink: dict | None = None) -> list[dict]:
    rows = R.recheck(now, fetch=_fake_fetch({A7RV: html}), sleep=lambda s: None, wait_first=False)
    if sink is not None:
        sink.update(R.LAST_DIAG)
    return rows


def test_failed_a7rv_does_not_advance_the_verification_date():
    from src.market.official_registry import derive_last_state
    ok = page(f"<div>{A7RV} 在庫あり 533,500円(税込)</div>")
    shape = page(f"<div>{A7RV} 533,500円(税込)</div>")
    hist = []
    for d in range(1, 5):                                                 # 11-01〜11-04: unchanged
        hist += [r for r in _recheck(datetime(2026, 11, d, 20, 47, tzinfo=JST), ok) if r["product_id"] == "prod_a7rv"]
    sink: dict = {}
    for d in range(5, 13):                                                # 11-05〜11-12: 現在の形（在庫語なし）
        hist += [r for r in _recheck(datetime(2026, 11, d, 20, 47, tzinfo=JST), shape, sink) if r["product_id"] == "prod_a7rv"]
    assert [r["status"] for r in hist] == ["unchanged"] * 4 + ["failed"] * 8
    assert all(r["price"] is None and r["reason"] == "" for r in hist[4:])
    st = derive_last_state(hist, date(2026, 11, 12))["prod_a7rv"]
    assert st["last_verified_at"] == "2026-11-04"                         # 進まない（偽の鮮度なし）
    assert st["last_recheck_result"] == "failed"
    assert sink["prod_a7rv"] == {"model_found": True, "price_candidate_count": 1, "stock_phrase_found": False, "matched_stock_phrase": ""}


# ── 9: 公開データの形は変えない ───────────────────────────────────────────────────────────

EXPECTED_ROW_KEYS = {"product_id", "url", "model", "match", "recorded_price", "observed_at", "status", "reason", "price", "stock"}


def test_9_recheck_rows_never_contain_diagnostic_keys():
    sink: dict = {}
    for h in (page(f"<div>{A7RV} 533,500円(税込)</div>"), page(f"<div>{A7RV} 在庫あり 533,500円(税込)</div>"),
              page(f"<div>{A7RV} 在庫あり 999,000円(税込)</div>"), page(f"<div>{A7RV} 販売終了 533,500円(税込)</div>"), ""):
        for r in _recheck(datetime(2026, 11, 12, 20, 0, tzinfo=JST), h, sink):
            assert not (set(r) & set(DIAG_KEYS))
            assert set(r) - {"fetched_url", "verified_by"} == EXPECTED_ROW_KEYS


def test_9b_public_row_strips_diagnostic_keys_from_any_source():
    row = {"product_id": "p", "status": "failed", "price": None, "reason": "", "stock": "", **{k: True for k in DIAG_KEYS}}
    assert set(R._public_row(row)) == {"product_id", "status", "price", "reason", "stock"}


def _patch_main(monkeypatch, tmp_path, rows, diag):
    monkeypatch.setattr(R, "OUT", tmp_path / "official_recheck")
    monkeypatch.setattr(R, "recheck", lambda now: (R.LAST_DIAG.update(diag), rows)[1])


def test_9c_main_writes_no_diagnostic_keys_to_history_or_latest(monkeypatch, tmp_path, capsys):
    base = {"product_id": "prod_a7rv", "url": "https://pur.store.sony.jp/x/", "model": A7RV, "match": A7RV, "recorded_price": 533500,
            "observed_at": datetime.now(tz=JST).isoformat(timespec="seconds"), "status": "failed", "reason": "", "price": None, "stock": ""}
    # 診断のキーが行に混ざっても（将来の変更で誤って入っても）、保存しない
    rows = [{**base, **{"model_found": True, "price_candidate_count": 1, "stock_phrase_found": False, "matched_stock_phrase": ""}}]
    _patch_main(monkeypatch, tmp_path, rows, {"prod_a7rv": {"model_found": True, "price_candidate_count": 1, "stock_phrase_found": False, "matched_stock_phrase": ""}})
    assert R.main([]) == 0
    for name in ("history.json", "latest.json"):
        text = (tmp_path / "official_recheck" / name).read_text(encoding="utf-8")
        for k in ("price_candidate_count", "stock_phrase_found", "matched_stock_phrase", "model_found"):
            assert k not in text, (name, k)
    hist = json.loads((tmp_path / "official_recheck" / "history.json").read_text(encoding="utf-8"))["results"]
    assert set(hist[0]) == EXPECTED_ROW_KEYS - {"fetched_url", "verified_by"}
    assert set(json.loads((tmp_path / "official_recheck" / "latest.json").read_text(encoding="utf-8"))) == {"generated_at", "results", "plan"}


def test_9d_committed_public_files_have_no_diagnostic_keys():
    for name in ("history.json", "latest.json"):
        f = ROOT / "exports" / "official_recheck" / name
        if f.exists():
            text = f.read_text(encoding="utf-8")
            for k in ("price_candidate_count", "stock_phrase_found", "matched_stock_phrase"):
                assert k not in text, (name, k)


# ── 10: ログ（failed の行だけ・固定形式・個別のページの内容を出さない） ─────────────────────────

FAILED_LINE = ("[公式の再確認] prod_a7rv: failed 価格 None 在庫 — "
               "diag=model_found:true price_candidates:1 stock_phrase_found:false matched_stock:none")


def _row(pid, status, reason="", price=None, stock=""):
    return {"product_id": pid, "url": "https://example.invalid/x", "model": "m", "match": "m", "recorded_price": 1,
            "observed_at": datetime.now(tz=JST).isoformat(timespec="seconds"), "status": status, "reason": reason, "price": price, "stock": stock}


def test_10_failed_log_line_is_fixed_format(monkeypatch, tmp_path, capsys):
    d = {"model_found": True, "price_candidate_count": 1, "stock_phrase_found": False, "matched_stock_phrase": ""}
    _patch_main(monkeypatch, tmp_path, [_row("prod_a7rv", "failed")], {"prod_a7rv": d})
    R.main([])
    assert capsys.readouterr().out.strip() == FAILED_LINE
    for dd, expect in (({"model_found": False, "price_candidate_count": 0, "stock_phrase_found": False, "matched_stock_phrase": ""},
                        "model_found:false price_candidates:0 stock_phrase_found:false matched_stock:none"),
                       ({"model_found": True, "price_candidate_count": 2, "stock_phrase_found": True, "matched_stock_phrase": "在庫あり"},
                        "model_found:true price_candidates:2 stock_phrase_found:true matched_stock:在庫あり")):
        _patch_main(monkeypatch, tmp_path, [_row("prod_a7rv", "failed")], {"prod_a7rv": dd})
        R.main([])
        assert capsys.readouterr().out.strip().endswith("diag=" + expect)


def test_10b_log_volume_only_failed_parser_rows_get_diagnostics(monkeypatch, tmp_path, capsys):
    d = {"model_found": True, "price_candidate_count": 1, "stock_phrase_found": True, "matched_stock_phrase": "在庫あり"}
    rows = [_row("a", "unchanged", price=1, stock="在庫あり"), _row("b", "changed", price=2), _row("c", "sale_ended"),
            _row("d", "blocked", reason="site_blocked"), _row("e", "failed", reason="timeout"), _row("f", "failed")]
    _patch_main(monkeypatch, tmp_path, rows, {k: d for k in "abcdef"})
    R.main([])
    out = capsys.readouterr().out.splitlines()
    assert [("diag=" in ln) for ln in out] == [False, False, False, False, False, True]   # 成功・遮断・取得の失敗（理由あり）には付けない
    assert "（timeout）" in out[4] and "（site_blocked）" in out[3]


def test_10c_log_never_contains_page_content_url_or_secrets(monkeypatch, tmp_path, capsys):
    hostile = ("https://shop.example/path?token=SECRET123&session=abc", "<html><script>x</script></html>", "Set-Cookie: sid=1",
               "Authorization: Bearer abc", "/hostile/local/path", "予約受付中（未知の語）")
    for h in hostile:
        d = {"model_found": True, "price_candidate_count": 1, "stock_phrase_found": False, "matched_stock_phrase": h,
             "html": h, "url": h, "headers": h, "raw": h}
        _patch_main(monkeypatch, tmp_path, [_row("prod_a7rv", "failed")], {"prod_a7rv": d})
        R.main([])
        out = capsys.readouterr().out.strip()
        assert out == FAILED_LINE, out                                      # 許可リスト外の値は none。未知のキーは出さない
        for bad in ("SECRET", "token", "cookie", "Cookie", "Bearer", "/hostile", "<html", "未知の語", "予約受付中", "http"):
            assert bad not in out
    for bad_diag in ({"model_found": "true", "price_candidate_count": 1, "stock_phrase_found": False, "matched_stock_phrase": ""},
                     {"model_found": True, "price_candidate_count": True, "stock_phrase_found": False, "matched_stock_phrase": ""},
                     {"model_found": True, "price_candidate_count": -1, "stock_phrase_found": False, "matched_stock_phrase": ""},
                     {"model_found": True}, {}, None):
        assert R._diag_suffix(bad_diag) == ""                               # 形が違う診断は何も付けない


def test_10e_diag_suffix_is_strict_and_never_raises():
    """型を厳密に見る。bool を int として通さない・サブクラス・巨大な整数・語彙の別名や連結・例外を投げる値でも、例外にせず固定形式か空。"""
    class EvilStr(str):
        def __format__(self, spec):  # 出力に混ぜようとする
            return "https://evil.example/?token=SECRET"

        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    class EvilInt(int):
        def __str__(self):
            return "SECRET"

    class Boom:
        def __eq__(self, other):
            raise RuntimeError("boom")

    ok = {"model_found": True, "price_candidate_count": 1, "stock_phrase_found": False, "matched_stock_phrase": ""}
    assert R._diag_suffix(ok).endswith("matched_stock:none")
    for bad in ({**ok, "price_candidate_count": EvilInt(1)}, {**ok, "price_candidate_count": 10 ** 5000},
                {**ok, "price_candidate_count": 1_000_001}, {**ok, "price_candidate_count": True},
                {**ok, "model_found": 1}, {**ok, "stock_phrase_found": "false"}):
        assert R._diag_suffix(bad) == ""
    for evil in (EvilStr("在庫あり"), EvilStr("x"), "在庫あり 在庫切れ", "在庫あり\n", " 在庫あり", Boom()):
        out = R._diag_suffix({**ok, "matched_stock_phrase": evil})
        assert out == "" or out.endswith("matched_stock:none"), out
        assert "SECRET" not in out and "evil" not in out and "\n" not in out
    assert R._diag_suffix({**ok, "matched_stock_phrase": "在庫あり"}).endswith("matched_stock:在庫あり")
    assert R._diag_suffix({**ok, "matched_stock_phrase": "当日出荷"}).endswith("matched_stock:当日出荷")


def test_10f_logging_failure_never_breaks_the_recheck_run(monkeypatch, tmp_path, capsys):
    """診断の整形で何が起きても（例外）、再確認は止まらない: 履歴は保存され、終了コードは 0、診断は付かない。"""
    class BoomDict(dict):
        def __getitem__(self, k):
            raise RuntimeError("boom")

    ok = {"model_found": True, "price_candidate_count": 1, "stock_phrase_found": False, "matched_stock_phrase": ""}
    assert R._diag_suffix(BoomDict(ok)) == ""
    monkeypatch.setattr(R, "_STOCK_WORDS", object())                       # 語彙の走査で例外になる
    assert R._diag_suffix({**ok, "matched_stock_phrase": "在庫あり"}) == ""
    monkeypatch.undo()
    # main の中でも: 診断が例外を起こす形でも、履歴・latest は書かれ、終了コード 0
    monkeypatch.setattr(R, "OUT", tmp_path / "official_recheck")
    monkeypatch.setattr(R, "recheck", lambda now: (R.LAST_DIAG.update({"prod_a7rv": BoomDict(ok)}), [_row("prod_a7rv", "failed")])[1])
    assert R.main([]) == 0
    assert (tmp_path / "official_recheck" / "history.json").exists() and (tmp_path / "official_recheck" / "latest.json").exists()
    assert "diag=" not in capsys.readouterr().out


def test_10d_a_real_run_through_recheck_logs_only_fixed_metadata(monkeypatch, tmp_path, capsys):
    """fake fetch → 実際の recheck → main のログ。ページに URL・秘密らしい文字列があっても、ログには出ない。"""
    h = page(f"<div>{A7RV} 533,500円(税込)</div><a href='https://evil.example/?token=SECRET123'>x</a><p>Set-Cookie: sid=1</p>")
    monkeypatch.setattr(R, "OUT", tmp_path / "official_recheck")
    monkeypatch.setattr(R, "_fetch", _fake_fetch({A7RV: h}))
    monkeypatch.setattr(R, "_host_interval", lambda url: 0.0)
    real_recheck = R.recheck
    monkeypatch.setattr(R, "recheck", lambda now: real_recheck(now, fetch=_fake_fetch({A7RV: h}), sleep=lambda s: None, wait_first=False))
    R.main([])
    out = capsys.readouterr().out
    line = [ln for ln in out.splitlines() if "prod_a7rv" in ln][0]
    assert line == FAILED_LINE
    for bad in ("SECRET", "token", "evil.example", "Cookie", "http"):
        assert bad not in out
    assert "diag=" not in "".join(ln for ln in out.splitlines() if "prod_a7rv" not in ln)      # 他の商品（取得失敗など）には付かない
