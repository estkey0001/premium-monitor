"""HOME の「今日何をするか」横断セクション（TCG・iPhone・カメラをまたいで、今日確認する価値のあるものだけを並べる）。

並び（各セクションは 0 件なら出さない。「0 件」を見出しに出さない。架空の件数は作らない）:
  ① 今日の利益商品  ② 締切間近  ③ 現在受付中  ④ 新着抽選  ⑤ 最新発売
  ⑥ 買取価格上昇  ⑦ WAIT → BUY  ⑧ BUY → WAIT
各セクションは上位 MAX_PER_SECTION 件だけ出し、全件は既存の目的ページ（TCG は ./tcg.html・iPhone は
./iphone-buyback.html・カメラは ./camera-research.html・利益商品と抽選は新UIのページ）へのリンクで案内する。

方針（偽装しない・推測しない）:
- 新しい収集・判定は作らない。利益は opportunity.eligibility（OpportunityView）と home.py の表示ガード
  （price_ok / roi_ok）をそのまま使う。iPhone・カメラの週次の調査は、既存の comparison / market JSON を読むだけ。
- 共通なのは見せ方（FeedCard）だけ。元のスキーマは変えず、TCG・iPhone・カメラは別々のアダプターで FeedCard に写す。
- checked_at は元データの値のまま（生成時刻で置き換えない）。iPhone・カメラは調査日が 7 日を超えたら
  「調査から N 日」を併記して新しく見せない。利益の候補は 14 日を超えたら出さない（opportunity.MAX_AGE_DAYS）。
- 抽選は lottery_card.render をそのまま使う（data-nu-bucket 等を残すので、閲覧時に締切を過ぎたカードは
  runtime が属性を書き換え、CSS で消える）。
- TCG の WAIT → BUY / BUY → WAIT・TCG の買取上昇はデータが無いので出さない。新着抽選は公式の公開日
  （published_at）が直近 48 時間のものだけ（非公開の初回観測台帳は読まない）。
- どれかの JSON が壊れていても HOME 全体は落とさない（そのセクションだけ空にして続行する）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import urlencode

from src.content.ui import categories as cats
from src.content.ui import home
from src.content.ui import lottery_card
from src.content.ui import runtime as rt
from src.content.ui.components import esc, safe_href
from src.content.ui.navigation import page_href
from src.tcg.models import JST, parse_dt

MAX_PER_SECTION = 5
STALE_NOTE_DAYS = 7          # 調査日がこれを超えたら「調査から N 日」を併記する
PROFIT_MAX_AGE_DAYS = 14     # 利益の候補に使える調査・確認の古さの上限（opportunity.MAX_AGE_DAYS と同じ）
NEW_LOTTERY_HOURS = 48       # 新着抽選: 公式の公開日がこの時間以内
DASH = "—"

TCG_HUB = "./tcg.html"
IPHONE_PAGE = "./iphone-buyback.html"
CAMERA_PAGE = "./camera-research.html"
# カテゴリの表示名 → 全件を見る既存の目的ページ
CATEGORY_PAGES = {"TCG": ("TCG 抽選ハブ", TCG_HUB), "iPhone": ("iPhone 買取比較", IPHONE_PAGE),
                  "カメラ": ("カメラの調査", CAMERA_PAGE)}


@dataclass
class FeedCard:
    """横断セクションの 1 件。各項目は None 可（不明は表示で「—」）。値は元データのまま（計算し直さない）。"""
    product: str | None = None
    category: str | None = None        # TCG / iPhone / カメラ（ほかはジャンル名）
    action: str | None = None          # 買い / 様子見 / 応募する など
    buy_source: str | None = None
    sell_source: str | None = None
    profit: float | None = None
    roi: float | None = None           # 比率（0.14 = 14%）
    status: str | None = None
    deadline: str | None = None
    checked_at: str | None = None      # 元データの値のまま
    # 描画の補助（元データではない）
    href: str | None = None
    note: str | None = None            # 「調査から N 日」など
    lot: tuple | None = field(default=None, repr=False)   # (vm, state, idx): 抽選カードを lottery_card で描くとき


@dataclass
class Section:
    key: str
    title: str
    cards: list[FeedCard]
    total: int                          # 候補の総数（生成時点）
    fields: tuple = ()
    categories: tuple = ()
    base_link: tuple | None = None      # (ラベル, href)
    lottery: bool = False


# ── 日付の読み取り（読めなければ None。推測しない） ────────────────────────

_DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def _date_of(value) -> date | None:
    m = _DATE_RE.search(str(value or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def age_days(value, now: datetime) -> int | None:
    """調査日・確認日から今日までの日数（読めなければ None。未来は 0）。"""
    d = _date_of(value)
    if d is None:
        return None
    return max((now.astimezone(JST).date() - d).days, 0)


WEEKLY_NOTE = "週次の Web 調査の価格です（現在の価格とは限りません）"


def stale_note(value, now: datetime, label: str = "調査から") -> str | None:
    n = age_days(value, now)
    return f"{label}{n}日" if n is not None and n > STALE_NOTE_DAYS else None


def _yen(v) -> str:
    try:
        return f"¥{int(float(v)):,}"
    except (TypeError, ValueError):
        return DASH


def _name_key(name) -> str:
    return re.sub(r"\s+", "", str(name or "")).lower()


# ── アダプター（元スキーマ → FeedCard。判定は既存のガードだけ） ───────────────

def card_from_view(v, now: datetime) -> FeedCard:
    """利益商品（opportunity.OpportunityView。eligibility を通ったもの）。汎用・TCG はここ。"""
    label = cats.LABELS.get(v.category, v.category) if v.category else None
    label = "TCG" if v.category == "tcg" else label
    return FeedCard(
        product=v.product_name or None, category=label,
        action="購入可" if v.actionable else "要確認",
        buy_source=v.buy_source or None, sell_source=v.sell_source or None,
        profit=v.net_profit, roi=v.roi, status=v.stock_label,
        checked_at=v.last_verified_at or None,
        href="?" + urlencode({"page": "opportunities", "q": (v.product_name or "")[:40]}),
        note=stale_note(v.last_verified_at, now, "確認から"))


def card_from_lottery(vm: dict, state: dict, ev: dict | None, cat_label: str | None, idx: int) -> FeedCard:
    """TCG（と旧来の抽選）の抽選・予約・発売待ち。表示は lottery_card.render（閲覧時に状態を書き換える）。"""
    ev = ev or {}
    cta = state.get("cta") or {}
    return FeedCard(
        product=vm.get("t") or None, category=cat_label,
        action=cta.get("label") if cta.get("kind") == "apply" else None,
        buy_source=(ev.get("retailer_name") or ev.get("retailer") or vm.get("sub") or None),
        status=state.get("label"), deadline=(vm.get("ae") or vm.get("aed") or vm.get("rd") or None),
        checked_at=(ev.get("last_verified_at") or ev.get("observed_at") or None),
        href=vm.get("info") or None, lot=(vm, state, idx))


_OPP_ACTION = {"BUY": "買い", "WAIT": "様子見", "WATCH": "様子見"}
_OUTLIER_OK = (None, "NONE", "REVIEWED")


def card_from_iphone_sku(s: dict, comp: dict, now: datetime) -> FeedCard | None:
    """iPhone の週次の買取比較の 1 SKU → 利益の候補。確定の利益として出せるものだけ（出せなければ None）。

    登録済みの SKU・黒字・最高の実行可能価格がある（FRESH で外れ値でない店の価格）・Apple で購入可能と確認済み・
    費用込みの純利益と ROI が表示ガードを通る・調査日が 14 日以内、をすべて満たすとき。参考値は出さない。
    """
    if not isinstance(s, dict) or s.get("identity") != "REGISTERED" or s.get("profit_status") != "PROFITABLE":
        return None
    if s.get("outlier_status") not in _OUTLIER_OK:
        return None
    ex = s.get("highest_executable") or {}
    try:
        roi = float(s.get("roi_pct")) / 100.0
    except (TypeError, ValueError):
        return None
    if not (home.price_ok(s.get("net_profit")) and home.roi_ok(roi) and home.price_ok(ex.get("price"))
            and home.price_ok(s.get("apple_price"))):
        return None
    if (s.get("apple_availability") or {}).get("status") != "BUYABLE":
        return None
    row = next((r for r in (s.get("rows") or []) if isinstance(r, dict) and r.get("shop") == ex.get("shop")
                and r.get("executable_price") == ex.get("price") and r.get("eligible")
                and r.get("freshness") == "FRESH"), None)
    if row is None:
        return None
    rdate = comp.get("research_date")
    n = age_days(rdate, now)
    if n is None or n > PROFIT_MAX_AGE_DAYS:
        return None
    return FeedCard(
        product=s.get("sku"), category="iPhone",
        action=_OPP_ACTION.get(str(s.get("opportunity_status") or "").upper(), "様子見"),
        buy_source="Apple 公式", sell_source=ex.get("shop"),
        profit=s.get("net_profit"), roi=roi, status=s.get("opportunity_reason") or None,
        checked_at=row.get("checked_at") or rdate, href=IPHONE_PAGE, note=stale_note(rdate, now) or WEEKLY_NOTE)


def card_from_camera_route(p: dict, r: dict, doc: dict, now: datetime) -> FeedCard | None:
    """カメラの週次の調査: ルート C / D（二次流通の最安で仕入れる）で、黒字かつ確定のものだけ。

    確定 = 判定が BUY・実行可能・確かさが低くない・登録済みの商品・仕入れ側と売却側の価格が FRESH・純利益と ROI が
    表示ガードを通る。registered=False の発見・参考の推定は出さない。
    """
    if not (isinstance(p, dict) and isinstance(r, dict)) or r.get("route_type") not in ("C", "D"):
        return None
    if not p.get("registered") or r.get("profit_status") != "PROFITABLE":
        return None
    if r.get("decision") != "BUY" or r.get("executable") is not True or str(r.get("confidence") or "").lower() == "low":
        return None
    buy, sell = r.get("buy") or {}, r.get("sell") or {}
    if buy.get("freshness") != "FRESH" or sell.get("freshness") != "FRESH":
        return None
    try:
        roi = float(r.get("roi_pct")) / 100.0
    except (TypeError, ValueError):
        return None
    if not (home.price_ok(r.get("net_profit")) and home.roi_ok(roi) and home.price_ok(buy.get("price"))
            and home.price_ok(sell.get("price"))):
        return None
    rdate = doc.get("research_date")
    n = age_days(rdate, now)
    if n is None or n > PROFIT_MAX_AGE_DAYS:
        return None
    checked = min((x for x in (buy.get("checked_at"), sell.get("checked_at")) if x), default=None) or rdate
    return FeedCard(
        product=p.get("product"), category="カメラ", action="買い",
        buy_source=buy.get("source"), sell_source=sell.get("source"),
        profit=r.get("net_profit"), roi=roi, status="黒字（確定）", checked_at=checked,
        href=CAMERA_PAGE, note=stale_note(rdate, now))


def _is_decision_change(e: dict) -> bool:
    """WAIT → BUY は変化後が BUY、BUY → WAIT は変化前が BUY のときだけ（前後の判定が記録されているもの）。"""
    if e.get("type") == "WAIT_TO_BUY":
        return e.get("to") == "BUY" and bool(e.get("from")) and e.get("from") != "BUY"
    return e.get("from") == "BUY" and bool(e.get("to")) and e.get("to") != "BUY"


def _iphone_event_cards(comp: dict, now: datetime) -> dict[str, list[FeedCard]]:
    """iPhone の events（前回の週次の調査との比較）→ 買取上昇 / WAIT→BUY / BUY→WAIT。登録済みの SKU だけ。"""
    out: dict[str, list[FeedCard]] = {"BUYBACK_SURGE": [], "WAIT_TO_BUY": [], "BUY_TO_WAIT": []}
    note_text = str(comp.get("events_note") or "")
    if note_text.startswith("初回"):               # 前回が無ければ出さない
        return out
    skus = {s.get("sku"): s for s in (comp.get("skus") or []) if isinstance(s, dict)}
    rdate = comp.get("research_date")
    for e in comp.get("events") or []:
        if not isinstance(e, dict) or e.get("type") not in out:
            continue
        s = skus.get(e.get("sku"))
        if not s or s.get("identity") != "REGISTERED":
            continue
        row = next((r for r in (s.get("rows") or []) if isinstance(r, dict) and r.get("shop") == e.get("shop")), None)
        checked = (row or {}).get("checked_at") or rdate
        note = stale_note(rdate, now)
        if e["type"] == "BUYBACK_SURGE":
            if not (home.price_ok(e.get("from")) and home.price_ok(e.get("to"))) or e["to"] <= e["from"]:
                continue
            out["BUYBACK_SURGE"].append(FeedCard(
                product=e.get("sku"), category="iPhone", action="買取上昇", sell_source=e.get("shop"),
                status=f"{_yen(e['from'])} → {_yen(e['to'])}（+{_yen(e['to'] - e['from'])}）",
                checked_at=checked, href=IPHONE_PAGE, note=note))
        else:
            if not _is_decision_change(e):
                continue
            net = e.get("net")
            out[e["type"]].append(FeedCard(
                product=e.get("sku"), category="iPhone",
                action="買い" if e["type"] == "WAIT_TO_BUY" else "様子見",
                status=f"{e.get('from') or DASH} → {e.get('to') or DASH}",
                profit=net if home.price_ok(net) else None, checked_at=checked, href=IPHONE_PAGE, note=note))
    return out


def _camera_event_cards(doc: dict, now: datetime) -> dict[str, list[FeedCard]]:
    """カメラの events → 買取上昇 / WAIT→BUY / BUY→WAIT。登録済みの商品だけ（WAIT↔BUY はルート C/D だけ）。"""
    out: dict[str, list[FeedCard]] = {"BUYBACK_SURGE": [], "WAIT_TO_BUY": [], "BUY_TO_WAIT": []}
    products = {p.get("product"): p for p in (doc.get("products") or []) if isinstance(p, dict)}
    rdate = doc.get("research_date")
    note = stale_note(rdate, now)
    for e in doc.get("events") or []:
        if not isinstance(e, dict) or e.get("type") not in out:
            continue
        p = products.get(e.get("product"))
        if not p or not p.get("registered"):
            continue
        obs = next((o for o in (p.get("observations") or []) if isinstance(o, dict)
                    and o.get("shop_key") == e.get("source") and o.get("kind") == e.get("market_type")), None)
        checked = (obs or {}).get("checked_at") or rdate
        if e["type"] == "BUYBACK_SURGE":
            if e.get("market_type") != "buyback" or not (home.price_ok(e.get("from")) and home.price_ok(e.get("to"))) \
                    or e["to"] <= e["from"]:
                continue
            out["BUYBACK_SURGE"].append(FeedCard(
                product=e.get("product"), category="カメラ", action="買取上昇",
                sell_source=(obs or {}).get("source") or e.get("source") or None,
                status=f"{_yen(e['from'])} → {_yen(e['to'])}（+{_yen(e['to'] - e['from'])}）",
                checked_at=checked, href=CAMERA_PAGE, note=note))
        elif e.get("route") in ("C", "D") and _is_decision_change(e):
            out[e["type"]].append(FeedCard(
                product=e.get("product"), category="カメラ",
                action="買い" if e["type"] == "WAIT_TO_BUY" else "様子見",
                status=f"{e.get('from') or DASH} → {e.get('to') or DASH}（ルート {e['route']}）",
                checked_at=checked, href=CAMERA_PAGE, note=note))
    return out


# ── セクションの組み立て（1 セクションずつ try/except。失敗したら空） ─────────────

_PROFIT_FIELDS = (("buy_source", "仕入れ"), ("sell_source", "売却"), ("profit", "純利益"), ("status", "状態"),
                  ("checked_at", "確認"))
_EVENT_FIELDS = (("sell_source", "買取店"), ("status", "変化"), ("profit", "利益の見込み"), ("checked_at", "確認"))


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:                       # noqa: BLE001  壊れた JSON・想定外の形で HOME を落とさない
        return []


def _profit_cards(catalog, data: dict, now: datetime) -> list[FeedCard]:
    """利益の候補（利益商品・iPhone・カメラ）。1 件ごとに try/except（壊れた 1 件で全体を落とさない）。"""
    cards: list[FeedCard] = []
    views = list(getattr(getattr(catalog, "opportunity_set", None), "eligible", None) or [])
    for v in views:
        cards += _safe(lambda v=v: [card_from_view(v, now)])
    comp = data.get("iphone") if isinstance(data.get("iphone"), dict) else {}
    for s in comp.get("skus") or []:
        cards += [c for c in _safe(lambda s=s: [card_from_iphone_sku(s, comp, now)]) if c]
    cam = data.get("camera") if isinstance(data.get("camera"), dict) else {}
    for p in cam.get("products") or []:
        for r in (p.get("routes") or []) if isinstance(p, dict) else []:
            cards += [c for c in _safe(lambda p=p, r=r: [card_from_camera_route(p, r, cam, now)]) if c]
    seen: set[str] = set()
    uniq: list[FeedCard] = []
    for c in sorted((c for c in cards if home.price_ok(c.profit)), key=lambda c: -float(c.profit)):
        k = _name_key(c.product)
        if k and k in seen:
            continue
        seen.add(k)
        uniq.append(c)
    return uniq


def _lottery_cards(catalog, model, tcg_report: dict, now: datetime) -> dict[str, list[FeedCard]]:
    """抽選系 4 セクションの候補（生成時点の runtime 状態で選ぶ。閲覧時の失効は属性と CSS で消す）。"""
    raw = {str(e.get("lottery_id")): e for e in ((tcg_report or {}).get("lotteries") or [])
           if isinstance(e, dict) and e.get("lottery_id")}
    ending: list = []
    opened: list = []
    fresh: list = []
    release: list = []
    for idx, vm in enumerate(model.vms):
        st = model.states.get(vm["id"])
        if not st or st["bucket"] >= rt.BUCKET_HIDDEN or vm.get("ann"):
            continue
        cat = catalog.lottery_cats.get(vm["id"])
        label = "TCG" if cat == "tcg" else cats.LABELS.get(cat or "", None)
        ev = raw.get(vm["id"])
        card = card_from_lottery(vm, st, ev, label, idx)
        if vm.get("k") == rt.KIND_RELEASE:
            if st["status"] == "RELEASE_WAIT":
                release.append((vm.get("rd") or "", idx, card))
            continue
        if vm.get("unv") or vm.get("conflict"):          # 確認待ち・参考情報・日程の食い違いは HOME に出さない
            continue
        if st["status"] == "ENDING_SOON":
            ending.append((st["sort"], idx, card))
        elif st["status"] == "OPEN":
            opened.append((st["sort"], idx, card))
        pub = parse_dt(str((ev or {}).get("published_at") or "").replace(" ", "T", 1)) if ev else None
        if pub is not None and st["status"] in ("ENDING_SOON", "OPEN", "UPCOMING"):
            hours = (now - pub.astimezone(JST)).total_seconds() / 3600
            if 0 <= hours <= NEW_LOTTERY_HOURS:
                fresh.append((-pub.timestamp(), idx, card))
    key = lambda t: (t[0], t[1])                          # noqa: E731
    return {"ending": [c for *_k, c in sorted(ending, key=key)],
            "open": [c for *_k, c in sorted(opened, key=key)],
            "new": [c for *_k, c in sorted(fresh, key=key)],
            "release": [c for *_k, c in sorted(release, key=key)]}


def build(catalog, model, tcg_report: dict | None, data: dict | None, now: datetime) -> list[Section]:
    """表示するセクション（0 件のものは含めない）。"""
    data = data if isinstance(data, dict) else {}
    now = now.astimezone(JST)
    sections: list[Section] = []

    def add(key, title, cards, *, fields=(), base_link=None, lottery=False):
        if not cards:
            return
        sections.append(Section(
            key=key, title=title, cards=cards[:MAX_PER_SECTION], total=len(cards), fields=fields,
            categories=tuple(dict.fromkeys(c.category for c in cards if c.category in CATEGORY_PAGES)),
            base_link=base_link, lottery=lottery))

    pcards = _safe(_profit_cards, catalog, data, now)
    # 判定が BUY の商品だけを「今日の利益商品」に出す。黒字でも週次の判定が様子見（ROI が買い条件未満など）の iPhone は別枠（買い推奨に見せない）
    watch = [c for c in pcards if c.category == "iPhone" and c.action != _OPP_ACTION["BUY"]]
    add("profit", "今日の利益商品", [c for c in pcards if c not in watch], fields=_PROFIT_FIELDS,
        base_link=("利益商品をすべて見る", page_href("opportunities")))
    add("profit_watch", "黒字だが様子見（買いの条件に届いていない）", watch, fields=_PROFIT_FIELDS,
        base_link=("iPhone の買取比較を見る", IPHONE_PAGE))
    lot = _safe(_lottery_cards, catalog, model, tcg_report or {}, now) or {}
    lot_link = ("抽選・予約をすべて見る", page_href("lottery"))
    ending_ids = {c.lot[0]["id"] for c in lot.get("ending", []) if c.lot}
    add("ending", "締切間近", lot.get("ending", []), base_link=lot_link, lottery=True)
    add("open", "現在受付中", [c for c in lot.get("open", []) if c.lot[0]["id"] not in ending_ids],
        base_link=lot_link, lottery=True)
    open_ids = {c.lot[0]["id"] for c in lot.get("open", []) if c.lot}
    add("new", "新着抽選", [c for c in lot.get("new", []) if c.lot[0]["id"] not in (ending_ids | open_ids)], base_link=lot_link, lottery=True)
    add("release", "最新発売", lot.get("release", []), base_link=lot_link, lottery=True)

    iph = _safe(_iphone_event_cards, data.get("iphone") if isinstance(data.get("iphone"), dict) else {}, now) or {}
    cam = _safe(_camera_event_cards, data.get("camera") if isinstance(data.get("camera"), dict) else {}, now) or {}
    for key, title, typ in (("surge", "買取価格上昇", "BUYBACK_SURGE"), ("w2b", "WAIT → BUY", "WAIT_TO_BUY"),
                            ("b2w", "BUY → WAIT", "BUY_TO_WAIT")):
        add(key, title, list(iph.get(typ, [])) + list(cam.get(typ, [])), fields=_EVENT_FIELDS)
    return sections


# ── 描画 ──────────────────────────────────────────────────────────

def _val(card: FeedCard, name: str) -> str:
    v = getattr(card, name, None)
    if name == "profit":
        if not home.price_ok(v):
            return DASH
        roi = f"（{card.roi * 100:.1f}%）" if card.roi is not None and home.roi_ok(card.roi) else ""
        return f"+{_yen(v)}{roi}"
    if name == "checked_at":
        d = _date_of(v)
        return d.isoformat() if d else (str(v).strip() if v else DASH)
    return str(v).strip() if v not in (None, "") else DASH


def _card_html(card: FeedCard, fields: tuple) -> str:
    rows = "".join(f"<dt>{esc(label)}</dt><dd>{esc(_val(card, name))}</dd>" for name, label in fields)
    stale = f'<p class="nu-feed__stale" role="note">{esc(card.note)}</p>' if card.note else ""
    link = safe_href(card.href or "")
    btn = f'<a class="nu-btn nu-btn--secondary" href="{esc(link)}">詳しく見る</a>' if link else ""
    head_badge = f'<span class="nu-badge nu-tone-info">{esc(card.action)}</span>' if card.action else ""
    return (f'<article class="nu-card nu-feedcard" data-nu-feedcard>'
            f'<div class="nu-card__head"><h3 class="nu-card__title">{esc(card.product or DASH)}</h3>{head_badge}</div>'
            f'<p class="nu-card__sub">{esc(card.category or DASH)}</p>'
            f'<dl class="nu-feed__dl">{rows}</dl>{stale}{btn}</article>')


def _section_html(sec: Section) -> str:
    if sec.lottery:
        items = "".join(f'<li class="nu-feed__item">{lottery_card.render(*c.lot)}</li>' for c in sec.cards)
    else:
        items = "".join(f'<li class="nu-feed__item">{_card_html(c, sec.fields)}</li>' for c in sec.cards)
    links = []
    if sec.base_link:
        links.append(sec.base_link)
    links += [CATEGORY_PAGES[c] for c in sec.categories]
    if sec.lottery:                                   # 受付の状態は閲覧時に変わるので、残りの件数は書かない
        more = ""
    else:
        rest = sec.total - len(sec.cards)
        more = f'<span class="nu-feed__rest">ほか{rest}件</span>' if rest > 0 else ""
    foot = "".join(f'<a href="{esc(h)}">{esc(lbl)}</a>' for lbl, h in links if safe_href(h))
    foot_html = f'<p class="nu-feed__more">{more}{foot}</p>' if (more or foot) else ""
    attr = " data-nu-lotsec" if sec.lottery else ""
    return (f'<div class="nu-feed__sec" data-nu-feed-sec="{esc(sec.key)}"{attr}>'
            f'<h2 class="nu-h2">{esc(sec.title)}</h2>'
            f'<ul class="nu-feed__list" role="list">{items}</ul>{foot_html}</div>')


def render_sections(sections: list[Section]) -> str:
    if not sections:
        return ""
    return ('<div class="nu-feed" data-nu-feed aria-label="今日の注目">'
            + "".join(_section_html(s) for s in sections) + "</div>")


def render(catalog, model, ctx) -> str:
    """HOME に差し込む HTML（空なら空文字）。どんな失敗でも HOME は出す。"""
    try:
        sections = build(catalog, model, getattr(ctx, "tcg_report", None),
                         getattr(ctx, "home_feed_data", None), model.now or datetime.now(tz=JST))
        return render_sections(sections)
    except Exception:                                  # noqa: BLE001
        return ""


def load_sources(load_json) -> dict:
    """生成側が渡す元データ（exports の既存 JSON。読むだけ）。load_json は壊れ・欠損を {} にして返す関数。"""
    return {"iphone": load_json("iphone_buyback", "iphone_buyback_comparison.json"),
            "camera": load_json("camera_research", "camera_market.json")}
