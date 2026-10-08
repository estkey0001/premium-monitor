# Phase 20 — 通知の outbox（送っても二重に送らない基盤）

作成: 2026-10-09。外部への送信（Discord・Telegram・webhook）はしない（dry-run 固定・送信先の transport をつながない）。

## 1. 基準（Phase 19 の生成物 6e2ae4ac）

| 指標 | 値 |
|---|---:|
| 今すぐ行動できる | 0 |
| 行動できるようになった（診断） | 0 |
| 通知の候補 / 重複の抑制 / dry-run の計画 | 0 / 0 / 0 |
| 外部への送信 | 0 |
| 台帳の記録 | 2商品（PS5 Pro 在庫切れ・GR IV HDF 抽選終了。通知済みなし） |
| CI の所要時間 | 68.6分 |

## 2. 保存の監査（Phase 19 まで）

- 台帳（exports/notifications/actionable/state.json）は、最後の「Commit and push」（生成物のコミット）だけで main に残っていた
- その手順は `if: always()` が無いので、deploy-check の失敗・生成物の push の失敗で台帳が残らない（次の実行で同じ候補をもう一度計画する。
  送信を有効にすると二重送信になる）
- Pages は別の workflow（pages-build-deployment）で、リポジトリを書き換えない（台帳を戻さない）
- 並行の実行は workflow の `concurrency: daily-lp-update`（cancel-in-progress: false）で並ぶ

## 3. 設計（`src/notifiers/outbox.py`）

候補 → outbox（PENDING を保存）→ 配信の直前の確認（dry-run は DRY_RUN_PLANNED・本番は SENDING を保存）→ 送信 → 結果を保存。

- 台帳（products）と outbox（records）は1つのファイル。内容が変わったときだけ atomic に書く（`save`。時刻だけの書き換えをしない）。
  同じ機械の上の読み書きは `locked`（fcntl）で排他。候補の途中で失敗したら保存しない（不完全な outbox を作らない）
- 記録: notification_id・idempotency_key・mode・product_id・notification_type・state_transition・availability_kind・event_id・deadline・
  action_url・net_profit・roi・created_at・status と、配信先ごとの status・attempts（attempted_at・status・provider・
  provider_delivery_id・error_class）・attempt_count・next_attempt_at
- 状態: PENDING・READY・SENDING・DELIVERED・DRY_RUN_PLANNED・FAILED_RETRYABLE・FAILED_FINAL・CANCELLED・EXPIRED・UNKNOWN_DELIVERY
- 冪等性のキー: `ACTIONABLE_NOW:<商品>:direct:<arm>`（通常販売）か `ACTIONABLE_NOW:<商品>:event:<商品|受付の開始>`（抽選・予約・先着）。
  配信先・方式に依らない。notification_id = sha256(キー|方式)。outbox は (キー, 方式) で1件
  - arm = 行動できないと確かめた観測（連番:状態@確認時刻）。在庫切れ・販売終了で新しい arm（re-arm）。在庫未確認・更新待ちでは
    新しくしない。初めて見た商品・抽選の受付中（一般販売で買えない）でまだ arm が無ければ arm を作る
  - 受付の識別は開始まで（締切を含めない）: 締切の延長だけでは再通知しない（締切の変更の通知は将来の別の種類）。
    日付だけの開始と 0:00 の開始は同じ時刻に読む（同じ受付）
- 消えない印: 記録を作った変化は、方式（dry-run / 本番）に依らず作り直さない（通常販売は arm_used、抽選などは known_events に
  締切から30日まで。締切が延びたら印も延ばす）。記録が prune で消えても同じキーを送り直さない。dry-run で計画した古い変化は、
  本番に切り替えた時点では送らない（切り替えた後の新しい変化から送る）
- 基準日: 台帳が無い・壊れている・前回を見ていない商品（新しい・利益から外れていた）が行動できる → 記録だけ（通常販売は arm を使い切る・
  抽選などは known_events に締切まで）。診断の行が0件の実行では台帳を変えない
- 配信の直前の確認（prepare）: 最新の診断の行で、今も同じキーで行動できるか・Phase 19 の4条件（期限・締切・公式のページ・確定の利益）。
  期限・締切 → EXPIRED、行動できない・利益が確定でない・URL → CANCELLED。本文と利益は最新の確定の値（計算し直さない）。
  送っていない（EXPIRED・CANCELLED）記録は、同じ変化がまた行動できれば同じキーで配信待ちに戻す
- 送信（send）: この実行（attempt_id）の SENDING だけを1回ずつ送る。前の実行の SENDING は UNKNOWN_DELIVERY（送った後に保存できずに
  止まった可能性。自動では送り直さない）
- 失敗: 接続できない・429・503 → FAILED_RETRYABLE（Retry-After か 5分から倍・上限6時間。`api_runtime.parse_retry_after` を再利用）、
  認証・宛先・本文の誤り（長すぎる本文を含む。切り詰めない）→ FAILED_FINAL、送った後の切断・500/502/504・想定外の例外
  → UNKNOWN_DELIVERY。試行は5回まで
- dry-run: DRY_RUN_PLANNED（DELIVERED にしない）。記録は方式ごと。本番に切り替えた後の新しい変化は送る（dry-run の記録は止めない）。
  方式が変わったら、前の方式の配信待ちは CANCELLED
- 古い記録: 終わってから30日を過ぎたものを消す（今の候補のキーは消さない）

## 4. 配信先（`src/notifiers/adapters.py`）

Discord（content 2000文字・一斉の呼び出しなし）・Telegram（text 4096文字。chat_id は transport が付ける）・log（内部のログ）。
本文の組み立て・検査・応答の分類（classify_http）だけ。HTTP の部品を import しない。transport を渡さないと送れない
（Phase 20 はどこからも渡さない）。配信先の URL・トークン・チャット ID は台帳・本文・ログに入れない。

## 5. ワークフロー

```
Sync notification outbox                     main の最新の台帳を取り出し、その版を基準に残す（待たされた実行・再実行が古い台帳から始めない）
→ Generate daily LP（診断 → outbox に PENDING。合わせられなかったら候補を作らない）
→ Persist notification outbox (candidates)   always・台帳だけをコミットして main に push・sha を出す
→ Prepare notification dispatch              dry-run → DRY_RUN_PLANNED（本番なら SENDING）
→ Persist notification outbox (prepared)
→ Send notifications                         --persisted-sha（保存した台帳と今のファイルが同じときだけ送る）
→ Persist notification outbox (sent)
→ … → Deploy check → Commit and push（生成物）
```

- 保存（`scripts/persist_notification_state.sh`）: main の最新を一時的な worktree に取り出して台帳だけを写してコミット（作業ツリーの
  生成物に触れない・stash や rebase をしない）。main の台帳が同期・前回の保存の後に変わっていたら上書きせずに止める（別の実行の記録を
  消さない）。内容が同じなら何もしない。push の失敗は取り直して3回まで。秘密の値の形（大文字小文字を区別しない）があれば保存しない
- 最後の「Commit and push」は台帳を含めない（台帳の保存は persist だけ。人の push などで main の台帳が変わっても上書きしない）
- 準備・送信は、取り消されたジョブでは動かさない・今回の生成（診断）が成功したときだけ。prepare は今回の候補の記録と同じ診断かを確かめる
- 生成物のコミット・deploy-check・Pages の成否に関わらず、台帳は手順ごとに残る
- dry-run に固定（NOTIFICATION_DRY_RUN "true"）。通知の送信先の Secrets はどの手順にも渡さない

## 6. 送った後に止まる場面（crash window）

| 場面 | 結果 |
|---|---|
| 送る前（PENDING を保存する前） | 送らない（送信は保存した台帳の sha が今のファイルと同じときだけ） |
| SENDING を保存した後・送る前に止まる | 次の実行で UNKNOWN_DELIVERY（送らない。届いていないのに送らない側＝取りこぼし） |
| 送った後・DELIVERED を保存する前に止まる | 次の実行で UNKNOWN_DELIVERY（送り直さない） |
| 送って保存した後に deploy-check・生成物のコミット・Pages が失敗 | 台帳は保存済み（次の実行は送らない） |
| 応答を受け取る前に切断 | UNKNOWN_DELIVERY（自動では送り直さない） |

配信先の冪等性（Discord・Telegram に重複を除く仕組みがあるか）は前提にしない。

## 7. 運営者向け・集計・検査

- 運営者向けの「通知」: 今回の候補・抑制・基準日の件数と、outbox の配信待ち・dry-run の計画・送信済み・失敗（出し直す/出し直さない）・
  期限切れ・取り消し・届いたか不明（この画面の生成の時点。配信の直前の確認・送信はこの後の手順）
- 集計（production_coverage_metrics）: outbox_pending・dry_run_planned・delivered・retryable_failed・expired・ambiguous_delivery・
  dedupe_suppressed
- deploy-check #855（候補の規則を outbox の上で）・#856（冪等性のキー・送った後に止まったら送り直さない・保存の前に送らない・dry-run は
  送信済みにしない・atomic・HTTP の部品なし・手順の順序と always・dry-run 固定・Secrets を渡さない・台帳に秘密の値・本番の送信の記録なし）
- テスト: tests/test_phase20_notification_outbox.py（Phase 19 のテストは outbox の上に移した。tests/_notify_helpers.py）
- mutation: 16/16 をテストで検出（冪等性のキーを消す・同じ記録を重ねる・消えない印を外す・失敗を DELIVERED・dry-run を DELIVERED・期限切れを送る・
  利益が消えても送る・同じ受付を2回・atomic でない書き込み・前の実行の SENDING を送り直す・保存を確かめずに送る・
  届いたか不明を出し直す・再試行の上限を外す・dry-run の記録が本番を止める・re-arm に連番なし・Retry-After を無視）

## 8. レビュー・監査の指摘（対応済み）

- High（監査）: 待たされた実行・再実行が古い台帳から始め、台帳の衝突でこの実行の側を採って先の記録を消す → 生成の前に main に合わせ、
  保存は main の台帳が変わっていたら止める
- High（監査）: 保存の `--autostash` で生成物に衝突の印が残る → 作業ツリーに触れない worktree で保存
- High（監査）: 記録が prune で消えた後に同じキーを送り直す → 消えない印（arm_used・known_events）
- Medium（監査）: dry-run で計画した何日も前の変化を本番に切り替えた時点で送る → 消えない印で送らない
- Medium（レビュー）: 最後のコミットが台帳を含み、衝突でこの実行の側を採って上書きする → 台帳を含めない
- Medium（レビュー）: 生成に失敗した実行でも古い診断で確かめ直して送る → 生成の成功を条件にし、prepare で同じ診断かを確かめる
- Low: 秘密の値の形（JSON の Authorization・URL の無いトークン・小文字）・想定外の transport の例外と 500/502/504 は届いたか不明・
  送信先が無いときの時刻だけの書き換え・手元の実行の識別・本文を切り詰めない（URL を欠かさない）・取り消されたジョブでは送らない

## 9. 残している点（Low）

- 確定の利益から外れている間の在庫の変化は追わない（Phase 19 のまま。誤通知より取りこぼし側。戻ったときは記録だけ）
- 送る前に止まった SENDING も UNKNOWN_DELIVERY になり、自動では送らない（二重送信より取りこぼし側）
- 運営者向けの outbox の件数は画面の生成の時点（その後の配信の直前の確認・送信の結果は次の生成で出る）
- 1回の実行で台帳の保存のコミットが最大3つ増える（内容が変わったときだけ。今の本番は変わらないので0）。push のたびに Pages の
  再構築が走る
- UNKNOWN_DELIVERY を人が確かめて片付ける手順（届いた/届いていないを記録する）は無い
- 手元（RUNNER_TEMP が無い環境）で sync を動かさずに persist だけを動かすと、前回の手元の基準のファイル（/tmp）を使う
  （CI では RUNNER_TEMP がジョブごとに新しい。persist は手元では実行しない）
- 最後の「Commit and push」の autostash で、手元の未コミットの台帳に衝突の印が残ることがある（台帳はコミットから除くので main に影響しない）
