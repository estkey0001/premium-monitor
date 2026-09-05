# Collector Quality Report

生成日時: 2026-09-05 16:14:27 UTC+09:00

## サマリ

| 合計 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| 55 | 11 | 40 | 4 |

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
| kaitori_shouten | 0 | 6 | 0 |
| mobile_ichiban | 2 | 3 | 0 |
| netoff | 4 | 0 | 0 |
| pasoko | 0 | 2 | 0 |
| sofmap | 0 | 2 | 0 |
| surugaya | 0 | 2 | 0 |
| tsutaya | 0 | 0 | 2 |

## 商品別 OK/失敗/スキップ

| 商品 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| iphone17pm256 | 3 | 5 | 0 |
| iphone17pm512 | 2 | 6 | 0 |
| iphone17pro256 | 2 | 6 | 0 |
| iphone17pro512 | 2 | 6 | 0 |
| ps5_pro | 1 | 9 | 2 |
| switch2 | 1 | 8 | 2 |

## 商品別 成功店舗数（目標達成状況）

| 商品 | 成功店舗数 | 目標 | 達成 | 平均価格 | 最低価格 | 最高価格 | suspicious |
|------|-----------|------|------|---------|---------|---------|-----------|
| iphone17pm256 | 3 | 3 | ✅ | ¥186,800 | ¥176,400 | ¥192,000 | — |
| iphone17pm512 | 2 | 3 | ❌ | ¥211,775 | ¥200,550 | ¥223,000 | — |
| iphone17pro256 | 2 | 3 | ❌ | ¥169,375 | ¥162,750 | ¥176,000 | — |
| iphone17pro512 | 2 | 3 | ❌ | ¥198,000 | ¥189,000 | ¥207,000 | — |
| ps5_pro | 1 | 2 | ❌ | ¥180,300 | ¥180,300 | ¥180,300 | — |
| switch2 | 1 | 2 | ❌ | ¥35,000 | ¥35,000 | ¥35,000 | ⚠️ |

| 商品 | 成功店舗 |
|------|---------|
| iphone17pm256 | mobile_ichiban, kaitori_itchome, netoff |
| iphone17pm512 | kaitori_itchome, netoff |
| iphone17pro256 | kaitori_itchome, netoff |
| iphone17pro512 | kaitori_itchome, netoff |
| ps5_pro | mobile_ichiban |
| switch2 | geo |

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
| janpara | 0% | 0 | 6 | 6/6 | — | rate_limited_429 |
| kaitori_itchome | 100% | 4 | 0 | — | — | — |
| kaitori_shouten | 0% | 0 | 6 | — | — | price_not_found |
| mobile_ichiban | 40% | 2 | 3 | — | — | product_not_listed |
| netoff | 100% | 4 | 0 | — | — | — |
| pasoko | 0% | 0 | 2 | — | — | product_not_listed |
| sofmap | 0% | 0 | 2 | — | — | service_unavailable |
| surugaya | 0% | 0 | 2 | — | 2/2 | site_blocked |
| tsutaya | 0% | 0 | 0 | — | — | not_supported |

## 優先修正対象

### 商品別（目標店舗数未達）
- iphone17pro256: 成功2店舗 (目標3) — あと1店舗必要
- iphone17pro512: 成功2店舗 (目標3) — あと1店舗必要
- iphone17pm512: 成功2店舗 (目標3) — あと1店舗必要
- switch2: 成功1店舗 (目標2) — あと1店舗必要
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
| price_not_found | 10 |
| product_not_listed | 6 |
| rate_limited_429 | 6 |
| http_403 | 6 |
| site_blocked | 6 |
| http_404 | 4 |
| not_supported | 4 |
| service_unavailable | 2 |

## 取得失敗一覧 (44件)

| 商品 | 店舗 | ステータス | 理由 |
|------|------|-----------|------|
| iphone17pro256 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pro256 | kaitori_shouten | FAILED | price_not_found |
| iphone17pro256 | janpara | FAILED | rate_limited_429 |
| iphone17pro256 | iosys | FAILED | http_403 |
| iphone17pro256 | geo_mobile | FAILED | site_blocked |
| iphone17pro256 | 2ndstreet | FAILED | price_not_found |
| iphone17pro512 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pro512 | kaitori_shouten | FAILED | price_not_found |
| iphone17pro512 | janpara | FAILED | rate_limited_429 |
| iphone17pro512 | iosys | FAILED | http_403 |
| iphone17pro512 | geo_mobile | FAILED | site_blocked |
| iphone17pro512 | 2ndstreet | FAILED | price_not_found |
| iphone17pm256 | kaitori_shouten | FAILED | price_not_found |
| iphone17pm256 | janpara | FAILED | rate_limited_429 |
| iphone17pm256 | iosys | FAILED | http_403 |
| iphone17pm256 | geo_mobile | FAILED | site_blocked |
| iphone17pm256 | 2ndstreet | FAILED | price_not_found |
| iphone17pm512 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pm512 | kaitori_shouten | FAILED | price_not_found |
| iphone17pm512 | janpara | FAILED | rate_limited_429 |
| iphone17pm512 | iosys | FAILED | http_403 |
| iphone17pm512 | geo_mobile | FAILED | site_blocked |
| iphone17pm512 | 2ndstreet | FAILED | price_not_found |
| switch2 | iosys | FAILED | http_403 |
| switch2 | kaitori_shouten | FAILED | price_not_found |
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
| ps5_pro | kaitori_shouten | FAILED | price_not_found |
| ps5_pro | janpara | FAILED | rate_limited_429 |
| ps5_pro | hardoff | FAILED | http_404 |
| ps5_pro | dosupara | FAILED | http_404 |
| ps5_pro | pasoko | FAILED | product_not_listed |
| ps5_pro | sofmap | FAILED | service_unavailable |
| ps5_pro | bookoff | SKIP | not_supported |
| ps5_pro | surugaya | FAILED | site_blocked |
| ps5_pro | tsutaya | SKIP | not_supported |

## 価格変動一覧 (3件)

| 商品 | 店舗 | 前回 | 今回 | 変化率 |
|------|------|------|------|--------|
| switch2 | geo | ¥45,000 | ¥35,000 | ↓22.2% |
| iphone17pro256 | netoff | ¥159,600 | ¥162,750 | ↑2.0% |
| iphone17pro512 | netoff | ¥190,050 | ¥189,000 | ↓0.6% |

## ⚠️ suspicious_price 一覧 (1件)

| 商品 | 店舗 | 価格 | 理由 | 詳細 |
|------|------|------|------|------|
| switch2 | geo | ¥35,000 | price_change_over_20pct | 前回¥45,000 → 今回¥35,000（-22.2% 下落） |
