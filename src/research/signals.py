"""利益が出やすい市場のシグナル（Coverage Wave 5: Profit-Dense Priority Model）。

調べる順番を決めるための**根拠つきの目印**だけを作る。AI の予測価格は使わない。確定（VERIFIED）にも、行動可能（actionable）にもしない。
どのシグナルも、根拠が無ければ付けない（推測しない）:

- 発売からの経過（release）: 公式で確かめた発売日があるときだけ。無ければ UNKNOWN（加点しない）
- 限定・特別（limited）: 公式の販売ページ・公式の商品名に、その語があるときだけ。買取店の名前・自分の推測では付けない
- 供給の逼迫（supply）: 公式で在庫なし・抽選のみ・再販の告知・短い応募期間。在庫が不明（UNKNOWN）は逼迫と見なさない
- 買取の勢い（buyback）: 前回の観測より上がった（前回があるときだけ）・同じ品目の中央値より小売に近い・小売に近い
- 価格差が正（positive_spread）: 同一性つきで小売の価格を引けたもの

個別の候補のシグナルは非公開（.private）。公開してよいのは件数だけ（`counts`）。
"""
from __future__ import annotations

from datetime import datetime
from statistics import median

# 発売からの経過
REL_NEW, REL_RECENT, REL_ESTABLISHED, REL_UPCOMING, REL_UNKNOWN = "NEW", "RECENT", "ESTABLISHED", "UPCOMING", "UNKNOWN"
RELEASE_NEW_DAYS = 30
RELEASE_RECENT_DAYS = 90

# 供給のシグナル
SUP_OUT_OF_STOCK = "OUT_OF_STOCK"
SUP_MULTI_UNAVAILABLE = "MULTI_SOURCE_UNAVAILABLE"
SUP_LOTTERY_ONLY = "LOTTERY_ONLY"
SUP_RESTOCK = "RESTOCK_ANNOUNCED"
SUP_SHORT_WINDOW = "SHORT_APPLICATION_WINDOW"
SUPPLY_SIGNALS = (SUP_OUT_OF_STOCK, SUP_MULTI_UNAVAILABLE, SUP_LOTTERY_ONLY, SUP_RESTOCK, SUP_SHORT_WINDOW)
SHORT_WINDOW_HOURS = 48

# 買取のシグナル
BUY_RISING, BUY_ABOVE_MEDIAN, BUY_NEAR_RETAIL = "RISING", "ABOVE_CATEGORY_MEDIAN", "NEAR_RETAIL"
BUYBACK_SIGNALS = (BUY_RISING, BUY_ABOVE_MEDIAN, BUY_NEAR_RETAIL)
RISING_MIN_RATIO = 1.03          # 前回より 3% 以上上がったとき
NEAR_RETAIL_RATIO = 0.95         # 買取の価格が小売の価格の 95% 以上（小売の価格 = 同一性つきで引けた現金の仕入れ値）
MEDIAN_MIN_SAMPLES = 3

# 限定・特別（公式の名前・ページに、この語があるときだけ）。値は「何の限定か」の分類
LIMITED_WORDS = (("数量限定", "limited"), ("期間限定", "limited"), ("限定", "limited"), ("Limited", "limited"),
                 ("Special Edition", "special"), ("スペシャル", "special"), ("特別", "special"), ("Special", "special"),
                 ("アニバーサリー", "anniversary"), ("Anniversary", "anniversary"), ("周年", "anniversary"), ("記念", "anniversary"),
                 ("CELEBRATION", "anniversary"), ("エクスクルーシブ", "exclusive"), ("Exclusive", "exclusive"),
                 ("コラボ", "collaboration"), ("Collaboration", "collaboration"))

# 点を付けない行の理由（誤価格・条件つきの値引き・識別が部分的・上限超え・急変・裏付け不足）
SUSPICIOUS_REASONS = frozenset({"PRICE_ANOMALY_SUSPECTED", "ACQUISITION_CONDITIONAL", "IDENTITY_PARTIAL", "ABOVE_GENRE_MAX",
                                "NEEDS_CORROBORATION", "PRICE_SPIKE", "SELL_REJECTED"})

# 点（調べる順番を決めるためだけの決まった点。価格差の予測ではない）
POINTS = {"release_new": 15, "release_recent": 8, "limited": 10, "supply": 8, "supply_cap": 16, "buyback_rising": 10,
          "near_retail": 5, "above_median": 5, "positive_spread": 20, "tcg_active": 6, "tcg_deadline": 6}


def _parse(value, now: datetime):
    s = str(value or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None and now.tzinfo is not None:
        d = d.replace(tzinfo=now.tzinfo)
    elif d.tzinfo is not None and now.tzinfo is None:
        d = d.replace(tzinfo=None)
    return d


def release_signal(release_date, now: datetime) -> dict:
    """公式で確かめた発売日から、発売からの経過を出す。読めない・無い発売日は UNKNOWN（推測しない・加点しない）。"""
    d = _parse(release_date, now)
    if d is None:
        return {"release_state": REL_UNKNOWN, "days_since_release": None}
    days = (now - d).days
    if now < d:
        return {"release_state": REL_UPCOMING, "days_since_release": None}
    state = REL_NEW if days <= RELEASE_NEW_DAYS else REL_RECENT if days <= RELEASE_RECENT_DAYS else REL_ESTABLISHED
    return {"release_state": state, "days_since_release": days}


def limited_signal(*, official_name: str = "", official_url: str = "", official: bool = False) -> dict:
    """公式の名前・ページに限定・特別の語があるときだけ、その種類を返す。official が偽・URL が無いなら付けない（名前だけの推測をしない）。"""
    name = str(official_name or "")
    if not (official and str(official_url or "").startswith("https://") and name):
        return {"limited": False, "limited_kind": "", "limited_evidence": ""}
    for word, kind in LIMITED_WORDS:
        if word in name:
            return {"limited": True, "limited_kind": kind, "limited_evidence": word}
    return {"limited": False, "limited_kind": "", "limited_evidence": ""}


def supply_signals(*, availability: str = "", official: bool = False, unavailable_sources: int = 0,
                   event_type: str = "", application_hours: float | None = None, lottery_active: bool = False) -> list[str]:
    """供給の逼迫の目印。在庫が不明（UNKNOWN・空）は逼迫と見なさない。公式でない取得元の在庫なしは単独では数えない。"""
    out: list[str] = []
    if official and availability == "OUT_OF_STOCK":
        out.append(SUP_OUT_OF_STOCK)
    if unavailable_sources >= 2:
        out.append(SUP_MULTI_UNAVAILABLE)
    if lottery_active and event_type in ("LOTTERY", ""):
        out.append(SUP_LOTTERY_ONLY)
    if event_type == "RESTOCK":
        out.append(SUP_RESTOCK)
    if isinstance(application_hours, (int, float)) and 0 < application_hours <= SHORT_WINDOW_HOURS:
        out.append(SUP_SHORT_WINDOW)
    return out


def category_medians(rows: list[dict]) -> dict[str, float]:
    """品目ごとの「買取 ÷ 小売」の中央値。標本が少ない品目は出さない（少数の値を基準にしない）。"""
    by: dict[str, list[float]] = {}
    for r in rows:
        ratio = buyback_ratio(r)
        if ratio is not None:
            by.setdefault(str(r.get("category") or ""), []).append(ratio)
    return {k: median(v) for k, v in by.items() if k and len(v) >= MEDIAN_MIN_SAMPLES}


def buyback_ratio(r: dict):
    sell, retail = r.get("observed_sell_price"), r.get("retail_price")
    if isinstance(sell, int) and isinstance(retail, int) and not isinstance(sell, bool) and retail > 0 and sell > 0:
        return sell / retail
    return None


def buyback_signals(r: dict, *, prev_sell: int | None = None, medians: dict | None = None) -> list[str]:
    """買取の勢い。前回の観測が無い（prev_sell が None）なら RISING は付けない。小売の価格が無ければ他の 2 つも付けない。
    価格差の疑い（誤価格・条件つきの値引き）の行には付けない（疑わしい価格を勢いに見せない）。"""
    if r.get("suspicious") or r.get("retail_conditions"):
        return []
    out: list[str] = []
    sell = r.get("observed_sell_price")
    if isinstance(prev_sell, int) and isinstance(sell, int) and prev_sell > 0 and sell >= prev_sell * RISING_MIN_RATIO:
        out.append(BUY_RISING)
    ratio = buyback_ratio(r)
    if ratio is not None:
        med = (medians or {}).get(str(r.get("category") or ""))
        if med is not None and ratio > med:
            out.append(BUY_ABOVE_MEDIAN)
        if ratio >= NEAR_RETAIL_RATIO:
            out.append(BUY_NEAR_RETAIL)
    return out


def profit_density(*, release: dict | None = None, limited: dict | None = None, supply: list[str] | None = None,
                   buyback: list[str] | None = None, positive_spread: bool = False, suspicious: bool = False) -> dict:
    """シグナルから、調べる順番のための点と内訳を出す。suspicious（誤価格の疑い）は点を 0 にする。
    この点は並べ替えにだけ使う。状態（VERIFIED・actionable）は変えない。"""
    if suspicious:
        return {"signal_points": 0, "signal_reasons": ["suspicious_no_boost"]}
    pts, why = 0, []

    def add(key: str, label: str, points: int | None = None) -> None:
        nonlocal pts
        n = POINTS[key] if points is None else points
        pts += n
        why.append(f"{label}+{n}")
    st = (release or {}).get("release_state")
    if st == REL_NEW:
        add("release_new", "release_new")
    elif st == REL_RECENT:
        add("release_recent", "release_recent")
    if (limited or {}).get("limited"):
        add("limited", "limited")
    sp = min(len(supply or []) * POINTS["supply"], POINTS["supply_cap"])
    if sp:
        add("supply", "supply", sp)
    b = buyback or []
    for key, name in ((BUY_RISING, "buyback_rising"), (BUY_NEAR_RETAIL, "near_retail"), (BUY_ABOVE_MEDIAN, "above_median")):
        if key in b:
            add(name, name)
    if positive_spread:
        add("positive_spread", "positive_spread")
    return {"signal_points": pts, "signal_reasons": why}


def annotate_buyback_rows(rows: list[dict], now: datetime, *, prev_sell_of=None) -> dict:
    """買取起点の候補（triage 済みの行）に、シグナルと点を付ける。件数（公開してよい集計）を返す。

    行に必要な項目: category（triage）・observed_sell_price・retail_price（照会で引けたときだけ）・retail_availability・
    retail_source_type・retail_url・identity_evidence の matched_name・status・missing_requirements。
    prev_sell_of(row) -> 前回の買取の価格 | None（前回の観測が無ければ None）。
    """
    medians = category_medians([{**r, "category": (r.get("triage") or {}).get("category", "")} for r in rows])
    counts = {"new_release_candidates": 0, "limited_candidates": 0, "supply_pressure_candidates": 0,
              "buyback_rising_candidates": 0, "positive_spread_candidates": 0, "stock_unknown_not_counted": 0}
    for r in rows:
        tri = r.get("triage") or {}
        reqs = set(r.get("missing_requirements") or [])
        # 調べる価値のある行（HIGH / MEDIUM・価格差が無いと分かった行でない・買取の観測が新しい）だけにシグナルを付ける
        if r.get("status") == "REJECTED" or tri.get("tier") not in ("HIGH", "MEDIUM") or tri.get("currentness") != "fresh":
            r.update({"release": {"release_state": REL_UNKNOWN, "days_since_release": None}, "limited_signal": {"limited": False, "limited_kind": "", "limited_evidence": ""},
                      "supply_signals": [], "buyback_signals": [], "signal_points": 0, "signal_reasons": ["not_eligible"]})
            continue
        official = r.get("retail_source_type") == "OFFICIAL_DIRECT"
        ev = r.get("retail_identity_evidence") or {}
        suspicious = bool(reqs & SUSPICIOUS_REASONS)
        avail = str(r.get("retail_availability") or "")
        r["release"] = release_signal(r.get("release_date"), now)          # 買取店の行に発売日は無い（UNKNOWN）。公式の発売日があるときだけ入る
        r["limited_signal"] = limited_signal(official_name=ev.get("matched_name", ""), official_url=r.get("retail_url", ""), official=official)
        sup = supply_signals(availability=avail, official=official, unavailable_sources=int(r.get("retail_unavailable_sources") or 0))
        r["supply_signals"] = sup
        if avail in ("", "UNKNOWN") and r.get("retail_price") is not None:
            counts["stock_unknown_not_counted"] += 1
        prev = prev_sell_of(r) if prev_sell_of else None
        row_for_b = {**r, "category": (r.get("triage") or {}).get("category", ""), "suspicious": suspicious}
        bb = buyback_signals(row_for_b, prev_sell=prev, medians=medians)
        r["buyback_signals"] = bb
        positive = bool(r.get("status") == "RESEARCH_CANDIDATE" and isinstance(r.get("raw_spread_hint"), int) and r["raw_spread_hint"] > 0
                        and r.get("retail_basis") == "retail_lookup" and not r.get("retail_conditions") and not (reqs & {"IDENTITY_PARTIAL", "BUY_STALE"}))
        d = profit_density(release=r["release"], limited=r["limited_signal"], supply=sup, buyback=bb, positive_spread=positive, suspicious=suspicious)
        r.update(d)
        counts["new_release_candidates"] += int(r["release"]["release_state"] == REL_NEW)
        counts["limited_candidates"] += int(r["limited_signal"]["limited"])
        counts["supply_pressure_candidates"] += int(bool(sup))
        counts["buyback_rising_candidates"] += int(BUY_RISING in bb)
        counts["positive_spread_candidates"] += int(positive)
    return counts
