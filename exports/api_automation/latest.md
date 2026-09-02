# API Automation Quality Dashboard

> 生成: 2026-09-02 17:36 JST / API自動化（eBay/楽天/Yahoo）の統合状態と品質。利益/AI/DQ思想は不変

- dry_run: True / target: canary / いずれか設定済: False

## API 別ステータス
| API | Configured | Status | Requests | Success | Items | Exact | Rejected | Main | Latency | LastSuccess |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| ebay | not_configured | disabled_kill_switch | 0 | 0% | 0 | 0 | 0 | 0 | 0ms | – |
| rakuten | not_configured | disabled_kill_switch | 0 | 0% | 0 | 0 | 0 | 0 | 0ms | – |
| yahoo | not_configured | disabled_kill_switch | 0 | 0% | 0 | 0 | 0 | 0 | 0ms | – |

## Canary ゲート（Product≥99% / Capacity=100% / False Main=0）
| API | evaluated | product | capacity | false_main | passed |
|---|--:|--:|--:|--:|:--:|
| ebay | 0 | None | None | 0 | None |
| rakuten | 0 | None | None | 0 | None |
| yahoo | 0 | None | None | 0 | None |

## Before / After
- API由来観測: 0 → 0
- API由来 Main昇格可: 0 → 0
> APIキー未設定のため API 由来観測は 0（before==after）。キー投入で自動起動する（Canaryゲート通過が全商品展開の条件）。

## 安全機構
- **kill_switch**: ENABLE_EBAY_API / ENABLE_RAKUTEN_API / ENABLE_YAHOO_API=false で即停止
- **dry_run**: API_DRY_RUN=true で DB Main を書き換えず取得・検証のみ
- **quality_gate**: 全 item が ProductIdentityResolver + price_quality + Main Gate を通過
- **data_origin**: api / fallback / manual を必ず区別（fallback を fresh API 扱いしない）
- **not_configured_handling**: 未設定は NOT_CONFIGURED（graceful skip・架空成功を報告しない）
