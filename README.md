# プレ値商品監視・速報システム

iPhone / Apple製品 / カメラ / ゲーム機 / PC / ガジェットを対象に、公式価格・中古価格・買取価格・海外価格を横断監視し、プレ値候補を検出するシステムです。

自動購入・自動応募は一切行いません。情報の収集・比較・通知・投稿素材の生成のみを行います。

## セットアップ

### 依存パッケージのインストール

```bash
cd premium-monitor
pip install -r requirements.txt
```

Playwright（JS描画が必要なサイト用、オプション）:

```bash
pip install playwright
playwright install chromium
```

### データベース初期化

```bash
python -m src.cli init-db
python -m src.cli seed
```

### 環境変数（オプション）

`.env` ファイルに通知先を設定:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### CSVインポート

手動収集した価格データを投入:

```bash
python -m src.cli import-market-csv --file data/manual_market_prices.csv
```

### Streamlit管理画面の起動

```bash
cd premium-monitor
streamlit run dashboard/app.py
```

## 毎日12時更新（LP公開運用）

### ワンコマンド更新

```bash
python3 -m src.cli daily-lp-update
```

以下を自動で順番に実行します:

1. リンク検証（validate-price-links）
2. 買取価格CSVインポート
3. 市場価格CSVインポート
4. 買取+プレ値統合ジョブ
5. LP生成（バリアントA）
6. docs/ ビルド
7. デプロイチェック（22項目）
8. 本番前チェック

### 更新後の公開手順

実行結果を確認してから手動でpushしてください:

```bash
# 内容確認
python3 -m src.cli daily-lp-update

# 問題なければ手動でgit push
git add docs/ exports/lp/daily/
git commit -m "Update daily LP $(date +%Y-%m-%d)"
git push
```

> **注意**: `daily-lp-update` は自動で git push しません。結果サマリを確認してから手動で push してください。

### リンク検証スキップ（高速化）

```bash
python3 -m src.cli daily-lp-update --skip-link-check
```

### バリアント変更

```bash
python3 -m src.cli daily-lp-update --variant B
```

---

## 日常運用

### 全体を1回実行

```bash
python -m src.cli run-once
```

公式価格取得 → 在庫チェック → 価格取得 → スコアリング → 通知 → 新製品スキャン を一括実行します。

### 常駐スケジューラ

```bash
python -m src.cli start-scheduler
```

在庫チェック(15分)、価格チェック(60分)、スコアリング(15分)、通知(5分)、新製品スキャン(3時間) を自動実行します。

### スケジューラ状態確認

```bash
python -m src.cli scheduler-status
```

### カテゴリ横断スキャン

```bash
python -m src.cli scan-category --category all
python -m src.cli scan-category --category camera
python -m src.cli scan-category --category apple
python -m src.cli scan-category --category game
```

### 市場比較

```bash
python -m src.cli compare-market --product iphone17pro
python -m src.cli compare-market --product gr4
python -m src.cli compare-market --user-level beginner
python -m src.cli compare-market --user-level advanced
```

### 初心者向け / 上級者向け候補一覧

```bash
python -m src.cli list-beginner-candidates
python -m src.cli list-advanced-candidates
```

### 投稿テンプレート生成

```bash
python -m src.cli generate-posts
python -m src.cli list-publish-queue
python -m src.cli show-publish-item --item-id <ID>
python -m src.cli approve-publish-item --item-id <ID>
```

### 週間レポート

```bash
python -m src.cli generate-weekly-report
```

## 毎日の運用フロー

朝10時前後に以下を実行します（GitHub Actions で自動化済み）:

```bash
# 1. 買取価格CSVを最新に更新（手動）
#    data/manual_buyback_prices.csv を編集

# 2. 買取価格をインポート
python -m src.cli import-buyback-csv --file data/manual_buyback_prices.csv

# 3. 買取更新 + プレ値計算（統合ジョブ: 全10工程一括）
python -m src.cli run-buyback-premium-check

# 4. LP生成
python -m src.cli generate-daily-lp --variant A

# 5. public/ にビルド
python -m src.cli build-public-lp

# 6. デプロイチェック
python -m src.cli deploy-check-lp

# 7. push（GitHub Actions使用時は自動）
git add . && git commit -m "Daily update" && git push
```

GitHub Actions が 10:15 / 12:15 / 18:15 JST に自動実行するため、手動実行は初回や臨時更新時のみです。

## LP公開フロー（初回）

```bash
# 1. LP生成
python -m src.cli generate-daily-lp --variant A

# 2. A/B/C 全バリアント生成
python -m src.cli generate-daily-lp --variant B
python -m src.cli generate-daily-lp --variant C

# 3. public/ にビルド
python -m src.cli build-public-lp

# 4. デプロイチェック
python -m src.cli deploy-check-lp

# 5. 本番前チェック
python -m src.cli prelaunch-check

# 6. GitHubにpush
git add . && git commit -m "Launch LP" && git push

# 7. GitHub Pages URLを開いて確認
# 8. GAリアルタイムでPV確認（GA設定済みの場合）
# 9. noteリンククリック確認
```

## A/Bテスト運用

`config/lp_settings.yaml` の `headline_variant` を切り替えます:

```yaml
headline_variant: "A"  # Week 1
# headline_variant: "B"  # Week 2
# headline_variant: "C"  # Week 3
```

切替後に LP を再生成して push:

```bash
python -m src.cli generate-daily-lp --variant B
python -m src.cli build-public-lp
git add . && git commit -m "Switch to variant B" && git push
```

GA で各週の PV・note CTR を比較し、最も効果的なヘッドラインを採用してください。

## データ更新

### manual_market_prices.csv の使い方

`data/manual_market_prices.csv` にスクレイピング困難なサイトの価格を手入力できます。

```csv
product_alias,source,price_type,price,currency,condition,is_sold,url,observed_at
iphone17pro256,mobile_ichiban,buyback,208000,JPY,new,false,https://...,2026-05-18T12:00:00
x100vi,ebay,overseas,3200,USD,new,true,https://...,2026-05-18T10:00:00
```

product_alias は `gr4`, `x100vi`, `iphone17pro256`, `ps5_pro`, `switch2` 等。price_type は `overseas`, `used`, `buyback`, `retail` のいずれか。currency が JPY 以外の場合は `fx_rates.yaml` のレートで自動換算されます。

```bash
python -m src.cli import-market-csv --file data/manual_market_prices.csv
```

### fx_rates.yaml の更新方法

`config/fx_rates.yaml` の `fx_rates.USD_JPY` 等を最新レートに更新してください。海外価格のJPY換算に使用されます。

### product_candidates の承認方法

```bash
python -m src.cli list-product-candidates
python -m src.cli approve-product-candidate --candidate-id <ID>
python -m src.cli reject-product-candidate --candidate-id <ID>
```

### beginner / advanced 分類の確認方法

```bash
python -m src.cli list-beginner-candidates
python -m src.cli list-advanced-candidates
python -m src.cli compare-market --user-level beginner
```

Streamlit管理画面のプレ値候補一覧ページでもフィルタ・ソートが可能です。

## 品質チェック (Phase 8)

### データ整合性チェック

```bash
python -m src.cli validate-data
```

商品マスタ、FK整合性、価格異常値、海外価格未換算、user_level欠損などを検証します。

### スコア再計算

```bash
python -m src.cli recalc-market-scores
python -m src.cli recalc-market-scores --fix-downgrade
```

既存の market_snapshots のスコアを再計算します。`--fix-downgrade` を付けると、品質不足の beginner_easy を beginner_watch に降格します。

### 投稿テンプレート安全チェック

```bash
python -m src.cli validate-publish-text
```

publish_queue 内の禁止表現（「確実に儲かる」「誰でも稼げる」等）を検出します。

### Streamlit品質チェック画面

管理画面の「品質チェック」ページで、上記すべてのチェック結果をまとめて確認できます。

## LP公開 (Phase 11)

### 日次LP生成

```bash
python -m src.cli generate-daily-lp
python -m src.cli build-public-lp
python -m src.cli deploy-check-lp
```

LP は `exports/lp/daily/index.html` に生成され、`build-public-lp` で `public/` にコピーされます。`deploy-check-lp` で禁止表現・免責・日付等を検証してからデプロイしてください。

### 初回公開手順

1. GitHubにリポジトリをpush
2. Settings → Actions → General → Workflow permissions を「Read and write permissions」に変更して Save
3. Settings → Pages → Source を「Deploy from a branch」に設定
4. Branch を `main`、フォルダを `/public` に設定して Save
5. ローカルで以下を実行:

```bash
python -m src.cli init-db
python -m src.cli seed
python -m src.cli import-buyback-csv --file data/manual_buyback_prices.csv
python -m src.cli run-buyback-premium-check
python -m src.cli generate-daily-lp
python -m src.cli build-public-lp
python -m src.cli deploy-check-lp
```

6. `public/index.html` をブラウザで開いて表示を確認
7. `git add . && git commit && git push` でデプロイ
8. GitHub Pages URL（ `https://<user>.github.io/<repo>/` ）を開いて公開を確認
9. note記事ができたら `config/lp_settings.yaml` の `note_url` を設定し、再ビルド:

```bash
python -m src.cli generate-daily-lp
python -m src.cli build-public-lp
python -m src.cli deploy-check-lp
git add . && git commit -m "Set note URL" && git push
```

以降は GitHub Actions が毎日 10:15 / 12:15 / 18:15 JST に自動更新します。

必要な Secrets（Settings → Secrets → Actions）:

- `DISCORD_WEBHOOK_URL`（任意）
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`（任意）

### Analytics 設定

`config/lp_settings.yaml` の `analytics` セクションにIDを設定するとLP内にタグが自動出力されます:

```yaml
analytics:
  google_analytics_id: "G-XXXXXXXXXX"
  meta_pixel_id: "1234567890"
```

LP内のリンクには `data-track` 属性が付与されており、GA/Meta Pixel でクリックイベントを自動計測します。

### note URL の設定

```yaml
note_url: "https://note.com/your_account/..."
enable_note_cta: true
```

設定後に `generate-daily-lp` を再実行するとLP内にCTAボタンが反映されます。

### LINE / Telegram を後から有効にする

```yaml
enable_line_cta: true
line_url: "https://lin.ee/xxxxx"
enable_telegram_cta: true
telegram_url: "https://t.me/xxxxx"
```

## 禁止事項

以下は実装していません。実装しないでください。

- 自動購入・自動応募
- CAPTCHA突破・ログイン突破
- 複数アカウント運用
- 高頻度アクセス
- 規約違反行為

監視・記録・比較・通知・投稿下書き作成のみを行います。

## ディレクトリ構成

```
premium-monitor/
  config/          設定ファイル (products.yaml, sources.yaml, fx_rates.yaml 等)
  dashboard/       Streamlit管理画面
  data/            SQLite DB, CSV, ログ
  src/
    cli.py         CLIエントリーポイント
    collectors/    各サイトのCollector (公式/価格/在庫/買取)
    db/            Database, Repository, Migrations
    market/        MarketComparator, PremiumDetector, CategoryScanner, CSVImporter
    models/        Pydanticモデル
    notifiers/     Log / Discord / Telegram 通知
    pipeline/      Scorer, Dedup, AlertDispatcher, QualityChecker
    publish/       TemplateGenerator, ReportGenerator
    orchestrator.py  全体オーケストレーション
    scheduler.py     APScheduler常駐
```
