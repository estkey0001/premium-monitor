# Collector Quality Report

生成日時: 2026-09-20 17:06:28 UTC+09:00

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
| mobile_ichiban | 2 | 3 | 0 |
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
| iphone17pro256 | 2 | 6 | 0 |
| iphone17pro512 | 2 | 6 | 0 |
| ps5_pro | 2 | 8 | 2 |
| switch2 | 2 | 7 | 2 |

## 商品別 成功店舗数（目標達成状況）

| 商品 | 成功店舗数 | 目標 | 達成 | 平均価格 | 最低価格 | 最高価格 | suspicious |
|------|-----------|------|------|---------|---------|---------|-----------|
| iphone17pm256 | 3 | 3 | ✅ | ¥272,000 | ¥190,000 | ¥436,000 | ⚠️ |
| iphone17pm512 | 2 | 3 | ❌ | ¥327,000 | ¥218,000 | ¥436,000 | ⚠️ |
| iphone17pro256 | 2 | 3 | ❌ | ¥304,500 | ¥173,000 | ¥436,000 | ⚠️ |
| iphone17pro512 | 2 | 3 | ❌ | ¥318,500 | ¥201,000 | ¥436,000 | ⚠️ |
| ps5_pro | 2 | 2 | ✅ | ¥543,350 | ¥186,700 | ¥900,000 | ⚠️ |
| switch2 | 2 | 2 | ✅ | ¥467,500 | ¥35,000 | ¥900,000 | ⚠️ |

| 商品 | 成功店舗 |
|------|---------|
| iphone17pm256 | mobile_ichiban, kaitori_shouten, kaitori_itchome |
| iphone17pm512 | kaitori_shouten, kaitori_itchome |
| iphone17pro256 | kaitori_shouten, kaitori_itchome |
| iphone17pro512 | kaitori_shouten, kaitori_itchome |
| ps5_pro | kaitori_shouten, mobile_ichiban |
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
| janpara | 0% | 0 | 6 | 6/6 | — | rate_limited_429 |
| kaitori_itchome | 100% | 4 | 0 | — | — | — |
| kaitori_shouten | 100% | 6 | 0 | — | — | — |
| mobile_ichiban | 40% | 2 | 3 | — | — | product_not_listed |
| netoff | 0% | 0 | 4 | — | — | price_not_found |
| pasoko | 0% | 0 | 2 | — | — | product_not_listed |
| sofmap | 0% | 0 | 2 | — | — | service_unavailable |
| surugaya | 0% | 0 | 2 | — | 2/2 | site_blocked |
| tsutaya | 0% | 0 | 0 | — | — | not_supported |

## 優先修正対象

### 商品別（目標店舗数未達）
- iphone17pro256: 成功2店舗 (目標3) — あと1店舗必要
- iphone17pro512: 成功2店舗 (目標3) — あと1店舗必要
- iphone17pm512: 成功2店舗 (目標3) — あと1店舗必要

### 店舗別 TOP5（成功率0%）
1. 2ndstreet (price_not_found 4件)
2. bookoff (not_supported 2件)
3. dosupara (http_404 2件)
4. geo_mobile (site_blocked 4件)
5. hardoff (http_404 2件)

## 取得不可理由ランキング

| 理由 | 件数 |
|------|------|
| price_not_found | 8 |
| product_not_listed | 6 |
| rate_limited_429 | 6 |
| http_403 | 6 |
| site_blocked | 6 |
| http_404 | 4 |
| not_supported | 4 |
| service_unavailable | 2 |

## 取得失敗一覧 (42件)

| 商品 | 店舗 | ステータス | 理由 |
|------|------|-----------|------|
| iphone17pro256 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pro256 | janpara | FAILED | rate_limited_429 |
| iphone17pro256 | iosys | FAILED | http_403 |
| iphone17pro256 | geo_mobile | FAILED | site_blocked |
| iphone17pro256 | 2ndstreet | FAILED | price_not_found |
| iphone17pro256 | netoff | FAILED | price_not_found |
| iphone17pro512 | mobile_ichiban | FAILED | product_not_listed |
| iphone17pro512 | janpara | FAILED | rate_limited_429 |
| iphone17pro512 | iosys | FAILED | http_403 |
| iphone17pro512 | geo_mobile | FAILED | site_blocked |
| iphone17pro512 | 2ndstreet | FAILED | price_not_found |
| iphone17pro512 | netoff | FAILED | price_not_found |
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
| ps5_pro | janpara | FAILED | rate_limited_429 |
| ps5_pro | hardoff | FAILED | http_404 |
| ps5_pro | dosupara | FAILED | http_404 |
| ps5_pro | pasoko | FAILED | product_not_listed |
| ps5_pro | sofmap | FAILED | service_unavailable |
| ps5_pro | bookoff | SKIP | not_supported |
| ps5_pro | surugaya | FAILED | site_blocked |
| ps5_pro | tsutaya | SKIP | not_supported |

## 価格変動一覧 (7件)

| 商品 | 店舗 | 前回 | 今回 | 変化率 |
|------|------|------|------|--------|
| switch2 | kaitori_shouten | ¥50,800 | ¥900,000 | ↑1671.7% |
| ps5_pro | kaitori_shouten | ¥134,500 | ¥900,000 | ↑569.1% |
| iphone17pro256 | kaitori_shouten | ¥178,000 | ¥436,000 | ↑144.9% |
| iphone17pm256 | kaitori_shouten | ¥192,000 | ¥436,000 | ↑127.1% |
| iphone17pro512 | kaitori_shouten | ¥214,000 | ¥436,000 | ↑103.7% |
| iphone17pm512 | kaitori_shouten | ¥226,000 | ¥436,000 | ↑92.9% |
| switch2 | geo | ¥45,000 | ¥35,000 | ↓22.2% |

## ⚠️ suspicious_price 一覧 (18件)

| 商品 | 店舗 | 価格 | 理由 | 詳細 |
|------|------|------|------|------|
| iphone17pro256 | kaitori_shouten | ¥436,000 | price_change_over_20pct | 前回¥178,000 → 今回¥436,000（+144.9% 上昇） |
| iphone17pro256 | kaitori_shouten | ¥436,000 | above_genre_max | iphone正常帯¥30,000〜¥400,000の上限超過（¥436,000） |
| iphone17pro512 | kaitori_shouten | ¥436,000 | price_change_over_20pct | 前回¥214,000 → 今回¥436,000（+103.7% 上昇） |
| iphone17pro512 | kaitori_shouten | ¥436,000 | above_genre_max | iphone正常帯¥30,000〜¥400,000の上限超過（¥436,000） |
| iphone17pm256 | kaitori_shouten | ¥436,000 | price_change_over_20pct | 前回¥192,000 → 今回¥436,000（+127.1% 上昇） |
| iphone17pm256 | kaitori_shouten | ¥436,000 | outlier_vs_peer_shops | 他店平均¥190,000から129%乖離（¥436,000） |
| iphone17pm256 | kaitori_shouten | ¥436,000 | above_genre_max | iphone正常帯¥30,000〜¥400,000の上限超過（¥436,000） |
| iphone17pm512 | kaitori_shouten | ¥436,000 | price_change_over_20pct | 前回¥226,000 → 今回¥436,000（+92.9% 上昇） |
| iphone17pm512 | kaitori_shouten | ¥436,000 | above_genre_max | iphone正常帯¥30,000〜¥400,000の上限超過（¥436,000） |
| switch2 | geo | ¥35,000 | price_change_over_20pct | 前回¥45,000 → 今回¥35,000（-22.2% 下落） |
| switch2 | kaitori_shouten | ¥900,000 | price_change_over_20pct | 前回¥50,800 → 今回¥900,000（+1671.7% 上昇） |
| switch2 | kaitori_shouten | ¥900,000 | over_3x_official | 公式¥49,980の18.0倍（¥900,000） |
| switch2 | kaitori_shouten | ¥900,000 | game_console_smartphone_price | ゲーム機(switch2)なのに¥900,000（閾値¥124,950超 / スマホ価格帯の可能性） |
| switch2 | kaitori_shouten | ¥900,000 | above_genre_max | game_console正常帯¥10,000〜¥200,000の上限超過（¥900,000） |
| ps5_pro | kaitori_shouten | ¥900,000 | price_change_over_20pct | 前回¥134,500 → 今回¥900,000（+569.1% 上昇） |
| ps5_pro | kaitori_shouten | ¥900,000 | over_3x_official | 公式¥119,980の7.5倍（¥900,000） |
| ps5_pro | kaitori_shouten | ¥900,000 | game_console_smartphone_price | ゲーム機(ps5_pro)なのに¥900,000（閾値¥299,950超 / スマホ価格帯の可能性） |
| ps5_pro | kaitori_shouten | ¥900,000 | above_genre_max | game_console正常帯¥10,000〜¥200,000の上限超過（¥900,000） |
