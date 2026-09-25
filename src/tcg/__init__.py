# -*- coding: utf-8 -*-
"""TCG（ポケモンカード / ONE PIECEカードゲーム）入荷・抽選・プレミア監視レイヤー。

既存の Profit / AI / Opportunity / Notification / Capital / Execution / API /
Source Matching には手を加えない、独立した追加レイヤー。
"""
from .models import TcgEvent, event_from_dict  # noqa: F401

__all__ = ["TcgEvent", "event_from_dict"]
