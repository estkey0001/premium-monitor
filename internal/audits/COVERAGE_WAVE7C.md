# Coverage Wave 7c（仕入れ価格・公式の確認・取得元の拡張）

進め方: 7c-1（コード）→ 7c-2（公式価格の人手確認 3 件）→ 7c-3（TCG の取得元・定価・API の準備）。各段階で検証・レビュー・push。

## 開始値（2026-11-06 の本番）
公式の価格が確認済み 16/47・調査候補 10・高優先 6・価格差が正 6（確定の関門を通過 2・通過していない 4）・確定の利益 2・actionable 0。作業キュー 10（HIGH 6・MEDIUM 4・URGENT 0）。次の行動: VERIFY_OFFICIAL_PRICE 6・VERIFY_MSRP 4。TCG の取得元 working 8（遮断 3・到達できない 6・未実装 3・対象外 2）。TCG の定価（MSRP）確認済み 15。Yahoo / 楽天 API は Secret 未設定（PENDING_USER_CONFIGURATION・リクエスト 0）。

## 原因の分類（公式の確認が取れない 21 / 監査対象 37。公開の監査データ `exports/official_source_audit/latest.json`）
- 販売終了・後継機に交代 17（Apple。公式は後継機だけを販売中で、今の公式の仕入れ価格が存在しない）
- 公式サイトに到達できず要手動確認 3（Sony α7CR・FX3、Canon R3。監査の環境から DNS が解決できなかった）→ 7c-2
- 生産終了・版が存在しない 3（リコー GR III・マリオカートワールドセット・PS5 デジタル・エディション）
- TCG の定価未連携 4: 公式 API がパック単体の価格だけを出す（PACK_PRICE_ONLY。パック価格から BOX の価格は作らない）か、公式の URL が無い。公式の BOX の価格の証拠が出るまで減らない。
- **公式確認の目標「+4」は、実データでは最大 +3**（上の「要手動確認」が実際に販売中で価格が読めた場合だけ）。数値のために証拠を弱めない。

## 7c-1 の実装
- `src/research/evidence_gap.py`（新規）: 公式の価格が確認できない原因の分類・価格の種類（REGULAR / SALE / COUPON / MEMBERSHIP / CONDITIONAL / UNKNOWN と、ポイント・キャッシュバックの参考）・件数。確定・通知・通信の部品に依存しない。
- `retail_lookup.price_evidence` に `price_type` / `confirmable` / `reference_types` を追加（既存の仕入れ値の計算は変えない）。`apply_lookups` は価格の種類が条件つきなら ACQUISITION_CONDITIONAL（確定に使わない・高優先にしない）。
- `candidates.build_candidates` が `official_gap` を付ける（非公開）。公開の集計は `official_gap_counts` と `price_type_counts`（件数だけ）。
- 作業キュー: 公式が売っていない商品の次の行動を VERIFY_RETAIL_PRICE に（公式を確認しても変わらないため）。管理画面は原因ごとの件数だけ。
- テスト `tests/test_coverage_wave7c.py`（17 件）・変異テスト `scripts/mutation_wave7c.py`（31 件）・deploy-check #880。

## 7c-1 のレビュー（1 回目）での修正
- 原因の分類に、実際の入力を接続した（reviewer の High: SOURCE_BLOCKED は、買取店の遮断の集合と公式の取得元 ID が重ならず本番では発火しなかった）。`official_signals` が、公式の再確認の記録（36 時間以内の blocked / failed）と公式の登録簿の同一性の判断から旗を作り、`daily_lp_generator` が `official_meta` に流す。IDENTITY_NOT_MATCHED・PAGE_CHANGED（新設）も同じ入力で発火する。
- 判定順の見直し: URL が無ければ（根拠のページが無い）確認が古いとは言わず SOURCE_NOT_IMPLEMENTED。確認済みなら遮断・ページの変更より先に「不足ではない」。
- 作業キューの次の行動を原因ごとに細分化: SALE_ENDED → VERIFY_RETAIL_PRICE、SOURCE_NOT_IMPLEMENTED → REGISTER_OFFICIAL_SOURCE（新設）、IDENTITY_NOT_MATCHED → VERIFY_IDENTITY、遮断・古い・設定値だけ・ページの変更 → VERIFY_OFFICIAL_PRICE（人が公式ページで確認。回避しない）。
- 価格の種類: 現金の価格が確定できない（値引きが価格以上など）ときは UNKNOWN（確定に使えない）。壊れた条件の値は条件つき（確定に使わない）側に倒す。条件が文字列 1 つなら 1 つの条件として読む。
- 変異テスト 43 件（見逃し 0）。

## 7c-1 のレビュー（2 回目）での修正
- 再確認の状態を正確に使う（`scripts/recheck_official.py` の状態）: blocked と理由ありの failed（取得失敗・到達不能）→ SOURCE_BLOCKED、理由なしの failed（ページは取れたが型番・価格を読めない）→ PAGE_CHANGED、sale_ended → SALE_ENDED、changed → PRICE_CHANGED（新設）。
- 再確認の記録に URL があれば、取得元の設定（DB）に URL が無くても根拠のページがあるとみなす（`merge_signals`。登録された URL は上書きしない・https だけ）。これで、実在する取得元を「未登録」と誤判定して REGISTER_OFFICIAL_SOURCE を出さない。
- 現在時刻がタイムゾーンなしでも落ちない（JST とみなす）。信号の組み立ては単独の try で包み、失敗しても旗なしで調査候補の生成を続ける。買取店の遮断の集合を、公式の取得元の遮断として混ぜない。
- 変異テスト 54 件（見逃し 0）。
- 残る（Low・記録のみ）: IDENTITY_NOT_MATCHED は「同一性が確認できない」（登録簿の PARTIAL_IDENTITY を含む）で、不一致と確かめたものではない。条件つきで通常価格が分かる場合も確定に使わない（従来どおり保守的）。期限つきのセールは SALE（条件なしの即時値引き）として確定に使えるが、期限の確認は取得器の責任。

## 7c-1 のレビュー（3 回目）での修正
- 再確認の `sale_ended` は原因の分類だけに使う（`recheck_sale_ended`）。候補の買い側の経路（公式 → 中古・二次）を切り替える `official_not_sold` には混ぜない（ページ内の文言を探すヒューリスティックだけで、人の確認なしにルートが変わらないように）。
- `failed` の理由を意味で分ける: 遮断・規約上の拒否・到達不能（timeout・connection_error・5xx など）→ SOURCE_BLOCKED、ページ側の理由（404・移動・空のページ・価格を読めない）や未知・理由なし → PAGE_CHANGED（遮断と断定しない）。語彙は `collectors.polite.CUTOFF_IMMEDIATE` との整合をテストで確かめる。
- どの版かが決まっていない商品（曖昧・判断待ち）は、公式ページの登録（REGISTER_OFFICIAL_SOURCE）より先に同一性の確認（VERIFY_IDENTITY）。型番・JAN の登録だけある商品は、まず公式ページを登録する。
- 再確認の URL は、https・ホストあり（英数字・ハイフン・ドット）・認証情報なし・空白や制御文字なしのものだけを根拠のページとして補う（手書きで検証。パーサーの import を増やさない）。価格の種類は、条件の元の項目（クーポン・会員限定・キャンペーン・数量限定）も読む。壊れたメタ・件数の型の違う値で落ちない。
- 変異テスト 66 件（見逃し 0）。
- 残る（Low・記録のみ）: IDENTITY_NOT_MATCHED は「同一性が確認できない」を含む。補った URL は、候補の `source_url.buy`（非公開）と送料の判定（既存のホスト単位の規則）に使われる。条件つきで通常価格が分かる場合は、従来どおり確定に使わない。

## 7c-1 のレビュー（4 回目）での修正
- 再確認の URL は分類専用の `gap_url` に入れる（`meta["url"]` には触らない）。候補の買い側の URL（`source_url.buy`）・送料の判定に影響させない（reviewer の Medium: URL を補うと Apple 系の送料が「不明」から「0」に変わりうる）。実際に `build_candidates` を通して、買い側の URL・費用・純差・経路・価格が変わらないことをテストで固定した。
- 公式の登録簿の販売終了（`identity_state` が DISCONTINUED）を、分類専用の旗（`registry_sale_ended`）で SALE_ENDED にする（reviewer の Medium: 販売終了の商品が「取得元が未登録」になり、公式ページの登録を促していた）。買い側の経路は変えない。
- 根拠のページの URL の検証を強化: 印字可能な ASCII だけ（不可視文字・DEL・方向制御・生の IDN を拒否。IDN は punycode で）・IP リテラル風のホスト（数字だけ・0x）を拒否・ポートは 1〜65535。
- 変異テスト 74 件（見逃し 0）。
- 残る（Low・記録のみ）: 再確認が `unchanged` の商品も、研究候補側の証拠の区分（`msrp_evidence`）は従来どおり（確認日の延長に使う `extends_verification` との整合は未対応）。`retail_confirmable` は保存と集計のためで、確定の関門からは読まれない（条件つきの価格が確定しないのは、従来の `ACQUISITION_CONDITIONAL` による）。再確認の URL の末尾ドット・アンダースコアのホスト・生の IDN は拒否する（根拠のページがあることを示せず、取得元が未登録に倒れる）。

## 7c-1 のレビュー（5 回目）での修正
- 新しい再確認で型番・価格が一致（`unchanged`）した商品を、専用の原因 RECHECK_MATCHED（記録の更新待ち）にする（reviewer の Medium: 昨夜自動確認された商品が「確認が古い・設定値だけ」と分類され、運営者に公式の確認のやり直しを促していた）。自動では確認日を更新しない方針は変えない。同一性・失敗・価格の変化・遮断は一致より先。古い一致（36 時間超）は使わない。
- 公式の登録簿の確認済み URL（`VERIFIED_URLS`）も、根拠のページ（`gap_url`）として使う（再確認の記録の URL を優先）。登録簿に URL があって再確認の対象外の商品に、公式ページの登録を促さない。
- `merge_signals` は許可した旗（`SIGNAL_KEYS`）だけを書く（買い側の経路・URL を決める `url`・`official_not_sold` は書けない）。再確認の記録の `results` が壊れていても登録簿の旗は残す。商品 ID が文字列でない記録は使わない。
- 根拠のページの URL の検証: スキームの大文字・末尾のドット（1 つ）・パスやクエリの日本語を許し（実在する公式の URL を落とさない）、不可視文字・方向制御・空白・DEL・IP リテラル風・ポート範囲外は引き続き拒否。ホストは ASCII（IDN は punycode）。`confirmable` は情報用であることをコメントで明記。
- 変異テスト 84 件（見逃し 0）。
- 残る（Low・記録のみ）: 登録簿の販売終了は、証拠が確認済みでも SALE_ENDED を優先する（登録簿の `checked_on` が古くなったときの注意）。旧い lookup 記録は `price_type` が無く UNKNOWN と数えられる（36 時間の期限で自然に消える）。`retail_confirmable` は確定の関門から読まれない。

## 6 回目のレビューでの修正

- auditor M-1（Medium）: 公式が販売終了と分類された商品（登録簿の販売終了・再確認の `sale_ended`）の価格差は、存在しない公式価格から出た値。作業キューで優先度・点・並べ替えに使わず、`spread.used` は None にする（買い側の経路は変えない）。テストと変異を追加。
- auditor L-1: `_https_url_ok` のポートは ASCII の数字だけ。
- 残る Low（記録のみ）: RECHECK_MATCHED の次の行動が VERIFY_OFFICIAL_PRICE のまま／公開の原因別件数は RESEARCH_CANDIDATE だけが対象／`identity_state` の順序で SALE_ENDED が IDENTITY_NOT_MATCHED に隠れる商品がある（switch2_mk・ps5_de）／同じ商品の再確認の結果が複数あると旗が重なる（現状は 1 商品 1 行）／`price_type_of` は通常価格が分かる条件つきの行も確定不可（保守側）。

## 7・8 回目のレビュー（ゲート通過）

- 7 回目の reviewer: M1（SECONDARY_TO_BUYBACK の実在の価格差まで SALE_ENDED で消す）→ 公式の買値の経路だけ None にする。M2（巨大なポートで `int()` が ValueError）→ 5 桁以下に限る。テストと変異を追加。
- 8 回目: reviewer・auditor とも Critical 0・High 0・Medium 0。
- 残る Low（記録のみ）: キュー項目の `spread.raw` / `known_cost` に無効化前の値が残る（非公開・優先度に不使用）／ポートの 0 埋めを許可／`official_gap` を正規化しない／条件つきで通常価格が不明のとき `effective_price` が掲載価格のまま（確定は ACQUISITION_CONDITIONAL が止める。`effective_price` だけを使う新しい経路を作るときは `confirmable` も見ること）／誤検知の販売終了は優先度が下がる側にだけ働く／公開の `official_gap_counts` に SOURCE_BLOCKED の件数が出る。

## 7c-1 の本番結果（2026-11-07・11-08 の定時 run）

- 2 回とも成功（約 1h45m）。`queue_build_failed` 0・外部送信 0・Phase24 は `PHASE24_WAITING`・confirmed 2・actionable 0・公式の確認済み 16/47（変化なし）・公開物への個別項目の漏洩 0・deploy-check #880 通過。
- 原因別（調査候補 4 件が対象）: SALE_ENDED 1・SOURCE_BLOCKED 1・IDENTITY_NOT_MATCHED 1。価格の種類は REGULAR 45・条件つき 0。次の行動: VERIFY_OFFICIAL_PRICE 6・VERIFY_PRODUCT_IDENTITY 1・VERIFY_MSRP 3。
- 判定: PARTIAL。作業キューの個別行は非公開で CI の外から見えないため、SALE_ENDED → VERIFY_RETAIL_PRICE・gap_url が買い側に影響しないこと・SECONDARY_TO_BUYBACK の価格差の維持・RECHECK_MATCHED の個別の挙動は、本番で直接観測できていない（テストでの確認のみ）。既知の観測上の制約として記録し、blocker にはしない。
- Sony α7CR・FX3・Canon R3 は、設定値の参考価格だけ（確認日・URL なし）で、人手確認の対象として残っている。

## 7c-2: Sony α7CR・Sony FX3・Canon EOS R3 の公式ページの人手確認（2026-11-08）

人がブラウザで公式ドメインのページを開いて読んだだけ（ログイン・アカウント作成・カート操作・購入・フォーム送信はしていない）。確認日は 2026-11-08（実行日では更新しない）。

| 商品 | 公式ページの表示 | 結果 | 登録 |
|---|---|---|---|
| Sony α7CR | ソニーストア購入ページ `pur.store.sony.jp/ichigan/products/ILCE-7CR/ILCE-7CR_purchase/`。ILCE-7CR/S・ILCE-7CR/B（ボディのみ）449,900円(税込)・翌日出荷・カートに入れる（押していない）。クーポン・カード割引・キャンペーンは適用前の表示。送料・JAN の表示なし | VERIFIED_CURRENT_OFFICIAL_PRICE（確定の仕入れ値ではない） | `VERIFIED_URLS`・`IDENTITY_EVIDENCE`（型番のみ。JAN は作らない）・`OFFICIAL_DIRECT_OFFERS`・再確認の対象。送料は未登録（UNKNOWN） |
| Sony FX3（ILME-FX3） | 製品ページ `sony.jp/pro-cam/products/ILME-FX3/` が「[生産完了]」「希望小売価格581,900円(税込)」「後継機種 FX3（ILME-FX3A）」「ソニーストアでの販売は終了」。現行は別型番の ILME-FX3A | OFFICIAL_NOT_CURRENTLY_SOLD | `OFFICIAL_NOT_SOLD`（ILME-FX3A と同一視しない） |
| Canon EOS R3 | オンラインショップ購入ページ `store.canon.jp/online/g/g4895C001/` の見出しが「【販売終了】」。通常価格 792,000円(税込)・送料無料の表示は残る。製品ページも「EOS R3 販売終了」・JAN 4549292-181661・商品コード 4895C001・希望小売価格オープン価格 | OFFICIAL_NOT_CURRENTLY_SOLD | `OFFICIAL_NOT_SOLD`（792,000円は仕入れ値にしない。カートボタンの有効・無効は未確認） |

- 同一性: α7CR は型番 ILCE-7CR の完全一致。JAN は公式の購入ページに表示が無いので登録しない。
- 既存の関門: α7CR の `official_direct_gate` は `jan_not_exact`・`shipping_unknown` で不通過。確定・actionable・通知に直接昇格しない。FX3・R3 は `no_official_direct_evidence`。
- 設定の旧参考価格（α7CR 330,000円）は誤りだった（実際は 449,900円）。前例（α7R V・α1 II）に合わせて `config/products.yaml` の `retail_price` とメモを直した（参考価格のまま。確認済みにはならない）。
- 再確認のパーサー `parse_sony_store` は、型番の後ろの色の型番（/S・/B）と色名（（シルバー））を許すようにした（実ページの並び。色ごとの価格が食い違えば読まない）。
- 残る Low（記録のみ）: FX3・R3 の設定の旧参考価格（520,000円・830,000円）とメモは未更新（販売終了で仕入れ値にならない）／IDENTITY_EVIDENCE は色違い（S/B）を区別しない（価格は同じ）／`audit_official_sources.py` の実行で FX3・R3 の `is_discontinued` が立ち、旧 UI の表示が「販売終了」に変わる／R3 のカートボタンの状態は未確認。
