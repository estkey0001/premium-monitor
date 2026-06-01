# プレ値商品監視・速報システム

## プロジェクト概要
iPhone / Apple製品 / カメラ / ゲーム機を対象に、公式価格・中古価格・買取価格・海外価格を横断監視し、プレ値候補を検出するシステム。自動購入は一切行わない。情報の収集・比較・通知・LP生成のみ。

## 技術スタック
- Python 3.10+, SQLite, Pydantic, Click, APScheduler
- Streamlit (管理画面), BeautifulSoup/Playwright (Collector)
- GitHub Actions (自動LP更新), GitHub Pages (LP公開)

## ディレクトリ構成
```
config/           設定 (products.yaml, sources.yaml, lp_settings.yaml, fx_rates.yaml)
data/             SQLite DB, CSV (manual_buyback_prices.csv, manual_market_prices.csv)
src/
  cli.py          全CLIコマンド (~2300行)
  scheduler.py    APScheduler (10:00/12:00/18:00 JST買取ジョブ + 60分在庫)
  orchestrator.py 全体オーケストレーション
  collectors/     公式/価格/在庫/買取 Collector
  db/             Database, Repository, migrations/ (001-009)
  models/         Pydantic (product, observation, alert, market_snapshot, buyback_price, beginner_deal等)
  market/         MarketComparator, PremiumDetector, BeginnerDealScanner, ProfitSimulator, BuybackChangeDetector
  pipeline/       Scorer, Dedup, AlertDispatcher, QualityChecker, PrelaunchChecker
  publish/        TemplateGenerator, ReportGenerator
  content/        NoteGenerator, LPGenerator, DailyLPGenerator, LINEMessageGenerator, CommunityMessageGenerator
  notifiers/      Log/Discord/Telegram + routing.py
  jobs/           BuybackPremiumJob (統合ジョブ)
dashboard/        Streamlit (01-19ページ)
scripts/          build_public_lp.py, deploy_check.py
exports/          note_reports/, lp/daily/, line_messages/, community_messages/, simulations/
docs/             GitHub Pages公開用 (index.html, archive/, sitemap.xml, robots.txt)
.github/workflows/daily_lp.yml
```

## 主要CLIコマンド
```bash
# 初期設定
python3 -m src.cli init-db
python3 -m src.cli seed
python3 -m src.cli import-buyback-csv --file data/manual_buyback_prices.csv

# 毎日の運用
python3 -m src.cli run-buyback-premium-check    # 統合ジョブ(10工程一括)
python3 -m src.cli generate-daily-lp --variant A # LP生成
python3 -m src.cli build-public-lp               # public/へビルド
python3 -m src.cli deploy-check-lp               # 公開前チェック
python3 -m src.cli prelaunch-check               # 本番前チェック

# 個別操作
python3 -m src.cli scan-beginner-deals           # 初心者案件スキャン
python3 -m src.cli list-beginner-deals           # 初心者案件一覧
python3 -m src.cli compare-buyback --product iphone17pro256  # 買取比較
python3 -m src.cli simulate-profit --product iphone17pro256  # 利益シミュレーション
python3 -m src.cli validate-data                 # データ整合性チェック
python3 -m src.cli scan-category --category all  # カテゴリ横断スキャン

# Streamlit
streamlit run dashboard/app.py
```

## 現在のフェーズ
**stable-collector-2026-05-27** — コレクター安定版ベースライン確立済み。
- GitHub Actions Run #26505153639: success
- deploy-check: 0 errors / 0 warnings / 271 OK（Actions上）
- collector FAILURES=0 / suspicious_price=0 / low_confidence=0
- kaitori_itchome 全4モデル取得成功（networkidle→domcontentloaded 修正）
- geo/tsutaya を OPTIONAL_SHOPS に追加済み

## 次にやること
1. GA ID / note_url / site_url を設定 → LP再生成
2. コレクター追加候補: geo_mobile（Cloudflare 対策）/ janpara（429 回避策）

## コレクター運用ルール（2026-05-27 確立）

### 優先度分類

| 分類 | 定義 | 対応 |
|------|------|------|
| **required** | LP 品質に直接影響する取得失敗 | **優先修正**（ワークフロー継続・警告） |
| **optional** | サイト制限・未対応で改善困難 | LP を止めない（`OPTIONAL_SHOPS` に追加） |
| **FAILURE** | suspicious_price または low_confidence | **強制対応**（ワークフロー停止） |

### 失敗理由の意味

| 理由 | 意味 | 対応 |
|------|------|------|
| `product_not_listed` | サイトに掲載なし | 正常分類。OPTIONAL_SHOPS 追加を検討 |
| `price_not_found` | ページ取得成功だが価格なし | URL/regex 調査が必要 |
| `rate_limited_429` | IP レートリミット | バックオフ延長 or optional 化 |
| `site_blocked` | Cloudflare 等ブロック | optional 化 |
| `service_unavailable` | サーバー障害 | optional 化 + 復旧待ち |
| `not_supported` | オンライン見積もり非対応 | optional 化（手動価格でカバー） |
| `timeout` | Playwright タイムアウト | domcontentloaded + リトライで対策 |

### 品質チェック体系

```
scripts/check_collector_quality.py  ← 取得品質チェック（FAILURES/WARNINGS/OPT_WARNINGS）
python -m src.cli deploy-check-lp   ← LP 構造チェック（271項目）
python -m src.cli prelaunch-check   ← 公開前最終チェック
```

### OPTIONAL_SHOPS（2026-05-27 現在）

```python
# scripts/check_collector_quality.py および src/content/daily_lp_generator.py
# の _OPTIONAL_SHOP_IDS と同期を保つこと
2ndstreet, bookoff, dosupara, geo, geo_mobile, hardoff,
janpara, pasoko, sofmap, surugaya, tsutaya
```

### LP 警告バー 3 段階

| レベル | 条件 | 表示 |
|--------|------|------|
| `collector-warn-strong` | suspicious_price > 0 または low_confidence > 0 | 🔴 強警告（価格精度に問題） |
| `collector-warn-soft`   | required 店舗の失敗が閾値以上 | 🟡 軟警告（一部取得失敗） |
| `collector-warn-info`   | optional 店舗のみ失敗 | ℹ️ 情報（サイト制限） |

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

## 絶対禁止
- 自動購入・自動応募・CAPTCHA突破・ログイン突破・複数アカウント運用・高頻度アクセス・規約違反行為
