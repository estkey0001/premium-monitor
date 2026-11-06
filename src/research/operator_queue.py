"""運営者向けの作業キュー（Wave 7b）: 「今日、人が何を確認すべきか」を最大 10 件に絞る。

- **運営者向けだけ**。確定の利益・actionable・顧客向けの画面・商品の通知には一切影響させない（このモジュールは確定の判定・通知の部品を import しない）。
  順位が高くても「確定」ではない。確定は既存の関門（公式の確認・同一性・状態・送料・鮮度）だけが決める。
- **決まった規則**（AI の価格予測は使わない）。同じ入力なら同じ順位（並べ替えの鍵: 区分・点・価格差・鮮度・候補の ID）。
- 区分: URGENT（価格差が正・同一性が確か・売値が新しい・足りない証拠が 1〜2 個だけ）/ HIGH（利益の可能性はあるが公式の確認・正本の登録・同一性の一部が残る）/
  MEDIUM（価格差は弱いが新型・買取の急騰・TCG の受付中などで調べる価値がある）/ LOW（古い・店のトップ・同一性が弱い・誤価格の疑い）。
- 隔離された価格（上限超え・急変・裏付け不足）は、調査の順位を上げてよいが確定には使わない。誤価格の疑い・外れた売値は差を加点せず LOW。
- 古い候補（売値・買値が古い・最後に見てから時間が経った）は LOW へ下げて「新しい価格を待つ」にする（過去の高優先を残さない）。
- 買取の急騰（RISING）の加点は、新しい・同一性が確か・隔離されていない・3% 以上かつ 500 円以上のもの（`signals.momentum` の `momentum_usable`）だけ。
- 次の行動（next_action）は、足りない証拠から決まった優先順で 1 つ決める（全部も残す）。運営者が証拠を確認すると、次回の run で足りない証拠が減り、
  順位と次の行動が再計算される（確定にならなくても）。状態は持たない（毎回、その時点の証拠から計算する）。
- TCG のイベントも別の種類（genre = TCG_EVENT）として入れる。応募の URL が無い・定価と結べない・商品が確認できない・締切が近い、を次の行動にする。
  締切の加点は、時刻つきの締切だけ（日付だけ・不明は大きく加点しない）。TCG は actionable にしない（応募の URL の判定は action_url が持つ）。

個別のキュー（商品名・候補の ID・価格・価格差・URL・順位の詳細・理由）は非公開（`.private/research/operator_queue.json`）。公開してよいのは件数だけ。
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from src.research import candidates as C

MAX_QUEUE = 10
URGENT, HIGH, MEDIUM, LOW = "URGENT", "HIGH", "MEDIUM", "LOW"
CLASSES = (URGENT, HIGH, MEDIUM, LOW)
_CLASS_ORDER = {c: i for i, c in enumerate(CLASSES)}

G_PRODUCT, G_DISCOVERED, G_TCG = "PRODUCT", "DISCOVERED_PRODUCT", "TCG_EVENT"
GENRES = (G_PRODUCT, G_DISCOVERED, G_TCG)

# 次の行動（商品）
VERIFY_OFFICIAL_PRICE, VERIFY_RETAIL_PRICE, VERIFY_BUYBACK = "VERIFY_OFFICIAL_PRICE", "VERIFY_RETAIL_PRICE", "VERIFY_BUYBACK"
VERIFY_SHIPPING, VERIFY_STOCK, VERIFY_IDENTITY = "VERIFY_SHIPPING", "VERIFY_STOCK", "VERIFY_IDENTITY"
FIND_CORROBORATING_SOURCE, REGISTER_CANONICAL_PRODUCT, WAIT_FOR_FRESH_PRICE = (
    "FIND_CORROBORATING_SOURCE", "REGISTER_CANONICAL_PRODUCT", "WAIT_FOR_FRESH_PRICE")
# 次の行動（TCG）
REGISTER_OFFICIAL_SOURCE = "REGISTER_OFFICIAL_SOURCE"                  # 公式の確認の取得元（URL）が登録されていない。まず公式の商品ページを登録する
VERIFY_APPLICATION_URL, VERIFY_PRODUCT_IDENTITY, VERIFY_MSRP, VERIFY_DEADLINE, VERIFY_ELIGIBILITY = (
    "VERIFY_APPLICATION_URL", "VERIFY_PRODUCT_IDENTITY", "VERIFY_MSRP", "VERIFY_DEADLINE", "VERIFY_ELIGIBILITY")
NEXT_ACTIONS = (VERIFY_OFFICIAL_PRICE, VERIFY_RETAIL_PRICE, VERIFY_BUYBACK, VERIFY_SHIPPING, VERIFY_STOCK, VERIFY_IDENTITY,
                FIND_CORROBORATING_SOURCE, REGISTER_CANONICAL_PRODUCT, WAIT_FOR_FRESH_PRICE,
                VERIFY_APPLICATION_URL, VERIFY_PRODUCT_IDENTITY, VERIFY_MSRP, VERIFY_DEADLINE, VERIFY_ELIGIBILITY, REGISTER_OFFICIAL_SOURCE)

MIN_SPREAD_YEN = 500              # 運営者が今日見る価値のある最小の価格差（買取の急騰の最小額と同じ。1 円差を URGENT にしない）
TCG_MIN_IN_QUEUE = 2              # 運営者向けの価値のある TCG（URGENT / HIGH）をキューに最低これだけ残す（商品の HIGH に全部押し出されない）
TCG_MAX_IN_QUEUE = 4              # キューの中の TCG の最大件数（確かな商品が TCG に押し出されない。空きがあるときだけ超えて埋める）
FUTURE_TOLERANCE_HOURS = 1.0      # 時計より先の観測時刻（これを超える未来）は読めない値として扱う
QUARANTINE_SPREAD_CAP = 20        # 隔離された価格（上限超え・急変・裏付け不足）の価格差の加点の上限
STALE_HOURS = 72                  # 最後の観測がこれより古い候補は古い候補として下げる（買取側の鮮度の基準 3 日と同じ）
URGENT_MISSING_OK = frozenset({C.PURCHASE_SHIPPING_UNKNOWN, C.STOCK_UNKNOWN, C.NEEDS_CORROBORATION})
URGENT_MAX_MISSING = 2
STALE_REASONS = frozenset({C.SELL_STALE, C.BUY_STALE})
WEAK_IDENTITY = frozenset({C.IDENTITY_UNCONFIRMED})
PARTIAL_IDENTITY = frozenset({C.IDENTITY_PARTIAL})
LOW_CONF = C.LOW_CONFIDENCE_PRICE_REASONS                       # 誤価格の疑い・外れた売値（差を加点しない・LOW）
QUARANTINE = C.CEILING_CLASS_REASONS                            # 上限超え・裏付け不足・急変（順位は上げてよいが確定には使わない）
# 足りない証拠 → 次の行動（この順で最初に当たったものが主の次の行動）
_PRODUCT_ACTION_ORDER = (
    (STALE_REASONS, WAIT_FOR_FRESH_PRICE),
    (frozenset({C.IDENTITY_UNCONFIRMED, C.IDENTITY_PARTIAL}), VERIFY_IDENTITY),
    (frozenset({C.OFFICIAL_UNVERIFIED}), VERIFY_OFFICIAL_PRICE),
    (frozenset({C.OFFICIAL_NOT_SOLD}), VERIFY_RETAIL_PRICE),                   # 公式が売っていない商品は、公式の価格は存在しない。仕入れ値は小売の価格で確かめる
    (frozenset({C.RETAIL_PRICE_MISSING, C.BUY_NOT_ITEM_LEVEL, C.ACQUISITION_CONDITIONAL}), VERIFY_RETAIL_PRICE),
    (frozenset({C.CANONICAL_UNREGISTERED}), REGISTER_CANONICAL_PRODUCT),
    (QUARANTINE | frozenset({C.PRICE_ANOMALY_SUSPECTED, C.SELL_REJECTED}), FIND_CORROBORATING_SOURCE),
    (frozenset({C.GENERIC_SELL_URL, C.CONDITION_UNKNOWN, C.CONDITION_MISMATCH, C.SELL_SAMPLE_INSUFFICIENT}), VERIFY_BUYBACK),
    (frozenset({C.PURCHASE_SHIPPING_UNKNOWN}), VERIFY_SHIPPING),
    (frozenset({C.STOCK_UNKNOWN}), VERIFY_STOCK),
)
# 応募の URL が公式ドメインに存在しない経路（URL の確認ではなく、応募の条件・方法の確認が次の行動になる）
_NO_URL_CHANNELS = frozenset({"SNS", "APP", "STORE_COUNTER", "MEMBER_LOGIN"})
TCG_ACTIVE = frozenset({"OPEN", "ENDING_SOON"})


def _int(value, default: int = 0) -> int:
    """壊れた値（文字列・None・NaN・無限大）で例外にしない。小数は整数に丸める（真偽値は 0 / 1 にしない）。"""
    if isinstance(value, bool):
        return default
    try:
        return int(value) if value == value and abs(float(value)) != float("inf") else default
    except (TypeError, ValueError, OverflowError):
        return default


def _num(value):
    """数値（int / float）だけ通す。真偽値・文字列・None・NaN・無限大は None（締切までの時間などを 1 時間として読まない）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _reasons(value) -> set:
    """足りない証拠の集合。文字列 1 つはその理由 1 つ、list / tuple / set は文字列だけ。それ以外（None・数値・辞書）は空。"""
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, (list, tuple, set, frozenset)):
        return {x for x in value if isinstance(x, str) and x}
    return set()


def _ts(value, now: datetime):
    return C._parse_ts(value, now)


def _age_hours(value, now: datetime):
    t = _ts(value, now)
    return None if t is None else (now - t).total_seconds() / 3600


def _observed_at(row: dict) -> str:
    """価格の観測時刻（古さ・鮮度の判定に使う。`last_seen_at` は毎回の run の時刻なので使わない）。"""
    return str(row.get("sell_observed_at") or row.get("observed_at") or "")


def _momentum(row: dict) -> dict:
    m = row.get("momentum") if isinstance(row.get("momentum"), dict) else {}
    return {"state": str(m.get("momentum_state") or ""), "previous_price": m.get("previous_price"), "current_price": m.get("current_price"),
            "delta_yen": m.get("delta_yen"), "delta_percent": m.get("delta_percent"), "usable": bool(m.get("momentum_usable")),
            "quarantined": bool(m.get("momentum_quarantined"))}


def next_actions(missing, *, stale: bool = False) -> list[str]:
    """足りない証拠から、次の行動を決まった優先順に（主の行動が先頭）。何も無ければ空。"""
    reasons = set(missing or ())
    if stale:
        reasons |= {C.SELL_STALE}
    out = [act for keys, act in _PRODUCT_ACTION_ORDER if reasons & keys]
    return list(dict.fromkeys(out))


def _classify_product(*, spread, missing: set, identity_ok: bool, stale: bool, signals: bool) -> str:
    """商品の区分。URGENT は、価格差が下限（500 円）以上・同一性が確か・売値が新しい・足りない証拠が 1〜2 個の許した種類だけ。"""
    positive = isinstance(spread, int) and spread >= MIN_SPREAD_YEN
    if stale or missing & LOW_CONF or missing & WEAK_IDENTITY or C.GENERIC_SELL_URL in missing:
        return LOW
    if positive and identity_ok and missing and missing <= URGENT_MISSING_OK and len(missing) <= URGENT_MAX_MISSING:
        return URGENT
    if positive:
        # 価格差があり、足りない証拠が人の確認で埋まる程度（4 個以下）なら HIGH。多すぎる・確認の見通しが立たないものは MEDIUM
        return HIGH if len(missing - C.ADVISORY) <= 4 else MEDIUM
    return MEDIUM if signals else LOW


def _score_product(*, spread, identity_ok: bool, sell_fresh: bool, buy_fresh: bool, missing: set, momentum: dict, signal_points: int,
                   stale: bool) -> tuple[int, list[str]]:
    """区分の中の並べ替えの点（決まった式）。大きいほど先。"""
    score, why = 0, []
    if isinstance(spread, int) and spread > 0 and not (missing & LOW_CONF):
        pts = min(spread, 100_000) // 1000
        if missing & QUARANTINE:
            pts = min(pts, QUARANTINE_SPREAD_CAP)                    # 隔離された売値は、裏付けが取れるまで価格差の大きさを信用しない（きれいな候補より上位にしない）
        score += pts
        why.append(f"spread+{pts}")
    for ok, name, pts in ((identity_ok, "identity", 15), (sell_fresh, "sell_fresh", 10), (buy_fresh, "buy_fresh", 8)):
        if ok:
            score += pts
            why.append(f"{name}+{pts}")
    if momentum["usable"] and not momentum["quarantined"] and not stale and identity_ok and not (missing & QUARANTINE):
        score += 10
        why.append("momentum_rising+10")
    sp = min(max(_int(signal_points), 0) // 4, 10)
    if sp:
        score += sp
        why.append(f"signals+{sp}")
    miss = len(missing - C.ADVISORY - {C.STOCK_UNKNOWN})
    if miss:
        score -= 4 * miss
        why.append(f"missing-{4 * miss}")
    if stale:
        score -= 30
        why.append("stale-30")
    return score, why


def _spread_of(row: dict):
    for k in ("known_cost_spread", "raw_spread_hint", "raw_spread"):
        v = row.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf"):
            return int(v)
    return None


def _product_item(row: dict, genre: str, now: datetime) -> dict:
    missing = _reasons(row.get("missing_requirements"))
    if genre == G_DISCOVERED:
        identity_ok = row.get("identity_status") == "IDENTITY_CONFIRMED" and C.IDENTITY_PARTIAL not in missing
        name = str(row.get("name") or "")
        pid = str(row.get("identity_value") or row.get("candidate_id") or "")
    else:
        identity_ok = not (missing & (WEAK_IDENTITY | PARTIAL_IDENTITY))
        ident = row.get("product_identity") if isinstance(row.get("product_identity"), dict) else {}
        name, pid = str(ident.get("name") or ""), str(ident.get("product_id") or "")
    last = _observed_at(row)
    age = _age_hours(last, now)
    # 観測時刻が空・読めない・時計より先のときは、新しいと確認できないので古い扱い（fail-closed。壊れた時刻の候補を URGENT にしない）
    unreadable_time = age is None or age < -FUTURE_TOLERANCE_HOURS
    stale = bool(missing & STALE_REASONS) or str(row.get("status")) == C.STALE or unreadable_time or age > STALE_HOURS
    mom = _momentum(row)
    gap = str(row.get("official_gap") or "")
    spread = _spread_of(row)
    if gap == "SALE_ENDED" and str(row.get("route_type") or "") != C.SECONDARY_TO_BUYBACK:
        # 公式が今は売っていない商品で、買値が公式の価格のままの経路は、存在しない公式価格から出た値。優先度・点・並べ替えには使わない
        # （買い側の経路は変えない。小売店・二次の価格を買値にした経路 SECONDARY_TO_BUYBACK の価格差は実在するので残す）
        spread = None
    signals = (_int(row.get("signal_points")) > 0 or (mom["usable"] and not mom["quarantined"])) and identity_ok and not (missing & QUARANTINE)
    cls = _classify_product(spread=spread, missing=missing, identity_ok=identity_ok, stale=stale, signals=signals)
    score, why = _score_product(spread=spread, identity_ok=identity_ok, sell_fresh=C.SELL_STALE not in missing and not stale,
                                buy_fresh=C.BUY_STALE not in missing and not stale, missing=missing, momentum=mom,
                                signal_points=_int(row.get("signal_points")), stale=stale)
    acts = next_actions(missing, stale=stale)
    # 公式の価格が確認できない原因に合わせて、公式の価格の確認を、より具体的な行動にする（原因が無い・それ以外は VERIFY_OFFICIAL_PRICE のまま。
    # 遮断（SOURCE_BLOCKED）は回避せず、人が公式ページで確認する）
    _gap_action = {"SALE_ENDED": VERIFY_RETAIL_PRICE,                # 公式が今は売っていない。公式を確認しても変わらない → 小売の価格の確認
                   "SOURCE_NOT_IMPLEMENTED": REGISTER_OFFICIAL_SOURCE,   # 確認の根拠のページが無い → まず公式の商品ページを登録
                   "IDENTITY_NOT_MATCHED": VERIFY_IDENTITY}          # 型番・JAN の証拠が無い → 先に同一性
    if gap in _gap_action:
        acts = list(dict.fromkeys(_gap_action[gap] if a == VERIFY_OFFICIAL_PRICE else a for a in acts))
    if not acts and cls != LOW:
        # 足りない証拠が見えない: 価格差が正なら公式の価格・状態の確認。信号だけ（急騰・新型）なら、まず仕入れ値（小売の価格）を確かめる
        acts = [VERIFY_OFFICIAL_PRICE] if isinstance(spread, int) and spread >= MIN_SPREAD_YEN else [VERIFY_RETAIL_PRICE]
    elif not acts and isinstance(spread, int) and spread >= MIN_SPREAD_YEN:
        acts = [VERIFY_OFFICIAL_PRICE]                             # 足りない証拠が見えないのに確定していない候補は、まず公式の価格・状態を確かめる
    src = row.get("source") if isinstance(row.get("source"), dict) else {}
    urls = row.get("source_url") if isinstance(row.get("source_url"), dict) else {}
    sell_url = str(urls.get("sell") or "") if isinstance(row.get("source_url"), dict) else str(row.get("source_url") or "")
    return {
        "candidate_id": str(row.get("candidate_id") or ""), "genre": genre, "priority": cls, "score": score, "score_parts": why,
        "product": {"name": name, "id": pid, "identity_confirmed": identity_ok,
                    "identity_basis": str(row.get("identity_basis") or ("canonical" if genre == G_PRODUCT else ""))},
        "spread": {"raw": row.get("raw_spread", row.get("raw_spread_hint")), "known_cost": row.get("known_cost_spread"), "used": spread},
        "missing_evidence": sorted(missing), "next_action": acts[0] if acts else None, "next_actions": acts, "official_gap": gap or None,
        "reason": _reason_text(cls, missing, stale, quarantined=bool(missing & QUARANTINE)),
        "last_seen": str(row.get("last_seen_at") or last), "observed_at": last, "stale": stale, "momentum": mom,
        "quarantined": bool(missing & QUARANTINE),
        "evidence": {"buy_source": str(src.get("buy") or row.get("retail_retailer") or ""), "sell_source": str(src.get("sell") or row.get("shop") or ""),
                     "buy_price": row.get("observed_buy_price", row.get("retail_price")), "sell_price": row.get("observed_sell_price"),
                     "buy_url": str(urls.get("buy") or row.get("retail_url") or ""), "sell_url": sell_url},
        "_sort": (_CLASS_ORDER[cls], -score, -(spread or 0), -(_ts_key(last, now)), str(row.get("candidate_id") or "")),
    }


def _ts_key(value, now: datetime) -> float:
    """並べ替え用の観測時刻（読めない・未来は 0 = 最も古い扱い。未来の時刻が有利にならない）。"""
    t = _ts(value, now)
    return 0.0 if t is None or t > now + timedelta(hours=FUTURE_TOLERANCE_HOURS) else t.timestamp()


def _reason_text(cls: str, missing: set, stale: bool, *, quarantined: bool) -> str:
    if stale:
        return "売値・買値が古い（または最後の観測から時間が経った）。新しい価格を待つ（過去の高優先を残さない）"
    parts = []
    if cls == URGENT:
        parts.append("価格差が正で、同一性が確かで、売値が新しい。足りないのは" + "・".join(sorted(missing)) + "だけ")
    elif cls == HIGH:
        parts.append("利益の可能性はあるが、公式の確認・正本の登録・同一性の一部などが残る")
    elif cls == MEDIUM:
        parts.append("価格差は弱い・または足りない証拠が多いが、新型・急騰・TCG の受付中などで調べる価値がある")
    else:
        parts.append("同一性が弱い・店のトップの URL・誤価格の疑い・市場の関連が低い")
    if quarantined:
        parts.append("隔離された価格（上限超え・裏付け不足・急変）。順位は上げるが確定には使わない")
    return "。".join(parts)


# ── TCG ───────────────────────────────────────────────────────────────────────────

def _tcg_group_key(r: dict) -> str:
    ident = r.get("product_name") or r.get("product_id") or f"unidentified:{r.get('store')}"      # 識別できないイベントを 1 件にまとめない
    raw = f"{r.get('retailer')}|{ident}|{r.get('event_type')}"
    return "tcg_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


_TCG_MISSING = {VERIFY_PRODUCT_IDENTITY: "PRODUCT_IDENTITY_UNCONFIRMED", VERIFY_APPLICATION_URL: "APPLICATION_URL_UNVERIFIED",
                VERIFY_MSRP: "MSRP_UNLINKED", VERIFY_DEADLINE: "DEADLINE_UNKNOWN_OR_DATE_ONLY", VERIFY_ELIGIBILITY: "ELIGIBILITY_UNVERIFIED"}


def _tcg_missing(acts: list[str]) -> list[str]:
    return [_TCG_MISSING[a] for a in acts if a in _TCG_MISSING]


def _tcg_items(events: list[dict], now: datetime, *, fresh: bool = True, healthy_sources=None) -> list[dict]:
    """TCG の受付中のイベント（profit_dense の非公開の行）を、同じ小売・商品・種類ごとに 1 件にまとめる（店舗数を残す）。"""
    groups: dict[str, list[dict]] = {}
    for r in events or []:
        if isinstance(r, dict) and str(r.get("status") or "") in (TCG_ACTIVE | {"UPCOMING"}):
            groups.setdefault(_tcg_group_key(r), []).append(r)
    out = []
    for gid, rows in groups.items():
        # 代表 = 締切がまだ来ていない（または不明）イベントのうち最も近いもの。期限切れの行が、同じ集約の開いている店舗を隠さない。全部が期限切れなら最も近いもの
        def _h(x):
            return _num(x.get("hours_to_deadline"))
        live = [x for x in rows if _h(x) is None or _h(x) >= 0] or rows
        rows = sorted(live, key=lambda x: (_h(x) is None, _h(x) or 0)) + [x for x in rows if x not in live]
        r = rows[0]
        status = str(r.get("status") or "")
        hours = _num(r.get("hours_to_deadline"))
        precise = r.get("application_end_precision") == "datetime"
        expired = hours is not None and hours < 0                         # 状態は受付中のままだが締切を過ぎている（古い情報）。優先しない
        source_ok = healthy_sources is None or str(r.get("retailer") or "") in healthy_sources
        stale = (not fresh) or (not source_ok)                            # 収集が失敗して前回のデータが残った日・健全でない取得元は、新しい情報と確認できない
        # どれかの店舗で確認できていれば確認済み（代表の店舗だけを見ない）。応募の URL・同一性・定価との結び付き・条件
        def _exact(x):
            return str(x.get("product_match") or "") == "exact" and bool(x.get("product_id")) and not x.get("provisional_product")
        identity_ok = any(_exact(x) for x in rows)                      # どれかの店舗で確認できていれば確認済み（表示・次の行動）
        rep_identity_ok = _exact(r)                                     # URGENT は、締切の代表の行の同一性が確かなときだけ
        app_urls = sorted({str(x.get("application_url")) for x in rows if x.get("application_url")})
        channels = {str(x.get("channel") or "") for x in rows}
        no_url_channel = bool(channels) and channels <= _NO_URL_CHANNELS
        msrp_linked = any(x.get("msrp_linked") for x in rows)
        requirements = sorted({q for x in rows for q in _reasons(x.get("requirements"))})
        sig = max((_int(x.get("signal_points")) for x in rows), default=0)
        acts = []
        if not identity_ok:
            acts.append(VERIFY_PRODUCT_IDENTITY)
        if not app_urls and not no_url_channel:
            acts.append(VERIFY_APPLICATION_URL)
        if not msrp_linked:
            acts.append(VERIFY_MSRP)
        if hours is None or not precise or expired:
            acts.append(VERIFY_DEADLINE)                                   # 締切が不明・日付だけ（時刻の精度が無い）
        if no_url_channel or requirements:
            acts.append(VERIFY_ELIGIBILITY)                                # 応募の方法・条件（SNS・アプリ・会員など）
        if stale:
            acts = [WAIT_FOR_FRESH_PRICE] + acts                          # TCG では「新しいイベントの情報を待つ」（収集が失敗した日・取得元が健全でない）
        acts = list(dict.fromkeys(acts))
        boost = 0
        if status in TCG_ACTIVE and hours is not None and hours >= 0:
            if precise:
                boost = (20 + int((24 - hours) / 2)) if hours <= 24 else (10 if hours <= 72 else 0)       # 24 時間以内は近いほど高い（20〜32）
            else:
                boost = 3 if hours <= 72 else 0                            # 日付だけの締切は大きく加点しない
        score = sig + boost + (8 if msrp_linked else 0) + (8 if identity_ok else 0) - 4 * len(acts)
        # 区分: 受付中で締切が時刻つき 24 時間以内かつ商品の同一性が確か = URGENT（確認が間に合うか。同一性が未確認のものは最上位にしない）。
        # 受付中 = HIGH（同一性が確か・締切の加点あり）/ MEDIUM。これから = MEDIUM / LOW。actionable にはしない
        if expired or stale:
            cls = LOW
        elif status in TCG_ACTIVE and precise and hours is not None and 0 <= hours <= 24 and rep_identity_ok:
            cls = URGENT
        elif status in TCG_ACTIVE:
            cls = HIGH if identity_ok or boost else MEDIUM
        else:
            cls = MEDIUM if identity_ok else LOW
        out.append({
            "candidate_id": gid, "genre": G_TCG, "priority": cls, "score": score,
            "score_parts": [f"signals+{sig}", f"deadline_boost+{boost}", f"actions-{4 * len(acts)}"],
            "product": {"name": str(r.get("product_name") or ""), "id": str(r.get("product_id") or ""), "identity_confirmed": identity_ok,
                        "identity_basis": "product_id_exact" if identity_ok else ""},
            "spread": {"raw": None, "known_cost": None, "used": None},
            "missing_evidence": _tcg_missing(acts), "next_action": acts[0] if acts else None, "next_actions": acts,
            "reason": f"TCG の{ '受付中' if status in TCG_ACTIVE else 'これから受付' }。応募の URL の確認は action_url の判定（actionable ではない）",
            "last_seen": "", "stale": stale, "momentum": {"state": "", "previous_price": None, "current_price": None, "delta_yen": None,
                                                           "delta_percent": None, "usable": False, "quarantined": False},
            "quarantined": False,
            "evidence": {"retailer": str(r.get("retailer") or ""), "channel": str(r.get("channel") or ""), "status": status,
                         "store_count": len({str(x.get("store") or "") for x in rows}), "events": len(rows),
                         "hours_to_deadline": hours, "deadline_precision": str(r.get("application_end_precision") or ""),
                         "announcement_url": r.get("announcement_url"), "application_url": app_urls[0] if app_urls else None,
                         "application_urls": app_urls, "channels": sorted(channels), "msrp_linked": msrp_linked,
                         "quality": str(r.get("quality") or ""), "requirements": requirements},
            "deadline_boosted": boost > 0,
            "_sort": (_CLASS_ORDER[cls], -score, hours if hours is not None else 10**6, 0.0, gid),
        })
    return out


# ── キューの組み立て ──────────────────────────────────────────────────────────────

def build(*, candidates: list[dict], product_candidates: list[dict], tcg_events: list[dict], now: datetime,
          max_queue: int = MAX_QUEUE, tcg_fresh: bool = True, tcg_healthy_sources=None) -> dict:
    """運営者向けの作業キュー。戻りは {"queue": 個別の行（非公開）, "counts": 公開してよい件数, "generated_at"}。

    candidates: 正本の商品の調査候補（RESEARCH_CANDIDATE だけを対象。売値・買値が古いものは LOW で「新しい価格を待つ」。STALE（今回見えなかった）は除外）。
    product_candidates: 買取起点の未登録商品の候補（RESEARCH_CANDIDATE だけ）。tcg_events: `profit_dense.evaluate` の非公開の行。
    """
    items: list[dict] = []
    not_seen = 0                                                   # 今回見えなかった候補（STALE）。キューから除外し、件数だけ残す（過去の高優先を残さない）
    for c in candidates or []:
        if not isinstance(c, dict):
            continue
        if str(c.get("status")) == C.STALE:
            not_seen += 1
        elif str(c.get("status")) == C.RESEARCH_CANDIDATE:
            items.append(_product_item(c, G_PRODUCT, now))
    for r in product_candidates or []:
        if isinstance(r, dict) and str(r.get("status")) == C.RESEARCH_CANDIDATE:
            items.append(_product_item(r, G_DISCOVERED, now))
    items.extend(_tcg_items(tcg_events or [], now, fresh=bool(tcg_fresh), healthy_sources=tcg_healthy_sources))
    items.sort(key=lambda x: x["_sort"])
    limit = max(0, _int(max_queue, MAX_QUEUE))
    chosen, picked, tcg_n = [], set(), 0
    for it in items:                                               # 0 巡目: 運営者向けの価値のある TCG（URGENT / HIGH）を最低枠まで先に確保する
        if tcg_n >= min(TCG_MIN_IN_QUEUE, limit):
            break
        if it["genre"] == G_TCG and it["priority"] in (URGENT, HIGH):
            chosen.append(it)
            picked.add(id(it))
            tcg_n += 1
    for it in items:                                               # 1 巡目: 区分の順に埋める。TCG は上限まで（確かな商品が TCG に押し出されない）
        if len(chosen) >= limit:
            break
        if id(it) in picked:
            continue
        if it["genre"] == G_TCG:
            if tcg_n >= TCG_MAX_IN_QUEUE:
                continue
            tcg_n += 1
        chosen.append(it)
        picked.add(id(it))
    for it in items:                                               # 2 巡目: 空きがあるときだけ、残りの TCG で埋める
        if len(chosen) >= limit:
            break
        if id(it) not in picked:
            chosen.append(it)
            picked.add(id(it))
    # 3 巡目: TCG の上限は「確かな商品を押し出さない」ためのもの。LOW 以外の TCG が、LOW（古い・待つだけ）の商品の行に負けて外れたままにしない
    for it in items:
        if id(it) in picked or it["genre"] != G_TCG:
            continue
        worst = max(chosen, key=lambda x: x["_sort"], default=None)
        if worst is not None and worst["genre"] != G_TCG and worst["priority"] == LOW and it["priority"] != LOW:
            chosen.remove(worst)
            picked.discard(id(worst))
            chosen.append(it)
            picked.add(id(it))
    chosen.sort(key=lambda x: x["_sort"])
    queue = []
    for i, it in enumerate(chosen, 1):
        row = {k: v for k, v in it.items() if k != "_sort"}
        row["rank"] = i
        queue.append(row)
    cls_all = {c: sum(1 for x in items if x["priority"] == c) for c in CLASSES}
    cls_q = {c: sum(1 for x in queue if x["priority"] == c) for c in CLASSES}
    act_q = {a: sum(1 for x in queue if x["next_action"] == a) for a in NEXT_ACTIONS}
    tcg_q = [x for x in queue if x["genre"] == G_TCG]
    counts = {
        "queue_build_failed": 0, "queue_count": len(queue), "urgent_count": cls_q[URGENT], "high_count": cls_q[HIGH], "medium_count": cls_q[MEDIUM], "low_count": cls_q[LOW],
        "candidates_considered": len(items), "urgent_all": cls_all[URGENT], "high_all": cls_all[HIGH], "medium_all": cls_all[MEDIUM], "low_all": cls_all[LOW],
        "stale_demoted": sum(1 for x in items if x["stale"]) + not_seen,
        "positive_spread_not_confirmed": sum(1 for x in items if x["genre"] != G_TCG and isinstance(x["spread"]["used"], int) and x["spread"]["used"] > 0),
        "quarantined_in_queue": sum(1 for x in queue if x["quarantined"]),
        "tcg_queue_count": len(tcg_q), "tcg_deadline_boosted": sum(1 for x in tcg_q if x.get("deadline_boosted")),
        "tcg_missing_application_url": sum(1 for x in tcg_q if VERIFY_APPLICATION_URL in x["next_actions"]),
        "tcg_missing_identity": sum(1 for x in tcg_q if VERIFY_PRODUCT_IDENTITY in x["next_actions"]),
        "tcg_missing_msrp": sum(1 for x in tcg_q if VERIFY_MSRP in x["next_actions"]),
    }
    next_counts = {f"next_{a}": n for a, n in act_q.items()}
    return {"generated_at": now.isoformat(timespec="seconds"), "queue": queue, "counts": counts, "next_action_counts": next_counts}


def empty(now: datetime) -> dict:
    """空のキュー（内部の部品を使わない。組み立てが失敗したときの代わり。件数はすべて 0）。"""
    counts = {k: 0 for k in PUBLIC_COUNT_KEYS}
    counts["queue_build_failed"] = 1                                # 失敗は 0 件と区別できるように、件数にも出す（公開してよい 0 / 1 の値）
    return {"generated_at": now.isoformat(timespec="seconds"), "queue": [], "counts": counts,
            "next_action_counts": {f"next_{a}": 0 for a in NEXT_ACTIONS}, "error": "operator_queue_failed"}


PUBLIC_COUNT_KEYS = ("queue_build_failed", "queue_count", "urgent_count", "high_count", "medium_count", "low_count", "candidates_considered", "urgent_all", "high_all",
                     "medium_all", "low_all", "stale_demoted", "positive_spread_not_confirmed", "quarantined_in_queue", "tcg_queue_count",
                     "tcg_deadline_boosted", "tcg_missing_application_url", "tcg_missing_identity", "tcg_missing_msrp")
PUBLIC_NEXT_ACTION_KEYS = tuple(f"next_{a}" for a in NEXT_ACTIONS)
