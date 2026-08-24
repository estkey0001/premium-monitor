# Source Matching Accuracy 監査

> 生成: 2026-08-24 12:31 JST / 商品同一性マッチング精度（利益/AI/UI/SaaS/DQ思想は不変）

## 精度サマリ（目標対比）
| 指標 | 実績 | 目標 |
|---|--:|--:|
| Product Match Accuracy | 100.0% | ≥99% |
| Capacity Match Accuracy | 100.0% | 100% |
| Model Match Accuracy | 100.0% | 100% |
| Condition Match Accuracy | 100.0% | 100% |
| False Main Promotion | 0 | 0 |
| High Risk Duplicates | 8 | (要レビュー) |
| Manual Review Queue | 464 | – |

## ソース精度ランキング（100点）
| # | source | 観測 | score | identity | capacity | model | fresh | main |
|--:|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | 買取商店 | 146 | 84 | 0.53 | 1.00 | 1.00 | 0.12 | 6 |
| 2 | イオシス | 174 | 78 | 0.32 | 1.00 | 1.00 | 0.12 | 5 |
| 3 | ネットオフ | 44 | 78 | 0.32 | 1.00 | 1.00 | 0.09 | 2 |
| 4 | メーカー公式/定価 | 45 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 5 | Yahoo Auction sold | 3 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 6 | Mercari sold | 3 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 7 | src_ebay | 6 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 8 | src_bhphoto | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 9 | ゲオ | 77 | 73 | 0.16 | 1.00 | 1.00 | 0.10 | 1 |
| 10 | フジヤカメラ | 52 | 73 | 0.17 | 1.00 | 0.98 | 0.15 | 0 |
| 11 | じゃんぱら | 242 | 71 | 0.00 | 1.00 | 1.00 | 0.14 | 0 |
| 12 | ソフマップ | 70 | 71 | 0.00 | 1.00 | 1.00 | 0.14 | 0 |
| 13 | eBay sold(新品) | 30 | 71 | 0.00 | 1.00 | 1.00 | 0.17 | 0 |
| 14 | メルカリ未使用 | 30 | 71 | 0.00 | 1.00 | 1.00 | 0.17 | 0 |
| 15 | Amazon新品出品 | 18 | 71 | 0.00 | 1.00 | 1.00 | 0.17 | 0 |
| 16 | 楽天市場新品 | 12 | 71 | 0.00 | 1.00 | 1.00 | 0.17 | 0 |
| 17 | モバイル一番 | 90 | 70 | 0.00 | 1.00 | 1.00 | 0.09 | 0 |
| 18 | 買取一丁目 | 68 | 70 | 0.00 | 1.00 | 1.00 | 0.06 | 0 |
| 19 | ブックオフ | 26 | 70 | 0.00 | 1.00 | 1.00 | 0.08 | 0 |
| 20 | 駿河屋 | 26 | 70 | 0.00 | 1.00 | 1.00 | 0.08 | 0 |
| 21 | TSUTAYA | 26 | 70 | 0.00 | 1.00 | 1.00 | 0.08 | 0 |
| 22 | ゲオモバイル | 44 | 70 | 0.00 | 1.00 | 1.00 | 0.09 | 0 |
| 23 | セカンドストリート | 44 | 70 | 0.00 | 1.00 | 1.00 | 0.09 | 0 |
| 24 | ハードオフ | 22 | 70 | 0.00 | 1.00 | 1.00 | 0.09 | 0 |
| 25 | ドスパラ | 22 | 70 | 0.00 | 1.00 | 1.00 | 0.09 | 0 |
| 26 | パソコン工房 | 10 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 27 | ヤフオク (新品/未使用落札) | 10 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 28 | マップカメラ | 40 | 69 | 0.00 | 1.00 | 1.00 | 0.23 | 0 |
| 29 | カメラのキタムラ | 40 | 69 | 0.00 | 1.00 | 1.00 | 0.23 | 0 |
| 30 | Amazon JP (新品出品) | 5 | 66 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |

## False Main Promotion 監査（目標 0）
- ✅ False Main Promotion = 0

## 検出された機種/容量 mismatch（隠さず明示・rejected含む）
| product | source | kinds | rejected | title |
|---|---|---|:--:|---|
| prod_m11 | フジヤカメラ | model | ✅ | ライカ M11-P メタルグレーペイント 20072 Leica 基準査定額 新品同様 ￥960,000 良品 ￥959,000 買取のみ10%UP 新品同様  |

## Duplicate Price Pattern（risk別・弾かず要確認）
| risk | source | role | price | SKU数 | 理由 | review |
|---|---|---|--:|--:|---|---|
| high | モバイル一番 | sell | ¥193,500 | 3 | different_capacity_same_price, pro_vs_promax_same_price | pending |
| high | モバイル一番 | sell | ¥195,500 | 3 | different_capacity_same_price, pro_vs_promax_same_price | pending |
| high | モバイル一番 | sell | ¥196,000 | 3 | different_capacity_same_price, pro_vs_promax_same_price | pending |
| high | メーカー公式/定価 | official | ¥214,800 | 2 | different_capacity_same_price, pro_vs_promax_same_price | manual_review_required |
| high | モバイル一番 | sell | ¥178,000 | 2 | different_model_same_price, pro_vs_promax_same_price | pending |
| high | イオシス | sell | ¥172,000 | 2 | different_model_same_price, pro_vs_promax_same_price | pending |
| high | ヤフオク (新品/未使用落札) | buy | ¥231,000 | 2 | different_model_same_price, pro_vs_promax_same_price | pending |
| high | ヤフオク (新品/未使用落札) | buy | ¥236,544 | 2 | different_model_same_price, pro_vs_promax_same_price | pending |
| medium | メーカー公式/定価 | official | ¥299,800 | 3 | different_model_same_price | reviewed_true_same_price |
| medium | メーカー公式/定価 | official | ¥142,800 | 2 | different_model_same_price | reviewed_true_same_price |
| medium | メーカー公式/定価 | official | ¥129,800 | 2 | different_model_same_price | reviewed_true_same_price |
| medium | イオシス | sell | ¥215,000 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥148,000 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥78,000 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥65,000 | 2 | different_model_same_price | pending |
| medium | ゲオ | sell | ¥190,000 | 2 | different_model_same_price | pending |
| medium | フジヤカメラ | sell | ¥213,400 | 2 | different_model_same_price | pending |
