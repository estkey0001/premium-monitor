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

# 対象カメラ（product_alias）
CAMERA_ALIASES = ["x100vi", "gr4", "gr4_hdf", "gr4_mono", "gr3x"]

# 対象買取店（shop_id, 表示名, 買取ページURL）
CAMERA_SHOPS = [
    ("src_mapcamera",       "マップカメラ",       "https://www.mapcamera.com/"),
    ("src_kitamura",        "カメラのキタムラ",   "https://www.kitamura.co.jp/"),
    ("src_fujiya",          "フジヤカメラ",       "https://www.fujiyacamera.com/"),
    ("src_sofmap",          "ソフマップ",         "https://www.sofmap.com/"),
    ("src_janpara",         "じゃんぱら",         "https://www.janpara.co.jp/sell/"),
    ("src_kaitori_shouten", "買取商店",           "https://www.kaitorishouten-co.jp/"),
]

# オンライン見積もり非対応（HTML から新品買取が取れない）店舗 → not_supported
NOT_SUPPORTED = {"src_kaitori_shouten"}


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


def _parse_buyback_price(html: str, alias: str) -> Optional[int]:
    """HTML から新品/未使用買取価格を抽出する（best-effort）。

    現状は汎用パターンのみ。確定的に新品買取と判別できない場合は None を返し、
    price_not_found として記録する（manual_today にフォールバック）。
    実セレクタが用意でき次第、店舗別に拡張する。
    """
    # 「買取価格 ¥xxx,xxx」「新品 買取 xxx円」などの近接パターンのみ採用
    for m in re.finditer(r"(新品|未使用|未開封)[^¥\d]{0,20}[¥￥]?\s?([0-9]{2,3}(?:,[0-9]{3})+)\s*円?", html):
        try:
            return int(m.group(2).replace(",", ""))
        except ValueError:
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="カメラ新品/未使用買取価格コレクター")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-scrape", action="store_true", help="取得せず status のみ出力")
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

    results = []  # (alias, shop_id, status, price, reason)
    saved = 0
    for alias in CAMERA_ALIASES:
        for shop_id, shop_name, url in CAMERA_SHOPS:
            if args.no_scrape:
                results.append((alias, shop_id, "SKIP", 0, "scrape_skipped"))
                continue
            if shop_id in NOT_SUPPORTED:
                results.append((alias, shop_id, "FAILED", 0, "not_supported"))
                continue
            html, reason = _fetch_html(url)
            if html is None:
                results.append((alias, shop_id, "FAILED", 0, reason))
                continue
            price = _parse_buyback_price(html, alias)
            if not price or price <= 0:
                results.append((alias, shop_id, "FAILED", 0, "price_not_found"))
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
