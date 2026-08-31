# Execution Intelligence Engine

生成: 2026-08-31 19:12 JST

## Execution Dashboard

- OPEN 75 / CLOSED 90（成功 28）
- Execution Success Rate: **31.1%**
- Prediction Accuracy: 予測 38.7111% vs 実績 31.1%（誤差 7.6pt）
- Notification Accuracy: 通知61 / BUY通知1 / WATCH→BUY 1 / 偽陽性率 21%
- Capital Allocation: 期待 ¥509,900 → 実 ¥0（精度 0.0）

## 補正係数（学習・利益ロジックには不適用）

- Opportunity Score 係数: 1.036
- Success Probability 係数: 0.803
- Risk Score 係数: 1.0
- サンプル数 90（信頼度 high）

## Execution Metrics（カテゴリ別）

| カテゴリ | 件数 | 成功率 | 平均利益 | 平均ROI | 平均保有日数 |
|---|---|---|---|---|---|
| camera | 71 | 39% | ¥5,008 | 3.4% | 1.1831日 |
| game_console | 19 | 0% | ¥-1,500 | -3.0% | 5.0日 |

## Insights — 今週学んだこと TOP10

1. カテゴリ「camera」の成功率が最も高い（39%）
2. RICOH GR IIIx は約3日で売却成立（回転が速い）
3. 成立確率の予測誤差は 7.6pt（概ね良好）
4. Nintendo Switch 2 は薄利/送料負けで失敗（国内薄利ルートは要注意）
5. Fujiya 買取は日次で更新され鮮度が高い（sell側の信頼性◎）
6. 海外sold（eBay）は EBAY_APP_ID 未設定で stale・main昇格の最大ボトルネック
7. 国内完結ルートは買取≥販売で薄利になりやすい（ROI<5%は自動除外）
8. フリマsold（メルカリ/ヤフオク）取得が buy 側の裾を広げ利益ルートを生む
9. manual由来ルートは再現性が低くスコアが伸びない（要 item_url/同条件件数）
10. Apple/GPU は流動性が高く、Coverage拡充の優先度が高い
