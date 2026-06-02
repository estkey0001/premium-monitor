#!/usr/bin/env python3
"""カメラ新品/未使用買取価格 取得コレクター（Task 2 / 次フェーズ）。

対象カメラ × カメラ買取店から「新品・未使用・未開封」の買取価格を毎日取得する。
取得できた店舗は auto_scraped（condition=new_unopened）として buyback_prices に保存。
取得できない店舗は理由を記録し、manual_buyback_prices.csv の manual_today（手動確認）を
フォールバックとして温存する（このスクリプトは manual 行を削除しない）。

取得失敗理由（fetch_failed）:
  timeout / http_error / site_blocked / price_not_found / product_not_listed / not_supported

出力:
  exports/camera_buyback_status.json   （店舗×商品の成功/失敗・理由・成功率）

実行:
  python scripts/update_camera_buyback.py [--verbose] [--no-scrape]

注意:
  各買取店の新品/未使用買取見積は多くが JS フォーム・要ログインで、HTML から確定値を
  取得できないことが多い。その場合は本スクリプトが理由を記録し、manual_today を使う。
  実セレクタが用意でき次第、_parse_buyback_price() を店舗別に拡張する。
"""
import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
STATUS_PATH = ROOT / "exports" / "camera_buyback_status.json"

logger = logging.getLogger("update_camera_buyback")

# 対象カメラ（product_alias → 検索キーワード）
CAMERA_ALIASES = ["x100vi", "gr4", "gr4_hdf", "gr4_mono", "gr3x"]
CAMERA_KEYWORDS = {
    "x100vi":   "FUJIFILM X100VI",
    "gr4":      "RICOH GR IV",
    "gr4_hdf":  "RICOH GR IV HDF",
    "gr4_mono": "RICOH GR IV Monochrome",
    "gr3x":     "RICOH GR IIIx",
}

# 優先実装対象（Task 2: まず3店舗に絞る）
PRIORITY_SHOPS = {"src_mapcamera", "src_fujiya", "src_kitamura"}

# 対象買取店（shop_id, 表示名, 買取検索URLテンプレート {kw}=URLエンコード済キーワード）
CAMERA_SHOPS = [
    # マップカメラ 買取検索（新品/新品同様の買取価格が掲載される検索ページ）
    ("src_mapcamera", "マップカメラ",
     "https://www.mapcamera.com/search?keyword={kw}&sell=1"),
    # フジヤカメラ 買取（ネット販売・買取の検索）
    ("src_fujiya", "フジヤカメラ",
     "https://www.fujiya-camera.co.jp/shop/goods/search.aspx?search.x=0&keyword={kw}"),
    # カメラのキタムラ ネットワンプライス買取（新品/未使用買取参考）
    ("src_kitamura", "カメラのキタムラ",
     "https://www.net-chuko.com/sell/search-list.do?goodsname={kw}"),
    # 以下は補助（フォーム/JS のため取得困難・失敗理由を記録）
    ("src_sofmap", "ソフマップ", "https://www.sofmap.com/"),
    ("src_janpara", "じゃんぱら", "https://www.janpara.co.jp/sell/"),
    ("src_kaitori_shouten", "買取商店", "https://www.kaitorishouten-co.jp/"),
]

# オンライン見積もり非対応（HTML から新品買取が取れない）店舗 → not_supported
NOT_SUPPORTED = {"src_kaitori_shouten"}

# 店舗別 買取価格抽出パターン（新品/未使用の買取価格を優先的に拾う）
import re as _re_shop  # noqa: E402
_SHOP_PRICE_PATTERNS = {
    # マップカメラ: 「買取価格」「新品」近接の金額
    "src_mapcamera": [
        _re_shop.compile(r"(?:買取|新品|未使用)[^¥￥\d]{0,30}[¥￥]\s?([0-9]{2,3}(?:,[0-9]{3})+)"),
    ],
    "src_fujiya": [
        _re_shop.compile(r"(?:買取|新品|未使用)[^¥￥\d]{0,30}[¥￥]\s?([0-9]{2,3}(?:,[0-9]{3})+)"),
    ],
    "src_kitamura": [
        _re_shop.compile(r"(?:買取|新品|未使用)[^¥￥\d]{0,30}[¥￥]\s?([0-9]{2,3}(?:,[0-9]{3})+)"),
    ],
}


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _fetch_html(url: str, timeout: int = 15) -> tuple[Optional[str], str]:
    """URL を取得して (html, reason) を返す。成功時 reason=''。"""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "ja,en;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status in (403, 429):
                return None, "site_blocked"
            if status == 404:
                return None, "product_not_listed"
            if status >= 500:
                return None, "service_unavailable"
            data = resp.read(400_000)
            html = data.decode("utf-8", errors="ignore")
            if any(k in html.lower() for k in ("captcha", "are you a robot", "cloudflare")):
                return None, "site_blocked"
            return html, ""
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__.lower()
        if "timeout" in name:
            return None, "timeout"
        if "http" in name and "403" in str(e):
            return None, "site_blocked"
        return None, "http_error"


def _parse_buyback_price(html: str, alias: str, shop_id: str = "") -> Optional[int]:
    """HTML から新品/未使用買取価格を抽出する（店舗別パターン優先）。

    店舗別パターン（_SHOP_PRICE_PATTERNS）→ 汎用パターンの順に試行。
    妥当範囲（¥10,000〜¥1,500,000）に収まる最初の金額を返す。
    取得できない場合は None（price_not_found として記録、manual_today にフォールバック）。
    """
    def _valid(v: int) -> bool:
        return 10_000 <= v <= 1_500_000

    # 1) 店舗別パターン
    for pat in _SHOP_PRICE_PATTERNS.get(shop_id, []):
        m = pat.search(html)
        if m:
            try:
                v = int(m.group(1).replace(",", ""))
                if _valid(v):
                    return v
            except (ValueError, IndexError):
                pass
    # 2) 汎用パターン（新品/未使用/未開封 近接の金額）
    for m in re.finditer(r"(新品|未使用|未開封)[^¥￥\d]{0,20}[¥￥]?\s?([0-9]{2,3}(?:,[0-9]{3})+)\s*円?", html):
        try:
            v = int(m.group(2).replace(",", ""))
            if _valid(v):
                return v
        except ValueError:
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="カメラ新品/未使用買取価格コレクター")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-scrape", action="store_true", help="取得せず status のみ出力")
    parser.add_argument("--priority-only", action="store_true",
                        help="優先3店舗（マップ/フジヤ/キタムラ）のみ取得")
    args = parser.parse_args()
    setup_logging(args.verbose)

    now = datetime.now(tz=JST)
    logger.info("update_camera_buyback 開始: %s", now.strftime("%Y-%m-%d %H:%M JST"))

    try:
        from src.db.database import Database
        from src.db.repository import Repository
        from src.models.buyback_price import BuybackPriceModel
        repo = Repository(Database())
    except Exception as e:  # noqa: BLE001
        logger.error("DB初期化失敗: %s", e)
        repo = None

    import urllib.parse as _up
    results = []  # (alias, shop_id, status, price, reason)
    saved = 0
    for alias in CAMERA_ALIASES:
        kw = CAMERA_KEYWORDS.get(alias, alias)
        kw_enc = _up.quote(kw)
        for shop_id, shop_name, url_tmpl in CAMERA_SHOPS:
            if args.priority_only and shop_id not in PRIORITY_SHOPS:
                continue
            if args.no_scrape:
                results.append((alias, shop_id, "SKIP", 0, "scrape_skipped"))
                continue
            if shop_id in NOT_SUPPORTED:
                results.append((alias, shop_id, "FAILED", 0, "not_supported"))
                continue
            url = url_tmpl.format(kw=kw_enc) if "{kw}" in url_tmpl else url_tmpl
            html, reason = _fetch_html(url)
            # 優先店舗は取得HTMLを保存（原因分析用）— 取得できた場合のみ
            if html is not None and shop_id in PRIORITY_SHOPS:
                try:
                    _dbg = ROOT / "exports" / "debug_camera"
                    _dbg.mkdir(parents=True, exist_ok=True)
                    (_dbg / f"{shop_id}_{alias}.html").write_text(html[:200_000], encoding="utf-8")
                except Exception:
                    pass
            if html is None:
                results.append((alias, shop_id, "FAILED", 0, reason))
                continue
            price = _parse_buyback_price(html, alias, shop_id)
            if not price or price <= 0:
                # HTML は取れたが価格抽出不可 → 原因を細分類
                _low = html.lower()
                if any(k in _low for k in ("captcha", "robot", "cloudflare", "access denied")):
                    _r = "site_blocked"
                elif len(html) < 800:
                    _r = "empty_html"
                else:
                    _r = "price_not_found"
                results.append((alias, shop_id, "FAILED", 0, _r))
                continue
            # 取得成功 → auto_scraped（新品未開封）で保存
            results.append((alias, shop_id, "OK", price, ""))
            if repo is not None:
                try:
                    pid = "prod_" + alias if not alias.startswith("prod_") else alias
                    bp = BuybackPriceModel(
                        product_id=pid, shop_id=shop_id, shop_name=shop_name,
                        buyback_price=price, condition="new_unopened", buyback_url=url,
                        observed_at=now, data_source="auto_scraped",
                        link_verified=True, confidence="medium",
                    )
                    repo.insert_buyback_price(bp)
                    saved += 1
                except Exception as e:  # noqa: BLE001
                    logger.debug("保存失敗 %s/%s: %s", alias, shop_id, e)

    ok = sum(1 for r in results if r[2] == "OK")
    failed = sum(1 for r in results if r[2] == "FAILED")
    skip = sum(1 for r in results if r[2] == "SKIP")
    total = len(results)
    from collections import Counter
    reasons = Counter(r[4] for r in results if r[2] == "FAILED" and r[4])

    status = {
        "generated_at": now.isoformat(timespec="seconds"),
        "summary": {"total": total, "ok": ok, "failed": failed, "skip": skip,
                    "success_rate_pct": round(100.0 * ok / total, 1) if total else 0.0,
                    "saved_to_db": saved},
        "failure_reasons": [{"reason": k, "count": v} for k, v in reasons.most_common()],
        "detail": [{"product_alias": a, "shop_id": s, "status": st, "price": p, "reason": rs}
                   for (a, s, st, p, rs) in results],
        "fallback_note": ("HTMLから新品買取を確定できない店舗は manual_buyback_prices.csv の "
                          "manual_today（手動確認）を使用。14日超は利益判定から除外。"),
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("camera_buyback_status 保存: OK=%d / FAILED=%d / SKIP=%d (saved_to_db=%d)",
                ok, failed, skip, saved)
    if ok == 0:
        logger.warning("WARNING: カメラ買取の自動取得は0件。manual_today（手動確認）で表示します。"
                       "（理由: %s）", dict(reasons))
    return 0


if __name__ == "__main__":
    sys.exit(main())
