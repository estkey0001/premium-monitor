# -*- coding: utf-8 -*-
"""Apple Japan の「購入できるか」（isBuyable）を、部品番号ごとに取得する。

Apple の機種ページ自身が使う公開の購入可否 API（`/jp/shop/buyability-message`）を、polite 取得（robots.txt・間隔・
正直な User-Agent・リダイレクトをたどらない）で 1 回だけ読む。ログイン・カート操作・CAPTCHA は使わない。

- 返すのは「購入できる（True）」「購入できない（False）」「分からない（None）」だけ。在庫の数や納期は読まない。
- 分からない理由（取得失敗・形式の変化・部品番号が応答に無い）は None にして、購入可能にしない。
- 容量の購入可否は、その容量の全部品番号（色違い）が True のときだけ BUYABLE。1 つでも False なら UNAVAILABLE
  （色によって異なる＝全色を指定せずには買えない）。None が混じれば UNKNOWN。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

BUYABILITY_URL = "https://www.apple.com/jp/shop/buyability-message"
JST = timezone(timedelta(hours=9))
BUYABLE, UNAVAILABLE, UNKNOWN = "BUYABLE", "UNAVAILABLE", "UNKNOWN"


def build_url(parts: list[str]) -> str:
    q = "&".join(f"parts.{i}={quote(p, safe='')}&option.{i}={quote(p, safe='')}" for i, p in enumerate(parts))
    return f"{BUYABILITY_URL}?{q}"


def parse_buyability(body: Optional[str], parts: list[str]) -> dict:
    """応答の JSON から {部品番号: True/False/None}。形式が違う・部品番号が無いものは None（購入可能にしない）。"""
    out: dict = {p: None for p in parts}
    try:
        sth = json.loads(body or "")["body"]["content"]["buyabilityMessage"]["sth"]
    except (ValueError, KeyError, TypeError):
        return out
    if not isinstance(sth, dict):
        return out
    for p in parts:
        v = (sth.get(p) or {}).get("isBuyable") if isinstance(sth.get(p), dict) else None
        out[p] = v if isinstance(v, bool) else None
    return out


def sku_status(part_flags: list[Optional[bool]]) -> str:
    """容量（SKU）の状態。全色 True=BUYABLE／1 つでも False=UNAVAILABLE／None が混じる・空=UNKNOWN。"""
    if not part_flags or any(f is None for f in part_flags):
        return UNKNOWN
    if all(part_flags):
        return BUYABLE
    return UNAVAILABLE


def _default_fetch(url: str) -> tuple[Optional[str], str]:
    root = Path(__file__).resolve().parents[3]
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))
    import recheck_official
    return recheck_official._fetch(url)


def fetch_buyability(parts: list[str], *, fetch: Optional[Callable] = None, now: Optional[datetime] = None) -> dict:
    """{"parts": {部品番号: bool|None}, "checked_at": ISO, "source": URL, "error": 理由 or None}。取得失敗は全部 None。"""
    now = now or datetime.now(JST)
    url = build_url(parts)
    body, why = (fetch or _default_fetch)(url)
    flags = parse_buyability(body, parts)
    err = None if body else (why or "fetch_failed")
    if body and all(v is None for v in flags.values()):
        err = "unexpected_format"
    return {"parts": flags, "checked_at": now.isoformat(timespec="seconds"), "source": BUYABILITY_URL, "error": err}


def availability_by_sku(sku_parts: dict, result: dict) -> dict:
    """sku_parts: {"iPhone Duo 2TB": ["MK2A4J/A", ...]} → {sku: {status, parts, checked_at, source}}。"""
    out = {}
    for sku, parts in sku_parts.items():
        flags = {p: result["parts"].get(p) for p in parts}
        out[sku] = {"status": sku_status(list(flags.values())), "parts": flags,
                    "checked_at": result["checked_at"], "source": result["source"]}
        if result.get("error"):
            out[sku]["error"] = result["error"]
    return out


def apple_live(model: str = "iPhone Duo", slug: str = "iphone-duo", *, fetch_page: Optional[Callable] = None,
               fetch: Optional[Callable] = None, now: Optional[datetime] = None) -> dict:
    """Apple 機種ページ（構造化データの部品番号・価格）と購入可否を読む。

    {"model", "prices": {容量: 税込円}, "sku_parts": {"iPhone Duo 2TB": [部品番号...]}, "availability": {...},
     "checked_at", "errors": [...]}。容量ごとに色違いで価格が違う場合は、その容量の価格を採らない（errors に残す）。
    """
    from src.discovery import apple
    now = now or datetime.now(JST)
    errors: list = []
    html, why = (fetch_page or apple._fetch)(apple.FAMILY_URL.format(slug=slug))
    prices: dict = {}
    sku_parts: dict = {}
    bad_caps: set = set()            # 価格を 1 つに決められない容量（購入可否も BUY の根拠にしない）
    if not html:
        errors.append(f"apple_page_failed:{why}")
    else:
        by_cap: dict = {}
        for p in apple.parse_products(html):
            line = p["parsed"]["line"] if p.get("parsed") else ""
            cap = p["parsed"]["capacity"] if p.get("parsed") else ""
            if not cap or apple.norm_line(line) != apple.norm_line(model):
                continue
            by_cap.setdefault(cap, []).append(p)
        for cap, items in by_cap.items():
            ps = {i["price"] for i in items}
            sku_parts[f"{model} {cap}"] = sorted({i["part_number"] for i in items})
            if len(ps) == 1:
                prices[cap] = ps.pop()
            else:
                errors.append(f"price_differs_by_color:{cap}")
                bad_caps.add(f"{model} {cap}")
    avail = {}
    if sku_parts:
        parts = sorted({p for v in sku_parts.values() for p in v})
        res = fetch_buyability(parts, fetch=fetch, now=now)
        avail = availability_by_sku(sku_parts, res)
        for sku in bad_caps:
            avail[sku] = dict(avail[sku], status=UNKNOWN, error="price_differs_by_color")
        if res.get("error"):
            errors.append(f"buyability:{res['error']}")
    return {"model": model, "prices": prices, "sku_parts": sku_parts, "availability": avail, "bad_skus": sorted(bad_caps),
            "checked_at": now.isoformat(timespec="seconds"), "errors": errors}


def merge_live(doc: dict, live: dict) -> None:
    """research_iphone.json の内容（doc）へ、Apple の価格と購入可否を反映する（その場で書き換える）。"""
    ao = doc.setdefault("apple_official", {})
    pj = ao.setdefault("prices_jpy", {}).setdefault(live["model"], {})
    pj.update(live["prices"])
    for sku in live["bad_skus"]:
        pj.pop(sku.split()[-1], None)      # 価格を決められない容量は、古い価格を残さない（比較から外す）
    ao["availability"] = {**(ao.get("availability") or {}), **live["availability"]}
    if not live["errors"]:                 # 全容量を取れたときだけ、機種ごとの確認日を更新する（ファイル全体の確認日は変えない）
        ao.setdefault("checked_at_by_model", {})[live["model"]] = live["checked_at"][:10]


def main(argv=None) -> int:
    """`python -m src.collectors.official.apple_buyability --dir <調査フォルダ> [--apply]`。既定は書かない。"""
    import argparse
    ap = argparse.ArgumentParser(description="Apple Japan の価格と購入可否を読み、research_iphone.json に反映する（既定は dry-run）")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    live = apple_live()
    print(json.dumps({"prices": live["prices"], "availability": {k: v["status"] for k, v in live["availability"].items()},
                      "errors": live["errors"]}, ensure_ascii=False))
    f = Path(a.dir) / "research_iphone.json"
    if a.apply and f.exists() and live["prices"]:
        d = json.loads(f.read_text(encoding="utf-8"))
        merge_live(d, live)
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if not live["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
