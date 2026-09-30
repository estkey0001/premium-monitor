# HANDOFF（最終更新: 2026-09-30）

## 今の状態
- ポケモンカードの監視を「カテゴリトップ解析」から「公式商品 API（`/products/resultAPI.php`）」へ切り替え、商品単位の registry・ニュース（公式カテゴリで大会記事を除外）・ローソン（公式一覧からリンク発見）の3系統で監視するようにした。ファネル計測（pages / product links / candidate / accepted / rejected と理由）を各 run で出力する。
- CI の deploy-check を fail-closed 化（`deploy-check-lp` がエラー時に exit 1 / workflow に `set -o pipefail`）。失敗した日も Notify・Prelaunch は `if: always()` で実行し、公開（commit / push）だけ止める。
- テスト 212 件 PASS。レビュー2回（1回目 FAIL → 修正 → 2回目 PASS WITH WARNINGS → 過剰棄却の MEDIUM も修正済み）。

## 未解決・保留
- **fail-closed の運用判断（ユーザー判断待ち）**: 外部データの取得状況に依存する error 項目（例: #595 flea_sold_price 0件）が出た日は LP が更新されない。直近5回では 9/27 の1回（#592/#595/#622/#624/#625）。warning に下げるかはユーザーが決める。
- ポケモンセンターオンラインは CI（GitHub Actions）から HTTP 403。bot 対策の回避はせず BLOCKED として記録している。
- 二次流通価格 CSV / 入荷報告 CSV が空のため、Premium・BUY NOW・地域シグナルは実データ未検証。
- ONE PIECE 公式ショップ / BANDAI CARD GAMES 公式ショップは URL 未確定（DNS 解決不可）。

## 次にやること
1. fail-closed の運用方針をユーザーに確認し、必要なら外部データ依存の error を warning に整理する。
2. 二次流通価格の投入（`exports/tcg/pokemon_registry.json` の `secondary_mapping` を使う）。
3. 他コンビニ（7-ELEVEN / FAMILY_MART / MINISTOP）を、公式一覧からの発見が確認できたものから追加する。

## 注意（次の人へ）
- **ポケモン公式の商品一覧は `/products/index.html` ではなく `/products/resultAPI.php`（JSON）から取る**。パラメータは公式 `bundle.js` の `setRequestParams` と同じ（productType / dateLowerY,M,D / dateUpperY,M,D / page）。周辺グッズ（peripheral）は TCG 販売監視の対象外なので取得しない。
- 公式 API の拡張パック系「希望小売価格」は**1パックの価格**（ハイクラスパック・拡張パックデラックスも同じ）。BOX 定価にしない。`registry_retail_prices` が定価候補にするのは「商品単価」と明示された BOX 対象種別のみ。
- registry 由来のイベントは `availability_basis=release_date_only`、ニュース由来は `article_date_only`。**これらは発売日・記事日を過ぎても AVAILABLE_NOW にならない**（在庫を確認していないため）。「今買える」に出るのは販売告知・在庫報告そのもの（公式系）だけ。
- 状態の区別: 発売前は `COMING_SOON`、応募開始前の抽選も `COMING_SOON`（受付中ではない）、当選者だけが買える期間は `WINNER_PURCHASE_PERIOD`（BUY NOW 対象外）。
- 非販売告知の判定（`src/tcg/sales_context.py`）: 大会・ジムバトル・プレイヤー募集等は常に除外。「キャンペーン」「プレゼント」「配布」等は**販売ラベル（発売日・価格・予約受付・販売開始 等）が無いブロックだけ**除外する。単独の除外語にすると発売告知ごと消えるので注意。
- 同一ドメインへのアクセスは RateLimiter が**最低60秒**を強制する（緩めない）。ポケモン公式は1 run あたり約8〜10リクエスト（API 3 + 商品詳細 ≤4 + ニュース一覧 1 + 記事 ≤3）なので、CI で数分かかる。
- robots.txt: pokemon-card.com は 404（`not_found`）。既存の fail-open（取得できなければ許可）は変えていないが、ログ上は `allowed` / `disallowed` / `not_found` / `unknown` を区別して記録する。
- **ローカル `main` と remote は共通祖先を持たない**（過去の本名除去による履歴書き換え）。remote に反映するときは `origin/main` から切ったブランチ（`tcg-push`）で作業し、fast-forward で push する。rebase しない。
- remote の履歴には本名とローカルメールが残っている。PUBLIC 化の前に再監査が必要。
- LP を手元で再生成すると、買取・deal データが揃っていない分だけ初心者タブ系の deploy-check が落ちる。`docs/` を手元生成物で上書きしない（CI に任せる）。
