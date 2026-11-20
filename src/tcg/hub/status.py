# -*- coding: utf-8 -*-
"""TCG Lottery Hub: 状態の再導出・今日応募可能の判定・応募優先度（S / A / B / WATCH）。

方針（新しい閾値・点数は作らない）:
- 状態は保存値を信じず、now から `compute_lottery_status`（既存）で毎回導出する。日付だけの項目は時刻を作らない。
- 優先度は既存の `event_quality.priority_of` と `action_url.classify` の結果を並べ替える写像だけ。
  利益や点数には結びつけない（利益の根拠は `profit_link` が扱い、根拠が無ければ算出前）。
- 入力が空・欠損・型違いでも例外にしない（読めない値は None / UNKNOWN / 対象外にする）。

自分の応募状態（未応募 / 応募済み / 当選 / 落選 / 購入済み）の設計メモ（今回は実装しない）:
- 保存先はブラウザの localStorage だけ（サーバーに送らない・アカウントも作らない）。
- キー案: `tcgHub.v1.entry.<lottery_id>` = JSON `{"s": "NONE|APPLIED|WON|LOST|PURCHASED", "t": 更新時刻(ISO)}`。
  lottery_id は lotteries.json の `lottery_id`（同一抽選の安定キー）。
- 読み書きは try/catch で囲み、保存できなくてもページは動く。公開 HTML には個人の状態を埋め込まない。
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Optional

from src.tcg import action_url as au
from src.tcg import event_quality as eq
from src.tcg.lottery import schema as ls
from src.tcg.models import now_jst

# 状態の表示名（保存値ではなく導出した状態に付ける）
STATUS_LABEL = {
    ls.L_OPEN: "受付中", ls.L_ENDING_SOON: "締切間近", ls.L_UPCOMING: "近日開始",
    ls.L_RESULT_PENDING: "結果待ち", ls.L_CLOSED: "締切後（発表日未定）",
    ls.L_WINNER_ANNOUNCED: "当選発表済み", ls.L_WINNER_PURCHASE_PERIOD: "購入期間中",
    ls.L_ENDED: "終了", ls.L_UNKNOWN: "日程未確認",
}
# 商品単位の集約で「いちばん手前に出す」順（先頭ほど優先して見せる）
_AGG_ORDER = (ls.L_ENDING_SOON, ls.L_OPEN, ls.L_UPCOMING, ls.L_WINNER_PURCHASE_PERIOD, ls.L_WINNER_ANNOUNCED,
              ls.L_RESULT_PENDING, ls.L_CLOSED, ls.L_UNKNOWN, ls.L_ENDED)
APPLYING = frozenset({ls.L_OPEN, ls.L_ENDING_SOON})        # いま応募できる状態
INTAKE = frozenset({ls.L_UPCOMING, ls.L_OPEN, ls.L_ENDING_SOON})   # 応募が済んでいない（開始前または受付中）

P_S, P_A, P_B, P_WATCH = "S", "A", "B", "WATCH"
PRIORITY_ORDER = (P_S, P_A, P_B, P_WATCH)


def live_status(ev, now: Optional[datetime] = None) -> str:
    """now から導出した状態。保存されている `status` は使わない。壊れた入力は UNKNOWN。"""
    if not isinstance(ev, dict):
        return ls.L_UNKNOWN
    try:
        st = ls.compute_lottery_status(ev, now or now_jst())
    except Exception:  # noqa: BLE001 — 1 件の壊れた行で全体を止めない
        return ls.L_UNKNOWN
    return st if st in ls.LOTTERY_STATUSES else ls.L_UNKNOWN


def is_applicable_today(ev, now: Optional[datetime] = None) -> bool:
    """今日応募できる = 導出した状態が受付中 / 締切間近で、日程の食い違い（conflict）が無く、確認済み（verified）のもの。

    開始が日付だけのものは、開始日当日は開始前（compute_lottery_status の安全側の扱い）なので含めない。
    締切が日付だけのものは締切日当日まで含める（その日の何時までかは作らない）。
    """
    if not isinstance(ev, dict) or ev.get("conflict") is True or ev.get("verified") is not True:     # 未確認（公式での再確認待ち）は「今日応募可能」に数えない
        return False
    return live_status(ev, now) in APPLYING


def aggregate_status(statuses) -> str:
    """商品に束ねた複数の抽選の状態から、手前に出す 1 つを選ぶ。空なら UNKNOWN。"""
    present = {s for s in (statuses or []) if isinstance(s, str)}
    for s in _AGG_ORDER:
        if s in present:
            return s
    return ls.L_UNKNOWN


def priority_of_event(ev, now: Optional[datetime] = None, *, bound_exact: bool = False) -> Optional[str]:
    """応募優先度 S / A / B / WATCH。応募期間が終わったもの（結果待ち以降）は None（対象外）。

    既存関数の結果を写すだけ:
      WATCH = 日程未確認・日程の食い違い・未確認（verified でない）・商品に exact で紐付いていない
      S     = priority_of が DEADLINE_SOON かつ classify の quality が complete（応募の URL まで確認済み）
      A     = priority_of が ACTIVE_LOTTERY / PREORDER_OPEN
      B     = それ以外の受付中・開始前
    """
    if not isinstance(ev, dict):
        return None
    now = now or now_jst()
    st = live_status(ev, now)
    if st not in INTAKE and st != ls.L_UNKNOWN:
        return None
    if (st == ls.L_UNKNOWN or ev.get("conflict") is True or ev.get("verified") is not True or not bound_exact):
        return P_WATCH
    try:
        live = copy.copy(ev)
        live["status"] = st                                   # priority_of は status を読む。導出した値を渡す
        prio = eq.priority_of(live, now)
        quality = au.classify(live, now)["quality"]
    except Exception:  # noqa: BLE001
        return P_WATCH
    if prio == eq.P_DEADLINE_SOON and quality == au.Q_COMPLETE:
        return P_S
    if prio in (eq.P_ACTIVE_LOTTERY, eq.P_PREORDER_OPEN):
        return P_A
    return P_B
