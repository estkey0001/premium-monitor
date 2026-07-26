# Execution Intelligence Engine

生成: 2026-07-26 15:42 JST

## Execution Dashboard

- OPEN 10 / CLOSED 17（成功 6）
- Execution Success Rate: **35.3%**
- Prediction Accuracy: 予測 39.8824% vs 実績 35.3%（誤差 4.6pt）
- Notification Accuracy: 通知22 / BUY通知1 / WATCH→BUY 1 / 偽陽性率 24%
- Capital Allocation: 期待 ¥365,200 → 実 ¥0（精度 0.0）

## 補正係数（学習・利益ロジックには不適用）

- Opportunity Score 係数: 0.984
- Success Probability 係数: 0.885
- Risk Score 係数: 1.0
- サンプル数 17（信頼度 medium）

## Execution Metrics（カテゴリ別）

| カテゴリ | 件数 | 成功率 | 平均利益 | 平均ROI | 平均保有日数 |
|---|---|---|---|---|---|
| camera | 13 | 46% | ¥5,862 | 3.9% | 1.3846日 |
| game_console | 4 | 0% | ¥-1,500 | -3.0% | 5.0日 |

## Insights — 今週学んだこと TOP10

1. カテゴリ「camera」の成功率が最も高い（46%）
2. RICOH GR IIIx は約3日で売却成立（回転が速い）
3. 成立確率の予測誤差は 4.6pt（概ね良好）
4. Nintendo Switch 2 は薄利/送料負けで失敗（国内薄利ルートは要注意）
5. Fujiya 買取は日次で更新され鮮度が高い（sell側の信頼性◎）
6. 海外sold（eBay）は EBAY_APP_ID 未設定で stale・main昇格の最大ボトルネック
7. 国内完結ルートは買取≥販売で薄利になりやすい（ROI<5%は自動除外）
8. フリマsold（メルカリ/ヤフオク）取得が buy 側の裾を広げ利益ルートを生む
9. manual由来ルートは再現性が低くスコアが伸びない（要 item_url/同条件件数）
10. Apple/GPU は流動性が高く、Coverage拡充の優先度が高い
