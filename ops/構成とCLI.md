# 構成と主要CLIコマンド

`CLAUDE.md` から移した参照資料。コマンドを実行する前に該当箇所を読む。

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

## 新商品・新しいイベントの発見（Phase 27）

```bash
python3 -m src.cli discover                       # Apple 公式（iPhone）と TCG の生成物から候補を作る（CI の手順と同じ）
python3 -m src.cli discover --skip-apple          # Apple を読まない（TCG の生成物だけ）
python3 -m src.cli approve-product-candidate --candidate-id <ID>   # 人の判断を台帳に記録（正本には入れない）
python3 -m src.cli reject-product-candidate --candidate-id <ID>
```

- 候補の台帳は `exports/discovery/product_candidates.json`（新商品）・`event_candidates.json`（告知・イベント）・`latest.json`（集計）。
  CI の生成物のコミットに入る。中身は既存の `product_candidates` の表にも写す
- 正本（`config/products.yaml`・products の表）には自動で入れない。承認しても台帳に記録するだけで、正本への追加は人が
  手で行い、確かめてからコミットする（自動で push しない）
- Apple は購入の一覧から機種のページを見つけ、1回の実行で最大2機種のページを読む（間隔120秒。新しい機種が先）。正本の
  「機種 + 容量」と照合し、正本に無いものを確認待ち（PENDING_REVIEW）にする。色はまとめる
- TCG は新しい取得をしない。日程の無い告知・予約 / 先着 / 再販のタイトルは「告知・日程なし（要確認）」。日程は推測しない
  （画像の文字を読まない）。TCG は利益・今すぐ行動・通知に接続しない
