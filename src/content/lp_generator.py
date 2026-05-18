"""LP（ランディングページ）素材生成 (Phase 10)。"""

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
EXPORTS_DIR = PROJECT_ROOT / "exports" / "lp"


class LPGenerator:
    """LP用コピー素材を生成する。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def generate(self) -> dict:
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        deals = self.repo.list_beginner_deals(user_level="beginner", min_profit=3000, limit=5)
        now = datetime.now()

        sections = {
            "headline": self._headline(deals),
            "sub_copy": self._sub_copy(),
            "benefits": self._benefits(deals),
            "case_study": self._case_study(deals),
            "caution": self._caution(),
            "line_cta": self._line_cta(),
            "note_cta": self._note_cta(),
            "faq": self._faq(),
        }

        # 全文結合
        full = "\n\n".join(sections.values())

        # 安全チェック
        forbidden = check_forbidden(full)
        if forbidden:
            full, _ = sanitize_text(full)
            for k in sections:
                sections[k], _ = sanitize_text(sections[k])

        # 保存
        path = EXPORTS_DIR / f"lp_copy_{now.strftime('%Y%m%d')}.md"
        path.write_text(full, encoding="utf-8")

        return {
            "path": str(path),
            "sections": sections,
            "full_text": full,
            "char_count": len(full),
            "forbidden_found": forbidden,
        }

    def _headline(self, deals) -> str:
        if deals:
            best = deals[0]
            return (
                f"# 公式価格と買取価格の差額を、毎日チェック。\n\n"
                f"例: {best.product_name}\n"
                f"公式 {fmt_price(best.official_price_jpy)} → "
                f"買取 {fmt_price(best.best_buyback_price)} "
                f"= 差額 {fmt_profit(best.gross_profit_jpy)}"
            )
        return "# 公式価格と買取価格の差額を、毎日チェック。"

    def _sub_copy(self) -> str:
        return (
            "## 誰でも確認できる「公開情報」を整理して配信\n\n"
            "Apple公式・量販店の定価と、買取専門店の買取価格。\n"
            "この2つの差額を毎日監視し、条件が良い商品を速報でお届けします。\n\n"
            "特別なスキルは不要。公式サイトで買い、買取店に送るだけ。\n"
            "ただし価格は常に変動します。最新情報の確認は必須です。"
        )

    def _benefits(self, deals) -> str:
        lines = [
            "## こんな情報が届きます",
            "",
            "1. **初心者でも分かりやすい低難度案件** — 公式で買える＋買取が定価超え",
            "2. **実質利益の計算済み** — 送料・手数料を差し引いた実利益を表示",
            "3. **複数買取店の比較** — モバイル一番・買取商店・じゃんぱら等を横断比較",
            "4. **在庫・価格変動の速報** — SOLD OUT・価格変更をいち早く通知",
        ]
        if deals:
            lines.extend(["", "**直近の実績例:**", ""])
            for d in deals[:3]:
                lines.append(
                    f"- {d.product_name}: "
                    f"公式{fmt_price(d.official_price_jpy)} → 買取{fmt_price(d.best_buyback_price)} "
                    f"= 実質利益{fmt_profit(d.net_profit_jpy)}"
                )
        return "\n".join(lines)

    def _case_study(self, deals) -> str:
        if not deals:
            return ""
        d = deals[0]
        return (
            f"## 具体例: {d.product_name}\n\n"
            f"| ステップ | 内容 |\n|---|---|\n"
            f"| 1. 公式で購入 | {fmt_price(d.official_price_jpy)} |\n"
            f"| 2. 買取店に送付 | {d.best_buyback_shop} |\n"
            f"| 3. 買取入金 | {fmt_price(d.best_buyback_price)} |\n"
            f"| 4. コスト | -{fmt_price(d.estimated_costs_jpy)}（送料+手数料） |\n"
            f"| **実質利益** | **{fmt_profit(d.net_profit_jpy)}（利益率{fmt_rate(d.net_profit_rate)}）** |\n\n"
            f"{DISCLAIMER_SHORT}"
        )

    def _caution(self) -> str:
        return (
            "## ご注意\n\n"
            "- 本サービスは価格差情報の配信であり、購入を推奨するものではありません。\n"
            "- 価格・在庫・買取条件は常に変動します。\n"
            "- 購入前に必ず公式サイトと買取店の最新条件を確認してください。\n"
            "- 利益を保証するものではありません。\n"
            "- 条件が合えば利益が出る可能性がある情報を整理してお届けしています。"
        )

    def _line_cta(self) -> str:
        return (
            "## LINE登録で速報を受け取る\n\n"
            "公式LINEでは、初心者向けの低難度案件を優先的に配信しています。\n\n"
            "- 公式価格と買取価格の差額速報\n"
            "- 在庫変動の通知\n"
            "- 週間まとめレポート\n\n"
            "▼ 公式LINE登録はこちら ▼\n"
            "[LINE登録ボタン]"
        )

    def _note_cta(self) -> str:
        return (
            "## noteで詳細レポートを読む\n\n"
            "noteでは、より詳しい分析レポートを公開しています。\n\n"
            "- 初心者向け: 毎週の低難度プレ値候補まとめ\n"
            "- 上級者向け: 高利益候補と海外価格差分析\n"
            "- 買取店比較: 複数店舗の横断比較レポート\n\n"
            "▼ noteはこちら ▼\n"
            "[note販売ページ]"
        )

    def _faq(self) -> str:
        return (
            "## よくある質問\n\n"
            "**Q. 本当に利益が出ますか？**\n"
            "A. 価格差が確認された時点の情報です。価格・在庫は変動するため、利益を保証するものではありません。\n\n"
            "**Q. 初心者でもできますか？**\n"
            "A. 公式ストアでの購入と買取店への発送という、シンプルな手順の案件を中心にお届けしています。\n\n"
            "**Q. リスクはありますか？**\n"
            "A. 買取価格の変動、在庫切れ、買取条件の変更等のリスクがあります。必ず最新情報を確認してください。\n\n"
            "**Q. 自動購入ツールですか？**\n"
            "A. いいえ。価格監視・比較・通知のみを行うサービスです。購入・応募は一切自動化していません。"
        )
