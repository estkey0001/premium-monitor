"""LINE配信用テンプレート生成 (Phase 10)。"""

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
EXPORTS_DIR = PROJECT_ROOT / "exports" / "line_messages"


class LINEMessageGenerator:
    """LINE配信用メッセージを生成する。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def generate_all(self) -> dict:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")

        messages = {
            "beginner_easy": self._beginner_easy(),
            "beginner_watch": self._beginner_watch(),
            "weekly_summary": self._weekly_summary(),
            "caution_reminder": self._caution_reminder(),
            "welcome_step": self._welcome_step(),
        }

        # 安全チェック
        all_forbidden = []
        for key, msg in messages.items():
            forbidden = check_forbidden(msg)
            if forbidden:
                messages[key], _ = sanitize_text(msg)
                all_forbidden.extend(forbidden)

        # 保存
        for key, msg in messages.items():
            path = EXPORTS_DIR / f"line_{key}_{date_str}.txt"
            path.write_text(msg, encoding="utf-8")

        return {
            "messages": messages,
            "count": len(messages),
            "exports_dir": str(EXPORTS_DIR),
            "forbidden_found": all_forbidden,
        }

    def _beginner_easy(self) -> str:
        deals = self.repo.list_beginner_deals(user_level="beginner_easy", min_profit=5000, limit=3)
        lines = ["🟢 初心者向け案件速報", ""]
        if not deals:
            lines.append("現在、条件を満たす案件はありません。")
        else:
            for d in deals:
                lines.extend([
                    f"■ {d.product_name}",
                    f"  公式: {fmt_price(d.official_price_jpy)}",
                    f"  買取: {fmt_price(d.best_buyback_price)}（{d.best_buyback_shop}）",
                    f"  実質利益: {fmt_profit(d.net_profit_jpy)}（{fmt_rate(d.net_profit_rate)}）",
                    f"  条件: {d.buyback_condition or '新品未開封'}",
                    "",
                ])
        lines.extend(["", DISCLAIMER_SHORT])
        return "\n".join(lines)

    def _beginner_watch(self) -> str:
        deals = self.repo.list_beginner_deals(user_level="beginner_watch", min_profit=0, limit=3)
        lines = ["🟡 価格ウォッチ情報", ""]
        if not deals:
            lines.append("現在、ウォッチ対象の案件はありません。")
        else:
            for d in deals:
                lines.extend([
                    f"■ {d.product_name}",
                    f"  公式: {fmt_price(d.official_price_jpy)}",
                    f"  買取: {fmt_price(d.best_buyback_price)}",
                    f"  差額: {fmt_profit(d.gross_profit_jpy)}（コスト差引前）",
                    f"  → 条件次第で案件化の可能性あり",
                    "",
                ])
        lines.extend(["", "在庫・買取価格の変動を引き続き監視中です。", "", DISCLAIMER_SHORT])
        return "\n".join(lines)

    def _weekly_summary(self) -> str:
        deals = self.repo.list_beginner_deals(user_level="beginner", min_profit=3000, limit=5)
        lines = [
            "📊 週間まとめ",
            "",
            f"今週の初心者向け案件: {len(deals)} 件",
            "",
        ]
        if deals:
            for d in deals:
                lines.append(f"  ・{d.product_name}: 実質{fmt_profit(d.net_profit_jpy)}")
        lines.extend(["", "詳細はnoteレポートをご確認ください。", "", DISCLAIMER_SHORT])
        return "\n".join(lines)

    def _caution_reminder(self) -> str:
        return "\n".join([
            "⚠️ 定期リマインド",
            "",
            "当チャンネルの情報は価格差の監視結果です。",
            "",
            "・価格/在庫/買取条件は常に変動します",
            "・購入前に必ず公式ページで最新情報を確認してください",
            "・買取条件（新品未開封/SIMフリー等）の確認は必須です",
            "・利益を保証するものではありません",
            "",
            "不明点があればお気軽にご質問ください。",
        ])

    def _welcome_step(self) -> str:
        return "\n".join([
            "🎉 ご登録ありがとうございます！",
            "",
            "このLINEでは、公式価格と買取価格の差額情報を配信しています。",
            "",
            "【配信内容】",
            "1️⃣ 初心者向け案件速報（低難度・再現性重視）",
            "2️⃣ 週間まとめレポート",
            "3️⃣ 在庫変動の速報",
            "",
            "【最初にやること】",
            "・noteの初心者ガイドを読む → [リンク]",
            "・過去の配信をチェックする",
            "・不明点はメッセージで質問OK",
            "",
            "今後ともよろしくお願いします！",
            "",
            DISCLAIMER_SHORT,
        ])
