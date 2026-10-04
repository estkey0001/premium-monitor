"""新UIの「利益商品」の ViewModel（OpportunityView）と、一覧に出してよいかの判定（1か所）。

UI は collector の生データを直接見ない。ここで既存の出力（初心者向け案件・利益ルート）を
OpportunityView に変換し、掲載してよいか（eligibility）を判定する。

- 利益は再計算しない。純利益は既存の値（BeginnerDeal.net_profit_jpy / profit_routes.net_profit）をそのまま使う。
  費用の内訳は既存の定数・項目から並べ、合計が既存の「売値 − 仕入れ − 純利益」と一致するときだけ出す
- ROI = 想定純利益 ÷ 取得原価（仕入価格 + 購入送料 + 購入時必須費用）× 100（UI_VIEW_MODEL_SPEC §2）
- 売値として確定利益に使えるのは買取（BUYBACK_CASH）と、条件を満たした成約中央値（SOLD_MEDIAN）だけ。
  出品（LISTING）・種別不明（UNKNOWN）・根拠の無い成約は使わない（price_types.CONFIRMED_SELL_TYPES）
- 定価は確認済み（price_evidence が VERIFIED_*）のときだけ。確認日不明の設定値（CONFIGURED_REFERENCE）は使わない
- 古い価格（買取の確認から14日超）は一覧に出さない
- 商品の同一性: 初心者向け案件は同じ product_id の買取行（買取の取得は商品行と照合済み・容量や型の違いは別の product_id）。
  利益ルートは正規化データの同一性の判定（normalized_prices の identity_ok）を通ったものだけが作られる
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from src.content.ui import categories as cats
from src.content.ui import home
from src.market import price_evidence as pe
from src.market import price_types as pt
from src.tcg.models import JST, parse_dt

# 価格の鮮度（初心者タブの 14日超の降格・正規化データの STALE_DAYS と同じ線）
MAX_AGE_DAYS = 14

# 在庫・販売の状態（推測しない。分からなければ UNKNOWN）
# 在庫の状態 → 利益案件の種類
AVAILABILITY_OF = {"IN_STOCK": "BUY_NOW", "OUT_OF_STOCK": "OUT_OF_STOCK", "UNKNOWN": "PROFIT_STOCK_UNKNOWN",
                   "RESERVATION": "RESERVATION", "LOTTERY": "LOTTERY"}
AVAILABILITY_LABELS = {"BUY_NOW": "今買える", "PROFIT_STOCK_UNKNOWN": "利益あり・在庫未確認",
                       "RESERVATION": "予約", "LOTTERY": "抽選", "OUT_OF_STOCK": "在庫切れ"}
STOCK_LABELS = {"IN_STOCK": "在庫あり", "OUT_OF_STOCK": "在庫切れ", "UNKNOWN": "在庫未確認",
                "RESERVATION": "予約", "LOTTERY": "抽選"}

# ユーザー向けの価格種別（内部値は出さない）
SELL_TYPE_LABELS = {pt.BUYBACK_CASH: "買取価格", pt.SOLD_MEDIAN: "成約中央値", pt.LISTING: "出品価格",
                    pt.CONFIGURED_REFERENCE: "参考価格", pt.UNKNOWN: "未確認", pt.SOLD: "成約価格",
                    pt.RETAIL: "販売価格", pt.TRADE_IN: "下取り価格"}


@dataclass
class OpportunityView:
    id: str
    kind: str                       # official_to_buyback / shop_to_buyback / to_sold_median
    product_id: str
    category: str
    product_name: str
    model: str = ""
    variant: str = ""
    capacity: str = ""
    condition: str = ""
    # 買う
    buy_source: str = ""
    buy_price: float | None = None
    buy_price_label: str = ""       # 「定価」「販売価格・新品未開封」など
    buy_price_type: str = "RETAIL"  # 仕入れ値の種別（price_types）。定価で買う案件は RETAIL
    buy_shipping: float | None = 0
    buy_required_cost: float | None = 0
    buy_stock: str = "UNKNOWN"
    stock_checked_at: str = ""      # 在庫の表示を確認した日時（無ければ空）
    buy_checked_at: str = ""        # ISO（買い値を確認した日時。定価なら確認日）
    buy_url: str = ""
    buy_evidence: str = pe.UNKNOWN
    # 売る
    sell_source: str = ""
    sell_price_type: str = pt.UNKNOWN
    sell_price: float | None = None
    sell_period: str = ""           # 成約中央値の集計期間（例: 過去30日）
    sell_samples: int | None = None
    sell_fee: float | None = 0
    sell_shipping: float | None = 0
    sell_required_cost: float | None = 0
    sell_checked_at: str = ""
    sell_url: str = ""
    # 結果（既存の値。再計算しない）
    net_profit: float | None = None
    acquisition_cost: float | None = None
    roi: float | None = None        # 比率（0.14 = 14%）
    cost_lines: list[tuple[str, float]] = field(default_factory=list)
    breakdown_ok: bool = False      # 内訳の合計が既存の値と一致するか
    status: str = ""                # 一覧の状態（STOCK_LABELS のキー）
    priority: tuple = ()            # おすすめ順のキー（既存の確かさ・状態から）
    last_verified_at: str = ""      # 買い・売りのうち古い方の確認日時
    freshness: str = "UNKNOWN"      # FRESH / STALE / UNKNOWN
    flags: dict = field(default_factory=dict)  # 判定に使う元の値（suspicious など）
    eligible: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def sell_type_label(self) -> str:
        return SELL_TYPE_LABELS.get(self.sell_price_type, "未確認")

    @property
    def stock_label(self) -> str:
        return STOCK_LABELS.get(self.buy_stock, "在庫未確認")

    @property
    def availability(self) -> str:
        """利益案件の種類（今買える / 利益あり・在庫未確認 / 予約 / 抽選 / 在庫切れ）。

        「今買える」（BUY_NOW）は、公式の在庫表示が確認から7日以内の「在庫あり」のときだけ。
        在庫が分からない案件は利益の情報としては出せるが、今買えるとは言わない（PROFIT_STOCK_UNKNOWN）。
        """
        return AVAILABILITY_OF.get(self.buy_stock, "PROFIT_STOCK_UNKNOWN")

    @property
    def availability_label(self) -> str:
        return AVAILABILITY_LABELS[self.availability]


# ── 値の読み取り ────────────────────────────────────────────────────

def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _dt(v):
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=JST)).astimezone(JST)
    s = str(v or "").strip()
    return parse_dt(s.replace(" ", "T", 1)) if s else None


def _iso(v) -> str:
    d = _dt(v)
    return d.isoformat() if d else ""


def _age_days(v, now: datetime) -> float | None:
    d = _dt(v)
    return None if d is None else (now - d).total_seconds() / 86400


_CAP_RE = re.compile(r"(\d{2,4})\s*(GB|TB)", re.I)


def _capacity(name: str) -> str:
    m = _CAP_RE.search(name or "")
    return f"{m.group(1)}{m.group(2).upper()}" if m else ""


def stock_from(stock_status: str, sale_method: str) -> str:
    """公式の在庫表示・販売方式から在庫の状態を決める（推測しない。規則は src/market/stock_state.py）。"""
    from src.market.stock_state import stock_state
    return stock_state(stock_status, sale_method)


def _buy_label(r: dict) -> str:
    """定価以外の仕入れ値の種別と商品の状態（例: 「販売価格・新品未開封」）。"""
    from src.models.sale_price import CONDITION_LABELS
    kind = pt.label(r.get("buy_canonical_type"))
    if kind == "定価・販売価格":
        kind = "販売価格"
    cond = CONDITION_LABELS.get(str(r.get("buy_condition") or ""), "")
    return f"{kind}・{cond}" if cond else kind


# ── 変換 ─────────────────────────────────────────────────────────

# 初心者向け案件の費用（src/models/beginner_deal.DEFAULT_COSTS と同じ内訳。合計が既存の値と一致するときだけ出す）
def _deal_cost_lines() -> list[tuple[str, str, float]]:
    from src.models.beginner_deal import DEFAULT_COSTS as c
    return [("buy_required", "購入時の費用（カード手数料など）", 0.0),
            ("sell_shipping", "買取店への発送", float(c["shipping_jpy"])),
            ("sell_required", "振込手数料", float(c["transfer_fee_jpy"])),
            ("sell_required", "移動・持ち込みの費用", float(c["transport_jpy"])),
            ("sell_required", "保険", float(c["insurance_jpy"]))]


def from_deal(d: dict) -> OpportunityView:
    """定価で買って買取店に売る案件（daily_lp_generator が BeginnerDeal から作る dict）→ OpportunityView。"""
    pid = str(d.get("product_id") or "")
    name = str(d.get("title") or "")
    buy = _num(d.get("official_price"))
    sell = _num(d.get("sell_price"))
    net = _num(d.get("net_profit"))
    v = OpportunityView(
        id=f"deal:{pid}", kind="official_to_buyback", product_id=pid,
        category=cats.from_genre(d.get("genre")), product_name=name,
        model=str(d.get("model") or ""), capacity=_capacity(name), condition=str(d.get("condition") or ""),
        buy_source=str(d.get("buy_source") or (f"{d['brand']} 公式ストア" if d.get("brand") else "公式ストア")),
        buy_price=buy, buy_price_label="定価",
        buy_stock=stock_from(d.get("stock_status"), d.get("sale_method")),
        # 在庫の確認日時は価格の確認日時とは別（在庫の根拠があった取得の時刻。無ければ空 = 在庫未確認）
        stock_checked_at=_iso(d.get("stock_checked_at")),
        buy_checked_at=_iso(d.get("official_checked_at")), buy_url=str(d.get("official_url") or ""),
        buy_evidence=str(d.get("msrp_evidence") or pe.UNKNOWN),
        sell_source=str(d.get("sell_shop") or ""), sell_price_type=pt.BUYBACK_CASH, sell_price=sell,
        sell_checked_at=_iso(d.get("sell_checked_at")), sell_url=str(d.get("sell_url") or ""),
        net_profit=net,
        flags={"resale_sell": bool(d.get("resale_sell")), "user_level": str(d.get("user_level") or ""),
               "href": str(d.get("href") or "")},
    )
    lines = _deal_cost_lines()
    v.buy_required_cost = sum(a for k, _l, a in lines if k == "buy_required")
    v.sell_shipping = sum(a for k, _l, a in lines if k == "sell_shipping")
    v.sell_required_cost = sum(a for k, _l, a in lines if k == "sell_required")
    v.cost_lines = [(lbl, a) for _k, lbl, a in lines if a]
    _finish(v)
    level = v.flags["user_level"]
    v.priority = (0 if v.buy_stock == "IN_STOCK" else 1,
                  {"beginner_easy": 0, "beginner_watch": 1}.get(level, 2))
    return v


def from_route(r: dict, product_genres: dict | None = None) -> OpportunityView:
    """利益ルート（exports/profit_routes の main_routes の1件）→ OpportunityView。"""
    genres = product_genres or {}
    pid = str(r.get("product_id") or "")
    name = str(r.get("product_name") or "")
    sell_type = pt.canonical(r.get("sell_canonical_type"))
    is_sold_median = sell_type == pt.SOLD_MEDIAN
    v = OpportunityView(
        id=f"route:{pid}:{r.get('buy_source')}:{r.get('sell_source')}",
        kind="to_sold_median" if is_sold_median else "shop_to_buyback", product_id=pid,
        category=cats.from_genre(genres.get(pid, "")), product_name=name, capacity=_capacity(name),
        condition=str(r.get("buy_condition") or ""),
        buy_source=str(r.get("buy_source") or ""), buy_price=_num(r.get("buy_price")),
        buy_price_label=_buy_label(r), buy_price_type=pt.canonical(r.get("buy_canonical_type")),
        buy_stock="UNKNOWN", buy_checked_at=_iso(r.get("buy_observed_at")), buy_url=str(r.get("buy_url") or ""),
        buy_evidence=str(r.get("buy_price_evidence") or pe.UNKNOWN),
        sell_source=str(r.get("sell_source") or ""), sell_price_type=sell_type, sell_price=_num(r.get("sell_price")),
        sell_samples=r.get("sell_sample_count"), sell_period=str(r.get("sell_period") or ""),
        sell_checked_at=_iso(r.get("sell_observed_at")), sell_url=str(r.get("sell_url") or ""),
        net_profit=_num(r.get("net_profit")),
        flags={"route": r, "sell_evidence": str(r.get("sell_price_evidence") or pe.UNKNOWN)},
    )
    # 手数料が分からない（項目が無い）ときは 0 円とみなさない（算出前）。為替の余裕は海外以外は 0 が正しい値
    fees = [_num(r.get(k)) for k in ("platform_fee", "payment_fee")]
    v.sell_fee = (sum(fees) + (_num(r.get("fx_buffer")) or 0)) if all(f is not None for f in fees) else None
    # 仕入れ側の送料（購入送料）・購入時の費用は、ルートのデータに項目があるときだけ（無ければ不明 = 算出前。0円とみなさない）
    v.buy_shipping = _num(r.get("buy_shipping"))
    v.buy_required_cost = _num(r.get("buy_required_cost"))
    v.sell_shipping = _num(r.get("shipping_cost"))
    v.sell_required_cost = _num(r.get("safety_margin"))
    v.cost_lines = [(lbl, a) for lbl, a in (
        ("販売手数料", _num(r.get("platform_fee")) or 0), ("決済手数料", _num(r.get("payment_fee")) or 0),
        ("為替の余裕", _num(r.get("fx_buffer")) or 0), ("発送", _num(r.get("shipping_cost"))),
        ("安全マージン", _num(r.get("safety_margin")))) if a]
    _finish(v)
    conf = str(r.get("route_confidence") or "").lower()
    v.priority = (1, {"high": 0, "medium": 1}.get(conf, 2))
    return v


def _finish(v: OpportunityView) -> None:
    """取得原価・ROI・内訳の一致・最終確認日時を埋める（純利益は既存の値のまま）。"""
    parts = (v.buy_price, v.buy_shipping, v.buy_required_cost)
    v.acquisition_cost = sum(parts) if all(p is not None for p in parts) else None
    sell_costs = (v.sell_fee, v.sell_shipping, v.sell_required_cost)
    if (v.acquisition_cost is not None and v.sell_price is not None and v.net_profit is not None
            and all(c is not None for c in sell_costs)):
        expected = v.sell_price - v.acquisition_cost - sum(sell_costs)
        v.breakdown_ok = abs(expected - v.net_profit) < 0.5
    v.roi = (v.net_profit / v.acquisition_cost
             if v.net_profit is not None and v.acquisition_cost and v.acquisition_cost > 0 else None)
    # 一覧の「情報確認」: 動く価格（買取・仕入れ）を確認した時刻のうち古い方。
    # 定価は固定値で、確認日（最長180日まで有効）は詳細に出す（一覧では「更新遅延」に見せない）
    moving = (v.sell_checked_at,) if v.kind == "official_to_buyback" else (v.buy_checked_at, v.sell_checked_at)
    times = [t for t in moving if t]
    v.last_verified_at = min(times) if times else ""
    v.status = v.buy_stock


# ── 掲載してよいか（1か所） ────────────────────────────────────────────

def eligibility(v: OpportunityView, now: datetime) -> tuple[str, ...]:
    """利益商品の一覧に出せない理由（空なら出せる）。"""
    reasons: list[str] = []
    if not home.price_ok(v.buy_price):
        reasons.append("invalid_buy_price")
    if not home.price_ok(v.sell_price):
        reasons.append("invalid_sell_price")
    if not home.price_ok(v.net_profit):
        reasons.append("no_profit")
    # 売値の種別: 買取か、条件（件数・期間）を満たした成約中央値だけ
    if v.sell_price_type not in pt.CONFIRMED_SELL_TYPES:
        reasons.append(f"sell_type_{v.sell_price_type.lower()}")
    elif v.sell_price_type == pt.SOLD_MEDIAN and not (
            isinstance(v.sell_samples, int) and v.sell_samples >= pt.MIN_SOLD_SAMPLES and v.sell_period):
        reasons.append("insufficient_sold_samples")
    # 仕入れ値の根拠（定価は確認済みのものだけ。設定値の参考価格は使わない）
    if not pe.is_profit_eligible(v.buy_evidence):
        reasons.append(f"buy_{str(v.buy_evidence).lower()}")
    # 仕入れ値の種別が分からない（定価か販売価格か出品か不明）ものは、何の値段で買うのか示せないので出さない
    if v.buy_price_type in (pt.UNKNOWN, pt.CONFIGURED_REFERENCE):
        reasons.append(f"buy_type_{v.buy_price_type.lower()}")
    # 鮮度: 売値は確認から14日以内。仕入れ値（定価以外）も14日以内
    sell_age = _age_days(v.sell_checked_at, now)
    if sell_age is None or sell_age > MAX_AGE_DAYS or sell_age < -1:
        reasons.append("stale_sell_price")
    if v.kind != "official_to_buyback":
        buy_age = _age_days(v.buy_checked_at, now)
        if buy_age is None or buy_age > MAX_AGE_DAYS or buy_age < -1:
            reasons.append("stale_buy_price")
    # 費用が分からなければ純利益は「算出前」（0円とみなさない）
    if v.acquisition_cost is None or any(c is None for c in (v.sell_fee, v.sell_shipping, v.sell_required_cost)):
        reasons.append("costs_unknown")
    if not home.roi_ok(v.roi):
        reasons.append("roi_out_of_range")
    # 案件ごとの除外（二次流通の売り先・監視中・疑わしい・参考扱いのルート）
    if v.flags.get("resale_sell"):
        reasons.append("resale_sell")
    if v.flags.get("user_level") in ("monitoring", "fetch_failed"):
        reasons.append("monitoring")
    r = v.flags.get("route")
    if isinstance(r, dict):
        why = home.route_reject_reason(r)
        if why:
            reasons.append(f"route_{why}")
        reasons.extend(route_identity_reasons(r))
        # 費用がすべて分かっているのに、内訳（売値 − 取得原価 − 費用）と純利益が合わないものは出さない
        # （購入送料などが純利益に入っていないと、利益が実際より大きく出るため）
        if (v.acquisition_cost is not None and not v.breakdown_ok
                and all(c is not None for c in (v.sell_fee, v.sell_shipping, v.sell_required_cost))):
            reasons.append("breakdown_mismatch")
    return tuple(dict.fromkeys(reasons))


# 商品の状態の系統（新品と中古を混ぜない）
# 新品と未使用（中古店の未使用品など）は別の系統として扱う（新品の価格と組み合わせない）
_NEW_CONDITIONS = ("new", "new_unopened", "新品")
_UNUSED_CONDITIONS = ("unused", "未使用")
_USED_CONDITIONS = ("used", "used_a", "used_b", "used_c", "used_s", "中古")


def _cond_family(c) -> str:
    s = str(c or "").strip().lower()
    if s in _NEW_CONDITIONS:
        return "new"
    if s in _UNUSED_CONDITIONS:
        return "unused"
    if s in _USED_CONDITIONS or s.startswith("used"):
        return "used"
    return ""


def route_identity_reasons(r: dict) -> list[str]:
    """利益ルート（定価以外で仕入れる）の商品の同一性・状態の理由（空なら問題なし）。

    - 仕入れ・売却の両方で商品の同一性が確認済み（正規化データの is_exact_product_match）。無い・False は未確認
    - 二次流通（出品）で仕入れる場合は、商品ページ単位の URL がある（検索結果の価格は実際に買える同じ商品と言えない）
    - 仕入れと売却の商品の状態の系統（新品・中古）が分かっていて、同じ
    """
    out = []
    if r.get("buy_exact_match") is not True:
        out.append("buy_identity_unverified")
    if r.get("sell_exact_match") is not True:
        out.append("sell_identity_unverified")
    buy_type = pt.canonical(r.get("buy_canonical_type"))
    # 成約価格（売れた価格）では仕入れられない
    if buy_type in (pt.SOLD, pt.SOLD_MEDIAN):
        out.append("buy_type_sold")
    # 二次流通（正規店の新品以外）で仕入れる場合は、実際に買える商品ページ単位の URL があること
    secondary = not (buy_type == pt.RETAIL and _cond_family(r.get("buy_condition")) == "new")
    if secondary and not str(r.get("buy_item_url") or "").startswith("https://"):
        out.append("buy_not_item_level")
    bf, sf = _cond_family(r.get("buy_condition")), _cond_family(r.get("sell_condition"))
    if not bf or not sf or bf != sf:
        out.append("condition_mismatch")
    return out


# 在庫の表示を「在庫あり／在庫切れ」と言ってよいのは、確認から CURRENT_DAYS（7日）以内のときだけ
def _apply_stock_freshness(v: OpportunityView, now: datetime) -> None:
    if v.buy_stock not in ("IN_STOCK", "OUT_OF_STOCK"):
        return
    age = _age_days(v.stock_checked_at, now)
    if age is None or age > pe.CURRENT_DAYS or age < -1:
        v.buy_stock = "UNKNOWN"
        v.status = "UNKNOWN"
        v.priority = (1,) + tuple(v.priority[1:])


@dataclass
class OpportunitySet:
    eligible: list[OpportunityView]
    ineligible: list[OpportunityView]


def build(*, deals: list[dict] | None, routes: list[dict] | None, product_genres: dict | None,
          now: datetime) -> OpportunitySet:
    """利益商品の候補を作り、掲載できるものとできないものに分ける。同じ商品・同じルートは1件にする。"""
    views = [from_deal(d) for d in deals or [] if isinstance(d, dict)]
    views += [from_route(r, product_genres) for r in routes or [] if isinstance(r, dict)]
    # 同じ商品の案件が複数あるときは、掲載できるもののうち純利益の大きい1件を残す
    views.sort(key=lambda v: -(v.net_profit or 0))
    ok, ng, seen = [], [], set()
    for v in views:
        _apply_stock_freshness(v, now)
        v.reasons = eligibility(v, now)
        v.eligible = not v.reasons
        age = _age_days(v.last_verified_at, now)
        v.freshness = "UNKNOWN" if age is None else ("FRESH" if age <= MAX_AGE_DAYS else "STALE")
        if v.eligible and v.id not in seen:
            seen.add(v.id)
            ok.append(v)
        else:
            ng.append(v)
    # 既定の並び（おすすめ）: 在庫あり → 既存の確かさ → 純利益の大きい順
    ok.sort(key=lambda v: (v.priority, -(v.net_profit or 0), v.product_name))
    return OpportunitySet(ok, ng)
