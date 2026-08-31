# Real API Canary & Progressive Rollout — Master

> 生成: 2026-08-31 19:12 JST / 実APIキーがある場合のみ実Canary。未設定はPENDING（架空の実行なし）。

## 総合判定: **REAL API AUTOMATION PENDING KEYS**

| API | Configured | Rollout State | Stage | Status | Real API |
|---|---|---|---|---|:--:|
| ebay | not_configured | NOT_CONFIGURED | 0 | PENDING_USER_CONFIGURATION | False |
| rakuten | not_configured | NOT_CONFIGURED | 0 | PENDING_USER_CONFIGURATION | False |
| yahoo | not_configured | NOT_CONFIGURED | 0 | PENDING_USER_CONFIGURATION | False |

- Canary PASS: []
- ROLLOUT_BLOCKED: []
- PENDING_USER_CONFIGURATION: ['ebay', 'rakuten', 'yahoo']

**推奨**: APIキー(EBAY_APP_ID→RAKUTEN_APP_ID→YAHOO_SHOPPING_APP_ID の順)を Secret 登録し、ENABLE_<API>_API=true / API_DRY_RUN=true / <API>_STAGE=0 で実Canary→段階展開。

## 安全機構
- **quality_gate**: 全 item が ProductIdentityResolver + price_quality + Main Gate を通過
- **cross_product_protection**: matched != expected は cross_product → main 不可・manual_review
- **dry_run**: 実Canary は Dry Run 相当（Main DB を書かない）
- **stage_control**: EBAY/RAKUTEN/YAHOO_API_STAGE(0/5/10/25/all) 以上を取得しない
- **rollback**: ENABLE_*_API=false で即停止（fallback/manual を壊さない）
- **no_fake**: 未設定APIを架空成功として報告しない・モックを実API結果としない
