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
import re
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
ABOVE_GENRE_MAX = "ABOVE_GENRE_MAX"                  # 売値が、ジャンルの正常帯の上限を超えて隔離された（上限は自動で引き上げない）
NEEDS_CORROBORATION = "NEEDS_CORROBORATION"          # 他店の裏付けが無い（人が確かめるまで確定にしない）
PRICE_SPIKE = "PRICE_SPIKE"                          # 前回の正常取得から大きく動いた（誤りとは限らない・要確認）
HIGH_PRIORITY_RESEARCH = "HIGH_PRIORITY_RESEARCH"    # 上限超え・裏付け不足・急変だけで確定から外れた、価格差が正の商品
STANDARD_RESEARCH = "STANDARD"
NO_SELL_SIDE = "NO_SELL_PRICE"
NO_BUY_SIDE = "NO_BUY_PRICE"
NO_SPREAD = "NO_SPREAD"
RETAIL_PRICE_MISSING = "RETAIL_PRICE_MISSING"        # 小売（公式直販）の価格を同一性つきで引けていない（買取起点の候補）
IDENTITY_PARTIAL = "IDENTITY_PARTIAL"                # 識別子が型番コードだけ（JAN・部品番号ほど確かでない）
CANONICAL_UNREGISTERED = "CANONICAL_UNREGISTERED"    # 正本（商品の登録）に無い。人が公式で確かめて登録する
ACQUISITION_CONDITIONAL = "ACQUISITION_CONDITIONAL"  # 仕入れ値が、クーポン・キャンペーン・会員限定・数量限定の値引きかもしれない（現金の確定の価格ではない）
RETAIL_LOOKUP_MAX_AGE_HOURS = 36                     # 小売の照会の結果がこれより古いときは使わない（鮮度を偽装しない）

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


# 品質ゲートで隔離された買取価格（collector_report の suspicious_prices）の理由 → 調査候補の理由。
# 調べる価値のある隔離だけを入れる（上限超え・急変）。取り違え・解析の誤り（cross_product_same_price・capacity_price_reversal・
# below_genre_min・over_3x_official・game_console_smartphone_price など）は、価格差があっても候補にしない（誤取得の積み上げ・
# 件数の水増しになるため）。他店との乖離（outlier_vs_peer_shops）も別の確認の領域なので入れない。
QUARANTINE_REASONS = {
    "above_genre_max": [ABOVE_GENRE_MAX, NEEDS_CORROBORATION],
    "price_change_over_20pct": [PRICE_SPIKE, NEEDS_CORROBORATION],
    "price_change": [PRICE_SPIKE, NEEDS_CORROBORATION],
}
CEILING_CLASS_REASONS = frozenset({ABOVE_GENRE_MAX, NEEDS_CORROBORATION, PRICE_SPIKE})
QUARANTINE_MAX_AGE_HOURS = 36        # 取得の報告（collector_report）がこれより古いときは、隔離行を新しい観測として使わない


def quarantine_observations(quarantined: list[dict], products: list[dict], now: datetime,
                            report_generated_at: str | None = None) -> list[dict]:
    """隔離された買取価格を、調査候補の売り側の観測にする（確定にはならない。上限は引き上げない）。

    - 観測の時刻は**取得の報告の生成時刻**（report_generated_at）。読めない・古い（QUARANTINE_MAX_AGE_HOURS 超）・未来のときは、
      隔離行を使わない（収集が失敗して前日の報告が残る日に、古い価格を今日の新しい観測にしない。鮮度を偽装しない）
    - action が rejected の行だけ（採用済み・フラグだけの行は、通常の観測として既にある）。理由は QUARANTINE_REASONS の許可リストだけ
    - 同じ (商品, 店) に許可リスト外の理由が1つでもあれば、その店は使わない。許可リスト内の複数理由は1つの観測にまとめる（理由は和集合。同じ価格の観測を重ねない）
    - 商品は別名の表（product_aliases）で結び付ける（`prod_<alias>` と決めつけない）
    """
    from src.market.product_aliases import product_id_of
    gen = _parse_ts(report_generated_at, now)
    if gen is None or not (timedelta(hours=-1) <= now - gen <= timedelta(hours=QUARANTINE_MAX_AGE_HOURS)):
        return []
    pids = {p["id"] for p in products}
    merged: dict[tuple, dict] = {}
    # 同じ (商品, 店) に許可リスト外の理由（取り違え・解析の誤り等）が1つでも付く行は、店ごと使わない（誤取得の素通りを防ぐ）
    tainted = {(str(q.get("product_alias")), str(q.get("shop") or ""))
               for q in quarantined or [] if isinstance(q, dict) and q.get("reason") not in QUARANTINE_REASONS}
    for q in quarantined or []:
        if not isinstance(q, dict) or q.get("action") != "rejected" or q.get("reason") not in QUARANTINE_REASONS:
            continue
        if (str(q.get("product_alias")), str(q.get("shop") or "")) in tainted:
            continue
        pid = product_id_of(q.get("product_alias"), pids)
        price = q.get("price")
        if pid not in pids or not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
            continue
        shop = str(q.get("shop") or "")
        key = (pid, shop)
        o = merged.get(key)
        if o is None:
            merged[key] = {"product_id": pid, "price_role": "sell", "price_type": "buyback_price",
                           "canonical_price_type": "BUYBACK_CASH", "price": int(price), "source_id": shop, "source_name": shop,
                           "condition": "new_unopened", "is_fresh": True, "freshness_basis": "observed",
                           "observed_at": gen.isoformat(timespec="seconds"), "accessory_flag": False, "wrong_model_flag": False,
                           "research_quarantine": [q["reason"]]}
        else:
            o["price"] = max(o["price"], int(price))
            if q["reason"] not in o["research_quarantine"]:
                o["research_quarantine"].append(q["reason"])
    return list(merged.values())


def _parse_ts(value, now: datetime):
    """時刻（ISO 形式・末尾の JST も可）。タイムゾーンが無ければ now に合わせる。読めなければ None。"""
    s = str(value or "").strip().replace(" JST", "")
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


def _sell_reasons(o: dict, buy_condition: str = "new") -> list[str]:
    from src.market import normalized_prices as npr
    if o.get("research_quarantine") is not None:
        rs = o["research_quarantine"] if isinstance(o["research_quarantine"], list) else [o["research_quarantine"]]
        return list(dict.fromkeys(r for q in rs for r in QUARANTINE_REASONS.get(q, [PRICE_ANOMALY_SUSPECTED])))
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


SELL_FLAG_NONE, SELL_FLAG_STALE_HIGH, SELL_FLAG_QUARANTINE = "", "stale_high", "quarantine"


def _best_sell(obs: list[dict], pid: str, buy_price: int | None = None, verified: bool = False):
    """売る側の代表の観測と、その行が確定の売値に使えない理由。戻りは (観測, 理由, 印)。

    印: "" = 通常 / "stale_high" = 古い高値を使った / "quarantine" = 品質ゲートで隔離された価格を使った。

    確定できる売値（既存の関門を通る行）の最高値を使う。ただし、その行では価格差が出ないのに、確定できない行
    （古い・店のトップの URL・商品の照合が未了…）に買値を上回る高値があるときは、その高値を調査候補の売値にする
    （最新の確定の売値では差が無いが、再確認すれば差が出るかもしれない商品を捨てない。理由は必ず付く）。

    隔離された価格（research_quarantine）は、確定できる売値・確定できない行の代表選びには混ぜない。確定できる売値で価格差が
    出ているとき（既存の判定が正本）は使わず、売値が無い・確定できる価格差が無い・確定できない行しか無いときだけ、
    隔離された価格を代表にする（理由 ABOVE_GENRE_MAX・NEEDS_CORROBORATION・PRICE_SPIKE が必ず付き、確定にはならない）。
    """
    all_opts = _sell_options(obs, pid)
    quar = [o for o in all_opts if o.get("research_quarantine") is not None]
    opts = [o for o in all_opts if o.get("research_quarantine") is None]
    key = lambda o: (o["price"], str(o.get("source_id") or ""))  # noqa: E731
    best, reasons, flag = None, [], SELL_FLAG_NONE
    if opts:
        confirmed = [o for o in opts if not _sell_reasons(o)]
        # 確定できない行の中では、品質の判定で外れた行（疑わしい価格）を後回しにする。外れた高値は調べる価値のある候補の
        # 代表にしない（それしか無いときだけ使う。理由 SELL_REJECTED が付き、信頼度・優先度は低くなる）
        clean = [o for o in opts if SELL_REJECTED not in _sell_reasons(o)]
        raw_best = max(clean or opts, key=key)
        if confirmed:
            best, reasons = max(confirmed, key=key), []
            if (buy_price is not None and best["price"] - buy_price <= 0 and raw_best["price"] > buy_price
                    and raw_best is not best):
                best, reasons, flag = raw_best, _sell_reasons(raw_best), SELL_FLAG_STALE_HIGH
        else:
            best, reasons = raw_best, _sell_reasons(raw_best)
    if quar and buy_price is not None and not verified:     # 確定済みの商品の行に、隔離された価格を高信頼の売値として載せない
        q = max(quar, key=key)
        confirmed_positive = best is not None and not reasons and best["price"] - buy_price > 0
        if q["price"] > buy_price and not confirmed_positive:
            return q, _sell_reasons(q), SELL_FLAG_QUARANTINE
    return best, reasons, flag


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
    # 隔離された価格（上限超え・急変）の売値は、既存の関門（売値の新しさ・商品の照合）を通っていないので、この2つは加点しない
    gated = not (reasons & CEILING_CLASS_REASONS)
    if gated and SELL_STALE not in reasons:
        score += 20
        why.append("sell_fresh+20")
    if gated and IDENTITY_UNCONFIRMED not in reasons:
        score += 15
        why.append("identity_ok+15")
    blocking = reasons - ADVISORY
    if blocking == {OFFICIAL_UNVERIFIED}:
        score += 25
        why.append("only_official_check_missing+25")
    elif blocking and blocking <= (CEILING_CLASS_REASONS | {PURCHASE_SHIPPING_UNKNOWN}) and blocking & CEILING_CLASS_REASONS:
        # 足りないのは、上限超え・急変の裏付け（他店の商品ページ）だけ。公式の価格・照合は揃っている（売値の新しさ・照合は隔離行では未確認）
        score += 25
        why.append("only_corroboration_missing+25")
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
        sell, sell_reasons, used_stale_high = _best_sell(observations, pid, int(buy['price']) if buy else None, pid in verified_pids)

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
                        "再確認すると差が出るかもしれない" if used_stale_high == SELL_FLAG_STALE_HIGH else
                        ("品質ゲートで隔離された買取価格（上限超え・急変）。確定の売値には使わない。他店の商品ページなどの裏付けが取れる"
                         "まで確定にしない（ジャンルの上限は自動で引き上げない）" if used_stale_high == SELL_FLAG_QUARANTINE else ""))}
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
        # 上限超え・裏付け不足・急変で確定から外れた、価格差が正の商品は、消さずに高優先の調査として残す
        reasons_set = set(row["exclusion_reasons"])
        row["research_class"] = (HIGH_PRIORITY_RESEARCH if row["status"] == RESEARCH_CANDIDATE
                                 and reasons_set & CEILING_CLASS_REASONS and not reasons_set & LOW_CONFIDENCE_PRICE_REASONS
                                 else STANDARD_RESEARCH)
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


_PART_RE = re.compile(r"\b[A-Z0-9]{4,5}J/A\b")
# 型番コード: 大文字の英字 + 数字（ベンダーの接頭辞 SM- なども含む）。5文字未満（S25・A15 など）は一般語・短いコードに当たるので使わない。
# 大文字小文字を変えて探さない（case-10 のような一般語を拾わない）
_MODEL_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{1,5}(?:-[A-Z]{1,3})?-?\d{2,5}[A-Z0-9-]{0,12}(?![A-Za-z0-9])")
_MODEL_MIN_LEN = 5
IDENT_JAN, IDENT_PART, IDENT_MODEL = "JAN", "PART_NUMBER", "MODEL_CODE"
_IDENT_POINTS = {IDENT_JAN: 40, IDENT_PART: 40, IDENT_MODEL: 20}


def identify_row(r: dict) -> tuple[str, str] | None:
    """買取の一覧の1行から、機械的に確かめられる識別子（JAN・メーカーの部品番号・型番コード）を取る。

    名前だけの行は識別しない（None）。商品の名前の一致で商品にしない。
    """
    jan = str(r.get("jan") or "").strip()
    if jan.isdigit() and len(jan) == 13:
        return IDENT_JAN, jan
    name = str(r.get("name") or "")
    parts = sorted(set(_PART_RE.findall(name)))
    if len(parts) == 1:
        return IDENT_PART, parts[0]
    if len(parts) > 1:
        return IDENT_PART, "+".join(parts)
    models = sorted({m for m in _MODEL_RE.findall(name) if len(m) >= _MODEL_MIN_LEN})
    if len(models) == 1:
        return IDENT_MODEL, models[0]
    return None


def rank_product_candidates(unmatched: list[dict], now: datetime, retail_hints: dict | None = None,
                            limit: int | None = CATALOG_LIST_LIMIT) -> tuple[list[dict], dict]:
    """買取の一覧にあるが正本に無い商品の候補（DISCOVERED_PRODUCT_CANDIDATE）を、調べる順に並べる。

    - 識別子（JAN・部品番号・型番コード）がある行だけを候補にする。名前だけの行は候補にしない（数だけ数える）
    - 同じ識別子の行（色違い・同じ店の重複）は1つにまとめる（候補の ID は店と識別子から決まる安定したもの）
    - 順位の点 = 識別の確かさ + 小売の価格を引ける見込み + 価格差の見込み（小売の価格が分かるときだけ）。買取の高い順ではない
    - 小売の価格のヒント（retail_hints: 部品番号 → 公式の発見の価格）は、公式の購入ページ由来の未登録商品の値。確定の価格ではない
    - 正本への自動登録はしない（人が公式で確かめて、既存の手順で登録する）
    """
    hints = retail_hints or {}
    fresh = [r for r in unmatched if _fresh_catalog_row(r, now)]
    stats = {"catalog_rows_fresh": len(fresh), "identified": 0, "name_only_rejected": 0}
    groups: dict[tuple, dict] = {}
    for r in fresh:
        ident = identify_row(r)
        if ident is None:
            stats["name_only_rejected"] += 1
            continue
        stats["identified"] += 1
        key = (str(r.get("shop") or ""), ident[0], ident[1])
        g = groups.get(key)
        price = int(r.get("price") or 0)
        if g is None or price > g["price"]:
            groups[key] = {"row": r, "ident": ident, "price": price, "variants": (g["variants"] if g else 0) + 1}
        else:
            g["variants"] += 1
    rows = []
    for (shop, basis, value), g in groups.items():
        r = g["row"]
        hint = None
        if basis == IDENT_PART:
            for part in value.split("+"):
                if part in hints:
                    hint = hints[part]
                    break
        spread = (g["price"] - int(hint["price"])) if hint and isinstance(hint.get("price"), int) else None
        points = _IDENT_POINTS[basis]
        feas = 30 if hint else (10 if basis in (IDENT_JAN, IDENT_PART) else 5)
        pot = min(max(spread or 0, 0), 100_000) // 3334 if spread is not None else 0
        rows.append({
            "candidate_id": "dp_" + hashlib.sha1(f"{shop}|{basis}|{value}".encode("utf-8")).hexdigest()[:12],
            "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": DISCOVERED,
            "shop": shop, "name": r.get("name", ""), "jan": r.get("jan", ""), "identity_basis": basis, "identity_value": value,
            "identity_confidence": "high" if basis in (IDENT_JAN, IDENT_PART) else "medium",
            "observed_sell_price": g["price"], "source_url": r.get("url", ""), "observed_at": r.get("observed_at", ""),
            "variants": g["variants"],
            "retail_price_hint": int(hint["price"]) if hint and isinstance(hint.get("price"), int) else None,
            "retail_hint_source": (hint or {}).get("source", ""),
            "raw_spread_hint": spread, "positive_spread_hint": bool(spread is not None and spread > 0),
            "rank_score": points + feas + pot,
            "missing_requirements": ["CANONICAL_UNREGISTERED", "IDENTITY_NOT_VERIFIED_BY_OFFICIAL"]
                                    + ([] if hint else ["OFFICIAL_PRICE_UNKNOWN"]),
            "note": "買取の一覧に載っているが正本に無い。識別子（JAN・部品番号・型番）は機械的に取れた値。"
                    "名前だけでは登録しない（公式で JAN・型番・価格を確かめる）。小売の価格のヒントは確定の価格ではない"})
    rows.sort(key=lambda x: (-x["rank_score"], -(x["raw_spread_hint"] or 0), x["candidate_id"]))
    stats.update({"unique_candidates": len(rows), "with_retail_hint": sum(1 for x in rows if x["retail_price_hint"] is not None),
                  "positive_spread_hint": sum(1 for x in rows if x["positive_spread_hint"])})
    for i, x in enumerate(rows, 1):
        x["rank"] = i
    return (rows if limit is None else rows[:limit]), stats


def apply_lookups(dps: list[dict], lookups: dict | None, now: datetime, generated_at: str | None = None) -> list[dict]:
    """買取起点の候補（DISCOVERED_PRODUCT_CANDIDATE）に、小売（公式直販）の価格の照会の結果を結び付ける。

    - 照会の結果（retail_lookup.lookup）は status が MATCHED のものだけ価格に使う。一致は JAN・型番・部品番号の完全一致で、
      照会の側が保証する（名前だけの一致は無い）。AMBIGUOUS・IDENTITY_MISMATCH・NOT_PURCHASABLE・UNSUPPORTED は価格に使わない
    - 結果の取得時刻（observed_at）が読めない・未来・36時間超のものは使わない（古い価格を今日の観測にしない）。
      照会の記録全体の生成時刻（generated_at）も同じ条件
    - 買取の価格 − 小売の価格が正なら RESEARCH_CANDIDATE（確定にはしない。理由 OFFICIAL_UNVERIFIED・PURCHASE_SHIPPING_UNKNOWN・
      CANONICAL_UNREGISTERED が必ず付く）。0 以下なら REJECTED（NO_SPREAD）。差が小売の 50% を超えるものは誤一致の疑い（低優先）
    - 照会の無い候補は、そのまま（DISCOVERED）。小売の価格のヒント（Apple の公式の発見）で正の差があるものも研究の対象にする
    """
    gen = _parse_ts(generated_at, now)
    usable = bool(lookups) and gen is not None and timedelta(hours=-1) <= now - gen <= timedelta(hours=RETAIL_LOOKUP_MAX_AGE_HOURS)
    for r in dps:
        lk = (lookups or {}).get(r["candidate_id"]) if usable else None
        r["lookup_status"] = (lk or {}).get("status") or "NOT_ATTEMPTED"
        r["route_type"] = RETAIL_TO_BUYBACK
        sell = int(r.get("observed_sell_price") or 0)
        retail, basis_note = None, ""
        if isinstance(lk, dict) and lk.get("status") == "MATCHED" and isinstance(lk.get("price"), int) and lk["price"] > 0:
            at = _parse_ts(lk.get("observed_at"), now)
            if at is not None and timedelta(hours=-1) <= now - at <= timedelta(hours=RETAIL_LOOKUP_MAX_AGE_HOURS):
                retail = lk["price"]
                r["retail_caveat"] = str(lk.get("price_caveat") or "")
                # 価格の証拠（表示価格・通常の価格・ポイントは現金から引かず別の項目）。条件つきの値引きは現金の仕入れ値に使わない
                r.update({"retail_source_type": str(lk.get("source_type") or ""),
                          "retail_listed_price": lk.get("listed_price"), "retail_regular_price": lk.get("regular_price"),
                          "retail_campaign_price": lk.get("campaign_price"), "retail_points": int(lk.get("points") or 0),
                          "retail_cashback": int(lk.get("cashback") or 0),
                          "retail_conditions": list(lk.get("price_conditions") or []),
                          "retail_price_basis": str(lk.get("price_basis") or "UNCONDITIONAL"),
                          "retail_alternatives": list(lk.get("alternatives") or [])})
                r.update({"retail_price": retail, "retail_retailer": str(lk.get("retailer") or ""),
                          "retail_url": str(lk.get("product_url") or ""), "retail_observed_at": lk["observed_at"],
                          "retail_availability": str(lk.get("availability_state") or "UNKNOWN"),
                          "retail_identity_evidence": lk.get("identity_evidence") or {}})
                basis_note = "retail_lookup"
            else:
                r["lookup_status"] = "STALE_LOOKUP"
        elif isinstance(lk, dict) and lk.get("status") == "NOT_PURCHASABLE":
            r["missing_requirements"] = list(dict.fromkeys(list(r.get("missing_requirements") or []) + [OFFICIAL_NOT_SOLD]))
        if retail is None and isinstance(r.get("retail_price_hint"), int):
            retail, basis_note = r["retail_price_hint"], "official_discovery_hint"
        if retail is None:
            if RETAIL_PRICE_MISSING not in r["missing_requirements"]:
                r["missing_requirements"] = list(r["missing_requirements"]) + [RETAIL_PRICE_MISSING]
            r["research_class"] = STANDARD_RESEARCH
            continue
        spread = sell - retail
        r["raw_spread_hint"], r["positive_spread_hint"], r["retail_basis"] = spread, spread > 0, basis_note
        req = [x for x in r["missing_requirements"] if x not in ("OFFICIAL_PRICE_UNKNOWN", RETAIL_PRICE_MISSING)]
        if spread <= 0:
            r.update({"status": REJECTED, "missing_requirements": list(dict.fromkeys(req + [NO_SPREAD])),
                      "research_class": STANDARD_RESEARCH})
            continue
        req += [OFFICIAL_UNVERIFIED, PURCHASE_SHIPPING_UNKNOWN]
        conditional = bool(r.get("retail_conditions")) or r.get("retail_price_basis") not in (None, "UNCONDITIONAL")
        if conditional:
            req.append(ACQUISITION_CONDITIONAL)
        if basis_note == "retail_lookup" and r.get("retail_availability") in (None, "UNKNOWN"):
            req.append(STOCK_UNKNOWN)
        if r.get("retail_points"):
            # ポイント還元は現金と同額として引かない。参考の差（ポイントを現金と見なした場合）は別の項目に残す
            r["spread_if_points_counted"] = spread + int(r["retail_points"])
        # 買取の価格を取得した日が3日より古い（または読めない）ときは、高優先にしない（買取側の鮮度。選別と同じ基準）
        buy_fresh = False
        _bat = _parse_ts(r.get("observed_at"), now)
        if _bat is not None and timedelta(hours=-1) <= now - _bat <= timedelta(days=3):
            buy_fresh = True
        if not buy_fresh:
            req.append(BUY_STALE)
        # 型番コードだけの識別・買取の名前から拾った部品番号での引き当て（JAN と突き合わせていない）は、識別が部分的
        ev = r.get("retail_identity_evidence") or {}
        r["identity_status"] = "IDENTITY_PARTIAL" if (r.get("identity_basis") == IDENT_MODEL or (
            ev.get("method") == "part_exact" and not ev.get("attributes_verified"))) else "IDENTITY_CONFIRMED"
        if r["identity_status"] == "IDENTITY_PARTIAL":
            req.append(IDENTITY_PARTIAL)
        anomaly = spread > retail * ANOMALY_RATIO
        if anomaly:
            req.append(PRICE_ANOMALY_SUSPECTED)
        r.update({"status": RESEARCH_CANDIDATE, "missing_requirements": list(dict.fromkeys(req)),
                  "research_class": STANDARD_RESEARCH if anomaly or IDENTITY_PARTIAL in req or basis_note != "retail_lookup" or r.get("retail_caveat") or conditional or not buy_fresh
                  else HIGH_PRIORITY_RESEARCH})
    return dps


def discovered_products(unmatched: list[dict], now: datetime, retail_hints: dict | None = None) -> list[dict]:
    """買取の一覧にあるが正本に無い商品（DISCOVERED_PRODUCT_CANDIDATE）。正本には入れない（人が公式で確かめて登録する）。"""
    return rank_product_candidates(unmatched, now, retail_hints)[0]


# 台帳の snapshot に残す項目（見えなくなった候補を STALE として出すときに使う。これ以外は読まない）
SNAPSHOT_KEYS = ("product_identity", "route_type", "source", "observed_buy_price", "observed_sell_price",
                 "raw_spread", "known_cost_spread", "genre")
# 台帳の状態（Stage 0）。実行をまたいだ保持の有無と、同じ実行の中の再生成を区別する（偽の永続性を表示しない）
LEDGER_NOT_AVAILABLE = "NOT_AVAILABLE"                  # 台帳が無く、実行をまたいで保持する手段も無い（鍵なし）。初めて見た日はこの実行の中だけ
LEDGER_NEW_THIS_RUN = "NEW_THIS_RUN"                    # 保持する手段はあるが、前回の台帳が無い（初回・キャッシュのミス）。今回新しく作った
LEDGER_REUSED_WITHIN_RUN = "REUSED_WITHIN_RUN"          # 同じ実行の中の再生成が、この実行の最初の生成の台帳を読んだ（前回の実行から引き継いだものではない）
LEDGER_RESTORED_FROM_PREVIOUS_RUN = "RESTORED_FROM_PREVIOUS_RUN"  # 前回の実行の台帳を引き継いだ（暗号化したキャッシュ・手元の .private）
LEDGER_CORRUPT = "CORRUPT"                              # 台帳が壊れていた（形が違う・読めない）。捨てて作り直した
# 互換の別名（以前の値）
LEDGER_FRESH, LEDGER_RESTORED = LEDGER_NEW_THIS_RUN, LEDGER_RESTORED_FROM_PREVIOUS_RUN

_PROCESS_RUN_ID = __import__("uuid").uuid4().hex


def current_run_id() -> str:
    """今の実行の識別子（CI は GITHUB_RUN_ID と試行番号。手元はプロセスごと）。同じ実行の中の再生成を見分ける。"""
    import os
    rid = os.environ.get("GITHUB_RUN_ID")
    return f"gh-{rid}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}" if rid else f"proc-{_PROCESS_RUN_ID}"


def persistence_enabled() -> bool:
    """実行をまたいで台帳を保持する手段があるか（ワークフローが、鍵が有るときだけ RESEARCH_LEDGER_PERSISTENCE=enabled を出す）。"""
    import os
    return os.environ.get("RESEARCH_LEDGER_PERSISTENCE") == "enabled"


def classify_ledger(raw, run_id: str, persistent: bool) -> tuple[str, dict]:
    """読んだ台帳の中身から、台帳の状態と前回の候補を決める。raw は state.json の中身（無ければ None）。

    first_seen（初めて見た日）は、RESTORED_FROM_PREVIOUS_RUN のときだけ実行をまたいで意味を持つ。鍵が無い CI では
    実行をまたいだ保持が無いので、NOT_AVAILABLE（と同じ実行の再生成 REUSED_WITHIN_RUN）になる。
    """
    if raw is None:
        return (LEDGER_NEW_THIS_RUN if persistent else LEDGER_NOT_AVAILABLE), {}
    cands = raw.get("candidates") if isinstance(raw, dict) else None
    if not isinstance(cands, dict):
        return LEDGER_CORRUPT, {}
    if raw.get("run_id") == run_id:
        return LEDGER_REUSED_WITHIN_RUN, cands
    return LEDGER_RESTORED_FROM_PREVIOUS_RUN, cands


def first_seen_scope(ledger_state: str) -> str:
    """初めて見た日の意味: 実行をまたいで保持されているか。"""
    return "ACROSS_RUNS" if ledger_state == LEDGER_RESTORED_FROM_PREVIOUS_RUN else "THIS_RUN_ONLY"


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
    "priority_reasons", "note", "name", "url", "jan", "shop", "rows",
    # 買取起点の選別・小売の照会（Coverage Wave 2）の個別の項目
    "identity_value", "identity_basis", "retail_price", "retail_url", "retail_retailer", "retail_identity_evidence",
    "retail_observed_at", "retail_availability", "retail_basis", "retail_caveat", "raw_spread_hint", "retail_source_type", "retail_listed_price", "retail_regular_price",
    "retail_campaign_price", "retail_points", "retail_cashback", "retail_conditions", "retail_price_basis", "retail_alternatives",
    "spread_if_points_counted", "route_type", "identity_status", "adapter_stats", "api_sources", "triage", "queue_rank", "lookup_status",
    "rank", "rank_score", "retail_price_hint", "lookups", "tcg_events", "quality_by_source"})


# 公開の集計に出してよい理由の語彙（商品名・価格などの個別の値がキーに混ざらないように、既知の語彙だけを通す）
ALLOWED_REASONS = frozenset({
    OFFICIAL_UNVERIFIED, OFFICIAL_NOT_SOLD, BUY_NOT_ITEM_LEVEL, BUY_STALE, SELL_STALE, GENERIC_SELL_URL, IDENTITY_UNCONFIRMED,
    CONDITION_UNKNOWN, CONDITION_MISMATCH, STOCK_UNKNOWN, SELL_SAMPLE_INSUFFICIENT, PURCHASE_SHIPPING_UNKNOWN,
    RETAIL_PRICE_MISSING, IDENTITY_PARTIAL, CANONICAL_UNREGISTERED, ACQUISITION_CONDITIONAL,
    PRICE_ANOMALY_SUSPECTED, SELL_REJECTED, NET_NEGATIVE, NO_SELL_SIDE, NO_BUY_SIDE, NO_SPREAD,
    ABOVE_GENRE_MAX, NEEDS_CORROBORATION, PRICE_SPIKE})
ALLOWED_CONFIDENCE = frozenset({"high", "medium", "low"})
ALLOWED_RETAIL_ADAPTERS = frozenset({"nikon_direct", "sony_store", "samsung_jp", "apple_jp", "canon_store", "sofmap_new"})
ALLOWED_API_STATUS = frozenset({"PENDING_USER_CONFIGURATION", "KILL_SWITCH_OFF", "READY_NOT_IMPLEMENTED"})
ALLOWED_STATUS = frozenset(STATUSES)
ALLOWED_LEDGER = frozenset({LEDGER_NOT_AVAILABLE, LEDGER_NEW_THIS_RUN, LEDGER_REUSED_WITHIN_RUN,
                            LEDGER_RESTORED_FROM_PREVIOUS_RUN, LEDGER_CORRUPT})
# 件数の入れ子（キーも値も固定。上流の報告に項目が増えても、ここで通したものしか公開されない）
COVERAGE_KEYS = {
    "official_verified_coverage": ("verified", "total"),
    "buyback_exact_coverage": ("products_with_confirmed_sell", "total"),
    "marketplace_sold_coverage": ("valid_sold_rows",),
    "tcg_source_coverage": ("configured_sources", "implemented_collectors", "reachable_sources", "healthy_sources",
                            "blocked_sources", "unreachable_sources", "not_implemented_sources",
                            "sources_with_active_lottery", "lottery_events_found"),
    "tcg_event_quality": ("active_events", "with_application_start", "with_application_end", "with_winner_announcement",
                          "with_purchase_window", "with_action_url", "fully_dated"),
    "tcg_priority": ("DEADLINE_SOON", "ACTIVE_LOTTERY", "PREORDER_OPEN", "FIRST_COME", "RESTOCK", "UPCOMING"),
    "tcg_fast_lane": ("events_measured", "median_application_duration_hours", "median_age_at_observation_hours",
                      "windows_under_24h_at_observation", "observed_after_half_window", "tolerated_age_at_observation_hours_p25",
                      "suggested_max_detection_interval_hours", "date_precision_events"),
    "tcg_funnel": ("raw_announcements", "parsed_events", "review_required", "rejected", "active_lotteries", "sources_with_gap",
                   "sources_truncated", "detail_candidates", "detail_fetched", "skipped_due_to_limit", "skipped_ended",
                   "sources_list_ok", "sources_detail_ok", "sources_blocked", "sources_parser_degraded"),
}
TCG_CLASS_KEYS = ("WORKING", "IMPLEMENTED_BUT_BLOCKED", "ACCESSIBLE_UNIMPLEMENTED", "UNREACHABLE", "UNSUPPORTED")


def _count_dict(src, keys) -> dict:
    """許可したキーだけ、整数の値だけを通す（それ以外は捨てる）。"""
    src = src if isinstance(src, dict) else {}
    return {k: int(src[k]) for k in keys if isinstance(src.get(k), (int, float)) and not isinstance(src.get(k), bool)}


def _num_dict(src, keys) -> dict:
    """許可したキーだけ、数値（小数も）だけを通す。時間（0.5 時間など）を整数に切り捨てない。"""
    src = src if isinstance(src, dict) else {}
    return {k: (round(float(src[k]), 1) if isinstance(src[k], float) else int(src[k])) for k in keys
            if isinstance(src.get(k), (int, float)) and not isinstance(src.get(k), bool)}


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
        # 既存商品の調査候補 + 買取起点（正本に無い商品）の調査候補（小売の価格を同一性つきで引けて、買取の価格が上回るもの）
        "research_candidate_count": int(counts.get("research_candidates") or len(research)),
        "positive_raw_spread_count": int(m.get("raw_positive_spread") or 0),
        # 生の価格差が正のうち、確定の関門を通過した数と通過していない数（足すと positive_raw_spread_count になる）
        "verified_positive_spread_count": int(m.get("verified_positive_spread") or 0),
        "suppressed_positive_spread_count": int(m.get("suppressed_positive_spread") or 0),
        "verified_count": verified_n,
        "ledger_state": report.get("ledger_state") if report.get("ledger_state") in ALLOWED_LEDGER else None,
        # 初めて見た日が実行をまたいで保持されているか（鍵が無い CI では THIS_RUN_ONLY。偽の永続性を示さない）
        "first_seen_scope": first_seen_scope(report.get("ledger_state") or ""),
        "ledger_persistence": "ACROSS_RUNS" if report.get("ledger_persistence") == "ACROSS_RUNS" else "NOT_AVAILABLE",
        # Wave 1 の指標
        "high_priority_research_count": int(m.get("high_priority_research") or 0),
        "product_research_candidate_count": int(m.get("product_research_candidates") or 0),
        "buyback_first_candidates": int(m.get("buyback_first_candidates") or 0),
        "confirmed_opportunities": verified_n,
        "actionable": _int_or_none(m.get("actionable")),
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
                          for k in ("catalog_rows", "canonical_matches", "identified", "name_only_rejected",
                                    "new_product_candidates", "with_retail_hint", "positive_spread_hint",
                                    "top_queue", "lookup_ready", "lookup_matched", "research_candidates")},
        # 買取起点の選別（HIGH / MEDIUM / LOW / REJECTED の件数だけ。個別の候補は非公開）
        "buyback_triage": {k: int(((report.get("buyback_first") or {}).get("triage") or {}).get(k) or 0)
                           for k in ("HIGH", "MEDIUM", "LOW", "REJECTED")},
        "retail_lookup_matched": int(m.get("retail_lookup_matched") or 0),
        # 取得器ごとの照会の件数（取得器の ID は固定の語彙だけ通す。件数だけ）
        "retail_adapters": {aid: _count_dict(v, ("supported", "requested", "fetched", "matched", "no_match"))
                            for aid, v in (m.get("retail_adapters") or {}).items() if aid in ALLOWED_RETAIL_ADAPTERS and isinstance(v, dict)},
        "retail_api_sources": dict(Counter(a.get("status") for a in (m.get("retail_api_sources") or [])
                                           if isinstance(a, dict) and a.get("status") in ALLOWED_API_STATUS)),
        "official_discovery_candidates": int(m.get("official_discovery_candidates") or 0),
        "tcg_source_coverage": dict(_count_dict(m.get("tcg_source_coverage"), COVERAGE_KEYS["tcg_source_coverage"]),
                                    source_classes=_count_dict((m.get("tcg_source_coverage") or {}).get("source_classes"),
                                                               TCG_CLASS_KEYS)),
        "tcg_working_sources": _int_or_none(((m.get("tcg_source_coverage") or {}).get("source_classes") or {}).get("WORKING")),
        "tcg_funnel": dict(_count_dict((m.get("tcg_source_coverage") or {}).get("funnel"), COVERAGE_KEYS["tcg_funnel"]),
                           zero_active_interpretation=(m.get("tcg_source_coverage") or {}).get("funnel", {}).get("zero_active_interpretation")
                           if ((m.get("tcg_source_coverage") or {}).get("funnel") or {}).get("zero_active_interpretation")
                           in ("NOT_PROVEN_MARKET_EMPTY", "NO_KNOWN_COLLECTOR_GAP") else None),
        "tcg_active_events": _int_or_none(m.get("tcg_active_events")),
        "tcg_event_quality": _count_dict(m.get("tcg_event_quality"), COVERAGE_KEYS["tcg_event_quality"]),
        "tcg_priority": _count_dict(m.get("tcg_priority"), COVERAGE_KEYS["tcg_priority"]),
        "tcg_fast_lane": _num_dict(m.get("tcg_fast_lane"), COVERAGE_KEYS["tcg_fast_lane"]),
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
          ledger_state: str | None = None, quarantined: list[dict] | None = None,
          retail_hints: dict | None = None, actionable_count: int | None = None,
          quarantine_generated_at: str | None = None, retail_lookups: dict | None = None,
          retail_lookups_generated_at: str | None = None, tcg_events: list[dict] | None = None,
          retail_adapter_stats: dict | None = None, retail_api_sources: list[dict] | None = None) -> tuple[dict, dict]:
    """調査候補のレポート（運営者向け）と、次回の台帳。戻りは (report, new_state)。

    quarantined: 品質ゲートで隔離された買取価格（collector_report の suspicious_prices）。上限超え・急変・裏付け不足で
    確定から外れた価格差を、消さずに調査候補（HIGH_PRIORITY_RESEARCH）として残す。ジャンルの上限は自動で引き上げない。
    retail_hints: 小売の価格のヒント（部品番号 → 公式の発見の価格）。買取起点の候補の順位に使う（確定の価格ではない）。
    """
    q_obs = quarantine_observations(quarantined or [], products, now, quarantine_generated_at)
    cands = build_candidates(products=products, observations=list(observations) + q_obs, msrp_evidence=msrp_evidence,
                             official_meta=official_meta, verified_pids=verified_pids, now=now,
                             blocked_sources=blocked_sources)
    prev_clean = sanitize_ledger(prev_state)
    if ledger_state is None:
        ledger_state = LEDGER_RESTORED_FROM_PREVIOUS_RUN if prev_clean else LEDGER_NEW_THIS_RUN
    cands, new_state = apply_ledger(cands, prev_clean, now)
    order = {RESEARCH_CANDIDATE: 0, VERIFIED: 1, DISCOVERED: 2, STALE: 3, REJECTED: 4}
    cands.sort(key=lambda c: (order.get(c["status"], 9), -int(c.get("priority_score") or 0),
                              str((c.get("product_identity") or {}).get("product_id") or "")))
    for i, c in enumerate([c for c in cands if c["status"] == RESEARCH_CANDIDATE], 1):
        c["priority_rank"] = i
    matched, unmatched = match_catalog(catalog or [], products, identity or {})
    from src.research import retail_lookup as _rl
    from src.research import triage as _tr
    all_dps, bf_stats = rank_product_candidates(unmatched, now, retail_hints, limit=None)
    all_dps = apply_lookups(all_dps, retail_lookups, now, retail_lookups_generated_at)
    tri = _tr.triage(all_dps, now, lookup_ready_of=lambda c: _rl.ready_for_triage({"name": c.get("name", "")})
                     or isinstance(c.get("retail_price_hint"), int),
                     lookup_results={c["candidate_id"]: {"status": "MATCHED"} for c in all_dps if c.get("retail_price") is not None})
    by_id = {r["candidate_id"]: r for r in tri["rows"]}
    # 個別の一覧（非公開）: 上位 50 件の待ち行列 + 調査候補にした行（重複なし）。全件は件数だけ残す
    listed_ids = {r["candidate_id"] for r in tri["queue"]} | {c["candidate_id"] for c in all_dps if c["status"] == RESEARCH_CANDIDATE}
    for c in all_dps:                                   # 上限（CATALOG_LIST_LIMIT）まで、順位の高い行で埋める（従来の一覧の範囲）
        if len(listed_ids) >= CATALOG_LIST_LIMIT:
            break
        listed_ids.add(c["candidate_id"])
    dps = sorted((by_id[i] for i in listed_ids), key=lambda r: (r.get("queue_rank") or 10**6, r.get("rank") or 10**6, r["candidate_id"]))
    metrics = coverage_metrics(products=products, candidates=cands, product_candidates=all_dps,
                               msrp_evidence=msrp_evidence, observations=observations,
                               discovery=discovery, tcg=tcg)
    metrics["high_priority_research"] = sum(1 for c in cands if c.get("research_class") == HIGH_PRIORITY_RESEARCH)
    metrics["buyback_first_candidates"] = bf_stats["unique_candidates"]
    prod_research = [c for c in all_dps if c["status"] == RESEARCH_CANDIDATE]
    metrics["product_research_candidates"] = len(prod_research)
    metrics["high_priority_research"] += sum(1 for c in prod_research if c.get("research_class") == HIGH_PRIORITY_RESEARCH)
    from src.tcg import event_quality as _eq
    eq = _eq.evaluate(tcg_events or [], now)
    metrics["tcg_event_quality"] = eq["quality"]
    metrics["tcg_priority"] = eq["priority"]
    metrics["tcg_fast_lane"] = eq["fast_lane"]
    # 取得器ごとの照会の件数（対応する候補・取った件数・取れたページ・一致・不一致）。記録の生成時刻が新しいときだけ（古い日の数字を今日のものにしない）
    gen_ok = _parse_ts(retail_lookups_generated_at, now)
    metrics["retail_adapters"] = (retail_adapter_stats if isinstance(retail_adapter_stats, dict) and gen_ok is not None
                                  and timedelta(hours=-1) <= now - gen_ok <= timedelta(hours=RETAIL_LOOKUP_MAX_AGE_HOURS) else {})
    metrics["retail_api_sources"] = (retail_api_sources if isinstance(retail_api_sources, list) and metrics["retail_adapters"] != {} else []
                                     ) if gen_ok is not None and timedelta(hours=-1) <= now - gen_ok <= timedelta(hours=RETAIL_LOOKUP_MAX_AGE_HOURS) else []
    metrics["buyback_triage"] = dict(tri["stats"]["tier_counts"])
    metrics["buyback_top_queue"] = tri["stats"]["top_queue"]
    metrics["retail_lookup_ready"] = tri["stats"]["lookup_ready"]
    metrics["retail_lookup_matched"] = tri["stats"]["lookup_matched"]
    metrics["actionable"] = actionable_count
    reasons = Counter(r for c in cands + prod_research if c["status"] == RESEARCH_CANDIDATE for r in c["missing_requirements"])
    report = {
        "schema": SCHEMA, "type": "RESEARCH_CANDIDATES", "audience": "operator",
        "generated_at": now.isoformat(timespec="seconds"), "ledger_state": ledger_state,
        "note": "運営者向けの調査候補。確定の利益ではない。顧客向けの画面・LP・商品の通知には出さない（確認して VERIFIED に"
                "なるまで）。価格は観測した買値・売値だけ（予測は使わない）",
        "counts": {"research_candidates": metrics["research_candidates"] + len(prod_research), "verified": metrics["verified_candidates"],
                   "high_priority_research": metrics["high_priority_research"],
                   "discovered": metrics["by_status"].get(DISCOVERED, 0), "rejected": metrics["by_status"].get(REJECTED, 0),
                   "stale": metrics["by_status"].get(STALE, 0)},
        "research_reasons": dict(reasons.most_common()),
        "candidates": cands,
        "buyback_first": {"catalog_rows": len(catalog or []), "canonical_matches": len(matched),
                          "unmatched_rows": len(unmatched), "identified": bf_stats["identified"],
                          "name_only_rejected": bf_stats["name_only_rejected"],
                          "new_product_candidates": bf_stats["unique_candidates"], "listed": len(dps),
                          "with_retail_hint": bf_stats["with_retail_hint"],
                          "positive_spread_hint": bf_stats["positive_spread_hint"],
                          "triage": dict(tri["stats"]["tier_counts"]), "top_queue": tri["stats"]["top_queue"],
                          "lookup_ready": tri["stats"]["lookup_ready"], "lookup_matched": tri["stats"]["lookup_matched"],
                          "research_candidates": len(prod_research)},
        "product_candidates": dps,
        "tcg_events": eq["events"],                     # 非公開（イベントごとの応募の長さ・検知の遅れ。件数・中央値だけ公開）
        "metrics": metrics,
    }
    return report, new_state


def write_outputs(report: dict, state: dict, private_dir, public_dir, run_id: str | None = None) -> dict:
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
    tmp.write_text(json.dumps({"schema": SCHEMA, "updated_at": report["generated_at"], "run_id": run_id or current_run_id(),
                               "candidates": state}, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(priv / "state.json")
    (pub / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
