"""利益商品（OpportunityView）の内部診断。

「なぜ利益商品が0件なのか」を、商品ごとの大量ログではなく理由別の件数で出す（運営者向け。一般の画面には出さない）。
掲載の判定は src/content/ui/opportunity.py の eligibility() だけが正本で、ここでは判定をし直さない。
判定に進めなかった候補（定価で買って買取店に売る案件が作られなかった商品）だけ、元データから理由を読む。

候補（candidate）の定義:
- RETAIL_TO_BUYBACK: 有効な商品（products）1件 = 1候補。公式の定価で買って、現金買取に売る
- それ以外のルート: profit_routes の main_routes 由来の OpportunityView（仕入れの種別と売値の種別で分ける）

理由（reason）の語彙と、判定理由（opportunity.eligibility）との対応は REASON_OF を参照。
1つの候補に理由が複数あるときは、exclusion_reasons にはすべて数え、primary_reasons には FUNNEL の先頭だけ数える。

注意（近似）: 案件が作られなかった商品の理由は正規化データから読むので、掲載判定と完全には一致しない。
- 「買取が古い」は正規化データの freshness_basis（STALE_DAYS）で見る（掲載判定は確認から14日）
- 定価も新しい現金買取もあるのに案件が無いものは、まとめて no_profit（既存の計算で純利益0以下）に入れる
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from src.market import price_evidence as pe
from src.market import price_types as pt

# 漏斗の順（先に当たったものを主な理由にする）
FUNNEL = ("no_buy_price", "unverified_buy_price", "no_sell_price", "invalid_identity", "stale_buyback",
          "unknown_type", "no_sold_period", "insufficient_sold_samples", "missing_costs", "no_profit", "other")

# opportunity.eligibility の理由 → 診断の理由
REASON_OF = {
    "invalid_buy_price": "no_buy_price",
    "buy_configured_reference": "unverified_buy_price", "buy_unknown": "unverified_buy_price",
    "buy_stale": "unverified_buy_price", "stale_buy_price": "unverified_buy_price",
    "invalid_sell_price": "no_sell_price",
    "sell_identity_unverified": "invalid_identity",   # 売却側の買取価格の商品照合が未了（Phase 6.1）
    "stale_sell_price": "stale_buyback",
    "costs_unknown": "missing_costs",
    "purchase_shipping_unknown": "missing_costs",     # 公式の購入送料を一次情報で確認していない
    "no_profit": "no_profit",
}

ROUTE_TYPE_OF_KIND = {"official_to_buyback": "RETAIL_TO_BUYBACK", "shop_to_buyback": "SECONDARY_TO_BUYBACK"}

# 取得元ごとの必要な更新頻度の目安（Task 24/25。本番のスケジュールはここでは変えない）
FREQUENCY = {
    "retail": {"recommended": "週1回〜価格改定の告知時", "current": "日次CI（公式 collector）+ 人の確認（確認日付き）",
               "assessment": "十分。ただし価格改定・世代交代は人の確認でしか拾えていない（2026-10-03 に4件の改定・交代を検出）"},
    "buyback": {"recommended": "1日2〜4回", "current": "日次CI 1回（12:00 JST）",
                "assessment": "14日の鮮度条件には足りる。急変を拾うには不足（1日1回では当日の値動きを反映できない）"},
    "stock": {"recommended": "30分〜数時間ごと", "current": "日次CI 1回（公式 collector。在庫表示が取れるのは一部）",
              "assessment": "不足。在庫は7日で在庫未確認に戻るので表示は安全だが、「今買える」を出せる頻度ではない"},
    "lottery_restock": {"recommended": "15〜60分ごと", "current": "日次CI 1回",
                        "assessment": "不足。在庫再開・抽選開始はより短い周期が必要（Phase 3 で検討）"},
}


def _reason(raw: str, view=None) -> str:
    if raw in REASON_OF:
        return REASON_OF[raw]
    if raw.startswith("sell_type_") or raw.startswith("buy_type_"):
        return "unknown_type"
    if raw == "insufficient_sold_samples":
        n = getattr(view, "sell_samples", None)
        enough = isinstance(n, int) and n >= pt.MIN_SOLD_SAMPLES
        return "no_sold_period" if enough else "insufficient_sold_samples"
    return "other"


def _primary(reasons) -> str:
    for r in FUNNEL:
        if r in reasons:
            return r
    return "other"


def _route_type(v) -> str:
    if v.kind in ROUTE_TYPE_OF_KIND:
        return ROUTE_TYPE_OF_KIND[v.kind]
    # 売値が成約中央値: 仕入れが定価・販売価格（新品）なら RETAIL、中古・フリマなら SECONDARY
    return "RETAIL_TO_SOLD_MEDIAN" if v.buy_price_type == pt.RETAIL and "新品" in (v.buy_price_label or "") \
        else "SECONDARY_TO_SOLD_MEDIAN"


def _cash_rows(obs: list[dict], pid: str) -> list[dict]:
    return [o for o in obs if o.get("product_id") == pid and o.get("price_role") == "sell"
            and o.get("price_type") in ("buyback_price", "trade_in_price")]


def _data_reasons(pid: str, evidence: str, obs: list[dict]) -> list[str]:
    """定価で買って買取に売る案件が作られなかった商品の、元データから読める理由。"""
    out = []
    if evidence == pe.UNKNOWN:
        out.append("no_buy_price")
    elif not pe.is_profit_eligible(evidence):
        out.append("unverified_buy_price")
    rows = [o for o in _cash_rows(obs, pid) if (o.get("price") or 0) > 0]
    cash = [o for o in rows if o.get("canonical_price_type") == pt.BUYBACK_CASH]
    if not rows:
        out.append("no_sell_price")
    elif not cash:
        out.append("unknown_type")          # 下取り（TRADE_IN）しか無い。下取りは現金買取として使わない
    else:
        good = [o for o in cash if not o.get("wrong_model_flag") and not o.get("accessory_flag")]
        if not good:
            out.append("invalid_identity")
        elif not any(o.get("freshness_basis") == "observed" for o in good):
            out.append("stale_buyback")
    if not out:
        # 定価は確認済み・新しい現金買取もあるのに案件が無い = 既存の計算で純利益が0以下
        out.append("no_profit")
    return out


def _stock_state(p: dict, now: datetime) -> tuple[str, bool]:
    """商品の公式在庫の状態（opportunity と同じ規則）と、根拠の日時が無いのに「在庫あり」と書かれているか。"""
    from src.content.ui import opportunity as opp
    sale = "lottery" if p.get("is_lottery") else ""
    raw = opp.stock_from(p.get("official_stock_status") or "", sale)
    at = p.get("official_stock_observed_at") or ""
    unsupported = raw == "IN_STOCK" and not at
    if raw in ("IN_STOCK", "OUT_OF_STOCK"):
        age = opp._age_days(at, now)
        if age is None or age > pe.CURRENT_DAYS or age < -1:
            raw = "UNKNOWN"
    return raw, unsupported


def _event_key(a, product_id: str = "") -> str:
    """抽選・予約・先着の受付の識別（商品 ID と、受付の開始・締切）。同じ商品の別の受付を別の通知にする。

    受付期間は正本（actionability.event_availability）と同じ項目から読み、時刻に直してから並べる（書式の違い・
    商品コードの有無だけで別の受付にしない。監査 L-1）。
    """
    from src.market.actionability import _dt
    ev = getattr(a, "event", None) or {}
    if not ev:
        return ""

    def _norm(v):
        d = _dt(v)
        return d.isoformat(timespec="minutes") if d is not None else str(v or "").strip()
    return "|".join((str(product_id or ev.get("product_id") or "").strip(),
                     _norm(ev.get("application_start") or ev.get("entry_start_at")),
                     _norm(ev.get("application_end") or ev.get("entry_end_at"))))


def _actionability_summary(opportunity_set, actionable: list[dict], prev_actionable: list | None) -> dict:
    """確定の利益案件のうち、今すぐ行動できるもの・できない理由ごとの件数・前回から行動できるようになった商品（Phase 18）。

    newly_actionable は前回の診断で行動できなかった商品だけ（同じ状態では毎回出さない。通知の候補）。
    prev_actionable が None（前回の診断が無い・読めない）のときは基準日として空にする。
    """
    rows, seen = [], set()
    # 商品ごとに1件（行動できる案件があればそれを、無ければ最初の案件を数える。actionable の数え方と揃える。レビュー L1）
    for v in sorted(opportunity_set.eligible, key=lambda x: not getattr(x, "actionable", False)):
        a = getattr(v, "action", None)
        if a is None or v.product_id in seen:
            continue
        seen.add(v.product_id)
        rows.append({"product_id": v.product_id, "product": getattr(v, "product_name", "") or v.product_id,
                     "availability": a.availability,
                     "label": a.label, "actionable": a.actionable, "reasons": list(a.reasons),
                     "deadline": a.deadline, "checked_at": a.checked_at,
                     # Phase 19: 通知の候補に使う値（判定・利益はここで作り直さず、案件と正本の結果のまま）
                     "confirmed": True, "net_profit": getattr(v, "net_profit", None), "roi": getattr(v, "roi", None),
                     "cta_label": a.cta_label, "cta_url": a.cta_url, "until_ms": a.until_ms,
                     "event_key": _event_key(a, v.product_id)})
    def _n(*rs):
        return sum(1 for r in rows if not r["actionable"] and any(x in r["reasons"] for x in rs))
    now_ids = {a["product_id"] for a in actionable}
    prev_ids = None if prev_actionable is None else {
        str(x.get("product_id") if isinstance(x, dict) else x) for x in prev_actionable}
    return {"confirmed_profitable": len(rows), "actionable": len(now_ids),
            "blocked_by_stock": _n("stock_out", "stock_unknown"),
            "blocked_by_closed_lottery": _n("lottery_closed", "preorder_closed", "first_come_closed",
                                            "winner_only_period"),
            "blocked_by_stale_availability": _n("availability_stale"),
            "blocked_by_unknown_schedule": _n("lottery_deadline_unknown", "lottery_not_open", "lottery_status_conflict",
                                              "lottery_evidence_stale"),
            "blocked_by_sale_ended": _n("sale_ended"),
            "blocked_by_missing_url": _n("missing_action_url"),
            "products": rows,
            "newly_actionable": [] if prev_ids is None else sorted(now_ids - prev_ids)}


def _camera_summary(products: list[dict], observations: list[dict], candidates: list[dict],
                    actionable: list[dict]) -> dict:
    """カメラの買取の網羅（Phase 17。判定はやり直さない: 確定の売値は normalized_prices.sell_confirmation_reasons、
    状態の系統は opportunity._cond_family、利益は候補の判定、行動できるかは actionable の結果）。"""
    from src.content.ui.opportunity import _cond_family
    from src.market.normalized_prices import sell_confirmation_reasons
    cams = {p["id"] for p in products if p.get("genre") == "camera"}
    rows = [o for o in observations if o.get("product_id") in cams and o.get("price_role") == "sell"
            and o.get("canonical_price_type") == pt.BUYBACK_CASH and (o.get("price") or 0) > 0]
    new = [o for o in rows if _cond_family(o.get("condition")) == "new"]
    confirmed = [o for o in rows if not sell_confirmation_reasons(o)]
    best: dict[str, dict] = {}
    for o in confirmed:
        if o["price"] > best.get(o["product_id"], {}).get("price", 0):
            best[o["product_id"]] = {"product_id": o["product_id"], "price": o["price"],
                                     "source": o.get("source_name") or "", "observed_at": o.get("observed_at") or "",
                                     "condition": o.get("condition") or ""}
    return {"products": len(cams),
            "fresh_new": sum(1 for o in new if o.get("is_fresh")),
            "stale_new": sum(1 for o in new if not o.get("is_fresh")),
            "used_reference": len(rows) - len(new),
            "confirmed_sells": len(confirmed),
            "confirmed_products": sorted(best.values(), key=lambda r: r["product_id"]),
            "profitable": sum(1 for c in candidates if c["product_id"] in cams and c["eligible"]),
            "actionable": sum(1 for a in actionable if a.get("product_id") in cams)}


# 「今すぐ行動できる」に数える利益案件の種類（opportunity.AVAILABILITY_OF の値。抽選は受付中か分からないので数えない）
# 利益案件の種類（opportunity.AVAILABILITY_OF）のうち、行動できる候補の種類。Phase 18 から「今すぐ行動できる」の
# 判定の正本は src/market/actionability（期限 3時間・抽選の受付期間・公式の URL も見る）。これは種類の目安として残す
ACTIONABLE_AVAILABILITY = frozenset({"BUY_NOW", "RESERVATION"})


def build(*, products: list[dict], msrp_evidence: dict, official_meta: dict, observations: list[dict],
          opportunity_set, home_count: int, list_count: int, sold_exports: dict | None, now: datetime,
          prev_actionable: list | None = None) -> dict:
    from src.content.ui import categories as cats

    views_by_pid: dict[str, list] = defaultdict(list)
    for v in list(opportunity_set.eligible) + list(opportunity_set.ineligible):
        views_by_pid[v.product_id].append(v)

    candidates = []
    # ── RETAIL_TO_BUYBACK（商品1件 = 1候補）──
    for p in products:
        pid = p["id"]
        cat = cats.from_genre(p.get("genre") or "")
        deal_views = [v for v in views_by_pid.get(pid, []) if v.kind == "official_to_buyback"]
        if any(v.eligible for v in deal_views):
            reasons = []
        elif deal_views:
            reasons = sorted({_reason(r, v) for v in deal_views for r in v.reasons})
        else:
            reasons = _data_reasons(pid, msrp_evidence.get(pid, pe.UNKNOWN), observations)
        candidates.append({"product_id": pid, "category": cat, "route_type": "RETAIL_TO_BUYBACK",
                           "eligible": not reasons, "reasons": reasons})
    # ── それ以外のルート（profit_routes 由来）──
    for v in list(opportunity_set.eligible) + list(opportunity_set.ineligible):
        if v.kind == "official_to_buyback":
            continue
        candidates.append({"product_id": v.product_id, "category": v.category, "route_type": _route_type(v),
                           "eligible": bool(v.eligible),
                           "reasons": sorted({_reason(r, v) for r in v.reasons})})

    excl, primary = Counter(), Counter()
    by_cat: dict[str, dict] = {k: {"candidates": 0, "eligible": 0, "reasons": Counter()} for k in cats.KEYS
                               if k != cats.ALL}
    route_types: dict[str, Counter] = defaultdict(Counter)
    for c in candidates:
        cat = by_cat.setdefault(c["category"], {"candidates": 0, "eligible": 0, "reasons": Counter()})
        cat["candidates"] += 1
        route_types[c["route_type"]]["candidates"] += 1
        if c["eligible"]:
            cat["eligible"] += 1
            route_types[c["route_type"]]["eligible"] += 1
            continue
        for r in c["reasons"]:
            excl[r] += 1
        pr = _primary(c["reasons"])
        primary[pr] += 1
        cat["reasons"][pr] += 1

    # ── 定価（仕入れ値）の監査 ──
    retail_rows, retail_summary = [], Counter()
    for p in products:
        pid = p["id"]
        ev = msrp_evidence.get(pid, pe.UNKNOWN)
        meta = official_meta.get(pid, {})
        if pe.is_profit_eligible(ev):
            action = "VERIFIED"
        elif meta.get("official_not_sold"):
            action = "KEEP_AS_REFERENCE"     # 公式で販売終了・後継機に交代（今その値段で公式から買えない）
        elif meta.get("open_price"):
            action = "KEEP_AS_REFERENCE"     # オープン価格（公式の定価が無い）
        else:
            action = "VERIFY_FROM_OFFICIAL"
        retail_summary[{"VERIFIED_CURRENT": "verified", "VERIFIED_DATED": "verified",
                        "CONFIGURED_REFERENCE": "reference", "STALE": "stale"}.get(ev, "unknown")] += 1
        if meta.get("official_not_sold"):
            retail_summary["sale_ended"] += 1        # 上の区分とは別に数える（公式で販売終了。Phase 14）
        retail_rows.append({
            "product_id": pid, "product": p.get("name", ""), "evidence": ev, "action": action,
            "official_not_sold": bool(meta.get("official_not_sold")),
            "price": p.get("official_price") or p.get("retail_price"),
            "price_type": "RETAIL" if p.get("official_price") else "CONFIGURED_REFERENCE",
            "source": p.get("official_price_source") or meta.get("source_id") or "config/products.yaml",
            "verified_at": p.get("official_price_updated_at") or "",
            "url": meta.get("url") or "", "note": meta.get("reason") or meta.get("note") or "",
        })

    # ── 買取（売り先）の鮮度 ──
    src: dict[str, Counter] = defaultdict(Counter)
    last_ok: dict[str, str] = {}
    usable_products = set()
    for o in observations:
        if o.get("price_type") not in ("buyback_price", "trade_in_price"):
            continue
        s = o.get("source_name") or o.get("source_id") or "?"
        src[s]["rows"] += 1
        if not (o.get("price") or 0) > 0:
            src[s]["failed"] += 1
            continue
        if o.get("freshness_basis") == "observed":
            src[s]["fresh"] += 1
            if o.get("canonical_price_type") == pt.BUYBACK_CASH:
                usable_products.add(o.get("product_id"))
        else:
            src[s]["stale"] += 1
        if (o.get("observed_at") or "") > last_ok.get(s, ""):
            last_ok[s] = o.get("observed_at") or ""
    buyback_sources = [{"source": s, **dict(c), "last_observed": last_ok.get(s, "")} for s, c in sorted(src.items())]

    # ── 成約（SOLD）の状態 ──
    sold = {}
    for name, d in (sold_exports or {}).items():
        items = []
        for prod in ((d or {}).get("products") or {}).values():
            items.extend(prod.get("items") or [])
        valid = sum(1 for it in items if pt.has_sold_evidence(it.get("item_url") or it.get("url"), it.get("sold_at")))
        sold[name] = {"rows": len(items), "valid_sold": valid, "policy": (d or {}).get("policy", "")}
    sold_obs = [o for o in observations if o.get("canonical_price_type") == pt.SOLD]
    sold["ebay"] = {"rows": len(sold_obs),
                    "valid_sold": sum(1 for o in sold_obs if pt.has_sold_evidence(o.get("item_url"), o.get("sold_at")))}
    median = {"eligible": sum(1 for o in observations if o.get("sold_median_eligible")),
              "missing_period": sum(1 for o in observations if o.get("canonical_price_type") == pt.SOLD
                                    and not (o.get("sold_period_start") and o.get("sold_period_end"))),
              "insufficient_samples": sum(1 for o in observations if o.get("canonical_price_type") == pt.SOLD
                                          and not (isinstance(o.get("sample_count"), int)
                                                   and o["sample_count"] >= pt.MIN_SOLD_SAMPLES))}

    # ── 在庫 ──
    stock, unsupported = Counter(), []
    for p in products:
        st, bad = _stock_state(p, now)
        stock[st] += 1
        if bad:
            unsupported.append(p["id"])

    eligible_n = sum(1 for c in candidates if c["eligible"])
    # 今すぐ行動できる確定の利益商品（Phase 14）: 掲載できる利益に加えて、今買える（在庫ありの明示・7日以内）か
    # 予約の根拠があるものだけ。利益だけでは数えない（在庫未確認・在庫切れ・抽選は数えない）。掲載の判定は変えない
    # 商品ごとに1件（1つの商品に確定の案件が複数あっても1と数える）
    # Phase 18: 判定は src/market/actionability（opportunity.build が付けた v.action）だけ。通常販売は在庫ありを確認して
    # から3時間以内・抽選/予約/先着は受付中（公式の確認が7日以内）・公式の購入/申込のページの URL がそろうものだけ
    actionable, _seen_act = [], set()
    for v in opportunity_set.eligible:
        if getattr(v, "actionable", False) and v.product_id not in _seen_act:
            _seen_act.add(v.product_id)
            a = v.action
            actionable.append({"product_id": v.product_id, "availability": a.availability,
                               "deadline": a.deadline, "checked_at": a.checked_at, "cta_label": a.cta_label})
    actionability = _actionability_summary(opportunity_set, actionable, prev_actionable)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "note": "内部用（運営者向け）。一般の画面には出さない。掲載の判定は opportunity.eligibility が正本",
        "candidate_count": len(candidates),
        "eligible_count": eligible_n,
        "exclusion_reasons": dict(excl.most_common()),
        "primary_reasons": dict(primary.most_common()),
        # 候補ごとの外した理由（運営者向けのページで商品ごとにたどるため。UI Phase 9）
        "candidates": [{"product_id": c["product_id"], "route_type": c["route_type"], "reasons": c["reasons"],
                        "primary": _primary(c["reasons"])} for c in candidates if not c["eligible"]],
        "stock_excluded": 0,   # 在庫は除外の理由にしない（利益あり・在庫未確認として出す）
        "category_counts": {k: {"candidates": v["candidates"], "eligible": v["eligible"],
                                "primary_reasons": dict(v["reasons"].most_common())} for k, v in by_cat.items()},
        "route_types": {k: dict(v) for k, v in sorted(route_types.items())},
        "home_parity": {"home": home_count, "list": list_count, "eligible": eligible_n,
                        "ok": home_count == list_count == len(opportunity_set.eligible)},
        "retail_prices": {"summary": dict(retail_summary), "products": retail_rows},
        "buyback": {"fresh_rows": sum(c["fresh"] for c in src.values()),
                    "stale_rows": sum(c["stale"] for c in src.values()),
                    "failed_rows": sum(c["failed"] for c in src.values()),
                    "failed_sources": sorted(s for s, c in src.items() if not c["fresh"] and not c["stale"]),
                    "usable_products": len(usable_products), "sources": buyback_sources},
        "sold": sold, "sold_median": median,
        # Phase 17: カメラの売る側（新品の買取・中古の参考・確定の売値）と利益・今すぐ行動できる商品
        "camera": _camera_summary(products, observations, candidates, actionable),
        "actionability": actionability,
        "stock": {"states": dict(stock), "in_stock_without_evidence": unsupported},
        "actionable": {"count": len(actionable), "products": actionable,
                       "note": "確定の利益 ＋ 今の購入の経路（公式の購入・申込のページ）＋ 今の購入の可否の証拠"
                               "（在庫ありの確認から3時間以内・抽選/予約/先着の受付中）がそろうものだけ"
                               "（src/market/actionability）"},
        "frequency": FREQUENCY,
    }
