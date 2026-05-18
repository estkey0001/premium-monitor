"""コンテンツ安全表現チェック・置換共通ヘルパー。"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

FORBIDDEN_PHRASES = [
    "確実に儲かる", "絶対利益", "誰でも稼げる", "今すぐ買え",
    "買えば勝ち", "ノーリスク", "guaranteed", "sure profit",
    "必ず儲かる", "100%利益", "損しない", "絶対に稼げる",
    "確実に利益", "リスクゼロ", "損失ゼロ",
]

SAFE_REPLACEMENTS = {
    "確実に儲かる": "利益が出る可能性があります",
    "絶対利益": "利益が見込めます",
    "誰でも稼げる": "条件を確認すれば始めやすい案件です",
    "今すぐ買え": "在庫があるうちに確認をおすすめします",
    "買えば勝ち": "価格差が確認されています",
    "ノーリスク": "リスクを理解した上でご判断ください",
    "必ず儲かる": "利益が出る可能性があります",
    "確実に利益": "利益が見込まれています",
    "リスクゼロ": "リスクを確認の上ご判断ください",
}

DISCLAIMER_SHORT = "※価格・在庫・買取条件は変動します。購入判断は各自でご確認ください。"

DISCLAIMER_FULL = """---
免責事項
- 本情報は価格差の監視結果であり、購入を推奨するものではありません。
- 価格・在庫・買取条件は常に変動します。
- 購入前に必ず公式サイト・買取店で最新の条件を確認してください。
- 投資判断・購入判断は各自の責任で行ってください。
- 本情報に基づく損失について、一切の責任を負いません。
---"""


def check_forbidden(text: str) -> list[str]:
    """禁止表現をチェックし、検出されたフレーズのリストを返す。"""
    found = []
    text_lower = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in text_lower:
            found.append(phrase)
    return found


def sanitize_text(text: str) -> tuple[str, list[str]]:
    """禁止表現を安全な表現に置換する。置換されたフレーズのリストも返す。"""
    replaced = []
    for phrase, safe in SAFE_REPLACEMENTS.items():
        if phrase in text:
            text = text.replace(phrase, safe)
            replaced.append(phrase)
    # 残りの禁止表現（置換候補がないもの）を削除
    remaining = check_forbidden(text)
    for phrase in remaining:
        text = text.replace(phrase, "")
        replaced.append(phrase)
    return text, replaced


def fmt_price(v) -> str:
    if v is None or v == 0:
        return "---"
    return f"¥{int(v):,}"


def fmt_profit(v) -> str:
    if v is None or v == 0:
        return "---"
    return f"+¥{int(v):,}"


def fmt_rate(v) -> str:
    if v is None or v == 0:
        return "---"
    return f"{v:.1%}"
