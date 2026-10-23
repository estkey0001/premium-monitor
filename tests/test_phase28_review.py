"""Phase 28（発見の候補の確認と正本への登録）のテスト。

承認（APPROVED）と登録（REGISTERED）を分ける・登録は承認済みの候補を1件ずつ・既定は dry-run・commit / push しない・
重複を登録しない・日程は人が確かめた値だけ、を確かめる。ネットワークには出ない。本物の正本（config/products.yaml・
data/tcg_verified_lotteries.csv）は変えない。各テストに否定の対照を付ける。
"""
from __future__ import annotations

import copy
import csv
import io
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml

from src.discovery import apple
from src.discovery import register as rg
from src.discovery import store as st
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 17, 15, 0, tzinfo=JST)
REAL_CANON = (ROOT / "config" / "products.yaml").read_text(encoding="utf-8")
REAL_CSV = (ROOT / "data" / "tcg_verified_lotteries.csv").read_text(encoding="utf-8")


def prod(sku, part, price, name, cat="iphone"):
    return (f'{{"sku":"{sku}","partNumber":"{part}","price":{{"fullPrice":{price}.00}},"category":"{cat}",'
            f'"name":"{name}"}}')


def page(*items):
    return '<script>{"products":[' + ",".join(items) + "]}</script>"


LIST = ('<a href="/jp/shop/buy-iphone/iphone-17">iPhone 17</a>'
        '<a href="/jp/shop/buy-iphone/iphone-air">iPhone Air</a>')
P17 = page(prod("MG6A4", "MG6A4J/A", 159800, "iPhone 17 256GB Lavender"),
           prod("MG6D4", "MG6D4J/A", 194800, "iPhone 17 512GB Black"))
PAIR = page(prod("MG274", "MG274J/A", 189800, "iPhone Air 256GB Sky Blue"),
            prod("MG284", "MG284J/A", 189800, "iPhone Air 256GB Space Black"),
            prod("MG2G4", "MG2G4J/A", 294800, "iPhone Air 1TB Cloud White"),
            prod("MG2H4", "MG2H4J/A", 299800, "iPhone Air 1TB Light Gold"))      # 1TB は色で価格が違う（登録しない）
CANON = """products:
  # =========================================
  # iPhone 17 シリーズ
  # =========================================
  - id: "prod_iphone17_256"
    genre: "iphone"
    name: "iPhone 17 256GB SIMフリー"
    brand: "Apple"
    retail_price: 139800
    keywords: ["iPhone 17", "iPhone17", "iPhone 17 256"]

  - id: "prod_iphone17pro_256"
    genre: "iphone"
    name: "iPhone 17 Pro 256GB SIMフリー"
    brand: "Apple"
    retail_price: 179800
    keywords: ["iPhone 17 Pro"]

  # =========================================
  # カメラ
  # =========================================
  - id: "prod_x100vi"
    genre: "camera"
    name: "FUJIFILM X100VI"
    brand: "FUJIFILM"
    model_number: "X100VI"
    retail_price: 315700
    keywords: ["X100VI"]
"""


@pytest.fixture
def env(tmp_path):
    y = tmp_path / "products.yaml"
    y.write_text(CANON, encoding="utf-8")
    pages = {apple.LIST_URL: LIST, apple.FAMILY_URL.format(slug="iphone-17"): P17,
             apple.FAMILY_URL.format(slug="iphone-air"): PAIR}

    def fetch(url):
        return (pages.get(url), "" if url in pages else "not_found")
    out = tmp_path / "out"
    apple.run(out, y, now=NOW, fetch=fetch)
    return out, y, fetch


def cands(out):
    return st.load(out / st.PRODUCT_FILE)["candidates"]


def cid_of(out, name):
    return next(k for k, v in cands(out).items() if v["product_name"] == name)


def approve(out, cid, checked=("official_url", "part_numbers", "capacity", "official_price")):
    return st.decide(out / st.PRODUCT_FILE, cid, "approve", now=NOW, evidence_checked=checked)


def unchanged_real():
    assert (ROOT / "config" / "products.yaml").read_text(encoding="utf-8") == REAL_CANON
    assert (ROOT / "data" / "tcg_verified_lotteries.csv").read_text(encoding="utf-8") == REAL_CSV


# ── 承認・却下（台帳だけ）────────────────────────────────────────────────────

def test_lifecycle_statuses_and_registered_is_human_decided():
    for s in (st.NEW, st.PENDING_REVIEW, st.APPROVED, st.REJECTED, st.STALE, st.MATCHED_EXISTING, st.REGISTERED):
        assert s in st.STATUSES
    assert st.REGISTERED in st.HUMAN_DECIDED and st.DB_STATUS[st.REGISTERED] == "approved"
    assert st.PENDING_REVIEW not in st.HUMAN_DECIDED                                   # 対照


def test_approval_records_audit_trail_without_personal_data(env):
    out, y, _f = env
    cid = cid_of(out, "iPhone Air 256GB")
    rec = approve(out, cid)
    assert rec["status"] == st.APPROVED and rec["review"]["evidence_checked"] == sorted(
        ["official_url", "part_numbers", "capacity", "official_price"])
    assert rec["decisions"][-1]["decision"] == st.APPROVED and rec["decisions"][-1]["at"].startswith("2026-10-17")
    assert set(rec["decisions"][-1]) <= {"at", "decision", "reason", "evidence_checked"}   # 名前・メールを残さない
    assert y.read_text(encoding="utf-8") == CANON                                      # 承認だけでは正本を変えない
    with pytest.raises(ValueError):
        approve(out, cid, checked=("made_up",))                                        # 知らない証拠の種類は受けない


def test_reject_reason_kept_and_not_reopened(env):
    out, y, fetch = env
    cid = cid_of(out, "iPhone 17 512GB")
    with pytest.raises(ValueError):
        st.decide(out / st.PRODUCT_FILE, cid, "reject", now=NOW, reason="because")      # 決めた理由の中から
    rec = st.decide(out / st.PRODUCT_FILE, cid, "reject", now=NOW, reason="not_target")
    assert rec["status"] == st.REJECTED and rec["review"]["reason"] == "not_target"
    for d in (1, 8, 100):
        apple.run(out, y, now=NOW + timedelta(days=d), fetch=fetch)
    assert cands(out)[cid]["status"] == st.REJECTED and cands(out)[cid]["review"]["reason"] == "not_target"


def test_stale_cannot_be_approved_until_rediscovered(env):
    out, y, fetch = env
    cid = cid_of(out, "iPhone Air 256GB")
    s = st.load(out / st.PRODUCT_FILE)
    s["candidates"][cid]["status"] = st.STALE
    st.save(out / st.PRODUCT_FILE, s)
    with pytest.raises(ValueError, match="stale_needs_recheck"):
        approve(out, cid)
    apple.run(out, y, now=NOW + timedelta(days=1), fetch=fetch)                         # 公式で見つけ直す
    assert cands(out)[cid]["status"] == st.PENDING_REVIEW                               # 確認待ちに戻る
    assert approve(out, cid)["status"] == st.APPROVED


def test_cli_reject_requires_reason(env, monkeypatch):
    from click.testing import CliRunner
    import src.cli as cli
    out, _y, _f = env
    monkeypatch.setenv("DISCOVERY_DIR", str(out))
    touched = []
    monkeypatch.setattr(cli, "_get_db", lambda: touched.append(1))
    cid = cid_of(out, "iPhone 17 512GB")
    r = CliRunner().invoke(cli.cli, ["reject-product-candidate", "--candidate-id", cid])
    assert r.exit_code == 1 and "--reason" in r.output and not touched                  # 台帳の候補は理由が必須
    r2 = CliRunner().invoke(cli.cli, ["reject-product-candidate", "--candidate-id", cid, "--reason", "whatever"])
    assert r2.exit_code != 0 and cands(out)[cid]["status"] == st.PENDING_REVIEW


def test_cli_refused_decision_does_not_touch_db(tmp_path, monkeypatch):
    from click.testing import CliRunner
    import src.cli as cli
    led = tmp_path / "led"
    s = st.empty()
    st.upsert(s, "apple-x", {"product_name": "iPhone Air 256GB"}, status=st.STALE, now=NOW)
    st.save(led / st.PRODUCT_FILE, s)
    monkeypatch.setenv("DISCOVERY_DIR", str(led))
    touched = []
    monkeypatch.setattr(cli, "_get_db", lambda: touched.append(1))
    r = CliRunner().invoke(cli.cli, ["approve-product-candidate", "--candidate-id", "apple-x", "--checked",
                                     "official_url"])
    assert r.exit_code == 1 and "stale_needs_recheck" in r.output and not touched
    assert st.load(led / st.PRODUCT_FILE)["candidates"]["apple-x"]["status"] == st.STALE


# ── 登録の前提 ─────────────────────────────────────────────────────────────

def test_registration_requires_approval(env):
    out, y, _f = env
    rec = cands(out)[cid_of(out, "iPhone Air 256GB")]
    p = rg.plan_product(rec, CANON, now=NOW)
    assert "not_approved:PENDING_REVIEW" in p["errors"] and not p["new_text"]
    approve(out, rec["candidate_id"], checked=("part_numbers",))                        # 公式ページの確認の記録が無い
    p2 = rg.plan_product(cands(out)[rec["candidate_id"]], CANON, now=NOW)
    assert p2["errors"] == ["approval_without_check:official_url,capacity,official_price"]
    approve(out, rec["candidate_id"])
    assert rg.plan_product(cands(out)[rec["candidate_id"]], CANON, now=NOW)["errors"] == []      # 対照


def test_stale_or_old_candidate_not_registered(env):
    out, y, _f = env
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    rec = cands(out)[cid]
    assert "stale_needs_recheck" in rg.plan_product(rec, CANON, now=NOW + timedelta(days=7))["errors"]
    assert rg.plan_product(rec, CANON, now=NOW + timedelta(days=6))["errors"] == []      # 対照


def test_duplicate_canonical_rejected(env):
    out, y, _f = env
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    rec = cands(out)[cid]
    same_cap = CANON + '  - id: "prod_air_x"\n    genre: "iphone"\n    name: "iPhone Air 256GB"\n'
    assert "duplicate_model_capacity" in rg.plan_product(rec, same_cap, now=NOW)["errors"]
    same_id = CANON + '  - id: "prod_iphoneair_256"\n    genre: "camera"\n    name: "x"\n'
    assert "duplicate_product_id" in rg.plan_product(rec, same_id, now=NOW)["errors"]
    same_part = CANON + '  - id: "prod_y"\n    genre: "iphone"\n    name: "y"\n    keywords: ["MG274J/A"]\n'
    assert "duplicate_part_number" in rg.plan_product(rec, same_part, now=NOW)["errors"]
    assert "duplicate_matched_existing" in rg.plan_product(dict(rec, match_to_existing="prod_q"), CANON,
                                                           now=NOW)["errors"]
    assert rg.plan_product(rec, CANON, now=NOW)["errors"] == []                          # 対照


def test_identity_and_evidence_required(env):
    out, y, _f = env
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    rec = cands(out)[cid]
    assert "part_numbers_missing_or_invalid" in rg.plan_product(dict(rec, part_numbers=[]), CANON, now=NOW)["errors"]
    assert "part_numbers_missing_or_invalid" in rg.plan_product(dict(rec, part_numbers=["MG274"]), CANON,
                                                                now=NOW)["errors"]
    assert "identity_insufficient" in rg.plan_product(dict(rec, capacity="512GB"), CANON, now=NOW)["errors"]
    assert "identity_insufficient" in rg.plan_product(dict(rec, model_number=""), CANON, now=NOW)["errors"]
    assert "official_url_missing" in rg.plan_product(dict(rec, official_url="https://shop.example.com/air"), CANON,
                                                     now=NOW)["errors"]
    assert "not_official_source" in rg.plan_product(dict(rec, source="rakuten"), CANON, now=NOW)["errors"]
    assert "official_price_not_single" in rg.plan_product(dict(rec, official_price=None,
                                                               official_prices=[1, 2]), CANON, now=NOW)["errors"]


def test_price_varies_by_color_not_registered(env):
    out, y, _f = env
    cid = cid_of(out, "iPhone Air 1TB")
    approve(out, cid)
    assert "official_price_not_single" in rg.plan_product(cands(out)[cid], CANON, now=NOW)["errors"]


def test_tcg_candidate_not_merged_into_canonical():
    rec = {"candidate_id": "tcg-pokemon-1", "status": st.APPROVED, "genre": "tcg", "source": "pokemon_card_official",
           "review": {"decision": st.APPROVED, "evidence_checked": ["official_url"]}, "last_seen_on": "2026-10-17",
           "product_name": "拡張パック", "model_number": "M6", "official_url": "https://www.pokemon-card.com/ex/m6/"}
    errs = rg.plan_product(rec, CANON, now=NOW)["errors"]
    assert "tcg_not_merged_into_canonical" in errs and "not_official_source" in errs


# ── 登録の中身 ─────────────────────────────────────────────────────────────

def test_product_id_rule_matches_existing():
    assert rg.product_id_for("iPhone 17 Pro Max", "256GB") == "prod_iphone17pm_256"
    assert rg.product_id_for("iPhone 17 Pro", "512GB") == "prod_iphone17pro_512"
    assert rg.product_id_for("iPhone 17", "256GB") == "prod_iphone17_256"
    assert rg.product_id_for("iPhone Duo", "2TB") == "prod_iphoneduo_2tb"
    assert rg.product_id_for("iPhone Air", "") == "" and rg.product_id_for("iPhone/Air", "256GB") == ""


def test_entry_keeps_capacity_parts_colors_and_yaml_format(env):
    out, y, _f = env
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    p = rg.plan_product(cands(out)[cid], CANON, now=NOW)
    e = p["entry"]
    assert e["id"] == "prod_iphoneair_256" and e["name"] == "iPhone Air 256GB SIMフリー"
    assert e["capacity"] == "256GB" and e["part_numbers"] == ["MG274J/A", "MG284J/A"]
    assert e["colors"] == ["Sky Blue", "Space Black"]                 # 色違いは1商品にまとめる（色で商品を増やさない）
    assert e["retail_price"] == 189800 and e["model_number"] == ""     # 型番を推測しない（部品番号の組で持つ）
    assert e["official_url"] == apple.FAMILY_URL.format(slug="iphone-air")
    assert e["keywords"][0] == "iPhone Air 256GB"                     # 先頭は容量つき（機種名だけにしない）
    assert all("256" in k or re.fullmatch(r"[A-Z0-9]{4,5}J/A", k) for k in e["keywords"])
    assert e["keywords"][2:] == ["MG274J/A", "MG284J/A"]               # 部品番号は検索のために後ろ
    assert e["id"] not in ("", None) and cands(out)[cid]["candidate_id"] not in p["new_text"]   # 候補の ID は正本に書かない
    new = yaml.safe_load(p["new_text"])["products"]
    old = yaml.safe_load(CANON)["products"]
    assert [x for x in new if x["id"] != e["id"]] == old and new[2] == e     # 最後の iPhone の後ろ・既存は不変
    assert p["new_text"].startswith(CANON.split("  # =========================================\n  # カメラ")[0])
    assert "# カメラ" in p["new_text"] and "# iPhone（発見の候補から人が承認して登録。Phase 28）" in p["new_text"]
    assert p["diff"].count("\n+  - id:") == 1 and "\n-" not in p["diff"].split("@@", 1)[1]     # 足すだけ
    assert not rg.verify_product_text(CANON, p["new_text"], e)


def test_second_registration_goes_after_first_without_second_header(env):
    out, y, _f = env
    a, b = cid_of(out, "iPhone Air 256GB"), cid_of(out, "iPhone 17 512GB")
    approve(out, a)
    approve(out, b)
    t1 = rg.plan_product(cands(out)[a], CANON, now=NOW)["new_text"]
    p2 = rg.plan_product(cands(out)[b], t1, now=NOW)
    assert p2["errors"] == [] and p2["new_text"].count("Phase 28）") == 1
    ids = [x["id"] for x in yaml.safe_load(p2["new_text"])["products"]]
    assert ids == ["prod_iphone17_256", "prod_iphone17pro_256", "prod_iphoneair_256", "prod_iphone17_512", "prod_x100vi"]


def test_write_is_atomic_and_checked(env, monkeypatch, tmp_path):
    out, y, _f = env
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    p = rg.plan_product(cands(out)[cid], CANON, now=NOW)
    bad = dict(p, new_text=p["new_text"].replace('name: "iPhone 17 Pro 256GB SIMフリー"', 'name: "x"'))
    with pytest.raises(ValueError, match="existing_products_changed"):
        rg.write_product(y, CANON, bad)
    with pytest.raises(ValueError, match="new_yaml_invalid"):
        rg.write_product(y, CANON, dict(p, new_text="products: [\n"))
    y2 = tmp_path / "other.yaml"
    y2.write_text(CANON + "\n# 手で変えた\n", encoding="utf-8")
    with pytest.raises(ValueError, match="canonical_changed_since_plan"):
        rg.write_product(y2, CANON, p)
    import os
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError):
        rg.write_product(y, CANON, p)
    assert y.read_text(encoding="utf-8") == CANON                                      # 途中で失敗しても元のまま
    assert not [f for f in y.parent.iterdir() if f.name.endswith(".tmp")]               # 一時ファイルを残さない
    monkeypatch.undo()
    rg.write_product(y, CANON, p)
    assert y.read_text(encoding="utf-8") == p["new_text"]                               # 対照


def test_registration_code_does_not_commit_or_push():
    srcs = [(ROOT / "src" / "discovery" / "register.py").read_text(encoding="utf-8")]
    cli = (ROOT / "src" / "cli.py").read_text(encoding="utf-8")
    i, j = cli.index('@cli.command("register-product-candidate")'), cli.index("def _print_registration_followup")
    srcs.append(cli[i:j])
    for s in srcs:
        assert "subprocess" not in s and not re.search(r"\bgit\s+(commit|push|add)\b|os\.system", s)


# ── CLI（dry-run・confirm）─────────────────────────────────────────────────

@pytest.fixture
def cli_env(env, monkeypatch):
    import src.cli as cli
    out, y, fetch = env
    root = y.parent / "root"
    (root / "config").mkdir(parents=True)
    canon = root / "config" / "products.yaml"
    canon.write_text(CANON, encoding="utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", root)
    monkeypatch.setenv("DISCOVERY_DIR", str(out))
    return cli, out, canon, fetch


def run_cli(cli, *args):
    from click.testing import CliRunner
    return CliRunner().invoke(cli.cli, list(args))


def test_cli_dry_run_writes_nothing(cli_env):
    cli, out, canon, _f = cli_env
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    led_before = (out / st.PRODUCT_FILE).read_text(encoding="utf-8")
    for args in ([], ["--dry-run"]):
        r = run_cli(cli, "register-product-candidate", "--candidate-id", cid, *args)
        assert r.exit_code == 0 and "prod_iphoneair_256" in r.output and "+  - id:" in r.output
        assert "見込みだけ" in r.output and "監視への影響" in r.output
    assert canon.read_text(encoding="utf-8") == CANON
    assert (out / st.PRODUCT_FILE).read_text(encoding="utf-8") == led_before
    r = run_cli(cli, "register-product-candidate", "--candidate-id", cid, "--dry-run", "--confirm")
    assert r.exit_code == 1 and canon.read_text(encoding="utf-8") == CANON
    unchanged_real()


def test_cli_confirm_requires_sync_with_main(cli_env):
    cli, out, canon, _f = cli_env
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    r = run_cli(cli, "register-product-candidate", "--candidate-id", cid, "--confirm")
    assert r.exit_code == 1 and "中止" in r.output                         # 台帳がリポジトリの外 = main と照合できない
    assert canon.read_text(encoding="utf-8") == CANON and cands(out)[cid]["status"] == st.APPROVED


def test_cli_confirm_writes_one_and_marks_registered(cli_env, monkeypatch):
    cli, out, canon, _f = cli_env
    monkeypatch.setattr(cli, "_registration_in_sync", lambda *a: (True, ""))
    cid = cid_of(out, "iPhone Air 256GB")
    r = run_cli(cli, "register-product-candidate", "--candidate-id", cid, "--confirm")
    assert r.exit_code == 1 and "not_approved" in r.output                              # 承認なしは書かない
    approve(out, cid)
    r = run_cli(cli, "register-product-candidate", "--candidate-id", cid, "--confirm")
    assert r.exit_code == 0, r.output
    assert "commit / push はしていません" in r.output and "その差分だけを戻して" in r.output
    new = yaml.safe_load(canon.read_text(encoding="utf-8"))["products"]
    assert len(new) == 4 and [x["id"] for x in new].count("prod_iphoneair_256") == 1
    rec = cands(out)[cid]
    assert rec["status"] == st.REGISTERED and rec["registered_id"] == "prod_iphoneair_256"
    assert rec["registered_to"] == "config/products.yaml"
    r = run_cli(cli, "register-product-candidate", "--candidate-id", cid, "--confirm")      # 2回目は登録しない
    assert r.exit_code == 1 and len(yaml.safe_load(canon.read_text(encoding="utf-8"))["products"]) == 4
    r = run_cli(cli, "reject-product-candidate", "--candidate-id", cid, "--reason", "duplicate")
    assert r.exit_code == 1 and "registered_use_git_revert" in r.output
    unchanged_real()


def test_next_discovery_matches_registered_and_rollback_reopens(cli_env, monkeypatch):
    cli, out, canon, fetch = cli_env
    monkeypatch.setattr(cli, "_registration_in_sync", lambda *a: (True, ""))
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    assert run_cli(cli, "register-product-candidate", "--candidate-id", cid, "--confirm").exit_code == 0
    n = len(cands(out))
    apple.run(out, canon, now=NOW + timedelta(days=1), fetch=fetch)
    rec = cands(out)[cid]
    assert len(cands(out)) == n                                                         # 新しい候補を作らない
    assert rec["status"] == st.REGISTERED and rec["match_to_existing"] == "prod_iphoneair_256"
    assert "not_in_canonical" not in rec["reasons"]
    canon.write_text(CANON, encoding="utf-8")                                           # 登録を戻した（git revert）
    apple.run(out, canon, now=NOW + timedelta(days=2), fetch=fetch)
    rec = cands(out)[cid]
    assert rec["status"] == st.PENDING_REVIEW and "registered_not_in_canonical" in rec["reasons"]


def test_seed_identity_and_search_after_registration(cli_env, monkeypatch, tmp_path):
    cli, out, canon, _f = cli_env
    monkeypatch.setattr(cli, "_registration_in_sync", lambda *a: (True, ""))
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    assert run_cli(cli, "register-product-candidate", "--candidate-id", cid, "--confirm").exit_code == 0
    data = yaml.safe_load(canon.read_text(encoding="utf-8"))
    from src.db.database import Database
    db_path = tmp_path / "t.db"
    monkeypatch.setattr(cli, "_get_db", lambda: Database(db_path=str(db_path)))
    monkeypatch.setattr(cli, "_load_yaml", lambda name: data if name == "products.yaml" else {})
    r = run_cli(cli, "seed")
    assert r.exit_code == 0 and "Products: 4" in r.output, r.output
    import sqlite3
    row = sqlite3.connect(str(db_path)).execute(
        "select name, retail_price, model_number from products where id='prod_iphoneair_256'").fetchone()
    assert row == ("iPhone Air 256GB SIMフリー", 189800, "")
    e = next(p for p in data["products"] if p["id"] == "prod_iphoneair_256")
    from src.market import official_registry as reg
    # Phase 29 で本物の登録簿に iPhone Air の証拠が入ったので、ここで止まる理由は「この一時の正本の部品番号の組
    # （2つ）が証拠（4つ）と違う」こと。証拠が無いときに止まることは test_phase29_activation が確かめる
    state, _why = reg.identity_state(e)
    assert state != "IDENTITY_CONFIRMED"                                    # 公式直販の証拠は人が確かめて別に記録する
    assert reg.official_direct_gate(e["id"], e)[0] is False                 # 確定の仕入れ値にしない（利益を作らない）
    assert apple.canonical_iphones(canon)[("iphone air", "256GB")] == "prod_iphoneair_256"
    blob = " ".join([e["name"], e["capacity"], *e["part_numbers"], *e["keywords"]]).lower()
    for q in ("iphone air", "256gb", "mg274j/a"):
        assert q in blob


# ── TCG の告知の確認・登録 ──────────────────────────────────────────────────

ANN = {"candidate_id": "tcg-ann-1", "source": "POKEMON_CENTER_ONLINE", "kind": "LOTTERY", "tcg": "POKEMON",
       "title": "【第二回】30周年商品の抽選受け付けについて",
       "official_url": "https://www.pokemoncenter-online.com/news/?id=20260821", "product_code": "",
       "application_start": None, "application_end": None, "missing_fields": ["application_start", "application_end"],
       "status": st.ANNOUNCEMENT_REVIEW_REQUIRED, "reasons": ["schedule_not_available"], "last_seen_on": "2026-10-17"}
# 応募の終了は今日から3日後（固定の日付だと、その日を過ぎた日に「終わった日程は登録しない」で落ちる）
GOOD = dict(product="ポケモンカードゲーム 30周年記念商品", start="2026-10-20T12:00:00+09:00",
            end=(datetime.now(JST) + timedelta(days=3)).replace(hour=16, minute=59, second=0, microsecond=0).isoformat(),
            official_page_checked=True)


def approved_ann(**kw):
    return dict(ANN, status=st.APPROVED, review={"decision": st.APPROVED, "evidence_checked": ["schedule",
                                                                                                "official_url"]}, **kw)


def test_event_review_required_preserved_and_not_open(tmp_path):
    p = tmp_path / st.EVENT_FILE
    s = st.empty()
    st.upsert(s, "tcg-ann-1", {k: v for k, v in ANN.items() if k not in ("candidate_id", "status", "reasons",
                                                                          "last_seen_on")},
              status=st.ANNOUNCEMENT_REVIEW_REQUIRED, now=NOW, reasons=["schedule_not_available"])
    st.save(p, s)
    rec = st.decide(p, "tcg-ann-1", "approve", now=NOW, evidence_checked=["official_url"])
    assert rec["status"] == st.APPROVED and rec["application_start"] is None            # 承認で日程を作らない
    assert "OPEN" not in (p.read_text(encoding="utf-8"))
    errs = rg.plan_event(rec, REAL_CSV, now=NOW, **GOOD)["errors"]
    assert errs == ["approval_without_schedule_check"]                                  # 日程を確かめた記録が要る


def test_event_manual_dates_required():
    rec = approved_ann()
    for bad in (dict(GOOD, start=""), dict(GOOD, end=""), dict(GOOD, start="2026-10-20"),
                dict(GOOD, start="2026-10-20T12:00:00"), dict(GOOD, end="来週")):
        assert "schedule_required_iso8601_with_tz" in rg.plan_event(rec, REAL_CSV, now=NOW, **bad)["errors"], bad
    assert "schedule_end_before_start" in rg.plan_event(
        rec, REAL_CSV, now=NOW, **dict(GOOD, end="2026-10-19T12:00:00+09:00"))["errors"]
    assert "official_page_not_checked" in rg.plan_event(
        rec, REAL_CSV, now=NOW, **dict(GOOD, official_page_checked=False))["errors"]
    assert "product_required" in rg.plan_event(rec, REAL_CSV, now=NOW, **dict(GOOD, product=" "))["errors"]
    assert rg.plan_event(rec, REAL_CSV, now=NOW, **GOOD)["errors"] == []                  # 対照


def test_event_official_url_and_kind_required():
    assert "official_url_missing" in rg.plan_event(approved_ann(official_url="https://blog.example.com/x"), REAL_CSV,
                                                   now=NOW, **GOOD)["errors"]
    assert "unsupported_event_kind:RESTOCK" in rg.plan_event(approved_ann(kind="RESTOCK"), REAL_CSV, now=NOW,
                                                             **GOOD)["errors"]
    assert "not_approved:ANNOUNCEMENT_REVIEW_REQUIRED" in rg.plan_event(ANN, REAL_CSV, now=NOW, **GOOD)["errors"]


def test_event_registration_uses_operator_dates_only_and_dedupes(tmp_path):
    from src.tcg.lottery import manual
    p = tmp_path / "v.csv"
    p.write_text(REAL_CSV, encoding="utf-8")
    plan = rg.plan_event(approved_ann(), REAL_CSV, now=NOW, **GOOD)
    rg.write_event(p, REAL_CSV, plan)
    rows = list(csv.DictReader(io.StringIO(p.read_text(encoding="utf-8"))))
    assert rows[:-1] == list(csv.DictReader(io.StringIO(REAL_CSV)))                      # 既存の行は不変
    new = rows[-1]
    assert (new["application_start"], new["application_end"]) == (GOOD["start"], GOOD["end"])
    assert new["purchase_start"] == "" and new["winner_announcement_at"] == ""          # 渡されていない日程は空
    assert new["verified_by"] == rg.VERIFIED_BY and "@" not in new["verified_by"]
    evs, errs = manual.load_manual_lotteries(p)
    assert not errs and evs[-1]["application_start"] == GOOD["start"] and evs[-1]["source_type"] != ""
    again = rg.plan_event(approved_ann(), p.read_text(encoding="utf-8"), now=NOW, **GOOD)
    assert "duplicate_event" in again["errors"]                                          # 同じ行を重ねない


def test_cli_event_dry_run_and_registered_dedupe(tmp_path, monkeypatch):
    import src.cli as cli
    from src.tcg.lottery import manual
    led = tmp_path / "led"
    s = st.empty()
    s["candidates"]["tcg-ann-1"] = approved_ann()
    st.save(led / st.EVENT_FILE, s)
    monkeypatch.setenv("DISCOVERY_DIR", str(led))
    csvp = tmp_path / "v.csv"
    csvp.write_text(REAL_CSV, encoding="utf-8")
    monkeypatch.setattr(manual, "MANUAL_CSV", csvp)
    args = ["register-event-candidate", "--candidate-id", "tcg-ann-1", "--product", GOOD["product"], "--start",
            GOOD["start"], "--end", GOOD["end"], "--official-page-checked"]
    r = run_cli(cli, *args)
    assert r.exit_code == 0 and "見込みだけ" in r.output and csvp.read_text(encoding="utf-8") == REAL_CSV
    r = run_cli(cli, *args[:-1], "--confirm")                                         # 公式ページの確認なし
    assert r.exit_code == 1 and csvp.read_text(encoding="utf-8") == REAL_CSV
    monkeypatch.setattr(cli, "_registration_in_sync", lambda *a: (True, ""))
    r = run_cli(cli, *args, "--confirm")
    assert r.exit_code == 0, r.output
    assert st.load(led / st.EVENT_FILE)["candidates"]["tcg-ann-1"]["status"] == st.REGISTERED
    n = len(csvp.read_text(encoding="utf-8").splitlines())
    r = run_cli(cli, *args, "--confirm")
    assert r.exit_code == 1 and len(csvp.read_text(encoding="utf-8").splitlines()) == n
    unchanged_real()


def test_cli_event_approve_and_reject(tmp_path, monkeypatch):
    import src.cli as cli
    led = tmp_path / "led"
    s = st.empty()
    s["candidates"]["tcg-ann-1"] = copy.deepcopy(ANN)
    st.save(led / st.EVENT_FILE, s)
    monkeypatch.setenv("DISCOVERY_DIR", str(led))
    assert run_cli(cli, "approve-event-candidate", "--candidate-id", "nope").exit_code == 1
    r = run_cli(cli, "approve-event-candidate", "--candidate-id", "tcg-ann-1", "--checked", "schedule")
    assert r.exit_code == 0 and "register-event-candidate" in r.output
    r = run_cli(cli, "reject-event-candidate", "--candidate-id", "tcg-ann-1", "--reason", "obsolete")
    rec = st.load(led / st.EVENT_FILE)["candidates"]["tcg-ann-1"]
    assert r.exit_code == 0 and rec["status"] == st.REJECTED and len(rec["decisions"]) == 2


# ── 管理画面 ───────────────────────────────────────────────────────────────

def test_admin_shows_review_states_and_cli_steps_only(env):
    from src.content.ui import admin
    out, y, _f = env
    a, b = cid_of(out, "iPhone Air 256GB"), cid_of(out, "iPhone 17 512GB")
    approve(out, a)
    st.decide(out / st.PRODUCT_FILE, b, "reject", now=NOW, reason="not_target")
    pc = st.load(out / st.PRODUCT_FILE)
    pc["candidates"][a]["status"] = st.REGISTERED
    pc["candidates"][a]["registered_id"] = "prod_iphoneair_256"
    d = admin.build_discovery({"generated_at": NOW.isoformat()}, pc, {"candidates": {"tcg-ann-1": dict(ANN)}})
    assert d["review"]["products"]["REGISTERED"] == 1 and d["review"]["products"]["REJECTED"] == 1
    assert d["review"]["events"]["PENDING"] == 1
    html = admin._discovery(d)
    for w in ("正本に登録済み（prod_iphoneair_256）", "却下（not_target）", "register-product-candidate", "--confirm",
              "register-event-candidate", a):
        assert w in html, w
    assert "<button" not in html and "<form" not in html                       # 登録のボタンを置かない


# ── レビューの指摘への対応 ────────────────────────────────────────────────

def test_sync_allows_only_this_candidates_approval_against_real_git(env, monkeypatch, tmp_path):
    """承認を手元だけで記録した状態では --confirm できる・ほかの候補が違えば止める（レビュー H-1。本物の git）。"""
    import json
    import shutil
    import subprocess
    import src.cli as cli
    out, _y, _f = env
    bare, work = tmp_path / "origin.git", tmp_path / "work"

    def git(*a, cwd=work):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git("init", "-q", "-b", "main", str(work), cwd=tmp_path)
    (work / "config").mkdir()
    (work / "config" / "products.yaml").write_text(CANON, encoding="utf-8")
    (work / "led").mkdir()
    shutil.copy(out / st.PRODUCT_FILE, work / "led" / st.PRODUCT_FILE)
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "x")
    git("remote", "add", "origin", str(bare))
    git("push", "-q", "origin", "main")
    monkeypatch.setattr(cli, "PROJECT_ROOT", work)
    led, canon = work / "led" / st.PRODUCT_FILE, work / "config" / "products.yaml"
    cid = cid_of(work / "led", "iPhone Air 256GB")
    assert cli._registration_in_sync(canon, led, cid) == (True, "")
    approve(work / "led", cid)
    assert cli._registration_in_sync(canon, led, cid)[0] is True                       # この候補の承認だけの違いは許す
    d = json.loads(led.read_text(encoding="utf-8"))
    other = cid_of(work / "led", "iPhone 17 512GB")
    d["candidates"][other]["status"] = st.REJECTED
    led.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert cli._registration_in_sync(canon, led, cid)[0] is False                      # ほかの候補の違いは止める
    canon.write_text(CANON + "\n", encoding="utf-8")
    assert cli._registration_in_sync(canon, led, cid)[0] is False                      # 正本が main と違えば止める


def test_ledgers_match_except():
    a = {"schema": 1, "candidates": {"x": {"status": "PENDING_REVIEW"}, "y": {"s": 1}}}
    assert rg.ledgers_match_except(a, {"schema": 1, "candidates": {"x": {"status": "APPROVED"}, "y": {"s": 1}}}, "x")
    assert not rg.ledgers_match_except(a, {"schema": 1, "candidates": {"x": {"status": "APPROVED"}, "y": {"s": 2}}}, "x")
    assert not rg.ledgers_match_except(a, {"schema": 2, "candidates": {"x": {"status": "PENDING_REVIEW"}, "y": {"s": 1}}},
                                       "x")
    assert not rg.ledgers_match_except(a, {"schema": 1, "candidates": {"y": {"s": 1}}}, "x")


def test_reconcile_reopens_without_fetching(env):
    """機種のページを読まない日でも、正本に無い登録済みの候補を確認待ちに戻す（レビュー H-2）。"""
    out, _y, _f = env
    cid = cid_of(out, "iPhone Air 256GB")
    s = st.load(out / st.PRODUCT_FILE)
    st.mark_registered(s, cid, now=NOW, target=rg.PRODUCT_TARGET, registered_id="prod_iphoneair_256")
    assert st.reconcile_registered(s, {"prod_iphoneair_256", "prod_x"}, now=NOW,
                                   reopen_status=st.PENDING_REVIEW) == 0               # 正本にあれば変えない
    assert st.reconcile_registered(s, set(), now=NOW, reopen_status=st.PENDING_REVIEW) == 0   # 正本を読めない日は何もしない
    assert s["candidates"][cid]["status"] == st.REGISTERED
    assert st.reconcile_registered(s, {"prod_x"}, now=NOW, reopen_status=st.PENDING_REVIEW) == 1
    rec = s["candidates"][cid]
    assert rec["status"] == st.PENDING_REVIEW and "registered_not_in_canonical" in rec["reasons"]
    assert rec["decisions"][-1]["note"] == "registered_not_in_canonical"


def test_cli_discover_reconciles_even_when_apple_skipped(cli_env, monkeypatch, tmp_path):
    cli, out, canon, _f = cli_env
    cid = cid_of(out, "iPhone Air 256GB")
    s = st.load(out / st.PRODUCT_FILE)
    st.mark_registered(s, cid, now=NOW, target=rg.PRODUCT_TARGET, registered_id="prod_iphoneair_256")
    st.save(out / st.PRODUCT_FILE, s)
    monkeypatch.setattr(cli, "_load_yaml", lambda name: yaml.safe_load(CANON) if name == "products.yaml" else {})
    monkeypatch.setattr(cli, "_get_db", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    r = run_cli(cli, "discover", "--skip-apple")
    assert "reopened" in r.output and cands(out)[cid]["status"] == st.PENDING_REVIEW


def test_matched_event_not_approvable_or_registerable():
    rec = dict(ANN, candidate_id="tcg-event-1", status=st.MATCHED_EVENT)
    assert st.check_decision(rec, "approve") == ["not_approvable:MATCHED_EVENT"]
    errs = rg.plan_event(dict(approved_ann(), candidate_id="tcg-event-1"), REAL_CSV, now=NOW, **GOOD)["errors"]
    assert "not_announcement" in errs


def test_duplicate_jan_rejected(env):
    out, _y, _f = env
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    rec = dict(cands(out)[cid], jan="4549995000000")
    canon = CANON + '  - id: "prod_j"\n    genre: "camera"\n    name: "j"\n    jan_code: "4549995000000"\n'
    assert "duplicate_jan" in rg.plan_product(rec, canon, now=NOW)["errors"]
    assert "duplicate_jan" not in rg.plan_product(rec, CANON, now=NOW)["errors"]          # 対照


def test_ledger_save_failure_restores_canonical(cli_env, monkeypatch):
    cli, out, canon, _f = cli_env
    monkeypatch.setattr(cli, "_registration_in_sync", lambda *a: (True, ""))
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    monkeypatch.setattr(st, "save", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    r = run_cli(cli, "register-product-candidate", "--candidate-id", cid, "--confirm")
    assert r.exit_code == 1 and "正本は元に戻しました" in r.output
    assert canon.read_text(encoding="utf-8") == CANON


# ── 監査の指摘への対応 ─────────────────────────────────────────────────

def test_event_schedule_must_be_jst_current_and_plausible():
    rec = approved_ann()
    for bad, why in ((dict(GOOD, start="2026-10-20T03:00:00Z"), "schedule_required_iso8601_with_tz"),
                     (dict(GOOD, end="2026-10-23T07:59:00+00:00"), "schedule_required_iso8601_with_tz"),
                     (dict(GOOD, start="2026-10-01T12:00:00+09:00", end="2026-10-05T16:59:00+09:00"),
                      "schedule_already_ended"),
                     (dict(GOOD, start="2062-10-20T12:00:00+09:00", end="2062-10-23T16:59:00+09:00"), "schedule_too_far")):
        assert why in rg.plan_event(rec, REAL_CSV, now=NOW, **bad)["errors"], bad


def test_event_duplicate_by_normalized_name_and_collected():
    rec = approved_ann(official_url="https://www.pokemoncenter-online.com/news/?id=99999")
    first = dict(GOOD, product="ポケモンカードゲーム MEGA 拡張パック「インフェルノX」BOX",
                 start="2026-10-20T12:00:00+09:00")
    csv_text = rg.plan_event(approved_ann(), REAL_CSV, now=NOW, **first)["new_text"]
    again = dict(first, product="ポケモンカードゲーム MEGA 拡張パック インフェルノX BOX")      # 表記の揺れ
    assert "duplicate_event" in rg.plan_event(rec, csv_text, now=NOW, **again)["errors"]
    collected = [{"retailer": "POKEMON_CENTER_ONLINE", "product_name": first["product"], "source_url": "x",
                  "application_start": first["start"]}]
    assert "duplicate_event" in rg.plan_event(rec, REAL_CSV, now=NOW, existing_events=collected, **first)["errors"]
    assert "duplicate_event" not in rg.plan_event(rec, REAL_CSV, now=NOW, **first)["errors"]    # 対照


def test_sync_requires_target_evidence_unchanged_on_main():
    base = {"product_name": "iPhone Air 256GB", "official_price": 189800, "status": st.PENDING_REVIEW}
    main = {"schema": 1, "candidates": {"x": dict(base)}}
    approved = dict(base, status=st.APPROVED, review={"decision": st.APPROVED}, updated_at="t")
    assert rg.ledgers_match_except(main, {"schema": 1, "candidates": {"x": approved}}, "x")
    repriced = {"schema": 1, "candidates": {"x": dict(base, official_price=199800)}}
    assert not rg.ledgers_match_except(repriced, {"schema": 1, "candidates": {"x": approved}}, "x")
    rejected = {"schema": 1, "candidates": {"x": dict(base, status=st.REJECTED)}}
    assert not rg.ledgers_match_except(rejected, {"schema": 1, "candidates": {"x": approved}}, "x")


def test_ci_conflict_does_not_overwrite_human_ledger_and_commit_excludes_canonical():
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    i = wf.index('HUMAN=$(echo "$CONFLICTS" | grep -E \'^exports/discovery/(product|event)_candidates\\.json$\'')
    j = wf.index('OTHERS=$(printf \'%s\\n%s\\n\' "$OTHERS" "$HUMAN" | sed \'/^$/d\')', i)
    k = wf.index('if [ -n "$OTHERS" ]; then', j)
    assert i < j < k < wf.index("git rebase --abort", k) < wf.index("xargs git checkout --theirs", k)
    m = re.search(r"^ *git add (.*?)\|\| true", wf, re.S | re.M)
    assert m and "config/" not in m.group(1) and "tcg_verified_lotteries" not in m.group(1)


def test_cli_event_dry_run_warns_when_already_open(tmp_path, monkeypatch):
    import src.cli as cli
    from src.tcg.lottery import manual
    led = tmp_path / "led"
    s = st.empty()
    s["candidates"]["tcg-ann-1"] = approved_ann()
    st.save(led / st.EVENT_FILE, s)
    monkeypatch.setenv("DISCOVERY_DIR", str(led))
    csvp = tmp_path / "v.csv"
    csvp.write_text(REAL_CSV, encoding="utf-8")
    monkeypatch.setattr(manual, "MANUAL_CSV", csvp)
    started = (datetime.now(tz=JST) - timedelta(hours=1)).isoformat(timespec="seconds")
    ending = (datetime.now(tz=JST) + timedelta(days=2)).isoformat(timespec="seconds")
    base = ["register-event-candidate", "--candidate-id", "tcg-ann-1", "--product", GOOD["product"],
            "--official-page-checked"]
    r = run_cli(cli, *base, "--start", started, "--end", ending)
    assert r.exit_code == 0 and "受付はもう始まっています" in r.output
    later = (datetime.now(tz=JST) + timedelta(days=1)).isoformat(timespec="seconds")
    r2 = run_cli(cli, *base, "--start", later, "--end", ending)
    assert r2.exit_code == 0 and "受付はもう始まっています" not in r2.output          # 対照


def test_rollback_after_discovery_matched_keeps_862_green(cli_env, monkeypatch):
    """登録 → 発見で一致 → 正本の差分を戻す → 機種のページを読まない discover → #862 は ok（再レビュー H-1）。"""
    cli, out, canon, fetch = cli_env
    monkeypatch.setattr(cli, "_registration_in_sync", lambda *a: (True, ""))
    cid = cid_of(out, "iPhone Air 256GB")
    approve(out, cid)
    assert run_cli(cli, "register-product-candidate", "--candidate-id", cid, "--confirm").exit_code == 0
    apple.run(out, canon, now=NOW + timedelta(days=1), fetch=fetch)
    assert cands(out)[cid]["match_to_existing"] == "prod_iphoneair_256"
    canon.write_text(CANON, encoding="utf-8")                                             # 正本の差分だけを戻した
    monkeypatch.setattr(cli, "_load_yaml", lambda name: yaml.safe_load(CANON) if name == "products.yaml" else {})
    monkeypatch.setattr(cli, "_get_db", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    run_cli(cli, "discover", "--skip-apple")
    rec = cands(out)[cid]
    assert rec["status"] == st.PENDING_REVIEW and rec["match_to_existing"] == ""
    src = (ROOT / "scripts" / "deploy_check.py").read_text(encoding="utf-8")
    assert 'r.get("status") == st.PENDING_REVIEW and r.get("match_to_existing")' in src     # #862 の条件
    assert not any(r.get("status") == st.PENDING_REVIEW and r.get("match_to_existing") for r in cands(out).values())


def test_event_reconcile_ignores_start_correction():
    s = st.empty()
    s["candidates"]["tcg-ann-1"] = dict(approved_ann(), status=st.REGISTERED,
                                        registered_id="POKEMON_CENTER_ONLINE|https://x|2026-10-20T12:00:00+09:00")
    key = lambda r: "|".join(str(r.get("registered_id") or "").split("|")[:2])   # noqa: E731
    assert st.reconcile_registered(s, {"POKEMON_CENTER_ONLINE|https://x"}, now=NOW,
                                   reopen_status=st.ANNOUNCEMENT_REVIEW_REQUIRED, key=key) == 0   # 開始を直しても戻さない
    assert st.reconcile_registered(s, {"POKEMON_CENTER_ONLINE|https://y"}, now=NOW,
                                   reopen_status=st.ANNOUNCEMENT_REVIEW_REQUIRED, key=key) == 1


def test_cli_discover_keeps_registered_event_after_start_correction(cli_env, monkeypatch, tmp_path):
    from src.tcg.lottery import manual
    cli, out, _canon, _f = cli_env
    url = "https://www.pokemoncenter-online.com/news/?id=20260821"
    s = st.empty()
    s["candidates"]["tcg-ann-1"] = dict(approved_ann(), status=st.REGISTERED,
                                        registered_id=f"POKEMON_CENTER_ONLINE|{url}|2026-10-20T12:00:00+09:00")
    st.save(out / st.EVENT_FILE, s)
    csvp = tmp_path / "v.csv"
    plan = rg.plan_event(approved_ann(), REAL_CSV, now=NOW, **dict(GOOD, start="2026-10-21T12:00:00+09:00"))
    csvp.write_text(plan["new_text"], encoding="utf-8")                              # 延期で開始日時を直した
    monkeypatch.setattr(manual, "MANUAL_CSV", csvp)
    monkeypatch.setattr(cli, "_load_yaml", lambda name: yaml.safe_load(CANON) if name == "products.yaml" else {})
    monkeypatch.setattr(cli, "_get_db", lambda: (_ for _ in ()).throw(RuntimeError("no db")))
    run_cli(cli, "discover", "--skip-apple")
    assert st.load(out / st.EVENT_FILE)["candidates"]["tcg-ann-1"]["status"] == st.REGISTERED
    csvp.write_text(REAL_CSV, encoding="utf-8")                                         # 行を消した（登録を戻した）
    run_cli(cli, "discover", "--skip-apple")
    assert st.load(out / st.EVENT_FILE)["candidates"]["tcg-ann-1"]["status"] == st.ANNOUNCEMENT_REVIEW_REQUIRED
