"""Phase 9A: user_level別通知振り分けルーティング。

user_levelに応じて通知先を分類する。
Notifier自体の実装は変えず、ルーティングテーブルでフィルタする。

ルーティング:
  beginner_easy     → LINE, X, note素材
  beginner_watch    → LINE, Discord
  advanced_high_profit → Discord, Telegram
  expert_only       → Discord（管理画面のみ）
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# user_level → 通知チャンネルのマッピング
USER_LEVEL_CHANNELS = {
    "beginner_easy": ["line", "x", "note"],
    "beginner_watch": ["line", "discord"],
    "advanced_high_profit": ["discord", "telegram"],
    "expert_only": ["discord"],
}

# alert_rank → デフォルト通知チャンネル（user_level未設定時のフォールバック）
RANK_CHANNELS = {
    "S": ["log", "discord", "telegram"],
    "A": ["log", "discord"],
    "B": ["log"],
    "C": ["log"],
}


def get_channels_for_alert(alert_rank: str, user_level: str = "") -> list[str]:
    """アラートの送信先チャンネルリストを返す。

    user_levelが設定されていればそちら優先、なければalert_rankでフォールバック。
    """
    if user_level and user_level in USER_LEVEL_CHANNELS:
        channels = USER_LEVEL_CHANNELS[user_level].copy()
        # logは常に含める
        if "log" not in channels:
            channels.insert(0, "log")
        return channels

    return RANK_CHANNELS.get(alert_rank, ["log"])


def get_template_channels_for_level(user_level: str) -> list[str]:
    """投稿テンプレートの生成先チャンネルを返す。"""
    return USER_LEVEL_CHANNELS.get(user_level, ["x", "discord"])


def should_notify_channel(channel: str, alert_rank: str, user_level: str = "") -> bool:
    """指定チャンネルに通知すべきかを判定する。"""
    allowed = get_channels_for_alert(alert_rank, user_level)
    return channel in allowed
