# Phase 25 — 実データの行動できる候補の検知と Phase 24 の受入状態

作成: 2026-10-14。検知・記録・見える化だけ（商品の通知・運営者への通知のどちらも外部へは送らない）。変数・関門は変えない。

## 1. 開始の時点

| 指標 | 値 |
|---|---:|
| 確定の利益商品 / 今すぐ行動できる / 新たに行動できる | 2 / 0 / 0 |
| 通知の候補 / READY の outbox / Telegram の商品の送信 | 0 / 0 / 0 |
| 健康度（health の合計） | 37.9 |
| CI の所要時間（直近の Daily LP Update） | 1時間7分 |
| pytest | 1897 passed |

## 2. 判定（`src/notifiers/readiness.py`）

新しい判定のロジックは作らない: 行動できるか・利益・期限・締切・公式のページは Phase 18 の正本（診断の行）と Phase 19 の
`revalidate_fields`、変化と同一性は Phase 19〜23 の outbox の記録（冪等性のキー）、古さは Phase 23 の上限（24時間）、優先の順は
既存の順位（診断の行の並び）。

| 状態 | 条件 |
|---|---|
| `PHASE24_REAL_CANDIDATE_READY` | 次をすべて満たす候補が1件以上: 実データの「行動できない → できる」の記録がある・今も同じ変化（今のキー）で行動できる・確定の利益・在庫の確認が新しい（抽選などは締切の前）・公式の購入/申込のページ・検知から24時間以内・送っていない / 届いたか不明でない / 取り消していない・本番の方式の記録を作れる（`outbox.handoff_ok`） |
| `PHASE24_WAITING` | 候補が無い |
| `PHASE24_REVIEW_REQUIRED` | 判定できない（診断の失敗・判定が無い・台帳が無い・判定の例外・今回の run の出力でない）・受入の送信が届いたか不明（人の解決待ち）。READY と推測しない |
| `PHASE24_ACCEPTANCE_DONE` | 受入で商品の通知を送った（本番の DELIVERED がある）。残りの候補は HELD（保留）にして READY にしない（受入は1件だけ） |

検知の結果: NO_ACTIONABLE_CHANGE / NEW_ACTIONABLE_FOUND / ACTIONABLE_STILL_PRESENT / ACTIONABLE_LOST（/ DETECTION_FAILED /
ACCEPTANCE_COMPLETED）。受入の実行で引き継いだ記録は新しい検知に数えない。
候補の移り変わり: READY / EXPIRED（検知から24時間）/ INVALIDATED / DELIVERED / CANCELLED / UNKNOWN_DELIVERY / HELD。

CI の「Phase24 readiness summary」（Send の後）は、今の台帳で判定し直して出力を書き直す（`readiness.refresh`）。今回の生成の報告
（latest.json）が今回の診断・今回の run（GITHUB_RUN_ID）のものでなければ REVIEW_REQUIRED（前回の出力を今回のものとして出さない）。
今回の run で送った件数と「追加の手動の実行はしない」を出す。

- 前の状態を見ていない（基準日）商品が行動できても候補にしない（変化を見ていない）
- 検知の時刻はその変化の記録のうち最も古い created_at（実行のたびに新しくしない）。履歴の changed_at は状態が変わったときだけ進む
- 候補の ID は冪等性のキーのハッシュ（キーは出さない）。同じ候補は毎回新規にしない。履歴は最大50件（台帳の記録の保存期間に従う）

## 3. Phase 24 への引き継ぎ（`outbox.adoptable_dry` / `handoff_ok`）

定時の実行（dry-run）で検知した変化は、dry-run の記録と消えない印（arm_used / known_events）が付くため、これまでは本番の実行で
送れなかった（Phase 20 の監査 M-1）。これでは受入状態が READY になっても Phase 24 で送れないので、本番の方式の observe が、
dry-run の記録（PENDING / READY / DRY_RUN_PLANNED・検知から24時間以内）の変化を1件だけ引き継ぐようにした:

- 本番の記録の created_at は dry-run の記録のまま（古さを新しくしない）・`adopted_from` を持つ
- 同じキーの本番の記録は1件だけ（2回目は重複の抑制）。24時間を過ぎた変化・取り消した dry-run の記録は引き継がない
- Phase 20 の「dry-run で計画した古い変化を本番で送らない」は「検知から24時間を過ぎた変化を送らない」になった（M-1 の意図
  「何日も前の『行動できるようになった』を送らない」は保つ。test_phase20 と #856 は25時間後の形に直した）
- 送るのは Phase 23 の関門（手動の実行・変数・限定モード）を通ったときだけ・run ごとに最大1件・送る直前の確かめ直し・canary の排他は
  そのまま。定時の実行は送らない

## 4. 出力

- `exports/notifications/actionable/phase24_readiness.json`: status・detection・actionable・candidate_count・candidate_ids・
  candidates（順・商品・利益・ROI・種類・状態・締切・確認・検知・古さ）・top_candidate・send_limit・external_sends（0）・history・
  generated_at。秘密の値・キー・配信先の ID は無い
- 運営者向け: 「Phase 24 の受入状態」（状態・今回の検知・行動できる商品・受入候補・上限・外部への送信 0・候補の表・履歴・
  READY のときの手順）。見るだけ（送信のボタン・フォームは置かない）
- CI: 「Phase24 readiness summary」の手順（Secrets・通知の変数を渡さない）が出力と GitHub Actions の Summary に書く。
  Issue・PR・メールなどの書き込みはしない

## 5. 検査・テスト

- deploy-check #860（候補なしは WAITING・実データの変化だけ READY・同じ候補・検知の時刻・24時間・無効・送信済み・引き継ぎ1件・
  判定の失敗・関門の既定・手順の Secrets・今の出力の形 / 秘密の値 / 診断との一致）
- テスト: tests/test_phase25_readiness.py（Phase 18 の判定から作った行。本番には入れない）
- mutation: 19/19 をテストで検出（受入の後も READY・前回の run の出力を今回とする・再試行の時刻の前に引き継ぎ可・台帳が無くても
  判定する・引き継ぎを新しい検知にする、を加えた。候補なしで READY・期限切れ / 送信済み / 無効が READY のまま・検知の時刻を新しくする（引き継ぎ /
  判定）・履歴の時刻を毎回新しくする・判定の失敗を READY・24時間を過ぎた変化を引き継ぐ・引き継げない候補を READY・同じ変化を
  2回引き継ぐ・定時の実行で送る・受入状態の手順に Secrets・画面が読めない状態を READY）

## 6. レビュー・監査の指摘（対応済み）

- Medium（両方）: 受入の実行で送った後も、Summary・出力が observe の時点の READY のまま（2通目の手動の実行につながる）・生成が
  落ちた run の Summary が前回の出力を出す → 送信の後に今の台帳で判定し直す（refresh）・今回の run の出力でなければ REVIEW_REQUIRED・
  送った件数と「追加の手動の実行はしない」を出す
- Medium（レビュー）: 受入で1件送った後も残りの候補が READY → PHASE24_ACCEPTANCE_DONE（残りは HELD）。届いたか不明・SENDING が
  あれば REVIEW_REQUIRED
- Low: 診断に判定が無い・台帳が無いときは REVIEW_REQUIRED・画面と CLI は壊れた READY を REVIEW_REQUIRED に落とす・引き継いだ記録を
  新しい検知に数えない・handoff_ok を prepare の再試行の時刻 / 試行の上限に合わせる・ACTIONABLE_LOST は前回の履歴の READY でも・
  通知を作らない生成では欄を出さない・判定できない理由を残す・受入の実行の検知は ACCEPTANCE_COMPLETED・画面の READY の欄に
  「生成の時点・直前の Summary が受入済みなら実行しない」

## 7. 残している点（Low）

- 受入状態は表示だけで、送信を止める関門ではない: 受入の後に変数を戻さずに別の run で手動の実行をすると、保留の2件目が送られうる
  （Phase 23 の関門の設計のとおり・保留は検知から24時間で期限切れ）。受入の手順の最後に変数を安全な値に戻す
- 受入で送った記録が30日で prune されると、受入済みの表示は消える（その後に新しい候補があれば READY になる）
- 公開の運営者向けの画面は生成の時点（送信の前）。送信の結果は、その実行の Summary と phase24_readiness.json

## 8. 本番の確認

（本番の確認の後に記入）
