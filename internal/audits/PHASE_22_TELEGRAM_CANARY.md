# Phase 22 — Telegram の送信の部品と接続の試験（canary）

作成: 2026-10-09。配信先は Telegram だけ（Discord は無効）。商品の通知の本番の送信は無効のまま。

## 1. 開始の時点

| 指標 | 値 |
|---|---:|
| 今すぐ行動できる / 候補 / outbox | 0 / 0 / 0 |
| 外部への送信 | 0 |
| リポジトリの Secrets / Variables | 0件 / 0件（Telegram は未設定 = PENDING_USER_CONFIGURATION） |

ユーザーの判断: Secrets はユーザーが設定し、その間に実装を進める。接続の試験の送信は、設定の確認の後にあらためて許可を得る。

## 2. 送信の部品（`src/notifiers/telegram_transport.py`）

- 公式の Bot API（`https://api.telegram.org/bot<トークン>/sendMessage`）だけに、HTTPS の POST を1回（再試行は outbox が次の実行で決める）
- 標準のライブラリ（urllib）だけ。依存を増やさない。TLS は既定の検証
- 要求: chat_id・text・disable_web_page_preview=true。parse_mode は付けない（そのままの文字。書式の文字の問題を避ける）
- トークン・チャット ID・URL をログ・例外・戻り値に出さない（ログを出さない・例外は段階だけの TransportError で `from None`）
- 送る前の失敗と断定できるもの（名前の解決・接続の拒否・証明書の検証）だけを出し直してよい失敗にする。タイムアウト・切断などは
  届いたか不明
- 応答の本文が読めなければ None（200 なら届いたか不明に分類される）

## 3. 応答の分類（`adapters.TelegramAdapter.classify_response`）

| 応答 | 扱い |
|---|---|
| 200 かつ ok=true かつ result.message_id | 送信済み（message_id を provider_delivery_id に保存） |
| 200 かつ ok=true で message_id なし・200 の読めない本文 | 届いたか不明 |
| 200 かつ ok=false | error_code で分類（400 などは出し直さない） |
| 400 / 401 / 403 / 404 | 出し直さない（FAILED_FINAL） |
| 429 | 出し直す（parameters.retry_after か Retry-After） |
| 503 | 出し直す |
| 500 / 502 / 504 | 届いたか不明（自動では出し直さない） |
| タイムアウト・切断 | 届いたか不明 |

## 4. 関門（`adapters.real_send_gate`）

- 商品の通知（purpose="product"）: `PRODUCT_REAL_SEND_ENABLED = False` で常に閉じる（接続の試験の成功だけでは開けない）
- 接続の試験（purpose="canary"）: 配信先が Telegram だけ・`NOTIFICATION_REAL_SEND=true`・`NOTIFICATION_DRY_RUN=false`・
  `TELEGRAM_CANARY=true`・手動の実行（`GITHUB_EVENT_NAME=workflow_dispatch`）・Telegram の設定がそろって形が正しい、がすべてそろったときだけ
- 値は返さない（各条件の可否と「名前:missing / invalid_format」だけ）

## 5. 接続の試験（`outbox.run_canary`）

- 本文は固定（`[TEST] Premium Monitor / Telegram 通知の接続テストです。/ 本番の商品通知ではありません（商品・価格・URL は含みません）。`）。
  商品の状態を偽らない（PS5 Pro を在庫あり・GR IV HDF を抽選受付中にしない）
- 記録: 冪等性のキー `CANARY:telegram:<試験の ID>`（既定 telegram_canary_v1）・is_canary・is_test_message・配信先は telegram だけ
  （Discord の記録を作らない）。チャット ID・トークンは入れない
- 同じ試験の ID の記録があれば送らない（届いた・不明・失敗・取り消しのどれでも。429・503 で出し直せるときだけ同じ記録で、期限の後に）。
  試し直しは新しい ID を明示する（自動で戻さない）
- 送る前: 記録を SENDING にして保存 → `scripts/persist_notification_state.sh` で main に保存 → 保存した台帳の sha が今のファイルと
  同じときだけ送る（違えば記録を元に戻して送らない）。送った後は結果を保存（次の手順の persist が main に残す）
- 送った後・保存の前に止まった → 次の実行の prepare が「届いたか不明」にする（送り直さない）。人の解決は Phase 21 の CLI
  （接続の試験の not-delivered は取り消し。新しい ID で試し直す）
- 接続の試験の記録は商品の通知の件数・配信の直前の確認・prune の対象にしない

## 6. Secrets とワークフロー

- Telegram の Secrets は「Send notifications」の手順だけに渡す。Discord の Secrets は既存の「Notify workflow result」だけ
  （ワークフローの結果の通知は Telegram に送らなくなった）
- 「Send notifications」の変数: NOTIFICATION_DRY_RUN（既定 'true'）・NOTIFICATION_REAL_SEND（既定 'false'）・
  NOTIFICATION_PROVIDERS（既定 ''）・TELEGRAM_CANARY（手動の実行のときだけ変数を読む。ほかは 'false'）・TELEGRAM_CANARY_ID
- deploy-check #857 の Secrets の検査は、手順ごとに渡してよい Secrets と実行してよいコマンドを決める（Telegram は「Send notifications」の
  `python -m src.cli dispatch-notifications --step send` だけ）。#858 が送信の部品・応答の分類・接続の試験・関門を偽の通信で確かめる

## 7. 運営者向け

「今すぐ行動の通知」に Telegram の設定（はい/いいえ）・本番の送信（接続の試験）・配信先の状態（NOT_CONFIGURED / READY / CANARY_PENDING /
CANARY_DELIVERED / ERROR）・接続の試験の状態・最後の配信を出す（前回の送信の手順が書いた provider_status.json。値は無い）。
商品の通知の本番の送信は「無効」と表示する。

## 8. 検査・テスト

- deploy-check #858・テスト tests/test_phase22_telegram.py（偽の通信だけ。ネットワークに出ない）
- mutation: 21/21 をテストで検出（接続の試験の記録で #856 を止める・見せかけの試験を除外・ほかの記録も送る・設定の値を見逃す・試験の ID を検査しない・数字で始まる ID を許す・トークンを出力・例外に URL を連ねる・チャット ID を台帳に・保存の前に送る・接続の試験を重ねる・
  関門で dry-run を見ない・定時の実行で送る・商品の通知を開く・200 ok:false を成功・message_id なしを成功・Discord を選べる・
  LP の生成の手順の Secrets を見逃す・送信の手順に Discord を許す・プレビュー/parse_mode・タイムアウトを出し直す）

## 9. レビュー・監査の指摘（対応済み）

- High（両方）: 接続の試験の記録（live）が台帳に入ると deploy-check #856（本番の送信の記録がある）が毎回エラーになり、LP の公開が
  止まり続ける → 接続の試験の記録（is_canary・TELEGRAM_CANARY・商品なし・telegram だけ・[TEST] で始まり URL・価格なし・
  CANARY: のキー）を数えない。文言の一致ではなく形で見る（文言を変えても過去の記録で止めない）
- Medium（両方）: run_canary の send が同じ attempt の SENDING の商品の記録も送りうる → send(only_ids) で接続の試験の記録だけ
- Low: Secrets を持つ送信の手順のコマンドは完全一致・例外は except の外で投げて元の例外を連ねない・試験の ID は小文字の英字で
  始まる形（チャット ID を入れられない）と設定の値を含まないこと・公開の画面に試験の ID を出さない・persist は送信の手順の中で
  トークン・webhook の値（部分一致）とチャット ID（JSON の文字列の完全一致）を拒む・保存に失敗したときの理由
  （not_persisted_or_unknown）・運営者向けの「本番の送信」は関門と同じ判定・requests は実際に通信した数

## 10. 残している点（Low）

- 公開の LP の運営者向けに、Telegram の設定の有無（はい/いいえ）と接続の試験の状態が出る（値は出さない）
- 接続の試験の後の Telegram の商品の通知は、別の明示の許可で `PRODUCT_REAL_SEND_ENABLED` を変えるまで無効
