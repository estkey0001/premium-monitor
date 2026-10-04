# HANDOFF（最終更新: 2026-10-04）

## 今の状態
- Phase 5.1: 旧UI（通常の URL）の利益ルート・ランキング・Hero・初心者ルート一覧・AI Opportunities（今日のおすすめ・BUY）・通知に、新UIと同じ確定の判定（`src/content/ui/opportunity.py` の `route_reasons` / `deal_reasons`）を使うようにした。`profit_routes` の `main_routes` は判定を通ったものだけ（外したものは `excluded_routes` に理由つき）。GR IV の偽ルートは旧UIの「検証済み利益ルート」「今日のおすすめ」「TOP10」「NEW_MAIN 通知」にも出ていた。
- UI Phase 5: 新UIの「せどりルート」（`?ui=new&page=routes`）を本番用にした（RouteView・確定ルートの一覧・出品価格の参考の別欄）。**本番に出ていた偽のルート（RICOH GR IV: Amazon の検索結果の出品 ¥107,491 → 買取、+¥39,009）を確定から外した**。ルートは両側の商品の同一性・状態・費用（購入送料を含む）がそろったものだけ確定にする。
- UI Phase 4: 新UIの「在庫再開」（`?ui=new&page=restock`）を本番用にした。タブは「購入可能」（既定）と「再開履歴すべて」。在庫の状態の変化を `exports/stock_history/latest.json` に残す（`scripts/update_stock_history.py`。CI の LP 生成の直前）。再入荷（在庫切れ→在庫あり）と、初めての在庫確認を区別する。購入可能は確認から3時間（TCG は既存の TTL）で「在庫未確認（更新待ち）」に落とす。HOME の件数は今購入可能なものだけ。
- UI Phase 3: 新UIの「抽選・予約」（`?ui=new&page=lottery`）を本番用の一覧にした。表示モデルは `lottery_view.py`（LotteryReservationView）、ページは `lottery_page.py`。状態の絞り込み（抽選受付中・今日締切・予約・発売待ち・当選・購入期限）・並べ替え（おすすめ・締切・開始・更新・想定利益）・検索・20件ごとのページ・ジャンル保持。1件1要素で、PC（1024px 以上）は行、モバイルはカード。予約（PREORDER）と発売待ち（公式の発売日のある COMING_SOON）を runtime に足した。
- Phase 0 / 0.1 / 0.2（データの正確さ・表示の信頼性・二次流通の価格の意味）はコミット・CI・本番で受け入れ済み。
- UI Phase 1 を実装（`?ui=new` だけ。通常の URL は旧UIのまま）。ジャンル起点の HOME（ジャンル6 → 目的4 → 小さな補助リンク）と、目的のページ4つ（利益商品・抽選・予約・在庫再開・せどりルート）の枠、ジャンルの URL 保持（`category=`）、上部ナビ／ボトムナビ5項目、SVG アイコン、デザイントークンの更新（アクセント青）。データのロジックは変えていない。
- Phase 2.1: 利益商品が0件だった原因を `exports/opportunity_diagnostics/latest.json`（内部用・理由別の件数）で出すようにした。主因は「定価が確認日不明の設定値」と「買取が定価を下回る（実際に利益が無い）」。公式で価格を確認し、PS5 Pro（Sony Store ¥137,980）・Switch 2（任天堂 ¥59,980）を確認済みにした。改定前の設定値で出ていた Switch 2 の黒字は偽物だった。在庫は根拠があるときだけ在庫あり／品切れにし、確認日時を価格と別に持つ（migration 020）。
- UI Phase 2 を実装（`?ui=new&page=opportunities`）。利益商品の一覧を OpportunityView（`src/content/ui/opportunity.py`）に一本化し、掲載の判定は `eligibility()` だけ。PC は比較テーブル（1200px 以上）、それ未満はカード（640px 以上は2列）。並べ替え4種・在庫ありの絞り込み・一覧内の検索・20件ごとのページ・TOP10・URL の状態保持。テスト 636 件 PASS（tests/test_ui_phase2.py 40件）。

## 未解決・保留
- **data/tcg_verified_lotteries.csv の PCO 2件は AI（Claude）が公式告知画像を目視で転記したもの**。人が公式ページで確認したら human_confirmed を true にする（それまで confidence=medium・通知しない・公式扱いにしない）。
- トイザらス / Joshin は HTTP 403（ローカルからも）、ヤマダ / ビック / ヨドバシは接続タイムアウト。解析器は未実装で、監視状況に SOURCE_BLOCKED / SOURCE_UNREACHABLE として表示している。エディオン / TSUTAYA / Amazon / 楽天ブックス / セブンネットは到達できるが TCG 抽選の告知一覧を発見できず未実装。
- fail-closed の運用判断（外部データ依存の error 項目を warning に下げるか）は引き続きユーザー判断待ち。
- 既知の LOW（Phase 0.1 では対応しない。backlog）:
  - #821 は「3件以上が同じ時刻」の形しか検出しない（検知範囲の拡張）
  - 買取の価格の種別（現金買取 / 下取）は DB に保存していない（status JSON にだけ記録。is_tradein は文字列判定）。sale_prices の種別は Phase 0.2 で保存するようにした
  - Leica M11 の商品コードが未確認（下記）
- **成約（sold）データは今は0件**。ヤフオク（自動）は出品価格、手動の成約 CSV（data/manual_flea_sold_prices.csv）は URL がダミーで成約日時が無い、eBay は API 未設定（CI では HTML もブロック）、メルカリ・ラクマの成約は NOT_IMPLEMENTED。成約中央値を使うには、規約に沿って1件ごとの商品ページの URL と成約日時を取れる経路が必要（eBay API を設定する場合も、1件ごとの成約日時を保存するように collector を直す必要がある）。
- 過去の誤分類（git の履歴で数えた）: NPO にヤフオクの出品を「落札」として入れたコミットが144（1,491行、2026-06-04〜10-02）。そのうち利益ルートの main（確定利益）の仕入れ値に使ったものが32行。ダミー URL の手動「成約」を使ったルートが39コミット・269行（06-15〜09-04）。履歴は書き換えていない。
- 旧UI は横に少しはみ出す（.tab-wrap の `margin: 0 -24px`。1440px で 24px、375px で 16px）。Phase 0.1 より前からある。旧UI は直していない（Phase 5.1 でも対象外。新UI は負のマージンを使わず、320〜1440px ではみ出し0をテストで確認）。旧UI を外すときに一緒に消える。
- 既知の LOW（Phase 5.1 で確認）: `normalized_prices._url_confirms_sku` は link_type が unknown（カテゴリページなど）でも商品の照合済みとする。仕入れ側は確定の判定の URL 条件（二次流通は `is_item_url`、正規店は link_type=item）で塞いだ。売却側の買取価格はカテゴリ・検索ページで collector が型番を厳密に照合したものを照合済みとして使っている（新UI・旧UIとも同じ）。
- 既知（Phase 5.1 で再評価）: 定価→買取の案件は購入送料・購入時の費用を 0 円としている（`OpportunityView` の既定値。公式ストアの送料を確認したデータは無い）。旧UI・新UIとも同じ判定なので食い違いは無い。直すなら公式ストアごとの送料を根拠つきで持たせる。
- **まだ作っていない画面**: 商品詳細、サイト全体のキーワード検索（枠だけ）、絞り込みの「在庫復活」「買取急騰」「新着」（準備中。判定できるデータが無い）、かんたん/詳細の切り替え、在庫再開の本格画面（Phase 4）。
- 抽選・予約の取得元: スマホ・PC は NOT_IMPLEMENTED。TCG は17件中5件が正常（PCO は 403 で手動補完）。頻度は1日1回で、新しい抽選の発見には遅い（推奨は internal/uiux/DATA_SOURCE_MATRIX.md §4）。
- **利益商品は本番データでは0件になりやすい**（確認済みの定価・14日以内の買取価格・費用が揃う案件が少ない）。0件のときは空状態を出し、件数を水増ししない。
- 成約中央値のルートは、正規化データに集計期間（sold_period）が無いので今は掲載されない（件数3以上かつ期間ありが条件）。期間を保存するようにすれば自動で出る。
- 公式の在庫表示は official_stock_observed_at（在庫の根拠があった取得の時刻。価格の時刻とは別）から7日を過ぎると「在庫未確認」にする。在庫の表示が取れる collector が少ないので、ほぼ全件が在庫未確認（利益あり・在庫未確認）。
- 公式で販売終了・後継機に交代した商品（iPhone 17 Pro/Pro Max・iPad Pro M4・iPad Air M3・Watch S11/Ultra 3・Switch 2 マリオカートセット）は `scripts/audit_official_sources.py` の OFFICIAL_NOT_SOLD。確認済みの定価を外し、設定値の参考価格に戻している。後継機（iPhone 18 Pro など）は登録していない（商品の追加は別判断）。
- 確認日不明の設定値の定価は38件（diagnostics の retail_prices）。VERIFY_FROM_OFFICIAL のものは、公式で確認できたら VERIFIED_URLS に確認日・URL 付きで入れる。
- 設定値の定価（PS5 Pro ¥119,980 など、config/products.yaml）は確認日が無い。公式で確認したら確認日付きで入れ直すまで「参考差額」のまま。
- Leica M11 の通常版の商品コードは公式資料で未確認（2026-10-02 は leica-camera.com が 502）。`scripts/update_camera_buyback.py` の m11 は require_code_any=[]（UNVERIFIED）で、どの行とも結びつけない。公式テクニカルデータ（日本語版 pm-65457）で確認できたらコードを入れる。
- 手動 CSV の時刻だけの書き換えは、過去に15回のコミット・483行あった（`python scripts/audit_timestamp_only_updates.py`）。履歴は書き換えていない。
- ネットワークを使わない手元の再現（init-db → seed → 手動 CSV 取り込み → 生成 → deploy-check）は Errors 18（初心者ページ系 #349・#432〜#467・#589〜#625 など、取得データが無いため）。修正前の HEAD でも同じ18件なので、変更前後の比較に使う。
- CI（daily_lp.yml）は pytest を実行していない。テストはローカルで実行すること。
- 既存の問題: pytest を実行すると追跡対象の exports/api_automation/collection.json が書き換わる。コミット前に `git checkout -- exports/api_automation/collection.json` で戻すこと（テストの出力先修正は別タスク）。

## 次にやること
0. Phase 6（商品詳細）はユーザーの指示を待ってから始める（Phase 5.1 の後も同じ）。
1. 利益商品の件数を増やすには、データ側を直す（設定値の定価の確認・カメラの買取の鮮度・成約の集計期間）。UI 側で条件を緩めない。
2. 買取・在庫の更新頻度（今は日次1回）。推奨は diagnostics の frequency。本番のスケジュール変更はユーザー判断。
2. 利益計算の8系統の統一（internal/uiux/UI_VIEW_MODEL_SPEC.md §2）と、成約データの取得方法（internal/uiux/IMPLEMENTATION_PLAN_V2.md）。

## 注意（次の人へ）
- **価格は「商品行」と照合して取る**。ページの見出し（「最高¥…」）やページ内の最初の価格で代用しない。一致する行が無ければ未掲載・未取得にする。明らかな異常値は `update_buyback_prices.quarantine_suspicious` で CSV に書く前に隔離される（data_source=suspicious_rejected）。
- Leica Q3 の通常版（黒・日本向け）は商品コード 19081（Leica 公式テクニカルデータ pm-19539-JP: 黒 19 080 EU/US/CN・19 081 JP・19 082 ROW、メタリックグレー 19 21x）。価格の水準からコードを推測しない。
- フジヤの買取ページは「買取金額」（現金）と「下取は10%UP」（下取）を併記する。現金の段だけを使い、下取の段しか読めない候補は採用しない。監視対象はボディ単体の通常版なので、限定版・キット・海外版・アクセサリー・別の型番（Leica は商品コードで判定）は使わない。
- 固定値・設定値の定価に実行日の日時を付けない。Apple の固定値の確認日は `scripts/audit_official_sources.py` の `VERIFIED_URLS_CHECKED_ON`（値を公式で再確認したときだけ更新する）。
- **新UI（UI Phase 1）の構成**: ナビは `navigation.py`（NAV_ITEMS・BOTTOM_ITEMS・PAGES・旧ハッシュの読み替え）、ジャンルは `categories.py`（products.genre などの読み替えはここだけ）、件数と一覧は `catalog.py`（件数の定義は docstring が正本。Fake count 禁止）、画面は `pages.py`、CSS は `styles.py`、アイコンは `icons.py`。ジャンルは URL の `category=` に持ち、`data-nu-keepcat` のリンクは表示のたびに今のジャンルを付けた href に書き換える（新しいタブで開いても同じ）。抽選の件数は runtime が書き換えるカードの `data-nu-bucket` から数え直す。設計の正本は internal/uiux/NEW_INFORMATION_ARCHITECTURE.md §0.1・WIREFRAMES.md §0・DESIGN_SYSTEM.md の冒頭。
- **せどりルートの確定条件**（`opportunity.route_identity_reasons`）: 仕入れ・売却とも商品の同一性が確認済み（is_exact_product_match）、二次流通で買う場合は商品ページ単位の URL（`price_types.is_item_url`）、正規店の新品も link_type=item、状態の系統（新品・未使用・開封済み・中古・TCG の各状態）が同じ、購入送料を含む費用がすべて分かる。今の生成データには購入送料の項目が無いので、ルートは確定にならない（0円とみなさない）。出品価格は参考欄だけ（利益・ROI なし・件数に数えない）。
- deploy-check（Phase 5.1）: #829 で main_routes が新UIと同じ判定を通っていることを検査する。#464 は降格の理由（`_UNCONFIRMED_LABELS`）も理由として認める。#467 はカメラの案件がすべて理由つきの監視中のときは warning（古い買取価格を利益カードに出さないため）。#446 は2位と同額のカードの「他N店舗と比較済み」も認める（生成側の仕様）。
- **旧UIと新UIで確定の判定を分けない**（Phase 5.1）。旧UI・AI Opportunities・通知・HOME は `opportunity.confirmed_routes` / `reference_routes` / `deal_reasons` を呼ぶ。旧UI側に同じ条件を書かない（tests/test_phase5_1_legacy_routes.py が検査）。参考ルートは「売却側の古さ・件数不足」以外は確定と同じ条件。通知は確定ルートの商品から作ったものに `route_checked: true` を付け、印の無い過去の利益ルート通知は旧UIに出さない。
- **在庫は restocked_at（再入荷）・last_checked_at（最終確認）・state（今の在庫）を混同しない**。履歴の更新は観測（取得に成功した在庫の状態）だけで行い、前回より新しくない観測は無視する（時刻だけ進めない）。取得に失敗した商品は観測に入れない。在庫あり→未確認→在庫ありは再入荷にしない（last_definite_state で判定）。購入可能の判定は Python（`RestockView.available`）とブラウザ（shell の `stockRuntime`）で同じ条件。
- **抽選・予約の状態は runtime だけで決める**（Python の `derive_runtime_state` と JS の `deriveLotteryRuntimeState` は同じ結果を返すこと。tests/test_new_ui_runtime.py・test_ui_phase3.py が node で照合）。VM の `k`（lottery / preorder / release）と `rd`（発売日）を足した。件数に数える状態は `runtime.COUNTED_STATUSES`（受付終了・終了・日程不明は数えない）。HOME の抽選の件数は `[data-nu-lot-list]` の行の bucket から数える。
- 抽選・予約の価格: TCG は公式の retail_price、発売待ちは `retail_price_basis=product_unit` のときだけ。旧来の抽選（公式ストア）の CSV の価格は読み取りの誤りがあるので使わず、利益商品の確認済み定価があるときだけ出す。想定利益は利益商品（掲載可）と同じ商品で、販売価格と仕入れ値が一致するときだけ。それ以外は「算出前」。
- **定価・在庫は公式の一次情報で確認する**。価格改定（PS5 Pro 2026-04-02、Switch 2 2026-05-25、iPhone 17 2026-09）や世代交代は collector では拾えないことが多い。確認した日は VERIFIED_URLS の各行の checked_on に書く（実行日にしない）。
- 在庫を推測しない: 公式 collector は「在庫あり」等の明示があるときだけ在庫あり、品切れの表示があれば在庫なし、それ以外は空（`_generic.stock_from_text` / `ricoh.ricoh_stock_from_status`）。「購入」「ご注文」「カートに入れる」は根拠にしない。
- **利益商品（UI Phase 2）**: 値は既存の純利益をそのまま使い、HTML/JS で計算し直さない。ROI = 純利益 ÷ 取得原価。費用の内訳は既存の純利益と合うときだけ出す。売値は BUYBACK_CASH か、条件を満たした SOLD_MEDIAN だけ。LISTING・UNKNOWN・設定値の参考価格・14日より古い価格は掲載しない。並べ替え・絞り込み・ページは shell.py の router（renderOpp）が data-* 属性で行う。HOME の件数は catalog.py の同じ一覧から数える（せどりルートは利益商品の一部なのでジャンル合計に重ねない）。見た目の確認用 DEMO は build/nu_preview/（gitignore）にだけ出す。
- 新UIは**追加レイヤー**。旧UIの DOM・id・クラス・JS は段階F まで触らない。新UIは `#new-ui-root` の中だけで、`html.ui-new` のとき旧UIを CSS で隠すだけ（DOM は残す）。新UIの生成が失敗しても旧UIは出る（deploy-check #801 は warning）。
- **抽選の状態は runtime だけで決める**。Python の `derive_runtime_state`（既存の compute_lottery_status を使用）と JS の `deriveLotteryRuntimeState` は同じ結果を返すこと。tests/test_new_ui_runtime.py が node で両方を実行し、多数の時刻で一致を確かめている。片方を変えたら必ずもう片方も変える。
- 「応募する」は、次の条件をすべて満たすときだけ出す。
  - 公式ドメインの https URL である
  - 開始時刻を過ぎている
  - 締切前だと言い切れる（日付だけの締切は、締切日の 0 時まで）
  - SOURCE_CONFLICT ではない
- 新UIの判定時刻は LP の生成時刻（`_nu_now`）。生成時刻は `_generation_time()`（実行環境のローカル時刻を JST に変換）。
- **時刻は保存時にタイムゾーンを付け、表示時に Asia/Tokyo へ変換してから「JST」と付ける。** タイムゾーン無しの値はこのプロジェクトでは JST として読むので、CI は `TZ: Asia/Tokyo` で動かす（daily_lp.yml）。公式価格の取得時刻（official_price_updated_at、RICOH の観測）とスキャン時刻は `+09:00` 付き（observations などはタイムゾーン無しの JST の値と文字列で並べ替えるので、`+00:00` にすると並び順が最大9時間ずれる）。根拠の無い古いタイムゾーン無しの値は補正しない。
- 「情報確認」に出してよいのは observed_at / verified_at / last_success_at だけ。generated_at（生成時刻）と last_attempt_at（失敗も含む試行時刻）は出さない。
- **価格の根拠は `src/market/price_evidence.py` の5区分**（VERIFIED_CURRENT / VERIFIED_DATED / CONFIGURED_REFERENCE / STALE / UNKNOWN）。利益を「今狙える利益」として強く出せる（最高利益・BUY・TOP10・高利益・ランキング👑）のは、仕入れ・売却とも VERIFIED_* のときだけ。旧UIは `_msrp_is_reference`、新UIは `home.evidence_reject_reason`。利益ルート・AI Opportunities は `buy_price_evidence` / `sell_price_evidence` を持つ。ルールは internal/uiux/UI_VIEW_MODEL_SPEC.md にも書いた。
- **価格の種別は `src/market/price_types.py` だけで決める**（RETAIL / BUYBACK_CASH / TRADE_IN / LISTING / SOLD / SOLD_MEDIAN / CONFIGURED_REFERENCE / UNKNOWN）。出品価格を「sold」「落札」「成約」と呼ばない。店名の文字列から成約を推測しない。sale_prices に保存する collector は必ず `price_type` と `sample_count` を渡す。成約（SOLD）は `has_sold_evidence`（1件の商品ページの URL と成約日時。ダミー・検索結果の URL は不可）を満たすものだけ。成約中央値は `sold_median`（同じ商品・3件以上・期間）。deploy-check #826〜#828 が取り違えを検出する。
- internal/uiux の5文書（UI_VIEW_MODEL_SPEC / IMPLEMENTATION_PLAN_V2 / DATA_SOURCE_MATRIX / DATA_CAPABILITY_AUDIT / AGREED_DESIGN_GAP_ANALYSIS）は Phase 0.2 で管理対象にした。UI_VIEW_MODEL_SPEC.md が新UIの仕様の正本、監査の2文書は 2026-10-02 時点のスナップショット（冒頭に位置づけを書いた）。
- 品質ゲート（check_collector_quality.py）: 誤りの可能性が高い価格（HARD_REJECT_REASONS）と low_confidence は ERROR（exit 1）、前回からの大きな変動・他店との差は WARNING（exit 0、公開を止めない）、optional 店の失敗は INFO。一般の画面には内部のチェック番号・理由コードを出さない。
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
