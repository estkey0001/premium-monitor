# -*- coding: utf-8 -*-
"""TCG Lottery Hub: 商品中心のビュー（product → events → retailers → status → profit）を作る純関数。

- 入力は exports/tcg/ の公開済み JSON を読んだ辞書だけ（lotteries / pokemon_registry / msrp）。非公開の候補・.private は読まない。
- 商品に束ねるのは product_match が exact で product_id があるものだけ。partial / none / ambiguous / 欠損は束ねず `unbound` に出す
  （商品名が似ているだけで推測して結ばない）。紐付け率が低いこと自体を stats に出す。
- 商品マスタはポケカだけ（pokemon_registry）。ONE PIECE は商品マスタが無いので、exact で束ねられても商品名はイベントの名前だけ
  （発売日・定価・画像を作らない）。canonical: MASTER / DISCOVERED / AMBIGUOUS / UNMATCHED。
- 状態は now から導出し直す（status.live_status）。日付だけの項目は時刻を作らない。
- 入力が空・欠損・型違いでも例外にしない。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from src.tcg import action_url as au
from src.tcg.hub import profit_link as pl
from src.tcg.hub import status as st
from src.tcg.lottery import schema as ls
from src.tcg.models import JST, now_jst, parse_dt

C_MASTER, C_DISCOVERED, C_AMBIGUOUS, C_UNMATCHED = "MASTER", "DISCOVERED", "AMBIGUOUS", "UNMATCHED"
NEW_WINDOW_DAYS = 3          # 「新着」として出す、公式の告知の公開日からの日数（表示の窓。点数ではない）

# カレンダーの種類（並び順もこの順）
K_START, K_END, K_RESULT, K_PURCHASE_START, K_PURCHASE_END, K_RELEASE = (
    "START", "END", "RESULT", "PURCHASE_START", "PURCHASE_END", "RELEASE")
KIND_LABEL = {K_START: "応募開始", K_END: "応募締切", K_RESULT: "当選発表", K_PURCHASE_START: "購入期間 開始",
              K_PURCHASE_END: "購入期間 終了", K_RELEASE: "発売日"}
_KIND_ORDER = {k: i for i, k in enumerate(KIND_LABEL)}
_CAL_FIELDS = ((K_START, "application_start", "application_start_date"), (K_END, "application_end", "application_end_date"),
               (K_RESULT, "winner_announcement_at", "winner_announcement_date"),
               (K_PURCHASE_START, "purchase_start", "purchase_start_date"), (K_PURCHASE_END, "purchase_end", "purchase_end_date"))


def _d(x) -> dict:
    return x if isinstance(x, dict) else {}


def _l(x) -> list:
    return x if isinstance(x, list) else []


def _s(x) -> str:
    return x.strip() if isinstance(x, str) else ""


def when(ev: dict, key: str, date_key: str) -> dict:
    """項目の日時。時刻付きなら date + time、日付だけなら date のみ（00:00 等を作らない）。無ければ date=None。"""
    ev = _d(ev)
    exact = parse_dt(ev.get(key)) if isinstance(ev.get(key), str) else None
    if exact:
        return {"date": exact.strftime("%Y-%m-%d"), "time": exact.strftime("%H:%M"), "precision": "datetime"}
    raw = ev.get(date_key)
    d = parse_dt(raw) if isinstance(raw, str) else None
    if d:
        return {"date": d.strftime("%Y-%m-%d"), "time": None, "precision": "date"}
    return {"date": None, "time": None, "precision": None}


def official_announcement(ev: dict) -> Optional[str]:
    """告知（情報元）の URL。その取得元の公式ドメインの https だけ。無ければ作らない。"""
    ev = _d(ev)
    r = au.safe_https(ev.get("source_url"))
    if not r:
        return None
    host, url = r
    allowed = au.official_hosts(_s(ev.get("retailer")).upper())
    if any(host == h or host == "www." + h or host.endswith("." + h) for h in allowed):
        return url
    return None


def _safe_id(ev: dict) -> str:
    try:
        return ls.lottery_id_of(ev)
    except Exception:  # noqa: BLE001 — 型違いの項目があるイベントでも落とさない
        return ""


def _safe_kind(ev: dict) -> str:
    try:
        return ls.entry_kind(ev)
    except Exception:  # noqa: BLE001
        return "LOTTERY"


def _event_view(ev: dict, now: datetime, bound_exact: bool) -> dict:
    status = st.live_status(ev, now)
    try:
        cls = au.classify(ev, now)
    except Exception:  # noqa: BLE001
        cls = {"application_url": None, "channel": au.CH_UNKNOWN, "requirements": [], "quality": au.Q_PARTIAL}
    return {
        "ev": ev,
        "lottery_id": _s(ev.get("lottery_id")) or _safe_id(ev),
        "status": status, "status_label": st.STATUS_LABEL[status],
        "applicable_today": st.is_applicable_today(ev, now),
        "priority": st.priority_of_event(ev, now, bound_exact=bound_exact),
        "verified": ev.get("verified") is True,
        "application_url": cls.get("application_url"),       # 検証済みの公式の応募 URL だけ（entry_url が無ければ None）
        "announcement_url": official_announcement(ev),
        "channel": cls.get("channel"), "requirements": list(cls.get("requirements") or []),
        "entry_kind": _safe_kind(ev),
        "start": when(ev, "application_start", "application_start_date"),
        "end": when(ev, "application_end", "application_end_date"),
        "result": when(ev, "winner_announcement_at", "winner_announcement_date"),
        "purchase_start": when(ev, "purchase_start", "purchase_start_date"),
        "purchase_end": when(ev, "purchase_end", "purchase_end_date"),
    }


def _bind_state(ev: dict) -> tuple[str, Optional[str]]:
    """('exact', product_id) か (canonical 状態, None)。exact でも product_id が無ければ束ねない。"""
    m = _s(ev.get("product_match"))
    pid = _s(ev.get("product_id"))
    if m == "exact" and pid:
        return "exact", pid
    return (C_AMBIGUOUS if m == "ambiguous" else C_UNMATCHED), None


def _sort_key(v: dict) -> tuple:
    """既存の並び順（ls.sort_key）。型違いの日付が混ざっても比較で落ちないよう文字列にそろえる。"""
    try:
        a, b = ls.sort_key({**v["ev"], "status": v["status"]})
        return a, str(b)
    except Exception:  # noqa: BLE001
        return 99, ""


def _first_date(v) -> Optional[str]:
    d = parse_dt(v) if isinstance(v, str) else None
    return d.strftime("%Y-%m-%d") if d else None


def _buyback_for(product_id: str, bb_rows: list, bb_cfg: dict, now: datetime, msrp_hit: Optional[dict]) -> tuple[Optional[dict], dict]:
    """(買取の表示用の要約 or None, 利益欄)。買取は src/tcg/buyback.py の規則（JAN で同一性・単位・条件・鮮度）を通ったものだけ。"""
    from src.tcg import buyback as bb
    summary = bb.summarize_product(product_id, bb_rows, bb_cfg, (msrp_hit or {}).get("retail_price"))
    pr = pl.profit_view(msrp_hit, bb.profit_for(summary, msrp_hit, bb_cfg))
    if pr.get("sell_shop"):
        pr["sell_shop_name"] = ((bb_cfg.get("shops") or {}).get(pr["sell_shop"]) or {}).get("name") or pr["sell_shop"]
    if summary["status"] == "NO_BUYBACK":
        return None, pr

    def slim(r):
        return None if not r else {"shop": r["shop"], "shop_name": ((bb_cfg.get("shops") or {}).get(r["shop"]) or {}).get("name") or r["shop"],
                                   "price": r["price"], "unit": r.get("unit"), "condition": r.get("condition"),
                                   "freshness": r.get("freshness"), "checked_at": r.get("observed_at"),
                                   "source_updated_at": r.get("source_updated_at"), "source_url": r.get("source_url"),
                                   "item_url": r.get("item_url"), "suspended": bool(r.get("suspended")), "suspended_text": r.get("suspended_text") or None}
    return {"status": summary["status"], "unit": summary["unit"],
            "highest_listed": slim(summary["highest_listed"]), "highest_executable": slim(summary["highest_executable"]),
            "ranking": [slim(r) for r in summary["ranking"]], "shop_count": summary["shop_count"],
            "single_source": summary["single_source"], "outlier": slim(summary["outlier"])}, pr


# 利益候補の判定（新しい閾値は作らない。黒字の線は既存の BUY NOW の基準 scoring.BUY_NOW_MIN_PREMIUM_PERCENT をそのまま使う）
O_PROFIT, O_WATCH = "PROFIT", "WATCH"
OPP_LABEL = {O_PROFIT: "黒字", O_WATCH: "様子見"}          # 「確認待ち」は表示時に価格の鮮度が切れたときだけ（JS）。ここでは作らない
_OPP_ORDER = {O_PROFIT: 0, O_WATCH: 1}


def opportunity_state(profit: dict) -> Optional[str]:
    """黒字 = 純利益が正で ROI が既存の BUY NOW の基準以上。様子見 = 黒字でも ROI がそれ未満、または赤字。算出できていなければ None。"""
    from src.tcg.scoring import BUY_NOW_MIN_PREMIUM_PERCENT as T
    if not isinstance(profit, dict) or not isinstance(profit.get("net_profit"), int) or not isinstance(profit.get("roi_pct"), (int, float)):
        return None
    return O_PROFIT if (profit["net_profit"] > 0 and profit["roi_pct"] >= T) else O_WATCH


def build_opportunities(bb_cfg: dict, bb_rows: list, master: dict, msrp_rows: list, lottery_by_key: dict, now: datetime) -> list:
    """抽選の有無に関係なく、いま利益が計算できる商品。条件（すべて）: 公式の定価（同じ単位）／実行可能な最高買取／鮮度 FRESH／同一性 CONFIRMED（JAN）／
    単位・条件の確認（実行可能の条件）／外れ値・確認待ちでない。利益は Route T1（buyback.profit_for）の結果をそのまま使う。
    並び: 状態（黒字 → 様子見）→ 純利益 → ROI。"""
    out = []
    for t in (bb_cfg or {}).get("targets") or []:
        try:
            key = (t["tcg"], t["product_id"])
            m = _d(master.get(key))
            hit = pl.msrp_for(t["product_id"], t["tcg"], _s(m.get("product_type")) or None, msrp_rows)
            if not hit:
                continue
            bbv, pr = _buyback_for(t["product_id"], bb_rows, bb_cfg, now, hit)
            state = opportunity_state(pr)
            if not bbv or bbv["status"] != "EXECUTABLE" or not bbv.get("highest_executable") or state is None:
                continue                                # 外れ値（OUTLIER_REVIEW）・掲載のみ・買取なしは候補に入れない
            lot = lottery_by_key.get(key)
            out.append({"tcg": t["tcg"], "product_id": t["product_id"], "canonical": C_MASTER if m else C_DISCOVERED,
                        "name": _s(m.get("name")) or _s(t.get("name")) or t["product_id"],
                        "product_type": _s(m.get("product_type")) or None, "unit": bbv.get("unit") or t.get("unit"),
                        "image_url": _s(m.get("official_image_url")) or None, "official_url": _s(m.get("official_url")) or None,
                        "msrp": hit, "profit": pr, "buyback": bbv, "state": state, "state_label": OPP_LABEL[state],
                        "lottery": lot})                 # lot が None = 現在確認できる抽選なし（利益機会が無いという意味ではない）
        except Exception:  # noqa: BLE001 — 1 商品の壊れたデータで全体を止めない（出さない側に倒す）
            continue
    out.sort(key=lambda o: (_OPP_ORDER[o["state"]], -o["profit"]["net_profit"], -o["profit"]["roi_pct"], o["name"]))
    return out


def profit_map(registry, msrp, buyback, now: Optional[datetime] = None) -> dict:
    """{(tcg, product_id): 利益欄}。HOME が「利益根拠あり」を出すための軽い版（build_hub と同じ規則: _buyback_for）。"""
    now = (now or now_jst()).astimezone(JST)
    out: dict = {}
    try:
        from src.tcg import buyback as bb
        cfg = bb.load_config()
        rows = bb.annotate([r for r in _l(_d(buyback).get("rows")) if isinstance(r, dict)], cfg, now)
        master = {(p.get("tcg"), p.get("product_id")): p for p in _l(_d(registry).get("products")) if isinstance(p, dict)}
        msrp_rows = _l(_d(msrp).get("verified"))
        for t in cfg.get("targets") or []:
            m = _d(master.get((t["tcg"], t["product_id"])))
            hit = pl.msrp_for(t["product_id"], t["tcg"], _s(m.get("product_type")) or None, msrp_rows) if m else None
            out[(t["tcg"], t["product_id"])] = _buyback_for(t["product_id"], rows, cfg, now, hit)[1]
    except Exception:  # noqa: BLE001 — 読めなければ空（利益根拠は出さない）
        return {}
    return out


def build_hub(lotteries, registry, msrp, now: Optional[datetime] = None, buyback=None) -> dict:
    """商品中心のビュー全体。lotteries / registry / msrp / buyback は公開済み JSON を読んだ辞書（壊れていても空として扱う）。"""
    now = (now or now_jst()).astimezone(JST)
    today = now.strftime("%Y-%m-%d")
    lot, reg, ms = _d(lotteries), _d(registry), _d(msrp)
    bb_rows: list = []
    bb_cfg: dict = {}
    try:
        from src.tcg import buyback as _bb
        bb_cfg = _bb.load_config()
        bb_rows = _bb.annotate([r for r in _l(_d(buyback).get("rows")) if isinstance(r, dict)], bb_cfg, now)    # 鮮度は今の時刻で付け直す
    except Exception:  # noqa: BLE001 — 買取の読み込みに失敗しても、抽選のページは出す（買取は「未確認」になる）
        bb_rows, bb_cfg = [], {}
    master = {}
    for p in _l(reg.get("products")):
        if isinstance(p, dict) and _s(p.get("product_id")) and _s(p.get("tcg")):
            master[(p["tcg"], p["product_id"])] = p
    msrp_rows = _l(ms.get("verified"))

    blocks: dict[tuple, dict] = {}
    unbound: list[dict] = []
    views: list[dict] = []
    skipped = 0
    for raw in _l(lot.get("items")):
        if not isinstance(raw, dict):
            continue
        if any(raw.get(k) is not None and not isinstance(raw.get(k), str)        # 文字列であるべき項目が型違い: その 1 件だけ捨てる（ページ全体を落とさない）
               for k in ("tcg", "retailer", "retailer_name", "store_name", "prefecture", "product_name", "product_id", "source_url", "source_type")):
            skipped += 1
            continue
        kind, pid = _bind_state(raw)
        v = _event_view(raw, now, bound_exact=(kind == "exact"))
        views.append(v)
        if kind != "exact":
            v["canonical"] = kind
            unbound.append(v)
            continue
        key = (_s(raw.get("tcg")), pid)
        b = blocks.get(key)
        if b is None:
            m = master.get(key)
            b = blocks[key] = {"key": key, "tcg": key[0], "product_id": pid, "canonical": C_MASTER if m else C_DISCOVERED,
                               "master": m, "events": []}
        v["canonical"] = b["canonical"]
        b["events"].append(v)
    # 商品マスタにあり、発売前（または抽選が見つかっている）商品はブロックを作る（抽選が無ければ「確認できている抽選なし」と出す）
    for key, m in master.items():
        if key not in blocks and (_first_date(m.get("release_date")) or "0000") >= today:
            blocks[key] = {"key": key, "tcg": key[0], "product_id": key[1], "canonical": C_MASTER, "master": m, "events": []}

    products = []
    for b in blocks.values():
        m = _d(b["master"])
        evs = sorted(b["events"], key=_sort_key)
        # 未確認（verified でない）・日程の食い違いの抽選は、商品の集約状態と「受付中」等の件数に数えない（応募できると見せない）
        statuses = [(v["status"] if (v["verified"] and not v["ev"].get("conflict")) or v["status"] not in st.INTAKE else ls.L_UNKNOWN)
                    for v in evs]
        name = _s(m.get("name")) or next((_s(v["ev"].get("product_name")) for v in evs if _s(v["ev"].get("product_name"))), b["product_id"])
        msrp_hit = pl.msrp_for(b["product_id"], b["tcg"], _s(m.get("product_type")) or None, msrp_rows) if m else None
        prios = [v["priority"] for v in evs if v["priority"]]
        bbv = _buyback_for(b["product_id"], bb_rows, bb_cfg, now, msrp_hit) if bb_cfg else (None, pl.profit_view(msrp_hit))
        products.append({
            "tcg": b["tcg"], "product_id": b["product_id"], "canonical": b["canonical"], "name": name,
            "series": _s(m.get("series_name")) or None, "product_type": _s(m.get("product_type")) or None,
            "release_date": _first_date(m.get("release_date")) if m else None,       # ONE PIECE（マスタ無し）は作らない
            "official_url": _s(m.get("official_url")) or None,
            "image_url": _s(m.get("official_image_url")) or None,        # 表示専用（ポケカの公式一覧にある画像の URL。検査は描画側）
            "profit": bbv[1],
            "buyback": bbv[0],                                     # 買取店自身のページの価格だけ（JAN で同一性・単位・条件・鮮度を確認したもの）
            "pack_price": (m.get("pack_price") if isinstance(m.get("pack_price"), int) and not isinstance(m.get("pack_price"), bool)
                           and m.get("pack_price") > 0 and _s(m.get("retail_price_basis")) == "pack" else None),     # 1 パックの公式価格（BOX の定価ではない）
            "events": evs, "status": st.aggregate_status(statuses),
            "counts": {"total": len(evs), "live": sum(1 for s in statuses if s != ls.L_ENDED),
                       "open": statuses.count(ls.L_OPEN), "ending_soon": statuses.count(ls.L_ENDING_SOON),
                       "upcoming": statuses.count(ls.L_UPCOMING),
                       "today": sum(1 for v in evs if v["applicable_today"])},
            "priority": next((p for p in st.PRIORITY_ORDER if p in prios), None),
        })
    lottery_by_key = {(p["tcg"], p["product_id"]): {"status": p["status"], "label": st.STATUS_LABEL[p["status"]], "counts": p["counts"]}
                      for p in products if p["events"]}
    opportunities = build_opportunities(bb_cfg, bb_rows, master, msrp_rows, lottery_by_key, now) if bb_cfg else []
    order = {s: i for i, s in enumerate(st._AGG_ORDER)}
    products.sort(key=lambda p: (order.get(p["status"], 99) if p["events"] else 98, p["release_date"] or "9999", p["name"]))

    today_list = sorted((v for v in views if v["applicable_today"]), key=lambda v: (v["end"]["date"] or "9999", v["end"]["time"] or "99"))
    deadline_today = [v for v in today_list if v["end"]["date"] == today]
    ending_soon = [v for v in views if v["status"] == ls.L_ENDING_SOON and not v["ev"].get("conflict")]
    upcoming = sorted((v for v in views if v["status"] == ls.L_UPCOMING), key=lambda v: (v["start"]["date"] or "9999", v["start"]["time"] or ""))
    new = []
    for v in views:
        pub = _first_date(v["ev"].get("published_at"))
        official = _s(v["ev"].get("source_type")) in ls.OFFICIAL_LOTTERY_SOURCES
        if (pub and official and v["status"] in (ls.L_UPCOMING, ls.L_OPEN, ls.L_ENDING_SOON)         # 応募が済んだ・終わった抽選は新着にしない
                and (now - timedelta(days=NEW_WINDOW_DAYS)).strftime("%Y-%m-%d") <= pub <= today):
            new.append((pub, v))
    new = [v for _p, v in sorted(new, key=lambda t: t[0], reverse=True)]

    cal = []
    for v in views:
        if v["status"] == ls.L_ENDED:
            continue
        for kind, k, dk in _CAL_FIELDS:
            w = when(v["ev"], k, dk)
            if w["date"] and w["date"] >= today:
                cal.append({"date": w["date"], "time": w["time"], "kind": kind, "lottery_id": v["lottery_id"],
                            "label": _s(v["ev"].get("product_name")), "retailer": _s(v["ev"].get("retailer_name")) or _s(v["ev"].get("retailer")),
                            "store": _s(v["ev"].get("store_name")), "verified": v["verified"]})
    for p in products:
        if p["release_date"] and p["release_date"] >= today:
            cal.append({"date": p["release_date"], "time": None, "kind": K_RELEASE, "lottery_id": None, "label": p["name"],
                        "retailer": "", "store": "", "verified": True})
    cal.sort(key=lambda c: (c["date"], _KIND_ORDER[c["kind"]], c["time"] or ""))

    live = [v for v in views if v["status"] != ls.L_ENDED]
    exact_n = len(views) - len(unbound)
    stats = {
        "events_total": len(views), "events_live": len(live),
        "bound_exact": exact_n, "unbound": len(unbound),
        "bind_rate": (exact_n / len(views)) if views else None,
        "bind_rate_live": (sum(1 for v in live if v["canonical"] in (C_MASTER, C_DISCOVERED)) / len(live)) if live else None,
        "products": len(products), "products_with_events": sum(1 for p in products if p["events"]),
        "applying": sum(1 for v in views if v["status"] in st.APPLYING),         # 受付中 + 締切間近（表示用の合計。判定は変えない）
        "today": len(today_list), "deadline_today": len(deadline_today), "ending_soon": len(ending_soon), "upcoming": len(upcoming),
        "new": len(new), "calendar": len(cal), "skipped_malformed": skipped,
        "opportunities": len(opportunities), "opportunities_profit": sum(1 for o in opportunities if o["state"] == O_PROFIT),
        "opportunities_watch": sum(1 for o in opportunities if o["state"] == O_WATCH),
        "master": sum(1 for p in products if p["canonical"] == C_MASTER),
        "discovered": sum(1 for p in products if p["canonical"] == C_DISCOVERED),
    }
    return {"now": now.isoformat(), "today": today, "products": products, "opportunities": opportunities, "unbound": unbound, "events": views,
            "today_list": today_list, "deadline_today": deadline_today, "ending_soon": ending_soon,
            "upcoming": upcoming, "new": new, "calendar": cal, "stats": stats,
            "checked_at": {"lotteries_generated_at": _s(lot.get("generated_at")) or None,
                           "lotteries_evaluated_at": _s(lot.get("evaluated_at")) or None,
                           "msrp_generated_at": _s(ms.get("generated_at")) or None,
                           "registry_generated_at": _s(reg.get("generated_at")) or None}}
