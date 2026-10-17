"""Apple 公式（iPhone）の新商品の発見（Phase 27）。読むだけ・候補を作るだけ（正本に登録しない）。

1. 購入の一覧ページ（/jp/shop/buy-iphone）から、販売中の機種のページ（/jp/shop/buy-iphone/<slug>）を見つける
2. 機種のページの商品データ（"sku"・"partNumber"・"price":{"fullPrice"}・"name"）から、部品番号ごとの
   機種・容量・色・価格を読む（名前の「iPhone」という語だけでは判断しない。部品番号と容量が要る）
3. 正本の iPhone（config/products.yaml。「機種 + 容量」で1商品・色はまとめる）と照合する
   - 同じ機種・容量が正本にある → MATCHED_EXISTING（新しい候補を作らない）
   - 正本に無い機種・容量 → PENDING_REVIEW の候補（部品番号・色・公式の価格・URL を証拠として残す）
   - 名前を読めない商品 → REVIEW_REQUIRED（部品番号で記録）

取得は src/collectors/polite.py の作法（robots.txt・同じドメインの間隔 120 秒・正直な User-Agent・リダイレクトを
たどらない・403 は止める）。1回の実行で読む機種のページは MAX_FAMILY_PAGES まで（新しく見つかった機種が先、
残りは確認が古い順）。同じページは1回の実行で1回だけ読む。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from src.discovery import store as st

SOURCE = "apple_jp_official"
LIST_URL = "https://www.apple.com/jp/shop/buy-iphone"
FAMILY_URL = "https://www.apple.com/jp/shop/buy-iphone/{slug}"
MAX_FAMILY_PAGES = 2
_SLUG = re.compile(r"/jp/shop/buy-iphone/(iphone-[a-z0-9-]{1,40})(?=[\"'?#/])")
_PRODUCT = re.compile(r'"sku"\s*:\s*"([A-Z0-9]{4,6})"\s*,\s*"partNumber"\s*:\s*"([A-Z0-9]{4,6}J/A)"\s*,\s*"price"\s*:\s*'
                      r'\{\s*"fullPrice"\s*:\s*([\d.]+)\s*\}\s*,\s*"category"\s*:\s*"(\w+)"\s*,\s*"name"\s*:\s*"([^"]{3,80})"')
_NAME = re.compile(r"^(iPhone(?:\s+[0-9A-Za-z]+){0,3}?)\s+(\d{1,4})\s*(GB|TB)(?:\s+(.+))?$")


def norm_line(line: str) -> str:
    """機種の名前を比べる形に（大文字小文字・空白）。世代（17 / 18）と種類（Pro / Pro Max / Air / e）は区別したまま。"""
    return re.sub(r"\s+", " ", str(line or "").replace(" ", " ")).strip().lower()


def parse_name(name: str) -> dict | None:
    """「iPhone 18 Pro 256GB Cosmic Orange」→ 機種・容量・色。読めなければ None（推測しない）。"""
    m = _NAME.match(re.sub(r"\s+", " ", str(name or "").replace(" ", " ")).strip())
    if not m:
        return None
    cap = f"{int(m.group(2))}{m.group(3).upper()}"
    return {"line": m.group(1), "line_key": norm_line(m.group(1)), "capacity": cap, "color": (m.group(4) or "").strip()}


def parse_products(html: str) -> list[dict]:
    """機種のページの商品データ（部品番号ごと）。iPhone の商品だけ。"""
    out, seen = [], set()
    for sku, part, price, cat, name in _PRODUCT.findall(html or ""):
        if cat != "iphone" or part in seen:
            continue
        seen.add(part)
        out.append({"sku": sku, "part_number": part, "price": int(float(price)), "name": name,
                    "parsed": parse_name(name)})
    return out


def family_slugs(html: str) -> list[str]:
    return sorted(set(_SLUG.findall(html or "")))


def canonical_iphones(products_yaml: Path) -> dict:
    """正本の iPhone の「機種 + 容量」→ product_id（config/products.yaml から読むだけ）。"""
    import yaml
    try:
        data = yaml.safe_load(Path(products_yaml).read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}
    items = data.get("products") if isinstance(data, dict) else data
    out = {}
    for p in items or []:
        if not isinstance(p, dict) or str(p.get("genre") or "") != "iphone":
            continue
        parsed = parse_name(re.sub(r"\s*(SIMフリー|SIM\s*free)\s*$", "", str(p.get("name") or ""), flags=re.I))
        if parsed:
            out[(parsed["line_key"], parsed["capacity"])] = str(p.get("id") or p.get("product_id") or "")
    return out


def candidate_id(line_key: str, capacity: str) -> str:
    return st.stable_id("apple", line_key, capacity)


def classify(products_by_slug: dict, canonical: dict, store: dict, *, now: datetime) -> dict:
    """読んだ商品データを台帳に入れる。候補の ID・照合・未登録の部品番号の件数を返す。"""
    seen, unknown_parts, matched, new = set(), 0, 0, 0
    seen_in: dict = {}                                   # 候補 → 今回その候補が載っていた機種のページ
    for slug, prods in products_by_slug.items():
        url = FAMILY_URL.format(slug=slug)
        groups: dict = {}
        for p in prods:
            q = p["parsed"]
            if q is None:
                # 名前を読めない（機種・容量が分からない）: 部品番号で記録して人が確認する（推測しない）
                cid = st.stable_id("apple-part", p["part_number"])
                fams_u = sorted(set((store["candidates"].get(cid) or {}).get("families") or []) | {slug})
                st.upsert(store, cid, {"source": SOURCE, "brand": "Apple", "genre": "iphone", "families": fams_u,
                                       "product_name": p["name"], "model_number": "", "sku": p["sku"],
                                       "part_numbers": [p["part_number"]], "capacity": "", "colors": [],
                                       "official_url": url, "official_price": p["price"],
                                       "match_to_existing": ""},
                          status=st.REVIEW_REQUIRED, now=now, reasons=["name_unparsed"])
                seen.add(cid)
                seen_in.setdefault(cid, set()).add(slug)
                unknown_parts += 1
                continue
            groups.setdefault((q["line_key"], q["capacity"]), []).append(p)
        for (line_key, cap), ps in groups.items():
            cid = candidate_id(line_key, cap)
            old = store["candidates"].get(cid) or {}
            if cid in seen:
                # 同じ実行で2つ目のページに出た: 部品番号・色・価格を合わせる（後のページで上書きしない。レビュー L-3）
                prev_parts, prev_colors = set(old.get("part_numbers") or []), set(old.get("colors") or [])
                prev_prices = set(old.get("official_prices") or [])
                prev_skus = {x for x in str(old.get("sku") or "").split(",") if x}
            else:
                prev_parts, prev_colors, prev_prices, prev_skus = set(), set(), set(), set()
            prices = sorted({p["price"] for p in ps} | prev_prices)
            pid = canonical.get((line_key, cap), "")
            fams = sorted(set(old.get("families") or []) | {slug})   # 複数の機種のページに出ても入れ替わらない（レビュー L-5）
            fields = {"source": SOURCE, "brand": "Apple", "genre": "iphone", "families": fams,
                      "product_name": f"{ps[0]['parsed']['line']} {cap}", "model_number": ps[0]["parsed"]["line"],
                      "sku": ",".join(sorted({p["sku"] for p in ps} | prev_skus)),
                      "part_numbers": sorted({p["part_number"] for p in ps} | prev_parts), "capacity": cap,
                      "colors": sorted({p["parsed"]["color"] for p in ps if p["parsed"]["color"]} | prev_colors),
                      "edition": "", "jan": "", "official_url": FAMILY_URL.format(slug=fams[0]),  # 読む順に依らない
                      "official_price": prices[0] if len(prices) == 1 else None,
                      "official_prices": prices, "match_to_existing": pid}
            reasons = [] if len(prices) == 1 else ["price_varies_by_color"]
            first_time = cid not in seen                      # 同じ実行で2ページに出ても1回だけ数える
            if pid:
                st.upsert(store, cid, fields, status=st.MATCHED_EXISTING, now=now, reasons=reasons)
                matched += first_time
            else:
                st.upsert(store, cid, fields, status=st.PENDING_REVIEW, now=now,
                          reasons=reasons + ["not_in_canonical"])
                new += first_time
                unknown_parts += len(ps) if first_time else 0
            seen.add(cid)
            seen_in.setdefault(cid, set()).add(slug)
    return {"seen": seen, "seen_in": seen_in, "unknown_parts": unknown_parts, "matched": matched,
            "new_or_pending": new}


def drop_missing_families(store: dict, checked: set, seen_in: dict, *, now: datetime) -> None:
    """今回読んだ機種のページに載っていなかった候補から、そのページを外す（レビュー M-1 の3回目）。

    載っているページが無くなった候補だけが、最後に見た日（last_seen_on）から数えて STALE になる（行き来しない・
    読むページの組み合わせに依らない）。人が決めた候補は変えない。
    """
    for cid, rec in store["candidates"].items():
        if rec.get("source") != SOURCE or rec.get("status") in st.HUMAN_DECIDED:
            continue
        fams = set(rec.get("families") or [])
        gone = {s for s in fams & checked if s not in seen_in.get(cid, set())}
        if gone:
            rec["families"] = sorted(fams - gone)
            rec["updated_at"] = now.isoformat(timespec="seconds")


def _fetch(url: str) -> tuple[str | None, str]:
    """robots.txt・間隔・正直な User-Agent・リダイレクトをたどらない（scripts/recheck_official.py と同じ作法）。"""
    import sys
    root = Path(__file__).resolve().parent.parent.parent
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))
    import recheck_official
    return recheck_official._fetch(url)


def pick_families(slugs: list[str], meta: dict, limit: int = MAX_FAMILY_PAGES, known_lines=()) -> list[str]:
    """今回読む機種のページ（まだ読もうとしていない機種が先・残りは読もうとしたのが古い順。上限まで）。

    まだ読もうとしていない機種の中では、正本に無い機種（新しい機種の可能性が高い）を先にする。
    読めなかった機種も「読もうとした日」を進める（読めない機種が毎回の枠を使い続けない）。
    """
    fam = meta.get("families") or {}
    known = {norm_line(x) for x in known_lines}
    unseen = sorted((s for s in slugs if not (fam.get(s) or {}).get("last_attempted_on")),
                    key=lambda s: (norm_line(s.replace("-", " ")) in known, s), reverse=False)
    unseen = [s for s in unseen if norm_line(s.replace("-", " ")) not in known][::-1] + \
        [s for s in unseen if norm_line(s.replace("-", " ")) in known]
    rest = sorted((s for s in slugs if s not in unseen), key=lambda s: (fam[s].get("last_attempted_on") or "", s))
    return (unseen + rest)[:limit]


UNPARSED_MAX_RATIO = 0.5                # 1ページで名前を読めない商品がこれより多ければ、ページの形が変わったとみなす


def run(out_dir: Path, products_yaml: Path, *, now: datetime, fetch=None, sleep=None) -> dict:
    """一覧と機種のページを読み、台帳（out_dir/product_candidates.json）を更新する。正本は変えない。

    取得元のブロック（403・robots など polite.CUTOFF_IMMEDIATE）を受けたら、この実行では残りの機種を読まない（監査 M-1）。
    実際の取得のときは、最初の取得の前に取得元の間隔の分を待つ（前の CI の手順が同じ取得元を読んだばかりかもしれない。
    間隔の記録はプロセスをまたがない。recheck_official と同じ。監査 L-1）。
    """
    from src.collectors.polite import CUTOFF_IMMEDIATE
    if fetch is None:
        import sys
        import time as _time
        root = Path(__file__).resolve().parent.parent.parent
        if str(root / "scripts") not in sys.path:
            sys.path.insert(0, str(root / "scripts"))
        import recheck_official
        (sleep or _time.sleep)(recheck_official._host_interval(LIST_URL))
    fetch = fetch or _fetch
    path = Path(out_dir) / st.PRODUCT_FILE
    store = st.load(path)
    meta = store.setdefault("apple", {"families": {}})
    report = {"source": SOURCE, "list_status": "", "families": [], "checked": [], "errors": {}, "unknown_parts": 0,
              "matched": 0, "pending": 0, "requests": 0, "cutoff": ""}
    html, why = fetch(LIST_URL)
    report["requests"] += 1
    if not html:
        report["list_status"] = why or "error"
        return report | {"store": store, "saved": False}
    report["list_status"] = "ok"
    slugs = family_slugs(html)
    report["families"] = slugs
    if not slugs:
        # 一覧の形が変わった（機種を1件も読めない）: 候補を STALE にしない（レビュー M-2）
        report["list_status"] = "no_families"
        st.save(path, store)
        return report | {"store": store, "saved": True}
    fam = meta.setdefault("families", {})
    for s in slugs:
        fam.setdefault(s, {"first_seen_on": now.strftime("%Y-%m-%d"), "last_checked_on": ""})
    for s in list(fam):
        if s not in slugs:
            fam[s]["listed"] = False
        else:
            fam[s]["listed"] = True
    by_slug = {}
    canonical = canonical_iphones(products_yaml)
    for s in pick_families(slugs, meta, known_lines=[k[0] for k in canonical]):
        fam[s]["last_attempted_on"] = now.strftime("%Y-%m-%d")
        h, why = fetch(FAMILY_URL.format(slug=s))
        report["requests"] += 1
        if not h:
            report["errors"][s] = why or "error"
            fam[s]["last_error"] = why or "error"
            if why in CUTOFF_IMMEDIATE:
                report["cutoff"] = why                       # ブロック: この実行では残りを読まない（回避しない）
                break
            continue
        fam[s]["last_error"] = ""
        prods = parse_products(h)
        unparsed = sum(1 for p in prods if p["parsed"] is None)
        if not prods or unparsed > len(prods) * UNPARSED_MAX_RATIO:
            # ページの形が変わった（読めない・名前の形が変わった）: 部品番号ごとの大量の候補を作らない（監査 L-2）
            report["errors"][s] = "no_product_data" if not prods else "name_format_changed"
            continue
        by_slug[s] = prods
        fam[s]["last_checked_on"] = now.strftime("%Y-%m-%d")
        report["checked"].append(s)
    res = classify(by_slug, canonical, store, now=now)
    checked = set(by_slug)
    drop_missing_families(store, checked, res["seen_in"], now=now)
    # 今回読めた機種の候補・一覧から消えた機種の候補だけを STALE の対象にする（読めなかった機種は変えない）
    st.age_out(store, res["seen"], now=now,
               # 載っている機種のページが無くなった（今回読んだページから外れた・一覧から消えた）候補だけ
               scope=lambda r: r.get("source") == SOURCE and not (set(r.get("families") or []) & set(slugs)))
    report.update(unknown_parts=res["unknown_parts"], matched=res["matched"], pending=res["new_or_pending"])
    st.save(path, store)
    return report | {"store": store, "saved": True}
