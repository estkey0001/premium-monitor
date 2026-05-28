"""為替レートのライブ取得モジュール。

プライマリ: open.er-api.com (無料、認証不要)
フォールバック: config/fx_rates.yaml の静的レート
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.error
import yaml

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
JST = timezone(timedelta(hours=9))
_CACHE: dict = {}  # {currency_pair: {rate, fetched_at}}
CACHE_TTL_HOURS = 6  # 6時間キャッシュ

ER_API_URL = "https://open.er-api.com/v6/latest/USD"
TIMEOUT_SEC = 10

# フォールバック静的レート
_STATIC_RATES = {
    "USD_JPY": 155.0,
    "EUR_JPY": 170.0,
    "GBP_JPY": 195.0,
    "HKD_JPY": 20.0,
    "CNY_JPY": 21.0,
    "AUD_JPY": 100.0,
    "CAD_JPY": 113.0,
}


def get_usd_jpy(force_refresh: bool = False) -> tuple[float, str]:
    """USD/JPY レートを取得する。

    Returns:
        (rate, source) - source は "live" or "config" or "static_fallback"
    """
    return _get_rate("USD", "JPY", force_refresh)


def get_eur_jpy(force_refresh: bool = False) -> tuple[float, str]:
    """EUR/JPY レートを取得する。"""
    return _get_rate("EUR", "JPY", force_refresh)


def _get_rate(from_currency: str, to_currency: str, force_refresh: bool = False) -> tuple[float, str]:
    key = f"{from_currency}_{to_currency}"
    now = datetime.now(tz=JST)

    # キャッシュチェック
    if not force_refresh and key in _CACHE:
        cached = _CACHE[key]
        age_h = (now - cached["fetched_at"]).total_seconds() / 3600
        if age_h < CACHE_TTL_HOURS:
            return cached["rate"], cached["source"]

    # ライブ取得
    try:
        req = urllib.request.Request(
            ER_API_URL,
            headers={"User-Agent": "PremiumMonitor/1.0"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("result") != "success":
            raise ValueError(f"API error: {data.get('error-type', 'unknown')}")

        rates = data.get("rates", {})
        jpy_rate = rates.get("JPY", 0)
        if to_currency == "JPY" and from_currency == "USD":
            rate = float(jpy_rate)
        elif to_currency == "JPY":
            # 例: EUR→JPY = (JPY/USD) / (EUR/USD)
            from_rate = rates.get(from_currency, 0)
            rate = float(jpy_rate) / float(from_rate) if from_rate else 0

        if rate <= 0:
            raise ValueError("Invalid rate: %s" % rate)

        _CACHE[key] = {"rate": rate, "source": "live", "fetched_at": now}
        logger.info("FX %s/%s = %.2f (live)", from_currency, to_currency, rate)
        return rate, "live"

    except Exception as e:
        logger.warning("FX live fetch failed (%s), falling back: %s", key, e)

    # config/fx_rates.yaml フォールバック
    try:
        with open(PROJECT_ROOT / "config" / "fx_rates.yaml", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        rate = float(config.get("fx_rates", {}).get(key, 0))
        if rate > 0:
            _CACHE[key] = {"rate": rate, "source": "config", "fetched_at": now}
            return rate, "config"
    except Exception:
        pass

    # 静的フォールバック
    rate = float(_STATIC_RATES.get(key, 155.0))
    _CACHE[key] = {"rate": rate, "source": "static_fallback", "fetched_at": now}
    logger.warning("FX using static fallback %s = %.2f", key, rate)
    return rate, "static_fallback"


def update_fx_yaml(rates: dict) -> None:
    """取得したレートを config/fx_rates.yaml に書き戻す。"""
    yaml_path = PROJECT_ROOT / "config" / "fx_rates.yaml"
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        existing = data.get("fx_rates", {})
        existing.update(rates)
        data["fx_rates"] = existing
        data["updated_at"] = datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M JST")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
        logger.info("fx_rates.yaml updated: %s", rates)
    except Exception as e:
        logger.warning("fx_rates.yaml update failed: %s", e)
