# Source Matching Accuracy 監査

> 生成: 2026-10-03 14:40 JST / 商品同一性マッチング精度（利益/AI/UI/SaaS/DQ思想は不変）

## 精度サマリ（目標対比）
| 指標 | 実績 | 目標 |
|---|--:|--:|
| Product Match Accuracy | 100.0% | ≥99% |
| Capacity Match Accuracy | 100.0% | 100% |
| Model Match Accuracy | 100.0% | 100% |
| Condition Match Accuracy | 100.0% | 100% |
| False Main Promotion | 0 | 0 |
| High Risk Duplicates | 2 | (要レビュー) |
| Manual Review Queue | 73 | – |

## ソース精度ランキング（100点）
| # | source | 観測 | score | identity | capacity | model | fresh | main |
|--:|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | 買取商店 | 17 | 81 | 0.35 | 1.00 | 1.00 | 0.35 | 6 |
| 2 | メーカー公式/定価 | 45 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 3 | 買取一丁目 | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 4 | ゲオモバイル | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 5 | セカンドストリート | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 6 | ネットオフ | 4 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 7 | ハードオフ | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 8 | ドスパラ | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 9 | ブックオフ | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 10 | 駿河屋 | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 11 | TSUTAYA | 2 | 75 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |
| 12 | モバイル一番 | 5 | 72 | 0.00 | 1.00 | 1.00 | 0.40 | 0 |
| 13 | イオシス | 20 | 72 | 0.00 | 1.00 | 1.00 | 0.30 | 0 |
| 14 | フジヤカメラ | 25 | 71 | 0.00 | 1.00 | 1.00 | 0.68 | 0 |
| 15 | じゃんぱら | 34 | 71 | 0.00 | 1.00 | 1.00 | 0.18 | 0 |
| 16 | ソフマップ | 10 | 70 | 0.00 | 1.00 | 1.00 | 0.20 | 0 |
| 17 | マップカメラ | 9 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 18 | カメラのキタムラ | 9 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 19 | eBay sold(新品) | 5 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 20 | メルカリ未使用 | 5 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 21 | Amazon新品出品 | 3 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 22 | 楽天市場新品 | 2 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 23 | src_ebay | 6 | 70 | 0.00 | 1.00 | 1.00 | 0.00 | 0 |
| 24 | ゲオ | 8 | 69 | 0.00 | 1.00 | 1.00 | 0.12 | 0 |
| 25 | Amazon JP (新品出品) | 2 | 65 | 0.00 | 1.00 | 1.00 | 1.00 | 0 |

## False Main Promotion 監査（目標 0）
- ✅ False Main Promotion = 0

## 検出された機種/容量 mismatch（隠さず明示・rejected含む）
- なし

## Duplicate Price Pattern（risk別・弾かず要確認）
| risk | source | role | price | SKU数 | 理由 | review |
|---|---|---|--:|--:|---|---|
| high | フジヤカメラ | sell | ¥194,000 | 4 | body_vs_accessory_same_price | pending |
| high | メーカー公式/定価 | official | ¥214,800 | 2 | different_capacity_same_price, pro_vs_promax_same_price | manual_review_required |
| medium | メーカー公式/定価 | official | ¥142,800 | 2 | different_model_same_price | reviewed_true_same_price |
| medium | メーカー公式/定価 | official | ¥129,800 | 2 | different_model_same_price | reviewed_true_same_price |
| medium | じゃんぱら | sell | ¥148,000 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥78,000 | 2 | different_model_same_price | pending |
| medium | じゃんぱら | sell | ¥65,000 | 2 | different_model_same_price | pending |
