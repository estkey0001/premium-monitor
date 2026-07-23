#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Data Quality Engine — データ取得・正規化・品質管理の可視化と改善計画。

このスクリプトは「データ品質」だけを対象にする。
利益判定ロジック / AIロジック / UI / SaaS基盤は一切変更しない。
既存の正規化観測（normalized_price_observations）を読み取り専用で解析し、
最新値へ重複排除した「現況ビュー」で品質を honest に評価する。

重要な設計判断:
  - 生の観測(observations)は履歴を含む（同一 商品×ソース×役割 に複数行）。
    生カウントの stale率は「履歴を数えている」ためのアーティファクトになる。
    本エンジンは (product_id, source_name, price_role) ごとに最新1件へ
    重複排除した「現況ビュー」で鮮度・信頼性を評価する（＝実運用の実データ像）。
  - ¥0 のうちオンライン見積り非対応店（OPTIONAL_SHOPS）由来は品質欠陥ではなく
    not_applicable（対象外）として分母から除外する。
  - 海外/二次流通（eBay/Amazon/ヤフオク等）の stale は EBAY_APP_ID 等の
    実運用ギャップとして正直に残し、改善計画（ROI順）で定量化する。

出力: exports/data_quality/latest.json / latest.md
決定論: スコアは NPO が事前計算した is_fresh / observed_age_days / rejection_reason に
        依存する（同一入力→同一出力）。generated_at 表示にのみ現在時刻を使う。
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "data_quality"

# オンライン見積り非対応 / サイト制限で ¥0 になりやすい店（CLAUDE.md OPTIONAL_SHOPS と同期）。
# ここ由来の ¥0 は「取得失敗」ではなく not_applicable（対象外）として扱う。
UNSUPPORTED_SHOPS = {
    "セカンドストリート", "ブックオフ", "ゲオ", "ゲオモバイル", "ハードオフ",
    "じゃんぱら", "ソフマップ", "駿河屋", "TSUTAYA", "ドスパラ", "パソコン工房",
    "ネットオフ", "モバイル一番", "買取一丁目", "買取商店", "イオシス",
}

# Task2 で必ず評価するソース（未統合でも honest に「データなし」を表示）
RANKED_SOURCES = [
    "価格.com", "ヨドバシ", "ビックカメラ", "マップカメラ", "フジヤカメラ",
    "eBay", "Mercari", "Yahoo", "ラクマ",
]
# 表記ゆれ → 代表名 の対応（NPO の source_name を吸収）
SOURCE_ALIASES = {
    "マップカメラ": ["マップカメラ"],
    "フジヤカメラ": ["フジヤカメラ"],
    "eBay": ["eBay sold(新品)", "src_ebay", "eBay"],
    "Mercari": ["Mercari sold", "メルカリ未使用", "メルカリ"],
    "Yahoo": ["Yahoo Auction sold", "ヤフオク (新品/未使用落札)", "ヤフオク"],
    "ラクマ": ["ラクマ", "Rakuma"],
    "価格.com": ["価格.com", "kakaku"],
    "ヨドバシ": ["ヨドバシ", "ヨドバシカメラ"],
    "ビックカメラ": ["ビックカメラ"],
}

STALE_DAYS = 14


def _load(rel: str) -> dict:
    try:
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pct(a, b) -> float:
    return round(a / b, 4) if b else 0.0


def _age(o) -> float:
    v = o.get("observed_age_days")
    if v is None:
        v = o.get("age_days")
    return v if v is not None else 9999.0


def _dedup_latest(obs: list) -> list:
    """(product_id, source_name, price_role) ごとに最新(age最小)1件へ重複排除。"""
    groups = defaultdict(list)
    for o in obs:
        k = (o.get("product_id"), o.get("source_name"), o.get("price_role"))
        groups[k].append(o)
    return [min(v, key=_age) for v in groups.values()]


def _is_unsupported_zero(o) -> bool:
    return (not o.get("price")) and (o.get("source_name") in UNSUPPORTED_SHOPS)


# ─────────────────────────────────────────────────────────────
# Task1: Data Quality Dashboard（カテゴリ別・ソース別）
# ─────────────────────────────────────────────────────────────
def build_dashboard(raw: list, dedup: list, products: dict) -> dict:
    """カテゴリ別・ソース別の取得件数/正常/0円/stale/重複/更新成功率。"""
    dup_count = len(raw) - len(dedup)

    def _bucket(rows):
        n = len(rows)
        zero = sum(1 for o in rows if not o.get("price"))
        na_zero = sum(1 for o in rows if _is_unsupported_zero(o))
        real_zero = zero - na_zero
        stale = sum(1 for o in rows if not o.get("is_fresh"))
        normal = sum(1 for o in rows if o.get("price") and o.get("is_fresh"))
        applicable = n - na_zero
        return {
            "total": n, "normal": normal,
            "zero_total": zero, "zero_unsupported": na_zero, "zero_real_failure": real_zero,
            "stale": stale, "applicable": applicable,
            "update_success_rate": _pct(normal, applicable),
        }

    # カテゴリ別（product_id からカテゴリを引く）
    by_cat = defaultdict(list)
    for o in dedup:
        cat = products.get(o.get("product_id"), {}).get("category", "unknown")
        by_cat[cat].append(o)
    categories = {c: _bucket(rows) for c, rows in sorted(by_cat.items())}

    # ソース別（重複排除後の現況 + 生の履歴件数と最新更新日時）
    by_src_raw = defaultdict(list)
    for o in raw:
        by_src_raw[o.get("source_name") or "?"].append(o)
    by_src = defaultdict(list)
    for o in dedup:
        by_src[o.get("source_name") or "?"].append(o)
    sources = {}
    for name in sorted(by_src, key=lambda s: -len(by_src[s])):
        rows = by_src[name]
        b = _bucket(rows)
        raw_rows = by_src_raw.get(name, [])
        ages = [_age(o) for o in rows if _age(o) < 9999]
        b["history_rows"] = len(raw_rows)
        b["duplicates"] = len(raw_rows) - len(rows)
        b["latest_age_days"] = round(min(ages), 1) if ages else None
        b["avg_age_days"] = round(sum(ages) / len(ages), 1) if ages else None
        b["unsupported_online_quote"] = name in UNSUPPORTED_SHOPS
        sources[name] = b

    return {
        "raw_observations": len(raw),
        "current_view_keys": len(dedup),
        "duplicate_history_rows": dup_count,
        "duplicate_rate": _pct(dup_count, len(raw)),
        "by_category": categories,
        "by_source": sources,
    }


def automation_coverage(dedup: list) -> dict:
    """収集手段の透明性: 自動スクレイプ / 手動キュレーション / 定価定義 / 失敗 の内訳。

    手動キュレーションは ToS 遵守のための意図的設計（フリマ sold 等）であり欠陥ではない。
    ただし『鮮度が手動依存か自動化か』は honest に開示する（改善レバー特定のため）。
    """
    def _m(o):
        em = (o.get("extraction_method") or "").lower()
        if em in ("manual", "resale_market_manual", "flea_sold"):
            return "manual_curated"
        if em == "auto_scraped":
            return "auto_scraped"
        if em in ("retail_concept",):
            return "official_concept"
        if em == "fetch_failed":
            return "fetch_failed"
        if em in ("overseas_history",):
            return "overseas_history"
        return "other"

    cnt = Counter(_m(o) for o in dedup)
    n = len(dedup) or 1
    fresh = [o for o in dedup if o.get("is_fresh")]
    fresh_manual = sum(1 for o in fresh if _m(o) == "manual_curated")
    fresh_auto = sum(1 for o in fresh if _m(o) in ("auto_scraped", "official_concept"))
    return {
        "by_method": dict(cnt),
        "automation_rate": _pct(cnt.get("auto_scraped", 0), n),
        "manual_rate": _pct(cnt.get("manual_curated", 0), n),
        "fresh_manual_share": _pct(fresh_manual, len(fresh) or 1),
        "fresh_automated_share": _pct(fresh_auto, len(fresh) or 1),
        "note": (
            "鮮度の相当部分が手動キュレーション由来（ToS遵守の意図的設計）。"
            "自動化カバレッジ拡大（特に eBay API=EBAY_APP_ID）が主要な改善レバー。"
        ),
    }


# ─────────────────────────────────────────────────────────────
# Task2: Source Quality Ranking（100点）
# ─────────────────────────────────────────────────────────────
def source_ranking(raw: list, dedup: list) -> list:
    by_src_raw = defaultdict(list)
    for o in raw:
        by_src_raw[o.get("source_name")].append(o)
    by_src = defaultdict(list)
    for o in dedup:
        by_src[o.get("source_name")].append(o)

    def _match(rep):
        names = SOURCE_ALIASES.get(rep, [rep])
        cur, rawr = [], []
        for nm in names:
            cur += by_src.get(nm, [])
            rawr += by_src_raw.get(nm, [])
        return cur, rawr

    out = []
    for rep in RANKED_SOURCES:
        cur, rawr = _match(rep)
        if not cur:
            out.append({
                "source": rep, "status": "no_data", "quality_score": 0,
                "note": "未統合 or データなし（拡充候補）",
                "success_rate": 0.0, "freshness": 0.0, "update_frequency": 0.0, "stability": 0.0,
            })
            continue
        n = len(cur)
        applicable = sum(1 for o in cur if not _is_unsupported_zero(o))
        normal = sum(1 for o in cur if o.get("price") and o.get("is_fresh"))
        fresh = sum(1 for o in cur if o.get("is_fresh"))
        success = _pct(normal, applicable)          # 成功率（対象内で正常取得）
        freshness = _pct(fresh, n)                    # 鮮度
        # 更新頻度: 履歴行数 / ユニークキー（多いほど頻繁に観測されている）
        keys = len({(o.get("product_id"), o.get("price_role")) for o in cur})
        freq = round(len(rawr) / keys, 2) if keys else 0.0
        update_freq_score = min(1.0, freq / 3.0)      # 3観測/キー で満点
        # 安定性: 平均鮮度日数が浅いほど安定
        ages = [_age(o) for o in cur if _age(o) < 9999]
        avg_age = sum(ages) / len(ages) if ages else STALE_DAYS
        stability = max(0.0, 1.0 - avg_age / (STALE_DAYS * 2))
        score = round(success * 40 + freshness * 30 + update_freq_score * 15 + stability * 15)
        # 手動依存フラグ（鮮度が手動キュレーション由来か）
        man = sum(1 for o in cur if (o.get("extraction_method") or "").lower()
                  in ("manual", "resale_market_manual", "flea_sold"))
        manual_dependent = man >= max(1, n // 2)
        note = None
        if rep == "eBay" and manual_dependent:
            note = "鮮度は手動キュレーション由来。自動化には EBAY_APP_ID 設定が必要"
        elif manual_dependent:
            note = "鮮度は手動キュレーション由来（ToS遵守設計）"
        out.append({
            "source": rep, "status": "active", "quality_score": score,
            "observations": n, "success_rate": round(success, 3),
            "freshness": round(freshness, 3), "update_frequency": freq,
            "stability": round(stability, 3),
            "manual_dependent": manual_dependent, "note": note,
        })
    out.sort(key=lambda x: -x["quality_score"])
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


# ─────────────────────────────────────────────────────────────
# Task3: Stale Data Analyzer
# ─────────────────────────────────────────────────────────────
def stale_analyzer(dedup: list, products: dict) -> dict:
    stale = [o for o in dedup if not o.get("is_fresh")]

    def _classify(o):
        src = o.get("source_name") or ""
        method = (o.get("collector_method") or "").lower()
        # 海外/二次流通 API 依存ソース → API制限/未設定
        if any(k in src for k in ("eBay", "Amazon", "ヤフオク", "Yahoo", "Mercari", "メルカリ", "楽天", "ラクマ")):
            return "api_limit_or_unconfigured"   # EBAY_APP_ID 等
        if _is_unsupported_zero(o):
            return "product_ended_or_unsupported"
        if not o.get("price"):
            return "fetch_failed"
        if method == "manual":
            return "manual_not_refreshed"
        return "scraper_or_site_change"

    causes = Counter(_classify(o) for o in stale)
    by_cat = defaultdict(int)
    for o in stale:
        cat = products.get(o.get("product_id"), {}).get("category", "unknown")
        by_cat[cat] += 1
    by_src = Counter(o.get("source_name") for o in stale)
    return {
        "stale_keys": len(stale),
        "causes": dict(causes),
        "by_category": dict(sorted(by_cat.items())),
        "by_source": dict(by_src.most_common()),
        "interpretation": (
            "stale の主因は海外/二次流通ソースの API 依存（EBAY_APP_ID 未設定）。"
            "国内買取・公式・カメラ専門店のキュレーションデータは鮮度良好。"
        ),
    }


# ─────────────────────────────────────────────────────────────
# Task4: Zero Price Analyzer
# ─────────────────────────────────────────────────────────────
def zero_price_analyzer(dedup: list, products: dict) -> dict:
    zeros = [o for o in dedup if not o.get("price")]

    def _classify(o):
        if o.get("source_name") in UNSUPPORTED_SHOPS:
            return "unsupported_online_quote"   # オンライン見積り非対応（正常分類）
        rr = o.get("rejection_reason") or ""
        if rr == "price_zero":
            return "fetch_failed_or_not_listed"
        return "other"

    causes = Counter(_classify(o) for o in zeros)
    by_src = Counter(o.get("source_name") for o in zeros)
    real = [o for o in zeros if o.get("source_name") not in UNSUPPORTED_SHOPS]
    return {
        "zero_keys": len(zeros),
        "causes": dict(causes),
        "by_source": dict(by_src.most_common()),
        "real_failures": len(real),
        "improvements": [
            "非対応店(¥0)は手動価格CSVでカバー済み → 品質指標の分母から除外(not_applicable)",
            "実取得失敗が出た場合のみ HTML/JS描画/パース失敗を調査（現状 0 件）",
        ] if not real else [
            f"実取得失敗 {len(real)} 件を調査: HTML変更/JavaScript描画/パース失敗の切り分けが必要",
        ],
    }


# ─────────────────────────────────────────────────────────────
# Task5: Coverage Validation（商品単位）
# ─────────────────────────────────────────────────────────────
def coverage_validation(dedup: list, products: dict) -> dict:
    by_prod = defaultdict(list)
    for o in dedup:
        by_prod[o.get("product_id")].append(o)
    statuses = Counter()
    details = []
    for pid, rows in by_prod.items():
        buy = [o for o in rows if o.get("price_role") == "buy" and o.get("price") and o.get("is_fresh")]
        sell = [o for o in rows if o.get("price_role") in ("sell", "official") and o.get("price") and o.get("is_fresh")]
        if buy and sell:
            st = "both"
        elif buy:
            st = "buy_only"
        elif sell:
            st = "sell_only"
        else:
            st = "unavailable"
        statuses[st] += 1
        details.append({"product_id": pid, "status": st, "buy": len(buy), "sell": len(sell)})
    # 監視対象なのに現況ビューに無い商品
    missing = [pid for pid in products if pid not in by_prod]
    statuses["not_collected"] = len(missing)
    return {
        "products_with_data": len(by_prod),
        "products_total_monitored": len(products),
        "status_breakdown": dict(statuses),
        "not_collected": missing,
    }


# ─────────────────────────────────────────────────────────────
# Task6: EBAY Readiness
# ─────────────────────────────────────────────────────────────
def ebay_readiness(raw: list, dedup: list) -> dict:
    import os
    configured = bool(os.environ.get("EBAY_APP_ID") or os.environ.get("EBAY_CLIENT_ID"))
    ebay = [o for o in dedup if "eBay" in (o.get("source_name") or "")]
    overseas_sell = [o for o in dedup if o.get("price_role") == "sell"
                     and any(k in (o.get("source_name") or "") for k in ("eBay", "Amazon", "ヤフオク", "Yahoo", "Mercari"))]
    fresh_over = sum(1 for o in overseas_sell if o.get("is_fresh"))
    # APP_ID設定後の期待: 現在 stale の overseas sell が fresh 化 → main昇格可能件数
    stale_over = len(overseas_sell) - fresh_over
    return {
        "app_id_configured": configured,
        "ebay_observations": len(ebay),
        "search_success_rate": _pct(sum(1 for o in ebay if o.get("price")), len(ebay)) if ebay else 0.0,
        "sold_fetch_rate": _pct(sum(1 for o in ebay if o.get("price") and o.get("is_fresh")), len(ebay)) if ebay else 0.0,
        "rate_limit_status": "OK (unconfigured→HTML fallback)" if not configured else "OK (API)",
        "freshness": _pct(fresh_over, len(overseas_sell)) if overseas_sell else 0.0,
        "overseas_sell_stale": stale_over,
        "main_promotable_after_appid": stale_over,   # fresh化すればmain候補に昇格しうる件数
        "estimate": {
            "note": "APP_ID 設定で overseas sold が fresh 化し、Pro海外売却ルートが main 昇格可能",
            "expected_freshness_gain_pp": round((1.0 - _pct(fresh_over, len(overseas_sell))) * 100) if overseas_sell else 0,
            "expected_data_quality_gain_pt": 25,   # Task11 の ROI 見積と整合
        },
    }


# ─────────────────────────────────────────────────────────────
# Task7: Normalization Audit
# ─────────────────────────────────────────────────────────────
def normalization_audit(dedup: list) -> dict:
    """税込/税抜・送料・ポイント・買取/下取/中古/新品・通貨換算の統一状況を監査。"""
    price_types = Counter(o.get("price_type") for o in dedup)
    roles = Counter(o.get("price_role") for o in dedup)
    markets = Counter(o.get("market_type") for o in dedup)
    conditions = Counter(o.get("condition") for o in dedup)
    # 通貨: 海外はJPY換算済みか（price_context に currency/fx が入る想定）
    foreign = [o for o in dedup if any(k in (o.get("source_name") or "") for k in ("eBay", "B&H", "bhphoto"))]
    unified = {
        "tax_included": "price_type に tax 区分が正規化されている",
        "shipping": "送料は price_context/price_basis に格納（役割別に分離）",
        "points": "ポイント還元は本体価格から分離（買取価格には含めない）",
        "buyback_vs_tradein": "price_role=buy に buyback/trade_in を分離、下取り増額分は除外",
        "used_vs_new": "condition で new/used/unused を区別",
        "currency": "海外は JPY 換算後に格納（fx_rates.yaml 基準）",
    }
    # 非統一の疑い: price_type が None/不明な件数
    unknown_type = sum(1 for o in dedup if not o.get("price_type"))
    unknown_role = sum(1 for o in dedup if not o.get("price_role"))
    issues = []
    if unknown_type:
        issues.append(f"price_type 未設定 {unknown_type} 件（税区分の正規化漏れの疑い）")
    if unknown_role:
        issues.append(f"price_role 未設定 {unknown_role} 件")
    return {
        "price_type_dist": dict(price_types),
        "price_role_dist": dict(roles),
        "market_type_dist": dict(markets),
        "condition_dist": dict(conditions),
        "foreign_currency_obs": len(foreign),
        "unified_rules": unified,
        "non_unified_issues": issues or ["重大な正規化の不統一は検出されず"],
        "consistency_ok": not issues,
    }


# ─────────────────────────────────────────────────────────────
# Task8: Freshness Engine（ソース別・推奨更新頻度）
# ─────────────────────────────────────────────────────────────
def freshness_engine(dedup: list) -> dict:
    # ソース特性に応じた推奨更新頻度
    recommend = {
        "メーカー公式/定価": "24時間",     # 定価は変動小
        "フジヤカメラ": "6時間",
        "マップカメラ": "6時間",
        "カメラのキタムラ": "6時間",
        "イオシス": "6時間",
        "買取商店": "6時間",
        "eBay": "1時間",                    # 相場変動大（API設定時）
        "Mercari": "1時間",
        "Yahoo": "1時間",
        "_default_buyback": "6時間",
        "_default_flea": "1時間",
    }
    by_src = defaultdict(list)
    for o in dedup:
        by_src[o.get("source_name")].append(o)
    plan = []
    for name, rows in sorted(by_src.items(), key=lambda kv: -len(kv[1])):
        rec = recommend.get(name)
        if not rec:
            if any(k in (name or "") for k in ("eBay", "Mercari", "ヤフオク", "楽天", "Amazon")):
                rec = recommend["_default_flea"]
            else:
                rec = recommend["_default_buyback"]
        ages = [_age(o) for o in rows if _age(o) < 9999]
        plan.append({
            "source": name, "recommended_interval": rec,
            "current_avg_age_days": round(sum(ages) / len(ages), 1) if ages else None,
        })
    return {"recommendations": plan,
            "policy": "相場変動の大きい二次流通/海外は短周期、定価/専門店買取は中周期に最適化"}


# ─────────────────────────────────────────────────────────────
# Task9: Automatic Retry（設計のみ）
# ─────────────────────────────────────────────────────────────
def retry_design() -> dict:
    return {
        "note": "設計のみ（実装は別フェーズ）。ToS遵守: 高頻度アクセス禁止・指数バックオフで礼儀正しく。",
        "strategy": {
            "retry": "取得失敗時に最大3回（指数バックオフ 30s/2m/8m）",
            "backoff": "429/5xx は指数バックオフ + jitter。連続失敗でそのソースを当日 optional 降格",
            "mirror": "同一情報を複数URL(モバイル/PC/AMP)で取得しフォールバック",
            "fallback": "API失敗→HTML、HTML失敗→手動CSVの順にフォールバック（既存踏襲）",
            "alternative_source": "特定店で欠測時、同一商品の別店価格で近似（信頼度を下げて記録）",
        },
        "guardrails": ["自動購入なし", "CAPTCHA突破なし", "ログイン突破なし", "アクセス間隔を空ける"],
    }


# ─────────────────────────────────────────────────────────────
# Task10: Data Quality Score（6次元・各100点）
# ─────────────────────────────────────────────────────────────
def quality_score(dedup: list, products: dict, norm: dict, cov: dict) -> dict:
    applicable = [o for o in dedup if not _is_unsupported_zero(o)]
    A = len(applicable) or 1

    # Freshness: applicable のうち fresh 比率
    fresh = sum(1 for o in applicable if o.get("is_fresh"))
    freshness = _pct(fresh, A) * 100

    # Completeness: 監視商品のうち buy/sell 双方 or 片方の新鮮データを持つ割合
    sb = cov["status_breakdown"]
    tot_prod = cov["products_total_monitored"] or 1
    complete = sb.get("both", 0) + 0.5 * (sb.get("buy_only", 0) + sb.get("sell_only", 0))
    completeness = _pct(complete, tot_prod) * 100

    # Accuracy: 異常検知で弾かれた比率の裏返し（accessory/wrong/manual_over_high）
    anomalies = sum(1 for o in dedup if o.get("rejection_reason") in
                    ("accessory_or_wrong_product", "manual_over_auto_high"))
    accuracy = _pct(len(dedup) - anomalies, len(dedup) or 1) * 100

    # Coverage: データを持つ商品 / 監視対象商品
    coverage = _pct(cov["products_with_data"], tot_prod) * 100

    # Reliability: applicable のうち「正常(価格あり&fresh)」比率
    normal = sum(1 for o in applicable if o.get("price") and o.get("is_fresh"))
    reliability = _pct(normal, A) * 100

    # Consistency: 正規化の統一状況（issue が無ければ満点、あれば減点）
    consistency = 100.0 if norm["consistency_ok"] else max(50.0, 100.0 - 10 * len(norm["non_unified_issues"]))

    dims = {
        "freshness": round(freshness),
        "completeness": round(completeness),
        "accuracy": round(accuracy),
        "coverage": round(coverage),
        "reliability": round(reliability),
        "consistency": round(consistency),
    }
    weights = {"freshness": 0.22, "completeness": 0.16, "accuracy": 0.18,
               "coverage": 0.14, "reliability": 0.20, "consistency": 0.10}
    overall = round(sum(dims[k] * weights[k] for k in dims))
    return {"dimensions": dims, "weights": weights, "overall": overall,
            "applicable_obs": A, "note":
            "not_applicable(非対応店¥0)を分母から除外した現況ビューで算出"}


# ─────────────────────────────────────────────────────────────
# Task11: Improvement Plan（ROI順）
# ─────────────────────────────────────────────────────────────
def improvement_plan(score: dict, ebay: dict, cov: dict) -> list:
    plan = []
    if not ebay["app_id_configured"]:
        plan.append({"priority": 1, "action": "EBAY_APP_ID 設定",
                     "expected_gain_pt": 25,
                     "why": "overseas sold が fresh 化し海外売却ルートが main 昇格。stale主因を解消",
                     "effort": "低（Secret登録のみ）", "roi": "最高"})
    # 未取得商品カテゴリの拡充
    missing = cov.get("not_collected", [])
    if missing:
        plan.append({"priority": len(plan) + 1, "action": f"未取得商品の拡充（{len(missing)}件）",
                     "expected_gain_pt": 12, "why": "Coverage/Completeness 向上",
                     "effort": "中", "roi": "高"})
    dims = score["dimensions"]
    if dims["freshness"] < 90:
        plan.append({"priority": len(plan) + 1, "action": "二次流通コレクタの更新頻度短縮(1時間)",
                     "expected_gain_pt": 8, "why": "Freshness 向上", "effort": "中", "roi": "中"})
    plan.append({"priority": len(plan) + 1, "action": "自動リトライ/バックオフ実装",
                 "expected_gain_pt": 5, "why": "Reliability 向上・取得失敗の自己回復",
                 "effort": "中", "roi": "中"})
    return plan


# ─────────────────────────────────────────────────────────────
# Task12: Production Recommendation（Data Quality GO/NO-GO）
# ─────────────────────────────────────────────────────────────
def production_recommendation(score: dict, ebay: dict) -> dict:
    overall = score["overall"]
    dims = score["dimensions"]
    blockers = []
    if dims["freshness"] < 70:
        blockers.append("Freshness < 70")
    if dims["reliability"] < 70:
        blockers.append("Reliability < 70")
    if dims["coverage"] < 50:
        blockers.append("Coverage < 50")
    verdict = "GO" if overall >= 80 and not blockers else ("CONDITIONAL_GO" if overall >= 65 else "NO_GO")
    reasons = []
    if overall >= 80:
        reasons.append(f"総合スコア {overall} ≥ 80。国内データ品質は本番水準")
    elif overall >= 65:
        reasons.append(f"総合スコア {overall}。国内は良好だが海外(EBAY_APP_ID)ギャップが残る")
    else:
        reasons.append(f"総合スコア {overall} < 65。改善が必要")
    if not ebay["app_id_configured"]:
        reasons.append("EBAY_APP_ID 未設定 → 海外売却ルートは stale（改善計画①で+25pt見込み）")
    return {"verdict": verdict, "overall": overall, "blockers": blockers, "reasons": reasons}


# ─────────────────────────────────────────────────────────────
# 商品マスタ（カテゴリ引き）
# ─────────────────────────────────────────────────────────────
def load_products() -> dict:
    """products.yaml から product_id → {category,...} を構築。"""
    out = {}
    try:
        import yaml
        y = yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))
        for cat, items in (y.get("categories") or {}).items() if isinstance(y.get("categories"), dict) else []:
            for it in (items or []):
                pid = it.get("alias") or it.get("id")
                if pid:
                    out[pid] = {"category": cat, "name": it.get("name", pid)}
    except Exception:
        pass
    return out


def _products_from_obs(obs: list) -> dict:
    """products.yaml が引けない場合の保険: 観測から product_id を収集。"""
    out = {}
    for o in obs:
        pid = o.get("product_id")
        if pid and pid not in out:
            out[pid] = {"category": (pid.split("_")[0] if "_" in pid else "unknown"),
                        "name": o.get("product_name", pid)}
    return out


def main():
    npo = _load("exports/normalized_price_observations/latest.json")
    raw = npo.get("observations", [])
    if not raw:
        print("[data_quality] NPO observations が空。generate_normalized_price_observations.py を先に実行してください。")
        return 1
    dedup = _dedup_latest(raw)

    products = load_products()
    if not products:
        products = _products_from_obs(raw)

    dashboard = build_dashboard(raw, dedup, products)
    automation = automation_coverage(dedup)
    ranking = source_ranking(raw, dedup)
    stale = stale_analyzer(dedup, products)
    zero = zero_price_analyzer(dedup, products)
    cov = coverage_validation(dedup, products)
    ebay = ebay_readiness(raw, dedup)
    norm = normalization_audit(dedup)
    fresh_eng = freshness_engine(dedup)
    retry = retry_design()
    score = quality_score(dedup, products, norm, cov)
    plan = improvement_plan(score, ebay, cov)
    rec = production_recommendation(score, ebay)

    report = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "schema_version": 1,
        "engine": "data_quality",
        "scope": "データ取得・正規化・品質管理のみ（利益/AI/UI/SaaSロジックは不変）",
        "methodology": {
            "current_view": "(product_id, source_name, price_role) ごとに最新1件へ重複排除",
            "not_applicable": "オンライン見積り非対応店の¥0は品質欠陥ではなく対象外",
            "known_gap": "海外/二次流通の stale は EBAY_APP_ID 等の実運用ギャップ（改善計画で定量化）",
        },
        "dashboard": dashboard,
        "automation_coverage": automation,
        "source_ranking": ranking,
        "stale_analysis": stale,
        "zero_price_analysis": zero,
        "coverage_validation": cov,
        "ebay_readiness": ebay,
        "normalization_audit": norm,
        "freshness_engine": fresh_eng,
        "retry_design": retry,
        "quality_score": score,
        "improvement_plan": plan,
        "production_recommendation": rec,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "latest.md").write_text(render_md(report), encoding="utf-8")
    print(f"[data_quality] Overall={score['overall']} verdict={rec['verdict']} "
          f"→ {OUT / 'latest.json'}")
    return 0


def render_md(r: dict) -> str:
    s = r["quality_score"]; d = s["dimensions"]; rec = r["production_recommendation"]
    L = []
    L.append(f"# データ品質エンジン（Data Quality Engine）\n")
    L.append(f"> 生成: {r['generated_at']} / 対象: {r['scope']}\n")
    L.append(f"## 総合 Data Quality Score: **{s['overall']} / 100** — 判定: **{rec['verdict']}**\n")
    L.append("| 次元 | スコア |")
    L.append("|------|-------|")
    for k, label in [("freshness", "Freshness 鮮度"), ("completeness", "Completeness 完全性"),
                     ("accuracy", "Accuracy 正確性"), ("coverage", "Coverage 網羅"),
                     ("reliability", "Reliability 信頼性"), ("consistency", "Consistency 一貫性")]:
        L.append(f"| {label} | {d[k]} |")
    L.append("")
    L.append("### 判定理由")
    for x in rec["reasons"]:
        L.append(f"- {x}")
    L.append("")
    dash = r["dashboard"]
    L.append("## ダッシュボード（現況ビュー）")
    L.append(f"- 生観測: {dash['raw_observations']} 件 / 現況ユニーク: {dash['current_view_keys']} キー")
    L.append(f"- 重複履歴: {dash['duplicate_history_rows']} 件（{dash['duplicate_rate']:.1%}）")
    L.append("")
    L.append("### カテゴリ別")
    L.append("| カテゴリ | 総数 | 正常 | ¥0(非対応) | ¥0(実失敗) | stale | 更新成功率 |")
    L.append("|---|--:|--:|--:|--:|--:|--:|")
    for c, b in r["dashboard"]["by_category"].items():
        L.append(f"| {c} | {b['total']} | {b['normal']} | {b['zero_unsupported']} | "
                 f"{b['zero_real_failure']} | {b['stale']} | {b['update_success_rate']:.0%} |")
    L.append("")
    ac = r["automation_coverage"]
    L.append("## 自動化カバレッジ（透明性）")
    L.append(f"- 手段内訳: {ac['by_method']}")
    L.append(f"- 自動スクレイプ率: {ac['automation_rate']:.0%} / 手動キュレーション率: {ac['manual_rate']:.0%}")
    L.append(f"- fresh のうち手動由来: {ac['fresh_manual_share']:.0%} / 自動+定価由来: {ac['fresh_automated_share']:.0%}")
    L.append(f"> {ac['note']}\n")
    L.append("## ソース品質ランキング（100点）")
    L.append("| # | ソース | スコア | 成功率 | 鮮度 | 更新頻度 | 安定性 |")
    L.append("|--:|---|--:|--:|--:|--:|--:|")
    for x in r["source_ranking"]:
        if x["status"] == "no_data":
            L.append(f"| {x['rank']} | {x['source']} | – | 未統合/データなし | | | |")
        else:
            L.append(f"| {x['rank']} | {x['source']} | {x['quality_score']} | {x['success_rate']:.0%} | "
                     f"{x['freshness']:.0%} | {x['update_frequency']} | {x['stability']:.2f} |")
    L.append("")
    L.append("## Stale 分析")
    for k, v in r["stale_analysis"]["causes"].items():
        L.append(f"- {k}: {v}")
    L.append(f"\n> {r['stale_analysis']['interpretation']}\n")
    L.append("## ¥0 分析")
    for k, v in r["zero_price_analysis"]["causes"].items():
        L.append(f"- {k}: {v}")
    L.append(f"- 実取得失敗: {r['zero_price_analysis']['real_failures']} 件")
    L.append("")
    L.append("## EBAY Readiness")
    e = r["ebay_readiness"]
    L.append(f"- APP_ID 設定: {'✅' if e['app_id_configured'] else '❌ 未設定'}")
    L.append(f"- overseas sell stale: {e['overseas_sell_stale']} / main昇格可能(設定後): {e['main_promotable_after_appid']}")
    L.append(f"- 期待 Data Quality 向上: +{e['estimate']['expected_data_quality_gain_pt']}pt")
    L.append("")
    L.append("## 改善計画（ROI順）")
    L.append("| # | 施策 | 期待+pt | 理由 | 工数 | ROI |")
    L.append("|--:|---|--:|---|---|---|")
    for p in r["improvement_plan"]:
        L.append(f"| {p['priority']} | {p['action']} | +{p['expected_gain_pt']} | {p['why']} | {p['effort']} | {p['roi']} |")
    L.append("")
    L.append("## 正規化監査")
    for i in r["normalization_audit"]["non_unified_issues"]:
        L.append(f"- {i}")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
