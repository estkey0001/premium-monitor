"""新UIの「抽選・予約」の表示モデル（LotteryReservationView。UI Phase 3）。

状態・残り時間・ボタンは runtime（derive_runtime_state / lottery_runtime.js）だけが決める。ここでは
収集データ（exports/tcg/latest.json の lotteries・events、旧来の抽選）を、一覧に出す値に写し取るだけで、
日時・価格・条件を推測で補わない。

- 販売価格: 公式の情報で確認できたものだけ（TCG の抽選の retail_price、発売予定の「商品1点の価格」）。
  旧来の抽選（公式ストアの抽選。lottery_events.csv）の価格は公式ページの読み取りに誤りがある（例: 定価と別の額）
  ので使わず、同じ商品の確認済みの定価（利益商品の仕入れ値。公式で確認日付き）があるときだけそれを出す
- 市場参考・想定利益: 利益商品（opportunity.eligibility を通った OpportunityView）がある商品だけ。
  販売価格と利益商品の仕入れ値が一致するときだけ想定利益を出し、それ以外は「算出前」。
  出品価格・根拠の無い価格では出さない。TCG は BOX / シュリンク付き / パック単位を混同しないため、
  同じ状態の成約・買取データが無い今は算出しない
- 応募条件: 収集で明示された項目だけ（True のものだけを出す。None は不明で、出さない）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.content.ui import categories as cats
from src.content.ui import runtime as rt

# 収集データの条件の項目 → 表示（True のときだけ出す）
REQUIREMENT_FLAGS = (
    ("membership_required", "会員登録が必要"),
    ("app_required", "アプリから応募"),
    ("identity_verification_required", "本人確認あり"),
    ("purchase_history_required", "購入履歴が必要"),
    ("store_pickup_required", "店舗受取"),
    ("online_only", "オンライン応募のみ"),
)
REQUIREMENTS_UNKNOWN = "条件は公式ページで確認"
KIND_LABELS = {rt.KIND_LOTTERY: "抽選", rt.KIND_PREORDER: "予約", rt.KIND_RELEASE: "発売待ち"}
EVENT_TYPE_OF_KIND = {rt.KIND_LOTTERY: "LOTTERY", rt.KIND_PREORDER: "PREORDER", rt.KIND_RELEASE: "RELEASE_WAIT"}


@dataclass
class LotteryReservationView:
    event_id: str
    kind: str                         # lottery / preorder / release（runtime の VM の k）
    event_type: str                   # LOTTERY / PREORDER / RELEASE_WAIT
    category: str
    product_name: str
    product_id: str = ""
    variant: str = ""                 # TCG の状態（BOX / パック単位など）。分かるときだけ
    retailer: str = ""
    store: str = ""
    region: str = ""
    channel: str = ""
    application_start: str = ""
    application_end: str = ""
    winner_announcement_at: str = ""
    purchase_start: str = ""
    purchase_end: str = ""
    release_at: str = ""
    retail_price: int | None = None
    retail_price_label: str = "価格未発表"
    market_reference_price: int | None = None
    market_reference_type: str = ""   # 買取参考 / 成約中央値（根拠が無ければ空）
    estimated_profit: int | None = None
    profit_status: str = "算出前"
    eligibility: str = ""             # 公式の応募条件の文（あるときだけ）
    requirements: list[str] = field(default_factory=list)
    official_url: str = ""            # 応募・予約のページ（公式の https だけ。runtime の apply）
    source_url: str = ""              # 情報元（公式の https だけ）
    source_type: str = ""
    confidence: str = ""              # 公式確認済み / 公式情報 / 確認待ち / 参考情報 / 日程要確認
    human_confirmed: bool = True
    source_conflict: bool = False
    last_verified_at: str = ""        # 情報を確認した日時（生成時刻ではない）
    vm: dict = field(default_factory=dict)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, "抽選")

    @property
    def category_label(self) -> str:
        return cats.LABELS.get(self.category, "その他")


def _int_price(v) -> int | None:
    x = rt._num(v)
    return int(x) if x is not None and x > 0 else None


def _requirements(ev: dict) -> list[str]:
    out = [label for key, label in REQUIREMENT_FLAGS if ev.get(key) is True]
    pay = str(ev.get("payment_method_requirement") or "").strip()
    if pay:
        out.append(f"支払い: {pay}")
    pref = str(ev.get("prefecture") or "").strip()
    if pref:
        out.append(f"地域: {pref}")
    return out


def _profit(v: LotteryReservationView, views_by_pid: dict, *, adopt_msrp: bool = False) -> None:
    """利益商品（掲載可）と同じ商品で、販売価格が仕入れ値と一致するときだけ想定利益を出す。

    adopt_msrp=True（公式ストアの抽選）は、販売価格が未取得なら利益商品の確認済みの定価を販売価格にする。
    """
    if not v.product_id:
        return
    for o in views_by_pid.get(v.product_id, []):
        if not o.eligible or o.kind != "official_to_buyback":
            continue
        if adopt_msrp and v.retail_price is None and o.buy_price:
            v.retail_price, v.retail_price_label = int(o.buy_price), f"{o.buy_price_label or '定価'}（公式で確認済み）"
        v.market_reference_price = int(o.sell_price) if o.sell_price else None
        v.market_reference_type = {"BUYBACK_CASH": "買取参考", "SOLD_MEDIAN": "成約中央値"}.get(o.sell_price_type, "")
        if v.retail_price is not None and o.buy_price is not None and int(o.buy_price) == v.retail_price:
            v.estimated_profit = int(o.net_profit)
            v.profit_status = "算出済み"
        return


def _from_tcg(vm: dict, ev: dict) -> LotteryReservationView:
    price = _int_price(ev.get("retail_price"))
    shrink = str(ev.get("shrink_status") or "")
    store = str(ev.get("store_name") or "") if ev.get("store_specific") else ""
    return LotteryReservationView(
        event_id=vm["id"], kind=vm.get("k") or rt.KIND_LOTTERY,
        event_type=EVENT_TYPE_OF_KIND.get(vm.get("k"), "LOTTERY"), category="tcg",
        product_name=vm.get("t") or "", product_id=str(ev.get("product_id") or ""),
        variant={"PACK_ONLY": "パック単位", "BOX": "BOX", "SEALED_SHRINK": "シュリンク付きBOX"}.get(shrink, ""),
        retailer=str(ev.get("retailer_name") or ev.get("retailer") or ""), store=store,
        region=str(ev.get("region") or ""), channel=str(ev.get("channel") or ""),
        application_start=vm.get("as") or vm.get("asd") or "", application_end=vm.get("ae") or vm.get("aed") or "",
        winner_announcement_at=vm.get("wa") or vm.get("wad") or "",
        purchase_start=vm.get("ps") or vm.get("psd") or "", purchase_end=vm.get("pe") or vm.get("ped") or "",
        retail_price=price, retail_price_label="販売価格" if price else "価格未発表",
        eligibility=str(ev.get("eligibility_text") or "").strip(),
        requirements=_requirements(ev) or [REQUIREMENTS_UNKNOWN],
        official_url=vm.get("apply") or "", source_url=vm.get("info") or "",
        source_type=str(ev.get("source_type") or ev.get("collection_method") or ""),
        confidence=vm.get("conf") or "", human_confirmed=not vm.get("unv"),
        source_conflict=bool(vm.get("conflict")),
        last_verified_at=str(ev.get("last_verified_at") or ev.get("observed_at") or ""), vm=vm)


def _from_legacy(vm: dict, it: dict, category: str) -> LotteryReservationView:
    return LotteryReservationView(
        event_id=vm["id"], kind=rt.KIND_LOTTERY, event_type="LOTTERY", category=category,
        product_name=vm.get("t") or "", product_id=str(it.get("product_id") or ""),
        retailer=str(it.get("brand") or ""),
        application_start=vm.get("as") or vm.get("asd") or "", application_end=vm.get("ae") or vm.get("aed") or "",
        winner_announcement_at=vm.get("wa") or vm.get("wad") or "",
        # 旧来の抽選の価格は読み取りの誤りがあるので出さない（「未取得」）
        retail_price=None, retail_price_label="未取得",
        requirements=[REQUIREMENTS_UNKNOWN],
        official_url=vm.get("apply") or "", source_url=vm.get("info") or "",
        source_type=str(it.get("data_source") or ""), confidence=vm.get("conf") or "",
        last_verified_at=str(it.get("checked_at") or ""), vm=vm)


def _from_release(vm: dict, ev: dict) -> LotteryReservationView:
    # 公式ページの価格は、商品1点の価格と明示されたもの（retail_price_basis=product_unit）だけ販売価格にする
    price = _int_price(ev.get("price")) if ev.get("retail_price_basis") == "product_unit" else None
    from src.content.ui.catalog import _store_label
    return LotteryReservationView(
        event_id=vm["id"], kind=rt.KIND_RELEASE, event_type="RELEASE_WAIT", category="tcg",
        product_name=vm.get("t") or "", product_id=str(ev.get("product_id") or ""),
        retailer=_store_label(ev.get("store")), release_at=vm.get("rd") or "",
        retail_price=price, retail_price_label="販売価格" if price else "価格未発表",
        requirements=[REQUIREMENTS_UNKNOWN], source_url=vm.get("info") or "",
        source_type=str(ev.get("source_type") or ""), confidence=vm.get("conf") or "",
        last_verified_at=str(ev.get("observed_at") or ""), vm=vm)


def build(*, vms: list[dict], tcg_report: dict | None, legacy_items: list | None, lottery_cats: dict,
          opportunity_set=None) -> list[LotteryReservationView]:
    """runtime の VM（build_vms の結果）ごとに表示モデルを作る（元データと id で突き合わせる）。"""
    report = tcg_report if isinstance(tcg_report, dict) else {}
    tcg_raw = {str(ev.get("lottery_id") or f"tcg-{i}"): ev
               for i, ev in enumerate(report.get("lotteries") or []) if isinstance(ev, dict)}
    rel_raw = {rt.release_id(ev): ev for ev in (report.get("events") or []) if isinstance(ev, dict)}
    leg_raw = {}
    for i, raw in enumerate(legacy_items or []):
        try:
            it = raw if isinstance(raw, dict) else dict(raw)
        except (TypeError, ValueError):
            continue
        leg_raw[rt.legacy_id(it, i)] = it
    by_pid: dict = {}
    if opportunity_set is not None:
        for o in list(opportunity_set.eligible):
            by_pid.setdefault(o.product_id, []).append(o)
    out = []
    for vm in vms:
        if vm.get("ann"):
            continue
        src = vm.get("src")
        if src == "tcg":
            v = _from_tcg(vm, tcg_raw.get(vm["id"], {}))
        elif src == "release":
            v = _from_release(vm, rel_raw.get(vm["id"], {}))
        else:
            v = _from_legacy(vm, leg_raw.get(vm["id"], {}), lottery_cats.get(vm["id"], "other"))
        _profit(v, by_pid, adopt_msrp=src == "legacy")
        out.append(v)
    return out
