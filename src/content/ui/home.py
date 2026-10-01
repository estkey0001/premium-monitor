"""新UIの HOME（今日のチャンス・おすすめアクション TOP5）。

新しい判定は作らない。抽選の状態は runtime.derive_runtime_state（既存の
compute_lottery_status）だけで決め、AI Opportunities・利益ルートは既存の出力をそのまま数える。

表示段階のガード: 0円・非有限・極端な利益率・参考扱い・低い確かさの値は
「おすすめ」「高利益」「高プレミア」として出さない。値の補正はしない（出さないだけ）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from src.content.ui import components as c
from src.content.ui import lottery_card
from src.content.ui import runtime as rt
from src.content.ui.navigation import page_href
from src.tcg.models import JST

# 利益率がこれを超える値は異常値の可能性が高いので「おすすめ」に出さない（表示だけのガード）
MAX_PLAUSIBLE_ROI = 2.0
TOP_ACTIONS_LIMIT = 5


# ── 価格のガード（表示だけ） ──────────────────────────────────────────

def _num(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v


def price_ok(value) -> bool:
    """0円・負・数値でない・有限でない価格は表示しない。"""
    v = _num(value)
    return v is not None and math.isfinite(v) and v > 0


def opportunity_reject_reason(o: dict) -> str:
    """AI Opportunity を「買う」として出せない理由。出せるなら空文字。"""
    if str(o.get("action") or "") != "BUY":
        return "not_buy"
    if str(o.get("kind") or "") != "main":
        return "reference"
    if o.get("rejection_reason") or o.get("suspicious") or o.get("invalid"):
        return "flagged"
    if str(o.get("confidence") or "").lower() == "low":
        return "low_confidence"
    if not (price_ok(o.get("buy_price")) and price_ok(o.get("sell_price"))
            and price_ok(o.get("net_profit"))):
        return "invalid_price"
    if not roi_ok(o.get("roi")):
        return "extreme_roi"
    return ""


def roi_ok(value) -> bool:
    """利益率が有限で 0 より大きく、上限以下のときだけ表示する。"""
    roi = _num(value)
    return roi is not None and math.isfinite(roi) and 0 < roi <= MAX_PLAUSIBLE_ROI


# プレミア率の表示上限（%）。これを超える値はサンプル異常の可能性があるので数えない
MAX_PLAUSIBLE_PREMIUM_PERCENT = 500.0


def premium_ok(premium: dict | None) -> bool:
    """「高プレミア」として数えてよいか（表示だけのガード。値は変えない）。"""
    p = premium or {}
    if p.get("insufficient_samples"):
        return False
    v = _num(p.get("premium_percent"))
    return v is not None and math.isfinite(v) and 0 < v <= MAX_PLAUSIBLE_PREMIUM_PERCENT


def route_reject_reason(r: dict) -> str:
    """検証済み利益ルートを「高利益」として数えられない理由。数えられるなら空文字。"""
    if r.get("reference_route") or r.get("rejection_reason"):
        return "flagged"
    if str(r.get("route_confidence") or "").lower() == "low":
        return "low_confidence"
    if not (price_ok(r.get("buy_price")) and price_ok(r.get("sell_price"))
            and price_ok(r.get("net_profit"))):
        return "invalid_price"
    if not roi_ok(r.get("roi")):
        return "extreme_roi"
    return ""


# ── 集計 ──────────────────────────────────────────────────────────

@dataclass
class Action:
    """AI Opportunities のカード（抽選カードは lottery_card が作る）。"""
    action: str                 # BUY / WAIT / SKIP（内部値）
    title: str
    subtitle: str = ""
    primary: str = ""
    secondary: str = ""
    cta_label: str = ""
    cta_href: str = ""
    bucket: int = rt.BUCKET_HIDDEN
    idx: int = 0

    def render(self, *, hidden: bool = False) -> str:
        card = c.Card(title=self.title, subtitle=self.subtitle, status=self.action,
                      primary_metric=self.primary, secondary_metric=self.secondary,
                      cta_label=self.cta_label, cta_href=self.cta_href, cta_external=False,
                      cta_track="product_click",
                      attrs={"nu-action": self.action, "nu-source": "ai_opportunity",
                             "nu-bucket": str(self.bucket), "nu-sort": "0", "nu-idx": str(self.idx)})
        html = card.render()
        return html.replace("<article ", "<article hidden ", 1) if hidden else html


@dataclass
class HomeModel:
    now: datetime | None = None
    counts: dict[str, int] = field(default_factory=dict)
    vms: list[dict] = field(default_factory=list)          # 抽選の VM（runtime.build_vms）
    states: dict[str, dict] = field(default_factory=dict)  # 生成時点の runtime state
    opp_cards: list[Action] = field(default_factory=list)
    has_data: bool = False
    next_lottery_text: str = ""
    parity: list[dict] = field(default_factory=list)        # ?debug=1 と deploy-check #810
    hidden_prices: int = 0                                   # 表示ガードで外した BUY
    alert_count: int = 0                                     # HOME に出さない ALERT
    opp_total: int = 0

    def ordered_cards(self) -> list[tuple[str, int, int, int, object]]:
        """HOME のカードを (種類, bucket, sort, idx, 本体) で並べる（JS の reorder と同じ順）。"""
        rows: list = []
        for i, vm in enumerate(self.vms):
            stt = self.states[vm["id"]]
            rows.append(("lot", stt["bucket"], stt["sort"], i, vm))
        for a in self.opp_cards:
            rows.append(("opp", a.bucket, 0, a.idx, a))
        rows.sort(key=lambda r: (r[1], r[2], r[3]))
        return rows

    @property
    def actions(self) -> list:
        """HOME に表示されるカード（最大 TOP_ACTIONS_LIMIT 件）。"""
        return [r for r in self.ordered_cards() if r[1] < rt.BUCKET_HIDDEN][:TOP_ACTIONS_LIMIT]


def build_home_model(*, tcg_report: dict | None, opportunities: dict | None,
                     profit_routes: dict | None, legacy_lotteries: list[dict] | None,
                     now: datetime | None = None) -> HomeModel:
    """既存の出力から HOME の数字とカードを作る（抽選の状態は runtime だけで決める）。"""
    now = (now or datetime.now(tz=JST)).astimezone(JST)
    report = tcg_report if isinstance(tcg_report, dict) else {}
    opps = opportunities if isinstance(opportunities, dict) else {}
    routes = profit_routes if isinstance(profit_routes, dict) else {}
    m = HomeModel(now=now)
    m.vms = rt.build_vms(report, legacy_lotteries)
    m.has_data = bool(report or opps or routes or m.vms)
    m.states = {vm["id"]: rt.derive_runtime_state(vm, now) for vm in m.vms}

    events = [e for e in (report.get("events") or []) if isinstance(e, dict)]
    available = [e for e in events if e.get("status") == "AVAILABLE_NOW" and not e.get("stale")]
    premium = [e for e in events if premium_ok(e.get("premium"))
               and e.get("status") != "ENDED" and not e.get("stale")]
    main_routes = [r for r in (routes.get("main_routes") or []) if isinstance(r, dict)]
    ok_routes = [r for r in main_routes if not route_reject_reason(r)]
    sts = m.states.values()
    m.counts = {
        "lottery_open": sum(1 for s in sts if s["open"]),
        "ending_today": sum(1 for s in sts if s["ending_today"]),
        "starting_24h": sum(1 for s in sts if s["starting_24h"]),
        "available_now": len(available),
        "high_profit": len(ok_routes),
        "high_premium": len(premium),
    }
    if not m.counts["lottery_open"]:
        m.next_lottery_text = rt.next_start_note(m.vms, m.states)

    # ── AI Opportunities（既存のアクションをそのまま使い、並べ方だけ決める） ──
    opp_list = [o for o in (opps.get("todays_opportunities") or []) if isinstance(o, dict)]
    opp_list.sort(key=lambda o: (o.get("priority") is None, o.get("priority") or 0))
    m.opp_total = len(opp_list)
    base_idx = len(m.vms)
    skip_seen = False
    for i, o in enumerate(opp_list):
        act = str(o.get("action") or "")
        name = str(o.get("product") or "")
        idx = base_idx + i
        if act == "BUY":
            if opportunity_reject_reason(o):
                m.hidden_prices += 1
                continue
            roi = _num(o.get("roi")) or 0.0
            m.opp_cards.append(Action(
                action="BUY", title=name,
                subtitle=f"{o.get('buy_source') or ''} → {o.get('sell_source') or ''}".strip(" →"),
                primary=f"利益 +¥{int(float(o['net_profit'])):,}（{roi * 100:.0f}%）",
                secondary="手数料込みの見込み",
                cta_label="詳しく見る", cta_href=page_href("profit"),
                bucket=rt.BUCKET_BUY, idx=idx))
        elif act == "WAIT":
            # 参考扱いの値は金額を出さない（内部の設定名なども一般向けには出さない）
            m.opp_cards.append(Action(
                action="WAIT", title=name, subtitle="参考情報（未検証）",
                secondary="価格の更新を待っています",
                cta_label="詳しく見る", cta_href=page_href("profit"),
                bucket=rt.BUCKET_WAIT, idx=idx))
        elif act == "SKIP":
            m.opp_cards.append(Action(
                action="SKIP", title=name, subtitle="利益が確認できません",
                cta_label="詳しく見る", cta_href=page_href("profit"),
                bucket=rt.BUCKET_HIDDEN if skip_seen else rt.BUCKET_SKIP, idx=idx))
            skip_seen = True
        elif act == "ALERT":
            m.alert_count += 1
    return m


# ── 表示 ──────────────────────────────────────────────────────────

TILES = (
    # key, icon, label, tone, 行き先
    ("lottery_open", "🎯", "抽選受付中", "success", "lottery"),
    ("ending_today", "⏰", "今日締切", "danger", "lottery"),
    ("starting_24h", "📅", "24時間以内に開始", "warning", "lottery"),
    ("available_now", "🔥", "今買える", "success", "lottery"),
    ("high_profit", "💰", "高利益", "success", "profit"),
    ("high_premium", "📈", "高プレミア", "info", "lottery"),
)
# 閲覧時に件数を数え直すタイル（抽選の runtime state から決まるもの）
RUNTIME_TILES = ("lottery_open", "ending_today", "starting_24h")


def render_home(m: HomeModel, *, source_issue: bool = False) -> str:
    tiles = "".join(
        c.tile(key=key, icon=icon, label=label, count=m.counts.get(key, 0), tone=tone,
               href=page_href(dest), runtime=key in RUNTIME_TILES,
               note=(m.next_lottery_text if key == "lottery_open" else ""))
        for key, icon, label, tone, dest in TILES)
    shown = 0
    cards = []
    for kind, bucket, _sort, idx, obj in m.ordered_cards():
        hide = bucket >= rt.BUCKET_HIDDEN or shown >= TOP_ACTIONS_LIMIT
        if not hide:
            shown += 1
        if kind == "lot":
            cards.append(lottery_card.render(obj, m.states[obj["id"]], idx, hidden=hide))
        else:
            cards.append(obj.render(hidden=hide))
    if not m.has_data:
        empty = c.empty_state("NO_DATA", "まだ情報がありません",
                              "最初の取得が終わると、ここに今日やることが表示されます")
    else:
        empty = c.empty_state("NO_ACTIVE", "今すぐやることはありません",
                              "次の抽選情報・価格の変化を監視しています")
    empty = empty.replace("<div ", f'<div data-nu-empty-home{" hidden" if shown else ""} ', 1)
    issue = (c.notice("一部の情報源を取得できていません。必ず公式サイトでもご確認ください。")
             if source_issue else "")
    return (
        '<section class="nu-page" data-nu-page="home" aria-labelledby="nu-home-title">'
        '<div class="nu-hero"><h1 id="nu-home-title" class="nu-hero__title">今日のチャンス</h1></div>'
        f'<div class="nu-tiles">{tiles}</div>'
        f'{issue}'
        '<h2 class="nu-h2">おすすめアクション TOP5</h2>'
        f'<div class="nu-cards" data-nu-actions="{shown}" data-nu-limit="{TOP_ACTIONS_LIMIT}">'
        f'{"".join(cards)}{empty}</div>'
        '<p class="nu-disclaimer">掲載情報は取得時点の参考です。購入・応募の前に必ず公式サイトでご確認ください。</p>'
        '</section>'
    )
