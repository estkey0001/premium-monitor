# Phase 14 — 国内の定価・在庫・買取・TCG の網羅

作成: 2026-10-08。eBay の成約は外部の設定待ち（PENDING_EXTERNAL_SETUP）なので触らない。

## 1. 基準（Phase 13 の生成物 d8ce6271）

| 指標 | 値 |
|---|---:|
| 商品 | 45 |
| 確認済みの定価 | 7（参考 38） |
| 確定の買取（商品） | 9 |
| 新しい買取 / 古い買取（行） | 67 / 71 |
| 在庫あり / 在庫切れ / 在庫未確認 / 抽選 | 0 / 1 / 41 / 3 |
| 在庫の再開 | 0 |
| TCG の抽選 / 予約 / 先着 / 再販 | 2 / 0 / 0 / 0 |
| 確定の利益商品 | 1（PS5 Pro。在庫切れ） |
| 健康度 | 37.5 |
| CI の所要時間 | 59.2分 |

ファネル（Phase 11 と同じ定義）: 候補 45 → 定価の確認 7 → 新しい売値 7 → 同一性 7 → 費用 7 → 利益 1 → 掲載 1。
定価が未確認の38件が最大の詰まり。

## 2. 網羅表（商品ごと。production_coverage_metrics の matrix）

- 定価 CONFIRMED・買取 CONFIRMED: AirPods Pro 3・Switch 2・PS5 Pro・iPhone 17 256GB
- 定価 CONFIRMED・買取 REFERENCE: GR IV・GR IV HDF・GR IV Monochrome（売値はフジヤの新品同様 = 中古系・検索結果）
- 定価 REFERENCE・買取 CONFIRMED: iPhone 16 Pro・17 Pro（256/512）・17 Pro Max（256/512）。どれも公式で販売終了
  （OFFICIAL_NOT_SOLD）なので、定価を確認済みにできない（正しい扱い）
- 定価 REFERENCE・買取 REFERENCE / STALE / MISSING: カメラ（オープン価格）・Mac・iPad・Watch・AirPods Max・PS5 DE・Xbox など
- 在庫: PS5 Pro だけ（在庫切れ）。GR IV 系3件は公式の抽選（LOTTERY）

## 3. 公式ページの確認（2026-10-08。ブラウザで公式ページを表示して確認）

| 商品 | 確認した内容 | 扱い |
|---|---|---|
| Nintendo Switch 2 | My Nintendo Store の商品ページで 59,980円（税込）・「カートに入れる」（押せる）・「お届け予定日：通常2～6日後」（02:32） | 定価は確認済みのまま（商品ページの URL に変更）。在庫あり（購入できる明示の表示） |
| PS5 Pro | Sony Store の購入ページで「入荷待ち 137,980円(税込)」（02:34）。PlayStation 公式の本体ラインナップでも 137,980円 | 定価を再確認。在庫切れ |
| AirPods Pro 3 | Apple の購入ページで 42,800円。在庫・お届けは選択を進める前は表示されない | 定価を再確認。在庫は記録しない（未確認） |
| PS5 Digital Edition | 公式の本体ラインナップのデジタル・エディションは「日本語専用」（55,000円）だけ | 公式で販売終了（この商品は型番の登録が無く、参考価格 72,980円 = 多言語の版） |
| RICOH GR III | RICOH の製品ページに「RICOH GRIII 生産終了」 | 公式で販売終了 |
| Xbox Series X | 公式の製品ページに複数の型（ディスク・1TB・デジタル）。表示中の価格は 109,980円 | 型番の登録が無く、どの型か決められないので確認済みにしない |

確認済みの定価の件数は変わらない（Switch 2・PS5 Pro・AirPods Pro 3 は前から確認済み）。過去の定価・設定値・
価格比較サイト・検索結果のページは確認済みにしていない。

### 公式で販売中かの確認（手順7）

- Apple: iPhone 17 Pro / Pro Max・16 Pro / Pro Max・iPad（M3 / M4）・Mac（M4）・Watch（S11 / Ultra 3）・AirPods Max は
  Phase 11 で販売終了を確認済み（OFFICIAL_NOT_SOLD）。iPhone 17・AirPods Pro 3 は販売中。
- Sony（PS5）: Pro は販売中、デジタル・エディション（この商品の版）は販売終了。
- Nintendo: Switch 2（日本語・国内専用）は販売中、マリオカート ワールド セットは生産終了（Phase 11）。
- RICOH: GR IV 系は販売中（公式の抽選）、GR III は生産終了。GR IIIx は生産終了の表示なし。
- Canon・Nikon・Fujifilm・Sony α・Leica: オープン価格。直販の販売価格を確認済みの定価にするかは、以前からユーザーの
  判断待ち（Phase 12 の HANDOFF）。カメラの売値はフジヤの新品同様（中古系・検索結果）しか無く、定価を確認しても
  利益の計算に使える売値が無いので、今回は変えていない。

## 4. 型番・JAN が無く同一性を確かめにくい商品（手順8。無理に確定にしない）

型番も JAN も登録が無い商品は23件: AirPods Max・AirPods Pro 3・Apple Watch S11 / Ultra 3・GR III・GR IV・
iPad Air M3 / Pro M4 11 / 13・iPhone 16 Pro 256・iPhone 17 256・17 Pro 256 / 512・17 Pro Max 256 / 512・Mac mini M4・
MacBook Air M4 13 / 15・MacBook Pro M4 14・PS5 Digital Edition・Switch 2・Switch 2 マリオカートセット・Xbox Series X。

- iPhone・AirPods Pro 3・Switch 2・GR IV は、商品名・容量・SIM フリー・版（日本語・国内専用）と、買取商店の行の型番
  （AirPods は MFHP4J/A）で照合できるので、今の確定の扱いを保つ。
- PS5 Digital Edition・Xbox Series X・Switch 2 マリオカートセットは、どの版（日本語専用 / 多言語・ディスク / デジタル・
  国内専用 / 多言語）か決められない。Switch 2 マリオカートセットは、買取商店の家電のページに「日本語・国内専用」の行
  （JAN 4902370553031）があるが、Phase 11 と同じ理由（登録の定価が国内専用版と合わない）で確定の買取に加えない。
  型番・JAN を登録して版を決めれば、取得を増やさずに（同じページ）加えられる。

## 5. 在庫（手順9〜15）

- 在庫ありにする証拠: 「在庫あり」「カートに入れる」の明示（`src/market/stock_state.py`）。在庫切れの表示（入荷待ち・
  品切れなど）を先に見るので、両方あるページは在庫切れ。商品ページがある・価格がある・発売中・予約ページがある、
  だけでは在庫ありにしない。
- 時刻: 公式の在庫は確認した時刻（official_stock_observed_at）つきで記録し、7日（price_evidence.CURRENT_DAYS）を過ぎれば
  在庫未確認に戻る。期限は延ばしていない。在庫の履歴（stock_history）は observed_at・last_checked_at・restocked_at を分ける。
- 販売店: ヨドバシ・ビック・ヤマダは接続タイムアウト、Joshin・トイザらスは 403（Phase 11〜13 の CI）。Amazon は検索結果
  の取得を禁止し、個別の商品ページも自動では取らない（NOT_SUPPORTED）。楽天は公式 API だけ（キーは未設定）。
- 結果: 在庫あり 0 → 1（Switch 2。診断・利益の案件の値。2026-10-15 に期限切れで在庫未確認に戻る）。
  公開の在庫再開のページ（stock_history → official_store）は、在庫ありを確認から3時間で「更新待ち」にする
  （期限は場所によって違い、どちらも延ばしていない）。CI の時刻には、公開の在庫ページでは在庫未確認（更新待ち）に見える。
- Switch 2 の購入送料: 公式 URL を商品ページ（store-jp.nintendo.com）に変えると、商品詳細は送料の決まり（5,500円以上は
  無料）で 0円と出す一方、利益の判定は公式 URL を引けない経路（beginner_deal_scanner._get_official_url。既存の不具合:
  存在しないテーブル名を引いて空になる）で送料不明のままになり、食い違う。商品ごとの送料の記録
  （official_shipping.PRODUCT_SHIPPING）に Switch 2（0円・条件つき・ストアの決まり 2026-10-05 確認）を加え、両方が
  同じ記録を使うようにした。テーブル名の不具合は別の作業（直すと他の商品の送料の判定が変わる）。
  送料が分かったので、Switch 2 は利益が出れば（今は買取 52,500円 < 定価 59,980円で出ない）確定に入りうる。
- 手で記録した在庫は、確認から7日を過ぎたら DB に書かない（audit_official_sources._stock_record_is_current）。
  CI は毎回 DB を作り直すので、7日の期限を見ない古い判定（初心者向けの分類・LINE の文面）にも古い在庫ありが残らない。
- 「カートに入れる」だけを根拠にするとき、予約・抽選・発売予定・発売前・否定（できません・不可）の語が並べば在庫あり
  にしない（stock_state.CART_BLOCKERS）。
- 予約（RESERVATION）は「今すぐ行動できる」に数えるが、今は予約の状態を作る経路が無い。予約の経路を足すときは、
  確認の時刻と期限を必ず付ける。

## 6. 買取（手順16〜22）

- 買取商店: 家電のページ（Switch 2・PS5 Pro・AirPods Pro 3 で取得済み・同じ実行で使い回し）に、PS5 デジタル・
  エディション 日本語専用（CFI-2200B01）と Switch 2 マリオカート ワールドセット（日本語・国内専用）の行がある。
  どちらも上の §4 の理由（版が決められない）で加えていない。Xbox Series X の行は無い。
- iPhone 16 Pro の一覧のページには 16 Pro Max の行が無い（加えるには別のページの取得が要る。公式で販売終了なので
  利益の計算にも使えない）。
- モバイル一番・買取一丁目: 店のページの価格は参考のまま（確定にしない）。
- フジヤ: 新品同様（used_s）は中古系。新品の利益に使わない（テストで確認）。
- ネットオフ: 掲載の価格はクーポン・自宅集荷・箱の条件付き（+5%）。条件の無い価格が無いので取らない（テストで確認）。
- 結果: 確定の買取の商品は 9 のまま（増やせる行は版の特定が要る）。

## 7. TCG（手順23〜28）

- 予約（PREORDER）・先着（FIRST_COME）・再販（RESTOCK）・抽選は別の種類として判定する（`src/tcg/classify.py`。
  発売予定は再販にしない）。今の取得元から予約・先着・再販の実データは見つかっていない（0件）。
- ポケモンセンターオンラインは CI から HTTP 403（Phase 12〜13）。回避しない。人が公式ページで確認した記録
  （data/tcg_verified_lotteries.csv・human_confirmed）だけを公式扱いにする仕組みを使う（AI の転記だけなら公式扱いにしない）。

## 8. 検索（手順37・38）

商品に登録済みの検索用キーワード（config/products.yaml の keywords）を検索の対象に加えた（別名を新しく作っていない）。
「PS5」「PlayStation」「CFI-7000」で PlayStation 5 Pro、「GR IV」で GR IV 系、「iPhone 17」で iPhone 17 系が見つかる。

## 9. 残している点（Low）

- 集計のファネルの最後の段の名前 `actionable` は「掲載できる」の意味（Phase 11 の定義。在庫切れも入る）。今すぐ行動
  できる商品は `actionable_products`。定義を比べられるように段の名前は変えていない。
- 検索は部分一致なので、数字の型番（15286・S0001566 など）の一部や短い語で関係の無い商品も出ることがある。
- 運営者向けの外部 API の説明に、Finding API の頃の文言（EBAY_APP_ID の例・成約日時を保存していない）が残っている。
  Phase 14 は eBay を触らない指示なので変えていない。

## 10. 指標の追加

- 運営者向け（システム）に「データの網羅（定価・在庫・買取・TCG）」の欄。
- 診断（opportunity_diagnostics）に、定価の「公式で販売終了」の件数（sale_ended）と、今すぐ行動できる確定の利益商品
  （actionable: 掲載できる利益 ＋ 在庫ありの明示か予約。利益だけ・在庫切れ・在庫未確認・抽選は数えない）。
  集計（production_coverage_metrics）に actionable_products。ファネルの定義（Phase 11）は変えていない。
