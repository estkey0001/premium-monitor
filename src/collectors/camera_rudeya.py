# -*- coding: utf-8 -*-
"""カメラの買取ルデヤ（kaitori-rudeya.com）の取得結果を、camera_refresh の調査行（research_camera_*.json の buyback）に変える。

- 一覧ページ（固定のカテゴリ）は TCG と同じカード形式なので、src/tcg/buyback.parse_rudeya と accept_state（fail-closed）を再利用する。
- 機種の同一性は 設定の JAN + 名前（name_contains / name_excludes）。JAN 一致だけで確定しない。
- 価格は「一覧」と「商品ページ」で一致したものだけ採用する（食い違う行は採用しない）。受付中と確認できない行は行を作らない。
- この関数は通信しない（取得は scripts/collect_camera_rudeya.py が polite 経由で行う）。取れなかったことを成功として書かない。
"""
from __future__ import annotations

import html as _html
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.tcg import buyback as bb

JST = timezone(timedelta(hours=9))
SHOP = "買取ルデヤ"
ACTIVE_TEXT = "ただいま買取受付中"
_ITEM_ASOF = re.compile(r"(20\d{2})-(\d{2})-(\d{2})\s*現在")
_ITEM_PRICE = re.compile(r"買取価格\s*[¥￥]\s*([\d,]+)")
_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _nfkc(s) -> str:
    """比較用の表記（NFKC・小文字・空白なし）。「Z 8」「GR  IIIx」のような空白の揺れを無視する。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s or "")).lower())


_MODAL_ACTION = re.compile(r'''\s*<a href="#" class="product-card-btn is-more js-modal-open modal_more" data-target="modal_c(\d+)">条件を選ぶ</a>\s*(?:</div>\s*)*(?:</article>\s*)?''', re.S)
SIGNAL_MODAL = "CONDITION_MODAL"


_STAMP_NG = re.compile(r"店舗印あり.*?買取不可")
_STAMP_DED = re.compile(r"店舗印あり\s*[-−ー－]\s*([\d,]+)\s*円")
_MODAL_STAMPED = re.compile(r"保証書店舗印あり\s*買取\s*[¥￥]\s*([\d,]+)")
STAMP_NOT_BUYABLE, STAMP_DEDUCTION, STAMP_UNKNOWN = "NOT_BUYABLE", "DEDUCTION", "UNKNOWN"
COND_COMPLETE, COND_STAMPED = "COMPLETE_NO_STAMP", "STAMPED_WARRANTY"       # 条件別の価格の種類（完品 = 保証書に店舗印なし / 店舗印あり）


def stamp_policy(memo: str, price: int, modal_text: str = "") -> dict:
    """保証書に店舗印がある（店で買った新品）場合の買取条件。完品（店舗印なし）の価格は、店で買った新品には当てはまらないことが多い。
    - 「店舗印あり買取不可」→ NOT_BUYABLE（店で買った新品の売却先にならない）
    - 「保証書店舗印あり-N円」→ DEDUCTION（店舗印ありの価格 = 完品 - N）。条件の画面に店舗印ありの価格があれば突き合わせ、食い違えば UNKNOWN
    - どちらも読めない → UNKNOWN（採用しない）"""
    t = unicodedata.normalize("NFKC", memo or "")
    if _STAMP_NG.search(t):
        return {"policy": STAMP_NOT_BUYABLE}
    m = _STAMP_DED.search(t)
    if m:
        ded = bb._int(m.group(1))
        if ded and 0 < ded < price:
            mm = _MODAL_STAMPED.search(unicodedata.normalize("NFKC", modal_text or ""))
            if mm and bb._int(mm.group(1)) != price - ded:
                return {"policy": STAMP_UNKNOWN, "why": f"条件の画面の店舗印ありの価格 {mm.group(1)} 円が、完品 {price} 円 - {ded} 円と一致しない"}
            return {"policy": STAMP_DEDUCTION, "deduction": ded, "price": price - ded}
    return {"policy": STAMP_UNKNOWN, "why": "店舗印ありの扱いが備考から読めない"}


def parse_list(html: str, page_url: str, now: datetime) -> list:
    """一覧ページの行（TCG と同じ parse_rudeya）。申込欄が「条件を選ぶ」の形（備考に減額が入る機種）の行には、
    停止の信号が無く、形が既知の形に完全一致するときだけ list_signal = CONDITION_MODAL を付ける。
    この信号は受付中の証拠ではない（受付中は商品ページの「ただいま買取受付中」で確認する）。UNKNOWN のまま実行には使わない。"""
    rows = bb.parse_rudeya(html, page_url, now)["rows"]
    by_item: dict = {}
    for art in re.findall(r'<article class="pgrid-card".*?</article>', html or "", re.S):
        m = re.search(r"/product/item/(\d+)", art)
        if m:
            by_item[m.group(1)] = art
    for r in rows:
        m = re.search(r"/product/item/(\d+)$", str(r.get("item_url") or ""))
        art = by_item.get(m.group(1)) if m else None
        i = (html or "").find(f'id="modal_c{m.group(1)}"') if m else -1
        if m and art and f'data-target="modal_o{m.group(1)}"' in art:
            j = (html or "").find(f'id="modal_o{m.group(1)}"')
            r["attention"] = (bb._text(re.sub(r"^[^>]*>", "", (html or "")[j:j + 1500])).split("閉じる")[0].strip()[:60] or "注意事項あり") if j >= 0 else "注意事項あり"      # 店自身の注意事項（「JANコード要確認」等）
        r["stamp"] = stamp_policy(r.get("condition_text") or "", r.get("price") or 0, bb._text((html or "")[i:i + 3500]) if i >= 0 else "")
        if not art or r.get("accept_state") != bb.A_UNKNOWN:
            continue
        blk = bb._RUDEYA_ACTION.search(re.sub(r"<!--.*?-->", " ", art, flags=re.S))
        mm = _MODAL_ACTION.fullmatch(blk.group(1)) if blk else None
        if mm and mm.group(1) == m.group(1):
            r["list_signal"] = SIGNAL_MODAL
    return rows


def parse_item_page(html: str) -> dict:
    """商品ページ。{name, jan, price, asof(YYYY-MM-DD), active(bool)}。読めなかった項目は None。備考（店舗印の扱い）は一覧の行から読む。"""
    html = html or ""
    name = jan = None
    for blob in _LD.findall(html):
        try:
            d = json.loads(blob)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            name, jan = d.get("name"), d.get("gtin13")
    body = re.sub(r"<!--.*?-->", " ", html, flags=re.S)              # コメントを先に除く（コメントの中の「<style>」の文字で、後ろの価格まで消えないように）
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S)
    text = bb._text(body)
    price_m, asof_m = _ITEM_PRICE.search(text), _ITEM_ASOF.search(text)
    stopped = bool(bb._STOP_TEXT.search(text)) or bool(bb._STOP_CLASS.search(body))
    return {
        "name": _html.unescape(name) if name else None,
        "jan": str(jan) if jan else None,
        "price": bb._int(price_m.group(1)) if price_m else None,
        "asof": f"{asof_m.group(1)}-{asof_m.group(2)}-{asof_m.group(3)}" if asof_m else None,
        "active": ACTIVE_TEXT in text and not stopped,      # 明示の「ただいま買取受付中」があり、停止の語・クラスが無いときだけ
    }


def identity_ok(item: dict, name: str, jan: Optional[str]) -> tuple[bool, str]:
    """設定の機種と、店の商品が同一か。JAN・名前（含む語・除く語）のすべてが合うこと。"""
    if not jan or str(jan) != str(item["jan"]):
        return False, f"JAN が一致しない（店 {jan} / 設定 {item['jan']}）"
    n = _nfkc(name)
    for w in item.get("name_contains") or []:
        if _nfkc(w) not in n:
            return False, f"商品名に「{w}」が無い"
    for w in item.get("name_excludes") or []:
        if _nfkc(w) in n:
            return False, f"商品名に別の版を示す「{w}」がある"
    return True, ""


def build_rows(cfg: dict, list_rows: list, fetch_item, today: str, lists_complete: bool = True) -> tuple[list, list]:
    """設定の機種ごとに、一覧の行を探し、商品ページ（fetch_item(item_url) -> html or None）で確認して、調査行を作る。
    戻り値: (products, notes)。products は research_camera の products の形。notes は採用しなかった理由（機種ごと）。"""
    products: dict = {}
    notes: list = []
    jans = {str(r.get("jan")) for r in list_rows}
    structure_changed = not any(str(i["jan"]) in jans for i in cfg.get("items") or [])       # 設定の機種が 1 件も見つからない = 一覧の構造が変わった可能性（機種が全部同時に消えたとは考えない）
    for it in cfg.get("items") or []:
        want = str(it["jan"])
        cands = [r for r in list_rows if str(r.get("jan")) == want]
        if not cands:
            # 一覧ページを全部取得できていない・構造が変わった疑いのときは、載っているのか読めなかったのか分からない（通信の失敗として扱い、前回の行を引き継ぐ）
            sure = bool(lists_complete) and not structure_changed
            reason = ("一覧に載っていない（JAN が見つからない）" if sure else
                      "一覧から設定の機種を 1 件も見つけられない（構造が変わった可能性）" if structure_changed else
                      "一覧ページを全部は取得できなかったため、載っているか確認できない")
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": sure, "reason": reason})
            continue
        if len({r.get("price") for r in cands}) > 1:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": "同じ JAN に違う価格が並んでいる（どれか決められない）"})
            continue
        row = cands[0]
        if any(r.get("attention") for r in cands):
            at = next(r["attention"] for r in cands if r.get("attention"))
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": f"店が注意事項を付けている（{at}）。同一性を確認できないので採用しない"})
            continue
        if len({(r.get("accept_state"), r.get("list_signal"), (r.get("stamp") or {}).get("policy"), (r.get("stamp") or {}).get("price")) for r in cands}) > 1:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": "同じ JAN の行の間で、受付状態・店舗印・注意事項の扱いが食い違う（先頭の行だけで決めない）"})
            continue
        ok, why = identity_ok(it, row.get("raw_product_name"), row.get("jan"))
        if not ok:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": why})
            continue
        if row.get("accept_state") != bb.A_ACTIVE and not (row.get("accept_state") == bb.A_UNKNOWN and row.get("list_signal") == SIGNAL_MODAL):
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": f"一覧の受付状態が {row.get('accept_state')}（{row.get('accept_reason')}）"})
            continue
        if row.get("condition") not in (bb.C_NEW, bb.C_UNOPENED, bb.C_SEALED):
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": f"一覧の状態が新品と確認できない（{row.get('condition')}）"})
            continue
        url = row.get("item_url") or f"https://kaitori-rudeya.com/product/item/{it['item']}"
        if not re.search(r"/product/item/%s$" % it["item"], url):
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": f"商品ページの URL が設定と一致しない（{url}）"})
            continue
        stamp = row.get("stamp") or {"policy": STAMP_UNKNOWN, "why": "店舗印の扱いを読んでいない"}
        if stamp["policy"] == STAMP_NOT_BUYABLE:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "stamp_policy": STAMP_NOT_BUYABLE, "full_price": row.get("price"),
                          "reason": ("店舗印ありは買取不可（店で買った新品の売却先にならない。" + (f"完品の価格 {row['price']:,} 円は店舗印なしの個体の価格で、参考であり売値に採用しない）" if isinstance(row.get("price"), int) else "完品の価格は読めていない）"))})
            continue
        if stamp["policy"] != STAMP_DEDUCTION:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": "店舗印ありの買取条件を確認できない（" + str(stamp.get("why")) + "）"})
            continue
        doc = parse_item_page(fetch_item(url) or "")
        if doc["price"] is None or doc["name"] is None:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": False, "reason": "商品ページを読めなかった"})
            continue
        ok, why = identity_ok(it, doc["name"], doc["jan"])
        if not ok:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": "商品ページ: " + why})
            continue
        if not doc["active"]:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": "商品ページに「ただいま買取受付中」が無い（受付状態を確認できない）"})
            continue
        if doc["price"] != row["price"]:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": f"一覧 {row['price']} 円と商品ページ {doc['price']} 円が食い違う"})
            continue
        if not doc["asof"]:
            notes.append({"product": it["product"], "jan": want, "ok": False, "withdraw": True, "reason": "商品ページに価格の日付が無い"})
            continue
        memo = row.get("condition_text") or ""
        sell = stamp["price"]
        rec = products.setdefault(it["product"], {"product": it["product"], "registered": True, "identity_note": None,
                                                  "official": None, "retail": [], "buyback": [], "listing": [], "sold": [], "notes": None})
        rec["buyback"].append({
            "shop": SHOP, "item_title": doc["name"], "price_jpy": sell, "condition": "NEW", "price_basis": "STAMPED_WARRANTY", "url": url, "is_product_page": True,
            "checked_at": today, "source_updated_at": doc["asof"], "result": "FOUND",
            "conditions": [{"key": COND_COMPLETE, "price": doc["price"], "evidence": "list+item_page"},
                           {"key": COND_STAMPED, "price": sell, "deduction": stamp["deduction"]}],      # 条件別の確認済み価格（別々に保持。売値の採用は安全側の price_jpy だけ）
            "reason": f"一覧（新品・受付中）と商品ページ（ただいま買取受付中・{doc['asof']} 現在）で価格が一致。JAN {doc['jan']}。完品（保証書に店舗印なし）は {doc['price']:,} 円、保証書に店舗印ありは {stamp['deduction']:,} 円減って {sell:,} 円。店で買った新品に店舗印が付くかを確認できないため、安全側に店舗印ありの価格を採用。備考: {memo or 'なし'}"})
        notes.append({"product": it["product"], "jan": want, "ok": True, "price": sell, "full_price": doc["price"], "url": url})
    return list(products.values()), notes


_BRANDS = (("RICOH", "RICOH"), ("FUJIFILM", "FUJIFILM"), ("SONY", "Sony"), ("CANON", "Canon"), ("NIKON", "Nikon"))


def brand_of(product: str) -> str:
    t = _nfkc(product).upper()
    for kw, brand in _BRANDS:
        if t.startswith(kw):
            return brand
    return "その他"


def build_docs(products: list, notes: list, today: str, now: datetime, attempted: int, withdraw_default: bool = True) -> dict:
    """ブランドごとの research_camera_<ブランド>_rudeya.json の中身 {ファイル名: 内容}。
    ファイル名は、同じブランドの既存の調査ファイルの後に読まれる並びにする（機種を統合するとき、ブランドは先に読んだファイルのものが残る）。
    - source_results: ブランドごとに、採用できた件数と不採用の理由。
    - withdrawn: 意図して不採用にした機種（買取不可・注意事項・価格の食い違いなど）。camera_refresh の carry_over が、前回の公開データから
      その行を復活させない。通信の失敗（商品ページを読めなかった等）は withdrawn にしない（前回の行を日付ごと引き継ぐ）。
    採用できた行も不採用も 1 件も無い（一覧ページを取得できなかった）ときは、FAILED の取得元の結果だけを書く。"""
    def brand_of_note(n):
        return brand_of(n["product"])

    brands = sorted({brand_of(p["product"]) for p in products} | {brand_of_note(n) for n in notes if not n["ok"] and n.get("withdraw", withdraw_default)})
    if not any(n["ok"] or n.get("withdraw", withdraw_default) for n in notes):
        found = 0
        rejected = " / ".join(f"{n['product']}（{n['reason']}）" for n in notes if not n["ok"])
        return {"research_camera_RUDEYA_rudeya.json": {"brand": "その他", "research_date": today, "checked_at": now.isoformat(), "products": [], "discovered": [], "lotteries": [],
                                                      "source_results": [{"source": SHOP, "result": "FAILED", "url": "https://kaitori-rudeya.com/category/detail/10",
                                                                          "reason": f"取得できなかった。{rejected}"}]}}
    docs = {}
    for brand in brands:
        mine = [n for n in notes if brand_of_note(n) == brand]
        ok = sum(1 for n in mine if n["ok"])
        rej = " / ".join(f"{n['product']}（{n['reason']}）" for n in mine if not n["ok"])
        docs[f"research_camera_{brand}_rudeya.json"] = {
            "brand": brand, "research_date": today, "checked_at": now.isoformat(),
            "products": [p for p in products if brand_of(p["product"]) == brand], "discovered": [], "lotteries": [],
            "withdrawn": [{"product": n["product"], "shop": SHOP, "kind": "buyback", "reason": n["reason"]} for n in mine if not n["ok"] and n.get("withdraw", withdraw_default)],
            "source_results": [{"source": SHOP, "result": "FOUND", "url": "https://kaitori-rudeya.com/category/detail/10",
                                "reason": f"{brand}: 対象 {len(mine)} 件のうち {ok} 件を、一覧と商品ページで確認して採用。" + (f" 不採用: {rej}" if rej else "")}]}
    return docs
