# Coverage Wave 6 — 台帳をまたぐ信号と TCG 収集の高速化

2026-10-29。Wave 5 の判定は PARTIAL。今回は「実行をまたぐ台帳を使える状態にする」「TCG の収集（約 51 分）を短くする」を優先した。
**Phase31 には進まない・iPhone 18 系は一括登録しない・Secrets の設定は私が行わない。**

## 1. 台帳の最終監査（Stage A / B / C）

`RESEARCH_LEDGER_KEY` を設定する前に、実装を確認した（コードの変更は不要だった。テストを足した）。

| 観点 | 確認した内容 |
|---|---|
| 暗号化 | `openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt`。鍵は Secrets を環境変数で渡すだけ（スクリプトに書かない・出力しない）。テストで鍵が stdout / stderr / GITHUB_OUTPUT / GITHUB_ENV に出ないことを確認 |
| 復号 | 復号 → 展開の前に、中身の名前が許可した 3 ファイル（state / latest / buyback_catalog）だけか・リンクやデバイスを含まないかを検査。失敗は `{"corrupt": true}` を置いて作り直す（`CORRUPT`） |
| 書き込み | 暗号化は一時ファイルに書き、成功したら置き換える（途中の書きかけを保存しない）。`state.json` も `.tmp` → `replace` |
| 壊れた台帳 | 形が違う・null・空・別の鍵 → `CORRUPT`。鮮度（first_seen・前回の価格）は引き継がない（偽らない） |
| キャッシュの隔離 | 定時の実行（schedule / workflow_dispatch）だけがキャッシュを読み書きする。PR の workflow ではない。キャッシュに置くのは暗号化したファイルだけ（テストで固定） |
| 最小の鍵の長さ | 32 文字未満は引き継がない（`enabled=false`・警告に鍵を出さない） |
| 公開 / 非公開 | `.private` は `.gitignore`。`git add` の対象に台帳を含めない（テスト）。公開の artifact に `.private` を入れない（テスト） |
| 5 つの状態 | `NOT_AVAILABLE`（鍵なし）/ `NEW_THIS_RUN`（鍵あり・前回なし）/ `REUSED_WITHIN_RUN`（同じ run の再生成）/ `RESTORED_FROM_PREVIOUS_RUN` / `CORRUPT`。コード・summary の語彙・テストで一致 |

**設定はユーザーが行う**（私は値を作らない・表示しない）:

```bash
gh secret set RESEARCH_LEDGER_KEY
```

プロンプトに 32 文字以上のランダムな値を貼り付ける（例: `openssl rand -base64 36` の出力）。値はチャット・ファイルに残さない。

## 2. 買取の勢い（Stage E）

`src/research/signals.py` の `momentum()`。前回の台帳を引き継げた日だけ数値を出す。

- 各候補に `previous_price` / `current_price` / `delta_yen` / `delta_percent` / `previous_observed_at` / `current_observed_at` と状態（`RISING` / `FALLING` / `FLAT` / `NEW_OBSERVATION` / `NOT_COMPARABLE` / `STALE_BASELINE` / `SAME_OBSERVATION`）を持たせる（非公開）。
- **点に使えるのは `RISING` かつ隔離されていない行だけ**（`momentum_usable`）。選別が HIGH / MEDIUM・買取の観測が新しい・同一性が確か（`IDENTITY_PARTIAL` は隔離扱い）・取得元が有効、が前提。
- 隔離（`above_genre_max` / `needs_corroboration` / 誤価格の疑い / 条件つきの仕入れ値）: 数値は参考として残すが `momentum_usable=False`。確定にも使わない。
- 前回が無ければ `NEW_OBSERVATION`（上がったと言わない）。前回が 7 日超なら `STALE_BASELINE`、前回と同じ観測日時なら `SAME_OBSERVATION`（同じデータを新しい値として数えない）。
- **次回の基準は正常な価格だけ**（`_buyback_baseline`）。隔離された価格は基準にせず、その候補の前回の正常な基準を（日時も前回のまま）引き継ぐ。
- 勢いは**並べ替えの点にだけ**使う（`tier` を上げない）。HIGH にしない。

## 3. 検知の遅れの測定（Stage F）

`src/tcg/detection_delay.py`。TCG イベントの `first_seen` を台帳（state.json の `tcg_first_seen`）に持つ。

- 前回の台帳を使えない日（鍵なし・初回・壊れた）は引き継がず、測定しない（`comparable=0`）。同じ run の再生成（`REUSED_WITHIN_RUN`）は、前回の run までの記録を含むので引き継ぐ（捨てると across-runs の記録が消える。テスト・変異で固定）。
- 台帳を使い始めた最初の run に既にあったイベントは **baseline**（いつから公開されていたか分からない）。測定するのは台帳を使い始めた**後**に初めて現れたイベントだけ。
- 遅れ = first_seen − 情報元の公開日時（`published_at`）。公開日時が無い・未来の値（矛盾）は **UNKNOWN**（推測しない）。応募の開始前に見つけたか・応募期間の残りの割合も出す。
- 公開は件数と中央値・最大だけ（`tcg_detection_delay`）。個別は非公開（`tcg_detection_events`）。
- first_seen の精度は「その run の時刻」＝定時の実行の間隔（現状 1 日 1 回）。

## 4. TCG の収集の高速化（Stage G〜J / Z）

**所要の内訳（Wave 5 の本番ログ）**: 取得が 2 つのフェーズを直列に回していた（①公式・小売の一覧 7 コレクター ②抽選の取得元 22 件）。①で約 6 分、②で約 45 分。
②は各取得元を直列に取り、詳細ページの取得数に全体の上限（40）があった。時間を決めるのは「最も取得数の多いドメイン」（カードラボ 24 件 × 60 秒）なのに、別ドメインを待っていた。

| 変更 | 内容 |
|---|---|
| 一覧（list）と詳細（detail）の 2 段 | 抽選の取得元は元々「一覧 1 回 → 候補の詳細」（終了済みは読まない・応募中らしいものを先に・取得枠）。この構造は維持し、`detail_candidates` / `detail_fetched` / `skipped_due_to_limit` / `skipped_ended` を指標に出す |
| 並列化 | `src/collectors/tcg/runcache.py`。異なるドメインは並列・**同じドメインは同時に 1 つ**（ドメインごとのロック）・60 秒以上の間隔は RateLimiter（変更なし）。**同時に通信する数**は `GLOBAL_CAP = 12`（通信の間だけ枠を使い、間隔の待ちの間は使わない。上限なしにしない）。①と②も同時に始める。取得元のスレッドは多くが間隔の待ちで眠っている |
| 同一 run の URL キャッシュ | 正規化した URL（クエリは残す）をキーに、**この run の間だけ・メモリだけ**。成功も失敗（403・robots・通信失敗）も覚え、ブロックされた URL を取り直さない（回避しない）。同時に同じ URL を要求されたら 1 つだけ取得して結果を共有。ファイルに書かない（deploy-check #877 が保存の語を禁止）。有効にするのは `activate()` の中だけ |
| 詳細の取得枠 | 以前の「実行全体で 40 件」をやめ、**取得元ごとの上限（`max_detail_fetch`）だけ**にした（上限の合計は約 60 件。取得は最大で約 50% 増える。減らしてはいない）。時間は最大ドメイン（カードラボ 24 件）で決まる。`budget.py` は互換のため残し、docstring に廃止を明記 |
| 取得元の健全性 | `src/tcg/collection_metrics.py`: HEALTHY / ZERO_EVENTS / PARSER_DEGRADED / BLOCKED / UNREACHABLE（タイムアウトを含む）/ FAILED と、`truncated_sources`。**run が成功しても取得元が健全とは限らない**。不明な状態は healthy にしない。`exports/tcg/latest.json` の `collection_metrics`（秒数・件数だけ） |

- ワークフローに `timeout-minutes: 240`（通常は約 2 時間 10 分。ハングで既定の 6 時間を使い切らないため。短すぎる値にしない）。
- 目標（TCG 51 分 → 30 分以下）は、最大ドメイン（カードラボ 24 件 + 一覧）の下限が約 26 分のため、並列化で理論上は届くが、**CI の実測で確認する**（§8）。取得件数を減らして達成しない。

## 5. TCG の取得元・応募 URL・定価との結び付き（Stage K / L / M / N）

- **新しい取得元（+1）は追加できなかった**: TSUTAYA は保守明け（2026-10-30）以降に再調査（今日は 10/29）。セブンネット・エディオンは Wave 5 で公開の告知一覧が確認できなかった。HMV は規約の判断が取れていないので実装しない。ブロックされる取得元（トイザらス・Joshin・ゲオ・キッズリパブリック・ポケモンセンター）は BLOCKED のまま（回避しない）。手元で取れて CI で 403 のものは WORKING に数えない（既存の規則）。
- **応募の URL と告知の URL を区別**: `entry_url`（公式で確認できた応募の URL）だけが応募の URL。告知の URL（情報元）・購入の URL（当選後）は応募の URL ではない。応募の URL が確認できないイベントは `announcement_url_only` で **actionable にしない**（`tcg_application_url_confirmed` / `tcg_announcement_url_only`）。
- 定価との結び付きは `product_id` の完全一致かつ `product_match == "exact"` だけ（Wave 5 のまま。名前だけの一致はしない）。

## 6. 限定の扱い（Stage W / Wave 5 の Low）

`Special` / `特別` / `スペシャル` / `記念` / `周年` / `アニバーサリー` / `CELEBRATION` / `コラボ` は、普通の商品名にも付くため**語の一致だけでは限定にしない**。
公式の構造化された項目（`structured_limited`）があるときだけ採用する。明確な語（`限定` / `数量限定` / `期間限定` / `Limited` / `エクスクルーシブ`）は、公式の名前・https の公式 URL があれば従来どおり。
（現状、公式の構造化された限定の項目を持つ取得元は無い（`msrp.json` にも項目が無い）ので、**曖昧な語は本番では限定にならない**。見逃しは増えうるが、誤って優先する方を避けた。曖昧な語が公式の名前にあるときは `limited_hint` に残す（点にも件数にもしない。人が確かめる手がかり）。`Unlimited`・`限定なし`・`非限定` は明確な語にも一致させない。Wave 5 のテストの定価の台帳の商品名は、曖昧な語（CELEBRATION）から明確な語（数量限定）に変えた = 意図した挙動の変更。曖昧な語が限定にならないことは別のテストで固定している。）

## 7. 公式の確認済み・正の価格差・API（Stage O〜V）

- **official verified は 16 のまま**。追加には、canonical の商品登録・`official_registry` の購入ページ（VERIFIED_URLS / OFFICIAL_DIRECT_OFFERS）・送料・JAN 等の同一性・毎日の再確認が要り、証拠の収集が必要。証拠が足りないものは追加しない（仕様どおり）。Canon の R6 Mark III・R7 は購入ページが読めるが、色・キットの JAN の確認を伴う登録は今回行っていない。Sony α7C R は 2 色の JAN が確認できず `IDENTITY_PARTIAL` のまま。
- 再確認の取得の共有（Stage P）: Canon は 1 商品 1 ページで、共有できるカタログのページが無い。今回は実装しない。
- 仕入れ元 API（Yahoo!ショッピング・楽天）: 鍵なしでは request しない（`PENDING_USER_CONFIGURATION`）。鍵の値はログ・成果物・URL に出さない。テストで固定（`requests.get` / `post` が呼ばれないこと）。鍵はユーザーが設定する。
- 正の価格差・高優先は、市場の状況に依存し、今回の変更（勢い・遅れ）では増えない（勢いは `RESEARCH_LEDGER_KEY` の設定後の 2 回目の run から効く）。

## 8. reviewer / auditor の指摘と対応（コミット前）

初回の reviewer: Critical 0 / High 1 / Medium 5。auditor: Critical 0 / High 0 / Medium 4。すべて対応した（下表）。

| 指摘 | 対応 |
|---|---|
| H1 限定の曖昧な語が本番で一切拾われない | 上記 §6 のとおり意図した変更として明記。構造化された項目は存在しないので配線できない。`limited_hint` を追加・語境界・否定の除外・テスト固定。HANDOFF に未配線を明記 |
| M1 同じ run の再生成で勢いの基準が消える | `momentum_baseline`: 同じ run の再生成は、最初の生成が引き継いだ前回の基準（`buyback_prices_prev`）と比べ、基準は上書きしない（テスト・変異） |
| M2 勢いの対象外の行の誤価格が基準に入る | 隔離の判定を行の項目から直接行う（`signals.is_quarantined`）。対象外の行も基準にしない（テスト・変異） |
| M3 勢いの誤検知 | 3% に加え **500 円以上**の差が要る。前回からの経過日数も残す |
| M4（reviewer）検知の遅れの水増し | ID は情報元 URL で決める・日付だけの公開日は UNKNOWN・初めて見てから 36 時間以内の run だけ測る（毎日同じイベントを数えない） |
| M5 グローバル枠の占有 | スレッドは取得元の数だけ（眠って待つ）、枠は通信の間だけ確保（間隔の待ちの間は使わない） |
| auditor M1 キャッシュの鍵に取得方法が無い | 鍵に JS 描画かどうかを追加（テスト・変異） |
| auditor M2 キャッシュ経由の観測時刻 | entry に実際の取得時刻（`fetched_at`）を持たせ、受け取った側のイベントの `observed_at` も実際の取得時刻（テスト・変異）。first_seen も収集した時刻（`observed_at`）を使う |
| auditor M3 検知の遅れに取得元の停止が混ざる | 前回の台帳でその取得元（小売）が 36 時間以内に見えていなければ、復旧日の「新規」は測らない（`source_gap_excluded`・テスト・変異） |
| auditor M4 `collection.json` の差分 | 手元の実行で変わるだけなので、そのつど `git checkout` で戻し、コミットに含めない |
| Low | 中断で待機側が解放されない → `finally`（テスト・変異）。測れた件数が 3 件未満のとき遅れの値を公開しない（`delay_values_withheld`）。一部だけブロックされた取得元を `partial_blocked_sources` に出す。例外のメッセージを失敗の理由に残す。`mutation_wave6.py` に追跡ファイルを書き換える注意を追記 |

再レビュー（修正後）の指摘（Medium 3 件）も対応した: 検知の遅れは **初めて見えた run（`measured_run`）でだけ**測る（翌日の run で二重に数えない）・取得元の停止の判定は同じ run の再生成でも不変（`sources_base`）・取得元の「見えていた」は正常に取得できた取得元（ブロック・到達不能を除く）でも更新・最初の生成が台帳を引き継げていなければ再生成も測らない（`trusted`）。Low: 引き継げなかった基準は `None`（空と区別）。この修正後の差分は reviewer の再確認を省き、テスト・変異（35 件）で確認した（メインの自己確認）。

## 9. 本番での確認

手動 run 1 回（run 40888944289、success、開始 2026-10-29 14:11Z・所要 **1h43m50s**。Wave 5 は 2h10m）。

| 項目 | Wave 5 | Wave 6（実測） |
|---|---|---|
| TCG 収集（Collect TCG events） | 51.1 分 | **25.1 分**（目標 30 分以下を達成） |
| 全体の所要 | 約 2h10m | **1h43m50s**（目標 1h45m 以下を達成） |
| 小売の照会 | 10.0 分 | 10.0 分 |
| カメラ買取 / 買取価格 | 28.7 / 12.2 分 | 28.7 / 12.2 分（変更なし。次のボトルネック） |

- `collection_metrics`: 並列（同時に通信する上限 12・ドメインごと 1）。HTTP 72 件（キャッシュで省いた 6 件）・ドメイン 21・最大ドメインの取得 26 件（= 最も遅い取得元 1502 秒）。**取得を減らしていない**: 詳細の候補 41 件を 41 件とも読んだ（打ち切り 0・終了済みの読み飛ばし 0）。
  取得元の健全性: HEALTHY 6 / ZERO_EVENTS 13 / PARSER_DEGRADED 0 / BLOCKED 5 / UNREACHABLE 4 / FAILED 0（計 28）。一部だけブロックされた取得元 1。
- 台帳: `RESEARCH_LEDGER_KEY` は未設定 → `ledger_persistence=NOT_AVAILABLE`・`ledger_state=REUSED_WITHIN_RUN`（同じ run の再生成）・`first_seen_scope=THIS_RUN_ONLY`。**勢いは全 337 行が `NOT_COMPARABLE`（上がった・下がったと言わない）**・first_seen・検知の遅れは `comparable=0` で測定 0（UNKNOWN）。これは設計どおりで、鍵の設定後の 2 回目の run から実測される。
- TCG: 取得元の状態 WORKING 8（Wave 5 と同じ。新しい取得元は追加できていない）・BLOCKED 5・UNREACHABLE 4。受付中のイベント 4（Wave 5 は 6。市場の変動）・応募の URL が確認できたもの 0・告知の URL だけ 4（いずれも actionable でない）・定価に結べたもの 0。検知の間隔のシミュレーションは Wave 5 とほぼ同じ（24 時間ごとだと半分を失う 3.3 件）。
- 調査候補 10・高優先 7・正の価格差 6（Wave 5 は 5）・official verified 16/47・confirmed 2（既存の確定）・actionable 0。小売の照会の exact は Wave 5 と同じ構成。
- 安全: false confirmed 0。`NOTIFICATION_REAL_SEND=false`・`PRODUCT_REAL_SEND_ENABLED=false`・`PHASE24_ACCEPTANCE_CANDIDATE_ID` は未設定（外部送信 0・Phase24 は変更なし）。公開の集計に勢い・first_seen・価格・JAN などの個別の項目なし。`.private` の追跡 0。deploy-check Errors 0（#877 を含む）・prelaunch Errors 0。

### 目標の評価

| 目標 | 結果 |
|---|---|
| TCG 収集 51 分 → 30 分以下 | **達成**（25.1 分） |
| 全体 2h10m → 1h45m 以下 | **達成**（1h43m50s。余裕は約 1 分と小さい） |
| official verified 16 → 20+ | 未達（16） |
| 正の価格差 5 → 10+ | 未達（6） |
| 高優先 7 → 10+ | 未達（7） |
| TCG working +1 | 未達（+0） |
| false confirmed 0・fake freshness 0・外部送信 0 | 達成 |
| 台帳の実測（勢い・first_seen・遅れ） | 未実測（鍵の設定待ち。実装・監査・テストは完了） |

判定: **COVERAGE_WAVE6_PARTIAL**（実行時間の 2 目標と安全は達成。カバレッジの目標は未達。台帳の実測はユーザーの鍵の設定が前提）。
