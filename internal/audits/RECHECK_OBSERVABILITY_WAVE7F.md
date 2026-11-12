# Wave 7f: 公式の再確認の観測性（A7RV の失敗の調査を受けて。2026-11-13）

## 背景（事実）

- Sony A7RV の公式の再確認が 2026-11-05 以降、8 回連続で `failed`（価格なし・在庫なし・`reason` 空）。11-04 までは 11 回連続で `unchanged`（533,500 円・在庫あり）。
- 取得は HTTP 200 で成功している（取得の失敗は `reason` が付く）。設定・コード・runner の環境に 11-04 と 11-05 の違いは無い。同じホストの A1 II・A7CR・PS5 Pro は成功を続けている。
- 公式のページの外部確認で、**商品行 `ILCE-7RM5 533,500円(税込)` に、販売状態を確定する在庫・出荷の語（在庫あり・当日出荷・翌日出荷・入荷待ち・在庫切れ・販売終了）が無い**ことが原因と確定。型番も価格もページ上にある。parser は「型番 → 在庫・出荷の語 → 価格」の並びを要求するため、価格を採用せず `failed`。**fail-close として正しく、parser の販売状態の判定は変更しない。**
- ページ上部の `現在、選択した商品が購入いただけません。` は A7RV 固有ではなく、正常な A1 II・A7CR のページにもある共通表示。**販売状態の根拠にしない**（この文言によるガード・在庫切れ・販売終了への対応づけは禁止。正常なページで誤検知になる）。
- 確認日は 2026-11-04 のまま（偽の鮮度 0）。**公式直販の期限 14 日: 11-18 まで有効、11-19 の定時 run から期限切れ（確認済み 16 → 15）。取得が回復しなければ正常な挙動**で、16 を維持するための特別扱いはしない。
- 7e-1 の last-state の保持は A7RV で確認済み（11-11・11-12 に `price_reconfirmed_from_last_state`・`on: 2026-11-04`・`last_verified_at: 2026-11-04`）→ **PASS**。

## 変更（観測性だけ）

目的: 次に `failed` になったとき、**parser の段階で**「型番が無い・価格候補が無い・価格候補が複数・在庫語が無い」をすぐ区別できるようにする。**判定（unchanged / changed / sale_ended / failed / blocked）は変えない。診断を判定に使わない。**

- `scripts/recheck_official.py`:
  - Sony の 2 つの parser（`parse_sony_store`・`parse_sony_product`）の戻り値に診断を足す: `model_found`（既存の意味のまま）・`price_candidate_count`（整数。0 = 候補なし・1 = 単一・2 以上 = 複数。型番の直後 30 文字以内に続く価格の種類数）・`stock_phrase_found`（真偽）・`matched_stock_phrase`（固定語彙 = 既知の在庫・出荷の語。該当なし・複数は空文字）。判定の分岐・既存の戻り値のキーの値は不変。`unknown_phrase_present` は入れない（未知の語の境界が曖昧）。
  - `recheck(now)` の呼び出しの形は不変。診断は `LAST_DIAG`（メモリ上）に入る。**結果の行（履歴・latest.json）には入れない**。
  - `main()` は保存前に診断キーを必ず除去（`_public_row`）。ログは、`failed` のうち取得はできて parser が読めなかった行（`reason` が空）だけに、固定形式を 1 行に足す: `diag=model_found:true price_candidates:1 stock_phrase_found:false matched_stock:none`。許可リスト: 真偽・非負の整数・固定の在庫語・`none`。成功・遮断・取得の失敗（理由あり）には付けない。ログの整形で何が起きても再確認は止めない（例外にしない）。
- 公開データの形: `history.json`・`latest.json` のスキーマ変更 0・新しい公開ファイル 0・`RESEARCH_LEDGER_KEY`・7e-2 に依存しない。新しい公開の商品単位の成果物・永続状態は 0。
- 既存の 3 つのテスト（`test_phase15_identity`・`test_market_research`・`test_integrity_remediation`）は、parser の戻り値を辞書の完全一致で比べていたため、**既存の 4 キー（model_found・price・stock・ended）の完全一致**に直した（診断のキーが増えたため。比較は弱めていない）。

## 診断の読み方（ログ）

| ログ | 意味 |
|---|---|
| `model_found:false` | ページに型番が無い（型番の不一致・別のページ） |
| `model_found:true price_candidates:0` | 型番はあるが、直後に価格が続かない（価格の不足） |
| `price_candidates:2`（以上） | 型番の直後に価格が複数ある（どれか決められない。既存の fail-close） |
| `price_candidates:1 stock_phrase_found:false` | 型番と価格はあるが、既知の在庫・出荷の語が無い（**A7RV の現在の形**） |
| `stock_phrase_found:true matched_stock:none` | 在庫語が複数種類ある（どれとも決められない） |

注意: `price_candidates` は「型番の直後 30 文字以内の価格」の数。価格が 30 文字より後ろにあるページでは 0 になる。型番の後ろに別商品の価格が入ると過大になりうる（診断の解釈の注意。判定には無関係）。非 Sony の parser（Apple・Canon・Nikon・Fuji・Nintendo）は診断を持たないので、`failed` でも `diag=` は付かない。

## 検証

- 新しいテスト `tests/test_recheck_parser_diagnostics.py`（32 件）: ①通常の Sony ②A7RV の現在の形（failed・診断・確認日が 11-04 のまま）③型番なし ④価格なし ⑤価格が複数 ⑥販売終了 ⑦**汎用バナー**＋ A1 II・A7CR（バナーの位置 3 通りで正常判定のまま。バナーを根拠にした分岐がソースに無い）⑧**判定の不変**（診断を足す前の実装（HEAD の実装を固定）との比較。1000 件超の組み合わせで、既存 4 キー・classify の結果が一致）／診断が判定に影響できない（診断を改ざんしても結果が変わらない）⑨**公開データの形**（recheck の行・`main()` の history / latest に診断キーが無い・コミット済みの公開ファイルにも無い）⑩**ログの安全**（固定形式・failed の理由が空の行だけ・許可リスト外の値・URL・秘密・未知の語は出ない。例外でも再確認は止まらない）＋語彙の固定・性能（型番の多いページ）。
- 診断の変異テスト 24 件すべて検出（診断を判定に使う・診断を履歴に保存する・除去をやめる・生の値をログに出す・成功の行にも付ける・バナーのガードを入れる・語彙を変える・正規表現の上限を外す・型を厳密に見ない・例外を握りつぶさない など）。既存の変異テスト: 7e-1 は 55 件、7c は 87 件で、どちらも見逃し 0。
- ローカル: pytest 3041 成功・1 skip（Linux 専用）・canary 判定 PASS（外部通信 0）・deploy-check Errors 0・ruff（変更ファイル）0。
- 独立の最終ゲート（reviewer・auditor。読み取り専用。コピーでの実験）: **両名とも Critical 0・High 0・Medium 0**。reviewer は 6 万ページ × 3 型番 × 2 parser、auditor は 36 万ケースの新旧比較で、既存 4 キーの不一致 0・`_sony_diag` の例外 0。`main()` を fake の fetch で新旧に走らせた `history.json`・`latest.json` はバイト一致（診断キーなし）。
- Low（記録のみ）: 診断の正規表現は最大 20〜50 倍遅い（異常なページでも 0.3 秒以下）／`price_candidates` の解釈の注意（上記）／`recheck()` 冒頭の `LAST_DIAG.clear()` は `main()` 側と二重（実害なし）／非 Sony の `failed` には診断が付かない（仕様）。**ゲート後に 1 件補強**: `_diag_suffix` の型検査を厳密にし（`type() is`・整数の上限・語は語彙の側の要素を返す）、整形で例外が起きても再確認を止めないようにした（両名の Low の指摘。許可を狭めるだけで、テストを追加）。

## 本番での確認（次の定時 run）

A7RV がまだ `failed` なら、ログに `diag=model_found:true price_candidates:1 stock_phrase_found:false matched_stock:none` が出ることを期待する。ページの状態が変わっていれば**実際の結果を正とする**（A7RV の状態を期待値に合わせるための操作はしない）。確認日・`verified` を維持する目的の修正はしない。

## 限界

- 診断はログ（公開の CI ログ）と内部の戻り値だけ。履歴に原因は残らない（公開データの形を変えない方針）。過去の失敗は、ログが無いと分類できない。
- 実際の Sony ページのバイト列では検証していない（fixture は架空）。
