# Secrets と外部 API の設定

通知・海外価格・公式 API の有効化手順。`CLAUDE.md` から移した。

## 通知 Secrets 設定（Discord / Telegram）

Daily LP Update ワークフローの結果通知を有効にするには、GitHub リポジトリの
Settings → Secrets and variables → Actions に以下のシークレットを設定してください。

| Secret 名 | 説明 | 必須 |
|-----------|------|------|
| `DISCORD_WEBHOOK_URL` | Discord webhook URL | どちらか一方でOK |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | どちらか一方でOK |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | TELEGRAM_BOT_TOKEN と対で必要 |

- どちらか一方だけでも通知可能
- 未設定の場合は自動でスキップ（エラーにならない）
- 通知スクリプト: `scripts/notify_workflow_result.py`（`--dry-run` オプションで動作確認可能）


## 海外価格 API 設定（EBAY_APP_ID）

eBay の正確な成約相場（Finding API）を使うには `EBAY_APP_ID` を設定してください。
未設定の場合は HTML フォールバックのみとなり、価格が **stale 化しやすく**、
ランキング/Pro/せどりの**主計算からは stale 海外価格が除外**されます
（`scripts/update_overseas_prices.py` が起動時に強警告 `STRONG WARNING ... api_not_configured` を出力）。

### 取得手順
1. https://developer.ebay.com/ にサインイン（無料）
2. 「Application Keys」から **Production** の App ID（Client ID）を発行
3. GitHub: Settings → Secrets and variables → Actions に登録

| Secret 名 | 説明 | 必須 |
|-----------|------|------|
| `EBAY_APP_ID` | eBay Finding API の App ID（Client ID）| 任意（未設定でも動作・精度低下）|
| `EBAY_CLIENT_ID` | `EBAY_APP_ID` の別名（どちらか一方でOK）| 任意 |

### ローカル実行
```bash
export EBAY_APP_ID="YourAppId-xxxx-xxxx-xxxx-xxxx"
python scripts/update_overseas_prices.py --verbose
```
- 未設定でも `--manual-only` / `--skip-ebay` でローカル動作可能。
- 設定すると eBay 成約相場が fresh 化し、Pro/せどりの海外売却候補の精度が向上します。


## 自動取得の拡張（2026-07-23）— キー投入で自動起動

「できるだけ自動取得」方針。以下は**Secret を登録するだけで自動化が起動**する設計。
未設定でも動作（既存のHTMLフォールバック/手動キュレーションが働く）。

### 公式定価コレクター（キー不要・実装済み）
- `apple/ricoh/fujifilm` に加え `canon/nikon/sony` を追加（`src/collectors/official/`）。
- 日次CIで `python -m src.cli collect-official` が走り公式定価を自動更新。
- **canon/nikon/sony を実際に収集するには** `product_source_config` に各商品の
  公式ストア `target_url` を登録する必要がある（未登録の商品は安全にスキップ）。
- robots.txt 準拠・`rate_limit_sec` 遵守で低頻度アクセス。

### 公式API統合（env-gated・キー投入で自動有効化）
`src/collectors/api/official_apis.py`。GitHub Secrets に登録すると自動でAPI優先に切替:

| Secret 名 | 用途 | 効果 |
|-----------|------|------|
| `EBAY_APP_ID` | eBay Finding API | 海外sold相場が fresh 化（Data Quality +25pt見込み・最優先）|
| `RAKUTEN_APP_ID` | 楽天 Ichiba Item Search API | 楽天新品価格をHTMLでなくAPIで取得（IPブロック回避）|
| `RAKUTEN_AFFILIATE_ID` | 楽天アフィリ（任意）| 任意 |
| `YAHOO_SHOPPING_APP_ID` | Yahoo!ショッピング API | 新品ショッピング価格（※落札soldとは別種・混在させない）|

### 自動化できない領域（ToS・正直な上限）
- **メルカリ / ラクマ**: スクレイピング禁止・公式価格APIなし → **手動キュレーション継続**が正しい設計。
- **クラウドIPブロック**: GitHub Actions のIPは多くの日本の小売サイトにブロックされる（成功率が上がらない主因）。回避はセルフホストRunner/プロキシ等のインフラ判断が必要（コードだけでは解決しない）。

