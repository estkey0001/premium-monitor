# API Canary（simulated）

> 生成: 2026-08-30 18:51 JST / API Canary（品質ゲートの機能検証）。利益/AI/DQ思想は不変

- mode: **simulated** / real_api_called: **False**

> APIキー未設定のため fixture による simulated 実行。実API取得は collect_api_prices が担い、キー投入後に実Canaryへ移行する。架空の実API成功としては報告しない。

## Canary 結果（品質ゲートの機能検証）
| API | Configured | Enabled | Product | Capacity | Model | False Main | Rollout |
|---|---|:--:|--:|--:|--:|--:|---|
| ebay | not_configured | False | 100% | 100% | 100% | 0 | READY |
| rakuten | not_configured | False | 100% | 100% | 100% | 0 | READY |
| yahoo | not_configured | False | 100% | 100% | 100% | 0 | READY |

## 除外内訳（品質ゲートが誤マッチを弾いた件数）
| API | evaluated | accepted | accessory | parts | model_mm | capacity_mm |
|---|--:|--:|--:|--:|--:|--:|
| ebay | 11 | 5 | 2 | 1 | 3 | 0 |
| rakuten | 11 | 5 | 2 | 1 | 3 | 0 |
| yahoo | 11 | 5 | 2 | 1 | 3 | 0 |

**All Pass: True**
