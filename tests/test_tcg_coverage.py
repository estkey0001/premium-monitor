# -*- coding: utf-8 -*-
"""TCG Coverage Expansion（2026-11-23）: 森森買取のパース・買取停止中の行・名前の照合（name_contains）・追加した対象商品の整合。"""
from datetime import datetime
from pathlib import Path

import yaml

from src.tcg import buyback as bb
from tests.test_tcg_buyback import CFG, NOW, art, page, row

JST = bb.JST
ROOT = Path(__file__).resolve().parent.parent
REAL_CFG = yaml.safe_load((ROOT / "config" / "tcg_buyback.yaml").read_text(encoding="utf-8"))


def _ean_ok(j: str) -> bool:
    d = [int(c) for c in j]
    return len(d) == 13 and (10 - sum(x * (3 if i % 2 else 1) for i, x in enumerate(d[:-1])) % 10) % 10 == d[-1]


# ── 買取停止中（ルデヤの「お申込一時停止中」） ──
def _stopped_art(name, price, jan):
    return art(name, price, jan).replace("</article>", '<span class="product-card-stopped">お申込一時停止中</span></article>')


def test_rudeya_stopped_row_is_listed_but_never_executable():
    html = page(_stopped_art("デッキセット", 8000, "4500000000111"), art("拡張パック BOX [M7]", 6000, "4500000000222"))
    rows = bb.parse_rudeya(html, "https://r.example/c", NOW)["rows"]
    assert rows[0].get("suspended") is True and "suspended" not in rows[1]
    ann = {r["jan"]: r for r in bb.annotate([{**r, "page_asof": NOW.isoformat()} for r in rows], CFG, NOW)}
    assert ann["4500000000111"]["identity_status"] == "CONFIRMED" and ann["4500000000111"]["executable"] is False
    assert ann["4500000000222"]["executable"] is True


def test_stopped_only_product_has_no_executable_price_and_no_profit():
    r = {**bb.parse_rudeya(page(_stopped_art("デッキセット", 8000, "4500000000111")), "u", NOW)["rows"][0], "page_asof": NOW.isoformat()}
    ann = bb.annotate([r], CFG, NOW)
    s = bb.summarize_product("deck", ann, CFG, 6000)
    assert s["status"] == "LISTED_ONLY" and s["highest_executable"] is None
    assert bb.profit_for(s, {"retail_price": 6000}, CFG)["status"] == bb.NOT_CALCULATED


# ── 名前の照合 ──
def test_name_contains_blocks_a_same_jan_row_with_a_different_name():
    cfg = {**CFG, "targets": [{**CFG["targets"][0], "name_contains": ["エーフィ"]}]}
    ok = bb.annotate([row(name="デッキセット エーフィ・ブラッキー")], cfg, NOW)[0]
    ng = bb.annotate([row(name="デッキセット 別の商品")], cfg, NOW)[0]
    assert ok["identity_status"] == "CONFIRMED"
    assert ng["identity_status"] == "NAME_MISMATCH" and ng["executable"] is False and ng["product_id"] is None


# ── 森森買取 ──
MM_ADD = '<button type="button" class="mm1551-add" data-mm1551-quick-add data-product-id="1">追加</button>'


def _mm(name, jan, price_html, note="", badge="新品", flg="0", pid="351067", action=MM_ADD):
    nt = f'<span class="note"><span class="notetip">{note}</span></span>' if note else ""
    return (f'<div class="mm1551-prow" data-mm1551-product-id="{pid}" data-price-disp-flg="{flg}">'
            f'<div class="mm1551-prow__name"><a href="/category/2403/product/{pid}">{name}</a></div>'
            f'<div class="mm1551-prow__meta">JAN:{jan}</div><div class="pmeta"><span class="rk">{badge}</span>{nt}</div>'
            f'<div class="mm1551-prow__price"><div class="mm1551-prow__cur"><span class="mm1551-prow__cur-label">現在価格</span>{price_html}</div>'
            f'<div class="mm1551-prow__keep">預かり(3カ月) <span class="mm1551-prow__keep-val">8,524</span>円</div></div>{action}</div>')


MM_HTML = ('<html><body><h1>ONE PIECE 買取 2026年11月23日 更新</h1>'
           + _mm("【BOX】OP-18 神の支配", "4582770067194", '<span class="mm1551-prow__cur-val">8,400</span>円',
                 note="未開封BOX/テープ付\n\n※不正品が発覚した場合…")
           + _mm("【BOX】OP-14 蒼海の七傑", "4582769922978", '<span class="mm1551-prow__cur-val">9,200</span>円', pid="318653")
           + _mm("プレミアムカードコレクション イベント限定", "4582769843532", "ASK", flg="1", pid="331608")
           + "</section></body></html>")


def test_parse_morimori_uses_current_price_only_and_skips_ask():
    r = bb.parse_morimori(MM_HTML, "https://www.morimori-kaitori.jp/category/2403", NOW)
    assert r["updated"] == "2026-11-23" and len(r["rows"]) == 2
    a = r["rows"][0]
    assert a["price"] == 8400 and a["jan"] == "4582770067194" and a["shop"] == "morimori"      # 預かり 8,524 は使わない
    assert a["condition"] == bb.C_UNOPENED and a["source_updated_at"] == "2026-11-23"
    assert a["item_url"] == "https://www.morimori-kaitori.jp/category/2403/product/351067"
    assert "不正品" not in a["condition_text"]
    assert r["rows"][1]["condition"] == bb.C_NEW                 # 未開封と書かれていない行は「新品」だけ = 実行可能にしない


def test_parse_morimori_empty_or_broken_page_makes_no_rows():
    assert bb.parse_morimori("", "u", NOW)["rows"] == []
    assert bb.parse_morimori("<html>ASK</html>", "u", NOW)["rows"] == []


def test_morimori_row_is_executable_only_with_unopened_note_and_fresh_date():
    cfg = {**CFG, "shops": {**CFG["shops"], "morimori": {"name": "森森買取", "freshness_basis": "page_date"}},
           "targets": [{"product_id": "op18", "tcg": "ONE_PIECE", "name": "OP-18", "unit": "BOX", "jan": "4582770067194"}]}
    rows = bb.parse_morimori(MM_HTML, "u", datetime(2026, 11, 23, 12, 0, tzinfo=JST))["rows"]
    ann = bb.annotate(rows, cfg, datetime(2026, 11, 23, 12, 5, tzinfo=JST))
    assert [r["executable"] for r in ann if r["product_id"] == "op18"] == [True]
    stale = bb.annotate(rows, cfg, datetime(2026, 11, 23, 19, 59, tzinfo=JST))
    assert stale[0]["executable"] is True                          # 8 時間以内
    old = bb.annotate([{**rows[0], "source_updated_at": "2026-11-20"}], cfg, datetime(2026, 11, 23, 12, 5, tzinfo=JST))
    assert old[0]["executable"] is False                           # 更新日が古い


# ── 追加した対象商品の整合 ──
def test_all_targets_have_valid_ean13_unique_jan_and_unique_product_id():
    ts = REAL_CFG["targets"]
    assert len({t["jan"] for t in ts}) == len(ts) and len({t["product_id"] for t in ts}) == len(ts)
    for t in ts:
        assert _ean_ok(t["jan"]), t["product_id"]
        assert t["unit"] in bb.UNITS and t["tcg"] in ("POKEMON", "ONE_PIECE")


def test_new_targets_require_name_tokens_and_morimori_is_not_a_profit_route():
    new = [t for t in REAL_CFG["targets"] if t.get("name_contains")]
    assert len(new) >= 14 and all(len(t["name_contains"]) >= 1 for t in new)
    assert "morimori" not in REAL_CFG["route_costs"]["store_counter"]["shops_supporting"]
    assert REAL_CFG["shops"]["morimori"]["freshness_basis"] == "page_date"


def test_one_unit_each_target_does_not_conflict_with_store_names():
    # 店の商品名に書かれる単位（BOX / セット）と、対象の単位が食い違う設定は作らない
    for t in REAL_CFG["targets"]:
        seen = bb.units_in(t["name"])
        assert not seen or seen == {t["unit"]}, (t["product_id"], seen, t["unit"])


# ── 独立レビュー（2026-11-23）の指摘 ──
def test_dedupe_is_order_independent_when_one_same_price_row_is_suspended():
    base = {**row(price=8000), "page_asof": NOW.isoformat()}
    sus = {**base, "suspended": True, "suspended_text": "お申込一時停止中"}
    for rows in ([sus, base], [base, sus]):
        got = bb.annotate(rows, CFG, NOW)
        assert len(got) == 1 and got[0]["executable"] is False and got[0]["suspended"] is True


def test_suspended_rows_never_enter_history_or_price_events():
    r = {**row(price=9500), "page_asof": NOW.isoformat(), "suspended": True}
    ann = bb.annotate([r], CFG, NOW)
    assert bb.update_history([], ann, "2026-11-21") == []
    prev = [{"product_id": "deck", "shop": "rudeya", "unit": "SET", "condition": bb.C_UNOPENED, "price": 8000,
             "checked_at": "2026-11-20T12:00:00+09:00", "date": "2026-11-20"}]
    assert bb.price_events(prev, ann, "2026-11-21", CFG) == []             # 停止中の価格で BUYBACK_SURGE を出さない


def test_suspended_listed_price_is_labelled_on_the_hub_view():
    from src.tcg.hub import product_view as pv
    r = {**row(price=8000), "page_asof": NOW.isoformat(), "suspended": True}
    ann = bb.annotate([r], CFG, NOW)
    view, pr = pv._buyback_for("deck", ann, CFG, NOW, {"retail_price": 6000})
    assert view["highest_executable"] is None and view["highest_listed"]["suspended"] is True
    assert pr["status"] == "NOT_CALCULATED"


def test_morimori_update_date_comes_from_before_the_price_table_only():
    html = ("<html><body><p>2026年11月01日 更新のお知らせ</p><h1>2026年11月23日 更新</h1>"
            + _mm("【BOX】OP-18 神の支配", "4582770067194", '<span class="mm1551-prow__cur-val">8,400</span>円', note="未開封BOX/テープ付")
            + "<footer>2026年12月31日 更新</footer></body></html>")
    # 価格表より前の最初の日付を採る（お知らせが先にあれば古い側 = STALE に倒れる。フッターの日付は採らない）
    assert bb.parse_morimori(html, "u", NOW)["updated"] == "2026-11-01"


# ── 森森買取の受付状態（fail-closed） ──
import pytest  # noqa: E402


@pytest.mark.parametrize("action", [
    "",
    '<button type="button" class="mm1551-add" data-mm1551-quick-add disabled>追加</button>',
    '<button type="button" class="mm1551-add" data-mm1551-quick-add hidden>追加</button>',
    '<button type="button" class="x">お気に入り</button>',
    '<span>現在、買取を休止しております</span>' + MM_ADD,
])
def test_morimori_without_an_explicit_active_signal_is_never_executable(action):
    html = "<html><body><h1>2026年11月23日 更新</h1>" + _mm("【BOX】OP-18 神の支配", "4582770067194", '<span class="mm1551-prow__cur-val">8,400</span>円',
                                                           note="未開封BOX/テープ付", action=action) + "</section></body></html>"
    rows = bb.parse_morimori(html, "u", datetime(2026, 11, 23, 12, 0, tzinfo=JST))["rows"]
    assert rows[0]["accept_state"] in (bb.A_STOPPED, bb.A_UNKNOWN) and rows[0].get("suspended") is True
    cfg = {**REAL_CFG}
    ann = bb.annotate(rows, cfg, datetime(2026, 11, 23, 12, 5, tzinfo=JST))
    assert all(r["executable"] is False for r in ann)


def test_condition_note_saying_unbuyable_does_not_stop_an_active_morimori_row():
    r = bb.parse_morimori(MM_HTML.replace("未開封BOX/テープ付", "未開封BOX/テープ付 買取不可の場合あり"), "u", NOW)["rows"][0]
    assert r["accept_state"] == bb.A_ACTIVE


def test_rudeya_stop_detection_survives_quote_and_wording_changes():
    from tests.test_tcg_opportunities import _rows
    for action in ("<span class='product-card-stopped'>x</span>", "<button class='b'>買取リクエスト</button><span>現在受付しておりません</span>",
                   "<button class='b'>買取リクエスト</button><span>買取休止中</span>", "<button class='b'>買取リクエスト</button><span>取扱終了</span>",
                   '<button onclick="if(a>b)x()" disabled>買取リクエスト</button>',
                   '<button style="display:none">買取リクエスト</button>'):
        assert _rows(action)[0]["accept_state"] != bb.A_ACTIVE, action


def test_price_events_skip_non_executable_and_outlier_products():
    hist = [{"product_id": "a", "shop": "s", "unit": "BOX", "condition": "UNOPENED", "price": 1000, "date": "2026-11-22"},
            {"product_id": "b", "shop": "s", "unit": "BOX", "condition": "NEW", "price": 1000, "date": "2026-11-22"},
            {"product_id": "c", "shop": "s", "unit": "BOX", "condition": "UNOPENED", "price": 1000, "date": "2026-11-22"}]
    mk = lambda pid, cond, ex: {"identity_status": "CONFIRMED", "product_id": pid, "shop": "s", "unit": "BOX", "condition": cond, "price": 5000,
                                "freshness": "FRESH", "executable": ex}
    rows = [mk("a", "UNOPENED", True), mk("b", "NEW", False), mk("c", "UNOPENED", True)]
    ev = bb.price_events(hist, rows, "2026-11-23", {}, skip_products={"c"})
    assert [e["product_id"] for e in ev] == ["a"]


# ── 森森買取のポケモン MEGA 一覧（2026-11-26 追加） ──
MM_POKE = (ROOT / "tests" / "fixtures" / "morimori" / "pokemon_mega_2401010.html").read_text(encoding="utf-8")
MM_POKE_URL = "https://www.morimori-kaitori.jp/category/2401010"


def test_morimori_pokemon_mega_page_parses_rows_with_jan_and_current_price():
    r = bb.parse_morimori(MM_POKE, MM_POKE_URL, NOW)
    assert r["updated"] == "2026-11-26"
    got = {x["jan"]: x for x in r["rows"]}
    assert got["4521329431529"]["price"] == 15300 and got["4521329431161"]["price"] == 6800      # 預かり・即フリの価格は使わない
    assert all(x["accept_state"] == bb.A_ACTIVE for x in r["rows"])
    assert got["4521329431529"]["item_url"].startswith("https://www.morimori-kaitori.jp/category/2401010/product/")


def test_morimori_pokemon_shrink_rejection_note_is_new_not_opened_and_never_executable():
    # 「シュリンクの破れ…はお断り」は買取を断る基準の説明で、その商品が開封済みという意味ではない。「新品」だけ = NEW（表示のみ）
    rows = bb.parse_morimori(MM_POKE, MM_POKE_URL, datetime(2026, 11, 26, 12, 0, tzinfo=JST))["rows"]
    assert {x["condition"] for x in rows} == {bb.C_NEW}
    ann = bb.annotate(rows, REAL_CFG_LOADED, datetime(2026, 11, 26, 12, 5, tzinfo=JST))
    mine = [x for x in ann if x["product_id"] in ("pokemon-拡張パック-インフェルノx", "pokemon-拡張パック-メガブレイブ")]
    assert len(mine) == 2 and all(x["identity_status"] == "CONFIRMED" and x["freshness"] == bb.FRESH for x in mine)
    assert all(x["executable"] is False for x in mine)                       # 未開封の根拠が無いので最高買取（実行可能）・利益に数えない
    s = bb.summarize_product("pokemon-拡張パック-インフェルノx", ann, REAL_CFG_LOADED)
    assert s["status"] == "LISTED_ONLY" and s["highest_executable"] is None and s["highest_listed"]["price"] == 15300


def test_morimori_policy_note_never_turns_a_row_into_executable():
    # 否定の語を含む行は、お断りの文を除いても実行可能な条件には上げない（緩める方向に使わない）
    note = "未開封BOX/テープ付。シュリンク無し商品の買取はお問い合わせください"
    assert bb._morimori_condition(note, "【BOX】OP-18", "新品") == bb.C_OPENED
    assert bb._morimori_condition("未開封BOX/テープ付", "【BOX】OP-18", "新品") == bb.C_UNOPENED
    assert bb._morimori_condition("開封済みの商品です", "BOX", "新品") == bb.C_OPENED


def test_morimori_pokemon_mega_page_is_one_page_and_new_targets_have_name_guard():
    pages = REAL_CFG["shops"]["morimori"]["pages"]
    assert "https://www.morimori-kaitori.jp/category/2401010" in pages
    assert not any("page=" in p for p in pages)                                # ページ送りの全件は取らない
    t = {x["product_id"]: x for x in REAL_CFG["targets"]}
    assert t["pokemon-拡張パック-インフェルノx"]["jan"] == "4521329431529" and t["pokemon-拡張パック-インフェルノx"]["name_contains"] == ["インフェルノX"]
    assert t["pokemon-拡張パック-メガブレイブ"]["jan"] == "4521329431161" and t["pokemon-拡張パック-メガブレイブ"]["name_contains"] == ["メガブレイブ"]


REAL_CFG_LOADED = bb.load_config()
