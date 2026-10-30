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
MOMENTUM_MIN_YEN = 500           # かつ 500 円以上（安い商品の数百円のぶれを勢いにしない）
# 買取の勢いの状態（Wave 6 Stage E）。前回の正常な観測と比べられたときだけ RISING / FALLING / FLAT になる
MOM_RISING, MOM_FALLING, MOM_FLAT = "RISING", "FALLING", "FLAT"
MOM_NEW_OBSERVATION = "NEW_OBSERVATION"        # 前回の台帳はあるが、この候補の前回の価格が無い（初めて見た）。上がったとは言わない
MOM_NOT_COMPARABLE = "NOT_COMPARABLE"          # 前回の台帳を引き継げていない（鍵なし・初回・壊れた）。上がった・下がったと言わない
MOM_STALE_BASELINE = "STALE_BASELINE"          # 前回の値が古すぎる（7 日超）。基準にしない
MOM_SAME_OBSERVATION = "SAME_OBSERVATION"      # 前回と同じ観測（日時が変わらない）。新しい値ではないので勢いにしない
MOM_STATES = (MOM_RISING, MOM_FALLING, MOM_FLAT, MOM_NEW_OBSERVATION, MOM_NOT_COMPARABLE, MOM_STALE_BASELINE, MOM_SAME_OBSERVATION)
NEAR_RETAIL_RATIO = 0.95         # 買取の価格が小売の価格の 95% 以上（小売の価格 = 同一性つきで引けた現金の仕入れ値）
MEDIAN_MIN_SAMPLES = 3

# 限定を示す明確な語（公式の名前・ページにあれば、それだけで限定の根拠にする）。値は「何の限定か」の分類
LIMITED_WORDS = (("数量限定", "limited"), ("期間限定", "limited"), ("限定", "limited"), ("Limited", "limited"),
                 ("エクスクルーシブ", "exclusive"), ("Exclusive", "exclusive"))
# 曖昧な語（Special・特別・記念・周年・コラボなど）。普通の商品名にも付くので、**語の一致だけでは限定にしない**。
# 公式の構造化された項目（structured_limited: 公式の API・台帳が限定と明示した）があるときだけ、その種類として採用する
WEAK_LIMITED_WORDS = (("Special Edition", "special"), ("スペシャル", "special"), ("特別", "special"), ("Special", "special"),
                      ("アニバーサリー", "anniversary"), ("Anniversary", "anniversary"), ("周年", "anniversary"), ("記念", "anniversary"),
                      ("CELEBRATION", "anniversary"), ("コラボ", "collaboration"), ("Collaboration", "collaboration"))

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


_NEG_AFTER = ("なし", "無し", "ではない", "ではありません", "ありません")
_NEG_BEFORE = ("非", "無")


def _ascii_alpha(ch: str) -> bool:
    """英字（日本語の文字は isalpha() が True になるので使わない）。"""
    return bool(ch) and ch.isascii() and ch.isalpha()


def _has_word(word: str, name: str) -> bool:
    """名前に限定の語がある（否定・別の語の一部は除く: 「限定なし」「非限定」「Unlimited」）。"""
    start = 0
    while True:
        i = name.find(word, start)
        if i < 0:
            return False
        before, after = name[:i], name[i + len(word):]
        if word.isascii() and _ascii_alpha(before[-1:]):                   # Unlimited など、別の英単語の一部
            start = i + 1
            continue
        if word.isascii() and _ascii_alpha(after[:1]):                     # Limitedly など
            start = i + 1
            continue
        if before[-1:] in _NEG_BEFORE or after.startswith(_NEG_AFTER):
            start = i + 1
            continue
        return True


def limited_signal(*, official_name: str = "", official_url: str = "", official: bool = False, structured_limited: bool = False) -> dict:
    """公式の名前・ページに限定を示す明確な語があるときだけ、その種類を返す。

    official が偽・URL が無いなら付けない（名前だけの推測をしない）。曖昧な語（Special・特別 など）は、
    公式の構造化された項目（structured_limited）が限定と明示したときだけ採用する（語の一致だけでは付けない。
    現状、公式の構造化された限定の項目を持つ取得元は無いので、曖昧な語は限定にならない）。
    曖昧な語が公式の名前にあるときは、点にも件数にも使わない参考として limited_hint に残す（人が確かめる手がかり）。
    """
    name = str(official_name or "")
    none = {"limited": False, "limited_kind": "", "limited_evidence": "", "limited_hint": ""}
    if not (official and str(official_url or "").startswith("https://") and name):
        return none
    for word, kind in LIMITED_WORDS:
        if _has_word(word, name):
            return {"limited": True, "limited_kind": kind, "limited_evidence": word, "limited_hint": ""}
    for word, kind in WEAK_LIMITED_WORDS:
        if _has_word(word, name):
            if structured_limited:
                return {"limited": True, "limited_kind": kind, "limited_evidence": f"{word}+structured", "limited_hint": ""}
            return {**none, "limited_hint": word}
    return none


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


def is_quarantined(r: dict) -> bool:
    """価格が隔離される（誤価格の疑い・上限超え・裏付け不足・識別が部分的・条件つきの仕入れ値）行か。勢い・基準・点に使わない。
    行の項目から直接判定する（シグナルを付ける対象かどうかには依存しない。対象外の行の誤価格も基準にしない）。"""
    return bool(set(r.get("missing_requirements") or []) & SUSPICIOUS_REASONS) or bool(r.get("retail_conditions"))


def momentum(r: dict, prev, *, comparable: bool, now: datetime, quarantined: bool = False) -> dict:
    """買取の勢い（前回の正常な価格との比較）。前回の台帳をこの run に引き継げたとき（comparable）だけ数値を出す。

    prev: {"price": int, "at": ISO 日時, "stale": bool} | None（この候補の前回の観測が無い）。
    - 前回が無ければ NEW_OBSERVATION（上がったと言わない）。引き継げていなければ NOT_COMPARABLE。古い基準・同じ観測は勢いにしない
    - quarantined（誤価格の疑い・上限超え・裏付け不足・条件つき）の行は、数値は参考として残すが usable=False（点・上昇の件数に使わない。確定にも使わない）
    - usable（点に使える）: RISING で、買取の観測が新しく、同一性が確かで、隔離されていないとき
    """
    cur = r.get("observed_sell_price")
    cur = cur if isinstance(cur, int) and not isinstance(cur, bool) and cur > 0 else None
    out = {"momentum_state": MOM_NOT_COMPARABLE, "previous_price": None, "current_price": cur, "delta_yen": None, "delta_percent": None,
           "previous_observed_at": None, "current_observed_at": str(r.get("observed_at") or "") or None, "momentum_usable": False,
           "momentum_quarantined": bool(quarantined)}
    if not comparable:
        return out
    if not isinstance(prev, dict):
        out["momentum_state"] = MOM_NEW_OBSERVATION
        return out
    pp = prev.get("price")
    pp = pp if isinstance(pp, int) and not isinstance(pp, bool) and pp > 0 else None
    out["previous_price"], out["previous_observed_at"] = pp, str(prev.get("at") or "") or None
    if pp is None or cur is None:
        out["momentum_state"] = MOM_NEW_OBSERVATION
        return out
    if prev.get("stale"):
        out["momentum_state"] = MOM_STALE_BASELINE
        return out
    if out["previous_observed_at"] and out["previous_observed_at"] == out["current_observed_at"]:
        out["momentum_state"] = MOM_SAME_OBSERVATION       # 同じ観測を新しい値として数えない
        return out
    out["delta_yen"] = cur - pp
    out["delta_percent"] = round((cur - pp) / pp * 100, 1)
    big = abs(cur - pp) >= MOMENTUM_MIN_YEN                  # 3% 以上でも、数百円のぶれは勢いにしない
    out["momentum_state"] = (MOM_RISING if big and cur >= pp * RISING_MIN_RATIO else MOM_FALLING if big and cur * RISING_MIN_RATIO <= pp
                             else MOM_FLAT)
    at = _parse(prev.get("at"), now)
    out["days_since_previous"] = None if at is None else max(0, (now - at).days)
    out["momentum_usable"] = out["momentum_state"] == MOM_RISING and not quarantined
    return out


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
    if (isinstance(prev_sell, int) and isinstance(sell, int) and prev_sell > 0 and sell >= prev_sell * RISING_MIN_RATIO
            and sell - prev_sell >= MOMENTUM_MIN_YEN):
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


def annotate_buyback_rows(rows: list[dict], now: datetime, *, prev_sell_of=None, prev_obs_of=None, comparable: bool | None = None) -> dict:
    """買取起点の候補（triage 済みの行）に、シグナルと点を付ける。件数（公開してよい集計）を返す。

    行に必要な項目: category（triage）・observed_sell_price・observed_at・retail_price（照会で引けたときだけ）・retail_availability・
    retail_source_type・retail_url・identity_evidence の matched_name・status・missing_requirements。
    prev_obs_of(row) -> {"price","at","stale"} | None（前回の観測が無ければ None）。comparable: 前回の台帳を引き継げたか。
    （古い呼び出しの prev_sell_of(row) -> 前回の価格 | None だけを渡したときは、その価格を前回の観測として使う。）
    """
    if prev_obs_of is None and prev_sell_of is not None:
        _legacy = prev_sell_of
        prev_obs_of = lambda row: ({"price": _legacy(row), "at": None, "stale": False} if _legacy(row) is not None else None)   # noqa: E731
        comparable = True if comparable is None else comparable
    comparable = bool(comparable) and prev_obs_of is not None
    medians = category_medians([{**r, "category": (r.get("triage") or {}).get("category", "")} for r in rows])
    counts = {"new_release_candidates": 0, "limited_candidates": 0, "supply_pressure_candidates": 0,
              "buyback_rising_candidates": 0, "positive_spread_candidates": 0, "stock_unknown_not_counted": 0,
              "momentum_observed": 0, "momentum_new_observation": 0, "momentum_quarantined": 0, "momentum_not_comparable": 0}
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
        quarantined = suspicious or bool(r.get("retail_conditions"))
        mom = momentum(r, prev_obs_of(r) if comparable else None, comparable=comparable, now=now, quarantined=quarantined)
        r["momentum"] = mom
        counts["momentum_observed"] += int(mom["delta_yen"] is not None)
        counts["momentum_new_observation"] += int(mom["momentum_state"] == MOM_NEW_OBSERVATION)
        counts["momentum_not_comparable"] += int(mom["momentum_state"] == MOM_NOT_COMPARABLE)
        counts["momentum_quarantined"] += int(quarantined and mom["delta_yen"] is not None)
        # 勢いに使えるのは、隔離されていない RISING だけ（隔離された行の数値は参考として momentum に残す）
        prev = mom["previous_price"] if mom["momentum_usable"] else None
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
