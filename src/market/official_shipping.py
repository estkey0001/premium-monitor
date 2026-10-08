"""公式ストアで定価で買うときの購入送料（根拠つき・1か所）。

送料は推測しない。公式の一次情報（ご利用ガイド・購入ページ）で確認したものだけを、確認日と URL つきで持つ。
確認していない購入元は UNKNOWN（送料が分からない）。UNKNOWN の案件は利益の確定に使わない
（src/content/ui/opportunity.py の eligibility で costs_unknown。せどりルートの「費用不明は確定にしない」と同じ）。

分類:
- FREE_VERIFIED: 送料無料を一次情報で確認した
- PAID: 有料（金額を一次情報で確認した）
- CONDITIONAL: 条件つきで無料（条件と金額を一次情報で確認した。購入額から決まる）
- UNKNOWN: 確認していない

純利益の計算（beginner_deal_scanner._estimate_costs・daily_lp_generator の補完・初心者ルート一覧）と、
新UIの費用の内訳（opportunity.from_deal）は、どれも purchase_shipping() の金額を使う（金額を食い違わせない）。
"""

from __future__ import annotations

from urllib.parse import urlparse

FREE_VERIFIED = "FREE_VERIFIED"
PAID = "PAID"
CONDITIONAL = "CONDITIONAL"
UNKNOWN = "UNKNOWN"

STATUS_LABELS = {FREE_VERIFIED: "送料無料（公式で確認）", PAID: "送料（公式で確認）",
                 CONDITIONAL: "条件つき送料（公式で確認）", UNKNOWN: "送料未確認"}

# 購入元ごとの送料の決まり（公式の一次情報。checked_on は公式ページを取得して確認した日。実行日にしない）。
# 2026-10-05 の確認は Claude（WebFetch・curl・ブラウザで公式ページを取得）。人が再確認したら checked_by を更新する
SOURCE_RULES: dict[str, dict] = {
    # 「配送料について Apple Online Storeでのご注文は、配送料無料です。」
    "src_apple_jp": {"status": FREE_VERIFIED, "fee": 0,
                     "url": "https://www.apple.com/jp/shop/help/shipping_delivery", "checked_on": "2026-10-05",
                     "checked_by": "Claude"},
    # 「税込 5,500円以上 の場合： 送料無料 / 税込 5,499円以下 の場合： 550円」（発送をともなう商品）
    "src_nintendo_store": {"status": CONDITIONAL, "fee": 550, "free_from": 5500,
                           "url": "https://support-jp.nintendo.com/app/answers/detail/a_id/33907",
                           "checked_on": "2026-10-05", "checked_by": "Claude"},
    # 「送料：550円（税込）」「オンラインの購入ページで『送料無料』アイコンの表示がある商品は、送料無料です」
    # 商品ごとにアイコンの有無を購入ページで確認したものだけ使う（PRODUCT_SHIPPING）
    "src_sony_store": {"status": PAID, "fee": 550,
                       "url": "https://www.sony.jp/store/guide/shopping/delivery.html", "checked_on": "2026-10-05",
                       "checked_by": "Claude"},
}

# 購入ページを開いて、その商品の送料を確認したもの（金額・分類・根拠の URL・確認日）
PRODUCT_SHIPPING: dict[str, dict] = {
    # 2026-10-05: ソニーストアの購入ページ（137,980円(税込)・入荷待ち）に「送料無料」アイコンの表示なし
    # → ご利用ガイドの送料 550円（税込）。店舗での注文（無料）・配送業者指定料・離島の追加は含めない。
    # 入荷待ちの状態のページで見たもの。購入できる状態で「送料無料」アイコンが付いたら見直す
    "prod_ps5_pro": {"source": "src_sony_store", "fee": 550, "status": PAID,
                     "url": "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/",
                     "checked_on": "2026-10-05", "checked_by": "Claude"},
    # 2026-10-08（Phase 14）: My Nintendo Store の商品ページで 59,980円（税込）を確認。ストアの送料の決まり
    # （税込 5,500円以上は送料無料。SOURCE_RULES の src_nintendo_store・2026-10-05 確認）に当てはめて 0円。
    # 商品ごとに記録するのは、利益の判定（公式 URL を引けない経路がある）と商品詳細の表示で同じ値を使うため。
    # checked_on は定価（59,980円）を確認した日。送料の決まりそのものを確認したのは 2026-10-05（SOURCE_RULES）
    "prod_switch2": {"source": "src_nintendo_store", "fee": 0, "status": CONDITIONAL,
                     "url": "https://support-jp.nintendo.com/app/answers/detail/a_id/33907",
                     "checked_on": "2026-10-08", "checked_by": "Claude"},
    # ---- カメラのメーカー直販（Phase 16。2026-10-08 にブラウザで確認）----
    # ニコンダイレクトの「送料・配送について」: 1注文 5,000円（税込）以上は会員（ログイン時）だけ当社負担、
    # 非会員・ログインなしは 550円（税込）。会員になる前提を置かず、高いほう（550円）で計算する
    "prod_z8": {"source": "src_nikon_direct", "fee": 550, "status": PAID,
                "url": "https://nij.nikon.com/shop/u/guide/delivery_charge/", "checked_on": "2026-10-08",
                "checked_by": "Claude"},
    # キヤノンオンラインショップの購入ページ（EOS R5 Mark II・ボディー）に「送料無料」（税込 5,500円以上は送料無料）
    "prod_r5ii": {"source": "src_canon_official", "fee": 0, "status": FREE_VERIFIED,
                  "url": "https://store.canon.jp/online/g/g6536C001/", "checked_on": "2026-10-08", "checked_by": "Claude"},
    # フジフイルムモールの購入ページ（X100VI シルバー）に「送料： 無料」（5,000円（税込）以上は送料無料）
    "prod_x100vi": {"source": "src_fujifilm_official", "fee": 0, "status": FREE_VERIFIED,
                    "url": "https://mall-jp.fujifilm.com/shop/g/g16941878/", "checked_on": "2026-10-08",
                    "checked_by": "Claude"},
}

# 公式 URL の購入ページのホスト → 購入元（すべての注文で同じ決まりの購入元だけ）
_HOSTS = {"www.apple.com": ("src_apple_jp", "/jp/shop/"), "store-jp.nintendo.com": ("src_nintendo_store", "/")}


def purchase_shipping(product_id: str, official_url: str = "", price: float | None = None) -> dict:
    """公式で定価で買うときの購入送料。

    返り値: {"fee": int | None, "status": 分類, "source": 購入元, "url": 根拠, "checked_on": 確認日}
    fee が None のときは送料が分からない（0円とみなさない）。
    """
    unknown = {"fee": None, "status": UNKNOWN, "source": "", "url": "", "checked_on": ""}
    item = PRODUCT_SHIPPING.get(str(product_id or ""))
    if item:
        if not isinstance(item.get("fee"), int) or not item.get("checked_on") or not item.get("url"):
            return unknown          # 金額・確認日・根拠の URL がそろわない記録は使わない
        return {"fee": item["fee"], "status": item["status"], "source": item["source"],
                "url": item["url"], "checked_on": item["checked_on"]}
    try:
        u = urlparse(str(official_url or ""))
    except ValueError:
        return unknown
    hit = _HOSTS.get(u.netloc.lower()) if u.scheme == "https" else None
    if not hit or not u.path.startswith(hit[1]):
        return unknown
    rule = SOURCE_RULES[hit[0]]
    if rule["status"] == CONDITIONAL:
        if price is None or price <= 0:
            return unknown
        fee = 0 if price >= rule["free_from"] else rule["fee"]
    else:
        fee = rule["fee"]
    return {"fee": fee, "status": rule["status"], "source": hit[0], "url": rule["url"],
            "checked_on": rule["checked_on"]}


def known_fee(product_id: str, official_url: str = "", price: float | None = None) -> int:
    """純利益の計算に足す購入送料（分かっているときの金額。分からなければ 0 を足し、確定の判定で外す）。"""
    fee = purchase_shipping(product_id, official_url, price)["fee"]
    return int(fee) if fee is not None else 0
