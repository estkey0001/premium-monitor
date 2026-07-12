# Collector Quality Report

生成日時: 2026-07-12 14:48:50 UTC+09:00

## サマリ

| 合計 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| 55 | 13 | 38 | 4 |

## 店舗別 OK/失敗/スキップ

| 店舗 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| 2ndstreet | 0 | 4 | 0 |
| bookoff | 0 | 0 | 2 |
| dosupara | 0 | 2 | 0 |
| geo | 1 | 1 | 0 |
| geo_mobile | 0 | 4 | 0 |
| hardoff | 0 | 2 | 0 |
| iosys | 0 | 6 | 0 |
| janpara | 0 | 6 | 0 |
| kaitori_itchome | 4 | 0 | 0 |
| kaitori_shouten | 6 | 0 | 0 |
| mobile_ichiban | 0 | 5 | 0 |
| netoff | 2 | 2 | 0 |
| pasoko | 0 | 2 | 0 |
| sofmap | 0 | 2 | 0 |
| surugaya | 0 | 2 | 0 |
| tsutaya | 0 | 0 | 2 |

## 商品別 OK/失敗/スキップ

| 商品 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| iphone17pm256 | 2 | 6 | 0 |
| iphone17pm512 | 2 | 6 | 0 |
| iphone17pro256 | 3 | 5 | 0 |
| iphone17pro512 | 3 | 5 | 0 |
| ps5_pro | 1 | 9 | 2 |
| switch2 | 2 | 7 | 2 |

## 商品別 成功店舗数（目標達成状況）

| 商品 | 成功店舗数 | 目標 | 達成 | 平均価格 | 最低価格 | 最高価格 | suspicious |
|------|-----------|------|------|---------|---------|---------|-----------|
| iphone17pm256 | 2 | 3 | ❌ | ¥191,500 | ¥191,000 | ¥192,000 | — |
| iphone17pm512 | 2 | 3 | ❌ | ¥226,750 | ¥226,500 | ¥227,000 | — |
| iphone17pro256 | 3 | 3 | ✅ | ¥169,833 | ¥157,500 | ¥176,500 | — |
| iphone17pro512 | 3 | 3 | ✅ | ¥203,650 | ¥187,950 | ¥211,500 | — |
| ps5_pro | 1 | 2 | ❌ | ¥147,800 | ¥147,800 | ¥147,800 | — |
| switch2 | 2 | 2 | ✅ | ¥44,750 | ¥40,000 | ¥49,500 | — |

| 商品 | 成功店舗 |
|------|---------|
| iphone17pm256 | kaitori_shouten, kaitori_itchome |
| iphone17pm512 | kaitori_shouten, kaitori_itchome |
| iphone17pro256 | kaitori_shouten, kaitori_itchome, netoff |
| iphone17pro512 | kaitori_shouten, kaitori_itchome, netoff |
| ps5_pro | kaitori_shouten |
| switch2 | geo, kaitori_shouten |

## 店舗別 詳細統計

| 店舗 | 成功率 | OK | 失敗 | 429率 | ブロック率 | 主な失敗理由 |
|------|-------|-----|------|------|-----------|------------|
| 2ndstreet | 0% | 0 | 4 | — | — | price_not_found |
| bookoff | 0% | 0 | 0 | — | — | not_supported |
| dosupara | 0% | 0 | 2 | — | — | http_404 |
| geo | 50% | 1 | 1 | — | — | product_not_listed |
| geo_mobile | 0% | 0 | 4 | — | 4/4 | site_blocked |
| hardoff | 0% | 0 | 2 | — | — | http_404 |
| iosys | 0% | 0 | 6 | — | 6/6 | http_403 |
| janpara | 0% | 0 | 6 | 5/6 | — | rate_limited_429 |
| kaitori_itchome | 100% | 4 | 0 | — | — | — |
| kaitori_shouten | 100% | 6 | 0 | — | — | — |
| mobile_ichiban | 0% | 0 | 5 | — | — | product_not_listed |
| netoff | 50% | 2 | 2 | — | — | price_not_found |
| pasoko | 0% | 0 | 2 | — | — | product_not_listed |
| sofmap | 0% | 0 | 2 | — | — | service_unavailable |
| surugaya | 0% | 0 | 2 | — | 2/2 | site_blocked |
| tsutaya | 0% | 0 | 0 | — | — | not_supported |

## 優先修正対象

### 商品別（目標店舗数未達）
- iphone17pm256: 成功2店舗 (目標3) — あと1店舗必要
- iphone17pm512: 成功2店舗 (目標3) — あと1店舗必要
- ps5_pro: 成功1店舗 (目標2) — あと1店舗必要

### 店舗別 TOP5（成功率0%）
1. 2ndstreet (price_not_found 4件)
2. bookoff (not_supported 2件)
3. dosupara (http_404 2件)
4. geo_mobile (site_blocked 4件)
5. hardoff (http_404 2件)

## 取得不可理由ランキング

| 理由 | 件数 |
|------|------|
| product_not_listed | 8 |
| http_403 | 6 |
| site_blocked | 6 |
| price_not_found | 6 |
| rate_limited_429 | 5 |
| http_404 | 4 |
| not_supported | 4 |
| service_unavailable | 2 |
| playwright_error | 1 |

## 取得失敗一覧 (42件)

| 商品 | 店舗 | ステータス | 理由 |
|------|------|-----------|------|
| iphone17pro256 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pro256 | janpara | FAILED | rate_limited_429 |
| iphone17pro256 | iosys | FAILED | http_403 |
| iphone17pro256 | geo_mobile | FAILED | site_blocked |
| iphone17pro256 | 2ndstreet | FAILED | price_not_found |
| iphone17pro512 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pro512 | janpara | FAILED | rate_limited_429 |
| iphone17pro512 | iosys | FAILED | http_403 |
| iphone17pro512 | geo_mobile | FAILED | site_blocked |
| iphone17pro512 | 2ndstreet | FAILED | price_not_found |
| iphone17pm256 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pm256 | janpara | FAILED | rate_limited_429 |
| iphone17pm256 | iosys | FAILED | http_403 |
| iphone17pm256 | geo_mobile | FAILED | site_blocked |
| iphone17pm256 | 2ndstreet | FAILED | price_not_found |
| iphone17pm256 | netoff | FAILED | price_not_found |
| iphone17pm512 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pm512 | janpara | FAILED | rate_limited_429 |
| iphone17pm512 | iosys | FAILED | http_403 |
| iphone17pm512 | geo_mobile | FAILED | site_blocked |
| iphone17pm512 | 2ndstreet | FAILED | price_not_found |
| iphone17pm512 | netoff | FAILED | price_not_found |
| switch2 | iosys | FAILED | http_403 |
| switch2 | janpara | FAILED | rate_limited_429 |
| switch2 | hardoff | FAILED | http_404 |
| switch2 | dosupara | FAILED | http_404 |
| switch2 | pasoko | FAILED | product_not_listed |
| switch2 | sofmap | FAILED | service_unavailable |
| switch2 | bookoff | SKIP | not_supported |
| switch2 | surugaya | FAILED | site_blocked |
| switch2 | tsutaya | SKIP | not_supported |
| ps5_pro | geo | FAILED | product_not_listed |
| ps5_pro | iosys | FAILED | http_403 |
| ps5_pro | mobile_ichiban | FAILED | product_not_listed |
| ps5_pro | janpara | FAILED | playwright_error |
| ps5_pro | hardoff | FAILED | http_404 |
| ps5_pro | dosupara | FAILED | http_404 |
| ps5_pro | pasoko | FAILED | product_not_listed |
| ps5_pro | sofmap | FAILED | service_unavailable |
| ps5_pro | bookoff | SKIP | not_supported |
| ps5_pro | surugaya | FAILED | site_blocked |
| ps5_pro | tsutaya | SKIP | not_supported |

## 価格変動一覧 (9件)

| 商品 | 店舗 | 前回 | 今回 | 変化率 |
|------|------|------|------|--------|
| switch2 | geo | ¥45,000 | ¥40,000 | ↓11.1% |
| ps5_pro | kaitori_shouten | ¥134,500 | ¥147,800 | ↑9.9% |
| switch2 | kaitori_shouten | ¥50,800 | ¥49,500 | ↓2.6% |
| iphone17pro256 | kaitori_shouten | ¥178,000 | ¥175,500 | ↓1.4% |
| iphone17pro256 | netoff | ¥159,600 | ¥157,500 | ↓1.3% |
| iphone17pro512 | kaitori_shouten | ¥214,000 | ¥211,500 | ↓1.2% |
| iphone17pro512 | netoff | ¥190,050 | ¥187,950 | ↓1.1% |
| iphone17pm256 | kaitori_shouten | ¥192,000 | ¥191,000 | ↓0.5% |
| iphone17pm512 | kaitori_shouten | ¥226,000 | ¥226,500 | ↑0.2% |

## ⚠️ suspicious_price 一覧 (0件)

（suspicious_price なし）
