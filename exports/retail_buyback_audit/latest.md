# Retail & Buyback Automation — 品質監査

> 生成: 2026-08-24 12:31 JST / 販売/買取/二次流通の取得品質・正規化・同一性（利益/AI/UI/SaaSロジックは不変）

## カテゴリ別サマリ
| カテゴリ | 観測 | 価格有 | exact | high | fresh | Main昇格可 | 失敗(0円/stale/rejected) |
|---|--:|--:|--:|--:|--:|--:|--:|
| buyback | 953 | 705 | 168 | 168 | 123 | 14 | 248/830/857 |
| resale | 81 | 81 | 0 | 0 | 16 | 0 | 0/65/65 |
| retail | 12 | 12 | 0 | 0 | 2 | 0 | 0/10/10 |

## Main 昇格（high conf + fresh + exact）: 合計 **14** 件
- カテゴリ別: {'buyback': 14, 'resale': 0, 'retail': 0}

## 販売価格 ソース網羅
| source | 観測 | 価格有 | fresh | Main昇格可 |
|---|--:|--:|--:|--:|
| 価格.com | 0 | – | – | no_data |
| ヨドバシ | 0 | – | – | no_data |
| ビックカメラ | 0 | – | – | no_data |
| 楽天市場 | 0 | – | – | no_data |
| Yahoo | 0 | – | – | no_data |
| 楽天市場新品 | 12 | 12 | 2 | 0 |

## 買取価格 ソース網羅
| source | 観測 | 価格有 | fresh | Main昇格可 |
|---|--:|--:|--:|--:|
| マップカメラ | 40 | 40 | 9 | 0 |
| フジヤカメラ | 52 | 52 | 8 | 0 |
| じゃんぱら | 242 | 146 | 34 | 0 |
| イオシス | 174 | 144 | 20 | 5 |
| カメラのキタムラ | 40 | 40 | 9 | 0 |
| ソフマップ | 70 | 44 | 10 | 0 |
| 買取商店 | 146 | 128 | 17 | 6 |
| ゲオ | 77 | 69 | 8 | 1 |
| 買取一丁目 | 68 | 28 | 4 | 0 |
| ネットオフ | 44 | 14 | 4 | 2 |

## 二次流通 ソース網羅
| source | 観測 | 価格有 | fresh | Main昇格可 |
|---|--:|--:|--:|--:|
| eBay sold(新品) | 30 | 30 | 5 | 0 |
| eBay | 0 | – | – | no_data |
| メルカリ未使用 | 30 | 30 | 5 | 0 |
| Mercari sold | 3 | 3 | 3 | 0 |
| ヤフオク (新品/未使用落札) | 10 | 10 | 0 | 0 |
| Yahoo Auction sold | 3 | 3 | 3 | 0 |
| Amazon JP (新品出品) | 5 | 5 | 0 | 0 |

## 商品同一性 監査
- 容量不一致: 0 / 別型番: 0 / アクセサリー: 37 / 非本体: 37
- condition分布: {'new': 1267, 'used': 160}

## 正規化 監査
- price_type付与率: 100% / 送料分離: 100% / ポイント分離: 100% / 下取除外: 98%
- price_type分布: {'buyback_price': 769, 'shop_sale_price': 201, 'overseas_listing_price': 30, 'flea_listing_price': 30, 'flea_sold_price': 16}

## duplicate_price_pattern（同一ソースで複数SKU同額・要確認）
| source | role | price | SKU数 | product_ids |
|---|---|--:|--:|---|
| モバイル一番 | sell | ¥193,500 | 3 | prod_iphone17pm_256, prod_iphone17pm_512, prod_iphone17pro_512 |
| モバイル一番 | sell | ¥195,500 | 3 | prod_iphone17pm_256, prod_iphone17pm_512, prod_iphone17pro_512 |
| モバイル一番 | sell | ¥196,000 | 3 | prod_iphone17pm_256, prod_iphone17pm_512, prod_iphone17pro_512 |
| メーカー公式/定価 | official | ¥214,800 | 2 | prod_iphone17pm_256, prod_iphone17pro_512 |
| モバイル一番 | sell | ¥178,000 | 2 | prod_iphone16pm_256, prod_iphone17pro_256 |
| イオシス | sell | ¥172,000 | 2 | prod_iphone17pm_256, prod_macbook_air_m4_15 |
| ヤフオク (新品/未使用落札) | buy | ¥231,000 | 2 | prod_iphone17pm_256, prod_iphone17pro_256 |
| ヤフオク (新品/未使用落札) | buy | ¥236,544 | 2 | prod_iphone17pm_512, prod_iphone17pro_512 |
| メーカー公式/定価 | official | ¥299,800 | 3 | prod_gr4, prod_gr4_hdf, prod_gr4_mono |
| メーカー公式/定価 | official | ¥142,800 | 2 | prod_apple_watch_ultra3, prod_iphone17_256 |
| メーカー公式/定価 | official | ¥129,800 | 2 | prod_gr3, prod_ipad_air_m3 |
| イオシス | sell | ¥215,000 | 2 | prod_iphone17pro_512, prod_macbook_pro_m4_14 |
| じゃんぱら | sell | ¥148,000 | 2 | prod_ipad_pro_m4_11, prod_iphone16pro_256 |
| じゃんぱら | sell | ¥78,000 | 2 | prod_ipad_air_m3, prod_mac_mini_m4 |
| じゃんぱら | sell | ¥65,000 | 2 | prod_airpods_max, prod_switch2_mk |
| ゲオ | sell | ¥190,000 | 2 | prod_ps5_pro, prod_switch2 |
| フジヤカメラ | sell | ¥213,400 | 2 | prod_gr4_hdf, prod_gr4_mono |

## Freshness 遵守: ✅ OK
- 取得失敗で時刻だけ更新した疑い: 0 件
