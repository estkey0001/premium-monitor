"""データ正規化モジュール。

Collectorが取得した生データを統一フォーマットに変換する。
価格パース・在庫判定・テキスト正規化などの共通処理を提供。
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Normalizer:
    """取得データの正規化処理を提供する。"""

    # =========================================
    # 価格パース
    # =========================================

    @staticmethod
    def parse_price(text: str) -> Optional[int]:
        """価格文字列を整数（円）に変換する。

        対応フォーマット:
            ¥189,800 / 189,800円 / ￥189800 / 189,800（税込）
            189800 / 税込 189,800円 / 1,234円(税込)

        Args:
            text: 価格を含む文字列

        Returns:
            円単位の整数。パース失敗時はNone。
        """
        if not text:
            return None

        text = text.strip()

        # 「〜」「～」「~」で始まる範囲表記は最初の値を取る
        text = re.split(r"[〜～~]", text)[0]

        # 数字とカンマだけ残す
        cleaned = re.sub(r"[^\d,]", "", text)
        cleaned = cleaned.replace(",", "")

        if not cleaned:
            return None

        try:
            price = int(cleaned)
            # 明らかに異常な値を排除（100円未満、1億以上）
            if price < 100 or price >= 100_000_000:
                logger.warning("Price out of range: %d (from '%s')", price, text)
                return None
            return price
        except ValueError:
            return None

    @staticmethod
    def parse_price_multiple(text: str) -> list[int]:
        """テキスト中の全ての価格を抽出する。

        例: "新品 ¥139,700 中古 ¥118,000" → [139700, 118000]
        """
        prices = []
        # ¥ or ￥ に続く数字、またはXXX,XXX円パターン
        patterns = [
            r"[¥￥]\s*([\d,]+)",
            r"([\d,]+)\s*円",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                raw = match.group(1).replace(",", "")
                try:
                    val = int(raw)
                    if 100 <= val < 100_000_000:
                        prices.append(val)
                except ValueError:
                    continue
        return prices

    # =========================================
    # 在庫判定
    # =========================================

    @staticmethod
    def normalize_stock(text: str) -> Optional[bool]:
        """在庫文字列をbool値に正規化する。

        Returns:
            True: 在庫あり / False: 在庫なし / None: 判定不能
        """
        if not text:
            return None

        text = text.strip()

        # 在庫あり判定（優先度順）
        in_stock_patterns = [
            r"在庫あり", r"在庫有り", r"在庫　あり",
            r"○", r"◎", r"残りわずか", r"残り\d+",
            r"カートに入れる", r"カートに追加", r"購入する", r"買い物かご",
            r"予約受付中", r"予約する",
            r"入荷済", r"即納",
            r"In\s*Stock", r"Add\s*to\s*Cart", r"Buy\s*Now",
        ]

        # 在庫なし判定
        out_of_stock_patterns = [
            r"在庫なし", r"在庫切れ", r"在庫　なし",
            r"×", r"品切れ", r"売り切れ", r"売切れ",
            r"入荷待ち", r"入荷未定", r"お取り寄せ",
            r"完売", r"販売終了", r"販売休止",
            r"予定数.*終了", r"受付.*終了",
            r"Out\s*of\s*Stock", r"Sold\s*Out", r"Unavailable",
        ]

        for pattern in out_of_stock_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False

        for pattern in in_stock_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True

        return None

    @staticmethod
    def extract_stock_detail(text: str) -> str:
        """在庫ステータスの詳細テキストを正規化して返す。

        例: "  在庫あり（残り3点）  " → "在庫あり（残り3点）"
        """
        if not text:
            return ""
        # 余分な空白・改行を除去
        return re.sub(r"\s+", " ", text).strip()

    # =========================================
    # ポイント還元パース
    # =========================================

    @staticmethod
    def parse_points(text: str) -> Optional[dict]:
        """ポイント還元情報をパースする。

        例: "13,200ポイント（10%還元）" → {"points": 13200, "rate": 10}
        """
        if not text:
            return None

        points = None
        rate = None

        # ポイント数
        m = re.search(r"([\d,]+)\s*ポイント", text)
        if m:
            points = int(m.group(1).replace(",", ""))

        # 還元率
        m = re.search(r"(\d+)\s*%\s*還元", text)
        if m:
            rate = int(m.group(1))

        if points is None and rate is None:
            return None

        return {"points": points, "rate": rate}

    # =========================================
    # テキスト正規化
    # =========================================

    @staticmethod
    def clean_text(text: str) -> str:
        """HTMLから抽出したテキストをクリーンアップする。"""
        if not text:
            return ""
        # HTMLエンティティ・余分な空白を正規化
        text = re.sub(r"\s+", " ", text)
        text = text.strip()
        return text

    @staticmethod
    def extract_json_ld(html: str) -> list[dict]:
        """HTMLからJSON-LD構造化データを全て抽出する。"""
        results = []
        pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        for match in re.finditer(pattern, html, re.DOTALL | re.IGNORECASE):
            try:
                data = json.loads(match.group(1))
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except (json.JSONDecodeError, TypeError):
                continue
        return results

    @staticmethod
    def extract_meta_content(html: str, property_name: str) -> Optional[str]:
        """HTMLからmeta tagのcontentを抽出する。

        Args:
            html: HTML文字列
            property_name: og:title, product:price:amount 等
        """
        # property= または name= の両方に対応
        patterns = [
            rf'<meta[^>]*(?:property|name)=["\']{ re.escape(property_name) }["\'][^>]*content=["\']([^"\']*)["\']',
            rf'<meta[^>]*content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{ re.escape(property_name) }["\']',
        ]
        for pattern in patterns:
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                return m.group(1)
        return None
