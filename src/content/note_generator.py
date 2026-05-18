"""note記事自動生成 (Phase 10)。

beginner / advanced / weekly の3タイプのMarkdown記事を生成する。
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.content.safety import (
    check_forbidden, sanitize_text, fmt_price, fmt_profit, fmt_rate,
    DISCLAIMER_FULL, DISCLAIMER_SHORT,
)
from src.db.repository import Repository

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports" / "note_reports"


class NoteGenerator:
    """note販売用Markdown記事を生成する。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def generate(self, report_type: str = "beginner") -> dict:
        """記事を生成して保存する。"""
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        date_str = now.strftime("%Y%m%d")

        if report_type == "beginner":
            content = self._generate_beginner()
            filename = f"note_beginner_{date_str}"
        elif report_type == "advanced":
            content = self._generate_advanced()
            filename = f"note_advanced_{date_str}"
        elif report_type == "weekly":
            content = self._generate_weekly()
            filename = f"note_weekly_{date_str}"
        else:
            raise ValueError(f"Unknown type: {report_type}")

        # 安全表現チェック
        forbidden = check_forbidden(content)
        if forbidden:
            logger.warning("Forbidden phrases found: %s — sanitizing", forbidden)
            content, replaced = sanitize_text(content)

        # 保存
        md_path = EXPORTS_DIR / f"{filename}.md"
        txt_path = EXPORTS_DIR / f"{filename}.txt"
        md_path.write_text(content, encoding="utf-8")
        txt_path.write_text(content, encoding="utf-8")

        return {
            "type": report_type,
            "md_path": str(md_path),
            "txt_path": str(txt_path),
            "content": content,
            "char_count": len(content),
            "forbidden_found": forbidden,
        }

    # ===== beginner =====

    def _generate_beginner(self) -> str:
        deals = self.repo.list_beginner_deals(user_level="beginner", min_profit=3000, limit=10)
        now = datetime.now()
        date_display = now.strftime("%Y年%m月%d日")

        lines = [
            f"# 【初心者向け】今週の低難度プレ値候補まとめ",
            f"",
            f"*{date_display} 更新*",
            f"",
            f"## はじめに",
            f"",
            f"公式ストアで通常購入できる商品のうち、買取価格が公式定価を上回っている案件をまとめました。",
            f"条件が分かりやすく、初心者でも確認しやすい案件を中心に掲載しています。",
            f"",
            f"**重要**: 価格・在庫・買取条件は常に変動します。必ず購入前に最新情報を確認してください。",
            f"",
        ]

        if not deals:
            lines.extend([
                "## 今週の初心者向け案件",
                "",
                "現在、条件を満たす案件はありません。次回の更新をお待ちください。",
            ])
        else:
            lines.extend([
                f"## 今週の初心者向け案件（{len(deals)}件）",
                "",
            ])

            for i, d in enumerate(deals, 1):
                level_tag = "低難度" if d.user_level == "beginner_easy" else "要確認"
                lines.extend([
                    f"### {i}. {d.product_name}【{level_tag}】",
                    f"",
                    f"| 項目 | 内容 |",
                    f"|------|------|",
                    f"| 公式価格 | {fmt_price(d.official_price_jpy)} |",
                    f"| 買取価格 | {fmt_price(d.best_buyback_price)}（{d.best_buyback_shop}） |",
                    f"| 粗利 | {fmt_profit(d.gross_profit_jpy)} |",
                    f"| 推定コスト | {fmt_price(d.estimated_costs_jpy)}（送料+手数料等） |",
                    f"| **実質利益** | **{fmt_profit(d.net_profit_jpy)}** |",
                    f"| 利益率 | {fmt_rate(d.net_profit_rate)} |",
                    f"| 買取条件 | {d.buyback_condition or '新品未開封'} |",
                    f"| 販売方式 | {d.sale_method} |",
                    f"| 難易度 | {d.difficulty_score:.2f} |",
                    f"",
                ])
                if d.official_url:
                    lines.append(f"公式購入ページ: {d.official_url}")
                if d.best_buyback_url:
                    lines.append(f"買取ページ: {d.best_buyback_url}")
                lines.append("")

        lines.extend([
            "## 注意点",
            "",
            "- 在庫状況は変動します。公式ページで最新の在庫を確認してください。",
            "- 買取価格も日々変動します。買取店の公式ページで最新価格を確認してください。",
            "- 買取条件（新品未開封・SIMフリー等）を必ず確認してください。条件を満たさない場合、買取価格が下がります。",
            "- 送料・振込手数料・移動コスト等を差し引いた実質利益を確認してから判断してください。",
            "",
            "## 買取条件の確認方法",
            "",
            "1. 買取店の公式ページで「買取価格表」を検索",
            "2. 商品名・型番・容量・色で検索",
            "3. 「新品未開封」「SIMフリー」等の条件を確認",
            "4. 減額条件（開封済・傷あり等）を確認",
            "5. 買取方法（宅配・店頭）と送料を確認",
            "",
            "## 次に見るべき商品",
            "",
            "- 新型iPhoneの発売直後は買取プレミアムが付きやすい傾向があります",
            "- ゲーム機の新型発売時も同様の傾向が確認されています",
            "- Apple製品は公式ストアでの購入が最も条件が明確です",
            "",
        ])

        lines.append(DISCLAIMER_FULL)
        return "\n".join(lines)

    # ===== advanced =====

    def _generate_advanced(self) -> str:
        # market_snapshotsからadvanced候補を取得
        snaps = self.repo.list_premium_candidates_with_snapshots(limit=15, user_level="advanced")
        now = datetime.now()
        date_display = now.strftime("%Y年%m月%d日")

        lines = [
            f"# 【上級者向け】高利益プレ値候補と海外価格差まとめ",
            f"",
            f"*{date_display} 更新*",
            f"",
            f"## 今週の高利益候補",
            f"",
        ]

        if not snaps:
            lines.append("現在、条件を満たす上級者向け候補はありません。")
        else:
            for i, s in enumerate(snaps, 1):
                prem = fmt_profit(s.premium_gap_jpy) if s.premium_gap_jpy else "---"
                method_label = {
                    "lottery": "抽選販売", "soldout": "SOLD OUT",
                    "discontinued": "販売終了", "normal": "通常販売",
                }.get(s.sale_method, s.sale_method)

                lines.extend([
                    f"### {i}. {s.product_name}",
                    f"",
                    f"| 項目 | 内容 |",
                    f"|------|------|",
                    f"| 公式定価 | {fmt_price(s.official_price_jpy)} |",
                    f"| 国内中古 | {fmt_price(s.domestic_used_price_jpy)} |",
                    f"| 海外(JPY) | {fmt_price(s.overseas_price_jpy)} |",
                    f"| プレ値差 | {prem} |",
                    f"| 販売方式 | {method_label} |",
                    f"| 難易度 | {s.difficulty_score:.2f} |",
                    f"| 総合スコア | {s.overall_score:.2f} |",
                    f"",
                ])

        lines.extend([
            "## 入手難易度について",
            "",
            "上記の商品は入手難易度が高く、以下のいずれかに該当します。",
            "- 抽選販売（当選が必要）",
            "- SOLD OUT（再販待ち）",
            "- 限定モデル（生産数が少ない）",
            "- 海外価格差が大きい（国内正規ルートでの入手が有利）",
            "",
            "## 注意点",
            "",
            "- 入手難易度が高いため、確実に購入できる保証はありません。",
            "- 二次流通価格は需給バランスで大きく変動します。",
            "- 抽選販売は複数回の応募が必要な場合があります。",
            "- 海外価格差は為替変動の影響を受けます。",
            "",
        ])

        lines.append(DISCLAIMER_FULL)
        return "\n".join(lines)

    # ===== weekly =====

    def _generate_weekly(self) -> str:
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        date_display = now.strftime("%Y年%m月%d日")

        beginner_deals = self.repo.list_beginner_deals(user_level="beginner", min_profit=3000, limit=10)
        advanced_snaps = self.repo.list_premium_candidates_with_snapshots(limit=10, user_level="advanced")
        alerts = self.repo.list_alerts(limit=20)
        recent_alerts = [a for a in alerts if a.created_at >= week_ago]

        lines = [
            f"# 週間プレ値監視レポート",
            f"",
            f"*{date_display} 発行*",
            f"",
            f"## 今週のサマリ",
            f"",
            f"| 項目 | 件数 |",
            f"|------|------|",
            f"| 初心者向け案件 | {len(beginner_deals)} 件 |",
            f"| 上級者向け候補 | {len(advanced_snaps)} 件 |",
            f"| 今週のアラート | {len(recent_alerts)} 件 |",
            f"",
            f"## 初心者向け案件",
            f"",
        ]

        if beginner_deals:
            lines.extend(["| 商品 | 公式 | 買取 | 実質利益 | 買取店 |", "|------|------|------|----------|--------|"])
            for d in beginner_deals:
                lines.append(
                    f"| {d.product_name} | {fmt_price(d.official_price_jpy)} | "
                    f"{fmt_price(d.best_buyback_price)} | {fmt_profit(d.net_profit_jpy)} | "
                    f"{d.best_buyback_shop} |"
                )
            lines.append("")
        else:
            lines.extend(["条件を満たす初心者向け案件はありませんでした。", ""])

        lines.extend([f"## 上級者向け候補", ""])

        if advanced_snaps:
            lines.extend(["| 商品 | 定価 | 中古 | プレ値差 | 方式 |", "|------|------|------|----------|------|"])
            for s in advanced_snaps:
                lines.append(
                    f"| {s.product_name} | {fmt_price(s.official_price_jpy)} | "
                    f"{fmt_price(s.domestic_used_price_jpy)} | {fmt_profit(s.premium_gap_jpy)} | "
                    f"{s.sale_method} |"
                )
            lines.append("")
        else:
            lines.extend(["条件を満たす上級者向け候補はありませんでした。", ""])

        lines.append(DISCLAIMER_FULL)
        return "\n".join(lines)
