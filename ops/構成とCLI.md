# 構成と主要CLIコマンド

`CLAUDE.md` から移した参照資料。コマンドを実行する前に該当箇所を読む。

## ディレクトリ構成
```
config/           設定 (products.yaml, sources.yaml, lp_settings.yaml, fx_rates.yaml)
data/             SQLite DB, CSV (manual_buyback_prices.csv, manual_market_prices.csv)
src/
  cli.py          全CLIコマンド (~2300行)
  scheduler.py    APScheduler (10:00/12:00/18:00 JST買取ジョブ + 60分在庫)
  orchestrator.py 全体オーケストレーション
  collectors/     公式/価格/在庫/買取 Collector
  db/             Database, Repository, migrations/ (001-009)
  models/         Pydantic (product, observation, alert, market_snapshot, buyback_price, beginner_deal等)
  market/         MarketComparator, PremiumDetector, BeginnerDealScanner, ProfitSimulator, BuybackChangeDetector
  pipeline/       Scorer, Dedup, AlertDispatcher, QualityChecker, PrelaunchChecker
  publish/        TemplateGenerator, ReportGenerator
  content/        NoteGenerator, LPGenerator, DailyLPGenerator, LINEMessageGenerator, CommunityMessageGenerator
  notifiers/      Log/Discord/Telegram + routing.py
  jobs/           BuybackPremiumJob (統合ジョブ)
dashboard/        Streamlit (01-19ページ)
scripts/          build_public_lp.py, deploy_check.py
exports/          note_reports/, lp/daily/, line_messages/, community_messages/, simulations/
docs/             GitHub Pages公開用 (index.html, archive/, sitemap.xml, robots.txt)
.github/workflows/daily_lp.yml
```


## 主要CLIコマンド
```bash
# 初期設定
python3 -m src.cli init-db
python3 -m src.cli seed
python3 -m src.cli import-buyback-csv --file data/manual_buyback_prices.csv

# 毎日の運用
python3 -m src.cli run-buyback-premium-check    # 統合ジョブ(10工程一括)
python3 -m src.cli generate-daily-lp --variant A # LP生成
python3 -m src.cli build-public-lp               # public/へビルド
python3 -m src.cli deploy-check-lp               # 公開前チェック
python3 -m src.cli prelaunch-check               # 本番前チェック

# 個別操作
python3 -m src.cli scan-beginner-deals           # 初心者案件スキャン
python3 -m src.cli list-beginner-deals           # 初心者案件一覧
python3 -m src.cli compare-buyback --product iphone17pro256  # 買取比較
python3 -m src.cli simulate-profit --product iphone17pro256  # 利益シミュレーション
python3 -m src.cli validate-data                 # データ整合性チェック
python3 -m src.cli scan-category --category all  # カテゴリ横断スキャン

# Streamlit
streamlit run dashboard/app.py
```

## 新商品・新しいイベントの発見（Phase 27）

```bash
python3 -m src.cli discover                       # Apple 公式（iPhone）と TCG の生成物から候補を作る（CI の手順と同じ）
python3 -m src.cli discover --skip-apple          # Apple を読まない（TCG の生成物だけ）
python3 -m src.cli approve-product-candidate --candidate-id <ID> --checked official_url --checked part_numbers \
    --checked capacity --checked official_price                  # 承認（台帳に記録するだけ。正本には入れない）
python3 -m src.cli reject-product-candidate --candidate-id <ID> --reason not_target   # 却下（台帳の候補は理由が必須）
```

- 候補の台帳は `exports/discovery/product_candidates.json`（新商品）・`event_candidates.json`（告知・イベント）・`latest.json`（集計）。
  CI の生成物のコミットに入る。中身は既存の `product_candidates` の表にも写す
- 正本（`config/products.yaml`・products の表）には自動で入れない。承認しても台帳に記録するだけ。正本への登録は
  下の「候補の確認と正本への登録（Phase 28）」の手順で、人が1件ずつ行う
- Apple は購入の一覧から機種のページを見つけ、1回の実行で最大2機種のページを読む（間隔120秒。新しい機種が先）。正本の
  「機種 + 容量」と照合し、正本に無いものを確認待ち（PENDING_REVIEW）にする。色はまとめる
- TCG は新しい取得をしない。日程の無い告知・予約 / 先着 / 再販のタイトルは「告知・日程なし（要確認）」。日程は推測しない
  （画像の文字を読まない）。TCG は利益・今すぐ行動・通知に接続しない

## 候補の確認と正本への登録（Phase 28）

承認と登録は別のもの。承認（APPROVED）は「人が公式ページで、この候補は正しい商品だと確かめた」。登録（REGISTERED）は
「正本に入れた」。承認だけでは正本・DB の seed・買取の照合・公式の登録簿は変わらない。

```bash
# 1. 承認（確かめた証拠を --checked で記録。正本への登録には official_url が要る）
python3 -m src.cli approve-product-candidate --candidate-id <ID> --checked official_url --checked part_numbers \
    --checked capacity --checked official_price
# 2. 見込み（dry-run。既定。新しい product_id・正本の差分・監視への影響を表示。何も書かない）
python3 -m src.cli register-product-candidate --candidate-id <ID>
# 3. 登録（config/products.yaml に1件だけ書き、台帳を REGISTERED にする。commit / push はしない）
python3 -m src.cli register-product-candidate --candidate-id <ID> --confirm
# 4. 差分を見てから、表示された2つのファイルだけをコミットし、CI の実行中でないことを確かめて push
#    git push origin tcg-push:main
```

- 登録できるのは: 承認済み（公式ページで official_url・part_numbers・capacity・official_price を確かめた記録あり）・7日以内に公式で見た（STALE でない）・Apple 公式の候補（URL・
  日本向けの部品番号・機種と容量・色で変わらない1つの価格）・正本に重複なし（product_id・機種 + 容量・部品番号）。TCG の
  商品は既存の正本に入れない。JAN があれば JAN の重複も見る。1回のコマンドで1件だけ（一括の登録は無い）
- `--confirm` は手元の正本が main と同じで、手元の台帳が main の台帳と「この候補の記録（手元の承認）」だけ違うときに
  書く（承認を先に push しなくてよい。ほかの候補が違う・main でこの候補の価格や部品番号が変わった・main で却下 /
  登録済みになったときは止まる。`git checkout -- exports/discovery/product_candidates.json` と `git pull` の後に
  承認をやり直す）。承認と登録は1件ずつ続けて行う（2件を手元で承認してから1件目を登録しようとすると、もう1件の違いで
  止まる）。書き込みは確かめてから一時
  ファイル経由で置き換える（途中で失敗しても正本は元のまま）
- product_id は既存の規則（`prod_iphone17pm_256`・TB は `prod_iphoneduo_1tb`）。name は「機種 容量 SIMフリー」、
  model_number は空（色ごとに部品番号が違うので、部品番号の組を `part_numbers` に持つ）。keywords の先頭は容量つきの名前・
  部品番号は後ろ（検索用）。retail_price は発見した公式の価格を設定値の参考価格として入れる（`price_observed_on` が公式で
  見た日）。公式直販価格の確定（`official_registry` の証拠）・在庫・買取の取得の対象は登録しない（人が確かめて別に足す）
- 登録した商品は、買取・販売の観測が無いうちは利益・今すぐ行動・通知に出ない。新商品の登録を理由に通知しない
- 次回の発見は、その「機種 + 容量」を正本と一致として扱い、新しい候補を作らない（台帳は REGISTERED のまま）
- 取り消すとき: コミット前は `git checkout -- config/products.yaml exports/discovery/product_candidates.json`。
  コミット後は正本（`config/products.yaml`）のその1件の差分だけを戻してコミットする（台帳は CI の生成で変わるので
  `git revert` すると衝突しやすい。台帳は戻さない）。次の `discover` が、機種のページを読むかに依らず、正本に無い
  登録済みの候補を確認待ち（`registered_not_in_canonical`）に戻す。それまでの間は deploy-check #863 の対応の項目が
  warning になる（CI は止めない）
- 正式なイベント（MATCHED_EVENT。自動で集めた抽選）は承認・登録しない（手動の CSV に重ねない）
- STALE の候補は承認・登録できない（公式で見つけ直されて確認待ちに戻ってから）。却下（REJECTED）は理由とともに残り、
  見つけ直しても確認待ちに戻らない（取り消すときは承認し直す）

TCG の告知（日程の無い告知）:

```bash
python3 -m src.cli approve-event-candidate --candidate-id <ID> --checked schedule --checked official_url
python3 -m src.cli register-event-candidate --candidate-id <ID> --product "<公式ページの商品名>" \
    --start 2026-10-20T12:00:00+09:00 --end 2026-10-23T16:59:00+09:00 --official-page-checked   # dry-run
# 同じコマンドに --confirm で data/tcg_verified_lotteries.csv に1行（human_confirmed=true）
python3 -m src.cli reject-event-candidate --candidate-id <ID> --reason obsolete
```

- 日程は運営者が公式ページで確かめた値だけ（`+09:00` つきの ISO8601。推測しない・画像の文字を AI が読んだ値を
  使わない）。終わった日程・1年より先の日程は登録しない。
  抽選・予約だけ（先着・再販は CSV の種類に無いので登録しない）。受付中かどうかは日程と今の時刻から決まる（登録で受付中に
  しない）。同じ店・同じ開始で、同じ URL か正規化した商品名が同じ抽選（手で確認した CSV・自動で集めた抽選）は重ねない。
  登録した行は公式確認済み（human_confirmed=true）として LP の抽選の表示・抽選の通知の候補に入る（外部には送信しない）
- 登録した告知の照らし合わせは「店|URL」で行う（延期で開始日時を直しても確認待ちに戻らない）。同じ告知の URL で複数の
  商品を登録したときは、1行を外しても台帳は登録済みのまま（外すときは台帳の候補も確かめる）
- CI の生成コミットが取り込みで衝突したとき、発見の台帳（人の判断が入る）は CI の側で上書きせずに止める。CI の実行中に
  台帳・正本を push しない
- 運営者向けの画面「新商品・新しいイベントの発見」は見るだけ（登録のボタンは無い）。確認待ち・承認済み・登録済み・却下・
  STALE の件数と、上の手順を表示する

## 登録した商品の公式直販価格と買取（Phase 29）

登録（Phase 28）は正本に入れるだけで、公式直販価格・買取・利益は付かない（設定値の参考価格・未取得・未算出）。利益の判定に
つなぐには、商品ごとに次を人が確かめて足す（1件ずつ。詳細は `internal/audits/PHASE_29_ACTIVATION.md`）。

- 公式直販価格: 公式の購入ページで、正本の part_numbers の全色が同じ価格であることを確かめ（取得の共通の作法で1回取得するか
  ブラウザで確認）、`src/market/official_registry.py` の VERIFIED_URLS・IDENTITY_EVIDENCE（色違いの部品番号の組）・
  OFFICIAL_DIRECT_OFFERS（在庫は UNKNOWN）に確認日つきで入れる。`scripts/recheck_official.py` の RECHECK_TARGETS にも入れる
  （価格が変われば changed で確定に使わない・14日で古くなる）
- 買取: 既存の買取商店の一覧で、行ごとに機種・容量・SIMフリー・部品番号まで照合できるときだけ
  `src/collectors/buyback_kaitori_shouten.py` の PRODUCT_URLS・ROW_RULES（parts・color_policy=min）と
  `scripts/update_buyback_prices.py` の TARGET_PRODUCTS に入れる（KEEP_PREVIOUS_ON_FAILURE には入れない）
- 利益は既存の計算のまま。売値が安ければ no_profit、在庫が不明なら今すぐ行動できない。deploy-check #864 が検査する

## 候補の優先順位（Phase 30）

```bash
python3 -m src.cli rank-product-candidates                     # 取得なし（買取は UNKNOWN のまま点を付ける）
python3 -m src.cli rank-product-candidates --fetch-buyback     # 買取商店のまとめ1回 + 上位の機種の価格表1回
```

- 点は決まった計算式（`src/discovery/priority.py`。内訳は `internal/audits/PHASE_30_PRIORITY.md`）。売値は取得した実際の
  行だけ（他の容量・予想の価格で埋めない）。色で価格が違えば最も低い色。全色がそろわなければ差を出さない
- 結果は `exports/discovery/priority.json`（取得したときだけ書く）。運営者向けの「候補の確認の順番」に出す（顧客向けの利益では
  ない・作成から7日で表を隠す）ために、人が差分の各候補の buyback_rows（店の行・価格・商品ページ）を確かめてコミットする。
  CI では作らない。同じ取得元へは前回の取得から 90秒以内（ブロックの後は24時間）は取得しない
- 登録は上の承認 → 見込み → 登録の手順で1件ずつ（優先順位は登録しない）。登録した後の公式直販価格と買取は「登録した商品の
  公式直販価格と買取（Phase 29）」の手順

## 利益の式・買取の比較の基準・運営者向けの劣化アラート（Production Integrity 是正）

- **利益の式は1つ**: `src/market/profit_formula.py`（費用 = 買取店への発送 + 振込手数料 + 移動・持ち込み + 保険 + 購入送料。購入送料が
  分からなければ載せない）。案件のスキャナー・候補の優先順位・順位レポート・健康度が同じ式・同じ関門
  （`confirmed_official_to_buyback`: 確認済みの公式価格・確定の売値・送料が分かる）を使う。順位レポートに固定の費用を持たない。
  載せなかった商品は `exports/ranking_report/latest.json` の `ineligible_items` に理由つきで残る
- **買取の「前回との比較」の基準**: `exports/collector_report/price_baseline.json`（`src/collectors/price_baseline.py`。
  直近の正常な自動取得の値・14日以内。手入力 / 取得失敗 / 隔離した行は入れない。CI が commit する）。基準が無い組（初めての観測）は
  前回比を出さない。前回比 ±20% は警告だけで隔離の理由にしない。手入力の CSV（`data/manual_buyback_prices.csv`）は基準にしない
- **カテゴリ共通の価格の上限**（GENRE_PRICE_RANGES）は目安で、単独の店の値は採用しない: 上限を超える値は、その行が商品ページの URL
  （`/detail/<番号>` など、マーカーの直後が識別の番号）・照合済み・信頼度 high / medium と自動取得が明示・公式の 1.5 倍以内で、別の店の行（ホストも URL も別）が
  同水準（±10%）かつ同じ条件のときだけ採用（`above_genre_max_corroborated`。劣化アラートの price_adopted_over_ceiling に出る）。
  店のトップ・一覧ページの根・複製は裏付けにならない。1つでも欠ければ隔離（要確認）。3 倍以上・ゲーム機のスマホ価格帯・容量の逆転・
  下限未満は、裏付けがあっても隔離
- **公式の再確認**: `scripts/recheck_official.py` の `RECHECK_PAGE`（購入ページとは別に、価格を読むページ）。PS5 Pro は Sony Store の
  商品ページ（購入ページ `_purchase` は在庫が無い間 E_NOTFOUND へ移る）、Switch 2 は任天堂の商品ラインナップ（My Nintendo Store は
  待機室へ移るので取らない・回避しない）。結果の `url` は記録（`VERIFIED_URLS`）の URL のまま、読んだページは `fetched_url`・何を確認したかは `verified_by`
  （Switch 2 は `msrp_lineup` = 希望小売価格だけ。購入ページ・在庫は未確認なので、価格の変化の検知には使うが確認日は進めない。
  人がブラウザで確認したときだけ延びる）
- **運営者向けの劣化アラート**（商品の通知とは完全に別。外部へ送らない）:

```bash
python3 scripts/operator_health_alert.py            # exports/ops/health_alert.json・health_alert_state.json を書く
python3 scripts/operator_health_alert.py --dry-run  # 書かずに注記だけ見る
```

  必須の店の連続失敗（既知のブロックは WARNING・予想外の理由は HIGH）・今日から取れなくなった必須の店・必須の店の失敗率・品質ゲート・
  公式の確認の期限（3日以内）・公式の再確認の連続失敗（3日 = WARNING・7日 = HIGH）。新しい・重くなった・復旧のときだけ CI の注記と
  Step Summary に出す（同じ異常は出し直さない）。管理画面の取得状況の先頭にも出る。CI では Collector quality gate の直後
- **失敗の数え方**（`collector_report/latest.json` の `counters`・`counter_definitions`）: `rows_failed`・`quality_rejected`・
  `rows_skipped`・`sources_failed`・`requests_failed` は別の指標。品質ゲートの「取得失敗率」は (rows_failed + quality_rejected) ÷ rows_total
- **定時の実行**: cron は 12:17 JST（UTC 03:17）。毎時 0 分は GitHub Actions が混み、毎日 4〜7 時間遅れて始まっていた。頻度は上げない

## 調査候補・TCG の取得元の分類（Market Research Foundation）

- 調査候補（`src/research/candidates.py`）は**確定の利益ではない**。確定の判定（`opportunity.eligibility`）で外れた商品のうち、
  生の価格差（売値 − 買値）がある商品を、足りないもの（公式の価格が未確認・売値が古い・店のトップの URL・照合が未了・
  費用不明…）つきで残す。**個別の候補は公開しない**: `.private/research/`（`.gitignore` 済み・commit しない。latest.json・台帳 state.json・
  買取の一覧 buyback_catalog.json）。公開してよい集計（件数・理由別・ジャンル別・網羅性）だけ `exports/research/summary.json`。
  台帳は、Secrets の `RESEARCH_LEDGER_KEY` があるときだけ暗号化して Actions のキャッシュで引き継ぐ（無ければ毎回新しく作る）。管理画面は公開サイトに埋め込まれる（誰でも開ける）ので集計だけを出す。元になる観測は既存の公開の成果物に含まれる。顧客の画面・LP・商品の通知には出さない（deploy-check #871）
- 買取商店の一覧から、正本に無い商品を逆引きする（JAN・部品番号だけで照合。名前だけでは正本にしない）。登録は既存の
  「候補の確認と正本への登録（Phase 28）」の手順で人が行う
- TCG の取得元は `source_class` で分類する（WORKING / IMPLEMENTED_BUT_BLOCKED / ACCESSIBLE_UNIMPLEMENTED / UNREACHABLE /
  UNSUPPORTED）。遮断された取得元は回避しない。監視していない売り場の候補は `config/tcg_source_candidates.yaml`（未確認。
  実装の前に robots・規約・公開ページを確認する）。定価の台帳は `exports/tcg/msrp.json`（パック価格から BOX の価格は作らない）
- 設計の全体と残りは `internal/audits/MARKET_RESEARCH_FOUNDATION.md`

## Coverage Wave 1（調査候補の網羅性・TCG の取得元）

- 台帳の状態（`ledger_state`）: NOT_AVAILABLE（鍵なし・保持の手段なし）/ NEW_THIS_RUN / REUSED_WITHIN_RUN（同じ実行の再生成）/ RESTORED_FROM_PREVIOUS_RUN / CORRUPT。
  初めて見た日（first_seen）が実行をまたいで意味を持つのは RESTORED_FROM_PREVIOUS_RUN のときだけ（`first_seen_scope`）
- 隔離された買取価格（上限超え。急変は収集側が rejected にしないため対象外）は、調査候補（HIGH_PRIORITY_RESEARCH）として残す。確定にはしない・ジャンルの上限は自動で引き上げない
- TCG の取得元: カードラボ（`src/collectors/tcg/lottery/clabo.py`。店舗ブログの抽選。応募は店舗の X で `entry_url` は空）。
  受付中が 0 件でも市場に無いとは断定しない（`announcement_funnel`・`zero_active_interpretation`）
- 公開成果物の商品単位データの一覧: `python scripts/inventory_public_raw_data.py --write`（削除・変更はしない）

## Coverage Wave 2（買取起点の選別・小売の価格の照会・TCG の取得元）

- 買取起点の候補: `src/research/triage.py` が HIGH / MEDIUM / LOW / REJECTED に分け、上位 50 件の待ち行列を作る（決まった規則だけ。
  AI の予測価格は使わない）。公開してよいのは件数だけ（`buyback_triage`・`buyback_first.top_queue` など）
- 小売の価格の照会: 定時の CI の「Research retail lookup」step が `python scripts/research_retail_lookup.py` を実行
  （取得は `scripts/recheck_official._fetch` の polite 経由だけ。結果は `.private/research/retail_lookups.json`。標準出力は件数だけ）。
  取得器は `src/research/retail_lookup.py`（`ADAPTERS`）。**JAN・型番・部品番号の完全一致だけ**で結び付け、販売終了の価格は仕入れ値にしない。
  記録の生成時刻・各結果の取得時刻が 36 時間以内のときだけ `build()` が使う
- 取得器を足すとき: `RetailAdapter` を継承し、`parse_index`（一覧を取る型）か `item_url` / `parse_item`（商品ごとの型。`MAX_ITEMS` で上限）を実装する。
  robots・規約・ページ構造を取得日つきで確認してから。403・遮断は回避しない
- TCG の取得元: ホビーステーション（`src/collectors/tcg/lottery/hbst.py`。公式お知らせの抽選告知。応募は外部で `entry_url` は空）。
  一覧のカードを 1 件も読めない取得元は `structure_changed_pages` で PARSER_DEGRADED（DEGRADED）になる
- 設計の全体と残りは `internal/audits/COVERAGE_WAVE2.md`

## Coverage Wave 3（仕入れ価格の発見・TCG の質）

- 仕入れ値の証拠: `retail_lookup.price_evidence`。**ポイント・キャッシュバックは現金から引かない**（別の項目）。クーポン・キャンペーン・会員限定・数量限定の値引きは
  現金の仕入れ値に使わない（通常の価格が分かればそれを使う。分からなければ高優先にしない）。誰でも即時の値引きだけ反映する
- 取得器を足すとき: `source_type`（OFFICIAL_DIRECT / AUTHORIZED_RETAILER / LARGE_RETAILER / EC_RETAILER / OUTLET / SECONDARY_NEW）を決め、一覧の行に
  `price`・`regular_price`・`immediate_discount`・`required_coupon`・`points`・`campaign_conditions` を分けて入れる。JAN・部品番号の完全一致だけで結び付ける
- Canon: `config/canon_codes.yaml`（JAN ↔ 商品コード。公式の製品ページで確かめた行だけ・許可リスト方式）。行を足すときは公式の製品ページの「JANコード」「商品コード」を根拠にする
- TCG の取得元: キッズリパブリック（`kidsrepublic.py`）・福福トレカ（`fukufuku.py`）。取りこぼしは `detail_candidates` / `detail_fetched` / `skipped_due_to_limit` / `skipped_ended`
- 受付中イベントの質・優先順位・検知の許容: `src/tcg/event_quality.py`（初めて見た時刻を保持していないので `first_seen_available = false`）
- 設計の全体と残りは `internal/audits/COVERAGE_WAVE3.md`

## Coverage Wave 4（公平な取得枠・Apple の同一性）

- 小売の照会の取得枠: `retail_lookup.allocate_budget`（`HTTP_BUDGET = 24`・`ITEM_MIN = 3`）。商品ごとにページを取る取得器は**全候補から**点の高い順に選ぶ。取得器を足すときは
  `MAX_ITEMS`（上限）と `item_key`（型番・JAN → キー）を決める。最低枠は全ブランドに 1 件ずつ → 最低枠まで → 余りを点の高い順
- Apple: 部品番号の完全一致 + 容量・世代の一致で `IDENTITY_CONFIRMED`。食い違えば `IDENTITY_MISMATCH`。JAN は一次根拠が無いので追加しない
- ソフマップ: `config/sofmap_products.yaml`（人が詳細ページで確かめた JAN ↔ sku だけ）。検索・一覧は使わない
- 仕入れ元 API（Yahoo!ショッピング `YAHOO_SHOPPING_APP_ID`・楽天 `RAKUTEN_APP_ID`）: 鍵が無ければ PENDING_USER_CONFIGURATION。鍵を設定しても実装は未（`READY_NOT_IMPLEMENTED`）
- TCG の取得枠: `src/tcg/lottery/budget.py`（総数 40・最低 4・枠の小さい取得元から先）。取得元の状態は `health_flags`（LIST_OK / DETAIL_OK / BLOCKED / PARSER_DEGRADED / TRUNCATED）
- 麦わらストア: `src/collectors/tcg/lottery/mugiwara.py`。クラウド IP から遮断されたら WORKING に数えない
- 変異テスト: `python3 scripts/mutation_wave4.py`（Wave 2・3 も同様）
- 設計の全体と残りは `internal/audits/COVERAGE_WAVE4.md`

## Coverage Wave 6（台帳をまたぐ信号と TCG 収集の高速化）

- 台帳: `RESEARCH_LEDGER_KEY`（32 文字以上）を設定すると、暗号化した台帳を次の run に引き継ぐ。**設定はユーザーが行う**: `gh secret set RESEARCH_LEDGER_KEY`（値はチャット・ファイルに残さない）。設定後の 2 回目の run から、買取の勢い・first_seen・検知の遅れが実測できる
- 買取の勢い: `signals.momentum()`（NEW_OBSERVATION / NOT_COMPARABLE / STALE_BASELINE / SAME_OBSERVATION。3% かつ 500 円以上で RISING・隔離された価格は参考のみ）。次回の基準は正常な価格だけ
- 検知の遅れ: `src/tcg/detection_delay.py`（台帳を使い始めた後に初めて現れたイベントだけ。公開日時が無ければ UNKNOWN）
- TCG の収集: `src/collectors/tcg/runcache.py`（異なるドメインは並列・同じドメインは同時に 1 つ・60 秒以上の間隔・同時に通信する数の上限・同一 run の URL キャッシュ（メモリだけ））。指標は `exports/tcg/latest.json` の `collection_metrics`
- 変異テスト: `python3 scripts/mutation_wave6.py`（追跡ファイルを書き換える。他のセッションが編集していないときだけ）。deploy-check #877
- 設計の全体と残りは `internal/audits/COVERAGE_WAVE6.md`

## Coverage Wave 5（利益が出やすい市場の優先度）

- シグナル: `src/research/signals.py`（発売からの経過・公式の根拠のある限定・供給の逼迫・買取の勢い・価格差が正）。**根拠が無ければ付けない**。点は並べ替えにだけ使い、確定・actionable にしない。
  発売日が無ければ UNKNOWN・在庫が不明は逼迫にしない・前回の観測が無ければ「上がった」と言わない・誤価格の疑いは 0 点
- 前回の買取の価格: `state.json` の `buyback_prices`（非公開）。`RESEARCH_LEDGER_KEY` を設定して台帳を引き継げた日（`RESTORED_FROM_PREVIOUS_RUN`）だけ比べる
- TCG: `src/tcg/profit_dense.py`（優先度・イベントの質 7 項目・定価の台帳との商品 ID の完全一致の結び付き・検知の間隔のシミュレーション。実装はしない・利益は計算しない）
- 取得: 小売の照会は取得器（ドメイン）ごとに並列（`retail_lookup._fetch_all`）・同一実行内の同じ URL は `RunFetchCache`（メモリだけ）。ドメインあたりの間隔は polite が守る
- 変異テスト: `python3 scripts/mutation_wave5.py`。deploy-check #876
- 設計の全体と残りは `internal/audits/COVERAGE_WAVE5.md`
