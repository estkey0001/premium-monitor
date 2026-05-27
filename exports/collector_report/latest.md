# Collector Quality Report

生成日時: 2026-05-27 18:52:55 UTC+09:00

## サマリ

| 合計 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| 55 | 20 | 31 | 4 |

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
| kaitori_itchome | 0 | 4 | 0 |
| kaitori_shouten | 6 | 0 | 0 |
| mobile_ichiban | 3 | 2 | 0 |
| netoff | 4 | 0 | 0 |
| pasoko | 0 | 2 | 0 |
| sofmap | 0 | 2 | 0 |
| surugaya | 0 | 2 | 0 |
| tsutaya | 0 | 0 | 2 |

## 商品別 OK/失敗/スキップ

| 商品 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| iphone17pm256 | 4 | 4 | 0 |
| iphone17pm512 | 3 | 5 | 0 |
| iphone17pro256 | 4 | 4 | 0 |
| iphone17pro512 | 3 | 5 | 0 |
| ps5_pro | 3 | 7 | 2 |
| switch2 | 3 | 6 | 2 |

## 商品別 成功店舗数（目標達成状況）

| 商品 | 成功店舗数 | 目標 | 達成 | 平均価格 | 最低価格 | 最高価格 | suspicious |
|------|-----------|------|------|---------|---------|---------|-----------|
| iphone17pm256 | 4 | 3 | ✅ | ¥185,062 | ¥172,000 | ¥197,500 | — |
| iphone17pm512 | 3 | 3 | ✅ | ¥212,250 | ¥204,750 | ¥227,000 | — |
| iphone17pro256 | 4 | 3 | ✅ | ¥169,900 | ¥157,000 | ¥181,500 | — |
| iphone17pro512 | 3 | 3 | ✅ | ¥197,350 | ¥187,000 | ¥215,000 | — |
| ps5_pro | 3 | 2 | ✅ | ¥123,000 | ¥100,000 | ¥134,500 | — |
| switch2 | 3 | 2 | ✅ | ¥48,600 | ¥46,000 | ¥50,000 | — |

| 商品 | 成功店舗 |
|------|---------|
| iphone17pm256 | mobile_ichiban, kaitori_shouten, iosys, netoff |
| iphone17pm512 | kaitori_shouten, iosys, netoff |
| iphone17pro256 | mobile_ichiban, kaitori_shouten, iosys, netoff |
| iphone17pro512 | kaitori_shouten, iosys, netoff |
| ps5_pro | iosys, kaitori_shouten, mobile_ichiban |
| switch2 | geo, iosys, kaitori_shouten |

## 店舗別 詳細統計

| 店舗 | 成功率 | OK | 失敗 | 429率 | ブロック率 | 主な失敗理由 |
|------|-------|-----|------|------|-----------|------------|
| 2ndstreet | 0% | 0 | 4 | — | 4/4 | http_403 |
| bookoff | 0% | 0 | 0 | — | — | not_supported |
| dosupara | 0% | 0 | 2 | — | — | http_404 |
| geo | 50% | 1 | 1 | — | — | product_not_listed |
| geo_mobile | 0% | 0 | 4 | — | — | playwright_not_installed |
| hardoff | 0% | 0 | 2 | — | — | http_404 |
| iosys | 100% | 6 | 0 | — | — | — |
| janpara | 0% | 0 | 6 | — | — | playwright_not_installed |
| kaitori_itchome | 0% | 0 | 4 | — | — | playwright_not_installed |
| kaitori_shouten | 100% | 6 | 0 | — | — | — |
| mobile_ichiban | 60% | 3 | 2 | — | — | product_not_listed |
| netoff | 100% | 4 | 0 | — | — | — |
| pasoko | 0% | 0 | 2 | — | — | product_not_listed |
| sofmap | 0% | 0 | 2 | — | — | service_unavailable |
| surugaya | 0% | 0 | 2 | — | 2/2 | site_blocked |
| tsutaya | 0% | 0 | 0 | — | — | not_supported |

## 優先修正対象

**商品別**: すべての商品が目標店舗数を達成しています

### 店舗別 TOP5（成功率0%）
1. 2ndstreet (http_403 4件)
2. bookoff (not_supported 2件)
3. dosupara (http_404 2件)
4. geo_mobile (playwright_not_installed 4件)
5. hardoff (http_404 2件)

## 取得不可理由ランキング

| 理由 | 件数 |
|------|------|
| playwright_not_installed | 14 |
| product_not_listed | 5 |
| http_403 | 4 |
| http_404 | 4 |
| not_supported | 4 |
| service_unavailable | 2 |
| site_blocked | 2 |

## 取得失敗一覧 (35件)

| 商品 | 店舗 | ステータス | 理由 |
|------|------|-----------|------|
| iphone17pro256 | kaitori_itchome | FAILED | playwright_not_installed |
| iphone17pro256 | janpara | FAILED | playwright_not_installed |
| iphone17pro256 | geo_mobile | FAILED | playwright_not_installed |
| iphone17pro256 | 2ndstreet | FAILED | http_403 |
| iphone17pro512 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pro512 | kaitori_itchome | FAILED | playwright_not_installed |
| iphone17pro512 | janpara | FAILED | playwright_not_installed |
| iphone17pro512 | geo_mobile | FAILED | playwright_not_installed |
| iphone17pro512 | 2ndstreet | FAILED | http_403 |
| iphone17pm256 | kaitori_itchome | FAILED | playwright_not_installed |
| iphone17pm256 | janpara | FAILED | playwright_not_installed |
| iphone17pm256 | geo_mobile | FAILED | playwright_not_installed |
| iphone17pm256 | 2ndstreet | FAILED | http_403 |
| iphone17pm512 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pm512 | kaitori_itchome | FAILED | playwright_not_installed |
| iphone17pm512 | janpara | FAILED | playwright_not_installed |
| iphone17pm512 | geo_mobile | FAILED | playwright_not_installed |
| iphone17pm512 | 2ndstreet | FAILED | http_403 |
| switch2 | janpara | FAILED | playwright_not_installed |
| switch2 | hardoff | FAILED | http_404 |
| switch2 | dosupara | FAILED | http_404 |
| switch2 | pasoko | FAILED | product_not_listed |
| switch2 | sofmap | FAILED | service_unavailable |
| switch2 | bookoff | SKIP | not_supported |
| switch2 | surugaya | FAILED | site_blocked |
| switch2 | tsutaya | SKIP | not_supported |
| ps5_pro | geo | FAILED | product_not_listed |
| ps5_pro | janpara | FAILED | playwright_not_installed |
| ps5_pro | hardoff | FAILED | http_404 |
| ps5_pro | dosupara | FAILED | http_404 |
| ps5_pro | pasoko | FAILED | product_not_listed |
| ps5_pro | sofmap | FAILED | service_unavailable |
| ps5_pro | bookoff | SKIP | not_supported |
| ps5_pro | surugaya | FAILED | site_blocked |
| ps5_pro | tsutaya | SKIP | not_supported |

## 価格変動一覧 (0件)

（前回との変動なし）

## ⚠️ suspicious_price 一覧 (0件)

（suspicious_price なし）
