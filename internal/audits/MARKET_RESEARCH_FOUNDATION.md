# Market Research Foundation（2026-10-23）

Market Coverage Audit（MARKET_COVERAGE_CRITICAL）を受けた土台づくり。「確定した商品だけを安全に表示する監視」から、
「市場から利益候補・抽選・予約・再販を探してくる」方向へ広げる。**既存の安全の仕組みは変えていない**（誤価格の防止・
同一性の確認・鮮度の関門・公式の証拠・買取の完全一致・古い値の除外・費用の確認・actionable の関門・通知の安全・
遮断された取得元の回避禁止・robots の遵守）。

## 1. 流れ

```
DISCOVERED → RESEARCH_CANDIDATE → VERIFIED → CONFIRMED_OPPORTUNITY → ACTIONABLE
 (発見)        (調べる価値あり)     (既存の関門を通過)   (確定の利益)        (今行動できる)
```

- 候補として見つけることと、確定の利益として出すことを分ける。**確定の判定（`opportunity.eligibility`）は変えず、やり直さない。**
- `VERIFIED` は、既存の判定を通った商品（`verified_pids`）だけ。調査候補の側で独自に VERIFIED にしない。
- 調査候補は**運営者向けのページだけ**が読む。顧客の画面・LP・商品の通知・Telegram には出さない。

## 2. 調査候補（`src/research/candidates.py`）

| 項目 | 内容 |
|---|---|
| 状態 | DISCOVERED（片側の価格だけ・価格差が出ない）／RESEARCH_CANDIDATE（生の価格差があり、分かっている費用を引いても正）／VERIFIED／REJECTED（価格差なし）／STALE（見えなくなった） |
| 項目 | candidate_id・product_identity・genre・source・source_url・observed_buy/sell_price・raw_spread・estimated_known_costs・raw_net_spread・confidence・missing_requirements・exclusion_reasons・discovered_at・last_seen_at・status・priority |
| 経路 | RETAIL_TO_BUYBACK（公式の定価で買う）／SECONDARY_TO_BUYBACK（公式で買えない・公式が無い商品は、販売店の新品の価格を仕入れ値にする） |
| 足りないもの（理由） | OFFICIAL_UNVERIFIED・OFFICIAL_NOT_SOLD・BUY_URL_NOT_ITEM_LEVEL・BUY_STALE・SELL_STALE・GENERIC_SELL_URL・IDENTITY_UNCONFIRMED・CONDITION_UNKNOWN／MISMATCH・STOCK_UNKNOWN（参考）・PURCHASE_SHIPPING_UNKNOWN・PRICE_ANOMALY_SUSPECTED・SELL_REJECTED ほか |
| 売値の選び方 | 確定できる行（既存の `sell_confirmation_reasons` が空）の最高値を使う。ただし、その行では価格差が出ないのに、確定できない行（古い・店のトップ・照合未了）に買値を上回る高値があるときは、その高値を調査候補の売値にして、理由と注記を付ける（再確認すれば差が出るかもしれない商品を捨てない） |
| 信頼度 | 誤価格の疑い・照合が曖昧・品質の判定で外れた売値があれば low。足りないものが1つ以下なら high |
| 優先度 | 決まった式（`priority_of`）: 純の差（10万円で上限）／売値が新しい／照合ができている／足りないのが公式の確認だけ、を加点。売値が古い・店のトップの URL・照合が曖昧・誤価格の疑い・取得元の遮断を減点。**予測価格は使わない** |
| ID | `rc_` + sha1("product\|<商品 ID>")。**商品だけ**から決まる（価格・日時・経路・買う店・売る店が変わっても同じ ID。経路・店は属性として持つ） |
| 台帳 | `.private/research/state.json`（非公開）。初めて見た日（discovered_at）は付け替えない。見えなくなった候補は STALE として30日残して捨てる |
| 出力 | **個別の候補・台帳は private**（`.private/research/latest.json`・`state.json`・`buyback_catalog.json`。`.gitignore` 済み・commit しない・公開しない）。**公開してよい集計だけ** `exports/research/summary.json`（commit の対象）。LP の生成の中で、診断の直後に書く（失敗しても LP は止めない） |
| 送料不明 | 購入送料が分からない候補は `raw_net_spread` を null にする（純利益と誤認させない）。分かっている費用だけを引いた差は `known_cost_spread`、費用は `known_costs`、`shipping_unknown` で分けて持つ |

偽陰性の確認（2026-10-22 の本番の生成物から読んだ結果）: 監査で挙げた「生の価格差が正なのに確定にならない商品」3件は、いずれも確定にならず、調査候補として残る（個別の商品名はここに書かない。公開リポジトリの文書なので）。
いずれも確定にならず、調査候補として残る。

## 3. 公開と非公開（Public / Private Hardening）

**GitHub Pages の管理画面は、認証が無い限り公開である。** 「管理画面」という名前でも非公開ではない。個別の調査候補
（確定していない価格差・探索の成果）は、公開リポジトリにも公開ページにも出さない。

| 区分 | 置き場 | 中身 |
|---|---|---|
| 公開（commit する） | `exports/research/summary.json` | 件数・理由別の件数・ジャンル別の件数・信頼度の分布・網羅性の指標・TCG の取得元の件数だけ。**許可リストで作る**（`public_summary`）。個別の項目（商品名・候補の ID・買値・売値・価格差・URL・売却先・商品ごとの理由・優先順位）が混ざったら例外にして何も書かない（`find_private_keys`・`write_outputs`） |
| 非公開（commit しない） | `.private/research/`（`.gitignore` 済み） | 個別の候補（latest.json）・台帳（state.json）・買取の一覧の全行（buyback_catalog.json） |
| 引き継ぎ | **暗号化した**台帳を GitHub Actions のキャッシュへ（`.private/ledger.enc`・鍵は Secrets の `RESEARCH_LEDGER_KEY`） | 台帳（初めて見た日・見えなくなった候補）を次回の実行に渡す。**平文でキャッシュしない**（fork の PR からも、ベースのキャッシュは復元できる。Secrets は fork の PR に渡らないので、鍵が無ければ復号できない）。artifact にもしない（公開リポジトリの artifact はログインした誰でも取れる）。**鍵（Secret）が無ければ引き継がない**（台帳は毎回新しく作る = 調査候補は動くが、初めて見た日は毎回今日。出力の `ledger_state` が `fresh` になり、管理画面にも出す）。鍵の設定は運営者が行う（Secrets の変更はここでは行っていない。32文字以上のランダムな値）。暗号は openssl の aes-256-cbc・pbkdf2（反復 60万回）・環境変数で鍵を渡す（コマンドラインに出さない）。復号の前に、中身が許可した3ファイル（state.json・latest.json・buyback_catalog.json）だけで、リンクを含まないことを確かめてから展開する。復号・検証に失敗した日は、台帳を作り直して `ledger_state` を corrupt にする。キャッシュの key に run_attempt を含める（再実行でも保存できる） |
| 状態の遷移日 | 台帳の `status_since` | 今の状態になった日（調査候補になった日）。`discovered_at`（台帳で初めて見た日。毎日1行ずつ作られる価格差なしの期間も含む）とは別 |
| 管理画面（公開サイトに埋め込まれる） | `admin.build_research` / `_research` | 集計だけ。個別の候補の報告（private の latest.json）は受け付けない。個別の表示コードは持たない。認証付きの管理画面ができるまで、個別の候補の Web 表示は作らない |

**守れる範囲（正直な限界。監査の High 相当・既存起因・運営者の判断待ち）**: 守っているのは、**個別の候補の一覧・順位付け・
商品ごとの調査の理由**である。元になる観測は、**既存の公開の成果物**として以前から公開リポジトリにある:
`exports/normalized_price_observations/latest.json`（商品別の価格・売却元・URL・鮮度）、`exports/opportunity_diagnostics/latest.json`
（商品別の除外理由 `candidates[].reasons` と公式価格 `retail_prices`）、`exports/profit_routes/`・`exports/ai_opportunities/` など。
したがって、第三者が公開済みの観測と、公開されているこのリポジトリのコード（`src/research/candidates.py`）から、調査候補とほぼ同じ
ものを**再計算できる**。これは今回の変更で悪化したものではなく、「調べた成果を秘匿する」ことはできていない。変えるには、既存の
公開の成果物の粒度（商品別の価格・商品別の除外理由）を見直す別の判断が要る（既存の画面・診断・テストが読んでいるので、
今回は変えていない）。`summary.json` を毎日 commit するので、git の履歴から調査候補の件数の増減は読める。

運営者が個別の候補を見る方法: 当面は、手元で LP の生成を実行して `.private/research/latest.json` を見る（将来は認証付きの画面か private な置き場）。
候補の生成・保持・買取起点の発見は削除していない（保存先と公開範囲だけを分けた）。

## 4. 買取起点の発見（buyback-first）

- 買取商店の一覧ページ（iPhone・カメラ）は、商品ごとの照合のために既に取得している。その**同じ HTML**の全行を
  `CATALOG_ROWS` に記録し、`.private/research/buyback_catalog.json`（非公開）に残す（**新しい取得はしない**）。取れなかった日は前回のまま
  （観測の日時を偽らない）。
- 一覧の行を、正本の JAN（公式の確認の記録・商品の登録）と Apple の部品番号だけで照合する。**名前だけでは一致にしない・
  正本にしない。**
- 一致しない行は `DISCOVERED_PRODUCT_CANDIDATE`（上限 100 件・価格の高い順）として残す。公式の価格・照合が無いので、
  利益の計算には進まない。正本への登録は、公式で JAN・型番・価格を確かめて人が行う（既存の Phase 28 の手順）。
- 新しい取得元は追加していない（買取商店のみ）。

## 5. 小売起点・成約の窓口（設計のみ。`src/research/interfaces.py`）

- `RetailDiscoveryAdapter` / `RetailListing`: Apple で作った発見の形を一般化する窓口。対象の候補は Nintendo・Sony・
  Ricoh・Fujifilm・Canon・Nikon。実装は Apple（既存）のみ。実装の条件は、公開ページに商品の一覧があり、robots が許し、規約が
  自動取得を禁じていないこと。
- `MarketplaceSoldAdapter` / `SoldRecord` / `SOLD_EVIDENCE_REQUIREMENTS`: 成約の取得の窓口と、成約の証拠の要件
  （個別の取引ページの URL・成約の日時・正の価格・商品の照合・公式 API か許諾か規約が許す公開ページ・中央値は期間と件数）。
  `valid_sold_record` が使えない理由を返す。**「コードがある」は網羅に数えない**。現状の成約の実データは 0 件のまま
  （メルカリ・ヤフオクは規約上ライブ取得をしない／ラクマ 0 行／eBay は API が未設定）。

## 6. TCG

| 項目 | 内容 |
|---|---|
| イベントの種別（H1） | `src/tcg/models.py` に STORE_LOTTERY・APP_LOTTERY・WEB_LOTTERY・IN_STORE_QR・RELEASE・REVIEW_REQUIRED を追加。**挙動は `base_event_type()` で既存の種類に写す**（店舗・アプリ・Web の抽選と店頭 QR は抽選と同じ状態の計算・通知の安全側の扱い）。RELEASE・REVIEW_REQUIRED は購入できる根拠にならないので、どんな場合も「今買える」にしない |
| 応募の経路の集計 | `lottery/schema.entry_kind()` が、イベントの明示の項目（store_specific・app_required・online_only・channel）だけから種別を決める（推測しない）。イベントの辞書・lottery_id は変えず、報告の `coverage.entry_kinds` に集計 |
| 取得元の分類（H2） | `registry.source_class()`: WORKING／IMPLEMENTED_BUT_BLOCKED／ACCESSIBLE_UNIMPLEMENTED／UNREACHABLE／UNSUPPORTED。取得元の行に `source_class`、報告の `coverage.source_classes` に件数。**遮断された取得元は実装の候補にしない（回避しない）**。Amazon は取得の作法（スクレイピングしない）で UNSUPPORTED |
| 優先（H3・H4） | 取得できるものを優先し、ACCESSIBLE_UNIMPLEMENTED（エディオン・TSUTAYA・セブンネット など）を実装の候補にする。実装の前に、売り場ごとに robots・規約・公開ページの告知の一覧を確認する（未確認） |
| 取得元の候補（H5） | `config/tcg_source_candidates.yaml`（14件・すべて未確認・fetch していない）。`lottery_sources.json` と `latest.json` に載せ、管理画面に出す |
| 画像のみの告知（H6） | REVIEW_REQUIRED のまま。OCR で日程を確定しない（コードに OCR を入れていない検査あり） |
| 種別（H7） | `FUTURE_TCG_TYPES = (YUGIOH, DUEL_MASTERS)` と `KNOWN_TCG_TYPES` を追加。取得器・商品データが無いので `TCG_TYPES` には入れない（入れると、取得器の無い種別まで報告・登録の対象になる） |
| 定価の台帳（I1） | `src/tcg/msrp.py` → `exports/tcg/msrp.json`。公式の商品 API が商品1個の希望小売価格と明示したものだけを、同一性（商品 ID・名前・種類・発売日・公式ページの URL・確認時刻）つきで記録。パック価格から BOX の価格は作らない（理由つきで excluded）。**利益の計算には使わない（I2）** |

## 7. 頻度の分離（設計のみ。実装なし）

GitHub の定時の実行は毎日 4〜5 時間遅れて始まる（2026-10-18〜22 の実績 +4h41m〜+5h23m。cron を 17 分に変えても改善なし）。

| 区分 | 用途 | 前提 |
|---|---|---|
| Slow lane（日次） | 公式の価格・長期の買取・発見・レポート | 今の Daily LP Update。遅れても害がない |
| Fast lane（将来） | 抽選の開始・先着・再販・買取の急騰 | **GitHub の schedule を前提にしない。** 数分〜数時間おきの別の実行の仕組みが要る。代替の仕組みは今回実装しない（必要性の評価のみ）。取得の作法（robots・間隔・正直な User-Agent）の範囲での頻度の上限を先に決める |

## 8. 確認

- deploy-check **#871**（`market_research_separation`）: src/research が通知・送信・取得を import しない／通知・顧客の画面が調査候補を読まない／
  古い売値・店のトップ・公式未確認は調査候補として残り確定にならない／ID は安定／**公開 JSON（exports/research/）・公開 HTML / Markdown / JSON（docs/）・
  commit の対象・git の追跡ファイルに、個別の候補（候補の ID・価格・価格差・URL・商品名）が出ない**／`.private/` が `.gitignore` 済みで commit の対象にない／
  公開の集計が許可リストで作られ、管理画面が個別の候補の報告を受け付けない。
- `tests/test_market_research.py`（131件）。変異テスト 83 件すべて検出（公開の集計に候補の ID・価格差・売値・URL・商品名を載せる・漏洩の門を外す・commit の対象に非公開の置き場を入れる・`.gitignore` から外す・個別の候補を公開の置き場に書く・送料不明でも純の差を出す を含む）。以前の（調査候補が確定になる・未確認の公式が確認済みになる・古い売値が新しくなる・
  店のトップの URL が通る・候補が捨てられる・通知に流れる・公開ページに個別の候補が出る・ID が売る側の店で変わる・外れた高値が代表になる・
  遮断された取得元を実装の候補にする・パック価格が BOX の定価になる・定価の台帳が空の日に上書きされる など）。
- レビュー（reviewer）・監査（auditor）の指摘への対応: 公開ページへの露出（High・上記）／候補 ID から売る側の店を外した／外れた高値・
  誤価格の疑いを代表・優先度に使わない（優先度は low 固定）／VERIFIED は確定の判定だけで決める（買値・売値が読めなくても漏れない）／
  Apple の部品番号を公式の確認の記録からも読む／買取の一覧の保存をページ単位にし、空のページを記録しない／定価の台帳は公式 API から
  1件も取れない日に書かない／SNS を実装の候補ではなく除外にした／報告 CSV で RELEASE・REVIEW_REQUIRED を受け付けない／
  新しいイベント種別の通知ラベル／entry_kind は明記された項目だけ／発見の件数を二重に数えない／naive と aware の混在でも落ちない。
  未対応（理由つき）: `source_class` の DEGRADED を別区分にしない（取得できている取得元なので WORKING のまま。Low）／
  送料不明の費用は固定費だけで足す（理由 PURCHASE_SHIPPING_UNKNOWN が必ず付く。Low）。

## 9. 残り・注意

- 個別の候補を見る認証付きの画面は無い（作らない）。`source_class` の「取得できたが対象の告知が無い」は将来別区分にできる既知の制約（Low）。
- 調査候補の数は、実データの量で決まる。今の本番のデータでは、生の価格差が正で確定にならない商品は 3 件（商品名はここに書かない）。
  **調査候補を増やすには、確認済みの公式の価格・買取の取得元・商品の登録を増やす必要がある**（この土台は、見つけたものを捨てない層）。
- 買取の一覧からの逆引きは、買取商店の一覧だけ。最初の本番の実行で `buyback_catalog.json` ができるまで、正本に無い商品の候補は 0 件。
- 小売起点（Apple 以外）・成約の取得・TCG の取得器の追加・TCG の買取・成約・二次流通・Fast lane は、窓口と要件を決めただけで未実装。
- iPhone 18 系の登録は保留（別の指示まで）。

## 10. 2 回目のレビュー・監査（公開と非公開の境界）への対応

- 公開の集計の件数の内訳を揃えた（生の価格差が正 = 確定の関門を通過 + 通過していない）。冗長な項目を整理。
- 候補 ID は商品だけで決める（経路・買う店・売る店が変わっても同じ。経路は属性）。STALE 行は台帳の値で状態・ID を上書きできない。
- 発売の予定・要確認は、日程の根拠が何も無い行も古い扱い。
- deploy-check #871 を強化: git add の全ての文（強制・全部・.private）・upload-artifact の範囲・キャッシュの path（ワイルドカードも）・
  openssl の鍵の渡し方と反復回数・pipefail・公開の docs の調査候補の表示に価格・商品名が無いこと・summary.json に商品名が無いこと・
  文書の項目単位の商品名の検査（products.yaml が読めないときは通さない）。一時のリポジトリで、検査が退行を検知することをテストで確認。
- 復号の step のシェルを、テストで実際に動かして確認（正常・余計なファイル・リンク・鍵の違い・壊れたファイル・初回）。
- 未対応（理由つき）: `scripts/collect_tcg_events.py` の抽選の絞り込みは `event_type == LOTTERY` のまま（新しい抽選の型をコレクターが生成し始めるときに、
  `base_event_type` を通す再監査が要る。今はどのコレクターも生成しない）。

## 11. 3 回目のレビュー・監査への対応

- 台帳の step（key check・restore・decrypt・encrypt・save）はすべて `continue-on-error: true`（付加の機能の不調で、その日の LP の公開を止めない）。#871 が検査する。
- 鍵は 32 文字未満なら引き継がない（key check で `enabled=false`・警告）。#871 が検査する。
- 暗号化は許可した 3 ファイル（state.json・latest.json・buyback_catalog.json）だけを梱包し、一時ファイルに書いてから置き換える（書きかけを保存しない）。
  復号は、通常ファイル・ディレクトリ以外（リンク・FIFO・デバイス）と許可名以外を含む台帳を展開しない。シェルはテストで実際に動かして確認した。
- #871 のパス検査を、`os.path.normpath`・glob の照合（`.private` を含みうる親・ワイルドカード）・`include-hidden-files`・`./` 付き・コメント行を除いた
  git add のトークン検査に直した。例外のログには型名だけを出す（公開ログに値を出さない）。
- 既知の限界（Low）: 公開 docs の検査は、調査候補の表示の属性（`data-nu-ad-panel="research"`）に依存する（別の場所に移すと検査の対象外になる）。
  商品名の突合は 5 文字以上・大文字小文字を区別する。買取の一覧由来の未登録商品名は突合できない。文書の検査は「調査候補」の語を含む項目だけ。
  ハードリンクを含む台帳の拒否は、GNU tar（本番）の `tar -tv` の表示に依存し、ローカル（bsdtar）のテストでは確かめられない。
  `openssl enc` は認証付き暗号ではない（改ざんは復号後の検査と gzip の CRC で防ぐ。鍵が無ければ有効な暗号文は作れない）。
