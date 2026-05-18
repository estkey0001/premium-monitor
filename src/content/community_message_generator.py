"""Discord / Telegram 向けテンプレート生成 (Phase 10)。"""

import logging
from datetime import datetime
from pathlib import Path

from src.content.safety import (
    check_forbidden, sanitize_text, fmt_price, fmt_profit, fmt_rate,
    DISCLAIMER_SHORT,
)
from src.db.repository import Repository

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports" / "community_messages"


class CommunityMessageGenerator:
    """Discord / Telegram 向けメッセージを生成する。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def generate_all(self) -> dict:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")

        messages = {
            "advanced_alert": self._advanced_alert(),
            "expert_notice": self._expert_notice(),
            "overseas_gap": self._overseas_gap(),
            "lottery_alert": self._lottery_alert(),
            "soldout_alert": self._soldout_alert(),
        }

        all_forbidden = []
        for key, msg in messages.items():
            forbidden = check_forbidden(msg)
            if forbidden:
                messages[key], _ = sanitize_text(msg)
                all_forbidden.extend(forbidden)

        for key, msg in messages.items():
            path = EXPORTS_DIR / f"community_{key}_{date_str}.txt"
            path.write_text(msg, encoding="utf-8")

        return {
            "messages": messages,
            "count": len(messages),
            "exports_dir": str(EXPORTS_DIR),
            "forbidden_found": all_forbidden,
        }

    def _advanced_alert(self) -> str:
        snaps = self.repo.list_premium_candidates_with_snapshots(limit=5, user_level="advanced")
        lines = ["🟠 **【上級者向け速報】高利益プレ値候補**", ""]
        if not snaps:
            lines.append("現在、条件を満たす候補はありません。")
        else:
            for s in snaps:
                method_label = {"lottery": "抽選", "soldout": "SOLD OUT", "discontinued": "終了"}.get(s.sale_method, s.sale_method)
                lines.extend([
                    f"**{s.product_name}**",
                    f"  定価: {fmt_price(s.official_price_jpy)} | 中古: {fmt_price(s.domestic_used_price_jpy)} | 差: {fmt_profit(s.premium_gap_jpy)}",
                    f"  方式: {method_label} | 難易度: {s.difficulty_score:.2f} | score: {s.overall_score:.2f}",
                    "",
                ])
        lines.extend([DISCLAIMER_SHORT])
        return "\n".join(lines)

    def _expert_notice(self) -> str:
        snaps = self.repo.list_premium_candidates_with_snapshots(limit=5, user_level="advanced")
        expert = [s for s in snaps if s.user_level == "expert_only" or s.difficulty_score >= 0.7]
        lines = ["🔴 **【エキスパート向け】高難度監視候補**", ""]
        if not expert:
            lines.append("現在、エキスパート向け候補はありません。")
        else:
            for s in expert:
                lines.extend([
                    f"**{s.product_name}** — 難易度: {s.difficulty_score:.2f}",
                    f"  定価: {fmt_price(s.official_price_jpy)} | 差: {fmt_profit(s.premium_gap_jpy)} | 方式: {s.sale_method}",
                    f"  ⚠️ 入手が非常に困難。情報収集・長期監視向け。",
                    "",
                ])
        lines.extend([DISCLAIMER_SHORT])
        return "\n".join(lines)

    def _overseas_gap(self) -> str:
        snaps = self.repo.list_market_snapshots(min_score=0, limit=50)
        overseas = [s for s in snaps if s.overseas_gap_percent and s.overseas_gap_percent >= 10]
        overseas.sort(key=lambda s: s.overseas_gap_percent or 0, reverse=True)

        lines = ["🌍 **【海外価格差速報】**", ""]
        if not overseas:
            lines.append("現在、10%以上の海外価格差がある商品はありません。")
        else:
            for s in overseas[:5]:
                lines.extend([
                    f"**{s.product_name}**",
                    f"  国内定価: {fmt_price(s.official_price_jpy)} | 海外(JPY): {fmt_price(s.overseas_price_jpy)}",
                    f"  海外差: +{s.overseas_gap_percent}%（{fmt_profit(s.overseas_gap_jpy)}）",
                    "",
                ])
        lines.extend([DISCLAIMER_SHORT])
        return "\n".join(lines)

    def _lottery_alert(self) -> str:
        snaps = self.repo.list_market_snapshots(min_score=0, limit=50)
        lottery = [s for s in snaps if s.sale_method == "lottery"]
        lines = ["🎰 **【抽選販売速報】**", ""]
        if not lottery:
            lines.append("現在、抽選販売中の監視商品はありません。")
        else:
            for s in lottery:
                lines.extend([
                    f"**{s.product_name}** — 抽選販売中",
                    f"  定価: {fmt_price(s.official_price_jpy)} | 中古: {fmt_price(s.domestic_used_price_jpy)} | 差: {fmt_profit(s.premium_gap_jpy)}",
                    "",
                ])
        lines.extend(["応募方法は各メーカー公式サイトをご確認ください。", "", DISCLAIMER_SHORT])
        return "\n".join(lines)

    def _soldout_alert(self) -> str:
        snaps = self.repo.list_market_snapshots(min_score=0, limit=50)
        soldout = [s for s in snaps if s.sale_method in ("soldout", "discontinued")]
        lines = ["🔴 **【SOLD OUT速報】**", ""]
        if not soldout:
            lines.append("現在、SOLD OUT/販売終了の監視商品はありません。")
        else:
            for s in soldout:
                label = "SOLD OUT" if s.sale_method == "soldout" else "販売終了"
                lines.extend([
                    f"**{s.product_name}** — {label}",
                    f"  定価: {fmt_price(s.official_price_jpy)} | 中古: {fmt_price(s.domestic_used_price_jpy)} | 差: {fmt_profit(s.premium_gap_jpy)}",
                    "",
                ])
        lines.extend(["再販情報は各メーカー公式サイトをご確認ください。", "", DISCLAIMER_SHORT])
        return "\n".join(lines)
