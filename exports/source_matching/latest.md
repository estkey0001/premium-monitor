# Source Matching Accuracy 監査

> 生成: 2026-09-05 17:22 JST / 商品同一性マッチング精度（利益/AI/UI/SaaS/DQ思想は不変）

## 精度サマリ（目標対比）
| 指標 | 実績 | 目標 |
|---|--:|--:|
| Product Match Accuracy | 100.0% | ≥99% |
| Capacity Match Accuracy | 100.0% | 100% |
| Model Match Accuracy | 100.0% | 100% |
| Condition Match Accuracy | 100.0% | 100% |
| False Main Promotion | 0 | 0 |
| High Risk Duplicates | 3 | (要レビュー) |
| Manual Review Queue | 85 | – |

## ソース精度ランキング（100点）
| # | source | 観測 | score | identity | capacity | model | fresh | main |
|--:|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | ネットオフ | 4 | 100 | 1.00 | 1.00 | 1.00 | 1.00 | 4 |
| 2 | メーカー公式/定価 | 45 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 3 | 買取一丁目 | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 4 | ゲオモバイル | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 5 | セカンドストリート | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 6 | ハードオフ | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 7 | ドスパラ | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 8 | ブックオフ | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 9 | 駿河屋 | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 10 | TSUTAYA | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 11 | ヤフオク (新品/未使用落札) | 11 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 12 | モバイル一番 | 5 | 72 | 0.00 | 1.00 | 1.00 | 0.40 | 0 |
| 13 | 買取商店 | 17 | 72 | 0.00 | 1.00 | 1.00 | 0.35 | 0 |
| 14 | イオシス | 20 | 72 | 0.00 | 1.00 | 1.00 | 0.30 | 0 |
| 15 | ゲオ | 8 | 72 | 0.12 | 1.00 | 1.00 | 0.12 | 1 |
| 16 | じゃんぱら | 34 | 71 | 0.00 | 1.00 | 1.00 | 0.18 | 0 |
| 17 | ソフマップ | 10 | 70 | 0.00 | 1.00 | 1.00 | 0.20 | 0 |
| 18 | マップカメラ | 9 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 19 | カメラのキタムラ | 9 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 20 | eBay sold(新品) | 5 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 21 | メルカリ未使用 | 5 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 22 | Amazon新品出品 | 3 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 23 | 楽天市場新品 | 2 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 24 | src_ebay | 6 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 25 | フジヤカメラ | 28 | 69 | 0.00 | 1.00 | 0.89 | 0.71 | 0 |
| 26 | Amazon JP (新品出品) | 3 | 65 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |

## False Main Promotion 監査（目標 0）
- ✅ False Main Promotion = 0

## 検出された機種/容量 mismatch（隠さず明示・rejected含む）
| product | source | kinds | rejected | title |
|---|---|---|:--:|---|
| prod_zf | フジヤカメラ | model | ✅ | Zf 40mm f/2 (SE) レンズキット ブラック Nikon 買取金額 新品同様 ￥158,000 良品 ￥157,000 下取は10%UP 新品同様  |
| prod_q3 | フジヤカメラ | model | ✅ | ライカ Q3 モノクローム 19201 Leica 買取金額 新品同様 ￥869,000 良品 ￥868,000 下取は10%UP 新品同様 ￥955,900  |
| prod_m11 | フジヤカメラ | model | ✅ | ライカ M11-P Safari 20236 Leica 買取金額 新品同様 ￥1,161,000 良品 ￥1,160,000 下取は10%UP 新品同様 ￥1 |

## Duplicate Price Pattern（risk別・弾かず要確認）
| risk | source | role | price | SKU数 | 理由 | review |
|---|---|---|--:|--:|---|---|
| high | メーカー公式/定価 | official | ¥214,800 | 2 | different_capacity_same_price, pro_vs_promax_same_price | manual_review_required |
| high | ヤフオク (新品/未使用落札) | buy | ¥221,529 | 2 | different_model_same_price, pro_vs_promax_same_price | pending |
| high | ヤフオク (新品/未使用落札) | buy | ¥245,080 | 2 | different_model_same_price, pro_vs_promax_same_price | pending |
| medium | メーカー公式/定価 | official | ¥299,800 | 3 | different_model_same_price | reviewed_true_same_price |
| medium | メーカー公式/定価 | official | ¥142,800 | 2 | different_model_same_price | reviewed_true_same_price |
| medium | メーカー公式/定価 | official | ¥129,800 | 2 | different_model_same_price | reviewed_true_same_price |
| medium | フジヤカメラ | sell | ¥200,000 | 2 | different_model_same_price | pending |
| medium | フジヤカメラ | sell | ¥213,400 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥148,000 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥78,000 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥65,000 | 2 | different_model_same_price | pending |
