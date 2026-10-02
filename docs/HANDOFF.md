# HANDOFF（最終更新: 2026-10-02）

## 今の状態
- Phase 0（データの正確さ）を実装、未コミット。公開 LP の誤価格（買取商店の ¥435,000 / ¥900,000、フジヤの下取り価格・限定版・キット、RICOH の共通値 ¥259,800、Leica の別 SKU）と、鮮度の偽装（Apple 固定値の毎日の日時、公式価格・設定値の生成時刻、失敗時刻の「最終更新」、品質集計の required 店の除外）を止めた。deploy-check #820〜#825 で再発を検出する。
- 段階B（新UIの外枠・HOME・runtime・照合）は本番で受け入れ済み（UI_PHASE_B_REVIEW_PASS）。
- テスト 496 件 PASS（Phase 0 は 60件）。独立レビューは FAIL → PASS WITH WARNINGS（残りは LOW のみ）。

## 未解決・保留
- **data/tcg_verified_lotteries.csv の PCO 2件は AI（Claude）が公式告知画像を目視で転記したもの**。人が公式ページで確認したら human_confirmed を true にする（それまで confidence=medium・通知しない・公式扱いにしない）。
- トイザらス / Joshin は HTTP 403（ローカルからも）、ヤマダ / ビック / ヨドバシは接続タイムアウト。解析器は未実装で、監視状況に SOURCE_BLOCKED / SOURCE_UNREACHABLE として表示している。エディオン / TSUTAYA / Amazon / 楽天ブックス / セブンネットは到達できるが TCG 抽選の告知一覧を発見できず未実装。
- fail-closed の運用判断（外部データ依存の error 項目を warning に下げるか）は引き続きユーザー判断待ち。
- Phase 0 の残り（LOW）:
  - #821 は「3件以上が同じ時刻」の形しか検出しない
  - 設定値の定価は確認日不明（freshness_basis=config_unknown_date）のまま参考値として使っている
  - is_tradein は文字列で判定していて甘い（price_kind は status JSON にだけ記録）
- Leica M11 の通常版の商品コードは公式資料で未確認（2026-10-02 は leica-camera.com が 502）。`scripts/update_camera_buyback.py` の m11 は require_code_any=[]（UNVERIFIED）で、どの行とも結びつけない。公式テクニカルデータ（日本語版 pm-65457）で確認できたらコードを入れる。
- 手動 CSV の時刻だけの書き換えは、過去に15回のコミット・483行あった（`python scripts/audit_timestamp_only_updates.py`）。履歴は書き換えていない。
- ローカルの deploy-check は Errors 11（初心者ページ系 #349・#432〜#467）。Phase B を外しても同じ11件で、ローカルの DB の状態が原因（CI では通る）。
- CI（daily_lp.yml）は pytest を実行していない。テストはローカルで実行すること。
- 既存の問題: pytest を実行すると追跡対象の exports/api_automation/collection.json が書き換わる。コミット前に `git checkout -- exports/api_automation/collection.json` で戻すこと（テストの出力先修正は別タスク）。

## 次にやること
0. Phase 0 をコミットして CI で確かめる（ユーザーの指示を待つ）。CI の deploy-check で #820〜#825 が ok、公開 LP に ¥435,000 / ¥900,000 / +¥848,220 / 下取りの値 / ¥259,800 が無いことを確認する。
1. 利益計算の8系統の統一（internal/uiux/UI_VIEW_MODEL_SPEC.md §2）と、成約データの取得方法（internal/uiux/IMPLEMENTATION_PLAN_V2.md）。
2. 新UI Phase 1（HOME とナビ。internal/uiux/IMPLEMENTATION_PLAN_V2.md）。

## 注意（次の人へ）
- **価格は「商品行」と照合して取る**。ページの見出し（「最高¥…」）やページ内の最初の価格で代用しない。一致する行が無ければ未掲載・未取得にする。明らかな異常値は `update_buyback_prices.quarantine_suspicious` で CSV に書く前に隔離される（data_source=suspicious_rejected）。
- Leica Q3 の通常版（黒・日本向け）は商品コード 19081（Leica 公式テクニカルデータ pm-19539-JP: 黒 19 080 EU/US/CN・19 081 JP・19 082 ROW、メタリックグレー 19 21x）。価格の水準からコードを推測しない。
- フジヤの買取ページは「買取金額」（現金）と「下取は10%UP」（下取）を併記する。現金の段だけを使い、下取の段しか読めない候補は採用しない。監視対象はボディ単体の通常版なので、限定版・キット・海外版・アクセサリー・別の型番（Leica は商品コードで判定）は使わない。
- 固定値・設定値の定価に実行日の日時を付けない。Apple の固定値の確認日は `scripts/audit_official_sources.py` の `VERIFIED_URLS_CHECKED_ON`（値を公式で再確認したときだけ更新する）。
- 新UIは**追加レイヤー**。旧UIの DOM・id・クラス・JS は段階F まで触らない。新UIは `#new-ui-root` の中だけで、`html.ui-new` のとき旧UIを CSS で隠すだけ（DOM は残す）。新UIの生成が失敗しても旧UIは出る（deploy-check #801 は warning）。
- **抽選の状態は runtime だけで決める**。Python の `derive_runtime_state`（既存の compute_lottery_status を使用）と JS の `deriveLotteryRuntimeState` は同じ結果を返すこと。tests/test_new_ui_runtime.py が node で両方を実行し、多数の時刻で一致を確かめている。片方を変えたら必ずもう片方も変える。
- 「応募する」は、次の条件をすべて満たすときだけ出す。
  - 公式ドメインの https URL である
  - 開始時刻を過ぎている
  - 締切前だと言い切れる（日付だけの締切は、締切日の 0 時まで）
  - SOURCE_CONFLICT ではない
- 新UIの判定時刻は LP の生成時刻（`_nu_now`）。`datetime.now()` はタイムゾーンを持たず、CI は UTC で動くので、ローカル時刻として JST に変換している（JST とみなすと9時間ずれる）。
- HOME の表示ガード（home.py の `opportunity_reject_reason` / `route_reject_reason` / `premium_ok`）は表示だけで、元の値は変えない。
  - 「おすすめ」「高利益」「高プレミア」に出さないもの: 0円、非有限の値、ROI が 0 以下または 200% 超、プレミア率が 0 以下または 500% 超、サンプル不足、reference、confidence low
- アーカイブ（/archive/）では、`?ui=new` を付けても新UIを有効にしない（相対リンクが合わないため）。
- `?from=new#tab-xxx` のときだけ旧UIの該当タブを開く（新UIの仮ページから現行版へ戻る導線）。通常URLのハッシュの挙動は変えていない。
- プロジェクトの場所は 2026-10-01 に `Desktop/AI/ClaudeCode/premium-monitor` へ移った。
- UI 移行中（段階B〜D）は機能追加を凍結する方針を提案中。例外は急ぎの抽選の情報源・誤情報の修正・collector の修理。
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
