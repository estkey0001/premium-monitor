# System Overview — プレ値商品監視・速報システム（premium-monitor）

## 0. システムの目的と安全制約

iPhone / Apple製品 / カメラ / ゲーム機を対象に、**公式価格・中古価格・買取価格・海外価格**を横断監視し、
プレ値（プレミア価格）候補を検出・比較・通知し、**LP（ランディングページ）を自動生成**するシステム。

> **絶対禁止（CLAUDE.md由来）**: 自動購入・自動応募・CAPTCHA突破・ログイン突破・複数アカウント運用・高頻度アクセス・規約違反行為。
> 本システムは **情報の収集・比較・通知・LP生成のみ**を行う。

## 1. システム全体構成

```
config/           設定 (products.yaml, sources.yaml, genres.yaml, lp_settings.yaml, fx_rates.yaml ...)
data/             SQLite DB (premium_monitor.db) + 手動CSV (manual_buyback/market/sale_prices.csv)
src/
  cli.py          全CLIコマンド (~2300行)
  scheduler.py    APScheduler (買取ジョブ + 在庫)
  orchestrator.py 全体オーケストレーション
  collectors/     公式 / price / stock / buyback / overseas Collector
  db/             Database, Repository, migrations/
  models/         Pydantic モデル
  market/         MarketComparator, PremiumDetector, BeginnerDealScanner, ProfitSimulator
  pipeline/       Scorer, Dedup, AlertDispatcher, QualityChecker, PrelaunchChecker
  content/        DailyLPGenerator, NoteGenerator, LINE/Community MessageGenerator
  notifiers/      Log / Discord / Telegram + routing
scripts/          収集・レポート生成・品質チェック・デプロイチェック
exports/          生成物 (lp/daily, ranking_report, data_quality_report, sedori_routes_report ...)
docs/             GitHub Pages 公開用
.github/workflows/daily_lp.yml   日次自動更新
```

```mermaid
graph TB
  subgraph Input[入力層]
    CFG[config/*.yaml<br/>products/sources/genres]
    CSV[data/manual_*.csv<br/>手動価格]
    WEB[外部サイト<br/>富士屋/eBay/各買取店]
  end
  subgraph Core[処理層 src/]
    COL[collectors/<br/>公式・価格・買取・海外]
    MKT[market/<br/>比較・プレ値検出・利益試算]
    PIPE[pipeline/<br/>scorer・dedup・quality・prelaunch]
    DB[(SQLite<br/>premium_monitor.db)]
  end
  subgraph Out[出力層 exports/ docs/]
    LP[Daily LP]
    RANK[ranking_report]
    SED[sedori_routes_report]
    DQ[data_quality_report]
    NOTIF[Discord/Telegram通知]
    PAGES[GitHub Pages]
  end
  CFG --> COL
  CSV --> DB
  WEB --> COL
  COL --> DB
  DB --> MKT --> DB
  DB --> PIPE
  PIPE --> LP & RANK & SED & DQ
  LP --> PAGES
  PIPE --> NOTIF
```

## 2. データフロー（全体）

```mermaid
flowchart LR
  A[init-db / seed] --> B[自動スクレイピング<br/>buyback / camera / overseas]
  B --> C[手動CSVインポート<br/>buyback / market / sale]
  C --> D[buyback-premium-check<br/>統合ジョブ]
  D --> E[sedori-routes / primary-to-secondary]
  E --> F[レポート生成<br/>ranking / sedori / data_quality]
  F --> G[Daily LP 生成]
  G --> H[build-public-lp]
  H --> I[deploy-check / prelaunch-check]
  I --> J[commit & push → GitHub Pages]
  D --> K[通知 Discord/Telegram]
```

## 3. スクレイピングフロー（買取・カメラ）

中核は `scripts/update_camera_buyback.py`（富士屋カメラ買取）。

```mermaid
flowchart TD
  S[CAMERA_MODELS 20機種定義] --> KW[検索キーワード生成<br/>FUJIYA_KEYWORD_VARIANTS]
  KW --> REQ[requests でページ取得]
  REQ -->|失敗/JS必須| PW[Playwright chromium<br/>headless フォールバック]
  REQ --> DOM[DOM probe<br/>_PW_DOM_PROBE_JS]
  PW --> DOM
  DOM --> CTX{買取コンテキスト?<br/>基準査定額/買取申込}
  CTX -->|No| REJ1[却下: not_buyback_context<br/>= 販売価格汚染防止]
  CTX -->|Yes| TXT[item_text 抽出<br/>親7階層を遡りブランド語特定]
  TXT --> MATCH{strict_model_match<br/>require_any/exclude}
  MATCH -->|不一致| REJ2[却下: model_mismatch]
  MATCH -->|一致| SAVE[confidence=high で保存<br/>id=camera_auto_alias_shop]
  SAVE --> ST[exports/camera_buyback_status.json]
```

**精度保証の要点**
- `near_buyback` ゲート: 「基準査定額/査定/買取申し込み」文脈の価格のみ採用（販売カタログ価格を排除）。
- 厳格モデル一致: ILCE/ILME 型番固定（Sony）、Mark III 除外（Canon）等で誤マッチ排除。
- `confidence=high` のみ自動採用。一致しなければ手動フォールバック。
- 取得元の現実: Mapcamera=Akamaiブロック、Kitamura=site_blocked、富士屋=稼働中。

## 4. LP生成フロー

`src/content/daily_lp_generator.py` → `build-public-lp` → `docs/`（GitHub Pages）。

```mermaid
flowchart TD
  DB[(buyback_prices / sale_prices / products)] --> ENR[_enrich_deal<br/>手動>1.3x auto-high 除外]
  ENR --> CARD[初心者向けショップカード<br/>自動取得/confidence/最終取得日/matched_item]
  ENR --> BADGE[利益ティア初心者バッジ]
  CARD --> WARN[警告バー3段階<br/>strong/soft/info]
  BADGE --> LPHTML[Daily LP HTML 生成]
  WARN --> LPHTML
  LPHTML --> BUILD[build-public-lp → docs/]
  BUILD --> CHECK[deploy-check / prelaunch-check]
  CHECK --> PAGES[GitHub Pages 公開]
```

## 5. ranking生成フロー

`scripts/generate_ranking_report.py` → `exports/ranking_report/latest.json|md`。

```mermaid
flowchart TD
  DB[(DB)] --> ENR[LP相当の enrich + 初心者カテゴリ付与]
  ENR --> STALE[14日超データ除外]
  STALE --> TOP10[beginner_top10 / route_type別]
  DB --> TCB[Top Camera Buyback Opportunities]
  TCB --> F1[data_source=auto_scraped]
  F1 --> F2[confidence=high]
  F2 --> F3[price>0 / 7日以内]
  F3 --> F4[genre='camera' のみ<br/>iPhone/PS5混入を排除]
  F4 --> OUT[ranking_report/latest.json]
  TOP10 --> OUT
```

## 6. sedori生成フロー

`python -m src.cli calculate-sedori-routes` →
`scripts/generate_sedori_routes_report.py` → `exports/sedori_routes_report/`。

```mermaid
flowchart TD
  DB[(買取/販売/海外価格)] --> R1[国内仕入れ → 国内売却]
  DB --> R2[国内仕入れ → 海外売却]
  R1 --> PROFIT[ProfitSimulator<br/>手数料/送料控除]
  R2 --> PROFIT
  PROFIT --> RANKR[利益率でランク付け]
  RANKR --> SREP[sedori_routes_report]
  note[海外価格 stale 時は主計算から除外] -.-> R2
```

## 7. data_quality生成フロー

`scripts/generate_data_quality_report.py` → `exports/data_quality_report/latest.json|md`。

```mermaid
flowchart TD
  ST[camera_buyback_status.json] --> CR[camera_reliability]
  CR --> M1[auto_scraped / high / low_confidence count]
  CR --> M2[manual_fallback_count]
  CR --> M3[rejection_reasons<br/>not_buyback_context/model_mismatch]
  CR --> M4[per_brand_success_rates]
  DB[(収集履歴)] --> M5[7日移動平均 / 店舗・製品成功率]
  DB --> M6[連続失敗店舗 / 改善優先度]
  DB --> M7[前回比較 delta/trend/top5]
  M1 & M2 & M3 & M4 & M5 & M6 & M7 --> DQ[data_quality_report/latest.json]
```

## 8. GitHub Actions実行フロー（daily_lp.yml）

- トリガー: `cron: '0 3 * * *'`（UTC 03:00 = JST 12:00）+ 手動 `workflow_dispatch`。
- 所要: 約50–80分（20機種カメラ収集 + Playwright導入時で80分）。

```mermaid
flowchart TD
  T0[Checkout / Setup Python 3.x] --> T1[pip install -r requirements.txt]
  T1 --> T2[Playwright install chromium]
  T2 --> T3[init-db / seed]
  T3 --> T4[update_buyback_prices.py]
  T4 --> T5[update_camera_buyback.py<br/>--priority-only --playwright --debug-html]
  T5 --> T6[Collector quality gate]
  T6 --> T7[update_lottery_events / update_alerts]
  T7 --> T8[update_overseas_prices]
  T8 --> T9[import buyback/market/sale CSV]
  T9 --> T10[collect_resale_prices]
  T10 --> T11[run-buyback-premium-check]
  T11 --> T12[calculate-sedori-routes / scan-primary-to-secondary]
  T12 --> T13[generate ranking / sedori / data_quality report]
  T13 --> T14[generate-daily-lp --variant A]
  T14 --> T15[Lottery quality gate]
  T15 --> T16[build-public-lp]
  T16 --> T17[deploy-check / prelaunch-check]
  T17 --> T18[Upload artifact: camera-playwright-debug]
  T18 --> T19[Notify Discord/Telegram]
  T19 --> T20[Commit & push → GitHub Pages]
```

**Secrets（実値はリポジトリ外・GitHub Secrets管理）**
`EBAY_APP_ID` / `DISCORD_WEBHOOK_URL` / `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`（未設定でも動作・精度低下のみ）。
