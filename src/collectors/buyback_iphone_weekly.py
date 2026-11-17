# -*- coding: utf-8 -*-
"""PASTEC・買取ルデヤの iPhone 新品未開封の買取価格を、決定論的に読む（週次の更新用）。

- 取得は共通の作法（src/collectors/polite.py: robots.txt・同じドメインの間隔・正直な User-Agent・リダイレクトなし）だけ。
  CAPTCHA・WAF の回避、プロキシ、UA の偽装はしない。ブロック・失敗した店は、その実行では取り直さない。
- 読むのは「新品未開封」の価格だけ。中古（範囲表示）の行は読まない。条件・容量・機種が完全に一致する行だけを返す。
- 読めなかった行は返さない（古い値を新しい値にしない）。読めた行にだけ、ページ自身の更新日・時刻を付ける。
  ページに更新日が無ければ「更新日の記載なし」とし、取得した日を更新日にしない（鮮度は UNKNOWN になる）。
- 結果は週次の入力（iphone_exp_*.json の店エントリ）と同じ形。新しい schema は作らない。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

JST = timezone(timedelta(hours=9))
PASTEC_URL = "https://pastec.net/iphone/"
RUDEYA_URL = "https://kaitori-rudeya.com/series/iphone18"
SHOP_PASTEC = "パステック（PASTEC）"
SHOP_RUDEYA = "買取ルデヤ"
CONDITION = "UNOPENED"

_MODELS = {"iphoneduo": "iPhone Duo", "iphone18pro": "iPhone 18 Pro", "iphone18promax": "iPhone 18 Pro Max"}
_CAP_RE = re.compile(r"^(256GB|512GB|1TB|2TB)$")
_YEN_RE = re.compile(r"^([\d,]+)円$")


def norm_model(name: str) -> Optional[str]:
    """表記ゆれ（iPhoneDuo / iPhone Duo / iPhone18 Pro Max）を正本の機種名にする。対象外の機種は None。"""
    return _MODELS.get(re.sub(r"\s+", "", str(name or "")).lower())


def _lines(html: str) -> list[str]:
    from bs4 import BeautifulSoup
    return BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True).split("\n")


def _yen(s: str) -> Optional[int]:
    m = _YEN_RE.match(s.strip())
    return int(m.group(1).replace(",", "")) if m else None


# ---------------- PASTEC ----------------
_PASTEC_HEAD = re.compile(r"^(iPhone ?[A-Za-z0-9 ]+?) (256GB|512GB|1TB|2TB)$")
_PASTEC_UPDATED = re.compile(r"買取価格更新日[：:]\s*(20\d{2})/(\d{1,2})/(\d{1,2})")
_PASTEC_REDUCTION = re.compile(r"^(.+?)-([\d,]+)円?\((.*)\)$")


def parse_pastec(html: str) -> dict:
    """{"updated": "YYYY-MM-DD"|None, "rows": {(機種, 容量): {"price": int, "reductions": {色: 減額}, "colors_ok": bool}}}。

    1 行の読み方: 「<機種> <容量>」の見出し → 色の減額（任意）→「未開封品買取価格」→「<金額>円」。次の見出しまでに
    未開封の価格が 1 つも無い・金額が読めない行は返さない。色の減額の行が読めない形なら colors_ok=False（実行可能価格にしない）。
    """
    lines = _lines(html)
    updated = None
    for ln in lines:
        m = _PASTEC_UPDATED.search(ln)
        if m:
            try:
                updated = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
            except ValueError:
                updated = None
            break
    rows: dict = {}
    i = 0
    while i < len(lines):
        m = _PASTEC_HEAD.match(lines[i])
        model = norm_model(m.group(1)) if m else None
        if not model:
            i += 1
            continue
        cap = m.group(2)
        j, reductions, ok, price = i + 1, {}, True, None
        while j < len(lines) and not _PASTEC_HEAD.match(lines[j]) and lines[j] != "買取価格詳細":
            if lines[j] == "未開封品買取価格":
                price = _yen(lines[j + 1]) if j + 1 < len(lines) else None
                break
            r = _PASTEC_REDUCTION.match(lines[j])
            if r:
                if "未開封" in r.group(3):                    # 未開封に効く減額だけ数える（開封済だけの減額は無関係）
                    reductions[r.group(1).strip()] = int(r.group(2).replace(",", ""))
            elif lines[j] not in ("中古買取価格",):
                ok = False                                    # 色の減額らしい読めない行
            j += 1
        if price and (model, cap) not in rows:
            rows[(model, cap)] = {"price": price, "reductions": reductions, "colors_ok": ok}
        i = max(j, i + 1)
    return {"updated": updated, "rows": rows}


# ---------------- 買取ルデヤ ----------------
_RUDEYA_HEAD = re.compile(r"^(iPhone ?[A-Za-z0-9 ]+?)の全商品の買取価格を見る")
_RUDEYA_ASOF = re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})時(\d{1,2})分現在")
_RUDEYA_RANGE = re.compile(r"^([\d,]+)〜([\d,]+)円$")


def parse_rudeya(html: str) -> dict:
    """{"as_of": "YYYY-MM-DD HH:MM"|None, "rows": {(機種, 容量): {"price": int} | {"range": (低, 高)}}}。

    表の価格は新品未開封・SIMフリー。単一の価格は色によらない価格、範囲（色で違う）は価格にしない（range）。
    """
    lines = _lines(html)
    as_of = None
    for ln in lines:
        m = _RUDEYA_ASOF.search(ln)
        if m:
            try:
                as_of = datetime(*(int(x) for x in m.groups())).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                as_of = None
            break
    rows: dict = {}
    i = 0
    while i < len(lines):
        m = _RUDEYA_HEAD.match(lines[i])
        model = norm_model(m.group(1)) if m else None
        i += 1
        if not model:
            continue
        while i < len(lines) and (lines[i] == "容量" or lines[i].startswith("買取価格（")):
            i += 1                                            # 表の見出し行を読み飛ばす
        while i + 1 < len(lines) and _CAP_RE.match(lines[i]):
            cap, val = lines[i], lines[i + 1]
            single, rng = _yen(val), _RUDEYA_RANGE.match(val)
            if single:
                rows[(model, cap)] = {"price": single}
            elif rng:
                rows[(model, cap)] = {"range": (int(rng.group(1).replace(",", "")), int(rng.group(2).replace(",", "")))}
            i += 2
    return {"as_of": as_of, "rows": rows}


# ---------------- 週次の入力（店エントリ）への変換 ----------------
def _sku(model: str, cap: str) -> str:
    return f"{model} {cap}"


def pastec_entry(parsed: dict, fetched_on: str, models: tuple) -> Optional[dict]:
    rows = []
    for (model, cap), r in sorted(parsed["rows"].items()):
        if model not in models:
            continue
        base = r["price"]
        row = {"sku": _sku(model, cap), "condition": CONDITION, "base_price": base}
        if r["colors_ok"]:
            worst = base - max(r["reductions"].values(), default=0)
            row["color_adjustments"] = {c: base - d for c, d in r["reductions"].items()}
            row["executable_price"] = {"no_reduction": base, "max_reduction_color": worst}
        else:
            row["color_adjustments"] = "色の減額の行を読み取れない（実行可能価格にしない）"
        rows.append(row)
    if not rows:
        return None
    upd = parsed["updated"]
    checked = f"{fetched_on} JST（ページ記載: 買取価格更新日 {upd.replace('-', '/')}）" if upd else \
        f"{fetched_on} JST 取得（ページに更新日の記載なし）"
    return {"shop_name": SHOP_PASTEC, "official_url": "https://pastec.net/", "price_page_url": PASTEC_URL,
            "checked_at": checked, "fetch_status": "ACTIVE", "discovered": True,
            "reason": f"{fetched_on} に polite 取得（決定論的）。読めた行だけを載せる。中古は読まない",
            "carrier_or_region": "UNKNOWN（版の区別はページで確認できず）", "campaign": None,
            "conditions": "未開封品買取価格の行だけ。減額の適用条件・バッテリー減額の説明はページになし。",
            "prices": rows}


def rudeya_entry(parsed: dict, fetched_on: str, models: tuple) -> Optional[dict]:
    rows = []
    for (model, cap), r in sorted(parsed["rows"].items()):
        if model not in models:
            continue
        row = {"model": model, "storage": cap, "condition": CONDITION}
        if "price" in r:
            p = r["price"]
            row.update({"base_price": p, "color_adjustments": {}, "executable_price_no_deduction": p,
                        "executable_price_max_deduction": p})
        else:
            row.update({"range_new": f"{r['range'][0]:,}〜{r['range'][1]:,}", "note": "色で差がある容量は範囲表示。色ごとの価格は未確認"})
        rows.append(row)
    if not rows:
        return None
    asof = parsed["as_of"]
    checked = f"{asof} (ページ表示の「{asof[11:].replace(':', '時')}分現在」)" if asof else \
        f"{fetched_on} JST 取得（ページに更新日の記載なし）"
    return {"shop_name": SHOP_RUDEYA, "official_url": "https://kaitori-rudeya.com/", "price_page_url": RUDEYA_URL,
            "checked_at": checked, "fetch_status": "ACTIVE",
            "reason": f"{fetched_on} に polite 取得（決定論的）。単一価格の容量は色によらない価格、範囲の容量は価格にしない",
            "carrier_or_region": "未開封・SIMフリー(国内版)。キャリア版の価格は記載なし。",
            "condition_note": "全て UNOPENED。価格は店頭買取。", "campaign": "ページ上に記載なし。",
            "conditions": "IMEI 判定が〇か-のみ。承認メール時点で価格保証、承認後は価格変更・キャンセル不可。",
            "skus": rows}


def _default_fetch(url: str):
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))
    import recheck_official
    return recheck_official._fetch(url)


SHOPS = {"pastec": (PASTEC_URL, parse_pastec, pastec_entry, SHOP_PASTEC),
         "rudeya": (RUDEYA_URL, parse_rudeya, rudeya_entry, SHOP_RUDEYA)}


def fetch_shop(key: str, *, models: tuple = ("iPhone Duo",), fetch: Optional[Callable] = None,
               now: Optional[datetime] = None) -> dict:
    """{"key", "shop_name", "ok": bool, "entry": 店エントリ|None, "rows": 件数, "error": 理由|None}。失敗しても例外にしない。"""
    url, parse, build, name = SHOPS[key]
    now = now or datetime.now(JST)
    body, why = (fetch or _default_fetch)(url)
    if not body:
        return {"key": key, "shop_name": name, "ok": False, "entry": None, "rows": 0, "error": why or "fetch_failed"}
    try:
        parsed = parse(body)
    except Exception as e:                                    # noqa: BLE001 - 形式の変化は失敗として返す（古い値を使わない）
        return {"key": key, "shop_name": name, "ok": False, "entry": None, "rows": 0, "error": f"parse_error:{type(e).__name__}"}
    entry = build(parsed, now.strftime("%Y-%m-%d"), models)
    if not entry:
        return {"key": key, "shop_name": name, "ok": False, "entry": None, "rows": 0, "error": "no_rows_parsed"}
    n = len(entry.get("prices") or entry.get("skus") or [])
    return {"key": key, "shop_name": name, "ok": True, "entry": entry, "rows": n, "error": None}
