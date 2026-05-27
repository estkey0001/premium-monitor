# Collector Quality Report

生成日時: 2026-05-27 13:35:38 UTC+09:00

## サマリ

| 合計 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| 55 | 16 | 35 | 4 |

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
| netoff | 0 | 4 | 0 |
| pasoko | 0 | 2 | 0 |
| sofmap | 0 | 2 | 0 |
| surugaya | 0 | 2 | 0 |
| tsutaya | 0 | 0 | 2 |

## 商品別 OK/失敗/スキップ

| 商品 | OK | 失敗 | スキップ |
|------|-----|------|----------|
| iphone17pm256 | 3 | 5 | 0 |
| iphone17pm512 | 2 | 6 | 0 |
| iphone17pro256 | 3 | 5 | 0 |
| iphone17pro512 | 2 | 6 | 0 |
| ps5_pro | 3 | 7 | 2 |
| switch2 | 3 | 6 | 2 |

## 商品別 成功店舗数（目標達成状況）

| 商品 | 成功店舗数 | 目標 | 達成 | 平均価格 | 最低価格 | 最高価格 | suspicious |
|------|-----------|------|------|---------|---------|---------|-----------|
| iphone17pm256 | 3 | 3 | ✅ | ¥189,000 | ¥172,000 | ¥197,500 | — |
| iphone17pm512 | 2 | 3 | ❌ | ¥215,750 | ¥205,000 | ¥226,500 | — |
| iphone17pro256 | 3 | 3 | ✅ | ¥173,333 | ¥157,000 | ¥181,500 | — |
| iphone17pro512 | 2 | 3 | ❌ | ¥200,750 | ¥187,000 | ¥214,500 | — |
| ps5_pro | 3 | 2 | ✅ | ¥123,000 | ¥100,000 | ¥134,500 | — |
| switch2 | 3 | 2 | ✅ | ¥48,500 | ¥46,000 | ¥50,000 | — |

| 商品 | 成功店舗 |
|------|---------|
| iphone17pm256 | mobile_ichiban, kaitori_shouten, iosys |
| iphone17pm512 | kaitori_shouten, iosys |
| iphone17pro256 | mobile_ichiban, kaitori_shouten, iosys |
| iphone17pro512 | kaitori_shouten, iosys |
| ps5_pro | iosys, kaitori_shouten, mobile_ichiban |
| switch2 | geo, iosys, kaitori_shouten |

## 店舗別 詳細統計

| 店舗 | 成功率 | OK | 失敗 | 429率 | ブロック率 | 主な失敗理由 |
|------|-------|-----|------|------|-----------|------------|
| 2ndstreet | 0% | 0 | 4 | — | 4/4 | http_403 |
| bookoff | 0% | 0 | 0 | — | — | not_supported |
| dosupara | 0% | 0 | 2 | — | — | http_404 |
| geo | 50% | 1 | 1 | — | — | price_not_found |
| geo_mobile | 0% | 0 | 4 | — | — | playwright_not_installed |
| hardoff | 0% | 0 | 2 | — | — | http_404 |
| iosys | 100% | 6 | 0 | — | — | — |
| janpara | 0% | 0 | 6 | — | — | playwright_not_installed |
| kaitori_itchome | 0% | 0 | 4 | — | — | empty_html |
| kaitori_shouten | 100% | 6 | 0 | — | — | — |
| mobile_ichiban | 60% | 3 | 2 | — | — | price_not_found |
| netoff | 0% | 0 | 4 | — | — | price_not_found |
| pasoko | 0% | 0 | 2 | — | — | price_not_found |
| sofmap | 0% | 0 | 2 | — | — | service_unavailable |
| surugaya | 0% | 0 | 2 | — | 2/2 | site_blocked |
| tsutaya | 0% | 0 | 0 | — | — | not_supported |

## 優先修正対象

### 商品別（目標店舗数未達）
- iphone17pro512: 成功2店舗 (目標3) — あと1店舗必要
- iphone17pm512: 成功2店舗 (目標3) — あと1店舗必要

### 店舗別 TOP5（成功率0%）
1. 2ndstreet (http_403 4件)
2. bookoff (not_supported 2件)
3. dosupara (http_404 2件)
4. geo_mobile (playwright_not_installed 4件)
5. hardoff (http_404 2件)

## 取得不可理由ランキング

| 理由 | 件数 |
|------|------|
| playwright_not_installed | 10 |
| price_not_found | 9 |
| empty_html | 4 |
| http_403 | 4 |
| http_404 | 4 |
| not_supported | 4 |
| service_unavailable | 2 |
| site_blocked | 2 |

## 取得失敗一覧 (39件)

| 商品 | 店舗 | ステータス | 理由 |
|------|------|-----------|------|
| iphone17pro256 | kaitori_itchome | FAILED | empty_html |
| iphone17pro256 | janpara | FAILED | playwright_not_installed |
| iphone17pro256 | geo_mobile | FAILED | playwright_not_installed |
| iphone17pro256 | 2ndstreet | FAILED | http_403 |
| iphone17pro256 | netoff | FAILED | price_not_found |
| iphone17pro512 | mobile_ichiban | FAILED | price_not_found |
| iphone17pro512 | kaitori_itchome | FAILED | empty_html |
| iphone17pro512 | janpara | FAILED | playwright_not_installed |
| iphone17pro512 | geo_mobile | FAILED | playwright_not_installed |
| iphone17pro512 | 2ndstreet | FAILED | http_403 |
| iphone17pro512 | netoff | FAILED | price_not_found |
| iphone17pm256 | kaitori_itchome | FAILED | empty_html |
| iphone17pm256 | janpara | FAILED | playwright_not_installed |
| iphone17pm256 | geo_mobile | FAILED | playwright_not_installed |
| iphone17pm256 | 2ndstreet | FAILED | http_403 |
| iphone17pm256 | netoff | FAILED | price_not_found |
| iphone17pm512 | mobile_ichiban | FAILED | price_not_found |
| iphone17pm512 | kaitori_itchome | FAILED | empty_html |
| iphone17pm512 | janpara | FAILED | playwright_not_installed |
| iphone17pm512 | geo_mobile | FAILED | playwright_not_installed |
| iphone17pm512 | 2ndstreet | FAILED | http_403 |
| iphone17pm512 | netoff | FAILED | price_not_found |
| switch2 | janpara | FAILED | playwright_not_installed |
| switch2 | hardoff | FAILED | http_404 |
| switch2 | dosupara | FAILED | http_404 |
| switch2 | pasoko | FAILED | price_not_found |
| switch2 | sofmap | FAILED | service_unavailable |
| switch2 | bookoff | SKIP | not_supported |
| switch2 | surugaya | FAILED | site_blocked |
| switch2 | tsutaya | SKIP | not_supported |
| ps5_pro | geo | FAILED | price_not_found |
| ps5_pro | janpara | FAILED | playwright_not_installed |
| ps5_pro | hardoff | FAILED | http_404 |
| ps5_pro | dosupara | FAILED | http_404 |
| ps5_pro | pasoko | FAILED | price_not_found |
| ps5_pro | sofmap | FAILED | service_unavailable |
| ps5_pro | bookoff | SKIP | not_supported |
| ps5_pro | surugaya | FAILED | site_blocked |
| ps5_pro | tsutaya | SKIP | not_supported |

## 価格変動一覧 (0件)

（前回との変動なし）

## ⚠️ suspicious_price 一覧 (0件)

（suspicious_price なし）
