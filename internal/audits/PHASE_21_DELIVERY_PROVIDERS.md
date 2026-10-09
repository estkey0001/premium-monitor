# Phase 21 — 配信先の部品と、届いたか不明の人による解決

作成: 2026-10-09。外部への送信（Discord・Telegram・webhook）はしない。dry-run を外さない。

## 1. 基準（Phase 20 の生成物 b132db40）

| 指標 | 値 |
|---|---:|
| 今すぐ行動できる / 候補 | 0 / 0 |
| outbox の配信待ち / dry-run の計画 / 送信済み | 0 / 0 / 0 |
| 届いたか不明 / 出し直す失敗 / 期限切れ | 0 / 0 / 0 |
| 外部への送信 | 0 |
| リポジトリの Secrets | 0件（通知の Secrets は未設定） |
| CI の所要時間 | 68.6分 |

## 2. 配信先の部品（`src/notifiers/adapters.py`）

outbox の後ろに差し込む（新しい通知の基盤は作らない）。配信先ごとに validate_config・build_payload・validate_payload・
classify_response・extract_delivery_id を持つ。HTTP の部品を import しない。送信は transport（呼び出し側が渡す関数）だけで、
transport は Phase 21 ではどこにも無い（`REAL_SEND_IMPLEMENTED = False`）。

- 本文（Discord・Telegram で同じ意味）: 状態の見出し・商品・想定純利益・ROI・状態・締切（抽選など）・確認の時刻・購入/申込の URL。
  値は outbox の記録の確定の値（利益・ROI を計算し直さない）。URL は記録の action_url（判定の正本の公式のページ）だけ
- 安全な短縮: 長さの上限（Discord 2000・Telegram 4096）を超えたら、確認の時刻の行 → 商品名の末尾（「…」）の順に削る。
  状態・利益・ROI・締切・URL は削らない。それでも収まらなければ空（送らない = FAILED_FINAL）。日本語・¥・%・絵文字はそのまま
- Discord: allowed_mentions は空（一斉の呼び出しなし）。配信先の ID は webhook を wait=true で呼んだときの message の id（無ければ空）
- Telegram: parse_mode なし（そのままの文字）。chat_id は transport が付ける（台帳・本文に入れない）。失敗を HTTP 200 +
  `{"ok": false}` で返すことがあるので本文の error_code も見る。429 は parameters.retry_after。成功の形でない 2xx は届いたか不明。
  配信先の ID は result.message_id
- 応答の分類（Phase 20 と同じ方針）: 2xx 届いた・429/503 出し直す（Retry-After）・400/401/403/404/413/422 出し直さない・
  500/502/504 など 届いたか不明・接続の前の失敗 出し直す・送った後の切断や分からない失敗 届いたか不明
- 設定の検査（validate_config）: Discord は webhook の URL の形、Telegram はトークンとチャット ID の形。問題は「名前:missing /
  invalid_format」だけで、値は返さない。`redact` は URL・トークン・Bearer の形を消す（ログの本文にも使う）
- 本文に秘密の値の形があれば送らない（validate_payload の secret_in_payload）

## 3. 本番の送信の最終の関門（`adapters.real_send_gate`）

送信の部品がある・`NOTIFICATION_REAL_SEND=true`（既定 false）・`NOTIFICATION_DRY_RUN=false`（既定 true）・配信先の選択
（`NOTIFICATION_PROVIDERS`）・選んだ配信先の設定が正しい、がすべてそろったときだけ開く。Phase 21 では送信の部品が無いので、
どの設定でも閉じている。`dispatch-notifications` は関門が閉じていれば dry-run と同じに扱い、send は送らない
（`real_send_allowed`）。`python -m src.cli notification gate` で各条件の可否だけを表示する。

## 4. Secrets の経路

- 通知の Secrets を渡すのは送信の手順だけ。収集と LP の生成を含む「Run buyback premium check」、イベントを作るだけの
  「Generate notifications」から外した（今は Secrets が未設定なので動きは変わらない）
- 既存の「Notify workflow result」（ワークフローの結果の通知。outbox とは別の既存の送信の手順）は残す
- 今すぐ行動の通知の「Send notifications」には Phase 21 では渡さない（本番の送信を有効にする Phase で、この手順にだけ渡す）
- deploy-check #857 が、Secrets を渡す手順が「Notify workflow result」だけであることと、本番の送信の旗が true でないことを検査する

## 5. 届いたか不明（UNKNOWN_DELIVERY）の人による解決

GitHub Pages は静的なので、書き換えの画面は作らない（装わない）。運営者向けの画面は一覧（通知の ID・商品・配信先・送信した時刻・
状態・締切・理由）だけを出し、解決は手元のコマンドで行う:

```
python -m src.cli notification list-unknown
python -m src.cli notification resolve <ID> delivered|not-delivered|cancel|keep-unknown [--channel ch] --confirm
```

- `--confirm` が無ければ結果の見込みだけを表示して書き換えない（既存の update-retail-price と同じ確認の形）
- main の台帳と手元の台帳が同じときだけ書き換える（`outbox.main_ledger_matches`。違えば git pull で合わせる）。書き換えは
  Phase 20 と同じ台帳に atomic に・排他して。台帳だけをコミットして main に push する
- delivered → DELIVERED（送り直さない）・cancel → CANCELLED・keep-unknown → そのまま（記録だけ）
- not-delivered → 最新の診断で確かめ直す: 今も同じキーで行動できて期限の内なら FAILED_RETRYABLE（次の実行の配信の直前の確認に
  回る。同じ冪等性のキー・同じ記録）、期限切れなら EXPIRED、行動できない・利益が確定でないなら CANCELLED、試行の上限を
  過ぎていれば FAILED_FINAL
- 記録: 配信先ごとの resolutions に resolved_at・resolution・resolver_type（operator_cli）・previous_status・result_status。
  個人名・メールは残さない。新しい記録・キーは作らない
- 届いたか不明は、人の判断まで自動では送り直さない（DUE に入らない）

## 6. 送る直前の確かめ直し

prepare（SENDING を保存する前）に加えて、send の中でも本文を作る直前に Phase 19 の4条件（期限・締切・公式のページ・確定の利益）を
確かめる。SENDING を保存してから送るまでに期限が過ぎたら送らない（EXPIRED / CANCELLED）。

## 7. 複数の配信先

outbox の記録は配信先ごとに状態を持つ（Phase 20 から）。Discord が届いて Telegram が失敗したら、Discord は DELIVERED のまま
（送り直さない）、Telegram だけが出し直しの対象になる。記録全体の状態は配信先の状態から決める。

## 8. 古い基準のファイル（Phase 20 の Low）

- 基準のファイルの既定の場所を `/tmp` から、CI は RUNNER_TEMP（ジョブごとに新しい）、手元は `.git` の中に変えた
- sync は「実行の識別（CI は run の ID と試行の回数・手元は作業ツリーの場所）・合わせた main のコミット・その台帳の blob・合わせた時刻」を書く
- persist はすべてを確かめる: 形・実行の識別が今の実行と同じ・基準の main のコミットがある・そのコミットの台帳が基準の blob と同じ・
  手元では6時間以内。どれかが違えば保存しない（送信の手順も動かない）。Phase 20 の形（blob だけ）の基準も受け付けない

## 9. Pages の再構築

GitHub Pages は「ブランチから公開」（legacy・main の /docs）で、main への push のたびに再構築が走る（変更のある場所に依らない）。
台帳の保存のコミットは台帳の内容が変わったときだけ（今の本番では Phase 20 の形からの移し替えの1回だけ）。台帳を Pages の
対象外の別のブランチに移す・Pages を workflow で公開にする、のどちらも保存の仕組みと CI の互換を変えるので、今回はしない
（保存を弱めない）。台帳は exports/ にあり /docs ではないので、公開のページには入らない。

## 10. 検査・テスト

- deploy-check #857（本番の送信が無効・Secrets を渡す手順・応答の分類・配信先の ID・秘密の値を消す・届いたか不明の解決・古い基準）
- テスト: tests/test_phase21_delivery_providers.py（一時の bare リポジトリで古い基準を拒むことを含む）
- mutation: 19/19 をテストで検出（cancel した配信を復活させる・Secrets の構造の検査を外す・応答を読めない例外を漏らす・秘密の値を消さない・関門が値を返す・届いたか不明を自動で出し直す・送信済みを出し直す・
  期限切れを戻す・古い基準を受け入れる（実行の識別・時刻・改ざん）・関門を開く・関門が閉じても送る・502 を出し直す・
  Telegram の ok:false を成功・送った後の切断を出し直す・URL を切る・送る直前に確かめない・解決が新しい記録を作る）

## 11. レビュー・監査の指摘（対応済み）

- High（両方）: cancel で解決した届いたか不明が、同じキーで行動できるままだと次の実行で配信待ちに戻って送られる → 人が cancel した
  配信先は自動で戻さない（resolutions の最後が cancel）
- Medium（レビュー）: Telegram の形の崩れた応答で ValueError が漏れて send 全体が止まる → 数値の読み取りを守り、分類・ID の読み取りの
  失敗は届いたか不明（classify_failed）にしてほかの配信先は続ける
- Medium（監査）: #857 の Secrets の検査がジョブ・全体の env・toJSON(secrets)・添字・コメントを挟んだ参照を見逃す → YAML の構造で
  全ワークフローを確かめ、全文の参照の数と許した手順の env の参照の数を照合する
- Low: LP の生成の方式を配信の手順と同じ決め方に（dry-run か関門が閉じていれば dry-run）・関門の dry_run_off を is_dry_run と同じ判定に・
  基準の時刻の数字でない値・未来の時刻を拒む・CLI の照合を省く隠しのオプションを外し、台帳だけをコミットする案内に・Discord の
  Markdown の文字を商品名でだけ無効にする・トークンの桁（5〜12桁）と scheme の無い webhook の URL も消す・既存の結果の通知の
  例外の文字列も redact を通す・Secrets の名前の大文字小文字と secrets: inherit も検出・Discord の商品名はエスケープの前で短縮

## 12. 残している点（Low）

- 送信の部品（HTTP の transport）は作っていない（本番の送信を有効にする Phase で、ユーザーの許可の後に作る）
- 既存の「Notify workflow result」には Secrets を渡したまま（outbox とは別の既存の結果の通知。今は Secrets が未設定）
- 解決の後の push は人が行う（CLI は台帳を書き換えるだけ）
- Pages の再構築は台帳の保存のコミットのたびに走る（内容が変わったときだけ）
