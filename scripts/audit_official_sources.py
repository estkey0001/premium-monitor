#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Official Source Registry & Validation — 公式ソースの監査・登録・検証。

目的: 公式定価の自動取得率を上げる。利益判定/AI/Opportunity/Notification/Capital/
Execution ロジックは一切変更しない（取得側の品質管理のみ）。

このスクリプトは:
  1. 現行 product_source_config を監査（旧URL/404/世代ドリフトを検出）— Task1
  2. 実検証済み(VERIFIED_URLS)の公式URLを登録 — Task2/4/5/6
     ※ URLは推測しない。WebFetch で HTTP200/公式ドメイン/canonical/商品一致を
       確認したものだけ verified=true とし last_verified_at を付す（Task12: 偽の
       鮮度更新をしない＝実検証した日時のみ記録）。
  3. product_source_config を official + 主要リテーラで整理 — Task7
  4. 登録価格に sanity/confidence を付与 — Task8/9（official_price_validator 使用）
  5. exports/official_source_audit/latest.json + latest.md を生成 — Task10/11

重要（正直な事実）:
  - カメラ各社(Fujifilm/Nikon/Canon 等)は「オープン価格」で公式定価が存在しない
    → link_type=category・official_price=null が正しい（¥0を保存しない）。
  - Sony/Canon の公式ストアは当環境から DNS 解決不可で URL 検証不能
    → verified=false（needs_manual_verification）。推測登録しない。
  - Apple/RICOH は公式直販で定価が実在し検証可能。
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
TODAY = NOW.strftime("%Y-%m-%d")
DB_PATH = ROOT / "data" / "premium_monitor.db"
OUT = ROOT / "exports" / "official_source_audit"

from src.market.official_price_validator import validate_official_price, is_official_domain

# 公式の確認の記録（VERIFIED_URLS・UNVERIFIED・OFFICIAL_NOT_SOLD・KNOWN_STALE）は src/market/official_registry.py が正本
# （Phase 15 で移した。名前はここでも同じに使える）
from src.market.official_registry import (  # noqa: E402,F401
    KNOWN_STALE, OFFICIAL_NOT_SOLD, UNVERIFIED, VERIFIED_URLS, VERIFIED_URLS_CHECKED_ON, official_direct_gate,
)

MAKER_OF = {
    "src_apple_jp": "Apple", "src_ricoh_imaging": "RICOH", "src_fujifilm_official": "FUJIFILM",
    "src_canon_official": "Canon", "src_nikon_direct": "Nikon", "src_sony_store": "Sony",
    "src_nintendo_store": "Nintendo",
}
RETAILER_SOURCES = ["src_kakaku", "src_yodobashi", "src_biccamera", "src_map_camera",
                    "src_fujiya", "src_rakuten", "src_yahoo", "src_ebay"]
RETAILER_LABEL = {"src_kakaku": "pricecom", "src_yodobashi": "yodobashi", "src_biccamera": "biccamera",
                  "src_map_camera": "mapcamera", "src_fujiya": "fujiya", "src_rakuten": "rakuten",
                  "src_yahoo": "yahoo", "src_ebay": "ebay"}


def _conn():
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def _products(c):
    return {r["id"]: dict(r) for r in c.execute(
        "SELECT id,name,brand,model_number,jan_code,retail_price,official_price FROM products WHERE is_active=1")}


def _existing_configs(c):
    out = defaultdict(dict)
    try:
        for r in c.execute("SELECT product_id,source_id,target_url,extra_config,is_active FROM product_source_config"):
            out[r["product_id"]][r["source_id"]] = dict(r)
    except Exception:
        pass
    return out


# ─────────────────────────────────────────────────────────────
# Task1: Apple Source Audit（旧URL検出）
# ─────────────────────────────────────────────────────────────
def apple_audit(products, configs):
    rows = []
    for pid, srcs in configs.items():
        cfg = srcs.get("src_apple_jp")
        if not cfg:
            continue
        url = cfg.get("target_url") or ""
        p = products.get(pid, {})
        stale = next((msg for key, msg in KNOWN_STALE.items() if key in url), None)
        verified = VERIFIED_URLS.get(pid)
        action = "keep"
        if stale:
            action = "replace(old/404)"
        elif verified and verified["url"] != url:
            action = "update→verified"
        rows.append({
            "product_id": pid, "product_name": p.get("name"), "current_url": url,
            "http_status": 404 if stale else ("200" if verified else "unknown"),
            "canonical_url": (verified["url"] if verified else None),
            "resolved_product": (p.get("name") if verified else "?"),
            "exact_product_match": bool(verified),
            "action": action, "note": stale or (verified.get("note") if verified else None),
        })
    return rows


# ─────────────────────────────────────────────────────────────
# 登録: VERIFIED_URLS を product_source_config へ書込（Task2/4/5/6/7）
# ─────────────────────────────────────────────────────────────
def register_verified(c, products):
    registered = []
    for pid, v in VERIFIED_URLS.items():
        p = products.get(pid)
        if not p:
            continue
        # 価格 sanity/confidence（価格があれば検証）
        conf = v["conf"]
        price = v.get("price")
        rejection = None
        # 公式直販価格は、証拠（型番・JAN・容量・ボディー/キット・版・購入ページ・送料・販売の形・在庫の表し方・確認日）が
        # そろったときだけ確定の仕入れ値に使う。1つでも欠ければ価格を書かない（参考。Phase 16 手順6・7）
        direct_ok, direct_why = (official_direct_gate(pid, p, TODAY) if v.get("price_kind") == "official_direct"
                                 else (None, ()))
        if direct_ok is False:
            rejection = "official_direct_gate:" + ",".join(direct_why)
            price = None
        if price is not None:
            vr = validate_official_price(
                source_id=v["source"], url=v["url"], http_status=200, canonical_url=v["url"],
                product_name=p["name"], model_number=p.get("model_number") or "",
                keywords=None, detected_name=p["name"], detected_text=p["name"],
                price=price, currency="JPY", reference_price=p.get("retail_price") or None,
                link_type=v["link_type"],
            )
            if not vr.accepted:
                rejection = vr.rejection_reason
                price = None
            else:
                conf = vr.confidence
        extra = {
            "link_type": v["link_type"], "verified": True,
            # 確認した日（固定値の確認日）。毎回の実行日（TODAY）にしない
            "last_verified_at": v.get("checked_on", VERIFIED_URLS_CHECKED_ON),
            "extraction_method": "webfetch_verified",
            "confidence": conf, "official_price": price,
            "open_price": v.get("open_price", False),
            "note": v.get("note"), "price_rejection": rejection,
            "price_kind": v.get("price_kind") or ("open_price" if v.get("open_price") else "msrp"),
        }
        if direct_ok is not None:
            extra["official_direct_eligible"] = direct_ok
        if direct_ok is False:
            # 判定を通らない公式直販の行は、購入ページ（「買う」のリンク）・在庫の記録にも使わない（Phase 16 監査 L-7）
            extra["verified"] = False
        _upsert_config(c, pid, v["source"], v["url"], extra)
        # high/medium confidence の検証済み価格のみ products.official_price に反映
        # （low は main 利用禁止）。official_price_updated_at には「その価格を確認した日」を入れる。
        # スクリプトの実行時刻（NOW）は入れない: 固定値を毎日「今確認した」ように見せないため
        if direct_ok is False:
            # 判定を通らなかった公式直販価格は、同じ取得元が先に書いた値があっても確定の定価に残さない
            c.execute("UPDATE products SET official_price=NULL, official_price_source='', "
                      "official_price_updated_at=NULL WHERE id=? AND official_price_source=?", (pid, v["source"]))
        if price and conf in ("high", "medium"):
            c.execute("UPDATE products SET official_price=?, official_price_source=?, "
                      "official_price_updated_at=? WHERE id=?",
                      (price, v["source"], v.get("checked_on", VERIFIED_URLS_CHECKED_ON), pid))
        # 人が公式ページで在庫の表示も確認したときだけ、確認した時刻つきで在庫を記録する
        # collector がそれより新しい在庫の表示を取っていれば、古い確認で上書きしない
        # 確認から CURRENT_DAYS（7日）を過ぎた在庫の記録は書かない（Phase 14 監査 M-1）。CI は毎回 DB を作り直すので、
        # 期限を見ない古い判定（初心者向けの分類・LINE の文面など）にも、古い「在庫あり」が残らない
        if v.get("stock") and v.get("stock_checked_at") and _stock_record_is_current(v["stock_checked_at"]) \
                and direct_ok is not False:
            c.execute("UPDATE products SET official_stock_status=?, official_stock_observed_at=? WHERE id=? "
                      "AND (official_stock_observed_at IS NULL OR official_stock_observed_at = '' "
                      "OR official_stock_observed_at < ?)",
                      (v["stock"], v["stock_checked_at"], pid, v["stock_checked_at"]))
        registered.append({"product_id": pid, "source": v["source"], "url": v["url"],
                           "link_type": v["link_type"], "confidence": conf,
                           "official_price": price, "verified": extra["verified"],
                           "price_kind": extra["price_kind"], "official_direct_eligible": direct_ok,
                           "price_rejection": rejection})
    # 検証不能は verified=false で明示（推測URLは登録しない＝target_url空のまま記録）
    for pid, u in UNVERIFIED.items():
        p = products.get(pid)
        if not p:
            continue
        extra = {"link_type": None, "verified": False, "last_verified_at": None,
                 "extraction_method": None, "confidence": "low", "official_price": None,
                 "needs_manual_verification": True, "reason": u["reason"], "model": u["model"]}
        _upsert_config(c, pid, u["source"], "", extra)
        registered.append({"product_id": pid, "source": u["source"], "url": None,
                           "verified": False, "reason": u["reason"]})
    # 公式で今は売っていない商品: 以前の確認済み定価を外す（設定値の参考価格に戻る）
    for pid, u in OFFICIAL_NOT_SOLD.items():
        if not products.get(pid):
            continue
        extra = {"link_type": None, "verified": False, "last_verified_at": u["checked_on"],
                 "extraction_method": None, "confidence": "low", "official_price": None,
                 "official_not_sold": True, "reason": u["reason"]}
        _upsert_config(c, pid, u["source"], "", extra)
        # official_price_source は文字列の列（ProductModel が str を要求する）なので NULL でなく空にする
        # 公式で販売終了なので is_discontinued も立てる（旧UIの表示・案件の分類が「販売終了」として扱う）
        c.execute("UPDATE products SET official_price=NULL, official_price_source='', "
                  "official_price_updated_at=NULL, is_discontinued=1 WHERE id=?", (pid,))
        registered.append({"product_id": pid, "source": u["source"], "url": None, "verified": False,
                           "official_not_sold": True, "reason": u["reason"]})
    c.commit()
    return registered


RECHECK_PATH = ROOT / "exports" / "official_recheck" / "latest.json"


def apply_recheck(c, products, path: Path | None = None) -> list[dict]:
    """公式の再確認（scripts/recheck_official.py）の結果を DB に反映する（Phase 15）。

    - unchanged（型番が一致し価格が記録と同じ）: 価格を確認した日を、実際に取得した日に進める（本当の観測。
      記録の確認日より古い結果では戻さない）
    - changed・sale_ended: 確認済みの定価を外す（人が確かめて VERIFIED_URLS を直すまで確定に使わない）
    - 在庫: 明示の表示を読み取れたときだけ、取得した時刻つきで記録する（確認から7日以内・より新しいときだけ）
    - failed・blocked: 何もしない（前回の価格は消さない。確認日も在庫の時刻も新しくしない）
    """
    try:
        data = json.loads(Path(path or RECHECK_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    applied = []
    today = NOW.date().isoformat()
    for r in data.get("results") or []:
        pid, st, at = r.get("product_id"), r.get("status"), str(r.get("observed_at") or "")
        v = VERIFIED_URLS.get(pid)
        if not v or pid not in products or not at:
            continue
        # 結果が今の記録（URL・型番・記録の価格）と同じものに対する再確認か（記録を直した後の古い結果で
        # 反映しない。Phase 15 監査 L-2）
        model = str((products.get(pid) or {}).get("model_number") or "")
        if r.get("url") != v["url"] or r.get("recorded_price") != v.get("price") \
                or (model and r.get("model") and r.get("model") != model):
            continue
        if st == "unchanged" and r.get("price") == v.get("price"):
            day = at[:10]
            # 記録の確認日より新しく、今日より未来でない日だけ（壊れた結果・時計のずれで未来の日にしない。L-1）
            if str(v.get("checked_on") or "") < day <= today:
                c.execute("UPDATE products SET official_price_updated_at=? WHERE id=? AND official_price=?",
                          (day, pid, v.get("price")))
                # 設定の行の確認日も合わせる（監査の表の確認日と食い違わないように。L-4）
                c.execute("UPDATE product_source_config SET extra_config = json_set(COALESCE(extra_config, '{}'), "
                          "'$.last_verified_at', ?) WHERE product_id=? AND source_id=? "
                          "AND COALESCE(json_extract(extra_config, '$.verified'), 0) = 1", (day, pid, v["source"]))
                applied.append({"product_id": pid, "action": "price_reconfirmed", "on": day})
        elif st in ("changed", "sale_ended"):
            c.execute("UPDATE products SET official_price=NULL, official_price_source='', "
                      "official_price_updated_at=NULL WHERE id=?", (pid,))
            # 公式の購入ページとしても使わない（確認済みの印を外す。人が確かめて VERIFIED_URLS を直すまで。M-3）
            # 新しい価格を自動で確定にしない: 人の確認待ち（REVIEW_REQUIRED）にする（Phase 16 手順43）
            c.execute("UPDATE product_source_config SET extra_config = json_set(COALESCE(extra_config, '{}'), "
                      "'$.verified', json('false'), '$.official_price', json('null'), '$.recheck_status', ?, "
                      "'$.review_status', 'REVIEW_REQUIRED') WHERE product_id=? AND source_id=?",
                      (st, pid, v["source"]))
            applied.append({"product_id": pid, "action": f"price_{st}_needs_review", "observed": r.get("price"),
                            "review_status": "REVIEW_REQUIRED"})
        # 在庫は、価格まで記録と一致した（unchanged）読み取りのときだけ記録する（価格が食い違った読み取りの在庫は
        # 別の商品の行かもしれないので信用しない。監査 N-1）
        if st == "unchanged" and r.get("stock") and _stock_record_is_current(at) and at[:10] <= today:
            # 判定を通らず購入ページとして使わない行（verified が外れた行）の在庫は書かない（再監査 Low-2）
            cur = c.execute("UPDATE products SET official_stock_status=?, official_stock_observed_at=? WHERE id=? "
                            "AND (official_stock_observed_at IS NULL OR official_stock_observed_at = '' "
                            "OR official_stock_observed_at < ?) AND EXISTS (SELECT 1 FROM product_source_config "
                            "WHERE product_id=? AND source_id=? "
                            "AND COALESCE(json_extract(extra_config, '$.verified'), 0) = 1)",
                            (r["stock"], at, pid, at, pid, v["source"]))
            if getattr(cur, "rowcount", 1) != 0:
                applied.append({"product_id": pid, "action": "stock_observed", "stock": r["stock"], "at": at})
    c.commit()
    return applied


def _stock_record_is_current(checked_at: str, now: datetime | None = None) -> bool:
    """在庫の確認の記録が、確認から CURRENT_DAYS（7日）以内か（読めない・未来すぎる記録は使わない）。"""
    from src.market import price_evidence as pe
    try:
        at = datetime.fromisoformat(str(checked_at))
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=JST)
    age = ((now or NOW) - at).total_seconds() / 86400
    return -1 <= age <= pe.CURRENT_DAYS


def _upsert_config(c, pid, sid, url, extra):
    cur = c.execute("SELECT id FROM product_source_config WHERE product_id=? AND source_id=?",
                    (pid, sid)).fetchone()
    ej = json.dumps(extra, ensure_ascii=False)
    if cur:
        c.execute("UPDATE product_source_config SET target_url=?, extra_config=?, is_active=1 WHERE id=?",
                  (url, ej, cur["id"]))
    else:
        import hashlib
        cid = "psc_" + hashlib.md5(f"{pid}:{sid}".encode()).hexdigest()[:16]
        c.execute("INSERT INTO product_source_config (id,product_id,source_id,target_url,extra_config,is_active,created_at) "
                  "VALUES (?,?,?,?,?,1,?)", (cid, pid, sid, url, ej, NOW.isoformat()))


# ─────────────────────────────────────────────────────────────
# Task7: product_source_config マトリクス（official + retailers）
# ─────────────────────────────────────────────────────────────
def source_matrix(c, products):
    configs = _existing_configs(c)
    matrix = {}
    for pid, p in products.items():
        srcs = configs.get(pid, {})
        entry = {"product_name": p["name"], "brand": p["brand"], "sources": {}}
        # official
        off = None
        for sid in ("src_apple_jp", "src_ricoh_imaging", "src_fujifilm_official",
                    "src_canon_official", "src_nikon_direct", "src_sony_store"):
            if sid in srcs:
                cfg = srcs[sid]
                ex = json.loads(cfg.get("extra_config") or "{}")
                off = {"url": cfg.get("target_url") or None, "link_type": ex.get("link_type"),
                       "verified": ex.get("verified", False), "last_verified_at": ex.get("last_verified_at"),
                       "extraction_method": ex.get("extraction_method"),
                       "confidence": ex.get("confidence"), "official_price": ex.get("official_price"),
                       "enabled": bool(cfg.get("is_active", 1)),
                       "reason_if_disabled": ex.get("reason") or ex.get("price_rejection")}
                break
        entry["sources"]["official"] = off
        # retailers
        for sid in RETAILER_SOURCES:
            label = RETAILER_LABEL[sid]
            if sid in srcs:
                cfg = srcs[sid]
                ex = json.loads(cfg.get("extra_config") or "{}")
                entry["sources"][label] = {"url": cfg.get("target_url") or None,
                                           "link_type": ex.get("link_type"),
                                           "verified": ex.get("verified", False),
                                           "enabled": bool(cfg.get("is_active", 1))}
            else:
                entry["sources"][label] = None
        matrix[pid] = entry
    return matrix


# ─────────────────────────────────────────────────────────────
# Task10/11: メーカー別レポート + Before/After
# ─────────────────────────────────────────────────────────────
def maker_report(registered, products):
    by_maker = defaultdict(lambda: {"products": 0, "url_verified": 0, "http_200": 0,
                                     "exact_match": 0, "price_ok": 0, "high_conf": 0,
                                     "failed": 0, "failures": []})
    seen = set()
    for r in registered:
        maker = MAKER_OF.get(r["source"], r["source"])
        m = by_maker[maker]
        if r["product_id"] not in seen:
            m["products"] += 1
            seen.add((maker, r["product_id"]) if False else r["product_id"])
        if r.get("verified"):
            m["url_verified"] += 1
            m["http_200"] += 1
            if r.get("official_price"):
                m["price_ok"] += 1
            if r.get("confidence") == "high":
                m["high_conf"] += 1
                m["exact_match"] += 1
        else:
            m["failed"] += 1
            m["failures"].append({"product_id": r["product_id"], "reason": r.get("reason")})
    return dict(by_maker)


def main():
    c = _conn()
    products = _products(c)
    configs_before = _existing_configs(c)

    # Before: 現行の公式取得成功（official_price>0 の商品数）
    before_ok = sum(1 for p in products.values() if (p.get("official_price") or 0) > 0)
    before_total = sum(1 for pid, srcs in configs_before.items() if any(
        s in srcs for s in MAKER_OF))

    task1 = apple_audit(products, configs_before)
    registered = register_verified(c, products)
    rechecked = apply_recheck(c, products)     # 公式の再確認の結果（Phase 15）
    # 再確認で確認済みの印を外したもの（価格が変わった・販売終了）は、この監査の出力でも確認済みに数えない（N-3）
    _unverified_now = {a["product_id"] for a in rechecked if str(a.get("action", "")).endswith("_needs_review")}
    for r in registered:
        if r.get("product_id") in _unverified_now:
            r["verified"], r["official_price"] = False, None
    matrix = source_matrix(c, products)
    makers = maker_report(registered, products)

    # After: 検証済みURL + 価格取得
    after_verified = sum(1 for r in registered if r.get("verified"))
    after_price = sum(1 for r in registered if r.get("official_price"))

    report = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "scope": "公式ソース登録・検証（利益/AI/Opportunity/Notification/Capital/Execution は不変）",
        "methodology": {
            "verification": "WebFetch で HTTP200/公式ドメイン/canonical/商品一致を実確認したURLのみ verified",
            "no_guess_url": "推測URLは verified 扱いしない（検証不能は needs_manual_verification）",
            "open_price": "オープン価格のメーカー(Fujifilm/Nikon等)は公式定価なし→category/価格null",
            "no_fake_freshness": "実検証した日時のみ last_verified_at に記録（Task12）",
        },
        "apple_audit": task1,
        "registered": registered,
        "source_matrix": matrix,
        "maker_report": makers,
        "success_rate": {
            "before": {"official_price_products": before_ok, "official_configs": before_total},
            "after": {"url_verified": after_verified, "price_captured": after_price,
                      "verified_targets": len(VERIFIED_URLS), "unverified_targets": len(UNVERIFIED)},
            # 互換のために残す（Phase 15 の置き場所。読むときは上の階層の recheck_applied を使う）
            "recheck_applied": rechecked,
        },
        # 公式の再確認の結果を反映したもの（価格の再確認・価格の変化・在庫の観測）。Phase 16 で success_rate の下から
        # 出力の上の階層へ移した
        "recheck_applied": rechecked,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "latest.md").write_text(render_md(report), encoding="utf-8")
    c.close()
    print(f"[official_audit] verified={after_verified} price_captured={after_price} "
          f"unverified={len(UNVERIFIED)} → {OUT/'latest.json'}")
    return 0


def render_md(r):
    L = ["# Official Source Registry & Validation\n",
         f"> 生成: {r['generated_at']} / {r['scope']}\n"]
    L.append("## メーカー別サマリ")
    L.append("| Maker | Products | URL verified | HTTP200 | exact match | price auto | high conf | failed |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for maker, m in r["maker_report"].items():
        L.append(f"| {maker} | {m['products']} | {m['url_verified']} | {m['http_200']} | "
                 f"{m['exact_match']} | {m['price_ok']} | {m['high_conf']} | {m['failed']} |")
    L.append("")
    sr = r["success_rate"]
    L.append("## 自動取得率 Before → After")
    L.append(f"- Before: 公式定価あり商品 {sr['before']['official_price_products']} / 公式config {sr['before']['official_configs']}")
    L.append(f"- After: URL検証済 {sr['after']['url_verified']} / 価格取得 {sr['after']['price_captured']} "
             f"（検証対象 {sr['after']['verified_targets']} / 検証不能 {sr['after']['unverified_targets']}）")
    L.append("")
    L.append("## Apple Source Audit（旧URL検出）")
    L.append("| product | current_url | http | action | note |")
    L.append("|---|---|--:|---|---|")
    for a in r["apple_audit"]:
        L.append(f"| {a['product_id']} | {a['current_url']} | {a['http_status']} | {a['action']} | {a['note'] or ''} |")
    L.append("")
    L.append("## 自動取得できた公式価格（検証済）")
    L.append("| product | source | price | link_type | confidence |")
    L.append("|---|---|--:|---|---|")
    for x in r["registered"]:
        if x.get("official_price"):
            L.append(f"| {x['product_id']} | {x['source']} | ¥{x['official_price']:,} | {x.get('link_type')} | {x.get('confidence')} |")
    L.append("")
    L.append("## 検証不能（要手動検証・推測登録しない）")
    L.append("| product | source | reason |")
    L.append("|---|---|---|")
    for x in r["registered"]:
        if not x.get("verified"):
            L.append(f"| {x['product_id']} | {x['source']} | {x.get('reason')} |")
    L.append("")
    L.append("## 次に改善すべきsource")
    L.append("1. **EBAY_APP_ID 設定**（海外相場の自動fresh化・最優先）")
    L.append("2. **Canon/Sony 公式ストアの手動URL検証**（当環境からDNS不可のため）")
    L.append("3. **Apple 512GB等の個別config価格**（購入フローの個別ページ）")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
