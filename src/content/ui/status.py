"""新UIの状態（ステータス）表示の対応表。

状態の「判定」は既存ロジック（src/tcg/lottery など）のまま変えない。
ここでは判定済みの状態コードを、表示用の文言・色・アイコン・並び順に対応付けるだけ。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.content.ui.design_tokens import TONES


@dataclass(frozen=True)
class Status:
    key: str
    label: str      # ユーザー向けの文言
    tone: str       # design_tokens.TONES のキー
    icon: str       # 文言の前に付ける絵文字（色だけで伝えないため）
    priority: int   # 小さいほど上に並べる


_ALL: tuple[Status, ...] = (
    # 抽選
    Status("ENDING_SOON", "締切間近", "danger", "⏰", 10),
    Status("OPEN", "受付中", "success", "🎯", 20),
    Status("UPCOMING", "まもなく開始", "warning", "📅", 30),
    Status("SOURCE_CONFLICT", "日程要確認", "warning", "⚠️", 35),
    Status("RESULT_PENDING", "結果待ち", "info", "⏳", 40),
    Status("WINNER_ANNOUNCED", "当選発表", "info", "🏆", 41),
    Status("WINNER_PURCHASE_PERIOD", "当選者購入期間", "info", "🛒", 42),
    Status("CLOSED", "受付終了・結果待ち", "info", "⏳", 43),
    Status("ENDED", "終了", "neutral", "■", 90),
    # 販売
    Status("AVAILABLE", "販売中", "success", "🔥", 25),
    Status("COMING_SOON", "発売予定", "info", "🗓", 45),
    # アクション（内部値はそのまま、文言だけ日本語にする）
    Status("APPLY", "応募する", "success", "🎯", 1),
    Status("BUY", "買う", "success", "💰", 2),
    Status("WAIT", "待つ", "warning", "⏳", 3),
    Status("SKIP", "見送る", "neutral", "—", 4),
    # 注意・情報源
    Status("ALERT", "注意", "danger", "❗", 15),
    Status("BLOCKED", "取得できません", "neutral", "🚫", 85),
    Status("UNKNOWN", "日程未確認", "neutral", "？", 95),
)

STATUSES: dict[str, Status] = {s.key: s for s in _ALL}

# 抽選の状態コード（src/tcg/lottery の値）→ 表示用キー
_LOTTERY_KEYS = {
    "OPEN": "OPEN",
    "ENDING_SOON": "ENDING_SOON",
    "UPCOMING": "UPCOMING",
    "CLOSED": "CLOSED",                  # 受付は終わり、結果発表日は未公表
    "RESULT_PENDING": "RESULT_PENDING",
    "WINNER_ANNOUNCED": "WINNER_ANNOUNCED",
    "WINNER_PURCHASE_PERIOD": "WINNER_PURCHASE_PERIOD",
    "ENDED": "ENDED",
    "UNKNOWN": "UNKNOWN",
}

# アクションの内部値 → 表示用キー（内部値は変更しない）
ACTION_KEYS = ("APPLY", "BUY", "WAIT", "SKIP")


def get(key: str) -> Status:
    """状態を返す。未登録のキーは UNKNOWN として扱う（勝手に別の状態にしない）。"""
    return STATUSES.get(key) or STATUSES["UNKNOWN"]


def lottery_status(ev: dict) -> Status:
    """抽選1件の表示用状態。公式情報が食い違うものは状態に関係なく「日程要確認」。"""
    if ev.get("conflict"):
        return STATUSES["SOURCE_CONFLICT"]
    return get(_LOTTERY_KEYS.get(str(ev.get("status") or "UNKNOWN"), "UNKNOWN"))


def action_label(action: str) -> str:
    """アクションの内部値（BUY 等）をユーザー向け文言にする。"""
    return get(action).label if action in ACTION_KEYS else str(action)


def validate() -> list[str]:
    """対応表の整合性を確かめる。問題があれば内容を返す（テスト・deploy-check 用）。"""
    problems: list[str] = []
    for s in _ALL:
        if s.tone not in TONES:
            problems.append(f"{s.key}: 未定義の色 {s.tone}")
        if not s.label or not s.icon:
            problems.append(f"{s.key}: 文言またはアイコンが空")
    if len(STATUSES) != len(_ALL):
        problems.append("状態キーが重複している")
    for target in _LOTTERY_KEYS.values():
        if target not in STATUSES:
            problems.append(f"抽選の対応先 {target} が未登録")
    return problems
