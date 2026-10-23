"""調査候補（リサーチエンジンの土台）: 「候補として見つける」と「確定した利益として出す」を分ける。

確定の利益の判定は src/content/ui/opportunity.py の eligibility() が正本で、ここでは変えない・やり直さない。
ここでは、判定で外された商品（公式の価格が未確認・売値が古い・店のトップの URL・商品の照合が未了…）のうち、
生の価格差（売値 − 買値）がある商品を捨てずに「調査候補」として残し、運営者が人の手で確かめられるようにする。

    DISCOVERED → RESEARCH_CANDIDATE → VERIFIED → （CONFIRMED_OPPORTUNITY → ACTIONABLE は既存の判定）

- 調査候補は確定の利益ではない。顧客向けの画面・LP・商品の通知には出さない（運営者向けのページだけが読む）
- VERIFIED は、既存の判定（eligible）を通った商品だけ。ここで独自に VERIFIED にしない
- AI の予測価格は使わない。価格は観測した買値・売値だけ。生の価格差が大きすぎるものは誤価格の疑いとして信頼度を下げる
- 候補の ID は商品だけから決まる（価格・経路・買う店・売る店が変わっても同じ ID。重複しない）
- 台帳（state）で初めて見た日（discovered_at）と最後に見た日（last_seen_at）を持つ。見えなくなった候補は STALE として
  残し、STALE_RETENTION_DAYS を過ぎたら捨てる
"""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta

SCHEMA = 1

# 状態
DISCOVERED = "DISCOVERED"
RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
VERIFIED = "VERIFIED"
REJECTED = "REJECTED"
STALE = "STALE"
STATUSES = (DISCOVERED, RESEARCH_CANDIDATE, VERIFIED, REJECTED, STALE)

# 経路
RETAIL_TO_BUYBACK = "RETAIL_TO_BUYBACK"          # 公式の定価で買って買取店に売る
SECONDARY_TO_BUYBACK = "SECONDARY_TO_BUYBACK"    # 販売店の新品（公式で買えない・公式が無い）を買って買取店に売る

# 足りないもの・外した理由の語彙
OFFICIAL_UNVERIFIED = "OFFICIAL_UNVERIFIED"          # 公式の価格が人の確認済みでない（設定値・期限切れ・不明）
OFFICIAL_NOT_SOLD = "OFFICIAL_NOT_SOLD"              # 公式で販売終了・後継機に交代（公式の定価で今は買えない）
BUY_NOT_ITEM_LEVEL = "BUY_URL_NOT_ITEM_LEVEL"        # 買う側の価格が検索結果・店トップのもの
BUY_STALE = "BUY_STALE"
SELL_STALE = "SELL_STALE"
GENERIC_SELL_URL = "GENERIC_SELL_URL"                # 売る側の URL が検索結果・店のトップ
IDENTITY_UNCONFIRMED = "IDENTITY_UNCONFIRMED"        # 売る側の商品の照合が未了
CONDITION_UNKNOWN = "CONDITION_UNKNOWN"
CONDITION_MISMATCH = "CONDITION_MISMATCH"
STOCK_UNKNOWN = "STOCK_UNKNOWN"                      # 参考情報（確定の関門には使わない）
SELL_SAMPLE_INSUFFICIENT = "SELL_SAMPLE_INSUFFICIENT"
PURCHASE_SHIPPING_UNKNOWN = "PURCHASE_SHIPPING_UNKNOWN"
PRICE_ANOMALY_SUSPECTED = "PRICE_ANOMALY_SUSPECTED"  # 価格差が買値に比べて大きすぎる（誤価格・別商品の疑い）
SELL_REJECTED = "SELL_REJECTED"                      # 売る側の価格が品質の判定で外れた（疑わしい価格など）
NET_NEGATIVE = "NET_NEGATIVE_AFTER_KNOWN_COSTS"      # 分かっている費用を引くと利益が出ない
NO_SELL_SIDE = "NO_SELL_PRICE"
NO_BUY_SIDE = "NO_BUY_PRICE"
NO_SPREAD = "NO_SPREAD"

# 確定の関門ではなく参考として付ける理由（これだけが残っても VERIFIED は既存の判定が決める）
ADVISORY = frozenset({STOCK_UNKNOWN})
# 候補の信頼度を下げる理由
LOW_CONFIDENCE_REASONS = frozenset({PRICE_ANOMALY_SUSPECTED, IDENTITY_UNCONFIRMED, SELL_REJECTED})
# 価格そのものが疑わしい理由（差の加点をしない・優先度を low に固定する）
LOW_CONFIDENCE_PRICE_REASONS = frozenset({PRICE_ANOMALY_SUSPECTED, SELL_REJECTED})

ANOMALY_RATIO = 0.5              # 価格差が買値の50%を超えるものは誤価格の疑い
STALE_RETENTION_DAYS = 30        # 見えなくなった候補を STALE として残す日数
CATALOG_LIST_LIMIT = 100         # 買取の一覧から見つけた未登録の商品の候補を残す上限（価格の高い順）

_NOT_ITEM_LINK = ("shop_home", "search", "official_top", "none", "unknown", "")
_SELL_REASON_MAP = {
    "stale_sell_price": SELL_STALE,
    "sell_identity_unverified": IDENTITY_UNCONFIRMED,
    "sell_url_not_item_level": GENERIC_SELL_URL,
    "sell_wrong_product": IDENTITY_UNCONFIRMED,
    "condition_mismatch": CONDITION_MISMATCH,
}


def candidate_id(route: str, product_id: str, buy_source: str = "", sell_source: str = "") -> str:
    """商品から決まる安定した ID（価格・日時・経路・買う店・売る店は含めない）。

    経路（公式 → 買取か、販売店 → 買取か）は、公式の販売が終わった日・公式の観測が消えた日に切り替わる。買う店（販売店の
    最安）も売る店（最高値の買取店）も日ごとに入れ替わる（売値が無い日もある）。どれを ID に入れても、同じ商品が
    「今日見つかった新しい候補」と古い候補（STALE）に二重に出る。経路・店は属性（route_type・source）として持つ。
    route・buy_source・sell_source は互換のための引数で、ID には使わない（1商品1行）。
    """
    raw = "|".join(["product", product_id])
    return "rc_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _sell_reasons(o: dict, buy_condition: str = "new") -> list[str]:
    from src.market import normalized_prices as npr
    out = []
    for r in npr.sell_confirmation_reasons(o, buy_condition=buy_condition):
        if r in _SELL_REASON_MAP:
            out.append(_SELL_REASON_MAP[r])
        elif r.startswith("sell_rejected_"):
            # 古いだけの行（rejection_reason が stale…）は SELL_STALE で表す。品質の判定で外れた行（疑わしい価格など）だけ
            if not r.startswith("sell_rejected_stale"):
                out.append(SELL_REJECTED)
        # not_sell / sell_type_not_buyback / invalid_sell_price は呼び出し側で除いてある
    if (o.get("condition") or "") in ("", "unknown") and CONDITION_MISMATCH in out:
        out[out.index(CONDITION_MISMATCH)] = CONDITION_UNKNOWN
    return list(dict.fromkeys(out))


def _sell_options(obs: list[dict], pid: str) -> list[dict]:
    """売る側の候補（買取の現金・価格が正・付属品や別の型番でないもの）。"""
    from src.market import price_types as pt
    out = []
    for o in obs:
        if o.get("product_id") != pid or o.get("price_role") != "sell":
            continue
        if pt.canonical(o.get("canonical_price_type") or o.get("price_type")) != pt.BUYBACK_CASH:
            continue
        p = o.get("price")
        if not isinstance(p, (int, float)) or p <= 0:
            continue
        if o.get("accessory_flag") or o.get("wrong_model_flag"):
            continue
        out.append(o)
    return out


def _best_sell(obs: list[dict], pid: str, buy_price: int | None = None):
    """売る側の代表の観測と、その行が確定の売値に使えない理由。戻りは (観測, 理由, 古い高値を使ったか)。

    確定できる売値（既存の関門を通る行）の最高値を使う。ただし、その行では価格差が出ないのに、確定できない行
    （古い・店のトップの URL・商品の照合が未了…）に買値を上回る高値があるときは、その高値を調査候補の売値にする
    （最新の確定の売値では差が無いが、再確認すれば差が出るかもしれない商品を捨てない。理由は必ず付く）。
    """
    opts = _sell_options(obs, pid)
    if not opts:
        return None, [], False
    key = lambda o: (o["price"], str(o.get("source_id") or ""))  # noqa: E731
    confirmed = [o for o in opts if not _sell_reasons(o)]
    # 確定できない行の中では、品質の判定で外れた行（疑わしい価格・隔離）を後回しにする。外れた高値は調べる価値の
    # ある候補の代表にしない（それしか無いときだけ使う。理由 SELL_REJECTED が付き、信頼度・優先度は低くなる）
    clean = [o for o in opts if SELL_REJECTED not in _sell_reasons(o)]
    raw_best = max(clean or opts, key=key)
    if confirmed:
        best = max(confirmed, key=key)
        if (buy_price is not None and best["price"] - buy_price <= 0 and raw_best["price"] > buy_price
                and raw_best is not best):
            return raw_best, _sell_reasons(raw_best), True
        return best, [], False
    return raw_best, _sell_reasons(raw_best), False


def _best_secondary_buy(obs: list[dict], pid: str):
    """公式で買えない商品の買う側: 販売店の新品の販売価格の最安（店のトップ・検索結果は理由に残す）。"""
    from src.content.ui.opportunity import _cond_family
    out = [o for o in obs if o.get("product_id") == pid and o.get("price_type") == "shop_sale_price"
           and isinstance(o.get("price"), (int, float)) and o["price"] > 0
           and _cond_family(o.get("condition")) == _cond_family("new")
           and not o.get("accessory_flag") and not o.get("wrong_model_flag")]
    if not out:
        return None
    return min(out, key=lambda o: (o["price"], str(o.get("source_id") or "")))


def _official_obs(obs: list[dict], pid: str):
    for o in obs:
        if (o.get("product_id") == pid and o.get("price_role") == "official"
                and isinstance(o.get("price"), (int, float)) and o["price"] > 0):
            return o
    return None


def _shipping_fee(pid: str, url: str, price: int):
    from src.market import official_shipping
    try:
        return official_shipping.purchase_shipping(pid, url, price)["fee"]
    except Exception:  # noqa: BLE001 - 送料が分からないときは None（0円とみなさない）
        return None


def _confidence(reasons: list[str]) -> str:
    blocking = [r for r in reasons if r not in ADVISORY]
    if any(r in LOW_CONFIDENCE_REASONS for r in reasons) or len(blocking) >= 4:
        return "low"
    if len(blocking) <= 1:
        return "high"
    return "medium"


def priority_of(c: dict) -> tuple[int, list[str]]:
    """調査の優先順位の点（決まった計算式。AI の予測価格は使わない）。大きいほど先に調べる。

    加点: 純の差（円。10万円で上限）/ 売値が新しい / 商品の照合ができている / 足りないのが公式の確認だけ
    減点: 売値が古い / 店のトップ・検索結果の URL / 照合が曖昧 / 誤価格の疑い / 取得元が遮断
    """
    reasons = set(c.get("exclusion_reasons") or [])
    score, why = 0, []
    net = int(c.get("known_cost_spread") or 0)
    # 誤価格の疑い・品質の判定で外れた売値は、差の大きさを加点しない（差が大きいほど疑わしい）
    base = 0 if reasons & LOW_CONFIDENCE_PRICE_REASONS else min(max(net, 0), 100_000) // 1000
    score += base
    why.append(f"net+{base}")
    if SELL_STALE not in reasons:
        score += 20
        why.append("sell_fresh+20")
    if IDENTITY_UNCONFIRMED not in reasons:
        score += 15
        why.append("identity_ok+15")
    blocking = reasons - ADVISORY
    if blocking == {OFFICIAL_UNVERIFIED}:
        score += 25
        why.append("only_official_check_missing+25")
    for r, pts in ((SELL_STALE, -30), (GENERIC_SELL_URL, -25), (IDENTITY_UNCONFIRMED, -30),
                   (PRICE_ANOMALY_SUSPECTED, -40), (SELL_REJECTED, -20), (BUY_NOT_ITEM_LEVEL, -15)):
        if r in reasons:
            score += pts
            why.append(f"{r}{pts}")
    if c.get("source_blocked"):
        score -= 20
        why.append("source_blocked-20")
    return score, why


def _label(score: int, reasons=()) -> str:
    # 誤価格の疑い・外れた売値は、点に関わらず優先度 low（信頼度 low と連動。本物の候補より上に並べない）
    if set(reasons) & LOW_CONFIDENCE_PRICE_REASONS:
        return "low"
    return "high" if score >= 60 else ("medium" if score >= 30 else "low")


def build_candidates(*, products: list[dict], observations: list[dict], msrp_evidence: dict, official_meta: dict,
                     verified_pids: set[str], now: datetime, blocked_sources: set[str] | None = None) -> list[dict]:
    """商品ごとの調査候補（状態・買値・売値・生の差・足りないもの・信頼度・優先度）。

    verified_pids: 既存の判定（eligibility）を通った商品。ここに入るものだけが VERIFIED。
    """
    from src.content.ui import categories as cats
    from src.market import price_evidence as pe
    from src.market import profit_formula as pf

    blocked_sources = blocked_sources or set()
    out = []
    for p in products:
        pid = p["id"]
        meta = official_meta.get(pid, {})
        off = _official_obs(observations, pid)
        route = RETAIL_TO_BUYBACK
        buy, buy_source, buy_url, buy_reasons = None, "official", "", []
        ev = msrp_evidence.get(pid, pe.UNKNOWN)
        if meta.get("official_not_sold") or off is None:
            sec = _best_secondary_buy(observations, pid)
            if sec is not None:
                route, buy = SECONDARY_TO_BUYBACK, sec
                buy_source = str(sec.get("source_id") or "shop")
                buy_url = sec.get("item_url") or sec.get("source_url") or ""
                if str(sec.get("link_type") or "") in _NOT_ITEM_LINK:
                    buy_reasons.append(BUY_NOT_ITEM_LEVEL)
                if sec.get("is_fresh") is not True:
                    buy_reasons.append(BUY_STALE)
                if sec.get("is_exact_product_match") is not True:
                    buy_reasons.append(IDENTITY_UNCONFIRMED)
            if meta.get("official_not_sold"):
                buy_reasons.append(OFFICIAL_NOT_SOLD)
        if buy is None and off is not None:
            buy = off
            buy_url = meta.get("url") or off.get("source_url") or ""
            if not pe.is_profit_eligible(ev):
                buy_reasons.append(OFFICIAL_UNVERIFIED)
            if meta.get("official_not_sold"):
                pass          # 上で付けた
        sell, sell_reasons, used_stale_high = _best_sell(observations, pid, int(buy['price']) if buy else None)

        reasons = list(buy_reasons)
        reasons += sell_reasons
        row = {"candidate_id": candidate_id(route, pid, buy_source, str((sell or {}).get("source_id") or "")),
               "product_identity": {"product_id": pid, "name": p.get("name", ""), "genre": p.get("genre", "")},
               "genre": cats.from_genre(p.get("genre") or ""), "route_type": route,
               "source": {"buy": buy_source, "sell": str((sell or {}).get("source_name") or (sell or {}).get("source_id") or "")},
               "source_url": {"buy": buy_url, "sell": str((sell or {}).get("item_url") or (sell or {}).get("source_url") or "")},
               "observed_buy_price": int(buy["price"]) if buy else None,
               "observed_sell_price": int(sell["price"]) if sell else None,
               "sell_observed_at": str((sell or {}).get("observed_at") or ""),
               "source_blocked": bool(sell and str(sell.get("source_id") or "") in blocked_sources),
               "note": ("最新の確定の売値では価格差が無いが、確定できない行（古い・店のトップなど）に買値を上回る高値の観測がある。"
                        "再確認すると差が出るかもしれない" if used_stale_high else "")}
        if buy is None or sell is None:
            row.update({"raw_spread": None, "known_costs": None, "known_cost_spread": None, "raw_net_spread": None,
                        "shipping_unknown": None,
                        "status": VERIFIED if pid in verified_pids else DISCOVERED,
                        "exclusion_reasons": reasons + [NO_BUY_SIDE if buy is None else NO_SELL_SIDE]})
            if pid in verified_pids:
                row["note"] = ("確定の関門は通過しているが、この表示用の買値・売値は読めなかった"
                               "（確定の判定は別のルートの価格を使うことがある）")
        else:
            spread = int(sell["price"]) - int(buy["price"])
            fee = _shipping_fee(pid, buy_url, int(buy["price"])) if route == RETAIL_TO_BUYBACK else None
            costs = pf.fixed_costs() + int(fee or 0)
            if fee is None:
                reasons.append(PURCHASE_SHIPPING_UNKNOWN)
            if spread > 0 and spread > int(buy["price"]) * ANOMALY_RATIO:
                reasons.append(PRICE_ANOMALY_SUSPECTED)
            net = spread - costs                  # 分かっている費用だけを引いた差（購入送料が不明なら純利益ではない）
            # raw_net_spread（純の差）は、購入送料が分かるときだけ。不明なときは null にして、純利益と誤認させない。
            # 判定（調査候補にするか）と優先度には、分かっている費用だけを引いた差 known_cost_spread を使う
            row.update({"raw_spread": spread, "known_costs": costs, "known_cost_spread": net,
                        "shipping_unknown": fee is None, "raw_net_spread": None if fee is None else net})
            if pid in verified_pids:
                row["status"] = VERIFIED
            elif spread <= 0:
                row["status"] = REJECTED
                reasons.append(NO_SPREAD)
            elif net <= 0:
                row["status"] = DISCOVERED
                reasons.append(NET_NEGATIVE)
            else:
                row["status"] = RESEARCH_CANDIDATE
            row["exclusion_reasons"] = reasons
        if row["status"] == VERIFIED:
            # 確定の関門を通った商品に残るのは参考情報だけ（在庫など）。外した理由は付けない
            row["exclusion_reasons"] = [r for r in row["exclusion_reasons"] if r in ADVISORY]
            if not row.get("note") and (buy is None or sell is None or sell is not None and sell_reasons):
                row["note"] = "確定の判定の価格と、この表示用の価格が違うことがある（確定の判定が正本）"
        row["exclusion_reasons"] = list(dict.fromkeys(row["exclusion_reasons"]))
        row["missing_requirements"] = [r for r in row["exclusion_reasons"] if r not in
                                       (NO_SPREAD, NET_NEGATIVE, NO_BUY_SIDE, NO_SELL_SIDE)]
        row["confidence"] = _confidence(row["exclusion_reasons"])
        score, why = priority_of(row)
        row["priority_score"], row["priority_reasons"] = score, why
        row["priority"] = _label(score, row["exclusion_reasons"])
        out.append(row)
    return out


def match_catalog(catalog: list[dict], products: list[dict], identity: dict) -> tuple[list[dict], list[dict]]:
    """買取の一覧（店の一覧ページの全行）から、正本と一致する行・一致しない行を分ける（買取起点の発見）。

    一致は商品の JAN（公式の確認の記録 IDENTITY_EVIDENCE の JAN と、商品の登録の jan_code）か、Apple の部品番号だけ。
    名前だけでは正本にしない（名前の一致は使わない）。一致しない行は DISCOVERED_PRODUCT_CANDIDATE として残す。
    """
    jan_of: dict[str, str] = {}
    for pid, ev in (identity or {}).items():
        for j in _jans_of(ev):
            jan_of[j] = pid
    parts_of: dict[str, str] = {}
    # 公式の確認の記録（IDENTITY_EVIDENCE）の部品番号の組・型番も照合に使う（商品の登録に part_numbers が無い商品がある）
    for pid, ev in (identity or {}).items():
        if isinstance(ev, dict):
            for sku in (ev.get("variant_skus") or {}):
                parts_of[str(sku)] = pid
            if ev.get("model_number"):
                parts_of.setdefault(str(ev["model_number"]), pid)
    for p in products:
        if p.get("jan"):
            jan_of.setdefault(str(p["jan"]), p["id"])
        for sku in p.get("part_numbers") or []:
            parts_of[str(sku)] = p["id"]
    matched, unmatched = [], []
    import re
    for r in catalog:
        pid = jan_of.get(str(r.get("jan") or ""))
        if not pid:
            found = re.findall(r"\b[A-Z0-9]{4,5}J/A\b", str(r.get("name") or ""))
            hit = {parts_of[f] for f in found if f in parts_of}
            pid = hit.pop() if len(hit) == 1 else ""
        (matched if pid else unmatched).append({**r, "canonical_product_id": pid})
    return matched, unmatched


def _jans_of(ev) -> list[str]:
    out = []
    if isinstance(ev, dict):
        for k in ("jan", "jan_code"):
            if ev.get(k):
                out.append(str(ev[k]))
        for c in (ev.get("colors") or {}).values() if isinstance(ev.get("colors"), dict) else []:
            if isinstance(c, dict) and c.get("jan"):
                out.append(str(c["jan"]))
            elif isinstance(c, str):
                out.append(c)
    return [j for j in out if j.isdigit() and len(j) == 13]


CATALOG_MAX_AGE_DAYS = 14


def _fresh_catalog_row(r: dict, now: datetime) -> bool:
    """買取の一覧の行が新しいか（取得した時刻が14日以内）。取れなくなったページの古い行を、新しい観測のように並べない。"""
    try:
        at = datetime.fromisoformat(str(r.get("observed_at") or "").replace(" JST", ""))
    except ValueError:
        return False
    if at.tzinfo is None and now.tzinfo is not None:
        at = at.replace(tzinfo=now.tzinfo)
    elif at.tzinfo is not None and now.tzinfo is None:
        at = at.replace(tzinfo=None)
    return timedelta(0) - timedelta(hours=1) <= now - at <= timedelta(days=CATALOG_MAX_AGE_DAYS)


def discovered_products(unmatched: list[dict], now: datetime) -> list[dict]:
    """買取の一覧にあるが正本に無い商品（DISCOVERED_PRODUCT_CANDIDATE）。正本には入れない（人が公式で確かめて登録する）。"""
    unmatched = [r for r in unmatched if _fresh_catalog_row(r, now)]
    rows = []
    for r in sorted(unmatched, key=lambda x: (-int(x.get("price") or 0), str(x.get("name") or "")))[:CATALOG_LIST_LIMIT]:
        key = f"{r.get('shop','')}|{r.get('jan') or r.get('name')}"
        rows.append({
            "candidate_id": "dp_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12],
            "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": DISCOVERED,
            "shop": r.get("shop", ""), "name": r.get("name", ""), "jan": r.get("jan", ""),
            "observed_sell_price": int(r.get("price") or 0), "source_url": r.get("url", ""),
            "observed_at": r.get("observed_at", ""),
            "missing_requirements": ["CANONICAL_UNREGISTERED", "OFFICIAL_PRICE_UNKNOWN", "IDENTITY_NOT_VERIFIED_BY_OFFICIAL"],
            "note": "買取の一覧に載っているが正本に無い。名前だけでは登録しない（公式で JAN・型番・価格を確かめる）"})
    return rows


# 台帳の snapshot に残す項目（見えなくなった候補を STALE として出すときに使う。これ以外は読まない）
SNAPSHOT_KEYS = ("product_identity", "route_type", "source", "observed_buy_price", "observed_sell_price",
                 "raw_spread", "known_cost_spread", "genre")
LEDGER_FRESH = "fresh"          # 台帳が無い（初回・キャッシュのミス・期限切れ）。初めて見た日は今日になる（実際の初見とは限らない）
LEDGER_RESTORED = "restored"    # 前回の台帳を引き継いだ
LEDGER_CORRUPT = "corrupt"      # 台帳が壊れていた（形が違う・読めない）。捨てて作り直した


def sanitize_ledger(prev) -> dict:
    """台帳の形を検証する。{candidate_id: {...}} の dict の、中身が dict の行だけを残す（壊れた台帳で落ちない）。"""
    if not isinstance(prev, dict):
        return {}
    return {str(k): v for k, v in prev.items() if isinstance(v, dict)}


def apply_ledger(candidates: list[dict], prev: dict, now: datetime) -> tuple[list[dict], dict]:
    """台帳で discovered_at / last_seen_at / status_since を付け、見えなくなった候補を STALE として残す。

    prev: {candidate_id: {"discovered_at", "last_seen_at", "status", "status_since", "snapshot"}}。戻りは (候補, 新しい台帳)。
    - discovered_at: 台帳で初めて見た日（台帳が無い日は今日になる。LEDGER_FRESH の報告では実際の初見と断定しない）
    - status_since: 今の状態になった日（調査候補になった日はここで分かる。毎日1行ずつ作られる REJECTED などの
      期間と区別するため、discovered_at とは別に持つ）
    """
    prev = sanitize_ledger(prev)
    stamp = now.isoformat(timespec="seconds")
    new_state: dict = {}
    seen = set()
    for c in candidates:
        cid = c["candidate_id"]
        old = prev.get(cid) or {}
        c["discovered_at"] = old.get("discovered_at") or stamp
        c["last_seen_at"] = stamp
        c["status_since"] = old.get("status_since") if old.get("status") == c.get("status") and old.get("status_since") else stamp
        seen.add(cid)
        new_state[cid] = {"discovered_at": c["discovered_at"], "last_seen_at": stamp, "status": c.get("status"),
                          "status_since": c["status_since"], "snapshot": {k: c.get(k) for k in SNAPSHOT_KEYS}}
    stale = []
    cutoff = now - timedelta(days=STALE_RETENTION_DAYS)
    for cid, old in prev.items():
        if cid in seen:
            continue
        try:
            last = datetime.fromisoformat(str(old.get("last_seen_at") or "").replace(" JST", ""))
        except ValueError:
            continue
        if last.tzinfo is None and now.tzinfo is not None:
            last = last.replace(tzinfo=now.tzinfo)
        elif last.tzinfo is not None and now.tzinfo is None:
            last = last.replace(tzinfo=None)
        if last < cutoff:
            continue
        snap_src = old.get("snapshot") if isinstance(old.get("snapshot"), dict) else {}
        snap = {k: snap_src.get(k) for k in SNAPSHOT_KEYS}            # 決まったキーだけ（台帳の値で状態・ID を上書きさせない）
        _s = lambda v: v if isinstance(v, str) else ""                # noqa: E731 - 日時は文字列だけ通す
        stale.append({**snap, "candidate_id": cid, "status": STALE, "discovered_at": _s(old.get("discovered_at")),
                      "last_seen_at": _s(old.get("last_seen_at")), "status_since": _s(old.get("status_since")),
                      "exclusion_reasons": ["NOT_SEEN_THIS_RUN"], "missing_requirements": ["NOT_SEEN_THIS_RUN"],
                      "confidence": "low", "priority_score": -100, "priority": "low", "priority_reasons": ["stale"]})
        new_state[cid] = old
    return candidates + stale, new_state


def coverage_metrics(*, products: list[dict], candidates: list[dict], product_candidates: list[dict],
                     msrp_evidence: dict, observations: list[dict], discovery: dict | None = None,
                     tcg: dict | None = None) -> dict:
    """新しい網羅性の指標（運営者向け）。件数は実データだけから数える。"""
    from src.market import price_evidence as pe
    from src.market import price_types as pt
    cnt = Counter(c["status"] for c in candidates)
    sell_ok = {o.get("product_id") for o in observations if o.get("price_role") == "sell"
               and not _sell_reasons(o) and isinstance(o.get("price"), (int, float)) and o["price"] > 0
               and (pt.canonical(o.get("canonical_price_type") or o.get("price_type")) == pt.BUYBACK_CASH)}
    sold_valid = sum(1 for o in observations if pt.canonical(o.get("canonical_price_type") or o.get("price_type")) == pt.SOLD
                     and pt.has_sold_evidence(o.get("item_url"), o.get("sold_at")))
    # 価格差が読めて正のものだけ（確定の関門を通過した商品でも、表示用の価格が読めない・価格差が正でないものは数えない）
    positive = [c for c in candidates if c["status"] in (RESEARCH_CANDIDATE, VERIFIED, DISCOVERED)
                and isinstance(c.get("raw_spread"), int) and c["raw_spread"] > 0]
    # 生の価格差が正のうち、確定の関門を通過したもの・通過していないもの（内訳が合計と一致する）
    verified_positive = [c for c in positive if c["status"] == VERIFIED]
    suppressed = [c for c in positive if c["status"] != VERIFIED]
    # 新商品の発見（Apple・TCG の公式の候補。exports/discovery/latest.json の metrics）。買取の一覧から見つけた分とは別に数える
    disc_n = int(((discovery or {}).get("metrics") or {}).get("product_candidates") or 0) if isinstance(discovery, dict) else 0
    # 買取の一覧から見つけた分と、Apple・TCG の公式の発見は同じ商品を指すことがあるので、足さず別々に出す
    return {
        "canonical_products": len(products),
        "discovered_products": len(product_candidates),
        "official_discovery_candidates": disc_n,
        "research_candidates": cnt.get(RESEARCH_CANDIDATE, 0),
        "verified_candidates": cnt.get(VERIFIED, 0),
        "suppressed_positive_spread": len(suppressed),
        "verified_positive_spread": len(verified_positive),
        "raw_positive_spread": len(positive),
        "official_verified_coverage": {"verified": sum(1 for p in products if pe.is_profit_eligible(msrp_evidence.get(p["id"], pe.UNKNOWN))),
                                       "total": len(products)},
        "buyback_exact_coverage": {"products_with_confirmed_sell": len(sell_ok & {p["id"] for p in products}),
                                   "total": len(products)},
        "marketplace_sold_coverage": {"valid_sold_rows": sold_valid},
        "tcg_source_coverage": (tcg or {}).get("source_coverage", {}),
        "tcg_active_events": (tcg or {}).get("active_events"),
        "tcg_msrp_verified": (tcg or {}).get("msrp_verified"),
        "tcg_source_candidates": (tcg or {}).get("source_candidates"),
        "by_status": dict(cnt),
    }


# 公開してはいけない項目（個別の候補の情報。公開の成果物のどこにも出さない）
PRIVATE_KEYS = frozenset({
    "candidate_id", "candidates", "product_identity", "product_id", "product_candidates", "observed_buy_price",
    "observed_sell_price", "raw_spread", "raw_net_spread", "known_cost_spread", "known_costs", "source_url",
    "source", "sell_observed_at", "missing_requirements", "exclusion_reasons", "priority_score", "priority_rank",
    "priority_reasons", "note", "name", "url", "jan", "shop", "rows"})


# 公開の集計に出してよい理由の語彙（商品名・価格などの個別の値がキーに混ざらないように、既知の語彙だけを通す）
ALLOWED_REASONS = frozenset({
    OFFICIAL_UNVERIFIED, OFFICIAL_NOT_SOLD, BUY_NOT_ITEM_LEVEL, BUY_STALE, SELL_STALE, GENERIC_SELL_URL, IDENTITY_UNCONFIRMED,
    CONDITION_UNKNOWN, CONDITION_MISMATCH, STOCK_UNKNOWN, SELL_SAMPLE_INSUFFICIENT, PURCHASE_SHIPPING_UNKNOWN,
    PRICE_ANOMALY_SUSPECTED, SELL_REJECTED, NET_NEGATIVE, NO_SELL_SIDE, NO_BUY_SIDE, NO_SPREAD})
ALLOWED_CONFIDENCE = frozenset({"high", "medium", "low"})
ALLOWED_STATUS = frozenset(STATUSES)
ALLOWED_LEDGER = frozenset({LEDGER_FRESH, LEDGER_RESTORED, LEDGER_CORRUPT})
# 件数の入れ子（キーも値も固定。上流の報告に項目が増えても、ここで通したものしか公開されない）
COVERAGE_KEYS = {
    "official_verified_coverage": ("verified", "total"),
    "buyback_exact_coverage": ("products_with_confirmed_sell", "total"),
    "marketplace_sold_coverage": ("valid_sold_rows",),
    "tcg_source_coverage": ("configured_sources", "implemented_collectors", "reachable_sources", "healthy_sources",
                            "blocked_sources", "unreachable_sources", "not_implemented_sources",
                            "sources_with_active_lottery", "lottery_events_found"),
}
TCG_CLASS_KEYS = ("WORKING", "IMPLEMENTED_BUT_BLOCKED", "ACCESSIBLE_UNIMPLEMENTED", "UNREACHABLE", "UNSUPPORTED")


def _count_dict(src, keys) -> dict:
    """許可したキーだけ、整数の値だけを通す（それ以外は捨てる）。"""
    src = src if isinstance(src, dict) else {}
    return {k: int(src[k]) for k in keys if isinstance(src.get(k), (int, float)) and not isinstance(src.get(k), bool)}


def _known_genres() -> frozenset:
    from src.content.ui import categories as cats
    return frozenset(k for k in cats.KEYS if k != cats.ALL) | {"other"}


def public_summary(report: dict) -> dict:
    """公開してよい集計（件数・理由別の件数・ジャンル別の件数・信頼度の分布・網羅性の指標）だけ。

    **許可リストで作る**（候補の行・商品名・候補の ID・価格・価格差・URL・売却先・商品ごとの理由・優先順位を一切コピーしない）。
    個別の候補は公開リポジトリ・公開ページに出さない（確定していない価格差を不特定多数に見せない。探索の成果を公開しない）。
    """
    cands = [c for c in report.get("candidates") or [] if isinstance(c, dict)]
    research = [c for c in cands if c.get("status") == RESEARCH_CANDIDATE]
    m = report.get("metrics") or {}
    counts = report.get("counts") or {}
    verified_n = int(counts.get("verified") or 0)
    out = {
        "schema": SCHEMA, "type": "RESEARCH_SUMMARY", "audience": "public_aggregate",
        "generated_at": report.get("generated_at"),
        "description": "調査候補の集計（件数だけ）。個別の候補（商品・価格・価格差・売却先）は公開しない。確定の利益ではない",
        "research_candidate_count": len(research),
        "positive_raw_spread_count": int(m.get("raw_positive_spread") or 0),
        # 生の価格差が正のうち、確定の関門を通過した数と通過していない数（足すと positive_raw_spread_count になる）
        "verified_positive_spread_count": int(m.get("verified_positive_spread") or 0),
        "suppressed_positive_spread_count": int(m.get("suppressed_positive_spread") or 0),
        "verified_count": verified_n,
        "ledger_state": report.get("ledger_state") if report.get("ledger_state") in ALLOWED_LEDGER else None,
        # 値（商品名・価格）がキーに混ざらないよう、既知の語彙だけを通す
        "status_counts": {k: int(v) for k, v in (m.get("by_status") or {}).items() if k in ALLOWED_STATUS},
        "reason_counts": {str(k): int(v) for k, v in (report.get("research_reasons") or {}).items() if k in ALLOWED_REASONS},
        "genre_counts": dict(Counter(g if g in _known_genres() else "other"
                                     for g in (str(c.get("genre") or "other") for c in research))),
        "confidence_counts": dict(Counter(c.get("confidence") for c in research if c.get("confidence") in ALLOWED_CONFIDENCE)),
        "official_verified_coverage": _count_dict(m.get("official_verified_coverage"), COVERAGE_KEYS["official_verified_coverage"]),
        "buyback_exact_coverage": _count_dict(m.get("buyback_exact_coverage"), COVERAGE_KEYS["buyback_exact_coverage"]),
        "marketplace_sold_coverage": _count_dict(m.get("marketplace_sold_coverage"), COVERAGE_KEYS["marketplace_sold_coverage"]),
        "canonical_products": int(m.get("canonical_products") or 0),
        "buyback_first": {k: int((report.get("buyback_first") or {}).get(k) or 0)
                          for k in ("catalog_rows", "canonical_matches", "new_product_candidates")},
        "official_discovery_candidates": int(m.get("official_discovery_candidates") or 0),
        "tcg_source_coverage": dict(_count_dict(m.get("tcg_source_coverage"), COVERAGE_KEYS["tcg_source_coverage"]),
                                    source_classes=_count_dict((m.get("tcg_source_coverage") or {}).get("source_classes"),
                                                               TCG_CLASS_KEYS)),
        "tcg_active_events": _int_or_none(m.get("tcg_active_events")),
        "tcg_msrp_verified": _int_or_none(m.get("tcg_msrp_verified")),
        "tcg_source_candidates": _int_or_none(m.get("tcg_source_candidates")),
    }
    leaked = find_private_keys(out)
    if leaked:                                   # 作り方の間違いで個別の情報が混ざったら、公開しない（出力を作らない）
        raise ValueError(f"公開の集計に個別の候補の項目が混ざっている: {sorted(leaked)}")
    return out


def _int_or_none(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def find_private_keys(obj, _path="") -> set[str]:
    """公開してはいけない項目名（PRIVATE_KEYS）が、入れ子も含めてどこかに使われていないか。"""
    found: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in PRIVATE_KEYS:
                found.add(f"{_path}{k}")
            found |= find_private_keys(v, f"{_path}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found |= find_private_keys(v, f"{_path}[{i}].")
    return found


def build(*, products: list[dict], observations: list[dict], msrp_evidence: dict, official_meta: dict,
          verified_pids: set[str], now: datetime, prev_state: dict | None = None,
          catalog: list[dict] | None = None, identity: dict | None = None, discovery: dict | None = None,
          tcg: dict | None = None, blocked_sources: set[str] | None = None,
          ledger_state: str | None = None) -> tuple[dict, dict]:
    """調査候補のレポート（運営者向け）と、次回の台帳。戻りは (report, new_state)。"""
    cands = build_candidates(products=products, observations=observations, msrp_evidence=msrp_evidence,
                             official_meta=official_meta, verified_pids=verified_pids, now=now,
                             blocked_sources=blocked_sources)
    prev_clean = sanitize_ledger(prev_state)
    if ledger_state is None:
        ledger_state = LEDGER_RESTORED if prev_clean else LEDGER_FRESH
    cands, new_state = apply_ledger(cands, prev_clean, now)
    order = {RESEARCH_CANDIDATE: 0, VERIFIED: 1, DISCOVERED: 2, STALE: 3, REJECTED: 4}
    cands.sort(key=lambda c: (order.get(c["status"], 9), -int(c.get("priority_score") or 0),
                              str((c.get("product_identity") or {}).get("product_id") or "")))
    for i, c in enumerate([c for c in cands if c["status"] == RESEARCH_CANDIDATE], 1):
        c["priority_rank"] = i
    matched, unmatched = match_catalog(catalog or [], products, identity or {})
    dps = discovered_products(unmatched, now)
    metrics = coverage_metrics(products=products, candidates=cands, product_candidates=dps,
                               msrp_evidence=msrp_evidence, observations=observations,
                               discovery=discovery, tcg=tcg)
    reasons = Counter(r for c in cands if c["status"] == RESEARCH_CANDIDATE for r in c["missing_requirements"])
    report = {
        "schema": SCHEMA, "type": "RESEARCH_CANDIDATES", "audience": "operator",
        "generated_at": now.isoformat(timespec="seconds"), "ledger_state": ledger_state,
        "note": "運営者向けの調査候補。確定の利益ではない。顧客向けの画面・LP・商品の通知には出さない（確認して VERIFIED に"
                "なるまで）。価格は観測した買値・売値だけ（予測は使わない）",
        "counts": {"research_candidates": metrics["research_candidates"], "verified": metrics["verified_candidates"],
                   "discovered": metrics["by_status"].get(DISCOVERED, 0), "rejected": metrics["by_status"].get(REJECTED, 0),
                   "stale": metrics["by_status"].get(STALE, 0)},
        "research_reasons": dict(reasons.most_common()),
        "candidates": cands,
        "buyback_first": {"catalog_rows": len(catalog or []), "canonical_matches": len(matched),
                          "new_product_candidates": len(unmatched), "listed": len(dps)},
        "product_candidates": dps,
        "metrics": metrics,
    }
    return report, new_state


def write_outputs(report: dict, state: dict, private_dir, public_dir) -> dict:
    """個別の候補・台帳は private_dir（.gitignore 済み）へ、公開してよい集計だけを public_dir/summary.json へ書く。

    集計を先に作る（個別の項目が混ざったら例外 → 何も書かない）。戻りは公開の集計。
    """
    import json
    from pathlib import Path
    summary = public_summary(report)
    priv, pub = Path(private_dir), Path(public_dir)
    priv.mkdir(parents=True, exist_ok=True)
    pub.mkdir(parents=True, exist_ok=True)
    (priv / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp = priv / "state.json.tmp"
    tmp.write_text(json.dumps({"schema": SCHEMA, "updated_at": report["generated_at"], "candidates": state},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(priv / "state.json")
    (pub / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
