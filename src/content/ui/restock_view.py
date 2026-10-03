"""新UIの「在庫再開」の表示モデル（RestockView。UI Phase 4）。

元データは在庫の状態の履歴（exports/stock_history/latest.json。src/market/stock_history）だけ。
- stock_state: 最後に取得に成功した観測の在庫の状態
- last_checked_at: その観測の時刻（取得に失敗した実行では更新されない）
- restocked_at: 在庫切れを確認した後に在庫ありを確認した時刻（再入荷）。初めての在庫ありは first_seen_at（在庫確認）
- 購入可能: 在庫あり・確認から stock_state.freshness_seconds 以内・公式（承認済み）の https の販売ページがある・
  商品が特定できる、をすべて満たすときだけ。期限はブラウザでも閲覧時の時刻で判定し直す（fresh_until）
- 想定利益: 利益商品（opportunity.eligibility を通ったもの）と同じ商品で、販売価格が仕入れ値と一致するときだけ
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.content.ui import categories as cats
from src.content.ui import runtime as rt
from src.market import stock_state as ss
from src.tcg.models import JST, parse_dt


@dataclass
class RestockView:
    key: str
    product_id: str
    category: str
    product_name: str
    variant: str
    condition: str
    retailer: str
    stock_state: str
    previous_stock_state: str
    restocked_at: str
    first_seen_at: str
    last_checked_at: str
    last_success_at: str
    fresh_until: str
    price: int | None
    price_observed_at: str
    purchase_limit: str
    purchase_url: str
    source_url: str
    source_type: str
    event_type: str
    profit: int | None = None
    roi: float | None = None
    profit_status: str = "算出前"

    @property
    def category_label(self) -> str:
        return cats.LABELS.get(self.category, "その他")

    def fresh(self, now: datetime) -> bool:
        until = parse_dt(self.fresh_until) if self.fresh_until else None
        return until is not None and now < until

    def available(self, now: datetime) -> bool:
        """今「購入可能」と言ってよいか（ブラウザ側の判定 stockRuntime と同じ条件）。"""
        until = parse_dt(self.fresh_until) if self.fresh_until else None
        return (self.stock_state == ss.IN_STOCK and until is not None and now < until
                and bool(self.purchase_url) and bool(self.product_name))

    def label(self, now: datetime) -> str:
        if self.stock_state == ss.IN_STOCK and not self.available(now):
            # 確認の期限を過ぎたら、販売ページの有無に関係なく「更新待ち」（今も在庫があるとは言わない）
            if not self.fresh(now):
                return ss.STALE_LABEL
            return "在庫あり（販売ページ未確認）"
        return ss.STATE_LABELS.get(self.stock_state, "在庫未確認")


# TCG の商品の状態（BOX とシュリンク付き BOX などを混同しない。内部コードは画面に出さない）
VARIANT_LABELS = {"SEALED_SHRINK": "シュリンク付きBOX", "SHRINK_REMOVED": "シュリンクなしBOX", "TAPE_CUT": "テープ切りBOX",
                  "OPENED_BOX": "開封済みBOX", "PACK_ONLY": "パック単位", "BOX": "BOX"}


def _variant(code: str) -> str:
    c = str(code or "").upper()
    if c in ("", "UNKNOWN"):
        return ""
    return VARIANT_LABELS.get(c, "")


def _store_label(store: str, source_type: str) -> str:
    if source_type == "tcg_event":
        from src.content.ui.catalog import _store_label as tcg_label
        return tcg_label(store)
    return store or "公式ストア"


def _int(v) -> int | None:
    x = rt._num(v)
    return int(x) if x is not None and x > 0 else None


def build(history: dict | None, *, opportunity_set=None, now: datetime | None = None) -> list[RestockView]:
    """一覧に出す記録（今在庫ありのもの・再入荷／在庫確認の履歴があるもの）を表示モデルにする。"""
    now = (now or datetime.now(tz=JST)).astimezone(JST)
    entries = (history or {}).get("entries") or {}
    by_pid: dict = {}
    if opportunity_set is not None:
        for o in opportunity_set.eligible:
            if o.kind == "official_to_buyback":
                by_pid.setdefault(o.product_id, o)
    out: list[RestockView] = []
    for key, e in sorted(entries.items()):
        if not isinstance(e, dict):
            continue
        state = e.get("state") if e.get("state") in ss.STOCK_STATES else ss.UNKNOWN
        restocked, first = str(e.get("restocked_at") or ""), str(e.get("first_seen_in_stock_at") or "")
        # 予約・抽選・発売待ち・未確認で、在庫ありを確認したことが無いものは出さない（抽選・予約のページで扱う）
        if state != ss.IN_STOCK and not (restocked or first):
            continue
        checked = parse_dt(str(e.get("last_checked_at") or "").replace(" ", "T", 1))
        if checked is None:
            continue
        secs = ss.freshness_seconds(str(e.get("source_type") or ""), str(e.get("event_type") or ""))
        source_type = str(e.get("source_type") or "")
        category = "tcg" if source_type == "tcg_event" else cats.from_genre(str(e.get("category") or ""))
        v = RestockView(
            key=key, product_id=str(e.get("product_id") or ""), category=category,
            product_name=str(e.get("product_name") or ""), variant=_variant(e.get("variant")),
            condition=str(e.get("condition") or ""), retailer=_store_label(str(e.get("store") or ""), source_type),
            stock_state=state, previous_stock_state=str(e.get("previous_state") or ""),
            restocked_at=restocked, first_seen_at=first, last_checked_at=checked.isoformat(),
            last_success_at=checked.isoformat(),
            # 在庫ありの観測だけが期限を持つ（ほかの状態は購入可能にならない）
            fresh_until=(checked + timedelta(seconds=secs)).isoformat() if state == ss.IN_STOCK else "",
            price=_int(e.get("price")), price_observed_at=str(e.get("price_observed_at") or ""),
            purchase_limit=str(e.get("purchase_limit") or ""),
            # 購入のボタンは公式（承認済み）の https の販売ページだけ（runtime.official_url の判定）
            purchase_url=rt.official_url(e.get("url")), source_url=rt.official_url(e.get("source_url")),
            source_type=source_type, event_type=str(e.get("event_type") or ""))
        o = by_pid.get(v.product_id)
        if o is not None and v.price is not None and o.buy_price is not None and int(o.buy_price) == v.price:
            v.profit, v.roi, v.profit_status = int(o.net_profit), o.roi, "算出済み"
        out.append(v)
    return out
