# Coverage Wave 7b（運営者向けの作業キュー）

## 目的
調査候補を「ただ残す」状態から、「今日、人が何を確認すべきか」まで絞る。最大 10 件の**非公開**の作業キュー（区分・次の行動・足りない証拠・理由）を作る。

## Before（2026-11-05 の公開 summary）
調査候補 10・高優先 7・価格差が正 6（確定の関門を通過 2・通過していない 4）・買取の急騰 1・確定の利益 2・actionable 0・理由別: OFFICIAL_UNVERIFIED 8・PURCHASE_SHIPPING_UNKNOWN 8・CANONICAL_UNREGISTERED 6・STOCK_UNKNOWN 6 など。作業キューは無かった。

## 実装
- `src/research/operator_queue.py`（新規）: 区分（URGENT / HIGH / MEDIUM / LOW）・点・次の行動・同一性の確かさ・古さ・急騰（momentum_usable だけ）・TCG の締切の加点（時刻つきだけ）・同じ入力なら同じ順位（区分 → 点 → 価格差 → 鮮度 → ID）。
- `src/research/candidates.py`: `build()` がキューを作る（非公開の `operator_queue`）。公開の集計は `operator_queue_counts`・`operator_queue_next_actions`（件数だけ。許可リスト）。`PRIVATE_KEYS` に個別の項目を追加。`write_outputs` が `.private/research/operator_queue.json` を書く。
- `src/tcg/profit_dense.py`: 非公開の行に、商品名・商品 ID・応募終了とその精度（datetime / date）・締切までの時間を追加。
- `src/content/ui/admin.py`: 「今日確認すべき候補 N件」（件数だけ）。
- テスト `tests/test_coverage_wave7b.py`（26 件）・変異テスト `scripts/mutation_wave7b.py`（43 件）・deploy-check #879。既存テスト `test_market_research.py` は、非公開ディレクトリのファイルに `operator_queue.json` を加えた（削除・スキップはしていない）。

## 守ったこと
確定・actionable・通知・顧客向けの画面に影響させない（確定・通知の部品を import しない。順位は確定ではない）／AI の価格予測は使わない／個別のキューは非公開（公開は件数だけ）／古い候補は URGENT のまま残さない／隔離された価格は確定にしない／TCG は応募の URL が確認できなければ actionable にしない／日付だけの締切に大きく加点しない。

## 最終ゲート（1 回目）での修正（reviewer / auditor の指摘）
- 観測時刻が空・読めない・時計より 1 時間を超えて先のときは、新しいと確認できないので古い扱い（LOW・「新しい価格を待つ」）。並びでも未来の時刻が有利にならない。
- 価格差の下限 500 円（1 円差を URGENT にしない）。価格差が正で足りない証拠が 4 個以下なら HIGH（OFFICIAL_NOT_SOLD・ACQUISITION_CONDITIONAL などにも次の行動を対応）。
- TCG: URGENT は商品の同一性が確かなものだけ。キューの TCG は最大 4 件（空きがあるときだけ超えて埋める）。同じ小売・商品のイベントは全店舗の属性を集約（応募の URL・同一性・定価との結び付き・条件）。商品名も ID も無いイベントは 1 件にまとめない。
- 急騰の加点は同一性が確かなときだけ。壊れた入力（文字列・None・NaN・小数）で例外にしない。`candidates.build` は作業キューの組み立てが失敗しても調査レポートを止めず、空のキュー（`operator_queue.empty`）にして警告を残す。
- 変異テスト 55 件（見逃し 0）。
- 残る（Low）: TCG の `signal_points` に締切の点が含まれるため、締切の加点と一部重なる。日付だけの当日締切は HIGH 止まり。

## 最終ゲート（2 回目）での修正
- 隔離された売値（上限超え・急変・裏付け不足）の価格差の加点に上限（20 点）。きれいな候補より上位に来ない。
- 組み立ての失敗は 0 件と区別できるよう、公開の件数に `queue_build_failed`（0 / 1）を追加し、管理画面にも「組み立てに失敗しました」と表示。警告ログは例外の型名だけ（メッセージには入力の値が載りうる）。
- 信号・急騰だけで LOW から MEDIUM に上がるのは、同一性が確かで隔離されていないものだけ。締切を過ぎた TCG（状態は受付中のまま）は LOW + 締切の確認。`hours_to_deadline` の型の混在・真偽値で例外にしない・1 時間として読まない。`missing_requirements` の型の揺れ（文字列・None・辞書）を吸収。価格差が正で足りない証拠が見えない候補には既定の次の行動（公式の価格・状態の確認）。
- 変異テスト 64 件（見逃し 0）。
- 残る（Low・記録のみ）: TCG の URGENT は応募の URL の有無を見ない（応募の URL が無い場合の次の行動は VERIFY_APPLICATION_URL。締切が近いうちに探す価値があるため）。店舗をまたいだ同一性は「どれかの店舗で確認できていれば確認済み」。単独の NEEDS_CORROBORATION は URGENT になりうる（仕様の例どおり）。

## 最終ゲート（3 回目）での修正
- TCG の入力の鮮度: `candidates.build` の `tcg_input_fresh`（収集が失敗して前回のデータが残った日）と `tcg_healthy_sources`（健全でない取得元）を作業キューにも渡し、古い TCG は LOW + 「新しい情報を待つ」。
- URGENT の TCG は、締切の加点を近さで段階づけ（24 時間以内は 20〜32）、並びの鍵にも締切を使い、締切が近い順に並ぶ。TCG の URGENT / HIGH は最低 2 件を確保（商品の HIGH に全部押し出されない）。上限 4 件は確かな商品を守るためで、LOW（待つだけ）の商品の行には負けない。
- 代表行は、締切がまだ来ていない最も近いイベント（期限切れの行が開いている店舗を隠さない）。URGENT は代表行の同一性が確かなときだけ（表示・次の行動は全店舗で見る）。
- 次の行動の無い MEDIUM には、まず仕入れ値の確認（VERIFY_RETAIL_PRICE）。隔離された行に急騰の加点をしない。TCG の `requirements` の型の揺れで例外にしない。時間の境界（72 時間・24 時間）のテストと変異を追加。
- 変異テスト 79 件（見逃し 0）。
- 残る（Low・記録のみ）: 管理画面は、Wave 7b より前の summary.json（`operator_queue_counts` が無い）では「0 件」と表示される（毎回再生成されるので通常は問題なし）。単独の NEEDS_CORROBORATION は URGENT になりうる（仕様の例どおり）。

## ゲート通過時点の残り（Low・記録のみ。reviewer / auditor とも Critical・High・Medium は 0）
- 単独の `NEEDS_CORROBORATION`（`ABOVE_GENRE_MAX` / `PRICE_SPIKE` を伴わない）は URGENT になりうる（仕様の例どおり。実データでは必ず他の隔離の理由を伴うので顕在化しない）。
- `max_queue` が 1〜2 のとき TCG の最低枠（2）が商品の URGENT より先に入る。`max_queue` の上限のクランプが無い（呼び出しは既定の 10 のみ）。
- TCG の個別イベントの観測時刻は見ない（`profit_dense` の行が持たない）。鮮度は収集全体と取得元の健全性だけ。締切不明の受付中で同一性が確かな TCG は HIGH になりうる。
- LOW で次の行動が無い行がある（枠が余ったときだけキューに入る）。TCG の集約表示で `id` が代表行のものになる場合がある。
- 時計が timezone なしのとき、極端な日時の値で組み立てが失敗する（本番の時計は JST 付き。失敗しても `queue_build_failed` に出る）。
- 管理画面は、Wave 7b より前の summary.json では「0 件」と表示される。
