#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公式価格 検証・sanity・confidence レイヤー。

「公式価格をDBへ保存する前に必ず検証する」ためのガード。利益判定/AI/Opportunity/
Notification/Capital/Execution ロジックは一切変更しない（このモジュールは取得側の品質管理）。

最重要ルール（save 前に全て満たすこと）:
  - 商品ページが HTTP 200
  - メーカー公式ドメイン
  - 商品名一致 / 型番一致
  - アクセサリーではない
  - 修理/下取/中古ページではない
  - 価格 > 0
  - 通貨 JPY
  - 本体販売価格である（月額/分割/下取/ポイント/中古ではない）

ページ内で最初に見つかった価格を無条件採用してはいけない。

confidence:
  high   = 公式ドメイン + exact product/model match + 本体価格 + canonical URL + price>0
  medium = 公式カテゴリページ + 商品名一致 + 個別URLなし
  low    = 検索結果ページ / 型番不明 / 複数商品の価格候補   （low は main 計算に使用禁止）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# メーカー公式ドメイン（source_id → 許可ドメイン群）。ここに無いドメインは official 扱いしない。
OFFICIAL_DOMAINS = {
    "src_apple_jp": ("apple.com",),
    "src_ricoh_imaging": ("ricohimagingstore.com", "ricoh-imaging.co.jp"),
    "src_fujifilm_official": ("fujifilm-x.com", "fujifilm.com"),
    "src_canon_official": ("canon.jp", "cweb.canon.jp", "store.canon.jp"),
    "src_nikon_direct": ("nikon-image.com", "nij.nikon.com", "shop.nikon-image.com", "nikon.com"),
    "src_sony_store": ("sony.jp", "store.sony.jp"),
}

# アクセサリー語（本体でない）
ACCESSORY_KW = (
    "ケース", "case", "カバー", "cover", "バッテリー", "battery", "充電器", "charger",
    "ストラップ", "strap", "フィルター", "filter", "アダプター", "adapter", "保護",
    "protector", "グリップ", "grip", "フード", "hood", "三脚", "tripod", "シール",
    "skin", "pouch", "ポーチ", "レンズフード", "予備", "スペア", "spare", "純正アクセサリ",
    "applecare", "apple care", "延長保証", "ケーブル", "cable", "スタンド", "stand",
)
# 修理/下取/中古ページ語
NON_SALE_KW = (
    "修理", "repair", "下取", "下取り", "trade in", "trade-in", "trade‑in",
    "中古", "used", "整備済", "refurb", "リユース", "買取", "買い取り",
    "リースバック", "レンタル", "rental", "サブスク", "subscription",
)
# 本体価格でない文脈語（月額/分割/ポイント）
NON_BODY_PRICE_KW = (
    "月々", "月額", "分割", "回払い", "実質", "ポイント", "還元", "／月", "/月",
    "円/月", "円／月", "1回分", "初回", "月々のお支払い",
)


@dataclass
class ValidationResult:
    accepted: bool
    confidence: str  # high / medium / low / rejected
    price: Optional[int]
    rejection_reason: Optional[str] = None
    reasons: list = field(default_factory=list)  # 判定の根拠ログ

    def as_dict(self) -> dict:
        return {
            "accepted": self.accepted, "confidence": self.confidence,
            "price": self.price, "rejection_reason": self.rejection_reason,
            "reasons": self.reasons,
        }


def _domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)/?", url or "")
    return (m.group(1).lower() if m else "").lstrip("www.")


def is_official_domain(source_id: str, url: str) -> bool:
    dom = _domain_of(url)
    allowed = OFFICIAL_DOMAINS.get(source_id, ())
    return any(dom == d or dom.endswith("." + d) or d in dom for d in allowed)


def detect_open_price(text: str) -> bool:
    """オープン価格（希望小売価格なし）を検出。カメラ各社に多い＝公式定価は存在しない。"""
    t = (text or "").replace("プライス", "価格")
    return ("オープン価格" in t) or ("open price" in t.lower())


def _tokens(s: str) -> list:
    s = (s or "").lower()
    s = re.sub(r"[　\s\-_/（）()、。・]", " ", s)
    return [t for t in s.split() if t]


def product_name_match(product_name: str, detected_name: str, keywords=None) -> bool:
    """商品名一致。商品名の主要トークン or keywords がページ側検出名に含まれるか。"""
    if not detected_name:
        return False
    dn = detected_name.lower()
    # 主要トークン（2文字以上）の過半が一致
    toks = [t for t in _tokens(product_name) if len(t) >= 2]
    if toks:
        hit = sum(1 for t in toks if t in dn)
        if hit >= max(1, (len(toks) + 1) // 2):
            return True
    for kw in (keywords or []):
        if kw and kw.lower() in dn:
            return True
    return False


def model_number_match(model_number: str, detected_text: str) -> Optional[bool]:
    """型番一致。

    True  = 型番がページ側に存在（一致確認）
    None  = 型番未設定、または型番がページに現れない（不確定＝内部SKU等。拒否しない）
    False = 同一ファミリーの『別の型番』が明確に存在（別商品ページの疑い）

    重要: 単に型番が見つからないだけでは False にしない（内部SKU S0001566 等は
    商品ページに載らないため。誤拒否で公式取得率を下げてしまう）。
    """
    if not model_number:
        return None
    mn = re.sub(r"[\s\-]", "", model_number.lower())
    dt = re.sub(r"[\s\-]", "", (detected_text or "").lower())
    if not mn:
        return None
    if mn in dt:
        return True
    # 同一プレフィックス（ILCE/ILME/EOS 等）の別型番がページにあれば mismatch。
    m = re.match(r"([a-z]{2,5})", mn)
    if m:
        prefix = m.group(1)
        # ページ内に同プレフィックス+英数字 のトークンがあるか
        others = re.findall(prefix + r"[0-9a-z]{2,}", dt)
        # 自分自身以外の同系型番が存在 → 別商品ページ
        if any(o != mn for o in others):
            return False
    return None  # 型番がページに無い（内部SKU等）→ 不確定（拒否しない）


def sanity_check_price(price: Optional[int], reference_price: Optional[int],
                       context_text: str = "") -> Optional[str]:
    """価格の異常検知。異常なら rejection_reason 文字列、正常なら None。

    異常例: 0/1円・本体相場の30%以下・月額/分割/ポイント/下取・中古文脈。
    reference_price（定価 or 市場相場）が無い場合は絶対閾値のみ適用。
    """
    if price is None or price <= 0:
        return "price_zero_or_none"
    if price <= 1:
        return "price_one_yen"
    ctx = context_text or ""
    if any(k in ctx for k in NON_BODY_PRICE_KW):
        return "non_body_price_context(月額/分割/ポイント)"
    if any(k in ctx for k in NON_SALE_KW):
        return "non_sale_context(下取/中古/修理)"
    # 相対チェック: 本体相場の30%以下は異常（アクセサリー/分割1回分の疑い）
    if reference_price and reference_price > 0:
        if price < reference_price * 0.3:
            return f"too_low_vs_market(<30%: {price} < {int(reference_price*0.3)})"
        if price > reference_price * 3.0:
            return f"too_high_vs_market(>300%: {price})"
    else:
        # 相場不明時の絶対下限（アクセサリー価格帯を弾く緩い下限）
        if price < 3000:
            return "too_low_absolute(<3000)"
    return None


def classify_confidence(*, official_domain: bool, http_200: bool, name_ok: bool,
                        model_ok: Optional[bool], is_body_price: bool,
                        canonical_url: bool, link_type: str,
                        multiple_candidates: bool) -> str:
    """confidence を high/medium/low に分類。"""
    if not (official_domain and http_200 and is_body_price):
        return "low"
    if link_type in ("search",) or multiple_candidates:
        return "low"
    # high: 公式ドメイン + exact(name & model) + 本体価格 + canonical + price>0
    if name_ok and (model_ok is True) and canonical_url and link_type == "item":
        return "high"
    # exact model 不明でも name 一致 + 個別item URL + canonical なら high 相当（型番未設定製品）
    if name_ok and (model_ok is None) and canonical_url and link_type == "item":
        return "high"
    # category ページ / 個別URLなし → medium
    if name_ok and link_type == "category":
        return "medium"
    if name_ok:
        return "medium"
    return "low"


def validate_official_price(
    *,
    source_id: str,
    url: str,
    http_status: int,
    canonical_url: Optional[str],
    product_name: str,
    model_number: str,
    keywords: Optional[list],
    detected_name: str,
    detected_text: str,
    price: Optional[int],
    currency: str,
    reference_price: Optional[int] = None,
    link_type: str = "item",
    multiple_candidates: bool = False,
    page_text: str = "",
) -> ValidationResult:
    """公式価格を保存前に総合検証する。最重要ルールを全てチェック。"""
    reasons = []

    # 1. HTTP 200
    if http_status != 200:
        return ValidationResult(False, "rejected", None, f"http_{http_status}", reasons)
    reasons.append("http_200")

    # 1.5 オープン価格（公式定価なし）→ 拒否（¥0保存防止・エラーではない正常分類）
    if detect_open_price(page_text) and (price is None or price <= 0):
        return ValidationResult(False, "rejected", None, "open_price_no_msrp", reasons)

    # 2. 公式ドメイン
    official_domain = is_official_domain(source_id, url)
    if not official_domain:
        return ValidationResult(False, "rejected", None, "not_official_domain", reasons)
    reasons.append("official_domain")

    # 3. 修理/下取/中古ページでない（URL/検出名/本文で判定）
    hay = " ".join([url or "", detected_name or "", detected_text or ""]).lower()
    if any(k.lower() in hay for k in NON_SALE_KW):
        return ValidationResult(False, "rejected", None, "repair_tradein_used_page", reasons)

    # 4. アクセサリーでない
    if any(k.lower() in (detected_name or "").lower() for k in ACCESSORY_KW):
        return ValidationResult(False, "rejected", None, "accessory_not_body", reasons)

    # 5. 商品名一致
    name_ok = product_name_match(product_name, detected_name, keywords)
    if not name_ok:
        # 名前不一致は保存しない（誤登録防止）
        return ValidationResult(False, "rejected", None, "product_name_mismatch", reasons)
    reasons.append("name_match")

    # 6. 型番一致（型番があり不一致なら拒否・未設定は許容）
    model_ok = model_number_match(model_number, detected_text or detected_name)
    if model_ok is False:
        return ValidationResult(False, "rejected", None, "model_number_mismatch", reasons)
    if model_ok is True:
        reasons.append("model_match")

    # 7. 通貨 JPY
    if currency and currency.upper() not in ("JPY", "YEN", "¥", "円"):
        return ValidationResult(False, "rejected", None, f"currency_not_jpy({currency})", reasons)

    # 8. 価格 sanity（>0・本体価格・月額/分割/ポイント/下取でない・相場30%以上）
    sc = sanity_check_price(price, reference_price, detected_text)
    if sc:
        return ValidationResult(False, "rejected", None, sc, reasons)
    reasons.append("price_sane")

    # 本体価格判定（sanity を通過し非本体文脈が無い＝本体価格とみなす）
    is_body_price = True

    # 9. confidence 分類
    conf = classify_confidence(
        official_domain=official_domain, http_200=(http_status == 200),
        name_ok=name_ok, model_ok=model_ok, is_body_price=is_body_price,
        canonical_url=bool(canonical_url), link_type=link_type,
        multiple_candidates=multiple_candidates,
    )
    return ValidationResult(True, conf, price, None, reasons)
