# HANDOFF（最終更新: 2026-09-25）

## 今の状態
- TCG（ポケモンカード / ONE PIECEカードゲーム）の入荷・抽選・プレミア監視レイヤーを追加し、**本番反映済み**（`03d5045` / `74bbe3c`）。既存の Profit / AI / Opportunity / Notification / API / Source Matching には未変更。
- CI（Daily LP Update run 36106561815）成功。CI 上の deploy-check は Errors 0 / OK 735、prelaunch Errors 0。GitHub Pages も反映され、本番サイトに「抽選・店頭販売」タブと TCG セクションが表示されている（JS console error 0、モバイル横スクロールなし）。
- 現在の実取得データは ONE PIECE 公式商品ページの 3 件のみ。ポケモンは 0 件だが **collector は正常動作**（Playwright 起動・ページ取得成功、errors=0）。
- eBay Real Canary は `EBAY_APP_ID` が GitHub Secret に未登録のため `EBAY_PENDING_CONFIGURATION` のまま（前フェーズからの継続）。

## 未解決・保留
- ポケモンカード公式の商品一覧（`/products/index.html`）は **カテゴリ紹介ページ**で、個別商品と価格が載っていない（「拡張パック / 構築デッキ / その他の商品 / 周辺グッズ」の説明のみ）。CI で Playwright は正常に動作しているので、0 件は collector 障害ではなく監視 URL の階層が浅いことが原因。商品単位のサブページを監視対象に追加する必要がある。
- ローカルは playwright 未導入のため、手元では同 collector が errors=1（未導入）になる。CI では正常。
- ONE PIECE カードゲーム公式ショップ / BANDAI CARD GAMES 公式ショップは URL が DNS 解決できず、`url_verified=False` の監視登録のみ。正しい URL が判明したらコレクターを実装する。
- 二次流通価格（`data/tcg_secondary_prices.csv`）が空のため、プレミア率は全件「サンプル不足で未算出」。入荷報告（`data/tcg_restock_reports.csv`）も空のため地域シグナルは 0 件。
- 量販店・EC・コンビニ（ローソン以外）は Source Registry に登録済みだがコレクター未実装。

## 次にやること
1. ポケモンの監視 URL を商品単位のサブページへ深掘りする（現状はカテゴリ紹介ページのため 0 件）。
2. 二次流通価格 CSV と入荷報告 CSV に実データを入れて、Premium / BUY NOW / 地域シグナルを通しで検証する。
3. 未実装 source（ヨドバシ / ビック / セブンネット / 他コンビニ）のコレクターを優先度順に追加する。

## 注意（次の人へ）
- **入荷速報（🔥 今買える / CRITICAL 通知）は scraping 経由では発火しない仕様**。記事から読める日付に時刻が無いと TTL（再入荷2時間・EC復活15分等）の起点が 00:00 になり、当日中に stale になるため。時刻付きの入荷情報は `data/tcg_restock_reports.csv` に `source=store_official` + `official_confirmation=true` で入れると STORE_OFFICIAL として「今買える」に到達できる。SNS/コミュニティ報告はこの経路でも AVAILABLE_NOW にはならない。
- TCG レイヤーは「判定できないものは推測しない」方針。販売方式が読めないブロックはイベント化せず、シュリンク状態は記載が無ければ UNKNOWN、市場価格はサンプル3件未満なら None にする。この挙動はテストで固定してある（`tests/test_tcg_monitor.py`）。
- 大会・イベント告知（ジムエントリー / 体験会 / チャンピオンズリーグ等）は `src/tcg/sales_context.py` で除外している。ここを緩めると「抽選販売」の誤検出が一気に増える。
- `scripts/deploy_check.py` はモジュール先頭で PROJECT_ROOT を sys.path に追加するようにした。これが無いと `python3 scripts/deploy_check.py` 直接実行時に src 依存の 9 項目が誤って error になる。
- LP を手元で再生成すると、買取・deal データが揃っていない分だけ初心者タブ系の deploy-check が落ちる。`docs/` を手元生成物で上書きしないこと（CI に任せる）。
- **ローカル `main` ブランチと remote は共通祖先を持たない**（過去の本名除去による履歴書き換えの結果。ローカル 352 / remote 380 コミットで merge-base なし）。remote へ反映するときは rebase ではなく `origin/main` から切ったブランチへ cherry-pick し、fast-forward で push すること。作業ブランチ `tcg-push` が origin/main を追跡している。
- remote 履歴には本名とローカルメールアドレスが残っている（`有藤 雄弥 <...MacBook-Air.local>` / 個人 Gmail）。リポジトリを PUBLIC 化する前に再監査が必要。
- CI の Deploy check ステップは `... | tee ...` で exit code が tee のものになるため、**deploy-check が失敗してもジョブは成功扱いになる**（pipefail 未設定）。実際 #601 は remote 上で失敗したまま日次 push が続いていた。厳格化する場合は `set -o pipefail` を入れる。
