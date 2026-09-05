# eBay Real API Canary

> 生成: 2026-09-05 17:22 JST

## Verdict: **EBAY_PENDING_CONFIGURATION**  (real_api_called=False, mode=not_executed)

## Configuration
- EBAY_APP_ID = NOT_CONFIGURED / ENABLE_EBAY_API = false / EBAY_API_STAGE = 0 / API_DRY_RUN = True
- rollout_state = NOT_CONFIGURED

> EBAY_APP_ID 未設定。実APIを呼ばず PENDING。PASS を偽らない。

## Queries
- prod_iphone17pro_256: `iPhone 17 Pro`（除外: case, cover, box only, for parts, replacement, screen protector…）
- prod_iphone17pm_256: `iPhone 17 Pro Max`（除外: case, cover, box only, for parts, replacement, screen protector…）
- prod_gr3x: `GR IIIx`（除外: case, cover, box only, for parts, replacement, screen protector…）
- prod_x100vi: `X100VI`（除外: case, cover, box only, for parts, replacement, screen protector…）

## Safety
- Dry Run Main Mutation = **0**
- DB snapshot before==after: True

## Recommended Next Action
- なし（PASS 時のみ Stage 5 を推奨）
