"""発見の候補の優先順位（Phase 30。運営者向け。顧客向けの利益とは別）。

確認待ちの Apple の候補に、決まった計算式で100点満点の点を付ける（同じ入力なら同じ点・AI の推測を使わない）:

| 項目 | 配点 | 根拠 |
|---|---:|---|
| 公式の証拠 | 20 | 公式の価格（色で同じ1つ）・日本向けの部品番号・公式の購入ページ・7日以内に公式で見た |
| 買取の取得 | 25 | 既存の買取の取得元で、全色の部品番号の行（商品ページ）がそろう = 25・一部の色だけ = 10・無い / 不明 / ブロック = 0 |
| 見込みの差 | 25 | 全色がそろったときだけ: 差 = 最も低い色の買取 − 公式の価格 − 既知の費用。差が 0 以下は 0、正なら 10 + ROI（%・切り捨て）で上限 25（売値・送料が分からなければ付けない） |
| 同一性 | 15 | 機種と容量が名前から読める・部品番号がある・公式の購入ページ |
| 市場の根拠 | 10 | 買取の取得元に機種の価格表がある・まとめのページに載っている（取得した事実だけ） |
| 監視の準備 | 5 | 既存の取得元に機種の価格表の URL がある（最小の変更で照合を足せる） |

買取の行の照合は、機種・容量・SIMフリー・キャリア版 / 中古の除外・行の部品番号が候補の部品番号のどれか、まで（Phase 29 の
照合と同じ考え）。色で価格が違えば最も低い色（都合の良い最高値だけを使わない）。他の容量・他の機種の価格から推測しない。
"""
from __future__ import annotations

import re
from datetime import datetime

from . import apple
from . import store as st

INPUT_FIELDS = ("source", "status", "product_name", "model_number", "capacity", "part_numbers", "official_url",
                "official_price", "official_prices", "last_seen_on")
WEIGHTS = {"official": 20, "buyback": 25, "spread": 25, "identity": 15, "market": 10, "readiness": 5}
_PART = re.compile(r"\b[A-Z0-9]{4,5}J/A\b")
_EXCLUDE = ("au", "docomo", "ドコモ", "softbank", "ソフトバンク", "楽天", "中古", "未使用", "開封済")
INDEX_URL = "https://www.kaitorishouten-co.jp/keitai"
SHOP_BASE = "https://www.kaitorishouten-co.jp"
_DETAIL = re.compile(r"^(?:https://www\.kaitorishouten-co\.jp)?/products/detail/\d+$")


def family_key(text: str) -> str:
    """機種の比べる形（「iPhone18 Pro Max」「iPhone 18 Pro Max」→ iphone18promax）。"""
    return re.sub(r"[\s　]+", "", str(text or "")).lower()


def known_costs(official_url: str, price: int) -> int | None:
    """公式で買って買取に売るときの既知の費用（式は market/profit_formula が正本）。送料が分からなければ None。"""
    from src.market import profit_formula
    return profit_formula.beginner_costs("", official_url, price)


def match_buyback_rows(cand: dict, rows) -> list[tuple]:
    """候補の機種・容量・SIMフリー・部品番号に一致する買取の行（商品ページの行だけ）。"""
    model, cap = str(cand.get("model_number") or ""), str(cand.get("capacity") or "")
    parts = set(cand.get("part_numbers") or [])
    if not model or not cap or not parts:
        return []
    head = re.compile(r"^" + r"\s?".join(re.escape(w) for w in model.split()) + r"\s+" + re.escape(cap) + r"\b")
    out = []
    for r in rows or ():
        name, href = str(r[0]), str(r[2])
        if not head.search(name) or "SIMフリー" not in name or not _DETAIL.match(href):
            continue
        if any(re.search(r"(?<![A-Za-z])" + re.escape(x) + r"(?![A-Za-z])", name, re.IGNORECASE) for x in _EXCLUDE):
            continue
        found = _PART.findall(name)
        if len(found) != 1 or found[0] not in parts:
            continue
        out.append((name, int(r[1]), href))                 # 取得元の種類（まとめ / 価格表）は落として重複を除く
    return sorted(set(out))


def score_candidate(cand: dict, evidence: dict, *, now: datetime) -> dict:
    """1件の候補の点と内訳・理由（決まった計算式。evidence は買取の取得の記録）。"""
    reasons: list[str] = []
    pts = dict.fromkeys(WEIGHTS, 0)
    model, cap = str(cand.get("model_number") or ""), str(cand.get("capacity") or "")
    parts = list(cand.get("part_numbers") or [])
    url = str(cand.get("official_url") or "")
    price = cand.get("official_price")
    single = isinstance(price, int) and not isinstance(price, bool) and price > 0 \
        and len(cand.get("official_prices") or []) == 1
    try:
        fresh = (now.date() - datetime.fromisoformat(str(cand.get("last_seen_on")) + "T00:00:00").date()).days \
            < st.STALE_AFTER_DAYS
    except ValueError:
        fresh = False
    parts_ok = bool(parts) and all(_PART.fullmatch(p) for p in parts)
    url_ok = url.startswith("https://www.apple.com/jp/shop/buy-iphone/")
    pts["official"] = 5 * sum((single, parts_ok, url_ok, fresh))
    official_state = "CONFIRMED" if pts["official"] == WEIGHTS["official"] else "UNKNOWN"
    if not single:
        reasons.append("official_price_not_single")
    if not fresh:
        reasons.append("not_seen_recently")
    parsed = apple.parse_name(f"{model} {cap}")
    name_ok = bool(parsed) and parsed["capacity"] == cap and cand.get("product_name") == f"{model} {cap}"
    pts["identity"] = 5 * sum((name_ok, parts_ok, url_ok))
    if not name_ok:
        reasons.append("identity_ambiguous")
    # 買取（取得した事実だけ）
    fam = family_key(model)
    fam_pages = (evidence or {}).get("families") or {}
    page = fam_pages.get(fam) or {}
    index_ok = (evidence or {}).get("index_status") == "ok"
    rows = match_buyback_rows(cand, (evidence or {}).get("rows") or [])
    covered = {(_PART.findall(r[0]) or [""])[0] for r in rows}
    if page.get("status") == "blocked" or (evidence or {}).get("index_status") == "blocked":
        buyback_state = "BLOCKED"
    elif rows and covered == set(parts):
        buyback_state = "CONFIRMED"
    elif rows:
        buyback_state = "PARTIAL"                               # 一部の色だけ（全色の対応が分からない）
    elif page.get("status") == "ok":
        buyback_state = "NOT_LISTED"                            # 機種の価格表を読んだが、この容量の行が無い
    else:
        buyback_state = "UNKNOWN"
    pts["buyback"] = {"CONFIRMED": 25, "PARTIAL": 10}.get(buyback_state, 0)
    sell = min(r[1] for r in rows) if buyback_state == "CONFIRMED" else None   # 全色のうち最も低い色
    spread = None
    costs = known_costs(url, price) if single else None
    if sell is not None and single and costs is not None:
        spread = sell - price - costs
        roi = spread / price
        pts["spread"] = 0 if spread <= 0 else min(WEIGHTS["spread"], 10 + int(roi * 100))
        if spread <= 0:
            reasons.append("no_profit_at_current_prices")
    elif buyback_state != "CONFIRMED":
        reasons.append(f"buyback_{buyback_state.lower()}")
    elif costs is None and single:
        reasons.append("shipping_unknown")                       # 送料が分からないので差を出さない
    # まとめのページ（取得元が選んで載せる各機種の数行）に、この機種の行がある（容量は問わない・前方一致で別の機種に当てない）
    any_cap = re.compile(r"^" + r"\s?".join(re.escape(w) for w in model.split()) + r"\s+\d{1,4}(?:GB|TB)\b") if model else None
    in_summary = bool(any_cap) and any(len(r) > 3 and r[3] == "index" and any_cap.search(str(r[0]))
                                       for r in (evidence or {}).get("rows") or [])
    pts["market"] = 5 * sum((bool(page.get("listed_in_index")), in_summary))
    pts["readiness"] = 5 if (index_ok and page.get("category_url")) else 0
    total = sum(pts.values())
    # 計算に使った候補の入力（priority.json を後から台帳に依らずに確かめるため。台帳は毎日の発見で変わる）
    inputs = {k: cand.get(k) for k in INPUT_FIELDS}
    return {"candidate_id": cand.get("candidate_id"), "inputs": inputs, "product_name": cand.get("product_name"),
            "model": model,
            "capacity": cap, "status": cand.get("status"), "official_price": price if single else None,
            "official_state": official_state, "buyback_state": buyback_state, "buyback_sell": sell,
            "buyback_rows": [list(r) for r in sorted(rows, key=lambda r: (r[1], r[0], r[2]))],
            "known_costs": costs, "spread": spread, "points": pts, "score": total,
            "category_url": page.get("category_url") or "", "reasons": sorted(set(reasons))}


def rank(candidates: dict, evidence: dict, *, now: datetime) -> dict:
    """確認待ちの Apple の候補の順位（登録済み・一致・却下・STALE は除く）。同点は候補の ID の順。"""
    ranked, excluded = [], []
    for cid in sorted(candidates or {}):
        c = candidates[cid]
        if not isinstance(c, dict) or c.get("source") != apple.SOURCE:
            continue
        if c.get("status") != st.PENDING_REVIEW:
            excluded.append({"candidate_id": cid, "status": c.get("status"), "reason": "not_pending_review"})
            continue
        r = score_candidate(dict(c, candidate_id=cid), evidence, now=now)
        if "not_seen_recently" in r["reasons"]:
            excluded.append({"candidate_id": cid, "status": c.get("status"), "reason": "stale"})
            continue
        ranked.append(r)
    # 同点は仕入れ値（公式の価格）が低い順（必要な資金が少ない）・候補の ID の順
    ranked.sort(key=lambda r: (-r["score"], r["official_price"] if r["official_price"] else 10 ** 9, r["candidate_id"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return {"ranked": ranked, "excluded": excluded, "weights": dict(WEIGHTS)}


def index_families(html: str) -> dict:
    """買取の取得元のまとめのページから、機種 → 価格表の URL（「iPhone Duoの買取価格表を見る」の形のリンク）。"""
    out = {}
    for href, text in re.findall(r'href="(/category/1/\d+)"[^>]*>([^<]{1,60})', html or ""):
        m = re.match(r"^\s*(iPhone[^<]*?)の買取価格表", text)
        if m:
            out.setdefault(family_key(m.group(1)), SHOP_BASE + href)
    return out
