# 公開成果物の商品単位データの一覧（Raw Data Exposure Inventory）

公開リポジトリ・GitHub Pages に出ている JSON のうち、**商品ごとの価格・取得元（店・URL）・除外・不足の理由**を持つもの。
第三者が公開済みの観測・診断から調査候補を再計算できるかの判断材料である。**一覧を作るだけで、削除・変更はしない**。
値（商品名・価格）はここに書かない。件数は、商品らしいキー（`product_id`・`name` など）を持つオブジェクトのうち、
各種類のキーも持つものの数（同じオブジェクトが複数の種類に数えられる）。日次の `history/` は同じ形のコピーなので除く。
生成: `python scripts/inventory_public_raw_data.py --write`。

| ファイル | 商品別の価格 | 取得元・URL | 除外・不足の理由 |
|---|---:|---:|---:|
| `exports/normalized_price_observations/latest.json` | 234 | 234 | 234 |
| `exports/official_recheck/history.json` | 222 | 222 | 222 |
| `exports/camera_buyback_status.json` | 60 | 60 | 60 |
| `exports/opportunity_diagnostics/latest.json` | 53 | 53 | 47 |
| `exports/discovery/product_candidates.json` | 40 | 40 | 40 |
| `exports/collector_report/latest.json` | 2 | 50 | 50 |
| `exports/official_source_audit/latest.json` | 9 | 37 | 56 |
| `exports/overseas_report/latest.json` | 0 | 78 | 0 |
| `exports/discovery/priority.json` | 36 | 18 | 18 |
| `exports/profit_routes/latest.json` | 0 | 0 | 47 |
| `exports/ranking_report/latest.json` | 22 | 20 | 4 |
| `exports/collector_report/price_baseline.json` | 20 | 20 | 0 |
| `exports/tcg/pokemon_registry.json` | 18 | 18 | 0 |
| `exports/tcg/msrp.json` | 15 | 15 | 3 |
| `exports/tcg/latest.json` | 9 | 21 | 2 |
| `exports/official_recheck/latest.json` | 9 | 9 | 9 |
| `exports/price_history/latest.json` | 0 | 27 | 0 |
| `exports/tcg/lottery_history.json` | 9 | 9 | 0 |
| `exports/flea_sold_prices/mercari_sold.json` | 8 | 4 | 4 |
| `exports/stock_history/latest.json` | 7 | 9 | 0 |
| `exports/tcg/lottery_sources.json` | 0 | 12 | 2 |
| `exports/tcg/opportunities.json` | 7 | 7 | 0 |
| `exports/overseas_prices/latest.json` | 0 | 13 | 0 |
| `exports/flea_sold_prices/yahoo_sold.json` | 6 | 3 | 3 |
| `exports/alerts_report/latest.json` | 0 | 4 | 0 |
| `exports/tcg/lotteries.json` | 2 | 2 | 0 |
| `data/accounts/demo_beta.json` | 3 | 0 | 0 |
| `exports/notifications/actionable/state.json` | 0 | 0 | 1 |

- 対象のファイル: 28 件。うち、商品別の価格と除外・不足の理由の両方を持つもの: 14 件。
- 調査候補の再計算に直接使えるのは、`exports/normalized_price_observations/latest.json`（商品別の価格・売却元・鮮度）と `exports/opportunity_diagnostics/latest.json`（商品別の除外理由・公式価格）。
- これらは既存の画面・診断・テスト・通知の入力でもあるため、公開粒度を変えるには別の判断（運営者）が要る。今回は変更しない。
