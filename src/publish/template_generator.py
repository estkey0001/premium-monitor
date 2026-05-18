"""速報テンプレート生成。

alerts / observations / products からチャネル別投稿文を生成する。
自動投稿はせず、draft として publish_queue に保存する。

文章ルール:
- 禁止: 「絶対儲かる」「確実に利益」「今すぐ買え」等の煽り
- 推奨: 「価格差が確認されています」「監視対象です」「購入判断は各自で」
"""

import logging
from datetime import datetime
from typing import Optional

import ulid

from src.db.repository import Repository
from src.models.alert import AlertModel
from src.models.product import ProductModel
from src.models.publish_item import PublishItemModel

logger = logging.getLogger(__name__)

# チャネル別文字数上限
CHAR_LIMITS = {"x": 280, "threads": 500, "line": 700, "discord": 2000, "note": 5000}

# ジャンル別ハッシュタグ
GENRE_TAGS = {
    "camera": "#カメラ #デジカメ",
    "iphone": "#iPhone #Apple",
    "game_console": "#ゲーム機",
    "pc": "#PC #パソコン",
}

# ブランド別ハッシュタグ
BRAND_TAGS = {
    "RICOH": "#RICOH #リコー #RICOHGR",
    "FUJIFILM": "#FUJIFILM #富士フイルム",
    "Canon": "#Canon #キヤノン",
    "Nikon": "#Nikon #ニコン",
    "Sony": "#Sony #ソニー",
    "Apple": "#Apple",
    "Nintendo": "#Nintendo #任天堂",
}

# 情報源表示名
SOURCE_NAMES = {
    "src_kakaku": "価格.com", "src_yodobashi": "ヨドバシカメラ",
    "src_map_camera": "マップカメラ", "src_ricoh_imaging": "RICOH公式",
    "src_fujifilm_official": "FUJIFILM公式", "src_apple_jp": "Apple公式",
}


class TemplateGenerator:
    """チャネル別投稿テンプレートを生成する。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def generate_from_alerts(self, channels: list[str] | None = None) -> list[PublishItemModel]:
        """未投稿のS/Aアラートから投稿テンプレートを生成する。"""
        channels = channels or ["x", "threads", "line", "discord"]
        alerts = self.repo.list_alerts(limit=50)

        # 既にpublish_queueにある alert_id を除外
        existing = set()
        for item in self.repo.list_publish_queue(limit=200):
            if item.source_id:
                existing.add(item.source_id)

        items = []
        for alert in alerts:
            if alert.alert_rank not in ("S", "A"):
                continue
            if alert.id in existing:
                continue

            product = self.repo.get_product(alert.product_id)
            if not product:
                continue

            for ch in channels:
                item = self._build_alert_post(alert, product, ch)
                items.append(item)

        return items

    def generate_from_candidates(self, channels: list[str] | None = None) -> list[PublishItemModel]:
        """新製品候補からテンプレートを生成する。"""
        channels = channels or ["x", "discord"]
        candidates = self.repo.list_product_candidates(status="pending")

        items = []
        for c in candidates:
            for ch in channels:
                item = self._build_candidate_post(c, ch)
                items.append(item)

        return items

    def generate_from_market_snapshots(self, channels: list[str] | None = None) -> list[PublishItemModel]:
        """market_snapshotsから初心者向け/上級者向けテンプレートを生成する。"""
        channels = channels or ["x", "threads", "line", "discord"]
        from src.models.market_snapshot import MarketSnapshotModel

        # 既にpublish_queueにあるproduct_nameを除外
        existing_titles = set()
        for item in self.repo.list_publish_queue(limit=200):
            existing_titles.add(item.title)

        items = []

        # 初心者向け
        beginner_snaps = self.repo.list_premium_candidates_with_snapshots(
            limit=20, user_level="beginner"
        )
        for snap in beginner_snaps:
            for ch in channels:
                title = f"【初心者向け】{snap.product_name}"
                if title in existing_titles:
                    continue
                item = self._build_beginner_post(snap, ch)
                items.append(item)
                existing_titles.add(title)

        # 上級者向け
        advanced_snaps = self.repo.list_premium_candidates_with_snapshots(
            limit=20, user_level="advanced"
        )
        for snap in advanced_snaps:
            for ch in channels:
                title = f"【上級者向け】{snap.product_name}"
                if title in existing_titles:
                    continue
                item = self._build_advanced_post(snap, ch)
                items.append(item)
                existing_titles.add(title)

        return items

    # ===== ビルダー =====

    def _build_alert_post(self, alert: AlertModel, product: ProductModel, channel: str) -> PublishItemModel:
        rank_label = {"S": "S級プレ値速報", "A": "A級注目速報"}.get(alert.alert_rank, "速報")
        rank_emoji = {"S": "🔴", "A": "🟠"}.get(alert.alert_rank, "📢")

        # 情報源を抽出
        source_name = ""
        url = ""
        for line in (alert.body or "").split("\n"):
            if line.startswith("情報源:"):
                source_name = line.split(":", 1)[1].strip()
            if line.startswith("URL:"):
                url = line.split(":", 1)[1].strip()

        retail = product.official_price or product.retail_price or 0
        profit_str = f"+¥{alert.estimated_profit:,}" if alert.estimated_profit and alert.estimated_profit > 0 else ""

        # チャネル別本文生成
        if channel == "x":
            body = self._build_x_post(rank_emoji, rank_label, product, alert, retail, profit_str, source_name)
        elif channel == "threads":
            body = self._build_threads_post(rank_emoji, rank_label, product, alert, retail, profit_str, source_name)
        elif channel == "line":
            body = self._build_line_post(rank_emoji, rank_label, product, alert, retail, profit_str, source_name, url)
        elif channel == "discord":
            body = self._build_discord_post(rank_emoji, rank_label, product, alert, retail, profit_str, source_name, url)
        else:
            body = f"{rank_emoji}【{rank_label}】{product.name}"

        tags = self._build_hashtags(product)

        return PublishItemModel(
            id=str(ulid.new()),
            source_type="alert",
            source_id=alert.id,
            channel=channel,
            title=f"【{rank_label}】{product.name}",
            body=body,
            hashtags=tags,
            rank=alert.alert_rank,
        )

    def _build_x_post(self, emoji, label, product, alert, retail, profit, source):
        """X/Twitter用（280文字以内）。"""
        lines = [f"{emoji}【{label}】", f"{product.name}"]
        if retail:
            lines.append(f"公式定価：¥{retail:,}")
        if alert.estimated_profit and alert.estimated_profit > 0:
            lines.append(f"想定利益：{profit}")
        if source:
            lines.append(f"情報源：{source}")
        lines.append("在庫状況は変動します。購入判断は各自でご確認ください。")
        tags = self._build_hashtags(product)
        text = "\n".join(lines) + "\n" + tags
        # 280文字制限
        if len(text) > 280:
            text = text[:277] + "..."
        return text

    def _build_threads_post(self, emoji, label, product, alert, retail, profit, source):
        """Threads用（500文字以内）。"""
        lines = [f"{emoji}【{label}】", "", f"商品：{product.name}"]
        if retail:
            lines.append(f"公式定価：¥{retail:,}")
        if alert.estimated_profit and alert.estimated_profit > 0:
            lines.append(f"想定利益：{profit}")
        stock = "抽選販売" if product.is_lottery else ("在庫なし" if product.official_stock_status == "SOLD OUT" else "監視中")
        lines.append(f"在庫状況：{stock}")
        if source:
            lines.append(f"情報源：{source}")
        lines.extend(["", "価格差が確認されています。在庫状況は変動しますので、最新情報をご確認ください。"])
        return "\n".join(lines)

    def _build_line_post(self, emoji, label, product, alert, retail, profit, source, url):
        """LINE配信用（700文字、改行多め）。"""
        lines = [f"{emoji}【{label}】", "", f"商品：{product.name}", ""]
        if retail:
            lines.append(f"公式定価：¥{retail:,}")
        if alert.estimated_profit and alert.estimated_profit > 0:
            lines.extend([f"想定利益：{profit}", ""])
        stock = "抽選販売中" if product.is_lottery else ("SOLD OUT" if product.official_stock_status == "SOLD OUT" else "確認中")
        lines.extend([f"在庫状況：{stock}", ""])
        if source:
            lines.append(f"情報源：{source}")
        if url:
            lines.extend(["", f"詳細：{url}"])
        lines.extend(["", "---", "在庫状況は変動します。", "購入判断は各自でご確認ください。"])
        return "\n".join(lines)

    def _build_discord_post(self, emoji, label, product, alert, retail, profit, source, url):
        """Discord用（詳細長め）。"""
        lines = [
            f"{emoji} **【{label}】{product.name}**", "",
            f"ジャンル：{product.genre}", f"ブランド：{product.brand}",
        ]
        if retail:
            lines.append(f"公式定価：¥{retail:,}")
        if alert.estimated_profit and alert.estimated_profit > 0:
            lines.append(f"想定利益：{profit}")
        if alert.confidence:
            lines.append(f"信頼度：{alert.confidence:.0%}")
        stock = "抽選販売中" if product.is_lottery else ("SOLD OUT" if product.official_stock_status == "SOLD OUT" else "確認中")
        lines.extend(["", f"在庫状況：{stock}"])
        if source:
            lines.append(f"情報源：{source}")
        if url:
            lines.append(f"URL：{url}")
        lines.extend(["", "※ 在庫状況は変動します。購入判断は各自でご確認ください。"])
        return "\n".join(lines)

    def _build_candidate_post(self, candidate, channel: str) -> PublishItemModel:
        body = f"🆕【新製品候補】{candidate.product_name}\n"
        body += f"ブランド：{candidate.brand}\n"
        body += f"検出キーワード：{candidate.detected_keyword}\n"
        if candidate.estimated_price:
            body += f"推定価格：¥{candidate.estimated_price:,}\n"
        body += "\n速報性のある情報です。正式発表を確認してください。"

        return PublishItemModel(
            id=str(ulid.new()),
            source_type="product_candidate",
            source_id=candidate.id,
            channel=channel,
            title=f"【新製品候補】{candidate.product_name}",
            body=body,
            hashtags=f"#新製品 #{candidate.brand}" if candidate.brand else "#新製品",
            rank="",
        )

    # ===== Phase 7B-2 / 9A: 初心者/上級者テンプレート =====

    def generate_from_beginner_deals(self) -> list[PublishItemModel]:
        """beginner_dealsから投稿テンプレートを生成する (Phase 9A)。"""
        from src.notifiers.routing import get_template_channels_for_level
        deals = self.repo.list_beginner_deals(user_level="beginner", min_profit=3000, limit=20)

        existing_titles = set()
        for item in self.repo.list_publish_queue(limit=200):
            existing_titles.add(item.title)

        items = []
        for deal in deals:
            channels = get_template_channels_for_level(deal.user_level)
            for ch in channels:
                title = f"【初心者向け】{deal.product_name}"
                if title in existing_titles:
                    continue
                item = self._build_beginner_deal_post(deal, ch)
                items.append(item)
                existing_titles.add(title)
        return items

    def _build_beginner_deal_post(self, deal, channel: str) -> PublishItemModel:
        """BeginnerDealModelから投稿テンプレートを生成する（Phase 9A強化版）。"""
        lines = ["🟢【初心者向け・低難度プレ値候補】", "", f"{deal.product_name}"]

        if deal.official_price_jpy:
            lines.append(f"公式価格：¥{deal.official_price_jpy:,}")
        if deal.best_buyback_price:
            lines.append(f"買取価格：¥{deal.best_buyback_price:,}（{deal.best_buyback_shop}）")
        if deal.net_profit_jpy > 0:
            lines.append(f"実質利益：+¥{deal.net_profit_jpy:,}（コスト¥{deal.estimated_costs_jpy:,}差引後）")
        if deal.net_profit_rate > 0:
            lines.append(f"利益率：{deal.net_profit_rate:.1%}")

        lines.append("")
        if deal.buyback_condition:
            lines.append(f"買取条件：{deal.buyback_condition}")
        if deal.official_url:
            lines.append(f"公式購入：{deal.official_url}")
        if deal.best_buyback_url:
            lines.append(f"買取店：{deal.best_buyback_url}")

        lines.append("")
        if deal.sale_method == "normal":
            lines.append("公式で通常購入できる状態で、買取価格が定価を上回っています。")
        lines.append("条件が分かりやすく、初心者でも確認しやすい案件です。")

        lines.extend([
            "",
            "--- 注意 ---",
            "・在庫状況は変動します。購入前に必ず最新の公式価格をご確認ください。",
            "・買取価格も変動します。買取条件（未開封・SIMフリー等）を必ず確認してください。",
            "・購入判断は各自の責任でお願いします。",
        ])

        body = "\n".join(lines)
        limit = CHAR_LIMITS.get(channel, 2000)
        if len(body) > limit:
            body = body[:limit - 3] + "..."

        tags = f"#プレ値 #初心者向け #{deal.brand}" if deal.brand else "#プレ値 #初心者向け"
        genre_tag = GENRE_TAGS.get(deal.category, "")
        if genre_tag:
            tags += f" {genre_tag}"

        return PublishItemModel(
            id=str(ulid.new()),
            source_type="beginner_deal",
            source_id=deal.id,
            channel=channel,
            title=f"【初心者向け】{deal.product_name}",
            body=body,
            hashtags=tags,
            rank="B",
        )

    def _build_beginner_post(self, snap, channel: str) -> PublishItemModel:
        """初心者向け投稿テンプレートを生成する（snapshot版、後方互換）。"""
        official = snap.official_price_jpy or 0
        buyback = snap.domestic_buyback_price_jpy or 0
        profit = buyback - official if buyback > official else 0

        lines = ["🟢【初心者向け・低難度プレ値候補】", "", f"{snap.product_name}"]
        if official:
            lines.append(f"公式価格：¥{official:,}")
        if buyback:
            lines.append(f"買取価格：¥{buyback:,}")
        if profit > 0:
            lines.append(f"差額：+¥{profit:,}")

        lines.append("")
        if snap.sale_method == "normal":
            lines.append("公式で通常購入できる状態で、買取価格が定価を上回っています。")
        else:
            lines.append("買取価格が定価を上回っている状態です。")
        lines.append("条件が分かりやすく、初心者でも確認しやすい案件です。")
        lines.extend([
            "",
            "※在庫・買取価格は変動します。購入前に必ず公式価格と買取条件を確認してください。",
        ])

        body = "\n".join(lines)
        limit = CHAR_LIMITS.get(channel, 2000)
        if len(body) > limit:
            body = body[:limit - 3] + "..."

        tags = f"#プレ値 #初心者向け #{snap.brand}" if snap.brand else "#プレ値 #初心者向け"
        genre_tag = GENRE_TAGS.get(snap.category, "")
        if genre_tag:
            tags += f" {genre_tag}"

        return PublishItemModel(
            id=str(ulid.new()),
            source_type="market_snapshot",
            source_id=snap.id,
            channel=channel,
            title=f"【初心者向け】{snap.product_name}",
            body=body,
            hashtags=tags,
            rank="B",
        )

    def _build_advanced_post(self, snap, channel: str) -> PublishItemModel:
        """上級者向け投稿テンプレートを生成する。"""
        official = snap.official_price_jpy or 0
        used = snap.domestic_used_price_jpy or 0
        premium = snap.premium_gap_jpy

        lines = ["🟠【上級者向け・高利益プレ値候補】", "", f"{snap.product_name}"]
        if official:
            lines.append(f"公式価格：¥{official:,}")
        if used:
            lines.append(f"二次流通価格：¥{used:,}")
        if premium and premium > 0:
            lines.append(f"想定価格差：+¥{premium:,}")

        lines.append("")
        method_desc = {
            "lottery": "抽選販売が続いており、入手難易度は高めです。",
            "soldout": "SOLD OUTが続いており、入手難易度は高めです。",
            "discontinued": "販売終了品で、新品入手は非常に困難です。",
        }
        lines.append(method_desc.get(snap.sale_method, "入手難易度を確認してください。"))
        lines.append("ただし価格差が大きいため、上級者向けの監視候補です。")
        lines.extend(["", "※在庫状況は変動します。購入判断は各自でご確認ください。"])

        body = "\n".join(lines)

        limit = CHAR_LIMITS.get(channel, 2000)
        if len(body) > limit:
            body = body[:limit - 3] + "..."

        tags = f"#プレ値 #上級者向け #{snap.brand}" if snap.brand else "#プレ値 #上級者向け"
        genre_tag = GENRE_TAGS.get(snap.category, "")
        if genre_tag:
            tags += f" {genre_tag}"

        return PublishItemModel(
            id=str(ulid.new()),
            source_type="market_snapshot",
            source_id=snap.id,
            channel=channel,
            title=f"【上級者向け】{snap.product_name}",
            body=body,
            hashtags=tags,
            rank="A",
        )

    def _build_hashtags(self, product: ProductModel) -> str:
        tags = ["#プレ値", "#速報"]
        genre_tag = GENRE_TAGS.get(product.genre, "")
        if genre_tag:
            tags.append(genre_tag)
        brand_tag = BRAND_TAGS.get(product.brand, "")
        if brand_tag:
            tags.append(brand_tag)
        return " ".join(tags)
