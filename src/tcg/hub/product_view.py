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

import re
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
                                   "item_url": r.get("item_url"), "suspended": bool(r.get("suspended")), "suspended_text": r.get("suspended_text") or None,
                                   "accept_state": r.get("accept_state"), "executable": bool(r.get("executable")), "page_asof": r.get("page_asof")}
    return {"status": summary["status"], "unit": summary["unit"],
            "highest_listed": slim(summary["highest_listed"]), "highest_executable": slim(summary["highest_executable"]),
            "ranking": [slim(r) for r in summary["ranking"]], "shop_count": summary["shop_count"],
            "single_source": summary["single_source"], "outlier": slim(summary["outlier"]),
            "others": [slim(r) for r in summary.get("others") or []]}, pr


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


# ───────────────────────── 商品カード（利益候補と商品を (tcg, product_id) で 1 枚に統合） ─────────────────────────
_LOT_PHASE = {ls.L_WINNER_PURCHASE_PERIOD: 2, ls.L_RESULT_PENDING: 2, ls.L_WINNER_ANNOUNCED: 2, ls.L_CLOSED: 2}


def lottery_item(v: dict, eff: str) -> dict:
    """商品カードに渡す抽選 1 件。eff = 商品の件数に数えた状態（未確認・日程の食い違いの受付中/開始前は UNKNOWN）。
    応募ページの URL は、eff が応募できる側（開始前・受付中・締切間近）のときだけ渡す（応募後・終了後・未確認は新規応募できるように見せない）。"""
    ev = v["ev"]
    label = st.STATUS_LABEL[eff]
    if eff == ls.L_UNKNOWN and v["status"] in st.INTAKE:
        label = "未確認（公式で再確認待ち）"
    elif v["status"] == ls.L_WINNER_PURCHASE_PERIOD:
        label = "購入期間中（当選者のみ）"
    return {"lottery_id": v["lottery_id"], "shop": retailer_label(ev),
            "retailer": _s(ev.get("retailer")), "kind": v["entry_kind"],
            "status": v["status"], "eff_status": eff, "status_label": label, "winner_only": v["status"] == ls.L_WINNER_PURCHASE_PERIOD,
            "end": v["end"], "start": v["start"], "result": v["result"],
            "purchase_start": v["purchase_start"], "purchase_end": v["purchase_end"],
            "verified": v["verified"], "conflict": bool(ev.get("conflict")), "requirements": list(v["requirements"]),
            "eligibility_text": _s(ev.get("eligibility_text"))[:200] or None,
            "application_url": v["application_url"] if eff in st.INTAKE else None,
            "announcement_url": v["announcement_url"]}


def _lot_phase(i: dict):
    """並びの段階。0=受付中・締切間近 → 0.5=開始前 → 1=日程未確認・未確認（締切を断定できないので、先に見せる）→ 2=当選発表待ち・購入期間 → 3=その他。
    開始前は、受付中・締切間近より後ろに置く（開始前の締切は応募開始より先なので、締切順だけで混ぜると、いま応募できる抽選が表示から落ちる）。"""
    e = i["eff_status"]
    if e == ls.L_UNKNOWN:
        return 1
    if e in (ls.L_ENDING_SOON, ls.L_OPEN):
        return 0
    if e == ls.L_UPCOMING:
        return 0.5
    return _LOT_PHASE.get(e, 3)


_ENUM_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
RETAILER_UNKNOWN = "店舗不明"


def _is_enum_like(name: str, key: str = "") -> bool:
    """列挙値（大文字英字とアンダースコア・数字だけ。または retailer のキーと同じ文字列）。表示名には使わない。"""
    return bool(_ENUM_RE.match(name)) or (bool(key) and name == key)


def _registry_retailer(key: str) -> str:
    if not key:
        return ""
    try:
        from src.tcg.lottery.registry import SOURCE_BY_ID
        return _s((SOURCE_BY_ID.get(key) or {}).get("retailer"))
    except Exception:  # noqa: BLE001 — 登録簿が読めなくても表示は止めない
        return ""


def retailer_label(ev: dict, store: bool = True) -> str:
    """店・小売の表示名。列挙値（POKEMON_CENTER_ONLINE 等）をそのまま出さない。
    store=True: 店舗名 → 小売名 → 登録簿の日本語名。store=False（絞り込みの選択肢）: 店舗名を使わない。
    店舗名・小売名が列挙値（大文字英字とアンダースコアだけ、または retailer のキーと同じ）なら採用しない。日本語名が無ければ「店舗不明」。"""
    ev = ev if isinstance(ev, dict) else {}
    key = _s(ev.get("retailer"))
    cands = ([_s(ev.get("store_name"))] if store else []) + [_s(ev.get("retailer_name"))]
    cands = [n for n in cands if n and not _is_enum_like(n, key)]
    names = cands + [_registry_retailer(key)]
    return next((n for n in names if n), RETAILER_UNKNOWN if (store or key) else "")


def retailer_filter_label(key: str, evs: list) -> str:
    """絞り込みの選択肢の代表ラベル（同じ小売が複数の ev に現れても 1 つに固定）。登録簿の日本語名 → 列挙値でない小売名の最小 → 店舗不明。"""
    reg = _registry_retailer(_s(key))
    if reg:
        return reg
    names = sorted({retailer_label(e, store=False) for e in evs if _s(e.get("retailer")) == _s(key)} - {RETAILER_UNKNOWN, ""})
    return names[0] if names else RETAILER_UNKNOWN


def lottery_items(evs: list, statuses: list) -> list:
    """終了（ENDED）を除き、受付中・締切間近 → 開始前 → 日程未確認・未確認 → 結果待ち・購入期間 の順。同じ段階の中は締切が近い順。"""
    items = [lottery_item(v, e) for v, e in zip(evs, statuses) if v["status"] != ls.L_ENDED]
    items.sort(key=lambda i: (_lot_phase(i), i["end"].get("date") or "9999", i["end"].get("time") or "99"))
    return items


def _card_from(p: dict) -> dict:
    pr, bbv = p["profit"], p.get("buyback")
    st_ = opportunity_state(pr) if (bbv and bbv.get("status") == "EXECUTABLE" and bbv.get("highest_executable")) else None
    return {"key": (p["tcg"], p["product_id"]), "tcg": p["tcg"], "product_id": p["product_id"], "canonical": p["canonical"], "name": p["name"],
            "series": p.get("series"), "product_type": p.get("product_type"), "unit": (bbv or {}).get("unit"),
            "release_date": p.get("release_date"), "official_url": p.get("official_url"), "image_url": p.get("image_url"),
            "msrp": pr.get("msrp"), "pack_price": p.get("pack_price"), "profit": pr, "buyback": bbv, "state": st_,
            "state_label": OPP_LABEL.get(st_), "lottery_items": p.get("lottery_items") or [], "counts": p["counts"],
            "lottery_status": p["status"] if p["events"] else None, "has_events": bool(p["events"]), "in_products": True}


def _card_from_opp(o: dict) -> dict:
    zero = {"total": 0, "live": 0, "open": 0, "ending_soon": 0, "upcoming": 0, "today": 0, "result_pending": 0, "purchase_period": 0, "unknown": 0}
    return {"key": (o["tcg"], o["product_id"]), "tcg": o["tcg"], "product_id": o["product_id"], "canonical": o["canonical"], "name": o["name"],
            "series": None, "product_type": o.get("product_type"), "unit": o.get("unit"), "release_date": None,
            "official_url": o.get("official_url") or (o["msrp"] or {}).get("official_url"), "image_url": o.get("image_url"),
            "msrp": o["profit"].get("msrp"), "pack_price": None, "profit": o["profit"], "buyback": o["buyback"], "state": o["state"],
            "state_label": o["state_label"], "lottery_items": [], "counts": zero, "lottery_status": None, "has_events": False, "in_products": False}


def _card_sort_key(c: dict) -> tuple:
    net = c["profit"].get("net_profit")
    if net is not None:                                          # 1) 利益が計算できる商品（利益の大きい順）
        return (0, -net, -(c["profit"].get("roi_pct") or 0), c["name"])
    applying = [i for i in c["lottery_items"] if i["eff_status"] in st.APPLYING]
    if applying:                                                 # 2) 応募受付中・締切間近の抽選がある商品（締切が近い順）
        return (1, min(i["end"].get("date") or "9999" for i in applying), min(i["end"].get("time") or "99" for i in applying), c["name"])
    rel = c.get("release_date") or ""                            # 3) その他（発売日が新しい順。発売日不明は最後）
    return (2, "".join(chr(0x10FFFF - ord(ch)) for ch in rel) if rel else "\U0010ffff", "", c["name"])


_OPP_KEYS = ("msrp", "profit", "buyback", "state", "state_label", "unit")


def _merge_opp(card: dict, o: dict) -> dict:
    """抽選つき商品ブロックのカードに、同じキーの利益候補を統合する。利益・定価・買取・状態は利益候補（opp）側、抽選・画像・発売日などはブロック側。
    商品マスタに無い商品（ブロック側は定価を引けない）でも、利益候補を捨てない。"""
    oc = _card_from_opp(o)
    merged = {**card, **{k: oc[k] for k in _OPP_KEYS}}
    for k in ("product_type", "official_url", "image_url"):
        if not merged.get(k):
            merged[k] = oc.get(k)
    return merged


def _card_from_target(t: dict, m: dict, bbv: dict, pr: dict) -> dict:
    """買取のデータがあるのに商品ブロックも利益候補にもならない商品（定価なし・発売済み・抽選なし等）。利益は出さない（pr に net_profit が無ければ『算出前』）。"""
    zero = {"total": 0, "live": 0, "open": 0, "ending_soon": 0, "upcoming": 0, "today": 0, "result_pending": 0, "purchase_period": 0, "unknown": 0}
    pid = t["product_id"]
    st_ = opportunity_state(pr) if (bbv and bbv.get("status") == "EXECUTABLE" and bbv.get("highest_executable")) else None
    return {"key": (t["tcg"], pid), "tcg": t["tcg"], "product_id": pid, "canonical": C_MASTER if m else C_DISCOVERED,
            "name": _s(m.get("name")) or _s(t.get("name")) or pid, "series": _s(m.get("series_name")) or None,
            "product_type": _s(m.get("product_type")) or None, "unit": (bbv or {}).get("unit") or t.get("unit"),
            "release_date": _first_date(m.get("release_date")) if m else None,
            "official_url": _s(m.get("official_url")) or (pr.get("msrp") or {}).get("official_url"),
            "image_url": _s(m.get("official_image_url")) or None, "msrp": pr.get("msrp"), "pack_price": None,
            "profit": pr, "buyback": bbv, "state": st_, "state_label": OPP_LABEL.get(st_), "lottery_items": [], "counts": zero,
            "lottery_status": None, "has_events": False, "in_products": False}


def build_cards(products: list, opportunities: list, extras: Optional[list] = None) -> list:
    """1 商品 1 カード。キーは (tcg, product_id)。商品（抽選つき）と利益候補（抽選なしの商品を含む）を統合する。並びは _card_sort_key。
    同じキーに利益候補があれば、利益・定価・買取は利益候補を優先する（商品マスタに無い商品でも捨てない）。extras = 買取だけがある商品のカード（既に出ているキーは無視）。"""
    cards: dict = {}
    for p in products:
        cards[(p["tcg"], p["product_id"])] = _card_from(p)
    for o in opportunities:
        k = (o["tcg"], o["product_id"])
        if k not in cards:
            cards[k] = _card_from_opp(o)
        else:
            cards[k] = _merge_opp(cards[k], o)
    for c in extras or []:
        cards.setdefault(c["key"], c)
    return sorted(cards.values(), key=_card_sort_key)


O_CONDITIONAL = "CONDITIONAL"
CONDITIONAL_LABEL = "条件付き"


def build_retailer_opportunities(bb_cfg: dict, bb_rows: list, master: dict, msrp_rows: list, retailer_rows: list, now: datetime) -> tuple:
    """販売店の BOX 価格（台帳 config/tcg_retailer_box_prices.yaml）による条件付きの利益。(条件付きの利益候補, 参考・不採用の行) を返す。

    - 公式定価（msrp_for）がある商品は対象外（公式定価の候補は build_opportunities が扱う）。定価が無く PACK_PRICE_ONLY の商品だけ。
    - 条件付きになるのは、LOTTERY で応募期間中（OPEN）・商品マスタに product_id が一致・BOX 単位・販売店ページの BOX 価格の行だけ。
      利益は buyback.profit_for（FRESH で実行可能な最高買取・既存の経路の費用）をそのまま使う。算出できなければ候補にしない（参考の側に理由を出す）。
    - 応募終了・当選者のみ・期間外・不明の行は REFERENCE_ONLY。利益は出さない。product_id 不一致などは REJECTED。
    - executable は常に False。BUY / 購入推奨 / 今すぐ行動 / HOME には入らない（hub["retailer_opportunities"] は別のキー）。
    """
    from src.tcg import buyback as bb
    from src.tcg import retailer_box as rb
    targets = {(t.get("tcg"), t.get("product_id")): t for t in (bb_cfg or {}).get("targets") or [] if isinstance(t, dict)}
    out, refs = [], []
    for e in retailer_rows if isinstance(retailer_rows, list) else []:
        try:
            c = rb.classify(e, master, now)
            key = (c.get("tcg"), c.get("product_id"))
            m = _d(master.get(key))
            c["display_name"] = _s(m.get("name")) or None        # 参考欄の表示用（マスタに名前が無ければ None）
            if c["kind"] != "REJECTED" and pl.msrp_for(c["product_id"], c["tcg"], _s(m.get("product_type")) or None, msrp_rows):
                continue                                         # 公式定価がある商品は、公式定価の側で扱う（販売店価格で上書きしない）
            if c["kind"] != rb.K_CONDITIONAL:
                refs.append(c)
                continue
            t = targets.get(key)
            if not t:
                refs.append({**c, "kind": "REJECTED", "reason": "買取の調査対象（targets）に無い商品のため、利益を算出しない"})
                continue
            summary = bb.summarize_product(c["product_id"], bb_rows, bb_cfg, c["price_jpy"])
            calc = bb.profit_for(summary, {"retail_price": c["price_jpy"]}, bb_cfg)
            if summary.get("unit") and summary["unit"] != c["unit"]:
                calc = {"status": bb.NOT_CALCULATED, "reason": "買取の単位と販売店価格の単位が一致しない"}
            bbv, pr0 = _buyback_for(c["product_id"], bb_rows, bb_cfg, now, {"retail_price": c["price_jpy"]})
            pr = pl.profit_view(None, calc)
            if pr["status"] not in ("PROFITABLE", "NO_PROFIT") or not bbv or bbv["status"] != "EXECUTABLE" or not bbv.get("highest_executable"):
                refs.append({**c, "kind": "NOT_CALCULATED", "reason": pr.get("reason") or pl.PENDING_REASON})
                continue
            if pr.get("sell_shop"):
                pr["sell_shop_name"] = ((bb_cfg.get("shops") or {}).get(pr["sell_shop"]) or {}).get("name") or pr["sell_shop"]
            out.append({"tcg": c["tcg"], "product_id": c["product_id"], "canonical": C_MASTER,
                        "name": _s(m.get("name")) or _s(t.get("name")) or c["product_id"], "product_type": _s(m.get("product_type")) or None,
                        "unit": c["unit"], "image_url": _s(m.get("official_image_url")) or None, "official_url": _s(m.get("official_url")) or None,
                        "source_kind": rb.SOURCE_KIND, "conditional": True, "executable": False, "condition": rb.CONDITION_TEXT,
                        "retailer": c, "profit": pr, "buyback": bbv, "state": O_CONDITIONAL, "state_label": CONDITIONAL_LABEL})
        except Exception:  # noqa: BLE001 — 1 行の壊れたデータで全体を止めない（出さない側に倒す）
            continue
    out.sort(key=lambda o: (-o["profit"]["net_profit"], -o["profit"]["roi_pct"], o["name"]))
    return out, refs


def _buyback_only_cards(bb_cfg: dict, bb_rows: list, master: dict, msrp_rows: list, now: datetime, have: set) -> list:
    """買取の調査対象（targets）のうち、買取の行があるのに商品ブロックにも利益候補にもなっていない商品のカード（表示の漏れを防ぐ）。
    定価が無ければ利益は出さない（『公式定価が未確認のため利益は算出前』）。買取の行が無い商品は出さない。"""
    out = []
    for t in (bb_cfg or {}).get("targets") or []:
        try:
            key = (t["tcg"], t["product_id"])
            if key in have:
                continue
            m = _d(master.get(key))
            hit = pl.msrp_for(t["product_id"], t["tcg"], _s(m.get("product_type")) or None, msrp_rows)
            bbv, pr = _buyback_for(t["product_id"], bb_rows, bb_cfg, now, hit)
            if not bbv:
                continue
            out.append(_card_from_target(t, m, bbv, pr))
        except Exception:  # noqa: BLE001 — 1 商品の壊れたデータで全体を止めない
            continue
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


def _unbound_by_tcg(unbound: list) -> dict:
    """未紐付けの受付中（確認済み・日程の食い違いなし）を TCG 別に数える。TCG が読めない告知は "" に数える（どの TCG の商品カードでも案内を消さない側に倒す）。"""
    out: dict = {}
    for v in unbound:
        if v["status"] in st.APPLYING and v["verified"] and not v["ev"].get("conflict"):
            k = _s(v["ev"].get("tcg"))
            out[k] = out.get(k, 0) + 1
    return out


def build_hub(lotteries, registry, msrp, now: Optional[datetime] = None, buyback=None, retailer_rows=None) -> dict:
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
                       "result_pending": statuses.count(ls.L_RESULT_PENDING) + statuses.count(ls.L_CLOSED),
                       "purchase_period": statuses.count(ls.L_WINNER_PURCHASE_PERIOD),
                       "unknown": statuses.count(ls.L_UNKNOWN),         # 日程未確認・未確認・日程の食い違い（応募できると断定しない。受付中の数には入れない）
                       "today": sum(1 for v in evs if v["applicable_today"])},
            "lottery_items": lottery_items(evs, statuses),
            "priority": next((p for p in st.PRIORITY_ORDER if p in prios), None),
        })
    lottery_by_key = {(p["tcg"], p["product_id"]): {"status": p["status"], "label": st.STATUS_LABEL[p["status"]], "counts": p["counts"]}
                      for p in products if p["events"]}
    opportunities = build_opportunities(bb_cfg, bb_rows, master, msrp_rows, lottery_by_key, now) if bb_cfg else []
    cards = build_cards(products, opportunities, _buyback_only_cards(bb_cfg, bb_rows, master, msrp_rows, now,
                                                                     {(p["tcg"], p["product_id"]) for p in products}
                                                                     | {(o["tcg"], o["product_id"]) for o in opportunities}) if bb_cfg else [])
    retailer_errors: list = []
    if retailer_rows is None:                                    # collector が同じ取得で読んだ販売価格（優先）＋手動台帳（検証・フォールバック）。読めなければ空
        try:
            from src.tcg import retailer_box as _rb
            retailer_rows, retailer_errors = _rb.merge_rows(_rb.rows_from_events(_l(lot.get("items")), now), _rb.load_ledger(), now)
        except Exception:  # noqa: BLE001
            retailer_rows, retailer_errors = [], []
    names = {pid: _s(p.get("name")) for (_t, pid), p in master.items()}
    retailer_errors = [{**e, "display_name": names.get(e.get("product_id")) or None} for e in retailer_errors if isinstance(e, dict)]
    retailer_opps, retailer_refs = build_retailer_opportunities(bb_cfg, bb_rows, master, msrp_rows, retailer_rows, now) if bb_cfg else ([], [])
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
                            "label": _s(v["ev"].get("product_name")), "retailer": retailer_label(v["ev"], store=False),
                            "store": "" if _is_enum_like(_s(v["ev"].get("store_name")), _s(v["ev"].get("retailer"))) else _s(v["ev"].get("store_name")),
                            "verified": v["verified"]})
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
        # 商品に紐付いていない（「二種」等の告知）受付中の抽選。確認済み・日程の食い違いなしのものだけ（商品カードの「抽選なし」の誤読防止用。紐付けは推測しない）
        "unbound_applying": sum(1 for v in unbound if v["status"] in st.APPLYING and v["verified"] and not v["ev"].get("conflict")),
        "unbound_applying_by_tcg": _unbound_by_tcg(unbound),
        "bind_rate": (exact_n / len(views)) if views else None,
        "bind_rate_live": (sum(1 for v in live if v["canonical"] in (C_MASTER, C_DISCOVERED)) / len(live)) if live else None,
        "products": len(products), "products_with_events": sum(1 for p in products if p["events"]),
        "applying": sum(1 for v in views if v["status"] in st.APPLYING),         # 受付中 + 締切間近（表示用の合計。判定は変えない）
        "today": len(today_list), "deadline_today": len(deadline_today), "ending_soon": len(ending_soon), "upcoming": len(upcoming),
        "new": len(new), "calendar": len(cal), "skipped_malformed": skipped,
        "retailer_conditional": len(retailer_opps), "retailer_reference": len(retailer_refs),
        "cards": len(cards), "opportunities": len(opportunities), "opportunities_profit": sum(1 for o in opportunities if o["state"] == O_PROFIT),
        "opportunities_watch": sum(1 for o in opportunities if o["state"] == O_WATCH),
        "master": sum(1 for p in products if p["canonical"] == C_MASTER),
        "discovered": sum(1 for p in products if p["canonical"] == C_DISCOVERED),
    }
    return {"now": now.isoformat(), "today": today, "products": products, "opportunities": opportunities, "cards": cards,
            "retailer_opportunities": retailer_opps, "retailer_references": retailer_refs, "retailer_validation_errors": retailer_errors, "unbound": unbound, "events": views,
            "today_list": today_list, "deadline_today": deadline_today, "ending_soon": ending_soon,
            "upcoming": upcoming, "new": new, "calendar": cal, "stats": stats,
            "checked_at": {"lotteries_generated_at": _s(lot.get("generated_at")) or None,
                           "lotteries_evaluated_at": _s(lot.get("evaluated_at")) or None,
                           "msrp_generated_at": _s(ms.get("generated_at")) or None,
                           "registry_generated_at": _s(reg.get("generated_at")) or None}}
