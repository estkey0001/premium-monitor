"""新UIの「商品詳細」の表示モデル（ProductDetailView。UI Phase 6）。

1商品（product_id）について、既存の正本だけから作る（collector の生データは読まない）:
- 利益・取得原価・ROI・費用の内訳: OpportunityView（opportunity.py。ここでも画面でも計算し直さない）
- せどりルート: RouteView（route_view.py）
- 在庫: RestockView（restock_view.py。在庫の状態の正本 stock_state）
- 抽選・予約: LotteryReservationView（lottery_view.py。状態は runtime だけで決める）
- 価格の種別: price_types、価格の根拠: price_evidence、公式の購入送料: official_shipping
- 店ごとの価格: 正規化データ（normalized_price_observations。商品の照合・鮮度・取得失敗の判定済み）
- 価格の履歴・変化: price_history（実際に観測した値だけ）・stock_history（在庫の状態の遷移）

同じページに出すのは同じ product_id の値だけ（容量・型番・版の違いは別の product_id）。
商品の照合が済んでいない価格・古い価格・参考価格は「参考」として出し、最安仕入・最高売却・利益・ROI には使わない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.content.ui import categories as cats
from src.content.ui import opportunity as opp
from src.content.ui import runtime as rt
from src.market import official_shipping as osh
from src.market import price_evidence as pe
from src.market import price_history as ph
from src.market import price_types as pt
from src.market import stock_state as ss
from src.tcg.models import JST, parse_dt

# 価格の種別のユーザー向けの呼び方（Task 22。内部の値は出さない）
TYPE_LABELS = {pt.RETAIL: "販売価格", pt.BUYBACK_CASH: "買取価格", pt.TRADE_IN: "下取り", pt.LISTING: "出品価格",
               pt.SOLD: "成約価格", pt.SOLD_MEDIAN: "成約中央値", pt.CONFIGURED_REFERENCE: "参考価格",
               pt.UNKNOWN: "未確認"}

# 価格の行の確かさ（画面に出す小さな印。内部の confidence の数値は出さない）
VERIFIED, REFERENCE, STALE, UNVERIFIED = "verified", "reference", "stale", "unverified"
QUALITY_LABELS = {VERIFIED: "確認済み", REFERENCE: "参考", STALE: "更新遅延", UNVERIFIED: "参考・商品照合未完了"}

# 利益を出せない理由（eligibility の理由 → 一般向けの言葉。判定そのものは opportunity.py）
REASON_LABELS = {
    "buy_configured_reference": "定価の確認日が分からない（公式での確認待ち）",
    "buy_unknown": "定価の根拠が分からない", "buy_stale": "定価の確認が古い",
    "stale_sell_price": "買取価格の確認が14日より前か、確認時刻が不明",
    "invalid_sell_price": "売却価格が未取得", "invalid_buy_price": "仕入れ価格が未取得",
    "purchase_shipping_unknown": "購入送料が分からない（公式で未確認）",
    "costs_unknown": "費用が分からない", "no_profit": "今の価格では利益が出ない",
    "resale_sell": "売り先が二次流通（買取店ではない）", "monitoring": "監視中（価格の取得待ち・赤字）",
    "roi_out_of_range": "利益率が表示できる範囲の外", "breakdown_mismatch": "利益の内訳が合わない",
    "buy_identity_unverified": "仕入れ側の商品の照合が未了", "sell_identity_unverified": "売却側の商品の照合が未了",
    "buy_not_item_level": "仕入れ先が商品ページ単位でない", "buy_url_not_item_level": "仕入れ先が商品ページ単位でない",
    "condition_mismatch": "商品の状態が違う・不明", "insufficient_sold_samples": "成約の件数・期間が足りない",
    "stale_buy_price": "仕入れ価格が古い",
}

# 最近の変化の種類（Task 37）
CHANGE_LABELS = {"PRICE_UP": "値上がり", "PRICE_DOWN": "値下がり", "STOCK_IN": "在庫あり", "STOCK_OUT": "在庫切れ",
                 "RESTOCK": "再入荷", "LOTTERY_OPEN": "抽選の受付開始", "LOTTERY_CLOSE": "抽選の受付終了",
                 "PREORDER_OPEN": "予約の受付開始", "PREORDER_CLOSE": "予約の受付終了",
                 "OFFICIAL_PRICE_CHANGE": "公式の定価の変更",
                 "SELL_PRICE_CHANGE": "買取価格の変化"}
CHANGE_DAYS = 30
# 在庫の変化の前後（その時点の状態。今も買えるとは言わない）
_AT_THE_TIME = {ss.IN_STOCK: "在庫あり", ss.OUT_OF_STOCK: "在庫切れ", ss.UNKNOWN: "在庫未確認"}
FRESH_DAYS = opp.MAX_AGE_DAYS


@dataclass
class PriceRow:
    role: str                       # buy / sell
    source: str
    price: int
    price_type: str                 # 正本の種別（price_types）
    quality: str                    # verified / reference / stale / unverified
    checked_at: str = ""            # 価格を確認した日時（観測時刻。生成時刻は入れない）
    shipping: int | None = None     # 購入送料（買う側）。分からなければ None
    shipping_label: str = ""
    required_cost: int | None = None
    acquisition: int | None = None  # 取得原価（買う側）。費用が分からなければ None
    cost_note: str = ""             # 売る側の費用（手数料・発送など）の説明
    samples: int | None = None
    period: str = ""
    stock_label: str = ""
    stock_checked_at: str = ""
    stock_until_ms: int | None = None   # 在庫ありと言える期限（過ぎたら画面で「更新待ち」に落とす）
    url: str = ""
    cta_label: str = ""
    cta_primary: bool = False
    note: str = ""
    condition: str = ""
    official: bool = False          # 公式ストアの行（定価）

    @property
    def type_label(self) -> str:
        # 公式ストアの販売価格は、利益の根拠と同じ「定価」と呼ぶ（同じ値の呼び方を揃える）
        if self.official and self.price_type == pt.RETAIL:
            return "定価"
        return TYPE_LABELS.get(self.price_type, "未確認")

    @property
    def quality_label(self) -> str:
        return QUALITY_LABELS.get(self.quality, "参考")

    @property
    def usable(self) -> bool:
        return self.quality == VERIFIED


@dataclass
class ProductDetailView:
    product_id: str
    category: str
    product_name: str
    brand: str = ""
    model: str = ""
    jan: str = ""
    variant: str = ""
    capacity: str = ""
    condition: str = "新品・未開封"
    identity_status: str = "商品ごとに照合（容量・型番・版の違いは別の商品）"
    status: str = "MONITORING"
    status_label: str = "監視中"
    status_until_ms: int | None = None
    fallback_status: str = "MONITORING"          # 受付中などの抽選・予約が無いときの状態（在庫などから決める）
    fallback_label: str = "監視中"
    last_verified_at: str = ""
    buy_rows: list[PriceRow] = field(default_factory=list)
    sell_rows: list[PriceRow] = field(default_factory=list)
    listing_refs: list = field(default_factory=list)
    sold_refs: list[PriceRow] = field(default_factory=list)
    opportunity: object = None                     # 掲載できる OpportunityView（無ければ None）
    profit_reasons: list[str] = field(default_factory=list)
    routes: list = field(default_factory=list)     # RouteView
    stock: object = None                           # RestockView（公式など。無ければ None）
    lotteries: list = field(default_factory=list)  # (LotteryReservationView, runtime の状態)
    history: list[dict] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)

    @property
    def category_label(self) -> str:
        return cats.LABELS.get(self.category, "その他")

    @property
    def alias(self) -> str:
        return self.product_id[len("prod_"):] if self.product_id.startswith("prod_") else self.product_id

    @property
    def best_buy(self) -> PriceRow | None:
        rows = [r for r in self.buy_rows if r.usable and r.acquisition is not None]
        return min(rows, key=lambda r: r.acquisition) if rows else None

    @property
    def best_sell(self) -> PriceRow | None:
        rows = [r for r in self.sell_rows if r.usable and r.price_type in pt.CONFIRMED_SELL_TYPES]
        return max(rows, key=lambda r: r.price) if rows else None

    @property
    def required_capital(self) -> float | None:
        """必要な仕入れ資金（仕入れ値 + 購入送料 + 購入時の費用）。利益があるときは OpportunityView の取得原価。"""
        if self.opportunity is not None:
            return self.opportunity.acquisition_cost
        b = self.best_buy
        return b.acquisition if b else None


def _age_days(iso: str, now: datetime) -> float | None:
    d = parse_dt(str(iso or "").replace(" ", "T", 1))
    return None if d is None else (now - d).total_seconds() / 86400


def _ms(iso: str) -> int | None:
    d = parse_dt(str(iso or "").replace(" ", "T", 1))
    return int(d.timestamp() * 1000) if d else None


def _quality(o: dict, now: datetime) -> str:
    """正規化データの観測1件の確かさ（照合・鮮度）。"""
    age = _age_days(o.get("observed_at"), now)
    if o.get("rejection_reason") == "stale_over_14d" or age is None or age > FRESH_DAYS or age < -1:
        return STALE
    if o.get("is_exact_product_match") is not True:
        return UNVERIFIED
    return VERIFIED


def _deal_sell_cost_note() -> str:
    """買取で売るときの費用（利益の計算の前提。opportunity._deal_cost_lines と同じ値）。"""
    lines = [(lbl, a) for k, lbl, a in opp._deal_cost_lines() if k != "buy_required" and a]
    return "・".join(f"{lbl} ¥{int(a):,}" for lbl, a in lines) + "（利益の計算の前提）"


def _official_row(pid: str, meta: dict, obs: list[dict], stock, now: datetime, deal_view) -> PriceRow | None:
    """公式で定価で買う行。定価は正規化データの公式の観測（根拠の区分つき）。"""
    off = next((o for o in obs if o.get("price_role") == "official" and (o.get("price") or 0) > 0), None)
    price = int(off["price"]) if off else int(meta.get("official_price") or 0)
    if price <= 0:
        return None
    evidence = pe.from_freshness_basis(off.get("freshness_basis")) if off else pe.UNKNOWN
    # 定価の根拠は、利益の判定に使った案件（OpportunityView）があればその根拠を使う（表示と判定を食い違わせない）
    if deal_view is not None and deal_view.buy_price == price:
        evidence = str(deal_view.buy_evidence or pe.UNKNOWN)
    url = rt.safe_url(meta.get("official_url") or "")
    ship = osh.purchase_shipping(pid, url, price)
    # 購入時の費用（カード手数料など）は利益の計算と同じ前提（opportunity._deal_cost_lines の buy_required）
    req = int(sum(a for k, _l, a in opp._deal_cost_lines() if k == "buy_required"))
    verified = pe.is_profit_eligible(evidence)
    row = PriceRow(role="buy", source=f'{meta.get("brand") or ""} 公式ストア'.strip(), price=price,
                   price_type=pt.RETAIL if verified else pt.CONFIGURED_REFERENCE,
                   quality=VERIFIED if verified else REFERENCE,
                   checked_at=str(off.get("observed_at") or "") if (off and verified) else "",
                   shipping=ship["fee"], required_cost=req, condition="新品",
                   shipping_label=(osh.STATUS_LABELS.get(ship["status"], "送料未確認")
                                   + (f'（{ship["checked_on"]} 確認）' if ship.get("checked_on") else "")),
                   url=url, note="" if verified else (
                       "公式の販売は終了（定価は参考）" if meta.get("sale_method") == "discontinued"
                       else "定価の確認日が分からない設定値（参考）"), official=True)
    if deal_view is not None and deal_view.buy_price == price and deal_view.acquisition_cost is not None:
        row.acquisition = int(deal_view.acquisition_cost)     # 利益の計算と同じ取得原価（計算し直さない）
    elif verified and ship["fee"] is not None:
        row.acquisition = price + int(ship["fee"]) + req
    # 在庫（公式の在庫の観測。確認の期限を過ぎたら「在庫あり」と言わない）
    if stock is not None:
        row.stock_label = stock.label(now)
        row.stock_checked_at = stock.last_checked_at
        if stock.available(now):
            row.stock_until_ms = _ms(stock.fresh_until)
    else:
        row.stock_label = "在庫未確認"
    if url:
        row.cta_primary = bool(stock is not None and stock.available(now))
        row.cta_label = "購入する" if row.cta_primary else "販売ページを見る"
    return row


def _same_condition(o: dict) -> bool:
    """監視している状態（新品・未開封）と同じ系統の価格か。中古・未使用・開封済みなど状態の違う価格は混ぜない。
    状態の記録が無い価格は False（行には出すが参考に下げる。_obs_row）。"""
    return opp._cond_family(o.get("condition")) == "new"


def _shown_condition(o: dict) -> bool:
    """表に出してよい状態か（新品の系統か、状態の記録が無いもの）。状態の違う価格は表に出さない。"""
    return opp._cond_family(o.get("condition")) in ("new", "")


def _obs_row(o: dict, role: str, now: datetime) -> PriceRow:
    from src.content.ui.route_view import _marketplace
    from src.models.sale_price import CONDITION_LABELS
    q = _quality(o, now)
    if q == VERIFIED and not _same_condition(o):
        q = REFERENCE                                  # 状態が分からない価格は確定に使わない
    t = pt.canonical(o.get("canonical_price_type"))
    url = rt.safe_url(o.get("item_url") or o.get("source_url") or "")
    # 情報元の名前（内部の ID は出さない。名前が無ければ市場名に読み替える）
    src = str(o.get("source_name") or "")
    if not src or src.startswith("src_"):
        src = _marketplace(o)
    row = PriceRow(role=role, source=src, price=int(o["price"]), price_type=t, quality=q,
                   checked_at=str(o.get("observed_at") or ""), url=url,
                   condition=CONDITION_LABELS.get(str(o.get("condition") or ""), ""))
    if role == "buy":
        # 店頭・出品で買うときの送料は観測に無い（0円とみなさない）。取得原価は算出前
        row.shipping_label = "送料未確認"
        if q == VERIFIED and pt.is_item_url(url):
            row.cta_label = "販売ページを見る"
    else:
        if t == pt.BUYBACK_CASH:
            row.cost_note = _deal_sell_cost_note()
            if url and q != STALE:
                row.cta_label = "買取ページを見る"
        else:
            row.cost_note = "手数料・発送費は未確認"
    if q == STALE and o.get("is_exact_product_match") is not True:
        row.note = "商品照合未完了"            # 古いうえに照合も済んでいない（更新遅延だけで隠さない）
        row.cta_label = ""
    if q == UNVERIFIED:
        row.cta_label = ""                     # 商品の照合が済んでいない価格から、購入・売却へ誘導しない
        if o.get("link_type") in ("search", "shop_home"):
            row.note = "検索結果・店のトップの価格"
    return row


def _sold_rows(obs: list[dict], now: datetime) -> tuple[list[PriceRow], list[PriceRow]]:
    """成約の値: 条件を満たす成約中央値（確定に使える）と、件数・期間が足りない成約（参考）。"""
    sells, refs = [], []
    for o in obs:
        t = pt.canonical(o.get("canonical_price_type"))
        if t not in (pt.SOLD, pt.SOLD_MEDIAN) or (o.get("price") or 0) <= 0 or not _shown_condition(o):
            continue
        row = _obs_row(o, "sell", now)
        row.samples = o.get("sample_count") if isinstance(o.get("sample_count"), int) else None
        ps, pe_ = str(o.get("sold_period_start") or ""), str(o.get("sold_period_end") or "")
        row.period = f"{ps[5:10].replace('-', '/')}〜{pe_[5:10].replace('-', '/')}" if ps and pe_ else ""
        eligible = (o.get("sold_median_eligible") is True and (row.samples or 0) >= pt.MIN_SOLD_SAMPLES
                    and bool(row.period))
        if eligible and row.quality == VERIFIED:
            row.price_type = pt.SOLD_MEDIAN
            row.cta_label = "市場を見る" if row.url else ""
            sells.append(row)
        else:
            row.price_type = pt.SOLD
            row.quality = REFERENCE if row.quality == VERIFIED else row.quality
            row.note = ("件数不足" if (row.samples is not None and row.samples < pt.MIN_SOLD_SAMPLES)
                        else "期間不明" if not row.period else "根拠未確認")
            row.cta_label = ""
            refs.append(row)
    return sells, refs


# 在庫の記録（stock_history の entries）の販売方法の状態の呼び方（在庫ありとは言わない）
_SALE_STATE_LABELS = {ss.LOTTERY: "抽選（公式の販売方法）", ss.RESERVATION: "予約受付（公式の表示）",
                      ss.PREORDER: "予約受付（公式の表示）", ss.RELEASE_WAIT: "発売待ち（公式の表示）"}


def _entry_status(entry: dict | None) -> tuple[str, str]:
    """在庫の記録だけがあるとき（在庫あり・再入荷の記録が無い）の状態。購入可能にはしない。
    「公式」と言うのは公式ストアの記録だけ（ほかの店の記録は店の表示と書く）。"""
    state = (entry or {}).get("state")
    if state == ss.OUT_OF_STOCK:
        return "OUT_OF_STOCK", "在庫切れ"
    if state in _SALE_STATE_LABELS:
        label = _SALE_STATE_LABELS[state]
        if (entry or {}).get("source_type") != "official_store":
            label = label.replace("（公式の販売方法）", "（店の販売方法）").replace("（公式の表示）", "（店の表示）")
        return "SALE_METHOD", label
    return "STOCK_UNKNOWN", "在庫未確認"


def _stock_status(stock, now: datetime, entry: dict | None = None) -> tuple[str, str]:
    """在庫から決める状態（抽選・予約を除く）。購入可能は確認の期限内の在庫ありだけ。"""
    if stock is None:
        return _entry_status(entry) if entry else ("MONITORING", "監視中")
    if stock.available(now):
        return "AVAILABLE", "購入可能"
    if stock.stock_state == ss.OUT_OF_STOCK:
        return "OUT_OF_STOCK", "在庫切れ"
    return "STOCK_UNKNOWN", stock.label(now)


def _status(stock, lotteries: list, now: datetime, entry: dict | None = None) -> tuple[str, str, int | None]:
    """ユーザー向けの今の状態（優先順: 購入可能 → 抽選・予約・発売待ち（受付中など） → 在庫切れ → 在庫未確認 → 監視中）。
    抽選の受付中は在庫ありではない（購入可能にはしない）。"""
    code, label = _stock_status(stock, now, entry)
    if code == "AVAILABLE":
        return code, label, _ms(stock.fresh_until)
    active = [st for _v, st in lotteries if st.get("bucket", 99) < rt.BUCKET_HIDDEN]
    if active:
        st = sorted(active, key=lambda s: (s.get("bucket", 99), s.get("sort", 0)))[0]
        return "LOTTERY", str(st.get("label") or "抽選・予約"), None
    return code, label, None


def _changes(pid: str, history: dict | None, stock_history: dict | None, lotteries: list, now: datetime) -> list[dict]:
    """最近の変化（実際の差分だけ。変化の前・後・時刻・情報元つき）。"""
    since = now - timedelta(days=CHANGE_DAYS)
    out = []
    for c in ph.changes(history, pid, since=since):
        if c["kind"] == ph.KIND_RETAIL:
            typ = "OFFICIAL_PRICE_CHANGE"
        elif c["kind"] == ph.KIND_BUYBACK:
            typ = "SELL_PRICE_CHANGE"
        else:
            typ = "PRICE_UP" if c["after"] > c["before"] else "PRICE_DOWN"
        label = (CHANGE_LABELS[typ] if typ in ("OFFICIAL_PRICE_CHANGE", "SELL_PRICE_CHANGE")
                 else f'{CHANGE_LABELS[typ]}（{ph.KIND_LABELS.get(c["kind"], "")}）')
        out.append({"type": typ, "label": label,
                    "before": f'¥{c["before"]:,}', "after": f'¥{c["after"]:,}', "changed_at": c["changed_at"],
                    "source": c["source"], "direction": "up" if c["after"] > c["before"] else "down"})
    kinds = {"RESTOCK": "RESTOCK", "SOLD_OUT": "STOCK_OUT", "FIRST_SEEN": "STOCK_IN"}
    for e in ((stock_history or {}).get("events") or []):
        if not isinstance(e, dict) or e.get("product_id") != pid or e.get("kind") not in kinds:
            continue
        at = parse_dt(str(e.get("transition_at") or "").replace(" ", "T", 1))
        if at is None or at < since:
            continue
        typ = kinds[e["kind"]]
        out.append({"type": typ, "label": CHANGE_LABELS[typ],
                    "before": _AT_THE_TIME.get(e.get("previous_state"), "在庫未確認"),
                    "after": _AT_THE_TIME.get(e.get("new_state"), "在庫未確認"),
                    "changed_at": e["transition_at"], "source": str(e.get("store") or ""), "direction": ""})
    pre = rt.KIND_PREORDER
    for v, _st in lotteries:
        for when, typ, is_end in ((v.application_start, "PREORDER_OPEN" if v.kind == pre else "LOTTERY_OPEN", False),
                                  (v.application_end, "PREORDER_CLOSE" if v.kind == pre else "LOTTERY_CLOSE", True)):
            raw = str(when or "").strip()
            if len(raw) == 10:
                # 日付だけの日程（時刻は告知に無い）: 時刻を作らない。終了はその日の終わり、開始はその日の始まりと比べる
                at = parse_dt(raw + ("T23:59:59+09:00" if is_end else "T00:00:00+09:00"))
                shown = raw
            else:
                at = parse_dt(raw.replace(" ", "T", 1))
                shown = at.isoformat() if at else ""
            if at is None or at < since or at > now or not v.source_url:
                continue                               # 公式の告知（情報元）がある、過ぎた日時だけ
            out.append({"type": typ, "label": CHANGE_LABELS[typ], "before": "", "after": v.retailer or v.store or "",
                        "changed_at": shown, "source": v.retailer or "公式の告知", "direction": "",
                        "url": v.source_url})
    return sorted(out, key=_change_order, reverse=True)


def _change_order(c: dict) -> tuple:
    """最近の変化の並び順（日付で比べ、同じ日の中は時刻つきの値を時刻で比べる。日付だけの値に時刻は作らない）。"""
    s = str(c.get("changed_at") or "")
    if len(s) == 10:
        return (s, 0)
    d = parse_dt(s.replace(" ", "T", 1))
    if d is None:
        return ("", 0)
    d = d.astimezone(JST)
    return (d.strftime("%Y-%m-%d"), d.timestamp())


def build(*, products: list[dict] | None, catalog, observations: list | None, price_history: dict | None,
          stock_history: dict | None, now: datetime) -> dict[str, ProductDetailView]:
    """商品ごとの詳細（product_id → ProductDetailView）。商品の一覧（products）に無い ID は作らない。"""
    s = getattr(catalog, "opportunity_set", None)
    eligible = list(s.eligible) if s else []
    ineligible = list(s.ineligible) if s else []
    obs_by = {}
    for o in observations or []:
        if isinstance(o, dict) and o.get("product_id"):
            obs_by.setdefault(str(o["product_id"]), []).append(o)
    out: dict[str, ProductDetailView] = {}
    for meta in products or []:
        pid = str(meta.get("product_id") or "")
        if not pid:
            continue
        name = str(meta.get("name") or pid)
        v = ProductDetailView(product_id=pid, category=cats.from_genre(meta.get("genre") or ""), product_name=name,
                              brand=str(meta.get("brand") or ""), model=str(meta.get("model") or ""),
                              jan=str(meta.get("jan") or ""), capacity=opp._capacity(name))
        obs = obs_by.get(pid, [])
        v.opportunity = next((x for x in eligible if x.product_id == pid), None)
        deal_view = next((x for x in eligible + ineligible
                          if x.product_id == pid and x.kind == "official_to_buyback"), None)
        stocks = [r for r in getattr(catalog, "restock_views", []) or [] if r.product_id == pid]
        official_stock = next((r for r in stocks if r.source_type == "official_store"), None)
        v.stock = official_stock or (stocks[0] if stocks else None)
        all_lots = [(lv, rt.derive_runtime_state(lv.vm, now)) for lv in getattr(catalog, "lottery_views", []) or []
                    if lv.product_id == pid and lv.vm]
        v.lotteries = [(lv, st) for lv, st in all_lots if st.get("bucket", 99) < rt.BUCKET_HIDDEN]
        # 在庫の状態の正本（stock_history の記録）。在庫再開に出ない記録（抽選・在庫切れ・不明）もここで読む
        entries = [e for e in ((stock_history or {}).get("entries") or {}).values()
                   if isinstance(e, dict) and e.get("product_id") == pid]
        entry = (next((e for e in entries if e.get("source_type") == "official_store"), None)
                 or (entries[0] if entries else None))
        v.status, v.status_label, v.status_until_ms = _status(v.stock, v.lotteries, now, entry)
        v.fallback_status, v.fallback_label = _stock_status(v.stock, now, entry)
        if v.fallback_status == "AVAILABLE":
            # 予備の表示は、在庫ありと言える期限が過ぎたあと（または抽選が締め切られたあと）に使う
            v.fallback_status, v.fallback_label = "STOCK_UNKNOWN", ss.STALE_LABEL
        # 買う
        off = _official_row(pid, meta, obs, official_stock, now, deal_view)   # 公式の行には公式ストアの在庫だけ
        off_entry = next((e for e in entries if e.get("source_type") == "official_store"), None)
        if off is not None and official_stock is None and off_entry:
            off.stock_label = _entry_status(off_entry)[1]
            off.stock_checked_at = str(off_entry.get("last_checked_at") or "")
        rows = [off] if off else []
        rows += [_obs_row(o, "buy", now) for o in obs if _shown_condition(o)
                 if o.get("price_role") == "buy" and (o.get("price") or 0) > 0
                 and pt.canonical(o.get("canonical_price_type")) != pt.UNKNOWN
                 and str(o.get("rejection_reason") or "") in ("", "stale_over_14d")]
        order = {VERIFIED: 0, REFERENCE: 1, UNVERIFIED: 2, STALE: 3}
        v.buy_rows = sorted(rows, key=lambda r: (order.get(r.quality, 9), r.acquisition is None,
                                                 r.acquisition if r.acquisition is not None else r.price))
        # 売る（買取・条件を満たす成約中央値。出品は参考欄、件数・期間が足りない成約は参考）
        sells = [_obs_row(o, "sell", now) for o in obs if _shown_condition(o)
                 if o.get("price_role") == "sell" and pt.canonical(o.get("canonical_price_type")) == pt.BUYBACK_CASH
                 and (o.get("price") or 0) > 0 and str(o.get("rejection_reason") or "") in ("", "stale_over_14d")]
        sold_ok, v.sold_refs = _sold_rows(obs, now)
        v.sell_rows = sorted(sells + sold_ok, key=lambda r: (order.get(r.quality, 9), -r.price))
        v.listing_refs = [r for r in getattr(catalog, "listing_refs", []) or [] if r.product_id == pid]
        v.routes = [r for r in getattr(catalog, "route_views", []) or [] if r.product_id == pid]
        if v.opportunity is None:
            why = [r for x in ineligible if x.product_id == pid for r in x.reasons]
            v.profit_reasons = list(dict.fromkeys(REASON_LABELS.get(r, "確定の条件を満たさない") for r in why))
            if not why:
                v.profit_reasons = (["有効な売却価格（買取価格・成約中央値）が未取得"] if not v.best_sell
                                    else ["確認済みの仕入れ先（送料などの費用が分かるもの）が無い"] if not v.best_buy
                                    else ["今の価格では利益が出ない（買取価格が仕入れ値と費用を下回る）"])
            if (deal_view is not None and off is not None and isinstance(deal_view.buy_price, (int, float))
                    and deal_view.buy_price > 0 and deal_view.buy_price != off.price):
                v.profit_reasons.insert(0, f"利益の判定は定価 ¥{int(deal_view.buy_price):,} で行った結果です"
                                           f"（表の定価 ¥{off.price:,} とは異なる値です）")
        # 価格の履歴（実際に観測した点だけ）・最近の変化
        v.history = [sr for sr in ((price_history or {}).get("series") or {}).values()
                     if sr.get("product_id") == pid and sr.get("points")]
        v.changes = _changes(pid, price_history, stock_history, all_lots, now)
        times = [r.checked_at for r in v.buy_rows + v.sell_rows if r.usable and r.checked_at]
        v.last_verified_at = max(times, key=lambda t: _ms(t) or 0) if times else ""
        out[pid] = v
    return out
