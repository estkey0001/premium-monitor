# Retail & Buyback Automation — 品質監査

> 生成: 2026-09-20 18:14 JST / 販売/買取/二次流通の取得品質・正規化・同一性（利益/AI/UI/SaaSロジックは不変）

## カテゴリ別サマリ
| カテゴリ | 観測 | 価格有 | exact | high | fresh | Main昇格可 | 失敗(0円/stale/rejected) |
|---|--:|--:|--:|--:|--:|--:|--:|
| buyback | 143 | 125 | 0 | 0 | 49 | 0 | 18/94/132 |
| resale | 23 | 23 | 0 | 0 | 13 | 0 | 0/10/16 |
| retail | 2 | 2 | 0 | 0 | 0 | 0 | 0/2/2 |

## Main 昇格（high conf + fresh + exact）: 合計 **0** 件
- カテゴリ別: {'buyback': 0, 'resale': 0, 'retail': 0}

## 販売価格 ソース網羅
| source | 観測 | 価格有 | fresh | Main昇格可 |
|---|--:|--:|--:|--:|
| 価格.com | 0 | – | – | no_data |
| ヨドバシ | 0 | – | – | no_data |
| ビックカメラ | 0 | – | – | no_data |
| 楽天市場 | 0 | – | – | no_data |
| Yahoo | 0 | – | – | no_data |
| 楽天市場新品 | 2 | 2 | 0 | 0 |

## 買取価格 ソース網羅
| source | 観測 | 価格有 | fresh | Main昇格可 |
|---|--:|--:|--:|--:|
| マップカメラ | 9 | 9 | 0 | 0 |
| フジヤカメラ | 28 | 28 | 20 | 0 |
| じゃんぱら | 34 | 28 | 6 | 0 |
| イオシス | 20 | 14 | 6 | 0 |
| カメラのキタムラ | 9 | 9 | 0 | 0 |
| ソフマップ | 10 | 8 | 2 | 0 |
| 買取商店 | 17 | 17 | 6 | 0 |
| ゲオ | 8 | 8 | 1 | 0 |
| 買取一丁目 | 4 | 4 | 4 | 0 |
| ネットオフ | 4 | 0 | 4 | 0 |

## 二次流通 ソース網羅
| source | 観測 | 価格有 | fresh | Main昇格可 |
|---|--:|--:|--:|--:|
| eBay sold(新品) | 5 | 5 | 0 | 0 |
| eBay | 0 | – | – | no_data |
| メルカリ未使用 | 5 | 5 | 0 | 0 |
| Mercari sold | 0 | – | – | no_data |
| ヤフオク (新品/未使用落札) | 11 | 11 | 11 | 0 |
| Yahoo Auction sold | 0 | – | – | no_data |
| Amazon JP (新品出品) | 2 | 2 | 2 | 0 |

## 商品同一性 監査
- 容量不一致: 0 / 別型番: 0 / アクセサリー: 32 / 非本体: 32
- condition分布: {'new': 220, 'used': 25}

## 正規化 監査
- price_type付与率: 100% / 送料分離: 100% / ポイント分離: 100% / 下取除外: 88%
- price_type分布: {'buyback_price': 120, 'shop_sale_price': 27, 'overseas_listing_price': 5, 'flea_listing_price': 5, 'flea_sold_price': 11}

## duplicate_price_pattern（同一ソースで複数SKU同額・要確認）
| source | role | price | SKU数 | product_ids |
|---|---|--:|--:|---|
| 買取商店 | sell | ¥436,000 | 4 | prod_iphone17pm_256, prod_iphone17pm_512, prod_iphone17pro_256, prod_iphone17pro_512 |
| フジヤカメラ | sell | ¥200,000 | 3 | prod_a7rv, prod_gr4_hdf, prod_x100vi |
| メーカー公式/定価 | official | ¥214,800 | 2 | prod_iphone17pm_256, prod_iphone17pro_512 |
| ヤフオク (新品/未使用落札) | buy | ¥227,304 | 2 | prod_iphone17pm_256, prod_iphone17pro_256 |
| メーカー公式/定価 | official | ¥259,800 | 3 | prod_gr4, prod_gr4_hdf, prod_gr4_mono |
| メーカー公式/定価 | official | ¥142,800 | 2 | prod_apple_watch_ultra3, prod_iphone17_256 |
| メーカー公式/定価 | official | ¥129,800 | 2 | prod_gr3, prod_ipad_air_m3 |
| フジヤカメラ | sell | ¥213,400 | 2 | prod_gr4_hdf, prod_gr4_mono |
| じゃんぱら | sell | ¥148,000 | 2 | prod_ipad_pro_m4_11, prod_iphone16pro_256 |
| じゃんぱら | sell | ¥78,000 | 2 | prod_ipad_air_m3, prod_mac_mini_m4 |
| じゃんぱら | sell | ¥65,000 | 2 | prod_airpods_max, prod_switch2_mk |
| 買取商店 | sell | ¥900,000 | 2 | prod_ps5_pro, prod_switch2 |

## Freshness 遵守: ✅ OK
- 取得失敗で時刻だけ更新した疑い: 0 件
