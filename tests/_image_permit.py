# -*- coding: utf-8 -*-
"""テスト用: 公式画像の「権利者の利用許可の記録」を差し替える（本番の記録 IMAGE_RIGHTS_PERMISSION は空）。"""
from src.tcg import verified_products as vp

ORIGINAL_RIGHTS_PERMISSION = vp.rights_permission


def _tcg_of(url: str) -> str:
    return "POKEMON" if "pokemon-card.com" in url else "ONE_PIECE" if "onepiece-cardgame.com" in url else ""


def permit_all(monkeypatch):
    """公式のホストの画像すべてに、許可の記録があることにする（表示の仕組みを試すため）。"""
    monkeypatch.setattr(vp, "rights_permission", lambda u: (
        {"tcg": _tcg_of(u), "basis": "test", "source_url": "https://example.test/permission", "checked_on": "2026-11-27"}
        if isinstance(u, str) and _tcg_of(u) else None))


def permit_none(monkeypatch):
    monkeypatch.setattr(vp, "rights_permission", lambda u: None)
