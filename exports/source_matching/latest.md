# Source Matching Accuracy 監査

> 生成: 2026-09-19 17:26 JST / 商品同一性マッチング精度（利益/AI/UI/SaaS/DQ思想は不変）

## 精度サマリ（目標対比）
| 指標 | 実績 | 目標 |
|---|--:|--:|
| Product Match Accuracy | 100.0% | ≥99% |
| Capacity Match Accuracy | 100.0% | 100% |
| Model Match Accuracy | 100.0% | 100% |
| Condition Match Accuracy | 100.0% | 100% |
| False Main Promotion | 0 | 0 |
| High Risk Duplicates | 5 | (要レビュー) |
| Manual Review Queue | 84 | – |

## ソース精度ランキング（100点）
| # | source | 観測 | score | identity | capacity | model | fresh | main |
|--:|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | ゲオモバイル | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 2 | セカンドストリート | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 3 | ネットオフ | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 4 | ハードオフ | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 5 | ドスパラ | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 6 | ブックオフ | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 7 | 駿河屋 | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 8 | TSUTAYA | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 9 | メーカー公式/定価 | 45 | 74 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 10 | ヤフオク (新品/未使用落札) | 10 | 73 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 11 | 買取商店 | 17 | 72 | 0.00 | 1.00 | 1.00 | 0.35 | 0 |
| 12 | フジヤカメラ | 28 | 70 | 0.00 | 1.00 | 0.93 | 0.71 | 0 |
| 13 | モバイル一番 | 5 | 70 | 0.00 | 1.00 | 1.00 | 0.40 | 0 |
| 14 | じゃんぱら | 34 | 70 | 0.00 | 1.00 | 1.00 | 0.18 | 0 |
| 15 | イオシス | 20 | 70 | 0.00 | 1.00 | 1.00 | 0.30 | 0 |
| 16 | マップカメラ | 9 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 17 | カメラのキタムラ | 9 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 18 | 買取一丁目 | 4 | 70 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 19 | eBay sold(新品) | 5 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 20 | メルカリ未使用 | 5 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 21 | Amazon新品出品 | 3 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 22 | 楽天市場新品 | 2 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 23 | ソフマップ | 10 | 68 | 0.00 | 1.00 | 1.00 | 0.20 | 0 |
| 24 | src_ebay | 6 | 68 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 25 | Amazon JP (新品出品) | 1 | 65 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 26 | ゲオ | 8 | 64 | 0.00 | 1.00 | 1.00 | 0.12 | 0 |

## False Main Promotion 監査（目標 0）
- ✅ False Main Promotion = 0

## 検出された機種/容量 mismatch（隠さず明示・rejected含む）
| product | source | kinds | rejected | title |
|---|---|---|:--:|---|
| prod_zf | フジヤカメラ | model | ✅ | Zf 40mm f/2 (SE) レンズキット ブラック Nikon 買取金額 新品同様 ￥155,000 良品 ￥154,000 下取は10%UP 新品同様  |
| prod_m11 | フジヤカメラ | model | ✅ | ライカ M11-P Safari 20236 Leica 買取金額 新品同様 ￥1,161,000 良品 ￥1,160,000 下取は10%UP 新品同様 ￥1 |

## Duplicate Price Pattern（risk別・弾かず要確認）
| risk | source | role | price | SKU数 | 理由 | review |
|---|---|---|--:|--:|---|---|
| high | 買取商店 | sell | ¥436,000 | 4 | different_capacity_same_price, pro_vs_promax_same_price | pending |
| high | フジヤカメラ | sell | ¥200,000 | 3 | body_vs_accessory_same_price | pending |
| high | メーカー公式/定価 | official | ¥214,800 | 2 | different_capacity_same_price, body_vs_accessory_same_price, pro_vs_promax_same_price | manual_review_required |
| high | ヤフオク (新品/未使用落札) | buy | ¥227,304 | 2 | different_model_same_price, pro_vs_promax_same_price | pending |
| high | ヤフオク (新品/未使用落札) | buy | ¥250,580 | 2 | different_model_same_price, pro_vs_promax_same_price | pending |
| medium | メーカー公式/定価 | official | ¥259,800 | 3 | different_model_same_price | reviewed_true_same_price |
| medium | メーカー公式/定価 | official | ¥142,800 | 2 | different_model_same_price | reviewed_true_same_price |
| medium | メーカー公式/定価 | official | ¥129,800 | 2 | different_model_same_price | reviewed_true_same_price |
| medium | フジヤカメラ | sell | ¥213,400 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥148,000 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥78,000 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥65,000 | 2 | different_model_same_price | pending |
| medium | 買取商店 | sell | ¥900,000 | 2 | different_model_same_price | pending |
