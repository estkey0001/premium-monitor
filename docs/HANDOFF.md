# HANDOFF（最終更新: 2026-09-25）

## 今の状態
- TCG（ポケモンカード / ONE PIECEカードゲーム）の入荷・抽選・プレミア監視レイヤーを追加（`src/tcg/`, `src/collectors/tcg/`, `scripts/collect_tcg_events.py`, `exports/tcg/`）。既存の Profit / AI / Opportunity / Notification / API / Source Matching には未変更。
- 実 source から取得を確認済み（ONE PIECE 公式商品ページから 3 件）。テスト 103 件 PASS、deploy-check Errors 0（OK 731 / TCG 12項目追加）、prelaunch PASS。
- eBay Real Canary は `EBAY_APP_ID` が GitHub Secret に未登録のため `EBAY_PENDING_CONFIGURATION` のまま（前フェーズからの継続）。

## 未解決・保留
- ポケモンカード公式の商品一覧は JavaScript 描画のため、Playwright 経由でのみ取得できる。ローカルは playwright 未導入で実取得未検証（CI では requirements.txt により利用可能）。
- ONE PIECE カードゲーム公式ショップ / BANDAI CARD GAMES 公式ショップは URL が DNS 解決できず、`url_verified=False` の監視登録のみ。正しい URL が判明したらコレクターを実装する。
- 二次流通価格（`data/tcg_secondary_prices.csv`）が空のため、プレミア率は全件「サンプル不足で未算出」。入荷報告（`data/tcg_restock_reports.csv`）も空のため地域シグナルは 0 件。
- 量販店・EC・コンビニ（ローソン以外）は Source Registry に登録済みだがコレクター未実装。

## 次にやること
1. 二次流通価格 CSV と入荷報告 CSV に実データを入れて、Premium / BUY NOW / 地域シグナルを通しで検証する。
2. CI 実行後に Playwright 経由のポケモン商品ページ取得が成功しているか `exports/tcg/latest.json` の source_health で確認する。
3. 未実装 source（ヨドバシ / ビック / セブンネット / 他コンビニ）のコレクターを優先度順に追加する。

## 注意（次の人へ）
- **入荷速報（🔥 今買える / CRITICAL 通知）は scraping 経由では発火しない仕様**。記事から読める日付に時刻が無いと TTL（再入荷2時間・EC復活15分等）の起点が 00:00 になり、当日中に stale になるため。時刻付きの入荷情報は `data/tcg_restock_reports.csv` に `source=store_official` + `official_confirmation=true` で入れると STORE_OFFICIAL として「今買える」に到達できる。SNS/コミュニティ報告はこの経路でも AVAILABLE_NOW にはならない。
- TCG レイヤーは「判定できないものは推測しない」方針。販売方式が読めないブロックはイベント化せず、シュリンク状態は記載が無ければ UNKNOWN、市場価格はサンプル3件未満なら None にする。この挙動はテストで固定してある（`tests/test_tcg_monitor.py`）。
- 大会・イベント告知（ジムエントリー / 体験会 / チャンピオンズリーグ等）は `src/tcg/sales_context.py` で除外している。ここを緩めると「抽選販売」の誤検出が一気に増える。
- `scripts/deploy_check.py` はモジュール先頭で PROJECT_ROOT を sys.path に追加するようにした。これが無いと `python3 scripts/deploy_check.py` 直接実行時に src 依存の 9 項目が誤って error になる。
- LP を手元で再生成すると、買取・deal データが揃っていない分だけ初心者タブ系の deploy-check が落ちる。`docs/` を手元生成物で上書きしないこと（CI に任せる）。
