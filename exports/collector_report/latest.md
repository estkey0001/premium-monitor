# Collector Quality Report

生成日時: 2026-06-04 13:46:34 UTC+09:00

## サマリ

| 合計 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| 55 | 22 | 29 | 4 |

## 店舗別 OK/失敗/スキップ

| 店舗 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| 2ndstreet | 0 | 4 | 0 |
| bookoff | 0 | 0 | 2 |
| dosupara | 0 | 2 | 0 |
| geo | 1 | 1 | 0 |
| geo_mobile | 0 | 4 | 0 |
| hardoff | 0 | 2 | 0 |
| iosys | 6 | 0 | 0 |
| janpara | 0 | 6 | 0 |
| kaitori_itchome | 4 | 0 | 0 |
| kaitori_shouten | 6 | 0 | 0 |
| mobile_ichiban | 3 | 2 | 0 |
| netoff | 2 | 2 | 0 |
| pasoko | 0 | 2 | 0 |
| sofmap | 0 | 2 | 0 |
| surugaya | 0 | 2 | 0 |
| tsutaya | 0 | 0 | 2 |

## 商品別 OK/失敗/スキップ

| 商品 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| iphone17pm256 | 4 | 4 | 0 |
| iphone17pm512 | 3 | 5 | 0 |
| iphone17pro256 | 5 | 3 | 0 |
| iphone17pro512 | 4 | 4 | 0 |
| ps5_pro | 3 | 7 | 2 |
| switch2 | 3 | 6 | 2 |

## 商品別 成功店舗数（目標達成状況）

| 商品 | 成功店舗数 | 目標 | 達成 | 平均価格 | 最低価格 | 最高価格 | suspicious |
|------|-----------|------|------|---------|---------|---------|-----------|
| iphone17pm256 | 4 | 3 | ✅ | ¥189,500 | ¥172,000 | ¥196,000 | — |
| iphone17pm512 | 3 | 3 | ✅ | ¥221,000 | ¥205,000 | ¥231,000 | — |
| iphone17pro256 | 5 | 3 | ✅ | ¥171,120 | ¥157,000 | ¥180,000 | — |
| iphone17pro512 | 4 | 3 | ✅ | ¥201,512 | ¥187,000 | ¥215,000 | — |
| ps5_pro | 3 | 2 | ✅ | ¥123,133 | ¥100,000 | ¥134,700 | — |
| switch2 | 3 | 2 | ✅ | ¥47,000 | ¥45,000 | ¥50,000 | — |

| 商品 | 成功店舗 |
|------|---------|
| iphone17pm256 | mobile_ichiban, kaitori_shouten, kaitori_itchome, iosys |
| iphone17pm512 | kaitori_shouten, kaitori_itchome, iosys |
| iphone17pro256 | mobile_ichiban, kaitori_shouten, kaitori_itchome, iosys, netoff |
| iphone17pro512 | kaitori_shouten, kaitori_itchome, iosys, netoff |
| ps5_pro | iosys, kaitori_shouten, mobile_ichiban |
| switch2 | geo, iosys, kaitori_shouten |

## 店舗別 詳細統計

| 店舗 | 成功率 | OK | 失敗 | 429率 | ブロック率 | 主な失敗理由 |
|------|-------|-----|------|------|-----------|------------|
| 2ndstreet | 0% | 0 | 4 | — | — | price_not_found |
| bookoff | 0% | 0 | 0 | — | — | not_supported |
| dosupara | 0% | 0 | 2 | — | — | http_404 |
| geo | 50% | 1 | 1 | — | — | product_not_listed |
| geo_mobile | 0% | 0 | 4 | — | 4/4 | site_blocked |
| hardoff | 0% | 0 | 2 | — | — | http_404 |
| iosys | 100% | 6 | 0 | — | — | — |
| janpara | 0% | 0 | 6 | 6/6 | — | rate_limited_429 |
| kaitori_itchome | 100% | 4 | 0 | — | — | — |
| kaitori_shouten | 100% | 6 | 0 | — | — | — |
| mobile_ichiban | 60% | 3 | 2 | — | — | product_not_listed |
| netoff | 50% | 2 | 2 | — | — | price_not_found |
| pasoko | 0% | 0 | 2 | — | — | product_not_listed |
| sofmap | 0% | 0 | 2 | — | — | service_unavailable |
| surugaya | 0% | 0 | 2 | — | 2/2 | site_blocked |
| tsutaya | 0% | 0 | 0 | — | — | not_supported |

## 優先修正対象

**商品別**: すべての商品が目標店舗数を達成しています

### 店舗別 TOP5（成功率0%）
1. 2ndstreet (price_not_found 4件)
2. bookoff (not_supported 2件)
3. dosupara (http_404 2件)
4. geo_mobile (site_blocked 4件)
5. hardoff (http_404 2件)

## 取得不可理由ランキング

| 理由 | 件数 |
|------|------|
| rate_limited_429 | 6 |
| site_blocked | 6 |
| price_not_found | 6 |
| product_not_listed | 5 |
| http_404 | 4 |
| not_supported | 4 |
| service_unavailable | 1 |
| connection_error | 1 |

## 取得失敗一覧 (33件)

| 商品 | 店舗 | ステータス | 理由 |
|------|------|-----------|------|
| iphone17pro256 | janpara | FAILED | rate_limited_429 |
| iphone17pro256 | geo_mobile | FAILED | site_blocked |
| iphone17pro256 | 2ndstreet | FAILED | price_not_found |
| iphone17pro512 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pro512 | janpara | FAILED | rate_limited_429 |
| iphone17pro512 | geo_mobile | FAILED | site_blocked |
| iphone17pro512 | 2ndstreet | FAILED | price_not_found |
| iphone17pm256 | janpara | FAILED | rate_limited_429 |
| iphone17pm256 | geo_mobile | FAILED | site_blocked |
| iphone17pm256 | 2ndstreet | FAILED | price_not_found |
| iphone17pm256 | netoff | FAILED | price_not_found |
| iphone17pm512 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pm512 | janpara | FAILED | rate_limited_429 |
| iphone17pm512 | geo_mobile | FAILED | site_blocked |
| iphone17pm512 | 2ndstreet | FAILED | price_not_found |
| iphone17pm512 | netoff | FAILED | price_not_found |
| switch2 | janpara | FAILED | rate_limited_429 |
| switch2 | hardoff | FAILED | http_404 |
| switch2 | dosupara | FAILED | http_404 |
| switch2 | pasoko | FAILED | product_not_listed |
| switch2 | sofmap | FAILED | service_unavailable |
| switch2 | bookoff | SKIP | not_supported |
| switch2 | surugaya | FAILED | site_blocked |
| switch2 | tsutaya | SKIP | not_supported |
| ps5_pro | geo | FAILED | product_not_listed |
| ps5_pro | janpara | FAILED | rate_limited_429 |
| ps5_pro | hardoff | FAILED | http_404 |
| ps5_pro | dosupara | FAILED | http_404 |
| ps5_pro | pasoko | FAILED | product_not_listed |
| ps5_pro | sofmap | FAILED | connection_error |
| ps5_pro | bookoff | SKIP | not_supported |
| ps5_pro | surugaya | FAILED | site_blocked |
| ps5_pro | tsutaya | SKIP | not_supported |

## 価格変動一覧 (5件)

| 商品 | 店舗 | 前回 | 今回 | 変化率 |
|------|------|------|------|--------|
| iphone17pm256 | kaitori_shouten | ¥192,000 | ¥195,000 | ↑1.6% |
| switch2 | kaitori_shouten | ¥50,800 | ¥50,000 | ↓1.6% |
| iphone17pro256 | kaitori_shouten | ¥178,000 | ¥179,500 | ↑0.8% |
| iphone17pm512 | kaitori_shouten | ¥226,000 | ¥227,000 | ↑0.4% |
| ps5_pro | kaitori_shouten | ¥134,500 | ¥134,700 | ↑0.1% |

## ⚠️ suspicious_price 一覧 (0件)

（suspicious_price なし）
