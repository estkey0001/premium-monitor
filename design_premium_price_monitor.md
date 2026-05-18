# プレ値商品監視・速報システム 設計書

**バージョン:** 1.0
**作成日:** 2026-05-16
**ステータス:** 設計フェーズ

---

## 禁止事項（最重要）

本システムでは以下の機能を**絶対に実装しない**。

- 自動購入・自動応募
- CAPTCHA突破
- 複数アカウント作成・SMS認証回避
- サイトに過剰負荷をかける高頻度アクセス（最低でも60秒間隔を遵守）

あくまで**合法的な情報収集・監視・通知システム**として運用する。

---

## 1. システム全体構成

### 1.1 アーキテクチャ概要

```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                     │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Streamlit    │  │  通知送信     │  │  API (将来)    │  │
│  │  管理画面     │  │  LINE/Discord │  │  外部連携用    │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────────┘  │
├─────────┼──────────────────┼────────────────────────────┤
│         │    Application Layer                           │
│  ┌──────┴──────────────────┴──────────────────────────┐  │
│  │              Orchestrator (指揮者)                   │  │
│  │  - スケジューリング (APScheduler)                    │  │
│  │  - Collector呼び出し制御                             │  │
│  │  - エラーハンドリング・リトライ                       │  │
│  └──────┬─────────────────────────────────────────────┘  │
│         │                                                │
│  ┌──────┴──────────────────────────────────────────────┐  │
│  │              Processing Pipeline                     │  │
│  │  ┌───────────┐ ┌───────────┐ ┌──────────────────┐   │  │
│  │  │ Normalizer│ │ Scorer    │ │ Alert Dispatcher  │   │  │
│  │  │ 正規化    │→│ スコアリング│→│ 通知判定・送信    │   │  │
│  │  └───────────┘ └───────────┘ └──────────────────┘   │  │
│  └─────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│                    Collection Layer                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ Stock    │ │ Price    │ │ Lottery  │ │ SNS      │   │
│  │ Collector│ │ Collector│ │ Collector│ │ Collector│   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘   │
│       │            │            │            │           │
│  ┌────┴────────────┴────────────┴────────────┴────────┐  │
│  │          Base Collector (共通基盤)                   │  │
│  │  - Rate Limiter / Retry / User-Agent管理            │  │
│  │  - robots.txt準拠チェック                            │  │
│  └────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│                      Data Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  SQLite DB   │  │  YAML Config │  │  Log Files    │  │
│  │  全データ格納 │  │  設定ファイル  │  │  実行ログ     │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
└──────────────────────────────────────────────────────────┘
```

### 1.2 データフロー

```
[情報源サイト] → Collector取得 → Normalizer正規化 → DB保存
                                                      ↓
                                              Scorer スコア計算
                                                      ↓
                                              Alert判定 (S/A/B/C)
                                                      ↓
                                         ┌─ S/A → 即時通知送信
                                         ├─ B   → 記録のみ
                                         └─ C   → 不要/誤報候補
```

### 1.3 レイヤー責務

| レイヤー | 責務 | 主な技術 |
|---------|------|---------|
| Presentation | 管理画面・通知送信 | Streamlit, LINE/Discord API |
| Application | スケジューリング・パイプライン制御 | APScheduler, Pydantic |
| Collection | サイト別データ取得 | requests, BeautifulSoup4, Playwright |
| Data | 永続化・設定管理 | SQLite, PyYAML |

---

## 2. ディレクトリ構成

```
premium-monitor/
├── config/
│   ├── settings.yaml          # グローバル設定
│   ├── sources.yaml           # 情報源マスタ（YAML版）
│   ├── products.yaml          # 監視対象商品（YAML版）
│   ├── notifications.yaml     # 通知先設定
│   └── scoring_rules.yaml     # スコアリングルール
│
├── src/
│   ├── __init__.py
│   │
│   ├── models/                # Pydanticモデル・DB定義
│   │   ├── __init__.py
│   │   ├── product.py         # 商品マスタモデル
│   │   ├── source.py          # 情報源マスタモデル
│   │   ├── observation.py     # 取得データモデル
│   │   ├── alert.py           # 通知モデル
│   │   └── enums.py           # 列挙型定義
│   │
│   ├── db/                    # データベース
│   │   ├── __init__.py
│   │   ├── database.py        # DB接続・初期化
│   │   ├── migrations/        # スキーマ変更履歴
│   │   │   └── 001_initial.sql
│   │   └── repository.py      # CRUD操作
│   │
│   ├── collectors/            # サイト別Collector
│   │   ├── __init__.py
│   │   ├── base.py            # BaseCollector（共通基盤）
│   │   ├── rate_limiter.py    # レートリミッター
│   │   ├── robots_checker.py  # robots.txt準拠チェック
│   │   │
│   │   ├── stock/             # 在庫系Collector
│   │   │   ├── __init__.py
│   │   │   ├── apple_store.py
│   │   │   ├── yodobashi.py
│   │   │   ├── biccamera.py
│   │   │   └── ...
│   │   │
│   │   ├── price/             # 価格系Collector
│   │   │   ├── __init__.py
│   │   │   ├── kakaku_com.py
│   │   │   ├── mercari.py
│   │   │   ├── yahoo_auction.py
│   │   │   └── ...
│   │   │
│   │   ├── buyback/           # 買取系Collector
│   │   │   ├── __init__.py
│   │   │   ├── sofmap.py
│   │   │   ├── janpara.py
│   │   │   ├── iosys.py
│   │   │   └── ...
│   │   │
│   │   ├── lottery/           # 抽選・予約系Collector
│   │   │   ├── __init__.py
│   │   │   └── generic_lottery.py
│   │   │
│   │   └── sns/               # SNS系Collector
│   │       ├── __init__.py
│   │       └── twitter.py
│   │
│   ├── pipeline/              # 処理パイプライン
│   │   ├── __init__.py
│   │   ├── normalizer.py      # データ正規化
│   │   ├── scorer.py          # スコアリングエンジン
│   │   ├── dedup.py           # 重複排除
│   │   └── alert_dispatcher.py # 通知判定・振り分け
│   │
│   ├── notifiers/             # 通知先別モジュール
│   │   ├── __init__.py
│   │   ├── base.py            # BaseNotifier
│   │   ├── line_notifier.py
│   │   ├── discord_notifier.py
│   │   ├── telegram_notifier.py
│   │   └── log_notifier.py    # ログ出力（開発用）
│   │
│   ├── orchestrator.py        # スケジューラ・全体制御
│   └── cli.py                 # CLIエントリーポイント
│
├── dashboard/                 # Streamlit管理画面
│   ├── app.py                 # メインページ
│   ├── pages/
│   │   ├── 01_alerts.py       # 速報一覧
│   │   ├── 02_products.py     # 商品マスタ管理
│   │   ├── 03_sources.py      # 情報源管理
│   │   ├── 04_price_chart.py  # 価格推移グラフ
│   │   ├── 05_ranking.py      # 利益ランキング
│   │   ├── 06_logs.py         # 実行ログ
│   │   └── 07_publish.py      # 速報候補 → SNS下書き
│   └── components/
│       ├── filters.py         # 共通フィルタUI
│       └── charts.py          # 共通チャートUI
│
├── data/
│   ├── premium_monitor.db     # SQLiteファイル
│   └── logs/                  # ログディレクトリ
│       └── collector_YYYYMMDD.log
│
├── tests/
│   ├── test_collectors/
│   ├── test_pipeline/
│   ├── test_notifiers/
│   └── fixtures/              # テスト用ダミーHTML等
│
├── .env                       # 環境変数（APIキー等）
├── .env.example
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 3. DB設計

SQLiteを使用。全テーブルの設計を以下に示す。

### 3.1 ER図（概念）

```
products ──1:N── observations
products ──1:N── price_history
products ──1:N── alerts
sources  ──1:N── observations
sources  ──1:N── collector_logs

products ──N:M── sources  (product_source_config で中間テーブル)
```

### 3.2 テーブル一覧

#### products（商品マスタ）

| カラム | 型 | 制約 | 説明 |
|-------|----|------|------|
| id | TEXT | PK | ULID or UUID |
| genre | TEXT | NOT NULL | iphone / pc / game_console / camera |
| name | TEXT | NOT NULL | 商品名（例: iPhone 16 Pro Max 256GB） |
| brand | TEXT | | メーカー名 |
| model_number | TEXT | | 型番 |
| jan_code | TEXT | UNIQUE, NULLABLE | JANコード |
| retail_price | INTEGER | | 定価（税込、円） |
| keywords | TEXT | | 検索用キーワード（JSON配列） |
| image_url | TEXT | | 商品画像URL |
| is_active | BOOLEAN | DEFAULT 1 | 監視対象か |
| memo | TEXT | | 管理者メモ |
| created_at | TEXT | NOT NULL | ISO8601 |
| updated_at | TEXT | NOT NULL | ISO8601 |

#### sources（情報源マスタ）

| カラム | 型 | 制約 | 説明 |
|-------|----|------|------|
| id | TEXT | PK | ULID or UUID |
| name | TEXT | NOT NULL | 表示名（例: ヨドバシカメラ） |
| source_type | TEXT | NOT NULL | official_store / electronics_retailer / ... |
| base_url | TEXT | NOT NULL | サイトベースURL |
| collector_module | TEXT | NOT NULL | collectors.stock.yodobashi 等 |
| rate_limit_sec | INTEGER | DEFAULT 60 | 最小取得間隔（秒） |
| requires_js | BOOLEAN | DEFAULT 0 | Playwright必須か |
| is_active | BOOLEAN | DEFAULT 1 | 有効か |
| robots_txt_url | TEXT | | robots.txtのURL |
| memo | TEXT | | 備考 |
| created_at | TEXT | NOT NULL | ISO8601 |
| updated_at | TEXT | NOT NULL | ISO8601 |

#### product_source_config（商品×情報源 設定）

| カラム | 型 | 制約 | 説明 |
|-------|----|------|------|
| id | TEXT | PK | |
| product_id | TEXT | FK → products | |
| source_id | TEXT | FK → sources | |
| target_url | TEXT | | 個別商品ページURL |
| css_selector_stock | TEXT | | 在庫判定用CSSセレクタ |
| css_selector_price | TEXT | | 価格取得用CSSセレクタ |
| extra_config | TEXT | | JSON（サイト固有パラメータ） |
| is_active | BOOLEAN | DEFAULT 1 | |
| created_at | TEXT | NOT NULL | |

#### observations（取得データ）

| カラム | 型 | 制約 | 説明 |
|-------|----|------|------|
| id | TEXT | PK | |
| product_id | TEXT | FK → products | |
| source_id | TEXT | FK → sources | |
| observation_type | TEXT | NOT NULL | stock / price / lottery / buyback / sns / overseas |
| observed_at | TEXT | NOT NULL | 取得日時 ISO8601 |
| is_in_stock | BOOLEAN | NULLABLE | 在庫あり/なし |
| price | INTEGER | NULLABLE | 取得価格（円） |
| buyback_price | INTEGER | NULLABLE | 買取価格（円） |
| lottery_status | TEXT | NULLABLE | upcoming / open / closed |
| lottery_deadline | TEXT | NULLABLE | 抽選締切日時 |
| raw_text | TEXT | | 取得した生テキスト |
| raw_html_hash | TEXT | | 取得HTML SHA256（変化検知用） |
| confidence | REAL | DEFAULT 1.0 | 情報信頼度 0.0〜1.0 |
| is_false_positive | BOOLEAN | DEFAULT 0 | 誤報フラグ |
| is_manually_verified | BOOLEAN | DEFAULT 0 | 手動確認済み |
| created_at | TEXT | NOT NULL | |

#### price_history（価格推移）

| カラム | 型 | 制約 | 説明 |
|-------|----|------|------|
| id | TEXT | PK | |
| product_id | TEXT | FK → products | |
| source_id | TEXT | FK → sources | |
| price_type | TEXT | NOT NULL | retail / used / buyback / auction / overseas |
| price | INTEGER | NOT NULL | 価格（円） |
| currency | TEXT | DEFAULT 'JPY' | 通貨 |
| recorded_at | TEXT | NOT NULL | 記録日時 |

#### alerts（通知ログ）

| カラム | 型 | 制約 | 説明 |
|-------|----|------|------|
| id | TEXT | PK | |
| observation_id | TEXT | FK → observations | トリガーとなった観測 |
| product_id | TEXT | FK → products | |
| alert_rank | TEXT | NOT NULL | S / A / B / C |
| alert_type | TEXT | NOT NULL | stock_available / lottery_open / price_drop / buyback_surge / sns_mention |
| title | TEXT | NOT NULL | 通知タイトル |
| body | TEXT | NOT NULL | 通知本文 |
| estimated_profit | INTEGER | NULLABLE | 想定利益（円） |
| score | REAL | | 総合スコア |
| confidence | REAL | | 信頼度 |
| is_sent | BOOLEAN | DEFAULT 0 | 送信済みか |
| sent_channels | TEXT | | 送信先チャネル（JSON配列） |
| is_false_positive | BOOLEAN | DEFAULT 0 | 誤報だった |
| is_published | BOOLEAN | DEFAULT 0 | SNS速報として公開済み |
| created_at | TEXT | NOT NULL | |
| sent_at | TEXT | NULLABLE | 送信日時 |

#### collector_logs（Collector実行ログ）

| カラム | 型 | 制約 | 説明 |
|-------|----|------|------|
| id | TEXT | PK | |
| source_id | TEXT | FK → sources | |
| product_id | TEXT | FK → products, NULLABLE | |
| started_at | TEXT | NOT NULL | |
| finished_at | TEXT | | |
| status | TEXT | NOT NULL | success / error / timeout / skipped |
| http_status | INTEGER | NULLABLE | HTTPレスポンスコード |
| error_message | TEXT | NULLABLE | エラー詳細 |
| duration_ms | INTEGER | NULLABLE | 実行時間（ms） |

#### notification_dedup（重複通知防止）

| カラム | 型 | 制約 | 説明 |
|-------|----|------|------|
| id | TEXT | PK | |
| dedup_key | TEXT | UNIQUE | product_id + alert_type + date のハッシュ |
| alert_id | TEXT | FK → alerts | |
| created_at | TEXT | NOT NULL | |
| expires_at | TEXT | NOT NULL | 重複チェック有効期限 |

### 3.3 インデックス

```sql
CREATE INDEX idx_observations_product ON observations(product_id, observed_at DESC);
CREATE INDEX idx_observations_type ON observations(observation_type, observed_at DESC);
CREATE INDEX idx_price_history_product ON price_history(product_id, price_type, recorded_at DESC);
CREATE INDEX idx_alerts_rank ON alerts(alert_rank, created_at DESC);
CREATE INDEX idx_alerts_product ON alerts(product_id, created_at DESC);
CREATE INDEX idx_collector_logs_status ON collector_logs(status, started_at DESC);
CREATE INDEX idx_notification_dedup_key ON notification_dedup(dedup_key);
```

---

## 4. 商品マスタ設計

### 4.1 ジャンル定義（拡張可能Enum）

```yaml
# config/genres.yaml
genres:
  iphone:
    display_name: "iPhone"
    default_sources: [apple_store, yodobashi, biccamera, mercari, kakaku]
  pc:
    display_name: "PC"
    default_sources: [yodobashi, biccamera, kakaku, mercari]
  game_console:
    display_name: "ゲーム機"
    default_sources: [sony_store, nintendo_store, yodobashi, biccamera, mercari, geo]
  camera:
    display_name: "カメラ"
    default_sources: [ricoh_store, sony_store, map_camera, kitamura, fujiya, kakaku]
  # --- 将来追加 ---
  # watch:
  #   display_name: "時計"
  # trading_card:
  #   display_name: "トレカ"
  # sneaker:
  #   display_name: "スニーカー"
  # gpu:
  #   display_name: "GPU"
```

### 4.2 商品登録例（YAML）

```yaml
# config/products.yaml
products:
  - id: "prod_iphone16pm_256"
    genre: "iphone"
    name: "iPhone 16 Pro Max 256GB"
    brand: "Apple"
    model_number: "MYW23J/A"
    retail_price: 189800
    keywords: ["iPhone 16 Pro Max", "iPhone16ProMax", "MYW23J"]

  - id: "prod_ps5_pro"
    genre: "game_console"
    name: "PlayStation 5 Pro"
    brand: "Sony"
    model_number: "CFI-7000A01"
    retail_price: 119980
    keywords: ["PS5 Pro", "PlayStation5Pro", "CFI-7000"]

  - id: "prod_gr3x"
    genre: "camera"
    name: "RICOH GR IIIx"
    brand: "RICOH"
    model_number: "15286"
    retail_price: 139700
    keywords: ["GR IIIx", "GR3x", "GRIIIx", "15286"]
```

### 4.3 商品マスタの設計方針

- **keywords**: 各サイトでの表記揺れに対応するためJSON配列で保持。Collectorがページ内テキストとマッチングする際に使用する。
- **retail_price**: 定価は手動入力（公式価格改定時にアップデート）。これを基準に利益計算する。
- **jan_code**: JANコードがある商品はこれで一意特定。ない場合はmodel_number + nameで照合。
- **is_active**: 販売終了品や監視不要になった商品を無効化できる。

---

## 5. 情報源マスタ設計

### 5.1 Source Type定義

| source_type | 説明 | 取得対象 |
|-------------|------|---------|
| official_store | メーカー公式ストア | 在庫・予約・抽選 |
| electronics_retailer | 家電量販店 | 在庫・価格 |
| used_marketplace | 中古専門店 | 中古価格・在庫 |
| buyback_shop | 買取専門店 | 買取価格 |
| auction_market | オークション | 落札相場 |
| flea_market | フリマ | 出品価格・売切れ速度 |
| sns | SNS | 入荷報告・リーク情報 |
| news_blog | ニュース・ブログ | 発売情報・入荷速報 |
| overseas_market | 海外マーケット | 海外価格（内外価格差） |
| price_comparison | 価格比較サイト | 最安値・価格推移 |

### 5.2 情報源登録例

```yaml
# config/sources.yaml
sources:
  # --- 公式ストア ---
  - id: "src_apple_store"
    name: "Apple Store (Japan)"
    source_type: "official_store"
    base_url: "https://www.apple.com/jp/"
    collector_module: "collectors.stock.apple_store"
    rate_limit_sec: 120
    requires_js: false

  - id: "src_sony_store"
    name: "Sony Store"
    source_type: "official_store"
    base_url: "https://store.sony.jp/"
    collector_module: "collectors.stock.sony_store"
    rate_limit_sec: 120
    requires_js: true

  - id: "src_nintendo_store"
    name: "My Nintendo Store"
    source_type: "official_store"
    base_url: "https://store-jp.nintendo.com/"
    collector_module: "collectors.stock.nintendo_store"
    rate_limit_sec: 120
    requires_js: true

  # --- 家電量販店 ---
  - id: "src_yodobashi"
    name: "ヨドバシカメラ"
    source_type: "electronics_retailer"
    base_url: "https://www.yodobashi.com/"
    collector_module: "collectors.stock.yodobashi"
    rate_limit_sec: 90
    requires_js: false

  - id: "src_biccamera"
    name: "ビックカメラ"
    source_type: "electronics_retailer"
    base_url: "https://www.biccamera.com/"
    collector_module: "collectors.stock.biccamera"
    rate_limit_sec: 90
    requires_js: false

  # --- 中古・買取 ---
  - id: "src_sofmap"
    name: "ソフマップ"
    source_type: "buyback_shop"
    base_url: "https://www.sofmap.com/"
    collector_module: "collectors.buyback.sofmap"
    rate_limit_sec: 90

  - id: "src_map_camera"
    name: "マップカメラ"
    source_type: "used_marketplace"
    base_url: "https://www.mapcamera.com/"
    collector_module: "collectors.price.map_camera"
    rate_limit_sec: 90

  - id: "src_janpara"
    name: "じゃんぱら"
    source_type: "buyback_shop"
    base_url: "https://www.janpara.co.jp/"
    collector_module: "collectors.buyback.janpara"
    rate_limit_sec: 90

  - id: "src_iosys"
    name: "イオシス"
    source_type: "buyback_shop"
    base_url: "https://iosys.co.jp/"
    collector_module: "collectors.buyback.iosys"
    rate_limit_sec: 90

  # --- フリマ・オークション ---
  - id: "src_mercari"
    name: "メルカリ"
    source_type: "flea_market"
    base_url: "https://jp.mercari.com/"
    collector_module: "collectors.price.mercari"
    rate_limit_sec: 120
    requires_js: true

  - id: "src_yahoo_auction"
    name: "ヤフオク"
    source_type: "auction_market"
    base_url: "https://auctions.yahoo.co.jp/"
    collector_module: "collectors.price.yahoo_auction"
    rate_limit_sec: 120

  # --- 価格比較 ---
  - id: "src_kakaku"
    name: "価格.com"
    source_type: "price_comparison"
    base_url: "https://kakaku.com/"
    collector_module: "collectors.price.kakaku_com"
    rate_limit_sec: 120

  # --- 海外 ---
  - id: "src_stockx"
    name: "StockX"
    source_type: "overseas_market"
    base_url: "https://stockx.com/"
    collector_module: "collectors.price.stockx"
    rate_limit_sec: 180
    requires_js: true

  # --- SNS ---
  - id: "src_twitter"
    name: "X (Twitter)"
    source_type: "sns"
    base_url: "https://x.com/"
    collector_module: "collectors.sns.twitter"
    rate_limit_sec: 60
```

### 5.3 product_source_config 例

```yaml
product_source_configs:
  - product_id: "prod_gr3x"
    source_id: "src_map_camera"
    target_url: "https://www.mapcamera.com/item/xxxxx"
    css_selector_price: ".price-value"
    css_selector_stock: ".stock-status"

  - product_id: "prod_gr3x"
    source_id: "src_kakaku"
    target_url: "https://kakaku.com/item/K0001234567/"
    css_selector_price: "#priceBox .priceTxt"
```

---

## 6. Collector設計

### 6.1 BaseCollector（共通基盤）

```
BaseCollector
├── プロパティ
│   ├── source: SourceModel          # 対応する情報源
│   ├── session: requests.Session    # HTTP session（UA設定済み）
│   ├── rate_limiter: RateLimiter    # レートリミッター
│   └── logger: Logger               # ロガー
│
├── メソッド（共通）
│   ├── fetch_page(url) → str        # HTML取得（rate limit込み）
│   ├── fetch_page_js(url) → str     # Playwright経由HTML取得
│   ├── check_robots_txt(url) → bool # robots.txt準拠チェック
│   ├── parse_price(text) → int      # 価格文字列パース（¥, 税込等対応）
│   ├── normalize_stock(text) → bool # 在庫文字列 → bool
│   └── save_observation(data)       # DB保存
│
├── メソッド（サブクラスで実装）
│   ├── collect(product, config) → Observation  # 取得実行
│   └── health_check() → bool                   # 疎通確認
│
└── エラーハンドリング
    ├── HTTPError → ログ記録 + skip
    ├── ParseError → confidence低下 + ログ記録
    ├── Timeout → リトライ(最大2回) + skip
    └── RobotsTxtBlocked → 永続skip + 管理者通知
```

### 6.2 Collector種別

| 種別 | 取得内容 | 出力observation_type |
|------|---------|---------------------|
| StockCollector | 在庫有無・入荷日 | stock |
| PriceCollector | 販売価格・相場 | price |
| BuybackCollector | 買取価格 | buyback |
| LotteryCollector | 抽選ステータス・締切日 | lottery |
| SNSCollector | キーワードマッチ投稿 | sns |
| OverseasPriceCollector | 海外販売価格 | overseas |

### 6.3 RateLimiter設計

```
RateLimiter
├── ドメイン単位でアクセス間隔を管理
├── last_access: dict[domain, datetime]
├── wait_if_needed(domain, min_interval_sec)
│   → 前回アクセスからmin_interval_sec未満ならsleep
├── 全Collectorで共有（シングルトン）
└── robots.txtのCrawl-delayも尊重
```

### 6.4 Collector登録・動的ロード

Collectorは `collector_module` 文字列からPython `importlib` で動的ロードする。新しいサイトを追加する際は以下の手順のみ。

1. `src/collectors/` 配下に新ファイル作成
2. `BaseCollector` を継承し `collect()` を実装
3. `config/sources.yaml` に情報源を追記
4. `config/product_source_configs` で商品と紐付け

コア部分の修正は不要。

### 6.5 取得失敗時のフォールバック

```
1回目失敗 → 30秒待機 → リトライ
2回目失敗 → 60秒待機 → リトライ
3回目失敗 → error としてログ記録、次の商品/ソースへ進む
              → 連続5回失敗でソースを一時無効化 + 管理者通知
```

**重要: 1つのCollectorが失敗しても他のCollector・他の商品の処理は停止しない。**

---

## 7. 通知設計

### 7.1 通知チャネル

| チャネル | 用途 | 優先度 |
|---------|------|--------|
| LINE Notify | 個人速報（即時性最優先） | S, A |
| Discord Webhook | コミュニティ向け速報 | S, A |
| Telegram Bot | 海外向け / バックアップ | S, A |
| ログ記録 | 全ランク記録（開発・分析用） | S, A, B, C |

### 7.2 BaseNotifier インターフェース

```
BaseNotifier
├── send(alert: AlertModel) → bool
├── format_message(alert) → str    # チャネル別フォーマット
├── is_enabled() → bool
└── test_connection() → bool       # 疎通確認
```

### 7.3 通知テンプレート

```
🔴 【S速報】在庫復活
━━━━━━━━━━━
商品: iPhone 16 Pro Max 256GB
情報源: ヨドバシカメラ
定価: ¥189,800
現在二次流通: ¥235,000
想定利益: ¥45,200
信頼度: 92%
━━━━━━━━━━━
検出時刻: 2026-05-16 14:32:05
```

### 7.4 重複通知防止ロジック

```
dedup_key = hash(product_id + alert_type + date_bucket)

date_bucket の定義:
  - stock_available → 6時間ごと（同日に何度も在庫復活する場合がある）
  - lottery_open → 1日ごと（抽選開始は1回のみ通知）
  - buyback_surge → 12時間ごと
  - price_drop → 24時間ごと

送信前に notification_dedup テーブルを確認。
同じ dedup_key が expires_at 以内に存在 → 送信スキップ。
```

### 7.5 通知フロー

```
Observation → Scorer → Alert生成
                          ↓
                   dedup チェック
                    ↓         ↓
                 重複あり    重複なし
                  (skip)       ↓
                         ランク判定
                    ↓              ↓
                 B/C (記録のみ)   S/A
                                   ↓
                            各Notifier.send()
                                   ↓
                            is_sent = true 更新
```

---

## 8. スコアリング設計

### 8.1 スコア計算パイプライン

Observationが保存されるたびにスコアリングが実行される。

```
Input: observation + product + 過去observations
                ↓
        ┌───────────────┐
        │ 利益スコア計算  │  estimated_profit / thresholds
        └───────┬───────┘
                ↓
        ┌───────────────┐
        │ 信頼度計算     │  source reliability × data freshness
        └───────┬───────┘
                ↓
        ┌───────────────┐
        │ 変化検知       │  前回との差分・急騰検知
        └───────┬───────┘
                ↓
        ┌───────────────┐
        │ 総合スコア     │  weighted sum → alert_rank判定
        └───────┬───────┘
                ↓
Output: Alert(rank, score, confidence, estimated_profit)
```

### 8.2 利益スコア（Profit Score）

```python
estimated_profit = secondary_price - retail_price - fees
# fees: 販売手数料10% + 送料1,500円（デフォルト値、設定変更可能）

profit_score:
  profit >= 30,000  →  1.0
  profit >= 20,000  →  0.8
  profit >= 10,000  →  0.6
  profit >= 5,000   →  0.4
  profit < 5,000    →  0.2
```

### 8.3 信頼度（Confidence）

```python
confidence = source_weight × freshness_weight × consistency_weight

source_weight:    # 情報源の信頼性
  official_store:       1.0
  electronics_retailer: 0.95
  price_comparison:     0.90
  used_marketplace:     0.85
  buyback_shop:         0.85
  auction_market:       0.75
  flea_market:          0.70
  sns:                  0.50
  news_blog:            0.60
  overseas_market:      0.70

freshness_weight:  # 情報の鮮度
  取得から 0〜5分:   1.0
  取得から 5〜30分:  0.9
  取得から 30〜60分: 0.7
  取得から 1〜6時間: 0.5
  取得から 6時間超:  0.3

consistency_weight:  # 複数ソースの一致度
  3ソース以上一致: 1.0
  2ソース一致:     0.85
  1ソースのみ:     0.65
```

### 8.4 変化検知スコア（Change Score）

```python
# 在庫変化
stock_change:
  なし → あり:  1.0  (在庫復活)
  あり → なし:  0.3  (売切れ、記録のみ)

# 買取価格変化
buyback_change:
  前日比 +20%以上: 1.0
  前日比 +10%以上: 0.7
  前日比 +5%以上:  0.4
  それ以下:        0.1

# 中古相場変化
used_price_change:
  前日比 +15%以上: 1.0
  前日比 +10%以上: 0.7
  前日比 +5%以上:  0.4
  それ以下:        0.1
```

### 8.5 総合スコア → ランク判定

```python
total_score = (
    profit_score   * 0.40 +
    change_score   * 0.30 +
    confidence     * 0.30
)

# ランク判定ルール
if estimated_profit >= 30000 and confidence >= 0.80 and (in_stock or lottery_open or buyback_surge):
    rank = "S"
elif estimated_profit >= 10000 and confidence >= 0.70 and (price_change or stock_change):
    rank = "A"
elif total_score >= 0.40:
    rank = "B"
else:
    rank = "C"
```

### 8.6 スコアリングルール設定（YAML）

```yaml
# config/scoring_rules.yaml
scoring:
  profit_thresholds:
    s_rank_min_profit: 30000
    a_rank_min_profit: 10000
  confidence_thresholds:
    s_rank_min_confidence: 0.80
    a_rank_min_confidence: 0.70
  weights:
    profit: 0.40
    change: 0.30
    confidence: 0.30
  fee_defaults:
    platform_fee_rate: 0.10
    shipping_fee: 1500
```

---

## 9. 管理画面設計（Streamlit）

### 9.1 画面一覧

| # | ページ | 主要機能 |
|---|--------|---------|
| 1 | ダッシュボード | KPIサマリ・直近S/Aアラート・稼働状況 |
| 2 | 速報一覧 | アラート一覧、ランク別フィルタ、誤報フラグ付与 |
| 3 | 商品マスタ管理 | 商品CRUD、ジャンル別一覧、有効/無効切替 |
| 4 | 情報源管理 | ソースCRUD、接続テスト、成功率表示 |
| 5 | 価格推移グラフ | 商品別の定価 vs 中古 vs 買取の時系列チャート |
| 6 | 利益ランキング | 想定利益が大きい商品TOP N |
| 7 | 実行ログ | Collector実行結果、エラー一覧、成功率推移 |
| 8 | 速報公開管理 | SNS投稿下書き生成、公開候補キュー |

### 9.2 ダッシュボード（トップ画面）

```
┌──────────────────────────────────────────────────────────┐
│  プレ値商品監視システム                          [更新]   │
├──────────┬──────────┬──────────┬──────────────────────────┤
│ S速報     │ A速報     │ 監視商品数 │ 稼働Collector         │
│ 3件(24h) │ 12件(24h)│ 42件      │ 28/30 正常             │
├──────────┴──────────┴──────────┴──────────────────────────┤
│                                                          │
│  📊 直近S/Aアラート (24h)                                │
│  ┌────────────────────────────────────────────────────┐  │
│  │ [S] iPhone 16 Pro Max - ヨドバシ在庫復活 +¥45,200  │  │
│  │ [S] GR IIIx - 買取急騰 ¥125,000→¥148,000         │  │
│  │ [A] PS5 Pro - ビックカメラ在庫あり +¥12,500        │  │
│  │ ...                                                │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  📈 Collector稼働率 (直近7日)                            │
│  [折れ線グラフ: 成功率の推移]                              │
│                                                          │
│  ⚠️ 要対応                                               │
│  - src_mercari: 連続3回タイムアウト                       │
│  - prod_switch2: 定価未設定                               │
└──────────────────────────────────────────────────────────┘
```

### 9.3 利益ランキング画面

```
┌──────────────────────────────────────────────────────────┐
│  💰 利益ランキング        [期間: 24h ▼] [ジャンル: 全て ▼] │
├────┬────────────────┬─────────┬─────────┬────────┬───────┤
│ #  │ 商品名          │ 定価    │ 二次流通 │ 想定利益│ 信頼度│
├────┼────────────────┼─────────┼─────────┼────────┼───────┤
│ 1  │ GR IIIx         │ ¥139,700│ ¥198,000│ ¥40,500│ 0.92 │
│ 2  │ iPhone 16 PM    │ ¥189,800│ ¥235,000│ ¥21,700│ 0.88 │
│ 3  │ Switch 2 本体   │ ¥49,980│ ¥72,000 │ ¥14,820│ 0.85 │
│ ...│                  │         │         │        │      │
└────┴────────────────┴─────────┴─────────┴────────┴───────┘
```

### 9.4 速報公開管理画面

将来のSNS→LP→LINE→note導線のため、速報候補を管理。

```
┌──────────────────────────────────────────────────────────┐
│  📢 速報公開管理                                         │
├──────────────────────────────────────────────────────────┤
│  未公開の速報候補: 5件                                    │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │ [S] GR IIIx 在庫復活 - マップカメラ                  │  │
│  │ 生成テンプレート:                                    │  │
│  │ 「🔥速報：RICOH GR IIIx マップカメラで在庫復活！     │  │
│  │   定価¥139,700 → 中古相場¥198,000                   │  │
│  │   想定利益: 約¥40,000」                              │  │
│  │                                                     │  │
│  │ [コピー] [X投稿用編集] [公開済みにする] [スキップ]     │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## 10. Phase別 実装手順

### Phase 1: 基盤構築（1〜2週間）

**目標:** DB・モデル・設定ファイル・CLIスケルトンが動く状態

| # | タスク | 成果物 |
|---|--------|--------|
| 1 | プロジェクト初期化、依存ライブラリ導入 | pyproject.toml, requirements.txt |
| 2 | Pydanticモデル定義（product, source, observation, alert） | src/models/ |
| 3 | SQLiteスキーマ作成・マイグレーション | src/db/ |
| 4 | YAML設定読み込み機構 | config/ |
| 5 | BaseCollector + RateLimiter + robots.txtチェッカー | src/collectors/base.py 等 |
| 6 | BaseNotifier + LogNotifier（ログ出力のみ） | src/notifiers/ |
| 7 | CLI エントリーポイント（手動実行テスト） | src/cli.py |

### Phase 2: 最初のCollector（1〜2週間）

**目標:** 1ジャンル（カメラ or iPhone）× 2〜3サイトで在庫・価格を実際に取得

| # | タスク | 成果物 |
|---|--------|--------|
| 1 | 価格.com Collector実装 | collectors/price/kakaku_com.py |
| 2 | ヨドバシ Collector実装 | collectors/stock/yodobashi.py |
| 3 | マップカメラ or ソフマップ Collector実装 | collectors/price/ or buyback/ |
| 4 | Normalizer実装（価格パース、在庫判定統一） | pipeline/normalizer.py |
| 5 | 手動テスト実行 + データ確認 | テスト用スクリプト |

### Phase 3: スコアリング＋通知（1週間）

**目標:** 取得データからスコア計算し、LINE/Discordに通知が飛ぶ

| # | タスク | 成果物 |
|---|--------|--------|
| 1 | Scorer実装（利益・信頼度・変化検知） | pipeline/scorer.py |
| 2 | AlertDispatcher実装（ランク判定・dedup） | pipeline/alert_dispatcher.py |
| 3 | LINE Notify連携 | notifiers/line_notifier.py |
| 4 | Discord Webhook連携 | notifiers/discord_notifier.py |
| 5 | 重複通知防止テスト | tests/ |

### Phase 4: 管理画面（1〜2週間）

**目標:** Streamlitでダッシュボード・速報一覧・利益ランキングが見える

| # | タスク | 成果物 |
|---|--------|--------|
| 1 | ダッシュボード（KPIサマリ） | dashboard/app.py |
| 2 | 速報一覧（フィルタ・誤報フラグ） | dashboard/pages/01_alerts.py |
| 3 | 商品マスタ管理 | dashboard/pages/02_products.py |
| 4 | 価格推移グラフ | dashboard/pages/04_price_chart.py |
| 5 | 利益ランキング | dashboard/pages/05_ranking.py |
| 6 | 速報公開管理（テンプレ生成） | dashboard/pages/07_publish.py |

### Phase 5: Collector拡充（2〜3週間）

**目標:** 全ジャンル × 主要サイトをカバー

| # | タスク |
|---|--------|
| 1 | Apple Store / Sony Store / Nintendo Store |
| 2 | ビックカメラ / ヤマダ電機 / エディオン / ノジマ / Joshin |
| 3 | じゃんぱら / イオシス / カメラのキタムラ / フジヤカメラ |
| 4 | メルカリ / ヤフオク / ラクマ（Playwright使用） |
| 5 | StockX / eBay（海外価格Collector） |
| 6 | X/Twitter SNS Collector |

### Phase 6: 自動スケジューリング（1週間）

**目標:** APSchedulerでCollectorが自動巡回する

| # | タスク | 成果物 |
|---|--------|--------|
| 1 | Orchestrator実装（APScheduler統合） | src/orchestrator.py |
| 2 | ソース別スケジュール設定 | config/settings.yaml |
| 3 | ヘルスチェック・自動無効化 | orchestrator内ロジック |
| 4 | ログローテーション設定 | data/logs/ |

### Phase 7: 販売導線準備（1〜2週間）

**目標:** SNS→LP→LINE→note/Discord導線に必要な機能を整備

| # | タスク |
|---|--------|
| 1 | 速報テンプレート自動生成（X/Twitter用、LINE用） |
| 2 | 速報公開キュー管理（公開済み/未公開/スキップ） |
| 3 | 週間・月間レポート自動生成（note記事の素材） |
| 4 | 利益実績ログ（実際に利確した分の記録 → 実績としてLP掲載） |

### Phase 8: 安定運用・拡張（継続）

| # | タスク |
|---|--------|
| 1 | ジャンル追加（時計・トレカ・スニーカー・GPU等） |
| 2 | Collector安定性向上（セレクタ変更検知、自動修復） |
| 3 | API化（外部サービス連携、モバイル対応） |
| 4 | 過去データ分析（プレ値予測モデルの検討） |

---

## 付録A: 設定ファイルテンプレート

### settings.yaml

```yaml
system:
  db_path: "data/premium_monitor.db"
  log_dir: "data/logs"
  log_level: "INFO"
  timezone: "Asia/Tokyo"

scheduler:
  default_interval_minutes: 30
  stock_check_interval_minutes: 15
  price_check_interval_minutes: 60
  buyback_check_interval_minutes: 120
  sns_check_interval_minutes: 10

http:
  default_timeout_sec: 30
  max_retries: 3
  user_agent: "PremiumMonitor/1.0 (Information Gathering; +https://example.com/bot-policy)"
  respect_robots_txt: true
  global_min_interval_sec: 60
```

### notifications.yaml

```yaml
notifications:
  line:
    enabled: true
    token_env: "LINE_NOTIFY_TOKEN"
    send_ranks: ["S", "A"]

  discord:
    enabled: true
    webhook_url_env: "DISCORD_WEBHOOK_URL"
    send_ranks: ["S", "A"]

  telegram:
    enabled: false
    bot_token_env: "TELEGRAM_BOT_TOKEN"
    chat_id_env: "TELEGRAM_CHAT_ID"
    send_ranks: ["S"]

  log:
    enabled: true
    send_ranks: ["S", "A", "B", "C"]
```

---

## 付録B: 技術スタック一覧

| ライブラリ | 用途 | 必須/任意 |
|-----------|------|----------|
| Python 3.11+ | ランタイム | 必須 |
| SQLite | データベース | 必須 |
| Pydantic | データバリデーション・モデル | 必須 |
| PyYAML | 設定ファイル読み込み | 必須 |
| requests | HTTP通信 | 必須 |
| BeautifulSoup4 | HTMLパース | 必須 |
| APScheduler | スケジューリング | 必須 |
| Streamlit | 管理画面 | 必須 |
| python-dotenv | 環境変数管理 | 必須 |
| Playwright | JS描画が必要なサイト用 | 任意 |
| plotly | 価格チャート | 任意 |
| ulid-py | ULID生成 | 任意 |

---

*以上、設計書 v1.0*
