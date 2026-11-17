# -*- coding: utf-8 -*-
"""カメラの週次の更新を 1 コマンドで行う（せどり判断ページ・利益ルート A〜D）。

    python -m src.research.camera_refresh            # dry-run（何も書かない。内容を表示するだけ）
    python -m src.research.camera_refresh --apply    # 検証に通ったときだけ書く

入力: 調査フォルダ（.private/research/weekly/<日付>/）の research_camera_*.json（Skill premium-market-research の camera を
ブランドごとに分担して実行した結果。AI の調査は DISCOVERED まで）と、既存の自動収集（exports/normalized_price_observations）の
買取の商品ページの価格。計算は camera_routes（A〜D・手数料・同一性・状態・鮮度）。24 時間の監視ではなく週 1 回の手動実行。

守ること:
- 取得は調査員が polite に行う。この実行では通信しない。
- **読めた行だけ**を今日の確認にする。失敗した取得元の古い価格は、日付もそのまま残る（鮮度で STALE になる）。
- 未確認の新商品の名前は公開しない（`.private/.../camera_candidates.json` に残し、公開は件数だけ）。
- 通知は dry-run の記録だけ（外部送信は 0）。
- 品質の数（同一性・状態・売値の種別・成約の件数・鮮度・日付・手数料）が 1 つでも 0 でなければ --apply は書かない。
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.research import camera_routes as cr

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEEKLY_ROOT = PROJECT_ROOT / ".private" / "research" / "weekly"
EXPORT_DIR = PROJECT_ROOT / "exports" / "camera_research"
MARKET_FILE = "camera_market.json"
HISTORY_FILE = "camera_market_history.json"
CONFIG_PATH = PROJECT_ROOT / "config" / "camera_routes.yaml"
OBS_PATH = PROJECT_ROOT / "exports" / "normalized_price_observations" / "latest.json"
KEEP_SNAPSHOTS = 26
CARRY_MAX_DAYS = 30
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_COND = {"new_unopened": cr.UNOPENED, "used_s": cr.LIKE_NEW, "used_a": cr.USED}


# ---------- 入力 ----------
def load_config() -> dict:
    import yaml
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def registered_cameras() -> dict:
    """products.yaml の camera の {名前: id}。登録済みかどうかはここで決める（調査員の申告は信用しない）。"""
    import yaml
    d = yaml.safe_load((PROJECT_ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))
    return {p["name"]: p["id"] for p in d.get("products", []) if p.get("genre") == "camera"}


def previous_dir(root: Path, date: str) -> Optional[Path]:
    c = sorted(d for d in root.iterdir() if d.is_dir() and _DATE.fullmatch(d.name) and d.name <= date
               and list(d.glob("research_camera_*.json"))) if root.exists() else []
    return c[-1] if c else None


def load_research(d: Path) -> tuple[list, list, list, list]:
    """(機種レコード, 取得元の結果, 発見した未登録の商品, 抽選) をブランドのファイルから集める。"""
    recs, srcs, disc, lots = [], [], [], []
    for f in sorted(d.glob("research_camera_*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for p in doc.get("products") or []:
            if isinstance(p, dict) and p.get("product"):
                recs.append({**p, "brand": doc.get("brand")})
        srcs += [{**s, "brand": doc.get("brand")} for s in doc.get("source_results") or [] if isinstance(s, dict)]
        disc += [{**x, "brand": doc.get("brand")} for x in doc.get("discovered") or [] if isinstance(x, dict)]
        lots += [{**x, "brand": doc.get("brand")} for x in doc.get("lotteries") or [] if isinstance(x, dict)]
    return recs, srcs, disc, lots


def _row_ok(r: dict) -> bool:
    """読めた行だけ（BLOCKED / FAILED / NOT_LISTED は、取得できなかった記録であって価格ではない）。"""
    return str(r.get("result") or "FOUND").upper() == "FOUND" and isinstance(r.get("price_jpy"), int)


def _is_price(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _to_price(v):
    """価格の数値化。「280,000」「¥280,000」「280000円」は整数にする。それ以外（範囲・「約」・文字）は None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    t = cr._nfkc(v).replace(",", "").replace("¥", "").replace("円", "").strip()
    return int(t) if re.fullmatch(r"\d{4,9}", t) else None


def clean_records(recs: list) -> list:
    """読めた行（result が FOUND か無し・価格が正の整数）だけ残す。公式の行にも同じ検査をする。入力の carried は受け付けない。"""
    out = []
    for p in copy.deepcopy(recs):
        for k in ("retail", "buyback", "listing", "sold"):
            rows = []
            for r in p.get(k) or []:
                if isinstance(r, dict) and str(r.get("result") or "FOUND").upper() == "FOUND":
                    pr = _to_price(r.get("price_jpy"))
                    if _is_price(pr):
                        rows.append({**r, "price_jpy": pr})
            for r in rows:
                r.pop("carried", None)
                r.pop("from_pipeline", None)
            p[k] = rows
        off = p.get("official")
        if isinstance(off, dict) and (str(off.get("result") or "FOUND").upper() != "FOUND"):
            p["official"] = None
        elif isinstance(off, dict) and off.get("price_jpy") is not None:
            off["price_jpy"] = _to_price(off.get("price_jpy"))
        out.append(p)
    return out


def existing_buyback_rows(obs_doc: dict, names: dict) -> dict:
    """自動収集（CI）の買取のうち、商品ページ（item）・当日分・拒否されていない行。{商品名: [行]}。
    古い手入力の価格・店のトップ・検索結果の行は使わない。"""
    by_id = {v: k for k, v in names.items()}
    out: dict = {}
    for o in obs_doc.get("observations", []):
        if (o.get("price_type") != "buyback_price" or o.get("link_type") != "item" or not o.get("item_url")
                or not o.get("is_fresh") or o.get("rejection_reason") or o.get("product_id") not in by_id
                or not o.get("is_exact_product_match") or o.get("product_match_reason") != "strict_model_match"
                or o.get("wrong_model_flag") or o.get("accessory_flag") or not o.get("is_body_only")):
            continue
        out.setdefault(by_id[o["product_id"]], []).append({
            "shop": o.get("source_name"), "item_title": o.get("extracted_title") or None, "price_jpy": o.get("price"),
            "condition": _COND.get(o.get("condition"), cr.UNKNOWN), "url": o["item_url"], "is_product_page": True,
            "checked_at": str(o.get("observed_at") or "")[:10], "source_updated_at": None, "result": "FOUND", "from_pipeline": True,
            "identity_basis": o.get("product_match_reason")})
    return out


def merge_pipeline(recs: list, extra: dict, names: dict) -> tuple[list, int]:
    """自動収集の買取の商品ページ行を、**調査員が同じ URL で商品名（版・色）を読んだ行の裏付け**にだけ使う。
    自動収集の行は商品名が汎用（「買取価格」）で版・色を区別できないので、単独では売値にしない。
    同じ URL の研究の行は、収集が商品ページと確認したので is_product_page=True にする。戻り値: (レコード, 使わなかった行数)。"""
    recs = copy.deepcopy(recs)
    have = {cr.name_key(r["product"]): r for r in recs}
    unused = 0
    for name, rows in extra.items():
        rec = have.get(cr.name_key(name))
        by_url = {x.get("url"): x for x in (rec.get("buyback") or [])} if rec else {}
        for r in rows:
            hit = by_url.get(r["url"])
            if hit is not None and hit.get("price_jpy") != r.get("price_jpy"):
                rec["buyback"] = [x for x in rec["buyback"] if x is not hit]       # 調査の価格と収集の価格が食い違う行（一覧表の列の読み違いなど）は採用しない
                by_url.pop(r["url"], None)
                unused += 1
                continue
            if hit is None and rec:
                # URL が違っても、同じ店・同じ状態区分・同じ価格の研究の行（一覧表で商品名を読んだ行）は、収集が商品ページで確認した行と同じとみなす
                same = [x for x in (rec.get("buyback") or []) if cr._shop_key(x.get("shop")) == cr._shop_key(r.get("shop"))
                        and x.get("price_jpy") == r.get("price_jpy") and cr.compatible(cr.condition_of(x.get("condition")), r.get("condition"))]
                hit = same[0] if len(same) == 1 else None
                if hit is not None:
                    hit["url"] = r["url"]
            if hit is not None:
                hit["is_product_page"] = True
                hit["confirmed_by_collector"] = True
            else:
                unused += 1
    return recs, unused


def attach_ids(recs: list, names: dict) -> list:
    """登録名と一致する機種は、登録名・id に揃える（同じ機種の別表記は 1 つにまとめる）。"""
    keyed = {cr.name_key(n): n for n in names}
    merged: dict = {}
    for r in recs:
        reg = keyed.get(cr.name_key(r["product"]))
        if reg:
            r["product"], r["product_id"] = reg, names[reg]
        k = cr.name_key(r["product"])
        if k in merged:
            m = merged[k]
            for kind in ("retail", "buyback", "listing", "sold"):
                have = {(x.get("url"), x.get("item_title"), x.get("shop") or x.get("market")) for x in m.get(kind) or []}
                m[kind] = list(m.get(kind) or []) + [x for x in r.get(kind) or [] if (x.get("url"), x.get("item_title"), x.get("shop") or x.get("market")) not in have]
            m["official"] = m.get("official") or r.get("official")
        else:
            merged[k] = r
    return list(merged.values())


# ---------- 失敗した取得元の古い価格を引き継ぐ ----------
def _row_of(o: dict) -> dict:
    return {"shop": o["source"], "market": o["source"], "item_title": o.get("item_title"), "price_jpy": o["price"],
            "condition": o["condition"], "url": o.get("url"), "checked_at": o.get("checked_at"),
            "source_updated_at": o.get("source_updated_at"), "is_product_page": True, "stock": "UNKNOWN",
            "purchasable_now": None, "shipping_jpy": o.get("shipping_jpy"),
            "shipping_url": o.get("shipping_url"), "result": "FOUND", "carried": True, "sold_at": o.get("sold_at")}


_LOT_SHOP = ("じゃんぱら", "セカンドストリート", "RICOH", "リコー", "GR SPACE", "FUJIFILM", "富士フイルム", "ソニー", "SONY", "キヤノン", "CANON", "ニコン", "NIKON",
             "ヨドバシ", "ビック", "マップカメラ", "フジヤ", "キタムラ", "ソフマップ")


_KW_CACHE: dict = {}


def _keywords_of(product: str) -> list:
    """登録機種の別名（products.yaml の keywords。例: GR4・GRIV）。"""
    if not _KW_CACHE:
        import yaml
        d = yaml.safe_load((PROJECT_ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))
        for p in d.get("products", []):
            if p.get("genre") == "camera":
                _KW_CACHE[cr.name_key(p["name"])] = [str(k) for k in p.get("keywords") or []]
    return _KW_CACHE.get(cr.name_key(product), [])


def _lottery_covers(product: str, text: str) -> bool:
    """抽選の商品名（「GR IV / GR IV HDF（…）」のように複数を並べた記載・別名「GR4」を含む）が、この機種（版を含む）を対象にしているか。
    抽選名の「現状」などの語はジャンク扱いにしない（抽選を見落とさない側に倒す）。"""
    t = str(text or "")
    segs = [x for x in re.split(r"[/・、,／＋+]|\s+と\s+|（|）|\(|\)", t) if x.strip()] + [t]
    for seg in segs:
        if cr.identity_ok(product, seg, allow_junk=True)[0] or cr.identity_ok(product, "RICOH " + seg, allow_junk=True)[0]:
            return True
        up = cr._up(seg)
        for kw in _keywords_of(product):
            k = cr._up(kw)
            if k and re.search(r"(?<![A-Z0-9])" + re.escape(k) + r"(?![A-Z0-9])", up) and cr.variant_flags(seg) == cr.variant_flags(product):
                return True
    return False


def apply_lotteries(recs: list, lots: list, now: datetime) -> list:
    """同じ機種（版を含む）の応募期間内の抽選が、調査の lotteries にあれば、**同じブランドの公式の行**と、販売元（店名・ドメイン）が
    一致する販売店の行を LOTTERY_DEPENDENT にする。行の在庫が AVAILABLE と書かれていても、抽選が必要な機種を購入可能として扱わない。
    応募の終わりが過ぎた抽選は対象にしない。"""
    recs = copy.deepcopy(recs)
    for lot in lots:
        end = cr._d(lot.get("application_end"))
        if end is not None and end.date() < now.date():
            continue
        who = (str(lot.get("retailer") or "")).upper()
        lot_dom = cr.domain_of(lot.get("official_url"))
        for r in recs:
            if not _lottery_covers(r["product"], lot.get("product")):
                continue
            same_brand = str(lot.get("brand") or "").upper() == str(r.get("brand") or "").upper() and bool(r.get("brand"))
            if r.get("official") and (same_brand or not lot.get("brand")):
                r["official"]["lottery"] = True
            for x in r.get("retail") or []:
                shop = str(x.get("shop") or "").upper()
                if (any(k.upper() in who and k.upper() in shop for k in _LOT_SHOP) or not x.get("shop")
                        or (lot_dom and cr.domain_of(x.get("url")) == lot_dom)):
                    x["lottery"] = True
    return recs


def canon_shop(name) -> str:
    t = str(name or "")
    for kw, canon in _SHOPS:
        if kw in t:
            return canon
    for kw, canon in _SHOP_EN:
        if kw in t.lower():
            return canon
    return t


def _shops_in(text: str) -> set:
    """取得元名に含まれる店（正規名）の集合。"""
    out = {canon for kw, canon in _SHOPS if kw in text}
    out |= {canon for kw, canon in _SHOP_EN if kw in text.lower()}
    return out


def _hint(text) -> str:
    m = re.search(r"[（(]([^）)]+)[）)]", str(text or ""))
    return cr._up(m.group(1)) if m else ""


def _roles_of(text: str) -> tuple:
    has_bb = "買取" in text
    has_rt = any(w in text for w in ("販売", "新品", "中古", "公式", "ストア", "モール", "抽選"))
    return ("buyback", "retail") if (has_bb and has_rt) else (("buyback",) if has_bb else (("retail",) if has_rt else ("buyback", "retail")))


def drop_failed_source_rows(recs: list, srcs: list) -> tuple[list, list]:
    """取得元が「読めなかった」（FOUND 系以外の結果）と報告している (ブランド, 店, 役割) の行は、行が FOUND と書かれていても今日の確認にしない
    （落とした後、前回の行があれば carry_over が日付そのままで引き継ぐ）。まとめた記載（複数の店）は対象にしない。
    取得元名の括弧書きが特定の機種（例: 「ネットオフ買取（HDF）」）を指すときは、その機種の行だけを落とす（他の機種の読めた行は落とさない）。"""
    recs = copy.deepcopy(recs)
    bad_by_rec: dict = {}                                    # id(rec) -> {(shop, role)}
    off_names: dict = {}                                     # id(rec) -> [正規化した取得元名]
    for x in srcs:
        if x.get("result") not in _BAD:
            continue
        text = str(x.get("source") or "")
        shops = _shops_in(text)
        if len(shops) != 1:
            continue                                         # まとめた記載・店名が分からない記載は、行の除外に使わない
        shop = next(iter(shops))
        hint = _hint(text)
        for r in recs:
            if x.get("brand") != r.get("brand"):
                continue
            if hint and any(hint in cr._up(q["product"]) for q in recs if q.get("brand") == r.get("brand")) and hint not in cr._up(r["product"]):
                continue                                     # 括弧書きが別の機種を指している
            for role in _roles_of(text):
                bad_by_rec.setdefault(id(r), set()).add((shop, role))
            off_names.setdefault(id(r), []).append(cr._norm(text))
    dropped = []
    for r in recs:
        bad = bad_by_rec.get(id(r), set())
        for kind, role in (("retail", "retail"), ("listing", "retail"), ("buyback", "buyback"), ("sold", "retail")):
            keep = []
            for x in r.get(kind) or []:
                if (canon_shop(x.get("shop") or x.get("market")), role) in bad:
                    dropped.append({"product": r["product"], "kind": kind, "source": x.get("shop") or x.get("market")})
                else:
                    keep.append(x)
            r[kind] = keep
        off = r.get("official")
        if isinstance(off, dict) and any(n and (n in cr._norm(off.get("shop")) or cr._norm(off.get("shop")) in n) for n in off_names.get(id(r), [])):
            dropped.append({"product": r["product"], "kind": "official", "source": off.get("shop")})
            r["official"] = None
    return recs, dropped


def carry_over(recs: list, old_market: Optional[dict], now: datetime) -> tuple[list, list]:
    """今回その (機種・種類・店) の価格が 1 つも取れなかったときだけ、前回の行をそのまま（日付もそのまま）残す。
    CARRY_MAX_DAYS を超えた行は捨てる。戻り値: (レコード, 引き継いだ行の一覧)。"""
    if not old_market:
        return recs, []
    recs = copy.deepcopy(recs)
    have = {cr.name_key(r["product"]): r for r in recs}
    carried = []
    for p in old_market.get("products", []):
        rec = have.get(cr.name_key(p["product"]))
        for o in p.get("observations", []):
            if o["kind"] in ("official",) or not o.get("price") or o.get("reasons"):
                continue
            chk = cr._d(o.get("checked_at"))
            if chk is None or (now - chk).days > CARRY_MAX_DAYS:
                continue
            if rec is None:
                rec = {"product": p["product"], "product_id": p.get("product_id"), "brand": p.get("brand"), "registered": p.get("registered"),
                       "identity_note": p.get("identity_note"), "retail": [], "buyback": [], "listing": [], "sold": [], "official": None}
                recs.append(rec)
                have[cr.name_key(p["product"])] = rec
            k = o["kind"]
            # 今回その (機種・種類・店) の行が 1 つでもあれば引き継がない。店は URL・ドメイン・店名のどれかが同じなら同じ店
            same = [r for r in rec.get(k) or [] if (o.get("url") and r.get("url") == o.get("url"))
                    or (cr.domain_of(r.get("url")) and cr.domain_of(r.get("url")) == cr.domain_of(o.get("url")))
                    or cr._norm(r.get("shop") or r.get("market")) == cr._norm(o["source"])]
            if same:
                continue
            rec.setdefault(k, []).append(_row_of(o))
            carried.append({"product": p["product"], "kind": k, "source": o["source"], "checked_at": o.get("checked_at")})
    return recs, carried


# ---------- 本体 ----------
def refresh(src_dir: Path, date: str, *, now: datetime, old_market: Optional[dict] = None, cfg: Optional[dict] = None,
            obs_doc: Optional[dict] = None, names: Optional[dict] = None, official_shipping_fn=None, fixed_cost_fn=None) -> dict:
    cfg = cfg or load_config()
    names = names if names is not None else registered_cameras()
    recs_raw, srcs, disc, lots = load_research(src_dir)
    recs, dropped_rows = drop_failed_source_rows(clean_records(recs_raw), srcs)
    if obs_doc is None:
        try:
            obs_doc = json.loads(OBS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            obs_doc = {}
    recs = apply_lotteries(recs, lots, now)
    recs, pipeline_unused = merge_pipeline(recs, existing_buyback_rows(obs_doc, names), names)
    recs, carried = carry_over(recs, old_market, now)
    recs = attach_ids(recs, names)
    if official_shipping_fn is None:
        from src.market import official_shipping
        official_shipping_fn = official_shipping.purchase_shipping
    if fixed_cost_fn is None:
        from src.market import profit_formula
        fixed_cost_fn = profit_formula.fixed_costs
    market = cr.build_market(recs, now, cfg, registered_names=set(names), official_shipping_fn=official_shipping_fn,
                             fixed_cost_fn=fixed_cost_fn)
    quality = cr.quality_checks(market, now, date, cfg, fixed_cost=int(fixed_cost_fn()))
    events = cr.diff_events(old_market, market)
    report = _report(market, srcs, disc, lots, carried, old_market, events)
    return {"market": market, "quality": quality, "events": events, "report": report, "sources": srcs, "discovered": disc,
            "lotteries": lots, "carried": carried, "date": date, "now": now,
            "pipeline_rows_unused": pipeline_unused, "dropped_rows": dropped_rows, "old_market": old_market}


def _prices(market: dict, kind: str) -> dict:
    return {cr.obs_key(p["product"], o): o["price"]
            for p in market["products"] for o in p["observations"] if o["kind"] == kind and o.get("price") and not o["reasons"]}


def _changed(new: dict, old: Optional[dict], kinds) -> int:
    n = 0
    for k in kinds:
        a, b = _prices(new, k), (_prices(old, k) if old else {})
        n += sum(1 for key, v in a.items() if key in b and b[key] != v)
    return n


_SHOP_EN = (("yodobashi", "ヨドバシ"), ("biccamera", "ビックカメラ"), ("bic camera", "ビックカメラ"), ("map camera", "マップカメラ"), ("mapcamera", "マップカメラ"),
            ("fujiya", "フジヤカメラ"), ("kitamura", "カメラのキタムラ"), ("sofmap", "ソフマップ"), ("netoff", "ネットオフ"), ("janpara", "ジャンパラ"))
_SHOPS = (("メルカリ", "メルカリ"), ("ラクマ", "ラクマ"), ("ヤフオク", "ヤフオク"), ("Yahoo", "Yahoo"), ("ヨドバシ", "ヨドバシ"), ("ビック", "ビックカメラ"), ("マップカメラ", "マップカメラ"), ("フジヤ", "フジヤカメラ"),
          ("キタムラ", "カメラのキタムラ"), ("ソフマップ", "ソフマップ"), ("ネットオフ", "ネットオフ"), ("買取商店", "買取商店"),
          ("ケーズ", "ケーズデンキ"), ("アムール", "ビックカメラ"), ("みんなのカメラ", "みんなのカメラ"), ("ソニーストア", "ソニーストア"),
          ("キヤノン", "キヤノン公式"), ("ニコン", "ニコン公式"), ("リコー", "リコー公式"), ("富士フイルム", "富士フイルム公式"))
_OK_RESULTS = ("FOUND", "NO_EVENT_FOUND", "CONFIRMED_NO_CURRENT_EVENT", "NOT_LISTED")


class _Bad:
    """成功の許可リスト（FOUND など）以外の結果（BLOCKED / FAILED / ERROR / TIMEOUT / PARTIAL / SKIPPED …）はすべて失敗として扱う。"""
    def __contains__(self, v):
        return str(v or "").upper() not in _OK_RESULTS


_BAD = _Bad()
_OFFICIAL_SHOPS = frozenset({"ソニーストア", "キヤノン公式", "ニコン公式", "リコー公式", "富士フイルム公式"})


def source_matrix(srcs: list) -> dict:
    """取得元の結果を (ブランド, 店, 役割) ごとに 1 つにする。名前の揺れ（ヨドバシ / ヨドバシ.com）は店に正規化し、
    「ヨドバシ・ビック・…」のようにまとめた記載は、含まれる店のすべての失敗として扱う（読めたことにしない）。
    同じ (ブランド, 店, 役割) で結果が食い違うときは悪い側（BLOCKED / FAILED）を採る。"""
    out: dict = {}
    for s in srcs:
        text = str(s.get("source") or "")
        res = str(s.get("result") or "").upper()
        shops = []
        for kw, canon in _SHOPS:
            if kw in text and canon not in shops:
                shops.append(canon)
        for kw, canon in _SHOP_EN:
            if kw in text.lower() and canon not in shops:
                shops.append(canon)
        if not shops:
            shops = [text if text in _PUBLIC_SHOPS else "その他"]       # 名前に自由記述・URL・価格が混ざる取得元は「その他」にまとめる
        has_bb = "買取" in text
        has_rt = any(w in text for w in ("販売", "新品", "中古", "公式", "ストア", "モール", "抽選"))
        roles = ("buyback", "retail") if (has_bb and has_rt) else (("buyback",) if has_bb else (("retail",) if has_rt else ("buyback", "retail")))
        for shop in shops:
            for role in (("retail",) if shop in _OFFICIAL_SHOPS else roles):
                k = (s.get("brand"), shop, role)
                prev = out.get(k)
                if prev is None or (res in _BAD and prev["result"] not in _BAD):
                    out[k] = {"brand": s.get("brand"), "shop": shop, "role": role, "result": res, "reason": s.get("reason"),
                              "lump": len(shops) > 1}
    return out


def _report(market, srcs, disc, lots, carried, old_market, events) -> dict:
    allobs = [o for p in market["products"] for o in p["observations"]]
    good = lambda k: [o for o in allobs if o["kind"] == k and o.get("price") and not o["reasons"] and not o.get("carried")]
    routes = market["routes"]
    calc = [r for r in routes if r["profit_status"] != cr.NOT_CALCULATED]
    mx = source_matrix(srcs)
    shops_ok = sorted({v["shop"] for v in mx.values() if v["result"] not in _BAD})
    shops_failed = {}
    for v in mx.values():
        if v["result"] in _BAD:
            shops_failed.setdefault(v["shop"], []).append(f"{_public_brand(v['brand'])}/{v['role']}: {reason_code(v['reason'])}")
    sec_n = sum(len(p["secondary"]["listing"]) for p in market["products"])
    return {
        "sources_attempted": sorted({v["shop"] for v in mx.values()}), "sources_succeeded": shops_ok,
        "sources_failed": {k: " | ".join(v)[:300] for k, v in sorted(shops_failed.items())},
        "products_checked": len(market["products"]), "products_discovered": len(disc),
        "buy_prices_changed": _changed(market, old_market, ("official", "retail")),
        "buyback_prices_changed": _changed(market, old_market, ("buyback",)),
        "secondary_prices_changed": _changed(market, old_market, ("listing",)),
        "sold_updated": sum(1 for p in market["products"] for s in p["secondary"]["sold"].values() if s["eligible"]),
        "profit_routes_changed": sum(1 for e in events if e["type"] in ("LOSS_TO_PROFIT", "PROFIT_TO_LOSS", "WAIT_TO_BUY", "BUY_TO_WAIT", "BEST_ROUTE_CHANGE")),
        "new_profitable_routes": sum(1 for e in events if e["type"] == "LOSS_TO_PROFIT"),
        "routes_lost": sum(1 for e in events if e["type"] == "PROFIT_TO_LOSS"),
        "found": {"official_or_retail_prices": len(good("official")) + len(good("retail")), "buyback": len(good("buyback")),
                  "listing": len(good("listing")), "listing_groups": sec_n, "sold": len(good("sold"))},
        "routes": {"total": len(routes), "confirmed": len(calc), "unknown": len(routes) - len(calc),
                   "profitable": sum(1 for r in calc if r["profit_status"] == cr.PROFITABLE),
                   "buy": sum(1 for r in calc if r["decision"] == cr.BUY)},
        "carried_rows": carried,
    }


_PRIVATE = re.compile(r"/Users/|/home/[a-z]|\.private|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-z]{2,}")


def validate(state: dict) -> list:
    problems = [f"品質: {k}={v}" for k, v in state["quality"].items() if v]
    if _PRIVATE.search(json.dumps(_public_market(state), ensure_ascii=False)) or _PRIVATE.search(json.dumps(history_snapshot(state), ensure_ascii=False)):
        problems.append("公開データに絶対パス・メールアドレス・非公開フォルダの名前が含まれる")
    fresh = [o for p in state["market"]["products"] for o in p["observations"]
             if o.get("price") and not o["reasons"] and not o.get("carried") and o.get("freshness") == cr.FRESH]
    if not fresh:
        problems.append("今回新しく確認できた（7 日以内の）価格が 1 つも無い（古い行・引き継いだ行だけを書かない）")
    prev = (state.get("old_market") or {}).get("research_date")
    if prev and str(prev) > str(state["date"]):
        problems.append(f"公開済みの調査日（{prev}）より古い調査（{state['date']}）で上書きしない")
    for p in state["market"]["products"]:
        for r in p["routes"]:
            if r["decision"] == cr.BUY and r["profit_status"] != cr.PROFITABLE:
                problems.append(f"{p['product']} {r['route_type']}: 黒字でないのに BUY")
    return problems


# ---------- 出力 ----------
_PUBLIC_SHOPS = {canon for _, canon in _SHOPS} | {"みんなのカメラ", "買取商店", "ネットオフ"}


def _public_shop(name) -> str:
    """公開する取得元名は、正規の店名だけ（自由記述・URL・価格を含む名前は「その他」）。"""
    return name if name in _PUBLIC_SHOPS else "その他"


def _lottery_name(product, market: dict) -> str:
    """公開する抽選の商品名は、登録済みの機種名に照合できたものだけ（未登録・未発表の名前は出さない）。"""
    names = [p["product"] for p in market["products"] if p.get("registered")]
    hit = [n for n in names if _lottery_covers(n, product)]
    return " / ".join(hit)


_REASON_CODES = ((r"(?<![\d,])403(?![\d,])", "アクセスを拒否された（403）"), (r"(?<![\d,])503(?![\d,])", "一時的に利用できない（503）"), ("タイムアウト", "タイムアウト"),
                 ("本文が空", "本文を読めなかった"), ("読み取れ", "本文を読めなかった"), ("取得できな", "取得できなかった"),
                 ("JS", "本文を読めなかった"), ("未調査", "未取得"), ("未取得", "未取得"), ("特定でき", "未取得"), ("取得せず", "未取得"))


def reason_code(text) -> str:
    """読めなかった理由は、自由記述をそのまま公開せず、定型の文にする（パス・メール・要約の価格が混ざらない）。"""
    t = str(text or "")
    for k, v in _REASON_CODES:
        if re.search(k, t):
            return v
    return "読めなかった" if t else ""


_PUBLIC_OBS_KEYS = ("kind", "price_type", "price", "condition", "source", "item_title", "url", "checked_at", "source_updated_at",
                    "freshness", "age_days", "identity_ok", "reasons", "carried", "color", "stock", "shipping_jpy", "shop_key")
_DOMAIN_LABEL = {"kaitorishouten-co.jp": "買取商店", "netoff.co.jp": "ネットオフ", "fujiya-camera.co.jp": "フジヤカメラ", "mapcamera.com": "マップカメラ",
                 "kitamura.jp": "カメラのキタムラ", "kitamura.co.jp": "カメラのキタムラ", "sofmap.com": "ソフマップ", "janpara.co.jp": "じゃんぱら",
                 "2ndstreet.jp": "セカンドストリート", "yodobashi.com": "ヨドバシ", "biccamera.com": "ビックカメラ",
                 "ricohimagingstore.com": "リコーイメージングストア", "ricoh-imaging.co.jp": "リコーイメージング", "mall-jp.fujifilm.com": "富士フイルムモール",
                 "fujifilm.com": "富士フイルム", "fujifilm-x.com": "富士フイルム", "sony.jp": "ソニーストア", "sony.com": "ソニー", "personal.canon.jp": "キヤノンオンラインショップ",
                 "canon.jp": "キヤノン", "nikon-image.com": "ニコン", "nikon.com": "ニコン", "nij.nikon.com": "ニコン"}
_KNOWN_BRANDS = {"RICOH", "FUJIFILM", "SONY", "CANON", "NIKON"}


def _public_brand(b) -> str:
    return str(b) if str(b or "").upper() in _KNOWN_BRANDS else "その他"


def _label_of(url, fallback) -> str:
    """公開する取得元名。URL のドメインから決める（自由記述の店名を出さない）。分からなければ正規の店名だけ、無ければ「その他」。"""
    return _DOMAIN_LABEL.get(cr.domain_of(url)) or (fallback if fallback in _PUBLIC_SHOPS or fallback in _MARKET_LABELS else "その他")


_MARKET_LABELS = set(cr._MARKET_LABEL.values()) | {"不明な市場"}


def _pub_view(v: Optional[dict], product: str) -> Optional[dict]:
    if not v:
        return v
    out = _pub_scrub(v)
    out["source"] = _label_of(v.get("url"), v.get("source"))
    if "item_title" in out:
        out["item_title"] = product                       # 同一性を確認済みの行だけなので、公開する商品名は登録名にする（店の自由記述を出さない）
    return out


def _public_product(p: dict) -> Optional[dict]:
    """公開する機種。登録済みで、確認できた価格（採用できる行）が 1 つ以上あるものだけ。採用しなかった行・集約サイト由来の行は出さない。
    店名・商品名は自由記述を出さず、ドメインから決めた正規名・登録名にする。"""
    if not p.get("registered"):
        return None
    obs = []
    for o in p["observations"]:
        if o.get("price") and not o["reasons"]:
            row = _pub_scrub({k: o.get(k) for k in _PUBLIC_OBS_KEYS})
            row["source"] = _label_of(o.get("url"), o.get("source"))
            row["item_title"] = p["product"]
            obs.append(row)
    if not obs:
        return None
    routes = []
    for r in p["routes"]:
        rr = dict(r)
        rr["buy"] = _pub_view(r.get("buy"), p["product"])
        rr["sell"] = _pub_view(r.get("sell"), p["product"])
        routes.append(rr)
    sold = {k: {**v, "market": v["market"] if v["market"] in _MARKET_LABELS else "不明な市場"} for k, v in (p["secondary"].get("sold") or {}).items()}
    return {"product": p["product"], "product_id": p.get("product_id"), "registered": True, "observations": obs,
            "secondary": {"listing": {k: {**v, "low_source": "店頭の中古販売"} for k, v in (p["secondary"].get("listing") or {}).items()}, "sold": sold},
            "routes": routes, "best_route": p.get("best_route")}


def _pub_date(v) -> Optional[str]:
    """公開する日付は、日付に解釈できるものだけ（自由記述を出さない）。"""
    d = cr._d(v)
    return d.strftime("%Y-%m-%d") if d else None


_KEEP_QS = frozenset({"pid", "shop", "cat", "id", "item", "gid", "no", "code"})


def _pub_url(u) -> str:
    """公開する URL は、フラグメントを落とし、クエリは商品を指す名前（pid・shop・cat など）の短い英数字の値だけ残す（メモ・個人情報が混ざらない）。"""
    base, _, q = str(u or "").split("#", 1)[0].partition("?")
    keep = [kv for kv in q.split("&") if "=" in kv and kv.split("=", 1)[0].lower() in _KEEP_QS and re.fullmatch(r"[A-Za-z0-9_-]{1,24}", kv.split("=", 1)[1])]
    return base + (("?" + "&".join(keep)) if keep else "")


def _pub_int(v):
    return v if (isinstance(v, int) and not isinstance(v, bool)) else None


def _pub_scrub(row: dict) -> dict:
    """公開する 1 行の値を正規化する（日付は日付だけ・金額は整数だけ・URL は商品を指す部分だけ）。自由記述を残さない。"""
    out = dict(row)
    for k in ("checked_at", "source_updated_at"):
        if k in out:
            out[k] = _pub_date(out[k])
    for k in ("shipping_jpy", "price", "age_days"):
        if k in out:
            out[k] = _pub_int(out[k])
    if "url" in out:
        out["url"] = _pub_url(out["url"])
    return out


def _pub_events(state: dict, pub: list) -> list:
    reg = {x["product"] for x in pub}
    return [e for e in (_public_event(e, reg) for e in state["events"]) if e]


def _public_market(state: dict) -> dict:
    m = state["market"]
    pub = [x for x in (_public_product(p) for p in m["products"]) if x]
    return {
        "schema": 1, "type": "CAMERA_MARKET", "research_date": state["date"],
        "generated_at": state["now"].isoformat(timespec="seconds"),
        "note": "週次の Web 調査（AI）と自動収集から、確認できた価格だけで利益を計算します。確認できない項目は計算せず（NOT_CALCULATED）、"
                "出品の最高値は売値に使いません。成約は件数 3 以上・期間・個別の根拠が揃った中央値だけが売値です。",
        "products": pub, "summary": {k: v for k, v in state["report"].items() if k != "carried_rows"} | {"carried_rows": len(state["report"]["carried_rows"])},
        "events": _pub_events(state, pub), "quality": state["quality"],
        "notification_dry_run": {"sent": 0, "would_notify": len(_pub_events(state, pub)), "events": _pub_events(state, pub)},
        "source_results": sorted(({"shop": _public_shop(v["shop"]), "brand": _public_brand(v["brand"]), "role": v["role"], "result": v["result"], "lump": v["lump"],
                                   "reason": reason_code(v.get("reason")) if v["result"] in _BAD else ""} for v in source_matrix(state["sources"]).values()),
                                 key=lambda v: (v["shop"], v["brand"] or "", v["role"])),
        "hidden_counts": {"discovered_products_unverified": len(state["discovered"]),
                          "unregistered_or_unpriced_products_not_shown": sum(1 for p in m["products"] if _public_product(p) is None)},
        "lotteries": [{"product": _lottery_name(x.get("product"), m), "retailer": "公式ページ記載の販売元", "application_start": _pub_date(x.get("application_start")),
                       "application_end": _pub_date(x.get("application_end")), "official_url": _pub_url(x.get("official_url")), "evidence": "公式ページ"}
                      for x in state["lotteries"] if _primary(x.get("official_url")) and _official_evidence(x.get("evidence"))
                      and _lottery_name(x.get("product"), m)],
    }


_NOT_OFFICIAL = re.compile(r"未取得|未確認|記事|要約|snippet|検索|報じ|報道|ブログ|まとめ|SNS|二次情報|Twitter")


def _official_evidence(text) -> bool:
    """根拠の説明が「公式ページを読んだ」ものか。記事・検索の要約・未取得と書かれた抽選は公開しない。"""
    t = str(text or "")
    return bool(t) and not _NOT_OFFICIAL.search(t)


def _primary(url) -> bool:
    if not cr.domain_of(url):                      # バックスラッシュ・@・空白などを含む URL は公式として扱わない
        return False
    try:
        from src.research import weekly_import as wi
        return bool(url) and bool(wi.primary_evidence(url))
    except Exception:
        return False


def _public_event(e: dict, registered: set) -> Optional[dict]:
    """公開するイベント。登録済みの機種だけ。店名は正規名にする。"""
    if e.get("product") not in registered:
        return None
    out = dict(e)
    if "source" in out:
        out["source"] = _DOMAIN_LABEL.get(out["source"]) or "その他"
    return out


def history_snapshot(state: dict) -> dict:
    """履歴は公開データなので、公開する機種（登録済み・確認できた価格がある）だけ、店名・商品名は公開と同じ正規名・登録名にする。"""
    pub = [x for x in (_public_product(p) for p in state["market"]["products"]) if x]
    reg = {x["product"] for x in pub}
    snap = {"date": state["date"], "generated_at": state["now"].isoformat(timespec="seconds"), "observations": [], "routes": [],
            "events": [e for e in (_public_event(e, reg) for e in state["events"]) if e]}
    for p in pub:
        for o in p["observations"]:
            snap["observations"].append({"product": p["product"], "source": o["source"], "market_type": o["kind"], "price_type": o["price_type"],
                                         "price": o["price"], "condition": o["condition"], "checked_at": _pub_date(o.get("checked_at")),
                                         "source_updated_at": _pub_date(o.get("source_updated_at")), "carried": o.get("carried", False)})
        for r in p["routes"]:
            snap["routes"].append({"product": p["product"], "route": r["route_type"], "profit_status": r["profit_status"],
                                   "decision": r["decision"], "net_profit": r["net_profit"], "roi_pct": r["roi_pct"]})
    return snap


def merge_history(old: Optional[dict], snap: dict) -> dict:
    snaps = [s for s in (old or {}).get("snapshots", []) if s.get("date") != snap["date"]] + [snap]   # 同じ日の再実行は上書き
    return {"schema": 1, "snapshots": sorted(snaps, key=lambda s: s["date"])[-KEEP_SNAPSHOTS:]}


def write_all(state: dict, target_dir: Path, *, export_dir: Path, build_page=None) -> list:
    from src.utils.atomic_write import write_json_atomic
    export_dir.mkdir(parents=True, exist_ok=True)
    try:
        old_hist = json.loads((export_dir / HISTORY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old_hist = None
    write_json_atomic(export_dir / MARKET_FILE, _public_market(state))
    write_json_atomic(export_dir / HISTORY_FILE, merge_history(old_hist, history_snapshot(state)))
    written = [f"exports/camera_research/{MARKET_FILE}", f"exports/camera_research/{HISTORY_FILE}"]
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "camera_candidates.json").write_text(json.dumps(
        {"research_date": state["date"], "note": "未確認の新商品（DISCOVERED）。公開しない", "discovered": state["discovered"]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    if build_page:
        build_page()
        written.append("docs/camera-research.html")
    return written


def _build_page():
    import sys
    if str(PROJECT_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import build_public_lp
    build_public_lp._build_camera_research_html(build_public_lp.PUBLIC_DIR)


def summarize(state: dict, *, apply: bool, written=None, problems=None) -> dict:
    r = state["report"]
    return {
        "mode": "APPLY" if apply else "DRY_RUN",
        **{k: r[k] for k in ("sources_attempted", "sources_succeeded", "sources_failed", "products_checked", "products_discovered",
                             "buy_prices_changed", "buyback_prices_changed", "secondary_prices_changed", "sold_updated",
                             "profit_routes_changed", "new_profitable_routes", "routes_lost")},
        "found": r["found"], "routes": r["routes"], "events": state["events"], "quality": state["quality"],
        "carried_rows": len(r["carried_rows"]), "notification": "DRY_RUN（送信 0）",
        "validation_problems": problems or [],
        "public_files": written if written is not None else ["(検証エラーのため書かなかった)"] if (apply and problems) else ["(dry-run: 書かない) exports/camera_research/camera_market.json・camera_market_history.json", "(dry-run: 書かない) docs/camera-research.html"],
    }


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="カメラの週次の更新（せどり判断）。既定は dry-run（何も書かない）")
    ap.add_argument("--apply", action="store_true", help="検証に通ったときだけ、公開データ・履歴・ページへ書き込む")
    ap.add_argument("--dir", help="調査フォルダ（既定: .private/research/weekly/<今日>。無ければ直近のもの）")
    a = ap.parse_args(argv)
    now = datetime.now(JST)
    date = now.strftime("%Y-%m-%d")
    target = Path(a.dir) if a.dir else WEEKLY_ROOT / date
    if a.dir and not _DATE.fullmatch(target.name):
        print(json.dumps({"error": "調査フォルダの名前は YYYY-MM-DD にしてください（調査日をフォルダ名から決めます）"}, ensure_ascii=False))
        return 1
    if _DATE.fullmatch(target.name):
        date = target.name
    src = target if list(target.glob("research_camera_*.json")) else previous_dir(WEEKLY_ROOT, date)
    if not src:
        print(json.dumps({"error": "元になる調査フォルダが見つからない"}, ensure_ascii=False))
        return 1
    try:
        old = json.loads((EXPORT_DIR / MARKET_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old = None
    if _DATE.fullmatch(src.name):
        date = src.name                          # 今日の調査が無く直近のものを使うときも、調査日は元のフォルダの日付（今日にしない）
    state = refresh(src, date, now=now, old_market=old)
    problems = validate(state)
    written = None
    if a.apply and not problems:
        written = write_all(state, target, export_dir=EXPORT_DIR, build_page=_build_page)
    print(json.dumps(summarize(state, apply=a.apply, written=written, problems=problems), ensure_ascii=False, indent=1, default=list))
    if problems:
        return 1
    return 0 if not state["report"]["sources_failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
