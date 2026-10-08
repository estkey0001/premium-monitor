# HANDOFF（最終更新: 2026-10-08）

## 今の状態
- Phase 16（判断待ちの商品と公式直販価格）: 定価（希望小売価格）と公式直販価格を分けた（`official_registry.price_kind_of`・`MSRP_OF`。カメラの希望小売価格はオープン価格のまま）。公式直販価格は `official_direct_gate`（同一性・容量・ボディー/キット・版・購入ページ・送料・販売の形・在庫の表し方・確認日）を通ったときだけ確定の仕入れ値。Z8・X100VI・R5 II を追加。GR IV 系の商品コード・Z8 / R5 II の JAN を登録（同一性の確認済み 3 → 9）。判断待ちの3商品は候補を更新して判断待ちのまま。quality_checker のテーブル名の不具合を修正。JAN 一致でもセット・版・限定品の食い違いは low。再確認に Canon・Nikon。記録は `internal/audits/PHASE_16_OFFICIAL_DIRECT.md`
- Phase 15（商品の同一性と公式の確認）: 公式の確認の記録を `src/market/official_registry.py` に集めた（VERIFIED_URLS など。同一性の証拠・判断待ち・価格の意味 msrp / official_direct / open_price）。公式ページで確かめた JAN・型番を登録（PS5 Pro・Switch 2 の JAN、AirPods Pro 3 の型番）。公式 URL のテーブル名の不具合を直した（送料・利益は変わらない）。公式の価格・在庫の再確認（`scripts/recheck_official.py`。PS5 Pro・AirPods Pro 3）。記録は `internal/audits/PHASE_15_IDENTITY.md`
- Phase 14（国内の定価・在庫・買取・TCG の網羅）: 公式ページの確認で Switch 2 の在庫あり（明示の表示・7日で期限切れ）・PS5 Pro の再確認・PS5 Digital Edition と GR III の販売終了を記録。在庫の判定に「カートに入れる」を加えた。検索に商品の登録済みキーワード（「PS5」で PS5 Pro）。運営者向けに網羅の欄、診断に今すぐ行動できる商品（actionable）。記録は `internal/audits/PHASE_14_COVERAGE.md`
- Phase 13（成約の有効化の準備と CI の組み込み・カメラの取得時間）を実装。CI の「eBay SOLD (Marketplace Insights)」は資格情報・承認・ライセンス・取得の明示がそろったときだけ取りに行き（今は全部無いので通信0・PENDING_USER_CONFIGURATION）、最初は1商品の canary（履歴に書かない）→ 段階 1 → 3 → 10 商品。廃止された Finding API を呼ぶコードを削除。フジヤは1ページを1回だけ開き、取得済みのページを使い回す（間隔90秒は変えない）。記録は `internal/audits/PHASE_13_SOLD_ACTIVATION.md`
- Phase 12（取得の安全性）: 全取得経路が `src/collectors/polite.py`（robots.txt・同じドメインの間隔・打ち切り・正直な User-Agent）を通る。メルカリ・ラクマ・Amazon・ヤフオク・eBay の検索結果の HTML は取得しない。記録は `internal/audits/PHASE_12_SOURCE_SAFETY.md`
- 開発場所は `premium-monitor`（ブランチ `tcg-push` = `origin/main`）の1か所。push は `tcg-push:main` の fast-forward のみ
- Phase ごとの詳細な実装記録と「踏んだ罠」は `internal/DEV_NOTES.md`（削らない・着手前に該当節を読む）

## 未解決・保留
- Phase 16 の残り（Low）: カメラの設定値の参考価格（retail_price「概算定価（要確認）」）が通知の文面で「定価」と出る経路が残る（以前から）。quality_checker の「公式購入URLが未設定」は確認済みの購入ページが無い商品すべてに付く（手動のコマンドだけ）。詳細は `internal/audits/PHASE_16_OFFICIAL_DIRECT.md` §11
- アーカイブの過去の LP（UI Phase 10 より前）は旧UIのまま残している（書き換えない）。その中の HOME（`/`）のリンクはプロジェクトの外を指して壊れている（`./` は `archive/index.html` で今のサイトへ転送される）。直すなら過去の LP の書き換えになるので、ユーザーの判断。
- せどりルートの内訳で、確定ルートの購入送料などが 0 のとき「−¥0」と出る（今の本番は確定ルート0件なので出ていない。出ると #807 が ERROR）。テストの架空ルートで気づいた。
- テストの後片付けの不具合（既存）: tests/test_pokemon_coverage.py・tests/test_tcg_lottery.py は `DailyLPGenerator._load_tcg_report` をクラスから取り出して戻すので、staticmethod が外れたまま残る（後のテストで LP 全体を作ると TypeError）。test_ui_phase8 は自分で決め直して避けている。
- マイページ（Phase 7）の通知条件は**表示の絞り込みだけ**（件数・履歴・締切の目印）。メール・スマホへの配信はしていない。通知の履歴は exports/notifications の利用者向けの種類（NEW_MAIN・WATCH_TO_BUY・PRICE_DROP・PRICE_RISE・ROI_UP・ROI_DOWN）のうち、判定の印（route_checked）があり今も確定・参考ルートのものと、商品詳細の「最近の変化」（価格・在庫・抽選の受付）だけ。今の本番の通知の artifact は0件なので、履歴はほぼ「変化」になる。マイページの中身は全商品ぶん HTML に入っていて（非表示）、ウォッチ中だけを表示する（個人のウォッチは HTML に入らない）。
- pytest の全体実行の途中で、空の `data/premium_monitor.db`（0バイト）が作られることがある。残ったまま再実行すると `test_api_automation.py::test_dry_run_no_main_mutation` が「no such table」で落ちることがある（消せば通る）。作っているテストは未特定（原因は未調査）。
- フジヤカメラの買取価格（カメラ）は検索結果ページ由来（link_type=search）なので、商品照合未了として確定利益の売値に使わない。価格は「新品同様」（中古の最上位の等級）で、Phase 11 から used_s として保存する（新品の仕入れと同じ状態にならない）。CI の取得結果に商品ページのリンク候補は0件。静的 HTML には商品が無く（JS で描画・AWS WAF のチャレンジあり）、商品ページの URL を取れるかは未確認。
- **data/tcg_verified_lotteries.csv の PCO 2件は AI（Claude）が公式告知画像を目視で転記したもの**。人が公式ページで確認したら human_confirmed を true にする（それまで confidence=medium・通知しない・公式扱いにしない）。
- トイザらス / Joshin は HTTP 403（ローカルからも）、ヤマダ / ビック / ヨドバシは接続タイムアウト。解析器は未実装で、監視状況に SOURCE_BLOCKED / SOURCE_UNREACHABLE として表示している。エディオン / TSUTAYA / Amazon / 楽天ブックス / セブンネットは到達できるが TCG 抽選の告知一覧を発見できず未実装。
- fail-closed の運用判断（外部データ依存の error 項目を warning に下げるか）は引き続きユーザー判断待ち。
- 既知の LOW（Phase 0.1 では対応しない。backlog）:
  - #821 は「3件以上が同じ時刻」の形しか検出しない（検知範囲の拡張）
  - 買取の価格の種別（現金買取 / 下取）は DB に保存していない（status JSON にだけ記録。is_tradein は文字列判定）。sale_prices の種別は Phase 0.2 で保存するようにした
  - Leica M11 の商品コードが未確認（下記）
- **成約（sold）データは今は0件**。成約を取れる公式の経路は eBay Marketplace Insights API だけ（審査制。Finding API は 2025-02-05 に廃止され、呼ぶコードも Phase 13 で削除）。CI のステップは入っているが、資格情報・承認・ライセンスの確認が無いので通信0（状態は `exports/sold_history/collect_status.json`）。ヤフオク・メルカリ・ラクマは取得しない（手動の成約 CSV は URL がダミーで成約日時が無いので使えない）。
- 使われていないコード（整理の候補。削除はユーザーの判断）: `src/collectors/price/mercari.py`・`src/collectors/price/ebay.py`・中古の取得の `MercariResaleCollector`・`RakumaResaleCollector`（Phase 13 の監査 §7）。
- Phase 13 のカメラの短縮は実物の1ページとテストで確かめたが、CI の所要時間は実測で確かめる（CI で「開けない」が続くと開き直しが残る）。
- 過去の誤分類（git の履歴で数えた）: NPO にヤフオクの出品を「落札」として入れたコミットが144（1,491行、2026-06-04〜10-02）。そのうち利益ルートの main（確定利益）の仕入れ値に使ったものが32行。ダミー URL の手動「成約」を使ったルートが39コミット・269行（06-15〜09-04）。履歴は書き換えていない。
- 既知の LOW（Phase 6.1）: せどりルートの計算（`sedori_route_calculator`）は店ごとの最高値を選ぶので、その値が未照合だとルートごと外れる（同じ店の照合済みの低い値に戻らない。確定には入らない安全側）。案件の売値の照合は「商品ID・店名・価格」の一致なので、正規化データと DB で店名の表記が変わると照合済みでも未照合になる（安全側。利益が黙って消えるので、件数の急減に注意）。商品詳細の売却の表の「有効」は、照合フラグと鮮度だけで決めている（店のトップ・検索結果の URL かは見ていない。利益の売却先は `confirmed_sell_keys` で決めるので確定には影響しない）。
- 手入力（manual_today）の買取価格は商品の照合済みにならない（`is_exact_product_match` は auto_scraped だけ。ルートと同じ）ので、確定利益の売値に使わない。手入力の価格を使いたいときは、照合の根拠（商品ページの URL など）を記録する仕組みが別に必要。
- 既知の LOW（Phase 5.1・5.2 で確認、変えていない）: `normalized_prices._url_confirms_sku` は link_type が unknown（カテゴリページなど）でも商品の照合済みとする。仕入れ側は確定の判定の URL 条件（二次流通は `is_item_url`、正規店は link_type=item）で塞いだ。売却側は、買取商店のカテゴリページ（6行）を collector が型番の厳密一致で照合したものを照合済みとして使っている。商品ごとに価格が違い、トップページの1価格を複数商品に割り当てる誤り（shop_home は対策済み）とは別物で、確定ルートをすり抜けた証拠は無いので変えない。
- 既知の LOW（Phase 5.2）: 購入時の費用（カード手数料など）は公式でも 0 円のまま（`_deal_cost_lines` の buy_required 0.0）。SaaS API（src/saas/api.py、127.0.0.1 のみ）は成果物をそのまま返す（公開ページではない）。Execution Dashboard の「今週学んだこと」の後半は固定文。
- **まだ作っていない画面**: 商品詳細、サイト全体のキーワード検索（枠だけ）、絞り込みの「在庫復活」「買取急騰」「新着」（準備中。判定できるデータが無い）、かんたん/詳細の切り替え、在庫再開の本格画面（Phase 4）。
- 抽選・予約の取得元: スマホ・PC は NOT_IMPLEMENTED。TCG は17件中5件が正常（PCO は 403 で手動補完）。頻度は1日1回で、新しい抽選の発見には遅い（推奨は internal/uiux/DATA_SOURCE_MATRIX.md §4）。
- **利益商品は本番データでは0件になりやすい**（確認済みの定価・14日以内の買取価格・費用が揃う案件が少ない）。0件のときは空状態を出し、件数を水増ししない。
- 成約中央値のルートは、正規化データに集計期間（sold_period）が無いので今は掲載されない（件数3以上かつ期間ありが条件）。期間を保存するようにすれば自動で出る。
- 公式の在庫表示は official_stock_observed_at（在庫の根拠があった取得の時刻。価格の時刻とは別）から7日を過ぎると「在庫未確認」にする。在庫の表示が取れる collector が少ないので、ほぼ全件が在庫未確認（利益あり・在庫未確認）。
- 公式で販売終了・後継機に交代した商品（iPhone 17 Pro/Pro Max・iPhone 16 Pro/Pro Max・iPad Pro M4・iPad Air M3・Watch S11/Ultra 3・Switch 2 マリオカートセット・AirPods Max・Mac mini M4・MacBook Air M4・MacBook Pro M4）は `scripts/audit_official_sources.py` の OFFICIAL_NOT_SOLD。確認済みの定価を外し、設定値の参考価格に戻している。後継機（iPhone 18 Pro など）は登録していない（商品の追加は別判断）。
- 確認日不明の設定値の定価は38件（diagnostics の retail_prices）。VERIFY_FROM_OFFICIAL のものは、公式で確認できたら VERIFIED_URLS に確認日・URL 付きで入れる。
- 設定値の定価（PS5 Pro ¥119,980 など、config/products.yaml）は確認日が無い。公式で確認したら確認日付きで入れ直すまで「参考差額」のまま。
- Leica M11 の通常版の商品コードは公式資料で未確認（2026-10-02 は leica-camera.com が 502）。`scripts/update_camera_buyback.py` の m11 は require_code_any=[]（UNVERIFIED）で、どの行とも結びつけない。公式テクニカルデータ（日本語版 pm-65457）で確認できたらコードを入れる。
- 手動 CSV の時刻だけの書き換えは、過去に15回のコミット・483行あった（`python scripts/audit_timestamp_only_updates.py`）。履歴は書き換えていない。
- ネットワークを使わない手元の再現（init-db → seed → 手動 CSV 取り込み → 生成 → deploy-check）は Errors 18（初心者ページ系 #349・#432〜#467・#589〜#625 など、取得データが無いため）。修正前の HEAD でも同じ18件なので、変更前後の比較に使う。
- CI（daily_lp.yml）は pytest を実行していない。テストはローカルで実行すること。
- 既存の問題: pytest を実行すると追跡対象の exports/api_automation/collection.json が書き換わる。コミット前に `git checkout -- exports/api_automation/collection.json` で戻すこと（テストの出力先修正は別タスク）。

## 次にやること
0. Phase 17 はユーザーの指示を待ってから始める（候補は Phase 16 の最終報告に書いた）。
1. 判断待ち（`src/market/official_registry.USER_DECISIONS`）: PS5 Digital Edition・Xbox Series X・Switch 2 マリオカートセットの版（候補は Phase 16 で更新）。決めたら config/products.yaml に型番・JAN、IDENTITY_EVIDENCE に証拠を書く。
2. カメラの新品の買取は14日より古い行しか無い（X100VI は新品の買取 約44万円の行が 2026-08-22）。新品の買取を新しく取れれば、公式直販価格との比較で利益の判定に入る。
3. eBay の成約: ユーザーの設定待ち（`ops/Secrets設定.md`）。

## 注意（次の人へ）
- **着手前に `internal/DEV_NOTES.md` の関係する節を読む**
- **取得を足すときは必ず `src/collectors/polite.py` を通す**（robots_allowed → polite_wait → 取得、失敗は ShopCutoff に記録）。ブラウザを名乗る UA・ブロックの後の Playwright での取り直し・429 の再試行はしない（deploy-check #842 が検出する）。テストでは conftest が polite を差し替えるので、robots・間隔を確かめるテストには `@pytest.mark.real_polite` を付ける（価格の照合・時刻の扱い・runtime・route_id・deploy-check 番号など、過去に本番で踏んだ罠がすべてある）
- 価格は「商品行」と照合して取る。見出しや最初の価格で代用しない
- 固定値・設定値の定価に実行日の日時を付けない。時刻だけ更新して新しく見せない
- 抽選の日時・在庫・定価は推測しない。根拠が無ければ未確認にする
- pytest 実行後は `git checkout -- exports/api_automation/collection.json` で戻す。`docs/` を手元生成物で上書きしない
- ローカル `main` と remote は共通祖先を持たない。`tcg-push` で作業し rebase しない
