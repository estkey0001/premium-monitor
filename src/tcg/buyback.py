# -*- coding: utf-8 -*-
"""TCG Route T1（公式定価 → 国内買取店）の買取データ。

守ること:
- 買取価格は買取店自身のページの価格だけ。集計サイト・フリマ・オークションの相場は使わない。
- 商品の同一性は JAN で照合する（名前の一部一致で同一扱いしない）。単位（BOX / CASE / SET …）と条件
  （新品未開封・シュリンク付き / 開封済み / 中古）が食い違う行は、利益にも「最高買取」にも使わない。
- 利益に使えるのは FRESH ＋ 同一性確認済み ＋ 単位一致 ＋ 条件が新品未開封の価格だけ（STALE・UNKNOWN は表示のみ）。
- 掲載の最高値（HIGHEST LISTED）と実行可能な最高値（HIGHEST EXECUTABLE）は別。
- 取得に失敗した店の古い行は、日付を進めずそのまま残す（鮮度で STALE になる）。取得時刻だけを新しくして新鮮に見せない。
- 費用が不明な経路は純利益を算出しない（NOT_CALCULATED）。不明を 0 円にしない。
- このモジュールはネットワークに触れない（取得は scripts/collect_tcg_buyback.py）。
"""
from __future__ import annotations

import html as _html
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "tcg_buyback.yaml"

# 販売・買取の単位（商品の同一性の一部）
UNITS = ("PACK", "BOX", "CASE", "SET", "PREMIUM_BOX", "DECK", "OTHER")
# 条件
C_NEW, C_UNOPENED, C_SEALED, C_USED, C_UNKNOWN = "NEW", "UNOPENED", "SEALED", "USED", "UNKNOWN"
C_OPENED = "OPENED"
EXECUTABLE_CONDITIONS = frozenset({C_UNOPENED, C_SEALED})                # 新品未開封の仕入れに使える条件。「新品」とだけ書かれた行（NEW）は未開封の根拠が無いので表示のみ
# 鮮度
FRESH, STALE, UNKNOWN_FRESHNESS = "FRESH", "STALE", "UNKNOWN_FRESHNESS"
# 利益の状態
PROFITABLE, NO_PROFIT, NOT_CALCULATED = "PROFITABLE", "NO_PROFIT", "NOT_CALCULATED"
OUTLIER_REVIEW = "OUTLIER_REVIEW"
# 同一性
ID_CONFIRMED = "CONFIRMED"

_DEFAULTS = {
    "freshness": {"page_date_fresh_days": 1, "page_asof_tolerance_minutes": 30, "observed_max_hours": 8, "future_tolerance_minutes": 5},
    "outlier": {"ratio": 1.5},
    "surge": {"yen": 1000, "pct": 15},
    "route_costs": {},
    "shops": {},
    "targets": [],
}


def load_config(path: Path = CONFIG_PATH) -> dict:
    """設定。読めない・壊れているときは既定値（targets が空なので何も採用しない＝安全側）。"""
    cfg = json.loads(json.dumps(_DEFAULTS))
    try:
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return cfg
    if not isinstance(data, dict):
        return cfg
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


# ───────────────────────── パース（店のページの HTML → 行） ─────────────────────────

def _int(s) -> Optional[int]:
    try:
        n = int(re.sub(r"[^\d]", "", str(s)))
    except ValueError:
        return None
    return n if n > 0 else None


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


_JAN = re.compile(r"JAN:\s*(\d{8,14})")
_ASOF = re.compile(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日\s*(\d{1,2})時\s*(\d{1,2})分現在")


_NEGATIVE_CONDITION = re.compile(r"開封済|(?<!未)開封品|シュリンク(無|な[しい]|破|あり.*不可)|中古|展示|傷|ダメージ|ダンボール未開封|ダンボールそのまま")


def condition_of(text: str, badge: str = "") -> str:
    """店の注意書きと商品名（「新品未開封/シュリンク付きのみ」等）から条件を決める。曖昧・否定の語が 1 つでもあれば新品未開封にしない。"""
    t = unicodedata.normalize("NFKC", text or "")
    if _NEGATIVE_CONDITION.search(t):
        return C_OPENED if re.search(r"(?<!未)開封|シュリンク(無|な[しい]|破)", t) else C_UNKNOWN
    if "未開封" in t and re.search(r"シュリンク付", t):
        return C_SEALED
    if "未開封" in t:
        return C_UNOPENED
    if (badge or "").strip() == "新品":
        return C_NEW
    return C_UNKNOWN


def units_in(name: str) -> set:
    """店の商品名に書かれている単位。書かれていなければ空（JAN で決まる商品）。"""
    t = unicodedata.normalize("NFKC", name or "")
    out = set()
    if re.search(r"カートン|CASE|ケース", t, re.I):
        out.add("CASE")
    if re.search(r"(?<![A-Za-z])BOX(?![A-Za-z])|ボックス", t, re.I):
        out.add("BOX")
    if re.search(r"デッキセット|カードセット|セット", t):
        out.add("SET")
    return out


def parse_rudeya(html: str, page_url: str, observed_at: datetime) -> dict:
    """買取ルデヤの一覧ページ。{asof, rows}。ページの「○時○分現在」は、ページを作った（=取得した）時刻で、
    価格の更新日ではない。取得した時刻と近いときだけ「その時点の最新」と認める（classify_freshness）。"""
    asof = None
    m = _ASOF.search(_text(html))
    if m:
        try:
            asof = datetime(*(int(x) for x in m.groups()), tzinfo=JST)
        except ValueError:
            asof = None
    rows = []
    for art in re.findall(r'<article class="pgrid-card".*?</article>', html or "", re.S):
        name = re.search(r'product-card-name-link"[^>]*>([^<]*)<', art)
        price = re.search(r'product-card-price-value">\s*([\d,]+)', art)
        if not name or not price:
            continue                                   # 価格が載っていない行（価格未掲載）は行を作らない
        jan = _JAN.search(art)
        link = re.search(r'product-card-name-link"\s+href="([^"]+)"', art) or re.search(r'href="([^"]+)"[^>]*class="product-card-name-link"', art)
        memo = re.search(r'product-card-memo">(.*?)</span>', art, re.S)
        badge = re.search(r'product-card-cond-badge[^"]*">([^<]*)<', art)
        stopped = re.search(r'product-card-stopped">([^<]*)<', art)       # 「お申込一時停止中」: 価格は載っているが今は買い取っていない
        p = _int(price.group(1))
        if p is None:
            continue
        raw = _text(name.group(1))
        rows.append({
            "shop": "rudeya", "raw_product_name": raw, "jan": jan.group(1) if jan else None, "price": p,
            "condition_text": _text(memo.group(1)) if memo else "",
            "condition": condition_of((_text(memo.group(1)) if memo else "") + " " + raw, badge.group(1) if badge else ""),
            "source_url": page_url, "item_url": link.group(1) if link else None,
            "source_updated_at": None, "page_asof": asof.isoformat() if asof else None,
            "observed_at": observed_at.isoformat(),
            **({"suspended": True, "suspended_text": _text(stopped.group(1))} if stopped else {}),
        })
    return {"asof": asof, "rows": rows}


_MM_UPDATED = re.compile(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日\s*更新")


def parse_morimori(html: str, page_url: str, observed_at: datetime) -> dict:
    """森森買取のカテゴリ一覧（ONE PIECE）。ページ見出しの「YYYY年M月D日 更新」が更新日。
    使う価格は「現在価格」（通常の買取価格）だけ。預かり・即フリは別の条件（期間・手数料）の価格なので使わない。
    価格が数字でない行（ASK = 価格未掲載）は行を作らない。"""
    html = html or ""
    first = html.find('mm1551-prow')                      # 更新日は価格表より前（見出し）のものだけ。お知らせ・フッターの日付を価格の更新日にしない
    m = _MM_UPDATED.search(_text(html[:first] if first >= 0 else html))
    updated = None
    if m:
        try:
            updated = datetime(*(int(x) for x in m.groups()), tzinfo=JST).strftime("%Y-%m-%d")
        except ValueError:
            updated = None
    rows = []
    for blk in re.findall(r'<div class="mm1551-prow" .*?(?=<div class="mm1551-prow" |</section>|$)', html, re.S):
        head = re.match(r'<div class="mm1551-prow" ([^>]*)>', blk)
        if not head or 'data-price-disp-flg="0"' not in head.group(1):
            continue
        name = re.search(r'mm1551-prow__name">\s*<a href="([^"]+)">([^<]*)</a>', blk)
        cur = re.search(r'mm1551-prow__cur-val">\s*([\d,]+)\s*<', blk)
        jan = re.search(r"JAN:\s*(\d{8,14})", blk)
        if not name or not cur:
            continue
        p = _int(cur.group(1))
        if p is None:
            continue
        note = re.search(r'class="notetip">(.*?)</span>', blk, re.S)
        badge = re.search(r'<span class="rk">([^<]*)<', blk)
        cond_text = _text(note.group(1)).split("※")[0].strip() if note else ""        # 「※不正品が…」以降は注意書きなので条件には使わない
        raw = _text(name.group(2))
        href = name.group(1)
        item_url = href if href.startswith("http") else "https://www.morimori-kaitori.jp" + href
        rows.append({
            "shop": "morimori", "raw_product_name": raw, "jan": jan.group(1) if jan else None, "price": p,
            "condition_text": cond_text,
            "condition": condition_of(cond_text + " " + raw, badge.group(1) if badge else ""),
            "source_url": page_url, "item_url": item_url,
            "source_updated_at": updated, "page_asof": None, "observed_at": observed_at.isoformat(),
        })
    return {"updated": updated, "rows": rows}


def parse_kaitorishouten(html: str, page_url: str, observed_at: datetime) -> Optional[dict]:
    """買取商店の商品ページ。JSON-LD（名前・JAN・価格）とページの「更新日 YYYY/MM/DD」。"""
    prod = None
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html or "", re.S):
        try:
            d = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product":
            prod = d
            break
    if not prod:
        return None
    offers = prod.get("offers") if isinstance(prod.get("offers"), dict) else {}
    price = _int(offers.get("price")) if isinstance(offers.get("price"), (int, float)) and not isinstance(offers.get("price"), bool) else None
    if price is None:
        return None
    t = _text(re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S))
    u = re.search(r"更新日\s*(20\d{2})/(\d{1,2})/(\d{1,2})", t)
    updated = f"{int(u.group(1)):04d}-{int(u.group(2)):02d}-{int(u.group(3)):02d}" if u else None
    new_label = bool(re.search(r"新品買取\s*[¥￥]", t))
    return {
        "shop": "kaitorishouten", "raw_product_name": _text(str(prod.get("name") or "")),
        "jan": str(prod.get("gtin13") or "") or None, "price": price,
        "condition_text": "新品買取" if new_label else "", "condition": C_NEW if new_label else C_UNKNOWN,
        "source_url": page_url, "item_url": page_url, "source_updated_at": updated, "page_asof": None,
        "observed_at": observed_at.isoformat(),
    }


# ───────────────────────── 同一性・重複 ─────────────────────────

def identify(row: dict, targets: list) -> dict:
    """行を対象商品に結ぶ。JAN が対象の JAN と一致し、かつ名前に書かれた単位が対象の単位と矛盾しないものだけ CONFIRMED。
    結べない行は product_id=None（捨てずに理由を残すが、利益・最高買取には使わない）。"""
    out = dict(row)
    out.update({"product_id": None, "tcg": None, "unit": None, "normalized_product_name": None,
                "identity_status": "NO_TARGET", "identity_reason": "対象商品の JAN と一致しない"})
    jan = str(row.get("jan") or "")
    for t in targets or []:
        if jan and jan == str(t.get("jan") or ""):
            seen = units_in(row.get("raw_product_name", ""))
            if seen and seen != {t.get("unit")}:                   # 単位が書かれているなら、対象の単位と完全に一致するときだけ（複数書かれていたら曖昧）
                out.update({"identity_status": "UNIT_MISMATCH",
                            "identity_reason": f"店の商品名の単位 {sorted(seen)} が対象の単位 {t.get('unit')} と違う（または複数書かれている）"})
                return out
            need = [unicodedata.normalize("NFKC", str(x)).lower() for x in (t.get("name_contains") or [])]
            nm = unicodedata.normalize("NFKC", row.get("raw_product_name", "")).lower()
            if any(x not in nm for x in need):                     # JAN が合っても、店の商品名に対象の特徴（型番・名前）が無ければ同一扱いしない
                out.update({"identity_status": "NAME_MISMATCH",
                            "identity_reason": f"JAN は一致するが、店の商品名に {need} がすべては含まれない"})
                return out
            out.update({"product_id": t["product_id"], "tcg": t.get("tcg"), "unit": t.get("unit"),
                        "normalized_product_name": t.get("name"), "identity_status": ID_CONFIRMED,
                        "identity_reason": f"JAN {jan} が一致、単位 {t.get('unit')} が矛盾しない"})
            return out
    return out


def dedupe(rows: list) -> list:
    """同じ店・同じ JAN・同じ条件の重複（同じ商品が「買取強化」と通常の一覧の両方に載る）は 1 行。
    同じキーで価格が食い違う行は、どちらも採用しない（ambiguous_rows）。"""
    groups: dict = {}
    for r in rows:
        k = (r.get("shop"), r.get("jan"), r.get("condition"))      # 商品名は含めない（名前だけ違って価格が食い違う行を両方残さない）
        groups.setdefault(k, []).append(r)
    out = []
    for k, g in groups.items():
        if len({x["price"] for x in g}) == 1:
            first = g[0]
            if any(x.get("suspended") for x in g) and not first.get("suspended"):
                first = {**first, "suspended": True, "suspended_text": next(x.get("suspended_text", "") for x in g if x.get("suspended"))}
            out.append(first)                              # 同じ価格の行に 1 件でも買取停止中があれば、並び順に関わらず停止中として扱う
    return out


# ───────────────────────── 鮮度 ─────────────────────────

def _parse_iso(v) -> Optional[datetime]:
    if not isinstance(v, str) or not v:
        return None
    try:
        d = datetime.fromisoformat(v)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=JST)


def classify_freshness(row: dict, cfg: dict, now: datetime) -> tuple[str, str]:
    """(FRESH / STALE / UNKNOWN_FRESHNESS, 理由)。取得時刻（observed_at）はこちらが実際に取得した時刻で、書き換えない。"""
    if row.get("carried_over"):
        return STALE, "取得に失敗したので前回の行を引き継いでいる（新鮮とは言わない）"
    fr = cfg.get("freshness") or {}
    from src.tcg import runtime_freshness as rf          # 生成時とページ表示時で同じ規則（しきい値は設定が唯一の定義）
    mx, fut = rf.thresholds(cfg)
    obs = _parse_iso(row.get("observed_at"))
    age = rf.evaluate(row.get("observed_at"), now, mx, fut)
    if obs is None or age == UNKNOWN_FRESHNESS:
        return UNKNOWN_FRESHNESS, "取得時刻が読めない（タイムゾーンが無い・未来を含む）"
    if age == STALE:
        return STALE, "取得してから時間が経っている（取得に失敗した日の古い価格）"
    basis = ((cfg.get("shops") or {}).get(row.get("shop")) or {}).get("freshness_basis")
    if basis == "page_asof":
        a = _parse_iso(row.get("page_asof"))
        if a is None:
            return UNKNOWN_FRESHNESS, "ページに時刻の記載が無い"
        tol = timedelta(minutes=float(fr.get("page_asof_tolerance_minutes", 30)))
        if abs(obs - a) <= tol:
            return FRESH, "ページの「現在」の時刻が取得時刻と一致（その時点の掲載価格）"
        return UNKNOWN_FRESHNESS, "ページの時刻が取得時刻とずれている（キャッシュの可能性）"
    if basis == "page_date":
        u = row.get("source_updated_at")
        try:
            d = datetime.strptime(str(u), "%Y-%m-%d").replace(tzinfo=JST)
        except ValueError:
            return UNKNOWN_FRESHNESS, "ページの更新日が読めない"
        if d.date() > obs.date():
            return UNKNOWN_FRESHNESS, "更新日が取得日より未来"
        if (obs.date() - d.date()).days <= int(fr.get("page_date_fresh_days", 1)):
            return FRESH, "ページの更新日が取得日の前後 1 日以内"
        return STALE, "ページの更新日が古い"
    return UNKNOWN_FRESHNESS, "この店の鮮度の根拠が未設定"


# ───────────────────────── 商品ごとの集計 ─────────────────────────

def _best_per_shop(rows: list) -> list:
    best: dict = {}
    for r in rows:
        if r["shop"] not in best or r["price"] > best[r["shop"]]["price"]:
            best[r["shop"]] = r
    return sorted(best.values(), key=lambda r: (-r["price"], r["shop"]))


def annotate(rows: list, cfg: dict, now: datetime) -> list:
    """全行に同一性・鮮度・実行可能かを付ける（元の行は変えない）。"""
    targets = cfg.get("targets") or []
    out = []
    for r in dedupe(rows):
        x = identify(r, targets)
        f, why = classify_freshness(x, cfg, now)
        x["freshness"], x["freshness_reason"] = f, why
        x["executable"] = bool(x["identity_status"] == ID_CONFIRMED and f == FRESH and x.get("condition") in EXECUTABLE_CONDITIONS
                               and x.get("unit") and not x.get("suspended"))
        out.append(x)
    return out


def summarize_product(product_id: str, rows: list, cfg: dict, msrp_price: Optional[int] = None) -> dict:
    """商品 1 件の買取の要約。rows は annotate() 済みの全行。"""
    mine = [r for r in rows if r.get("product_id") == product_id and r.get("identity_status") == ID_CONFIRMED]
    listed = _best_per_shop(mine)
    execs = _best_per_shop([r for r in mine if r["executable"]])
    status = "NO_BUYBACK"
    highest_exec = None
    outlier = None
    if execs:
        status = "EXECUTABLE"
        highest_exec = execs[0]
        ratio = float((cfg.get("outlier") or {}).get("ratio", 1.5))
        if len(execs) >= 2 and execs[0]["price"] > execs[1]["price"] * ratio:
            status, highest_exec, outlier = OUTLIER_REVIEW, None, execs[0]     # 最高値は外れ値の疑い。次点を最高とは呼ばない
        elif len(execs) == 1 and isinstance(msrp_price, int) and msrp_price > 0:
            mult = float((cfg.get("outlier") or {}).get("single_source_max_multiple", 3.0))
            if execs[0]["price"] > msrp_price * mult:                          # 1 店だけで定価の数倍: 別の店で確認できるまで最高買取と呼ばない
                status, highest_exec, outlier = OUTLIER_REVIEW, None, execs[0]
    elif listed:
        status = "LISTED_ONLY"                                                 # 載っているが、鮮度・条件のどれかが足りない
    return {
        "product_id": product_id, "status": status,
        "highest_listed": listed[0] if listed else None,
        "highest_executable": highest_exec,
        "ranking": execs[:3],                                                  # 最高買取・2 位・3 位（新鮮な行だけ）
        "shop_count": len(execs), "single_source": len(execs) == 1,
        "outlier": outlier, "listed_count": len(listed),
        "unit": (mine[0].get("unit") if mine else None),
    }


def profit_for(summary: dict, msrp: Optional[dict], cfg: dict) -> dict:
    """Route T1 の利益。定価（同じ単位）・費用の分かる経路・新鮮で同一性確認済みの買取価格がそろったときだけ算出する。"""
    def pending(reason: str) -> dict:
        return {"status": NOT_CALCULATED, "reason": reason, "net_profit": None, "roi_pct": None,
                "sell_price": None, "acquisition_cost": None, "sell_shop": None, "route": None}

    if not isinstance(msrp, dict) or not isinstance(msrp.get("retail_price"), int) or msrp["retail_price"] <= 0:
        return pending("公式の定価（この販売単位の価格）が確認できていない。パック価格から BOX の定価は作らない")
    if summary.get("status") == OUTLIER_REVIEW:
        if summary.get("shop_count") == 1:
            return pending("買取が 1 店のみで、定価の数倍と大きく離れた価格のため確認待ち（別の店でも確認できたら算出する）")
        return pending("最高の買取価格が他店と大きく離れており、確認待ち（外れ値の疑い）")
    if summary.get("status") != "EXECUTABLE":
        return pending("鮮度・同一性・単位・条件を満たす買取価格が無い")
    route = (cfg.get("route_costs") or {}).get("store_counter") or {}
    ok_shops = set(route.get("shops_supporting") or [])
    cand = [r for r in (summary.get("ranking") or []) if r.get("shop") in ok_shops]
    if not cand:
        return pending("費用（送料）が分かる経路で買取している店の、新鮮な価格が無い")
    sell = cand[0]
    mult = float((cfg.get("outlier") or {}).get("single_source_max_multiple", 3.0))
    if summary.get("shop_count") == 1 and sell["price"] > msrp["retail_price"] * mult:
        return pending(f"買取が 1 店のみで、定価の {mult:g} 倍を超える価格のため確認待ち（別の店でも確認できたら算出する）")
    costs = [route.get("purchase_shipping_yen"), route.get("outbound_shipping_yen"), route.get("other_yen")]
    if any(not isinstance(c, int) or isinstance(c, bool) or c < 0 for c in costs):
        return pending("費用が不明（不明を 0 円にしない）")
    acq = msrp["retail_price"] + costs[0]
    net = sell["price"] - acq - costs[1] - costs[2]
    return {
        "status": PROFITABLE if net > 0 else NO_PROFIT, "reason": None,
        "net_profit": net, "roi_pct": round(net / acq * 100, 1), "sell_price": sell["price"], "sell_shop": sell["shop"],
        "acquisition_cost": acq, "retail_price": msrp["retail_price"], "sell_observed_at": sell.get("observed_at"),
        "route": route.get("label"), "route_note": route.get("note"),
        "single_source": bool(summary.get("single_source")),
    }


# ───────────────────────── 履歴・価格の変化 ─────────────────────────

def history_key(r: dict) -> tuple:
    return (r.get("product_id"), r.get("shop"), r.get("unit"), r.get("condition"))


def update_history(history: list, rows: list, today: str, keep_days: int = 120) -> list:
    """観測を履歴に足す（同じ日の同じキーは 1 件。実際に取得した行だけ）。"""
    hist = [h for h in (history or []) if isinstance(h, dict)]
    have = {(history_key(h), h.get("date")) for h in hist}
    for r in rows:
        if r.get("identity_status") != ID_CONFIRMED or r.get("carried_over") or r.get("suspended"):
            continue                                      # 取得に失敗して引き継いだ行・買取停止中の行（今は買い取っていない価格）は、今日の観測として履歴に入れない
        k = (history_key(r), today)
        if k in have:
            continue
        have.add(k)
        hist.append({"product_id": r["product_id"], "shop": r["shop"], "unit": r["unit"], "condition": r["condition"],
                     "price": r["price"], "checked_at": r["observed_at"], "date": today})
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    return sorted((h for h in hist if str(h.get("date")) >= cutoff), key=lambda h: (h["date"], str(h["product_id"]), h["shop"]))


def price_events(history: list, rows: list, today: str, cfg: dict) -> list:
    """同じ商品・店・単位・条件の前回（今日より前の最新）との差。語彙: PRICE_RISE / PRICE_DROP / BUYBACK_SURGE。"""
    sg = cfg.get("surge") or {}
    prev: dict = {}
    for h in sorted((h for h in history or [] if str(h.get("date")) < today), key=lambda h: h["date"]):
        prev[history_key(h)] = h
    events = []
    for r in rows:
        if r.get("identity_status") != ID_CONFIRMED or r.get("carried_over") or r.get("suspended") or r.get("freshness") != FRESH:
            continue                                   # 取得していない日・買取停止中の価格・古い価格から、新しい日付のイベントを作らない
        p = prev.get(history_key(r))
        if not p or p["price"] == r["price"]:
            continue
        d = r["price"] - p["price"]
        surge = d > 0 and d >= int(sg.get("yen", 1000)) and d / p["price"] * 100 >= float(sg.get("pct", 15))
        events.append({"type": "BUYBACK_SURGE" if surge else ("PRICE_RISE" if d > 0 else "PRICE_DROP"),
                       "product_id": r["product_id"], "shop": r["shop"], "unit": r["unit"],
                       "from": p["price"], "to": r["price"], "from_date": p["date"], "to_date": today})
    return events


def build_export(rows: list, history: list, shops_state: dict, cfg: dict, now: datetime, msrp_rows: Optional[list] = None) -> dict:
    """exports/tcg/buyback.json の中身。"""
    today = now.strftime("%Y-%m-%d")
    ann = annotate(rows, cfg, now)
    hist = update_history(history, ann, today)
    from src.tcg.hub.profit_link import msrp_for       # 画面と同じ定価の選び方（単一ソースの乖離ゲートを JSON の要約にも効かせる）

    def _msrp(t: dict) -> Optional[int]:
        hit = msrp_for(t["product_id"], t.get("tcg"), None, msrp_rows or [])
        return hit["retail_price"] if hit else None
    summaries = {t["product_id"]: summarize_product(t["product_id"], ann, cfg, _msrp(t)) for t in cfg.get("targets") or []}
    kept = [r for r in ann if r["identity_status"] != "NO_TARGET"]      # 対象外の商品（店の一覧の他の商品）は公開しない
    return {
        "schema": 1, "generated_at": now.isoformat(), "shops": shops_state, "rows": kept,
        "summaries": summaries, "events": price_events(history, ann, today, cfg),
        "counts": {"rows": len(kept), "rows_seen": len(ann), "confirmed": sum(1 for r in ann if r["identity_status"] == ID_CONFIRMED),
                   "executable": sum(1 for r in ann if r["executable"]),
                   "products_with_executable": sum(1 for s in summaries.values() if s["status"] in ("EXECUTABLE", OUTLIER_REVIEW)),
                   "products_listed": sum(1 for s in summaries.values() if s["status"] != "NO_BUYBACK")},
    }, hist
