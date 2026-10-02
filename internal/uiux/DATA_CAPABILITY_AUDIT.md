# データ取得能力の監査（2026-10-02）

> **位置づけ（2026-10-03 更新）**: 2026-10-02 時点の監査の記録（スナップショット）。ここに挙げた誤り（E1〜E7）は Phase 0 / 0.1 で修正済み。§4 のヤフオクは Phase 0.2 で「出品価格」と判明し、訂正した。現在の仕様は UI_VIEW_MODEL_SPEC.md と `src/market/price_types.py` が正本。

対象: commit `f684785a`（CI run 36949841607 の生成物）時点のコードと、`exports/` の実データ。
調査は読み取りだけで行い、コード・collector・利益判定は変更していない。
根拠はすべて `ファイル:行` で示す。推測には「推測」と書く。

前提:
- 本番は GitHub Actions だけで動き、1日1回 12:00 JST に実行される（`.github/workflows/daily_lp.yml:6`）。
- DB は実行のたびに `init-db` → `seed` → CSV の取り込みで作り直す（`daily_lp.yml:39,43,121-134`）。前回の値が残るのは、コミットされた CSV と `exports/*.json` だけ。
- `src/scheduler.py` の常駐スケジュール（買取 10/12/18 時、在庫 60分ごと）は CI では動いていない。
- ローカルの `data/premium_monitor.db` は 2026-08-24 時点の古いコピーで、本番とは別物。

---

## 0. 公開中の誤情報（UI 移行より先に直すべきもの）

今の公開 LP（`docs/index.html`、2026-10-02 11:37 生成）に、誤った値がそのまま出ている。どれも UI ではなくデータの問題なので、新UIに作り替えても直らない。

| # | 内容 | 根拠 | 公開 LP での出現 |
|---|---|---|---|
| E1 | 買取商店の誤価格。iPhone 17 Pro/Pro Max の4 SKU がすべて ¥435,000、Switch 2・PS5 Pro が ¥900,000（confidence=high） | `src/collectors/buyback_kaitori_shouten.py:80-115` の汎用フォールバック（ページ内の無関係な「買取価格」や最高値を拾う）。`exports/collector_report/latest.json` の suspicious_prices は18件 | ¥435,000 が13か所。ヒーローの「最高利益参考 +¥848,220」 |
| E2 | フジヤの下取り価格を現金買取として採用している（gfx100rf ¥521,400 = ¥474,000×1.1 など） | `scripts/update_camera_buyback.py:200-203` の `_TIER_RE` に、フジヤの表記「買取金額」が無い。`src/market/normalized_prices.py:112-131` の `is_tradein()` でも除外されない | ¥521,400 / ¥592,900 などが5か所 |
| E3 | フジヤで別の商品（限定版・キット）に誤マッチしている。gr4→30th Anniversary Kit、gr3→Street Edition、q3→Q3 43、m11→M11-P | `src/market/price_quality.py:73` の `_VARIANTS` に edition / kit / 43 / -P が無い | 買取価格として使用可の判定になっている |
| E4 | RICOH の公式価格が、GR IV / GR IV HDF / GR IV Monochrome の3商品とも ¥259,800 | `src/collectors/official/ricoh.py:196-200` の `first_on_page` フォールバック。検証は定価の 0.3〜3倍なら通る（`official_price_validator.py:165-168`） | 公式定価として使用 |
| E5 | Apple の公式価格がスクリプトに書かれた固定値なのに、毎回「今日確認した」扱いになる | `scripts/audit_official_sources.py:50-69`（価格の直書き）、`:177`（`last_verified_at=TODAY`）、`:186-190`（`official_price_updated_at=NOW`） | 公式定価として使用 |
| E6 | 手動データの観測時刻を、価格を変えずに新しくしている | commit `c214ea40`（2026-08-23）。`data/manual_market_prices.csv` の eBay sold 6行で、値は同じまま 07-22 を 08-22 に変更（`manual_buyback_prices.csv` も同様） | 鮮度の判定と「最終更新」に影響 |
| E7 | 誤価格を基準値にしたせいで、正しい値が除外される（公式定価 ¥194,800 や、買取一丁目の ¥172,000 が「付属品・別商品」扱い） | 基準値の計算（`normalized_prices.py:418`）が、重複衝突の検出（`:472`）より前に走る | 利益ルートが成立しない一因 |

品質ゲート（`daily_lp.yml:74-90`）は `continue-on-error: true` で、疑わしい価格を検出しても LP は公開される。CLAUDE.md の「FAILURE＝ワークフロー停止」と実装が食い違っている。

---

## 1. 小売（公式・正規店）価格

| source | 対象 | 実際の状態 |
|---|---|---|
| RICOH 公式（`src/collectors/official/ricoh.py`） | GR IV 系4商品 | CI で動いている。ただし E4 の誤マッチがある |
| FUJIFILM 公式（`fujifilm.py`） | X100VI | オープン価格なので price=null（正しい挙動） |
| Apple 公式（`apple.py`） | 設定は iPhone 16 Pro Max のみ | ページが 404 で取得できない。実際の値は E5 の固定値 |
| Canon / Nikon / Sony（`canon.py` / `nikon.py` / `sony.py`） | — | **動いていない**。`src/orchestrator.py:30-41` の COLLECTOR_MAP に入っておらず（`src/cli.py:123-145` とは食い違う）、URL も未登録 |
| Nintendo・PlayStation・PC メーカー・量販店 | — | `config/sources.yaml` に定義があるだけで、collector は無い |
| 楽天 / Yahoo API（`src/collectors/api/official_apis.py`） | — | モールの新品出品価格の中央値で、公式定価ではない。キーが未設定で、kill-switch により無効 |

項目ごとの保持状況:
- `observations` テーブル（`001_initial.sql`）には price・is_in_stock・observed_at がある。**url・condition・variant・capacity の列は無い**（URL は raw_text の JSON の中だけ、容量は product_id で表すだけ）。
- `normalized_prices.py:280-296` が、公式価格の observed_at に生成時刻を入れる（鮮度が常に「今」になる）。

実データ（`exports/normalized_price_observations/latest.json`）:
- official 45件。Web から実際に取れているのは RICOH の4件だけ（その4件も E4）。
- Apple の9件は固定値。残り32件は `config/products.yaml` の手入力の定価。

## 2. 買取価格

- **携帯・ゲーム機の自動取得**（`scripts/update_buyback_prices.py:61-107`）
  - 対象は6商品（iPhone 17 Pro / Pro Max の 256GB・512GB、Switch 2、PS5 Pro）× 16店。
  - 同一性の判定は店ごとのキーワードと正規表現で、JAN は 0件、型番は 22/45件。
- **カメラ**（`scripts/update_camera_buyback.py`）
  - 取得先はマップカメラ・フジヤ・キタムラの3店。
  - 今日の結果は、OK 20/60 で全件がフジヤ。マップカメラとキタムラは site_blocked。
- **condition（状態）**
  - ページから読み取らず、設定値をそのまま割り当てている（`buyback_base_csv.py:43,73`）。
  - 値は `new_unopened` / `new_unopened_simfree` / `used_a` だけで、中古の B/C ランクは無い。キャリア版も区別していない。
- **サンプル数**: 1店 = 1価格。最低件数の要件は無い。
- **成功率**: 13/55（23.6%）。12店が連続して失敗中（`exports/data_quality_report/`）。
- **失敗時**: price=0 と `fetch_failed` で記録し、前回の値は引き継がない。ただし観測時刻に「失敗した時刻」が入り、「最終更新」に混ざる（`src/db/repository.py:1146-1155`、`update_buyback_prices.py:269-343`）。
- **重複**: 常駐スケジューラ用の collector（`src/collectors/buyback/`）と、CSV 用（`src/collectors/buyback_*.py`）が二重にある。

## 3. 二次流通の出品価格（listing）

| source | 中身 | 根拠 |
|---|---|---|
| メルカリ | 出品中（`status=on_sale`）、新品・未使用、Playwright で取得。今日は blocked_cloud_ip | `scripts/collect_resale_prices.py:458-463` |
| ラクマ | 売り切れ・状態のフィルタ無し。blocked | `:782-786` |
| 楽天 / Amazon | 新品のショップ価格 | `:354-358`, `:680-684` |
| 手動 CSV（`manual_market_prices.csv`、`manual_sale_prices.csv`） | 58行。すべて 8/12〜8/22 で、14日を過ぎて stale | — |

- **出品の最安値・最高値は保存していない**。各 source の中央値1つだけ（`collect_resale_prices.py:383,483,621,721,813`）。listing_count も無い。
- **タイトル照合が無い**。検索結果ページ全体の価格を集計している。
- **出品価格と成約価格の混同（Critical）**
  - `src/market/comparator.py:49-52` が、price_type="used" の最大値をプレ値として使っている。
  - "used" には、メルカリ出品・メルカリ成約・中古ショップの販売価格が混ざっている。
  - "used" が無ければ、定価超えの小売価格で代用する（`:61-67`）。

## 4. 成約価格（sold）— 最重要

| 経路 | 方法 | 本番の状態 | 有効件数 |
|---|---|---|---|
| ~~ヤフオクの落札検索~~ **ヤフオクの出品中の一覧**（`collect_resale_prices.py`。Phase 0.2 で訂正） | ~~落札検索の HTML（20件）の中央値~~ 実際は `/search/search` の出品中の一覧（「現在 …円」「残り …日」）。さらにページ全体から数字を拾い、カテゴリ ID なども混ざっていた | **成約データではない**。Phase 0.2 で LISTING（出品価格）に直し、出品ごとの属性だけを読むようにした | 成約としては0件（2026-10-02 時点の記録では「カメラの5件だけ使用可。iPhone 17 Pro と Pro Max が同額」。これは Pro の検索に Pro Max の出品が混ざっていたため） |
| 手動の成約 CSV（`data/manual_flea_sold_prices.csv`） | 人手で記入 | **item_url が連番のダミー**（`x000000001` など。`:9-15`）。全7行が 14日超 | 0 |
| eBay の Finding API（`src/collectors/overseas/ebay_completed.py:286-338`） | findCompletedItems | EBAY_APP_ID 未設定、kill-switch で無効 | 0（手動6件はすべて stale） |
| メルカリの成約 | — | **NOT_IMPLEMENTED**（規約上、手動以外は不可） | 0 |
| ラクマの成約 | — | **NOT_IMPLEMENTED** | 0 |

- 集計期間・成約件数を正しく出せる経路は、今のところ無い（成約日を持たず、14日の判定は取得日が基準）。
- **中央値**: 実装はあるが、`prices[len//2]` で上側の値を取る（`collect_flea_sold_prices.py:203`）。最低サンプル数の要件は無い。
- **型の取り違え**
  - eBay の成約価格が「出品価格（buy 側）」に分類されている（`normalized_prices.py:99`）。
  - 逆に、API の出品価格に「成約価格（sell）」の型を付けるコードがある（`scripts/collect_api_prices.py:169-170`。今は無効化されている）。
  - price_basis が空の eBay を成約とみなす推測もある（`normalized_prices.py:377`）。
- **海外の売値の水増し（Critical）**
  - 海外価格に「送料3000円＋輸入税10%」を足して保存している（`src/market/csv_importer.py:149-152`、`src/collectors/price/ebay.py:71-76`）。
  - その値を、売り側の海外成約価格として使っている。
- 推測（要確認）: eBay の Finding API は廃止が告知されている可能性がある。キーを入れても動かないかもしれない。

**結論: 合意済み設計の「想定売値＝最近の同一商品の成約中央値（期間・件数つき）」に使える成約データは、実質 0。**
新UIでは、ほぼすべての「正規→二次」「二次→二次」ルートが「成約価格 未取得 / 想定利益 算出前」になる。

## 5. 在庫・再入荷

- **一般商品の在庫監視は CI で動いていない**
  - ヨドバシ・ビックの collector は、常駐スケジューラか `run-stock-check` からしか呼ばれない。
  - 本番の在庫観測は 0件。
- 公式 collector の在庫判定:
  - Apple は、本文に「購入」があれば在庫ありとする（`apple.py:172-177`）。実質いつも True。
  - RICOH は、不明（None）を在庫ありとして保存する（`ricoh.py:107`）。
  - `src/pipeline/normalizer.py:105` は「予約受付中」を在庫ありとして扱う。**予約と在庫を混同している。**
- **`restocked_at` / `last_checked_at` の項目は、リポジトリのどこにも無い**。在庫復活は前回の観測との比較で出す設計（`scorer.py:138-140`）だが、DB が毎回作り直されるので成立しない。
- TCG は丁寧に作られている（`src/tcg/models.py`、`src/tcg/freshness.py`）。
  - TTL は EC 15分、店頭 2時間。
  - sold_out は不明なら None、購入制限は記載が無ければ None。
  - ただし実データは、restock 0件・available_now 0件。PCO は HTTP 403。
  - LP は1日1回の生成なので、TTL 15分の「今買える」が24時間表示され続けるおそれがある（推測。今は該当0件）。

## 6. 抽選（Phase B 時点で正常）

- **状態**: UPCOMING / OPEN / ENDING_SOON / CLOSED / RESULT_PENDING / WINNER_ANNOUNCED / WINNER_PURCHASE_PERIOD / ENDED / UNKNOWN（`src/tcg/lottery/schema.py`）。新UIでは SOURCE_CONFLICT を加え、閲覧時に判定し直す（`src/content/ui/runtime.py`・`lottery_runtime.js`）。
- 人による確認（`human_confirmed`）、公式 URL の判定、閲覧時の期限切れは、Phase B の本番確認で正常だった。
- **実データ**:
  - TCG 抽選は6件。PCO の手動転記2件（確認待ち）と、GEO の4件（終了済み）。
  - 旧来の抽選（`data/lottery_events.csv`）は8件で、すべて終了済み。
- **問題（High）**: 旧来の抽選の RICOH の定価が固定値なのに、`data_source=auto_scraped` と表示されている。同じ行の抜粋には「定価 ¥299,800」とあり、矛盾している（`src/collectors/lottery/ricoh.py:29-41`）。

## 7. 予約・発売予定・公式発表

- **TCG**
  - ポケモン公式の商品 API から17商品、ONE PIECE 公式から4商品を、発売日つきで取得している。
  - 月までしか分からない日付は None / UNVERIFIED にしていて、推測で埋めていない。
  - 「予約開始日」専用の項目は無い。
- **TCG 以外: NOT_IMPLEMENTED**
  - `config/new_product_watchlist.yaml` は手動の候補リストで、未発表の価格を推測で書いている（例: iPhone 18 Pro ¥189,800）。
  - `src/market/new_product_scanner.py` がその推測値を `product_candidates.official_price` に保存している（LP には出ていない。Streamlit だけ）。**合意済み設計の「未発表値を推測しない」に反する。**

## 8. 鮮度

source ごとの表は DATA_SOURCE_MATRIX.md にまとめた。要点:

- **しきい値**
  - 買取・二次流通は、表示 24h / 48h、利益判定 7日で「要更新」、14日で除外（`daily_lp_generator.py:6680-6735, 6974-7024`、`normalized_prices.py:20`）。
  - 海外は 48h（`base_overseas.py:12`）。
  - TCG は種別ごとの TTL（`freshness.py:24-30`）。
- **鮮度を良く見せてしまう実装**
  - E5・E6（固定値や時刻の書き換え）。
  - 公式価格の観測時刻を「今」にする（`normalized_prices.py:280-296`）。
  - 空の観測時刻を現在時刻で埋める（`buyback_csv_importer.py:129` ほか3か所。今は該当0行）。
  - 海外価格は stale でも選ばれる（`overseas/orchestrator.py:111-132`）。
- **鮮度の表示**
  - トップの鮮度バナーは中身が無い（`daily_lp_generator.py:4405-4412`）。
  - 「最終更新」は 24h を超えると消え、古いことも知らせない（`:586-592`）。
  - 新UIの「更新 MM/DD HH:MM」は LP の生成時刻で、データの観測時刻ではない。
- **データ品質の集計が実態より良く見える**
  - `scripts/generate_data_quality_dashboard.py:40-44` が、required の4店を「対象外」として数え、real_failures=0 になる。
  - 同一性の監査は精度 1.0 と出るが、実際に独立して確認できた件数は 0（`audit_source_matching.py:192-205`）。

## 9. 同一商品の照合

- **ProductIdentityResolver**（`src/market/product_identity_resolver.py`）
  - JAN → SKU/MPN → 型番 → 機種名 → 容量 → variant の順で照合し、機種名だけなら medium にする設計で、合意済み設計の考え方に合う。
  - ただし**使っているのは API・canary・監査の経路だけ**で、本番の買取・二次流通・`normalized_prices.py` は通っていない。
- **本番の照合**（`normalized_prices.py:140-512`、`price_quality.py:121-143`）
  - 見ているのは、付属品の語、基準値の50%フロア、variant・世代、同額の衝突。
  - **色・付属品（ボディ/キット）・キャリア版・限定版・状態は見ていない。**
- テスト（`tests/test_source_matching.py`）は16件。限定版・キット・下取りの段のテストは無い。

## 10. 利益計算

詳細は UI_VIEW_MODEL_SPEC.md の「利益計算」の節にある。現状は**8系統以上の計算があり、統一されていない**。

- 売値の種類、費用（1800 / 1300 / 1500＋安全マージン / 13%＋3500 / 20%＋5000＋安全マージン）、ROI の分母（定価 / 仕入価格 / 投下額）がばらばら。
- 購入送料・購入時の必須費用はどこにも無い。
- メルカリの販売手数料 10% は、LP に関わる計算に一つも入っていない（`src/pipeline/scorer.py:211` だけ）。
- 同じせどりタブに、2種類の利益定義（`generate_profit_routes.py` と `sedori_route_calculator.py`）が並んで出ている（`daily_lp_generator.py:5399-5401`）。
- `sedori_route_calculator.py:165` は eBay 売りの手数料を引いていない。
- 「正規→二次流通（フリマで売る）」と「二次→二次」は**未実装**。ラベルだけがある（`generate_ranking_report.py:179,182`）。
- 新UIの HOME は「手数料込みの見込み」と書いているが、国内ルートは手数料0で、安全マージンを引いているだけ（`src/content/ui/home.py:201`）。

## 11. 一般向けの画面に出ている運営者向け情報

Health タブ、collector-warn、取得統計（「取得失敗 36件」）、フッターのデータ取得状況（生のエラーコード）、TCG の監視元の表（HTTP 403）、`EBAY_APP_ID` の案内、`gh workflow run` などが出ている（`daily_lp_generator.py:5301, 5760-5927, 9361-9475, 4683-4706, 6152-6162`）。

公開ディレクトリ `docs/` には、`docs/HANDOFF.md`（運用メモ）と `collector_report.html` もある。新UIは段階Bでこれらを出していないが、`/admin/` への移動はまだしていない。
