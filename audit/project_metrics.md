# Project Metrics — premium-monitor

## コード規模

| 指標 | 値 |
|---|---|
| Python ファイル数（全体） | 164 |
| 総行数（Python） | 45,745 |
| `src/` 行数 | 30,179（123 files） |
| `scripts/` 行数 | 12,597（15 files） |
| `dashboard/` files | 26 |
| GitHub Actions workflow 数 | 1（daily_lp.yml） |
| DB サイズ | 3.7MB |
| exports/ サイズ | 17.5MB |

## 行数トップ12ファイル

| 行数 | ファイル |
|---|---|
| 8,406 | `./src/content/daily_lp_generator.py` |
| 5,341 | `./scripts/deploy_check.py` |
| 3,456 | `./src/cli.py` |
| 1,644 | `./src/db/repository.py` |
| 1,401 | `./scripts/collect_resale_prices.py` |
| 1,001 | `./scripts/update_buyback_prices.py` |
| 776 | `./scripts/update_camera_buyback.py` |
| 584 | `./src/collectors/overseas/ebay_completed.py` |
| 552 | `./scripts/check_collector_quality.py` |
| 542 | `./scripts/check_lottery_quality.py` |
| 540 | `./dashboard/pages/18_daily_lp.py` |
| 527 | `./scripts/update_alerts.py` |

## 重複コード候補（完全一致ハッシュ）

- `./dashboard/components/__init__.py` ≡ `./src/__init__.py` ≡ `./src/pipeline/__init__.py` ≡ `./src/collectors/sns/__init__.py` ≡ `./src/collectors/buyback/__init__.py` ≡ `./src/collectors/official/__init__.py` ≡ `./src/collectors/price/__init__.py` ≡ `./src/collectors/stock/__init__.py` ≡ `./src/publish/__init__.py` ≡ `./src/market/__init__.py`

## 未使用ファイル候補（scripts/ で他から参照されずworkflow未使用）

- `scripts/build_public_lp.py`
- `scripts/deploy_check.py`

> ※ 手動CLI実行専用の可能性あり。削除前に用途確認を推奨。
