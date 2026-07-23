# ROADMAP / 運用手順（AI Profit Assistant → SaaS）

本書は SaaS 移行の運用・障害対応・デプロイ・課金・バックアップ手順をまとめる。
AIロジック（利益判定）は変更しない方針。SaaS 層は `src/saas/` に分離。

## 1. アーキテクチャ現状と移行方針

- 現状: バッチ（GitHub Actions 日次）→ 生成物（`exports/`, `docs/`）→ GitHub Pages 静的配信。
- SaaS 層（本フェーズ）: `src/saas/`（subscription / accounts / auth / billing / api）＋ Admin Dashboard。
- **未完（外部基盤が必要）**: 実 OAuth（Google/Apple）・メール認証・Stripe 実課金・常時稼働 API。
  これらは静的ホスティングでは完結しないため、別途バックエンド（例: Cloud Run / Fly.io / VPS +
  HTTPS + セッション/JWT + マネージド DB）を用意して差し込む。コードは env gating で「未設定＝無効」。

### 移行ステップ（推奨順）
1. `src/saas/api.py` をバックエンド（uvicorn 相当の常駐）で公開（現状は stdlib http.server で起動可）。
2. 認証: `GOOGLE_OAUTH_CLIENT_ID` / `APPLE_OAUTH_CLIENT_ID` / `AUTH_EMAIL_ENABLED` を設定し
   `src/saas/auth.py` の `AuthProvider` を実装。API 前段でセッション/JWT により account_id を検証。
3. 課金: Stripe アカウント作成 → `STRIPE_SECRET_KEY` / `STRIPE_PRICE_*` 設定 → webhook を
   `billing.handle_webhook` に接続（署名検証は前段で）。
4. アカウント永続: `data/accounts/*.json` をマネージド DB / KVS に移行（`accounts.py` の load/save を差替）。

## 2. デプロイ手順

- LP/生成物（既存）: `git push` → GitHub Actions `daily_lp.yml` が全生成→`deploy-check`→`prelaunch`→commit/push→Pages 反映。
- 手動再生成: 各 `scripts/generate_*.py` を `PYTHONPATH=.` で実行 → `generate-daily-lp` → `build-public-lp` → `deploy-check-lp`。
- API（新設・任意）: `PORT=8787 python -m src.saas.api`。本番はバックエンド基盤にコンテナデプロイ。
- Admin 集計: `python scripts/generate_admin_dashboard.py` → `exports/admin/latest.json|md`。

## 3. 課金運用（Stripe）

- プラン: Free(¥0) / Pro(月¥1,480・年¥14,800) / Enterprise(月¥9,800・年¥98,000)。Trial 14日（`billing.TRIAL_DAYS`）。
- Price ID は環境変数（`STRIPE_PRICE_PRO_MONTHLY` 等）で注入。コードに秘匿情報を置かない。
- webhook: `checkout.session.completed`→active昇格 / `customer.subscription.deleted`→free降格 /
  `invoice.payment_failed`→past_due。`billing.handle_webhook(event_type, payload)` が account 状態遷移を担当。
- 返金/解約は Stripe ダッシュボード + webhook 反映。手作業での顧客資格情報入力は禁止。

## 4. 障害対応（Runbook）

| 事象 | 検知 | 対応 |
|------|------|------|
| 生成ジョブ失敗 | Actions 失敗通知 / deploy-check Errors | 該当 `generate_*` をローカル再実行しログ確認。`continue-on-error` で他工程は継続 |
| 価格 stale 増加 | Health Score 低下 / stale率>50% Critical | コレクター（買取/海外/フリマ）取得状況を確認、`EBAY_APP_ID` 等の鮮度要因を是正 |
| 通知過多/誤通知 | 通知履歴・偽陽性率 | `generate_notifications.py` の閾値（価格±/ROI±/利益+）とアカウント設定を調整 |
| API 5xx | 監視/ヘルスチェック `/health` | ログ確認、生成物 JSON の整合性、`route()` 例外を確認 |
| 課金不整合 | Stripe ダッシュボード | webhook 再送、`billing.handle_webhook` の状態遷移を確認 |

- ロールバック: 生成物は git 履歴で即時復旧可（`git revert` / 直前コミットの docs を配信）。

## 5. バックアップ

- 対象: `data/*.csv`（手動価格・実績台帳）, `data/accounts/*.json`（アカウント）,
  `exports/**`（生成物・履歴）, `data/premium_monitor.db`（再生成可能・任意）。
- 方法: git 履歴が一次バックアップ。アカウント/課金は DB 移行後にマネージド DB の自動バックアップを利用。
- 復旧: リポジトリ clone + `init-db`/`seed` + CSV インポート + 各 `generate_*` 再実行で復元。

## 6. データ/プライバシー・規約

- 認証情報・カード情報はアプリで保持しない（Stripe / OAuth プロバイダに委譲）。
- スクレイピングは規約遵守（自動大量取得・ログイン突破・CAPTCHA 突破は禁止）。フリマ sold 等は
  手動キュレーション + 検索 URL 方式（`collect_flea_sold_prices.py`）。
- 実行結果台帳（`data/manual_execution_outcomes.json`）はユーザー私的記録。account 単位で分離保存。

## 7. ロードマップ達成状況

```
✅ Beginner → ✅ Pro → ✅ Health → ✅ AI Dashboard → ✅ Action Engine
→ ✅ Notification → ✅ Market Coverage → ✅ Capital Allocation
→ ✅ Execution Intelligence(Learning) → ⭐ SaaS 基盤（本フェーズ・サービス層）
```

- 次の実運用化: バックエンド常駐 + 実 OAuth + Stripe 実課金 + マネージド DB。
- 利益発見率の最大解放は継続課題: **EBAY_APP_ID 設定**（海外sold fresh化）と **Coverage 拡充**。
