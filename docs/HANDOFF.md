# HANDOFF（最終更新: 2026-09-30）

## 今の状態
- TCG の抽選インテリジェンス（src/tcg/lottery/, src/collectors/tcg/lottery/）を追加。17 source を registry 化し、抽選・購入権の状態（UPCOMING / OPEN / ENDING_SOON / CLOSED / RESULT_PENDING / WINNER_ANNOUNCED / WINNER_PURCHASE_PERIOD / ENDED / UNKNOWN）、締切カウントダウン、応募条件（原文つき）、重複・矛盾検出、履歴、通知候補、監視状況（実装 / 正常 / 拒否 / 接続不可 / 未実装）を出力する。LP の TCG タブ最上部が抽選。
- 実データ: ゲオ（自動取得 4件、10/1 締切で終了済み）、ポケモンセンターオンライン（8/21 告知は自動取得、9/29 告知は日程が画像のみのため手動転記 2件・人による確認待ち）。
- テスト 302 件 PASS。レビュー 5 回（FAIL→FAIL→FAIL→PASS WITH WARNINGS→PASS WITH WARNINGS、残 MEDIUM も修正済み）。

## 未解決・保留
- **data/tcg_verified_lotteries.csv の PCO 2件は AI（Claude）が公式告知画像を目視で転記したもの**。人が公式ページで確認したら human_confirmed を true にする（それまで confidence=medium・通知しない・公式扱いにしない）。
- トイザらス / Joshin は HTTP 403（ローカルからも）、ヤマダ / ビック / ヨドバシは接続タイムアウト。解析器は未実装で、監視状況に SOURCE_BLOCKED / SOURCE_UNREACHABLE として表示している。エディオン / TSUTAYA / Amazon / 楽天ブックス / セブンネットは到達できるが TCG 抽選の告知一覧を発見できず未実装。
- fail-closed の運用判断（外部データ依存の error 項目を warning に下げるか）は引き続きユーザー判断待ち。
- 既存の問題: pytest を実行すると追跡対象の exports/api_automation/collection.json が書き換わる。コミット前に `git checkout -- exports/api_automation/collection.json` で戻すこと（テストの出力先修正は別タスク）。

## 次にやること
1. PCO の手動転記データを人が確認して human_confirmed=true にする。
2. 到達可能な未実装 source（エディオン / TSUTAYA / 楽天ブックス / セブンネット）で TCG 抽選の告知一覧の URL を実ページから発見し、解析器を追加する。
3. 二次流通価格の投入（pokemon_registry.json の secondary_mapping）。

## 注意（次の人へ）
- **抽選の日時は推測しない**。年の無い日付は記事の公開年から補い、曜日が書かれていれば一致を検証する（合わなければ採用しない）。時刻の無い日付は *_date（YYYY-MM-DD）に入れ、00:00 を作らない。状態判定では「開始日当日はまだ開始前」「締切日当日は締切間近、翌日以降は締切後」と安全側に扱う。既存パーサー（TcgEvent）由来の 00:00 も from_tcg_events で日付のみに戻している。
- 抽選の統合（merge）は、同じ商品・小売でも応募期間が重ならない別回は分ける。片方の日時しか無い情報は、時刻で比べられればその回の期間内のときだけ合流し、日付のみのときだけ3日の幅を認める。公式どうしの食い違いはどちらも採用せず「日程要確認」で表示する。下位 source が上位の空欄を埋めるのは公式 source のときだけ。
- 応募ボタンは公式ドメインの URL・公式 source・受付前 / 受付中のときだけ。締切後は公式の結果確認ページ（明記があるもの）に切り替える。
- PCO は CI から HTTP 403。bot 対策は回避しない。公式ニュース一覧の外部リンクから告知を発見し、本文が取れなければタイトルで大会・プレゼント等を除外したうえで「抽選告知あり（日程未取得）」として残す。
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
