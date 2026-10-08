"""今すぐ行動できるようになった利益商品の通知の共通の部品（Phase 19。通知の種類 ACTIONABLE_NOW）。

既存の通知エンジン（scripts/generate_notifications.py の種類・優先度・配信先の構造、src/notifiers/routing の配信先）に
1つの種類として足す。判定はしない: 「今すぐ行動できるか」は src/market/actionability（Phase 18 の正本）が決め、
その結果（exports/opportunity_diagnostics の actionability.products）を読むだけ。利益も再計算しない。

候補・重複の抑制・配信の状態は src/notifiers/outbox（Phase 20）。ここは種類・本文・配信の直前の確認・dry-run の判定。
"""
from __future__ import annotations

import os
import math
from datetime import datetime

from src.market import actionability as act

TYPE = "ACTIONABLE_NOW"
PRIORITY = "Critical"            # 確定の利益 + 今すぐ行動できる（既存の WATCH_TO_BUY と同じ優先度）
RANK = "S"                       # 配信先は既存のランクの表（routing.RANK_CHANNELS）の S と同じ
TITLES = {act.IN_STOCK: "購入可能になりました", act.LOTTERY_OPEN: "抽選受付が始まりました",
          act.PREORDER_OPEN: "予約受付が始まりました", act.FIRST_COME_OPEN: "先着販売が始まりました"}
# re-arm（もう一度通知できるようにする）のは、通常販売で行動できないと確かめた状態だけ。抽選・予約・先着の受付終了では
# 消さない（ページの表示の揺れで同じ受付を2回通知しない。別の受付は受付の識別が変わるので通知する。レビュー M-2）
REARM_STATES = frozenset({act.OUT_OF_STOCK, act.SALE_ENDED})
# 確定の利益から外れた商品の台帳の状態（状態の変化を見ていないので、戻ってきたときは商品ごとの基準日として通知しない）
NOT_CONFIRMED = "NOT_CONFIRMED"


def is_dry_run(env=None) -> bool:
    """dry-run か（既定は dry-run。NOTIFICATION_DRY_RUN が "false" のときだけ外れる）。"""
    v = str((env if env is not None else os.environ).get("NOTIFICATION_DRY_RUN", "true")).strip().lower()
    return v not in ("false", "0", "no", "off")


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def message(c: dict) -> str:
    """通知の本文（値は診断の行のまま。利益を計算し直さない）。"""
    lines = [f"🎯 {TITLES.get(c['availability'], '')}", c.get("product") or c["product_id"]]
    if _finite(c.get("net_profit")):
        roi = f" / ROI {c['roi'] * 100:.1f}%" if _finite(c.get("roi")) else ""
        lines.append(f"想定純利益 +¥{int(c['net_profit']):,}{roi}（確定の利益案件）")
    if c.get("deadline"):
        d = act._dt(c["deadline"])
        if d is not None:
            lines.append("締切 " + d.strftime("%m/%d" if act.is_date_only(c["deadline"]) else "%m/%d %H:%M"))
    ck = act._dt(c.get("checked_at")) if c.get("checked_at") else None
    if ck is not None:
        lines.append(f"{ck.strftime('%m/%d %H:%M')} 公式で確認")
    lines.append(f"{c.get('cta_label') or ''}: {c.get('cta_url') or c.get('action_url') or ''}")
    return "\n".join(lines)


def revalidate_fields(c: dict, now: datetime) -> list[str]:
    """配信の直前の確認（Phase 19 の4条件。行動できない理由。空なら配信してよい）。生成から配信までに期限が過ぎたものを送らない。

    行動できる種類・理由なし・確定の利益（confirmed かつ利益 > 0）・期限（until_ms）が未来・抽選などは締切が未来・
    公式の購入/申込のページ。
    """
    why = []
    if c.get("availability") not in act.ACTIONABLE_TYPES:
        why.append("not_actionable")
    if c.get("reasons"):
        why.append("has_reasons")
    if not (c.get("confirmed") is True and _finite(c.get("net_profit")) and c["net_profit"] > 0):
        why.append("profit_not_confirmed")
    now_ms = int(now.timestamp() * 1000)
    if not isinstance(c.get("until_ms"), int) or isinstance(c.get("until_ms"), bool) or c["until_ms"] <= now_ms:
        why.append("expired")
    if c.get("availability") != act.IN_STOCK:
        d = act._dt(c.get("deadline")) if c.get("deadline") else None
        if d is None or d <= now:
            why.append("deadline_invalid")
    if not act._official_url(c.get("cta_url") or ""):
        why.append("url_not_official")
    return why
