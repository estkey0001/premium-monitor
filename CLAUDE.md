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
Phase 13完了。LP公開準備完了。prelaunch-check PASS (0 errors, 3 warnings)。
Warningsは GA ID / note_url / site_url の未設定（公開後に設定可能）。

## 次にやること
1. Mac上で init-db → seed → import-buyback-csv → run-buyback-premium-check → generate-daily-lp → build-public-lp → prelaunch-check を実行
2. GitHubにpush → GitHub Pages有効化
3. GA ID / note_url / site_url を設定 → LP再生成

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

## 絶対禁止
- 自動購入・自動応募・CAPTCHA突破・ログイン突破・複数アカウント運用・高頻度アクセス・規約違反行為
