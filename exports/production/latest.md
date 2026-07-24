# Production Readiness Report

生成: 2026-07-24 15:54 JST

## Overall Score: **81.7 / 100**

| 観点 | 点 |
|---|---|
| Security | 90 |
| Reliability | 85 |
| Performance | 92 |
| Maintainability | 83 |
| Scalability | 66 |
| Operations | 82 |
| Deployment | 70 |
| Data Quality | 85 |
| Monitoring | 84 |
| Recovery | 76 |
| Documentation | 86 |

## 課題サマリ

- Critical: 0 / High: 2 / Medium: 2 / Low: 2

### Critical
- （なし）

### High
- EBAY_APP_ID 未設定 → 海外sold stale・利益ルート限定（要: Secrets設定/運用）
- SaaS 実稼働（実OAuth/Stripe/常時API/マネージドDB）は外部基盤が必要（ROADMAP記載）

### Medium
- item_url率 56%（確認導線/再現性の改善余地）
- Coverage 7カテゴリ（Apple/GPU等の拡充で候補増）

### Low
- 依存監査/未使用コード検出の自動化（pip-audit/vulture 等）未導入
- API のページネーション未実装（現状データ規模では不要）

### 本監査で修正済（Critical/High）

- ✅ accounts.load の account_id 未検証によるパストラバーサル（検証追加で修正済）
- ✅ REST API の入力検証欠如（account_id/budget を400検証で修正済）
- ✅ REST API のセキュリティヘッダ/CORS/レート制限欠如（追加で修正済）

## Security

- コードSecret: 0件 / git履歴clean: True / path traversal対策: True
- API hardening: {'input_validation': True, 'security_headers': True, 'rate_limit': True, 'cors': True, 'account_isolation': True}

## Data Quality（改善優先順）

- stale率 20% / item_url率 56% / EBAY設定 False / Coverage 78
  1. EBAY_APP_ID設定（海外sold fresh化・最大効果）
  2. 買取/フリマ日次更新でstale率低下
  3. item_url個別化
  4. Coverage拡充

## API

- routes: ['/account', '/opportunities', '/notifications', '/capital', '/execution', '/plans', '/health']
- 不足: ['pagination未実装', '認証はゲートウェイ/JWT前提（前段実装要）', 'アクセスログ集約は外部基盤']

## Operations

- {'backup': 'git履歴 + (DB移行後)マネージドDB', 'restore': 'clone+init-db+seed+import+generate', 'runbook': True, 'health': True, 'monitoring': True, 'alert': 'notifications engine（webhook設定で有効）', 'history': True, 'rollback': 'git revert / 直前docs配信'}

## Deployment

- LP/分析はPages稼働・SaaS常駐は外部基盤導入で
- Production構成案: {'recommended': ['Cloud Run', 'Fly.io', 'Railway'], 'docker': '要Dockerfile追加', 'https': 'マネージドで自動', 'secrets': '各PaaSのSecret Manager'}

## Business Readiness

- プラン: ['free', 'pro', 'enterprise'] / 優先: ['実課金(Stripe)接続', '実認証(OAuth)接続', '常駐API+DB', 'Trial/解約フロー']

## Production Checklist

- [x] コードにSecret無し
- [x] パストラバーサル対策
- [x] API 入力検証/ヘッダ/レート制限
- [x] 認証/課金 env gated（キー非埋め込み）
- [x] deploy-check Errors 0（別途）
- [x] Health/Monitoring 稼働
- [x] Runbook/ROADMAP 整備
- [ ] EBAY_APP_ID 設定（データ鮮度）
- [ ] 実OAuth/Stripe/常駐API（外部基盤）

## Go / No-Go

- **LP/分析リリース: GO (LP/分析リリース可)**
- SaaS実稼働: NO-GO (外部基盤導入まで): 実OAuth/Stripe/常駐API/マネージドDB
