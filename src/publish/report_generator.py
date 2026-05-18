"""週間レポート生成。

過去7日間のalerts / observations / product_candidatesから
note用の下書きを生成する。
"""

import logging
from datetime import datetime, timedelta

import ulid

from src.db.repository import Repository
from src.models.publish_item import PublishItemModel

logger = logging.getLogger(__name__)


class ReportGenerator:
    """週間レポートを生成する。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def generate_weekly_report(self) -> PublishItemModel:
        """過去7日間の週間レポートを生成する。"""
        since = (datetime.now() - timedelta(days=7)).isoformat()

        # データ収集
        s_alerts = self.repo.db.connection.execute(
            "SELECT * FROM alerts WHERE alert_rank='S' AND created_at>=? ORDER BY estimated_profit DESC",
            (since,),
        ).fetchall()

        a_alerts = self.repo.db.connection.execute(
            "SELECT * FROM alerts WHERE alert_rank='A' AND created_at>=? ORDER BY estimated_profit DESC",
            (since,),
        ).fetchall()

        all_alerts = self.repo.db.connection.execute(
            "SELECT a.*, p.name as product_name, p.retail_price, p.official_price "
            "FROM alerts a JOIN products p ON p.id=a.product_id "
            "WHERE a.created_at>=? ORDER BY a.estimated_profit DESC",
            (since,),
        ).fetchall()

        soldout_obs = self.repo.db.connection.execute(
            "SELECT o.*, p.name as product_name FROM observations o "
            "JOIN products p ON p.id=o.product_id "
            "WHERE o.is_in_stock=0 AND o.observed_at>=? "
            "GROUP BY o.product_id ORDER BY o.observed_at DESC",
            (since,),
        ).fetchall()

        try:
            candidates = self.repo.db.connection.execute(
                "SELECT * FROM product_candidates WHERE detected_at>=? ORDER BY detected_at DESC",
                (since,),
            ).fetchall()
        except Exception:
            candidates = []

        # レポート本文生成
        today = datetime.now().strftime("%Y年%m月%d日")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%m/%d")
        today_short = datetime.now().strftime("%m/%d")

        lines = [
            f"# 今週のプレ値マーケットレポート",
            f"期間: {week_ago} 〜 {today_short}",
            f"生成日: {today}",
            "",
            "---",
            "",
        ]

        # 1. S級速報
        lines.append("## 1. 今週のS級速報")
        lines.append("")
        if s_alerts:
            for a in s_alerts[:10]:
                d = dict(a)
                profit = f"+¥{d['estimated_profit']:,}" if d.get("estimated_profit") and d["estimated_profit"] > 0 else "---"
                lines.append(f"- **{d['title']}** (利益: {profit}, 信頼度: {d.get('confidence', 0):.0%})")
            lines.append("")
        else:
            lines.extend(["今週はS級速報はありませんでした。", ""])

        # 2. 価格差が大きかった商品
        lines.append("## 2. 価格差が大きかった商品")
        lines.append("")
        profit_alerts = [dict(a) for a in all_alerts if dict(a).get("estimated_profit") and dict(a)["estimated_profit"] > 0]
        if profit_alerts:
            for a in profit_alerts[:10]:
                retail = a.get("official_price") or a.get("retail_price") or 0
                retail_str = f"¥{retail:,}" if retail else "不明"
                lines.append(f"- {a['product_name']}: 定価{retail_str} / 利益+¥{a['estimated_profit']:,}")
            lines.append("")
        else:
            lines.extend(["今週は顕著な価格差は確認されませんでした。", ""])

        # 3. SOLD OUT・抽選販売
        lines.append("## 3. SOLD OUT・抽選販売が目立った商品")
        lines.append("")
        if soldout_obs:
            seen = set()
            for o in soldout_obs:
                d = dict(o)
                name = d.get("product_name", d.get("product_id", ""))
                if name not in seen:
                    seen.add(name)
                    lines.append(f"- {name}")
            lines.append("")
        else:
            lines.extend(["今週は特筆すべきSOLD OUT情報はありませんでした。", ""])

        lottery_products = self.repo.db.connection.execute(
            "SELECT name FROM products WHERE is_lottery=1"
        ).fetchall()
        if lottery_products:
            lines.append("**抽選販売中の商品:**")
            for p in lottery_products:
                lines.append(f"- {p['name']}")
            lines.append("")

        # 4. 新製品候補
        lines.append("## 4. 新製品・後継機候補")
        lines.append("")
        if candidates:
            for c in candidates[:10]:
                d = dict(c)
                lines.append(f"- {d['product_name']} ({d.get('brand', '')}): {d.get('detected_keyword', '')}")
            lines.append("")
        else:
            lines.extend(["今週は新製品候補の検出はありませんでした。", ""])

        # 5. 来週の監視候補
        lines.append("## 5. 来週の監視候補")
        lines.append("")
        lines.append("- 抽選販売中の商品の次回エントリー開始に注目")
        lines.append("- SOLD OUT商品の在庫復活を監視")
        if profit_alerts:
            top = profit_alerts[0]
            lines.append(f"- {top['product_name']} の二次流通価格推移に注目")
        lines.append("")

        # 6. 注意点
        lines.append("## 6. 注意点")
        lines.append("")
        lines.append("- 在庫状況は常に変動します。最新情報を必ず確認してください。")
        lines.append("- 二次流通価格は取得時点の参考値です。実際の取引価格と異なる場合があります。")
        lines.append("- 購入・転売の判断は各自の責任で行ってください。")
        lines.append("- 本レポートは情報提供を目的としており、投資助言ではありません。")
        lines.append("")
        lines.append("---")
        lines.append(f"*自動生成: プレ値商品監視システム ({today})*")

        body = "\n".join(lines)

        return PublishItemModel(
            id=str(ulid.new()),
            source_type="weekly_report",
            source_id="",
            channel="note",
            title=f"今週のプレ値マーケットレポート ({week_ago}〜{today_short})",
            body=body,
            hashtags="#プレ値 #マーケットレポート #カメラ #速報",
            rank="",
        )
