# Wave 7e-1: Observability Aggregate（観測性）

目的: システムが本番で何を判断しているかを、**公開できる集計だけ**で監査できるようにする。取得件数を増やす Phase ではない。
確定・actionable・通知・Phase24 の基準は変えない（判定を読むだけ）。設計は Wave 7e Design Report（承認済み）。

## 実装

| 項目 | 内容 | 主なファイル |
|---|---|---|
| 公式の状態 | 全 canonical product を 1 回ずつ 12 状態に分類（VERIFIED_CURRENT / VERIFIED_DATED / RECHECK_MATCHED / SALE_ENDED / SOURCE_BLOCKED / SOURCE_NOT_REGISTERED / IDENTITY_NOT_MATCHED / PAGE_CHANGED / PRICE_CHANGED / STALE / CONFIGURED_REFERENCE / UNKNOWN）。既存の語彙（`evidence_gap.GAP_CAUSES`・`price_evidence`）と互換。確認済みを最初に判定するので、確認済みの状態の合計は既存の「公式の確認済み」と一致する。商品数は products から取得（47 をハードコードしない）。公開は状態別の件数（0 件も出す）だけ。個別の状態は `.private/research/official_state.json` | `src/research/official_state.py`・`candidates.py` |
| 期限の正本 | `normalized_prices.official_stale_days`（公式直販 14 日・それ以外 180 日）だけ。`verification_status`・`health_alert` も同じ値を使う。アラートの文言は実際の日数を示す。Switch 2（希望小売価格・180 日）の誤警報が消える。確認済みの判定（price_evidence）は変えていない | `official_registry.py`・`health_alert.py` |
| 確認日時 | `original_verified_at`（人の初回確認。登録簿の `checked_on` の意味を固定）・`last_verified_at`（実際に取得でき URL・価格・型番が一致した再確認の最新日）・`last_recheck_at` / `last_recheck_result`（最新の再確認から導出）。`stale_days` も行に出す | `official_registry.verification_status` |
| 更新規則 | `last_verified_at` を進めるのは「実際に取得でき、**型番など同一性を確かめた**（`recheck_identity_ok`）一致（unchanged）の再確認」だけ。failed・blocked・sale_ended・changed・希望小売価格だけの確認（msrp_lineup）・今日より未来の日付・記録と違う結果・型番が正本と違う／照合の値が無い（商品名だけ）結果では進めない。timestamp だけの更新はしない | `official_registry.advance_last_state`・`recheck_identity_ok` |
| 最終状態 | **別の永続ファイルは持たない**。公開済みの再確認の履歴（`exports/official_recheck/history.json`）から毎回導出する（`derive_last_state`）。履歴の保持は 2 本立て（`official_registry.trim_recheck_history`）: 通常の行は 35 日（公式直販の期限 14 日より長い）、無効化の行（changed・sale_ended）は商品ごとに最新の 1 件を 195 日（期限 180 日 + 余白 15 日）。登録簿の URL・価格が変わった商品は引き継がない。DB 側も、今日の再確認が失敗しても、履歴から導出した前回の実際の確認日を引き継ぐ（changed・sale_ended の商品・未来の日付・登録簿の確認日より古い日付・型番が違う結果は使わない） | `scripts/recheck_official.py`・`scripts/audit_official_sources.py` |
| 未来の日付 | `verification_status` が、未来の `checked_on`・未来の再確認の日付を無効として無視する（確認日が無ければ期限切れ = 安全側） | `official_registry.py` |
| 実行の観測性 | `scripts/run_observability.py`: `start`（最初の step。非公開 `.private/ops/run_timing_<lane>.json`）と `finish`（公開の前の step）。公開は `exports/ops/run_timing_<lane>.json` の `last_run_at`・`runtime_seconds`・`schedule_delay_seconds`・`trigger`・`lane` だけ。`schedule_delay_seconds` は定時（schedule）の最初の試行だけ。手動・再実行・cron が読めないときは null。例外の文面・URL・取得元・候補の詳細は書かない。lane ごとにファイルを分ける（将来の Fast Lane） | `scripts/run_observability.py`・`.github/workflows/daily_lp.yml` |
| Research Ledger | 公開の集計: `ledger_restore_status`・`cross_run_restored`・`ledger_version`・`momentum_comparable`・`detection_delay_measured`・`detection_delay_unknown`（固定の語彙・真偽・整数だけ）。**この実行の最初の生成で決めた復元の結果を、同じ実行の再生成（REUSED_WITHIN_RUN）で上書きしない**（最初の生成が state.json に `first_ledger_state` を残す）。従来の `ledger_state` は互換のためそのまま。検知の遅れの内訳に `already_processed`（前の run で処理済み）を追加し、`new_after_baseline == measured + 測れなかった（3 種）+ already_processed` を説明できる | `candidates.py`・`src/tcg/detection_delay.py` |
| Wave 5 変異テスト負債 | 3 件を整理: 2 件は OBSOLETE（置換元が現行コードに無い。等価な守りは Wave 6 の変異にあり、現行コードに合う変異へ更新）。1 件は本当のテストの穴（条件つき仕入れ値の行に点が付かない）をテストで固定（`tests/test_wave7e1_conditional_points.py`） | `scripts/mutation_wave5.py` |
| 日付だけの更新の検知 | `audit_timestamp_only_updates.py` が登録簿 `VERIFIED_URLS` の `checked_on` / `stock_checked_at` も検査（根拠のない日付だけの前進 = `TIMESTAMP_ONLY_REGISTRY`、過去への後退 = `CHECKED_ON_REGRESSED`）。価格・URL の変更・新しい日付のコメントの追加は人の確認として許す。再確認（RECHECK_MATCHED）は登録簿を書き換えないので対象外 | `scripts/audit_timestamp_only_updates.py` |
| deploy-check | #881 状態の合計 == 商品数（確認済みの状態の合計 == 既存の確認済みの件数）・#882 個別の状態は非公開・#883 未来の確認日は無効・#884 失敗・遮断などで確認日を進めない（窓が切れても戻らない）・#885 期限の正本の一致・#886 台帳の観測性・#887 実行の記録の許可リスト・#888 条件つき仕入れ値に点を付けない・#889 登録簿の日付だけの更新 | `scripts/deploy_check.py` |

## 判断した点（ユーザーに報告するもの）

- **商品ごとの最終状態の個別ファイルは新しく公開・保存しない**（受入前の修正で、`last_state.json` を廃止）。商品 ID・URL・価格・確認日の写しを長く保持する新しい公開物を作らないため、既存の公開履歴（`history.json`。日数で保持）から毎回導出する。公式の状態（SALE_ENDED など）の個別の分類は公開しない（`.private/research/official_state.json`。CI の実行機の上にしか存在しない）。履歴の保持は直近 300 件（約 18 日）から 35 日（上限 900 件）に延びた（既存の公開ファイルの保持期間の延長。新しい種類の情報ではない）。
- **DB 側の確認日の引き継ぎ**は、設計書の「最終状態を保持する」の実装。履歴から導出するので初回の本番 run から効く。確認済みの件数は変わらない見込み。実際に一致し、型番を確かめた過去の確認日だけが引き継がれる。
- **実行の記録の所要時間**は、最初の step から公開の前の step まで（deploy-check・prelaunch・commit の時間を含まない）。
- **GR IV HDF の価格の不一致（抽選 187,020円と公式 222,000円）は変更していない**。別途、人の確認対象。

## 未確認（本番の run で確認する）

- `github.event.schedule` が定時の run で `17 3 * * *` として渡ること（渡らなければ `schedule_delay_seconds` は null のまま = 安全側）。
- 初回の本番 run での official_state_counts の内訳（合計 == canonical_products・確認済みの状態の合計 == 16）。
- `ledger_restore_status` が REUSED_WITHIN_RUN ではなく復元の結果（RESTORED_FROM_PREVIOUS_RUN など）になること。

## レビューでの修正（2 回）

1 回目の reviewer・auditor（Medium 各 1〜2 件）→ 修正 → 2 回目（reviewer・auditor とも Critical 0・High 0・Medium 0）。

- **M-1（両者）**: 販売終了・価格変化の翌日に取得の失敗・遮断が続くと、DB の確認日が古い last_state の確認日に戻り、確認済みが復活する。→ `advance_last_state` が `changed` / `sale_ended` を観測したら `last_verified_at` を空にして無効化（実際に一致した再確認が来るまで空）。`apply_recheck` も、直近の結果が `changed` / `sale_ended` の商品は引き継がない（二重の防御）。3 日の手順（一致 → 販売終了 → 遮断）・価格変化版・初回の履歴からの初期化後の経路を、回帰テストと変異テストで固定。
- **M-2（reviewer）**: last_state の初回が履歴から作られない（窓が切れると確認日・連続失敗が戻る）。→ `last_state_for_run`（最終状態が無い・空のときは履歴全体から作ってから今回の結果を進める）。実データで、履歴だけの場合と、窓が切れた後の最終状態だけの場合が全商品で一致した。
- Low の修正: 引き継ぐ確認日が未来なら無効化（固着しない）／公開集計の `official_state_counts` が数値でない値で例外にならない／引き継ぎ時に `product_source_config.last_verified_at` も更新。

## 確認済みの件数への影響（実データでの確認）

- 初回の本番 run で確認済み（16/47）は変わらない見込み。DB 側の確認日が動くのは A7RV だけ（10-28 → 11-04。実際に 11-04 に一致した再確認の引き継ぎ）。今日は期限内（確認済み）のまま。**11-11 以降も確認済みのまま残る期間が、従来（11-11 に STALE）より 11-18 まで延びる**（意図した効果。実際に一致した再確認の確認日だけが引き継がれる）。

## 残る Low（記録のみ・コードはゲート後に変更していない）

- （解消）引き継ぎ側が型番の照合を通らなかった点は、受入前の修正で `recheck_identity_ok`（型番・公式の証拠・照合の値）を通すようにした。商品名だけの一致・型番違い・正本が読めないときは引き継がない（fail closed）。
- 運営者向けの劣化アラート（`verification_status`）は、履歴の窓内に過去の unchanged が残るあいだ、販売終了・価格変化の後も古い確認日を使う（期限切れアラートが遅れる偽陰性だけ。確認済み・通知の判定には効かない。履歴ベースの既存の挙動）。
- （解消）最終状態の導出に渡す履歴が今回の結果を含む点は、導出が履歴だけから行われるので前提ではなくなった。
- DB は毎回登録簿から作り直されるため、販売終了の「確認済みを外す」操作は当日限り。3 日目の遮断では登録簿の `checked_on` の確認日に戻る（既存の挙動）。
- （解消）`last_state.json` は廃止した（上記）。
- `schedule_delay_seconds` は、予定から 24 時間以上遅れた実行では過小になる（直前の予定の時刻を採るため。実測の遅れは 4〜8 時間）。
- 登録簿の日付だけの更新の検知は、新しい確認日を含むコメントが商品の範囲に 1 行あれば通る（人の確認の慣習。機械的な保証ではない）。

## 受入前の修正のレビュー（reviewer・auditor 各 1 回）での判断

- **Auditor M-1（修正済み）**: 販売終了・価格の変化の後に失敗・遮断が続くと、`verification_status` が登録簿の `checked_on` の確認日に戻り、期限アラートが沈黙した。→ 最終状態に `invalidated_at` を持たせ、観測の日より前の確認日（登録簿の人の確認日を含む）は使わない。人が確かめ直す（`checked_on` が無効化の日以降）か、同一性を確かめた一致の再確認で復帰する。結果の行で #890 と回帰テストを固定。
- **残る Low**: ①（最終ブロッカーで解消。下の「履歴より長い期限の商品」）。②旧記録に対する changed が、直した直後の新しい記録を最大 1 日誤って無効にする（誤警報のみ）。③型番を持つ商品の `match` は空でないことだけを見る（`model`・`match` は再確認の対象設定由来で、ページ照合は取得器側の unchanged 判定に依存）。④DB 側の同一性は DB の商品行で見る（ローカルの古い DB では引き継ぎが止まる。CI は毎回 yaml から作るので一致）。
- 確認済みの期間: A7RV は 11-18 まで延びる（実際に一致した 11-04 の確認。偽の鮮度ではない）。

## 履歴より長い期限の商品（最終ブロッカーの修正。C-event 方式で確定）

**問題**: 履歴は 35 日だけ保持していたため、期限が 180 日の再確認の対象（PS5 Pro・Switch 2。msrp）では、35 日より前の販売終了・価格の変化が履歴から消え、その後に取得の失敗・遮断が続くと、登録簿の古い `checked_on` の確認日へ戻り、確認済みが復活しうる。最初の対処（履歴の範囲外の確認日を使わない）は、無効化の無い Switch 2 まで 32 日で確認済みから外した（180 日の期限を保存方式の都合で 35 日に縮めていた）ので、採らない。

**保存先の再調査（READ-ONLY）**: ①非公開の永続は `RESEARCH_LEDGER_KEY` の台帳だけ（鍵の流用・新しい Secret・7e-2 の先取りになる）②登録簿には自動観測の無効化を導出できる情報が無い（`OFFICIAL_NOT_SOLD` は人が書く永続的な無効化で既に効く。CI は浅い checkout で git の履歴も使えない）③履歴を全件で 195 日に伸ばす案（約 970KB）は、公開の保持が全商品で延びる。→ **④無効化の行だけを 195 日残す（C-event）を採用**。新しい項目・ファイル・Secret・非公開の成果物なし。

**規則（`official_registry.trim_recheck_history`。`recheck_official.trim_history` が使う）**:
- 通常の行（unchanged・failed・blocked ほか）: 直近 35 日・最大 900 件。
- 無効化の行（changed・sale_ended）: 195 日（180 日 + 15 日）以内の、**商品ごとに最新の 1 件**。件数の上限は通常の行にだけ掛け、無効化の行を消さない。古い無効化は、最新の無効化が「それより前の確認日を使わない」で覆うので残さない。
- 回復の行: 最新の無効化より後の、同一性を確かめた確認日を進める一致（unchanged）の最新 1 件も同じ 195 日残す（reviewer の Medium: 回復の行が 35 日で消え、古い無効化が回復済みの現在を無効にする）。無効化の無い商品の通常の行は 35 日のまま。
- 時刻は `datetime` で比べる（naive は JST・Z も可）。読めない行・未来の行は捨てる（壊れた時計・行が本物の無効化を追い出さない。auditor L-1）。無効化は現行の記録（URL・記録価格）に対する観測だけが効く（auditor L-3）。
- 判定は従来のまま（`invalidated_at` より前の確認日は使わない）。無効化より新しい人の確認日（`checked_on`）・同一性を確かめた延長一致の再確認で復帰する。無効化が観測より新しい確認日で上書きされない限り、180 日の間は消えない（無効化 > 確認日 なら、無効化は確認日より新しく 180 日以内に必ず残る）。
- 確認日を進めない再確認（Switch 2 の msrp_lineup）は、従来どおり確認日を進めない。無効化が無ければ、履歴（35 日）を超えても 180 日の期限まで確認済みのまま。
- DB 経路（`apply_recheck`）: 登録簿の確認日が無効化の観測より古い商品は、今回の観測と同じ扱い（価格・確認日を消し、人の確認待ち）。無効化の行が 195 日残るので、観測の 11〜200 日後でも戻らない。

**公開量（実データ）**: 現在の履歴は 300 行（通常 300・無効化 0）・約 112KB で、整理後も同じ（通常の行は 15 商品 × 35 日で最大約 525 行・約 180KB。上限 900 行でも約 300KB）。無効化の行は起きたときだけ、商品ごとに 1 行 + 回復の行 1 行（各約 300 バイト）。最悪（再確認の対象 15 商品すべて）でも約 9KB。新しい項目・ファイル・URL・価格・候補の対応は 0（既存の行を、無効化の行だけ 195 日残す）。

**Switch 2**: 無効化なし・`checked_on`=2026-10-08・msrp_lineup。確認済みのまま（確認済み 16 のまま。以前の厳格版の 16 → 15 は撤回）。

**検証**: `tests/test_wave7e1_long_horizon.py`（保持 9 種・長期 200 日のシミュレーション・人の再確認・Switch 2・実際の DB 経路・公開量）。deploy-check #892。変異テスト（7e-1）に保持の変異 8 件。

**最終監査での追加の修正（auditor 2 回目）**: **Critical（修正済み）**: 実際の取得では各結果の `observed_at` が `main` の開始時刻より後になり、「未来の行は捨てる」が今回の結果を全部捨てた（履歴に何も残らず、無効化の持続が働かない。テストは now を固定して渡すので検知できなかった）。→ 整理の基準を取得の後の現在時刻にし、許容幅（1 時間）を持たせた。`main` を通す回帰テスト・deploy-check #892・変異を追加。**Medium（修正済み）**: 無効化の最新 1 件を現行の記録（URL・記録価格）に対する観測に限った。**Low（修正済み）**: `advance_last_state` は時刻で並べ、日付は JST にした。\n\n**残る Low（監査記録のみ）**: 人の確認日が観測と同日のときの順序／`advance_last_state` の `invalidated_at` の `max(str)`（将来の永続化の潜在リスク）／現在の履歴の入力の重複／定時の 24 時間の遅れの表現／履歴ファイルが消えた・壊れたとき（`recheck_official` は今日の結果だけで上書きする）は無効化の記憶が失われる（auditor L-2。壊れた履歴の検出・復元は別の問題）／同じ秒の観測の順序・Switch 2 は無効化の後、人が `checked_on` を更新するまで自動では復帰しない（仕様）／履歴ファイルが壊れたときは窓内の無効化を知らない（壊れた履歴の検出は別の問題）。

**最終ゲート（C-event。最終差分）**: pytest 2943・変異 7e-1 0/55・7c 0/87・7b 0/79・7a 0/90・Wave 6 0/58・Wave 5 0/28・deploy-check（エラー 0。#892 追加）・prelaunch エラー 0・ruff は変更ファイルで新規 0（既存 10）。reviewer（3 回目）・auditor（3 回目）とも Critical 0 / High 0 / Medium 0。auditor は実運用の経路（fetch の差し替え → recheck → trim → history 書き込み → 翌日以降の導出 → DB 経路）を 228 日分再現し、販売終了・価格変化の復活・Switch 2 の脱落・履歴の肥大がないことを確認した。

**最終ゲートの残る Low（修正しない。安全側または破損・時計のずれのときだけ）**: ①`last_recheck_result` の更新だけ文字列比較（`+09:00` と `Z` が混在するときだけ。現在は全部 `+09:00`）②壊れた `observed_at`（`0001-01-01` など）が `derive_last_state`・`verification_status` に直接渡ると `OverflowError`（整理済みの履歴は安全。履歴は `recheck_official` だけが書く）③人の確認日と同日の観測の順序（`checked_on == 観測日` は無効化にならない）④時計が 1 時間より先に進んだ行は無効化の行も捨てる（NTP 同期のランナーでは低リスク）⑤許容幅 1 時間内の未来行が回復として残りうる（履歴ファイルの手動改ざん・時計のずれが前提）⑥`history.json` の `results` が list でないと `TypeError`（以前から）。

## 判定

**`WAVE_7E1_PRECOMMIT_GATE_READY`**（最終差分。reviewer・auditor とも Critical 0・High 0・Medium 0）。commit・push 済み。**本番での確認は未了（最初の定時の run の後）**。期待値: 公式の状態の合計 == `canonical_products`・確認済みの状態の合計 == 16（Switch 2 も確認済みのまま）・`ledger_restore_status` が REUSED_WITHIN_RUN で上書きされない・`schedule_delay_seconds` が取れる（取れなければ null）・履歴は通常の行 35 日・無効化の行 195 日・件数の上限で無効化が消えない・確定 / actionable / Phase24 に意図しない変化がない・偽の鮮度 0・公開の漏れ 0・外部送信 0。

