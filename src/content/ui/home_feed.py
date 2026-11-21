"""HOME の「今日何をするか」横断セクション（TCG・iPhone・カメラをまたいで、今日確認する価値のあるものだけを並べる）。

最上部に「今日のアクション」サマリー（購入候補・締切間近・受付中・様子見の件数。data-nu-today。feed の外）を常に出す。
並び（各セクションは 0 件なら出さない。「0 件」を見出しに出さない。架空の件数は作らない）:
  ⓪ 今日やるべきこと（ヒーロー。購入候補と締切間近の抽選だけ。最大 HERO_MAX 件。ここへ出した分は下のセクションから外す）
  ① 利益商品  ② 締切間近  ③ 新着抽選  ④ 現在受付中  ⑤ 様子見（黒字だが買いの条件に届いていない）
  ⑥ 最新発売  ⑦ 買取価格上昇  ⑧ WAIT → BUY  ⑨ BUY → WAIT
カードは重要度で 3 種（ヒーロー / 標準 / コンパクト）。表示語はこのファイルの辞書だけで統一する（status.py は変えない）。
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
HERO_MAX = 2                 # 「今日やるべきこと」の最大件数
TODAY_END = "<!--nu-today-end-->"   # pages.render_home が、注意バナーをサマリーの下へ差し込む位置
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
    unverified: bool = False           # 判定の変化イベント（WAIT→BUY）で、実行可能・FRESH を確認できていないもの（緑にしない）
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
    kind: str = "std"                   # hero / std / compact（カードの大きさ。重要度の強弱）


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


_JUDGE_WORD = {"BUY": "購入候補", "WAIT": "様子見", "WATCH": "様子見"}


def judge_word(v) -> str:
    """判定の内部値（BUY / WAIT）を HOME の表示語にする（知らない値はそのまま。内部値・判定は変えない）。"""
    return _JUDGE_WORD.get(str(v or "").upper(), str(v)) if v else DASH


def plain_reason(text) -> str | None:
    """判定の理由に含まれる内部語（BUY・WAIT）を HOME の表示語にする。詳細ページ側の文言は変えない。"""
    if not text:
        return None
    return re.sub(r"\s*\bBUY\b\s*", "購入候補", re.sub(r"\s*\bWAIT\b\s*", "様子見", str(text)))


def _yen(v) -> str:
    try:
        return f"¥{int(float(v)):,}"
    except (TypeError, ValueError):
        return DASH


def _name_key(name) -> str:
    return re.sub(r"\s+", "", str(name or "")).lower()


# ── 表示語と色（HOME だけのローカルな辞書。内部値・判定は変えない） ──────────────

BUY_ACTIONS = ("買い", "購入可")
ACTION_LABEL = {"買い": "購入候補", "購入可": "購入候補", "様子見": "様子見", "要確認": "要確認"}
_STALE_RE = re.compile(r"^(調査|確認)から\d+日")


def is_buy(card: FeedCard) -> bool:
    return card.action in BUY_ACTIONS


def is_stale(card: FeedCard) -> bool:
    return bool(card.note and _STALE_RE.match(card.note))


def is_actionable_buy(card: FeedCard) -> bool:
    """購入候補で、かつ調査が古くない（古い調査は件数・ヒーローに数えない）。"""
    return is_buy(card) and not is_stale(card)


def card_tone(card: FeedCard) -> str:
    """カードの色（design_tokens.TONES のキー）。緑は購入候補だけ・様子見は warning・古い調査と要確認は neutral。"""
    if is_stale(card):
        return "neutral"
    if is_buy(card):
        return "info" if card.unverified else "success"
    if card.action == "様子見":
        return "warning"
    if card.action == "要確認":
        return "neutral"
    return "info"


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
        profit=s.get("net_profit"), roi=roi, status=plain_reason(s.get("opportunity_reason")),
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
                status=f"{judge_word(e.get('from'))} → {judge_word(e.get('to'))}",
                profit=net if home.price_ok(net) else None, checked_at=checked, href=IPHONE_PAGE, note=note,
                unverified=e["type"] == "WAIT_TO_BUY"))
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
                status=f"{judge_word(e.get('from'))} → {judge_word(e.get('to'))}（ルート {e['route']}）",
                checked_at=checked, href=CAMERA_PAGE, note=note, unverified=e["type"] == "WAIT_TO_BUY"))
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


def _lottery_priority(ev, now: datetime) -> str | None:
    """TCG ハブの応募優先度（S / A / B / WATCH）。新しい基準は作らず、ハブの関数をそのまま使う。読めなければ None。"""
    if not isinstance(ev, dict):
        return None
    try:
        from src.tcg.hub import product_view as pv
        from src.tcg.hub import status as hub_st
        return hub_st.priority_of_event(ev, now, bound_exact=(pv._bind_state(ev)[0] == "exact"))
    except Exception:  # noqa: BLE001 — 優先度が出せなくても HOME の抽選カードは出す
        return None


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
        prio = _lottery_priority(ev, now)                 # 応募優先度（TCG ハブと同じ判定。未確認・未紐付けは WATCH で強く勧めない）
        if prio in ("S", "A"):
            vm = {**vm, "prio": prio}
        card = card_from_lottery(vm, st, ev, label, idx)
        if vm.get("k") == rt.KIND_RELEASE:
            if st["status"] == "RELEASE_WAIT":
                release.append((vm.get("rd") or "", idx, card))
            continue
        if vm.get("unv") or vm.get("conflict"):          # 確認待ち・参考情報・日程の食い違いは HOME に出さない
            continue
        rank = 0 if prio == "S" else 1                    # 優先度 S を同じ節の先頭へ（それ以外の並びは変えない）
        if st["status"] == "ENDING_SOON":
            ending.append(((rank, st["sort"]), idx, card))
        elif st["status"] == "OPEN":
            opened.append(((rank, st["sort"]), idx, card))
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


def build_with_counts(catalog, model, tcg_report: dict | None, data: dict | None,
                      now: datetime) -> tuple[list[Section], dict[str, int]]:
    """表示するセクション（0 件のものは含めない）と、サマリー用の件数（ヒーローへ移す前の総数）。"""
    data = data if isinstance(data, dict) else {}
    now = now.astimezone(JST)
    sections: list[Section] = []

    def add(key, title, cards, *, fields=(), base_link=None, lottery=False, kind="std"):
        if not cards:
            return
        sections.append(Section(
            key=key, title=title, cards=cards[:MAX_PER_SECTION], total=len(cards), fields=fields,
            categories=tuple(dict.fromkeys(c.category for c in cards if c.category in CATEGORY_PAGES)),
            base_link=base_link, lottery=lottery, kind=kind))

    pcards = _safe(_profit_cards, catalog, data, now)
    # 判定が BUY の商品だけを「利益商品」に出す。黒字でも週次の判定が様子見（ROI が買い条件未満など）の iPhone は別枠（買い推奨に見せない）
    watch = [c for c in pcards if c.category == "iPhone" and c.action != _OPP_ACTION["BUY"]]
    profit = [c for c in pcards if c not in watch]
    lot = _safe(_lottery_cards, catalog, model, tcg_report or {}, now) or {}
    ending_all = list(lot.get("ending", []))
    ending_ids = {c.lot[0]["id"] for c in ending_all if c.lot}
    open_all = [c for c in lot.get("open", []) if c.lot[0]["id"] not in ending_ids]
    open_ids = {c.lot[0]["id"] for c in lot.get("open", []) if c.lot}
    new_all = [c for c in lot.get("new", []) if c.lot[0]["id"] not in (ending_ids | open_ids)]

    counts = {"buy": sum(1 for c in profit if is_actionable_buy(c)), "ending": len(ending_all), "open": len(open_all),
              "wait": len(watch)}

    # ⓪ 今日やるべきこと: 購入候補（利益の大きい順）と締切間近の抽選だけ。「要確認」は上げない。ここへ出した分は下から外す
    buys = [c for c in profit if is_actionable_buy(c)]
    hero = buys[:1] + ending_all[:1]
    for extra in buys[1:2] + ending_all[1:2]:
        if len(hero) < HERO_MAX:
            hero.append(extra)
    hero = hero[:HERO_MAX]
    moved = {id(c) for c in hero}
    profit = [c for c in profit if id(c) not in moved]
    ending = [c for c in ending_all if id(c) not in moved]
    add("hero", "今日やるべきこと", hero, fields=_PROFIT_FIELDS, kind="hero",
        lottery=bool(hero) and all(c.lot for c in hero))

    add("profit", "利益商品", profit, fields=_PROFIT_FIELDS,
        base_link=("利益商品をすべて見る", page_href("opportunities")))
    add("ending", "締切間近", ending, lottery=True, kind="compact")
    add("new", "新着抽選", new_all, lottery=True, kind="compact")
    add("open", "現在受付中", open_all, lottery=True, kind="compact")
    add("profit_watch", "様子見（黒字だが買いの条件に届いていない）", watch, fields=_PROFIT_FIELDS,
        base_link=("iPhone の買取比較を見る", IPHONE_PAGE))
    add("release", "最新発売", lot.get("release", []), lottery=True, kind="compact")

    iph = _safe(_iphone_event_cards, data.get("iphone") if isinstance(data.get("iphone"), dict) else {}, now) or {}
    cam = _safe(_camera_event_cards, data.get("camera") if isinstance(data.get("camera"), dict) else {}, now) or {}
    # 様子見 → 購入候補の変化は、同じ商品が「実行可能・FRESH を確認済みの購入候補」（上の利益商品）にもいるときだけ緑にする。
    # それ以外は変化の記録にすぎない（購入できるかは未確認）ので緑にせず、サマリーの「購入候補」件数とも矛盾させない
    verified = {_name_key(c.product) for c in buys}
    for c in list(iph.get("WAIT_TO_BUY", [])) + list(cam.get("WAIT_TO_BUY", [])):
        if _name_key(c.product) in verified:
            c.unverified = False
    for key, title, typ in (("surge", "買取価格上昇", "BUYBACK_SURGE"), ("w2b", "様子見 → 購入候補", "WAIT_TO_BUY"),
                            ("b2w", "購入候補 → 様子見", "BUY_TO_WAIT")):
        add(key, title, list(iph.get(typ, [])) + list(cam.get(typ, [])), fields=_EVENT_FIELDS, kind="compact")
    # 「抽選・予約をすべて見る」は HOME 全体で 1 つだけ（最後の抽選の節の下。行き先が同じリンクを節ごとに並べない）。
    # ヒーローは抽選カードを含みうるが、リンクは付けない
    lot_secs = [sec for sec in sections if sec.lottery and sec.key != "hero"]
    if lot_secs:
        lot_secs[-1].base_link = ("抽選・予約をすべて見る", page_href("lottery"))
    return sections, counts


def build(catalog, model, tcg_report: dict | None, data: dict | None, now: datetime) -> list[Section]:
    """表示するセクション（0 件のものは含めない）。"""
    return build_with_counts(catalog, model, tcg_report, data, now)[0]


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


def _rows(card: FeedCard, fields: tuple, kind: str) -> str:
    """項目の行。ヒーロー・標準は利益を大きな 1 行にして <dl> から外し、仕入れ・売却は 最適ルート の 1 行にまとめる。"""
    big = kind in ("hero", "std") and home.price_ok(card.profit)
    out = []
    names = [n for n, _l in fields]
    route_done = False
    for name, label in fields:
        if name == "profit" and big:
            continue
        if kind in ("hero", "std") and name in ("buy_source", "sell_source") and "buy_source" in names \
                and "sell_source" in names and (card.buy_source or card.sell_source):
            if not route_done:
                route = f"{_val(card, 'buy_source')} → {_val(card, 'sell_source')}"
                out.append(f"<dt>最適ルート</dt><dd>{esc(route)}</dd>")
                route_done = True
            continue
        out.append(f"<dt>{esc('確認日' if name == 'checked_at' else label)}</dt><dd>{esc(_val(card, name))}</dd>")
    return "".join(out)


def _card_html(card: FeedCard, fields: tuple, kind: str = "std", *, button: bool = True) -> str:
    tone = card_tone(card)
    stale = is_stale(card)
    big = kind in ("hero", "std") and home.price_ok(card.profit)
    # 金額と「黒字」の緑は購入候補だけ（様子見・要確認・古い調査は CSS が tone ごとに中立・橙へ）
    profit_html = (f'<p class="nu-fc__profit"><span class="nu-fc__tag">黒字</span>{esc(_val(card, "profit"))}</p>'
                   if big else "")
    note_text = card.note or ("購入できるかは未確認です（詳細で確認してください）" if card.unverified and is_buy(card) else None)
    note = f'<p class="nu-feed__stale" role="note">{esc(note_text)}</p>' if note_text else ""
    link = safe_href(card.href or "") if button else ""
    # ボタンは主 1 つ（ヒーローの購入候補は primary・標準は secondary）。コンパクトは文字のリンクにして重複を減らす
    btn_kind = "primary" if kind == "hero" and tone == "success" else ("link" if kind == "compact" else "secondary")
    btn = f'<a class="nu-btn nu-btn--{btn_kind}" href="{esc(link)}">詳細と情報元を見る</a>' if link else ""
    label = ACTION_LABEL.get(card.action, card.action) if card.action else None
    if card.unverified and is_buy(card):                  # 変化の記録だけ。「購入候補」と断定しない
        label = "購入候補に変化"
    head_badge = f'<span class="nu-badge nu-tone-{tone}">{esc(label)}</span>' if label else ""
    cls = f"nu-card nu-feedcard nu-fc nu-fc--{kind} nu-fc--{tone}" + (" nu-fc--stale" if stale else "")
    return (f'<article class="{cls}" data-nu-feedcard>'
            f'<div class="nu-card__head"><h3 class="nu-card__title">{esc(card.product or DASH)}</h3>{head_badge}</div>'
            f'<p class="nu-card__sub">{esc(card.category or DASH)}</p>{profit_html}'
            f'<dl class="nu-feed__dl">{_rows(card, fields, kind)}</dl>{note}{btn}</article>')


def _item_html(card: FeedCard, sec: Section, button: bool = True) -> str:
    if card.lot:                                     # 抽選は lottery_card をそのまま（runtime の data-nu-* 契約を変えない）
        return f'<li class="nu-feed__item nu-feed__item--lot">{lottery_card.render(*card.lot)}</li>'
    return f'<li class="nu-feed__item">{_card_html(card, sec.fields, sec.kind, button=button)}</li>'


def _section_html(sec: Section) -> str:
    links = []
    if sec.base_link:
        links.append(sec.base_link)
    if not sec.lottery:                               # 抽選の節は「抽選・予約をすべて見る」の 1 つだけ（TCG ハブと二重に出さない）
        links += [CATEGORY_PAGES[c] for c in sec.categories]
    seen_h: set[str] = set()                          # 同じ行き先のリンクは 1 つ
    links = [(lbl, h) for lbl, h in links if not (h in seen_h or seen_h.add(h))]
    if sec.lottery:                                   # 受付の状態は閲覧時に変わるので、残りの件数は書かない
        rest = 0
        more = ""
    else:
        rest = sec.total - len(sec.cards)
        more = f'<span class="nu-feed__rest">ほか{rest}件</span>' if rest > 0 else ""
    # 同じ行き先は 1 節に 1 つ: 節の下のリンクと同じ行き先をカードのボタンが持つなら、どちらか一方だけにする
    #   - 同じ行き先のカードが 2 件以上 → カードのボタンを外し、節の下のリンクに任せる
    #   - 1 件だけで「ほか」も無い → 節の下のリンクを外し、カードのボタンに任せる
    # （ヒーローは節の下のリンクが無いので、カードのボタンを残す）
    foot_hrefs = {h for _l, h in links} if sec.key != "hero" else set()
    counts: dict[str, int] = {}
    for c in sec.cards:
        if c.href and not c.lot:
            counts[c.href] = counts.get(c.href, 0) + 1
    no_button = {h for h, n in counts.items() if n >= 2 and h in foot_hrefs}
    if rest == 0:
        links = [(lbl, h) for lbl, h in links if not (h in counts and h not in no_button and counts[h] == 1)]
    items = "".join(_item_html(c, sec, button=not (c.href in no_button)) for c in sec.cards)
    foot = "".join(f'<a href="{esc(h)}">{esc(lbl)}</a>' for lbl, h in links if safe_href(h)) if sec.key != "hero" else ""
    foot_html = f'<p class="nu-feed__more">{more}{foot}</p>' if (more or foot) else ""
    attr = " data-nu-lotsec" if sec.lottery else ""
    return (f'<div class="nu-feed__sec nu-feed__sec--{esc(sec.key)}" id="nu-sec-{esc(sec.key)}"'
            f' data-nu-feed-sec="{esc(sec.key)}"{attr}>'
            f'<h2 class="nu-h2">{esc(sec.title)}</h2>'
            f'<ul class="nu-feed__list nu-feed__list--{esc(sec.kind)}" role="list">{items}</ul>{foot_html}</div>')


def render_sections(sections: list[Section]) -> str:
    if not sections:
        return ""
    return ('<div class="nu-feed" data-nu-feed aria-label="今日の注目">'
            + "".join(_section_html(s) for s in sections) + "</div>")


# ── 今日の状況（サマリー。feed の外。nu-card は使わない） ──────────────────────

_TILES = (("buy", "購入候補", "buy"), ("ending", "締切間近", "end"), ("open", "受付中", "open"),
          ("wait", "様子見", "wait"))
TILE_SUB = {"open": "締切間近を除く"}     # 件数の定義（TCG ハブの「受付中」は締切間近を含む）


def _tile_target(key: str, sections: list[Section]) -> str | None:
    """タイルのジャンプ先。ヒーローへ移した分も数えているので、ヒーローに該当のカードがあればヒーローへ、無ければ各節へ。"""
    keys = {sec.key for sec in sections}
    hero = next((sec for sec in sections if sec.key == "hero"), None)
    if key == "buy":
        if hero and any(not c.lot for c in hero.cards):
            return "hero"
        return "profit" if "profit" in keys else None
    if key == "ending":
        if hero and any(c.lot for c in hero.cards):
            return "hero"
        return "ending" if "ending" in keys else None
    want = {"open": "open", "wait": "profit_watch"}[key]
    return want if want in keys else None


def render_today(sections: list[Section], counts: dict[str, int], *, source_issue: bool = False,
                 actionable: str = "") -> str:
    """最上部の 4 タイル + 注意・件数の 1 ブロック + 近道。0 のタイルは小さく淡く「該当なし」の 1 語だけ（「0件」「—」とは書かない）。件数はページ生成時点。"""
    tiles = []
    for key, label, cls in _TILES:
        n = int(counts.get(key, 0) or 0)
        target = _tile_target(key, sections) if n > 0 else None
        if n > 0:
            sub = f'<span class="nu-today__sub">{esc(TILE_SUB[key])}</span>' if key in TILE_SUB else ""
            body = (f'<span class="nu-today__label">{esc(label)}</span>'
                    f'<span class="nu-today__n">{n}<span class="nu-today__u">件</span></span>{sub}')
        else:
            body = (f'<span class="nu-today__label">{esc(label)}</span>'
                    f'<span class="nu-today__n">該当なし</span>')
        zero = "" if n > 0 else " nu-today__tile--zero"
        klass = f"nu-today__tile nu-today__tile--{cls}{zero}"
        if target:
            tiles.append(f'<li><a class="{klass}" href="./#nu-sec-{esc(target)}">{body}</a></li>')
        else:
            tiles.append(f'<li><div class="{klass}">{body}</div></li>')
    # 注意・件数の行を、サマリー直下の 1 ブロックに（重要度の高い順: 情報源の取得失敗 → 購入候補なし → 行動できる件数 → 件数の定義）
    notes = []
    if source_issue:
        notes.append('<p class="nu-today__warn" role="note">ⓘ 一部の情報源を取得できていません。公式サイトでもご確認ください。</p>')
    if actionable:
        notes.append(actionable)
    # 購入候補なしはタイルの「該当なし」で足りるので文にしない。件数の注記と案内は 1 文に統合する
    note = "件数はページ生成時点のものです（抽選の受付状況は閲覧時に変わります）。"
    if not any(counts.get(k) for k in ("buy", "ending", "open", "wait")):
        note = "抽選・予約の受付状況は下のジャンルから確認できます。" + note
    notes.append(f'<p class="nu-today__note">{esc(note)}</p>')
    jump = ('<nav class="nu-hjump" aria-label="ジャンル・目的への近道">'
            '<a class="nu-hjump__a" href="./#nu-genres">ジャンルから探す</a>'
            '<a class="nu-hjump__a" href="./#nu-purposes-h">目的から探す</a></nav>')
    return ('<div class="nu-today" data-nu-today aria-label="今日の状況">'
            '<h2 class="nu-h2">今日の状況</h2>'
            f'<ul class="nu-today__tiles" role="list">{"".join(tiles)}</ul>'
            f'<div class="nu-today__notes">{"".join(notes)}</div>{jump}'
            f'</div>{TODAY_END}')


def render(catalog, model, ctx) -> str:
    """HOME に差し込む HTML（サマリー + フィード）。サマリーは常に出す。どんな失敗でも HOME は出す。"""
    try:
        sections, counts = build_with_counts(catalog, model, getattr(ctx, "tcg_report", None),
                                             getattr(ctx, "home_feed_data", None), model.now or datetime.now(tz=JST))
        from src.content.ui.pages import _actionable_line     # 循環 import を避けて関数内で読む
        today = render_today(sections, counts, source_issue=bool(getattr(ctx, "source_issue", False)),
                             actionable=_actionable_line(catalog, hide_zero=True))
        return today + render_sections(sections)
    except Exception:                                  # noqa: BLE001
        return ""


def load_sources(load_json) -> dict:
    """生成側が渡す元データ（exports の既存 JSON。読むだけ）。load_json は壊れ・欠損を {} にして返す関数。"""
    return {"iphone": load_json("iphone_buyback", "iphone_buyback_comparison.json"),
            "camera": load_json("camera_research", "camera_market.json")}
