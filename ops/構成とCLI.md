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
