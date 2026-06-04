# Audit Package — premium-monitor

ChatGPT 等による技術監査のための監査パッケージ。生成日（システム日付）: 2026-06-04。

## 構成
- `repository_tree.txt` … ディレクトリツリー / ファイル一覧 / サイズ
- `system_overview.md` … 全体構成・各種データフロー（Mermaid図付き）
- `database_schema.md` … 全20テーブルのスキーマ・index・row数（主要6テーブル詳細）
- `project_metrics.md` … コード規模・重複/未使用候補・各種サイズ
- `security_report.md` … Secrets検査結果（実値の機密情報なし）
- `config/` … products.yaml / sources.yaml / genres.yaml / manual_buyback_prices.csv
- `workflows/` … .github/workflows/*
- `source/` … 主要スクリプト（収集・レポート生成・LP生成）
- `reports/` … 最新の生成レポート群（data_quality/ranking/sedori/camera等）

## 機密情報の取り扱い
- 実値のAPIキー/トークン/パスワード/Cookieは**検出されず**、含まれていません（`security_report.md` 参照）。
- `.env` / `.env.example` / `data/*.db`（生データ）/ `.git` はパッケージに**含めていません**。

## 補足（要求項目との差異）
- `generate_lp.py` は存在せず、LP生成は `source/daily_lp_generator.py`（+ CLI `build-public-lp`）が該当。
- `categories.yaml` は存在せず、`genres.yaml` が該当。
- `ranking` はDBテーブルではなくレポートJSON（`reports/ranking_report/`）として生成。
