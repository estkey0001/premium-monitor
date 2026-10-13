# Phase 23 — Telegram の商品の通知の限定運用

作成: 2026-10-14。配信先は Telegram だけ（Discord は無効）。1回の実行で送る商品の通知は最大1件。初回は手動の実行だけ。

## 1. 開始の時点

| 指標 | 値 |
|---|---:|
| Telegram の接続の試験（Phase 22） | DELIVERED（message_id 保存・重複 0） |
| 今すぐ行動できる / 候補 / 商品の本番の記録 | 0 / 0 / 0 |
| 変数 | TELEGRAM_CANARY=false・NOTIFICATION_REAL_SEND=false・NOTIFICATION_DRY_RUN=true・NOTIFICATION_PROVIDERS=telegram |
| pytest | 1850 passed |

## 2. 関門（`adapters.real_send_gate(purpose="product")`）

すべてそろったときだけ開く（値は返さない）:

- 配信先が Telegram だけ（`NOTIFICATION_PROVIDERS=telegram`）・`NOTIFICATION_REAL_SEND=true`・`NOTIFICATION_DRY_RUN=false`
- `PRODUCT_REAL_SEND_ENABLED=true`（リポジトリの変数。既定 false。ワークフローは手動の実行のときだけ読む）
- 限定モード（`PRODUCT_NOTIFICATION_LIMITED_MODE`。既定 true。false にすると閉じる。全開放の経路は作らない = `PRODUCT_UNLIMITED_ALLOWED = False`）
- 手動の実行（`GITHUB_EVENT_NAME=workflow_dispatch`。定時の実行では開かない。初回の後も自動で開けない）
- Telegram の設定（トークン・チャット ID）がそろって形が正しい

Secrets を持たない手順（LP の生成・配信の直前の確認）は `product_live_intent`（設定を見ない同じ判定）で本番の方式にするかを決め、
送信の手順が設定を含めて確かめ直す。

## 3. 1回の実行で最大1件

- 上限は `PRODUCT_SEND_LIMIT_PER_RUN = 1`（コードで固定。変数で増やせない・成功しても外さない）
- 配信の直前の確認（prepare）: 確かめ直しを通った候補を既存の順位（診断の行の並び = 行動できる商品が先・利益商品の順位）で並べ、
  先頭の1件だけを SENDING にする。残りは READY（`limited_send_hold`。試行に数えない）で次の実行に回す
- 送信（send）でも上限をかける（SENDING が2件あっても1件だけ送り、残りは READY に戻す）
- 接続の試験（canary）は再送しない（同じ ID は DELIVERED のまま。`TELEGRAM_CANARY=false`）

## 4. 送らないもの（確かめ直し）

prepare と send の直前の両方で Phase 19 の4条件を確かめる: 行動できる種類・理由なし・確定の利益（参考の利益は送らない）・期限
（在庫の確認から3時間）・抽選などは締切の前・公式の購入/申込のページ（一般のページは送らない）。行動できない・古い在庫・
締切切れ・終了した抽選は送らない（偽の状態・価格・期限で候補を作らない）。

## 5. 方式（dry-run / 本番）の切り替え

- 本番の方式の記録の配信先は Telegram だけ（`LIVE_CHANNELS`）
- 定時の実行（dry-run）は本番の記録を送らない・取り消さない。期限切れ・行動できなくなったものだけを EXPIRED / CANCELLED にする
  （次の手動の実行で確かめ直して送る）。同じ移り変わりの dry-run の記録は作らない（消えない印 arm_used / known_events）
- 本番の実行は dry-run の配信待ちを送らない（mode_changed で取り消し。Phase 20 のまま）
- 送信の手順の関門が閉じていた・dry-run・保存した台帳と違う → この実行の SENDING を READY に戻す（送信の要求の前なので、
  届いたか不明にしない）。送った後・保存の前に止まったものは、次の実行で届いたか不明（Phase 20 のまま）

## 6. 重複・再通知（Phase 19・20 のまま）

同じ冪等性のキーは送り直さない（在庫ありが続くだけ・同じ受付・締切の延長だけでは送らない）。在庫切れ → 在庫ありの新しい移り
変わり（re-arm）は別のキーで送る。同じ workflow の再実行（attempt が変わる）は、前の SENDING を届いたか不明にして送らない。

## 7. 応答

200 かつ ok=true かつ message_id → DELIVERED（message_id を provider_delivery_id に保存）。message_id なし・500 / 502 / 504・
タイムアウト → 届いたか不明（自動で送り直さない。人が CLI で解決）。400 / 401 / 403 → 出し直さない。429 / 503 → 出し直す
（Retry-After の後。同じ実行の中では送り直さない）。

## 8. 表示

- 運営者向け: 商品の通知の本番の送信（有効/無効）・限定モード・1回の実行の上限・今日の送信・配信待ち・送信済み・届いたか不明・
  送信の失敗・送信した商品の通知の履歴（商品・種類・利益・時刻）。値・配信先の ID は出さない
- マイページ: 実際に送った（DELIVERED）通知だけ。dry-run の計画・配信待ちは出さない

## 9. Secrets・ワークフロー

- Telegram の Secrets は「Send notifications」の手順だけ（#857 の検査のまま）。Generate・Prepare には変数だけを渡す
- 3つの手順の通知の変数は同じ形（`_NOTIFICATION_VARS`。既定 dry-run・本番の送信の旗 false・商品の通知の旗は手動の実行だけ・限定モード true）

## 10. 検査・テスト

- deploy-check #859（関門・上限・残りの READY・同じキー・届いたか不明・定時の実行・関門が閉じたときの戻し・送らないもの・本文・
  ワークフローの変数と Secrets・今の台帳の形と1回の実行の件数）。#856 は正しい形の限定運用の記録を除外
- テスト: tests/test_phase23_product_limited.py（偽の通信だけ）
- mutation: 25/25 をテストで検出（上限を attempt ごとに戻す・商品の実行で canary も送る・古い候補を送る・人の解決の記録で
  LP を止める、を加えた。上限の撤廃 prepare / send・上限を2件・行動できない商品・同じキー・締切切れ・参考の利益・
  公式でない URL・古い在庫・Secrets を Prepare に・dry-run の迂回・定時の実行（関門 / ワークフロー）・限定モードを外す・
  dry-run の実行が本番の記録を進める・関門が閉じても戻さない・Discord にも送る・届いたか不明を送り直す・本文の見出し・
  マイページに未送信・台帳の上限の検査）

## 11. レビュー・監査の指摘（対応済み）

- Medium（レビュー）: 同じ run の Re-run（attempt が変わる）で、1回目に READY で残した2件目が送られる → 上限を run ごとに数える
  （`outbox.run_key`・`product_sends_in_run`。prepare・send・#859 の台帳の検査）
- Medium（監査）: 商品の通知と接続の試験の旗が両方立つと、1回の実行で Telegram に2件 → 商品の関門が開いた・商品を送った実行では
  canary を送らない（`skipped_product_run`。#859 が分岐を検査）
- Medium（監査）: 届いたか不明を人が「届いていた」と解決した記録（配信先の ID なし）で #856・#859 が LP の公開を止める →
  最後の解決が delivered なら正しい形
- Low（両方）: 手動の実行の間が空くと古い「になりました」が送られる → 候補にしてから24時間を過ぎた本番の候補は EXPIRED
  （`stale_candidate`。戻さない。新しい移り変わりは送る）
- Low: Send が動かなかった・送信の後の保存に失敗した実行の SENDING は次の実行で届いたか不明（送り直さない側。人が not-delivered で
  解決）・定時の実行で先に見つかった変化は本番で通知しない → `ops/Secrets設定.md` に記載

## 12. 残している点（Low）

- 配信待ちに戻した本番の記録も、古さは最初に候補にした時刻から数える（24時間を過ぎていれば送らない。送らない側に倒れる。次の
  在庫切れ → 在庫ありで新しいキーになり送る）

## 13. 本番の確認

（本番の確認の後に記入）
