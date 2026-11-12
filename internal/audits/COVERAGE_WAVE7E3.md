# Coverage Wave 7e-3: CI Canary（2026-11-12）

本番の定時（`daily_lp.yml`）とは別に、「CI で pytest を、外へ出ない・Secrets を使わない・commit も push もしない状態で通せるか」を確かめる canary。

## 構成

| ファイル | 役割 |
|---|---|
| `.github/workflows/ci_canary.yml` | `workflow_dispatch` だけ・`contents: read`・Secrets なし・Python 3.11・`TZ=Asia/Tokyo`・matrix なし・timeout 45 分。checkout は `persist-credentials: false`。Playwright のブラウザは入れない |
| `scripts/ci_canary/netguard.py` | Python の外部通信の遮断・記録（`sys.addaudithook`）。site-packages の `.pth` から全プロセスに入れる |
| `scripts/ci_canary/node_netguard.js` | Node の遮断・記録（`NODE_OPTIONS=--require`。pytest の step の env だけ） |
| `scripts/ci_canary/chrome_wrapper.sh` | Chrome の hermetic wrapper（`CHROME_BIN`。名前解決・プロキシ・バックグラウンド通信を塞ぐ） |
| `scripts/ci_canary/verify.py` | 合否の判定（終了コード 0 / 1。`$GITHUB_STEP_SUMMARY` にも出す） |
| `tests/test_wave7e3_ci_canary.py` | 上のテスト（59 件＋Linux だけ走る 1 件） |

## PASS 条件（verify.py）

外部通信 0（Python・Node）／ガードが実際に入っていた（verify 自身の分を数えない）／Chrome がある実行では wrapper の起動 1 回以上／HEAD が動かない（commit 0）／認証情報（extraheader）が無い（push できない）／作業ツリーの変更が許可リストだけ（既知の書き込みは `exports/api_automation/collection.json` のみ）／`daily_lp.yml` が参照する Secrets の名前が pytest の step の環境に無い／canary の workflow が `secrets.` を参照しない。

## canary が実際に見つけたこと

1. `tests/test_phase12_safety.py::test_ebay_html_scraping_is_disabled` が、為替 API（`open.er-api.com`）を実通信で呼んでいた（遮断下でもテストが通るのは、失敗時に静的レートへフォールバックするため。これまで気づかれなかった）。テストの中で `get_usd_jpy` を固定値にして解消（src は不変。レートの非決定性もなくなる）。
2. ガードの初版が、ローカルの一時リポジトリへの `git clone` / `fetch` まで遮断し 15 件のテストを落とした。宛先が URL 形式（`https://`・`ssh://`・`user@host:`）のものだけを違反にし、`GIT_ALLOW_PROTOCOL=file` を併用。
3. Node ガードが `net.connect(port, host)`（内部で正規化された配列で `connect` を呼ぶ）を見落としていた。修正済み。
4. Chrome は、名前解決の規則だけでは IP リテラル（`http://203.0.113.1/`）を塞げない恐れがある（実測: IP リテラルも名前も、プロキシを指定するとプロキシ側へ向かう）。プロキシを使われない死んだローカルのポート（`socks5://127.0.0.1:9`）へ向けた。ループバックと `file://` は直接届く（実測）。

## 検証

- ローカルの再現（CI と同じ手順: venv の `.pth`・Node・Chrome wrapper・`GIT_ALLOW_PROTOCOL=file`・`--expect-chrome`・`--expect-node`）: pytest 3003 成功（ゲート後のテスト 1 件の追加の前の実行。canary のテストは単独で 59 成功・1 skip）・1 skip（Linux 専用の 1 件）・canary PASS・外部通信 0・Chrome 起動 128 回。
- canary 自体の変異テスト: **54 件中 53 件検出 + Linux 専用の 1 件は未検証**（`AF_NETLINK` は macOS では存在せず、ローカルでは検出できない。全件検出とは記録しない）。**GitHub Actions の初回の実行で、この Linux 専用テストが実行され PASS することを受入項目にする。**
- deploy-check: Errors 0（#881〜#892 全 OK）。ruff: 新規 0。
- 独立 reviewer 1 回目: Critical 0・High 1・Medium 4・Low 6 → 対応。最終差分の再ゲート（reviewer・auditor を独立に実行）: 2 名とも Critical 0・High 0・**Medium 1**（reviewer: パスつき `/usr/bin/curl`・`bash -lc` / `-ec`・シェル文字列内の git URL が素通り／auditor: `git clone file:///…` を誤って遮断）→ 対応（パスつきの検出・連結フラグ・`env` / `timeout` 等の包み・bytes の argv・git の `-C` / `-c` の値の読み飛ばし・`file://` の許可・`localhost` は完全一致のみ・Node のガードが入ったことを node がある実行で必須に）。対応後の最終差分の判定は下の「最終ゲート」。
- 再ゲートの途中で、auditor が Node の実験用スクラッチ（`nf.js`）をリポジトリ直下に残した（読み取り専用・リポジトリ外で実行する指示に反する）。どこからも参照されておらず、削除した。

## 最終ゲート（最終差分に対する独立の再ゲート）

| | Critical | High | Medium | Low |
|---|---|---|---|---|
| Reviewer（読み取り専用。約 150 通りの実験・テスト一式を複製ツリーで実行） | 0 | 0 | 0 | 7 |
| Auditor（読み取り専用。本物の Chrome を wrapper 経由で起動して IP リテラルを実証・既存テストを複製で実行して誤検知 0） | 0 | 0 | 0 | 6 |

前回までの指摘 5 件（パスつき道具・連結フラグ・シェル内 git URL／`file://` の誤検知／Chrome の IP リテラル／verify の自己カウント・Secrets・Chrome 起動 0・Node の未要求／`.localhost`）は両名とも「解消」。

ゲート後に直した 1 件（テストだけ。安全性に関わるコードは不変）: `test_verify_main_exit_code_reflects_result` が `verify.main()` を通して、CI の `GITHUB_STEP_SUMMARY` に偽の PASS / FAIL を追記していた（判定の終了コードには影響しない）。`GITHUB_STEP_SUMMARY` を外し、追記の挙動を一時ファイルで確かめる専用のテストを足した。

**記録だけの Low（直していない）**: ①`env sh -c "curl …"`・`nohup`・`timeout 5 sh -c …` のようにラッパーの先がシェルのときは見ない（git は `GIT_ALLOW_PROTOCOL=file` が補う。入れ子を使うテストが入ったら Medium に格上げ）②`bash /dev/tcp`・`openssl s_client`・`ping`・`dig` など道具の網羅漏れ③行継続・変数経由・stdin 経由のシェル文字列④Node の `dns.promises.resolve*`・`dns.Resolver`・`dns.reverse` が未ガード（コメントの「`dns.resolve*` を止める」は callback 版だけ）⑤Chrome は、呼び出し側が `--no-proxy-server` 等を渡すと後ろの `--proxy-server` より優先される（テストには無い）⑥`python -S`⑦`git --repo=URL`・scp 形式（`user@` なし）⑧誤検知: `git remote set-url`（ローカル操作）・シェル文字列の `echo 'no curl here'`・`socket.getfqdn()`・`0.0.0.0`・大文字の `LOCALHOST`（本リポジトリのテストには該当なし）⑨`verify.py` の `git()` は git の失敗時に空文字列を返す（fail-open。`rev-parse` も同時に空になり `git_commit_zero` が落ちる）⑩`cache: pip` は本番と同じ key（害なし）。

**再ゲートで起きた手順の逸脱（記録）**: auditor が Node の実験用スクラッチ（`nf.js`）をリポジトリ直下に残した（削除済み・未コミット）。reviewer は、Low-3 の検証のため外部 DNS の解決を 1 回だけ実際に発生させた（`example.com`。内容は名前解決のみで、リポジトリ・データは送っていない）。どちらも canary の成果物ではない。

## 限界（canary は tripwire であって sandbox ではない）

- Python の audit hook は通常の経路（requests・urllib・socket・subprocess・`os.system`・`shell=True`・`os.exec*` / `posix_spawn` / `spawn*`・`sendto` / `sendmsg`）を見る。**ctypes から libc を直接呼ぶ・`-S` や別のインタープリタ（`.pth` を読まない）・`curl` 以外の別名の道具**は見ない。敵対的な迂回は想定せず、「うっかり外へ出るテスト・コード」を見つける目的。
- Node は `net` / `dns`（http・https・fetch を含む）だけ。`dgram`・`child_process` 経由の通信は見ない。
- git は URL 形式の宛先を見る。URL を渡さない `git fetch origin` などは `GIT_ALLOW_PROTOCOL=file`（ガードが設定する）と「認証情報なし」で止める。
- Chrome の通信は記録できない（起動回数だけを数える）。通信を止める仕組み（名前解決の規則＋死んだプロキシ）で防ぐ。
- ソース変更の検査は追跡・未追跡のファイルが対象で、`.gitignore` 対象への書き込み（`data/*.db`・`data/logs/` など）は見ない。
- `verify.py` 自身がテストで書き換えられうる（書き換えは `repository_mutation_zero` で検出されるが、検出するのは書き換えられうる側）。
- `.pth` を作る step（printf）の動作は、Actions 上でしか確かめられない。

## 初回の GitHub Actions 実行と UI の修正（2026-11-12）

- run 43195021214（`097f006f`・`workflow_dispatch` 1 回）: canary の判定は PASS（外部通信 0・Chrome 起動 128・Node / Python のガード導入・commit 0・push 0・ソース変更 0・Secrets 0）。pytest は 3005 件中 1 件失敗（`tests/test_ui_phase9.py::test_dom_admin_no_overflow[500]`）。Linux 専用の `AF_NETLINK` テストは skip 0 件のため実行された計算。
- 診断（run 43221944241・診断用 workflow を 1 回）: 同一の commit・Python 3.11.18・Ubuntu 26.04・Chrome 156 で、A（canary と同じ wrapper あり）と B（wrapper なし。ネットワークデバイスの無い network namespace の中）が**同一の失敗**（`notifications` 区分・scrollWidth 506・clientWidth 485・delta 21）→ canary の wrapper は無関係。macOS はどちらも PASS（500 / 500 / 0）。
- 原因: `<code>`（`admin.py` の却下コマンド）の折り返せない 66 文字 `<duplicate|not_target|variant_only|bad_parse|unsupported|obsolete>`。Linux の DejaVu Sans Mono は字送り 7.2246px（66 文字 = 476.8px）で、実測の幅 476.8px と一致。さらに Linux は 15px の従来型スクロールバー（clientWidth 485・innerWidth 500）。必要 505.8px に対し使えるのは 485px。macOS の monospace は約 6.0px（同じ連続が約 396px）なので 500px では収まるが、macOS でもコンテナ幅が約 425px 未満になると同じ要素がはみ出す（420px で +5px・360px で +65px）。分類は `LATENT_UI_BUG` exposed by `OS_DIFFERENCE`。この `<code>` は 2026-10-17（#863）、テストは 2026-10-06 から存在し、pytest が Linux で動くまで見えていなかった。
- 修正: `src/content/ui/styles.py` の `_admin_css` に `.nu-ad code{overflow-wrap:anywhere}` を 1 行。運営者ページ（`.nu-ad`）の中の `<code>` だけ。素の `code{…}` にはしない。`overflow-x:hidden`・固定幅・font-size の縮小・ellipsis・文字列の短縮はしていない（却下コマンドは 120 文字すべてが読める。360px では 4 行に折り返す）。
- テスト（`tests/test_ui_phase9.py`）: ①`test_dom_admin_notifications_no_overflow_in_narrow_viewport`（360 / 390 / 420 / 500px。`innerWidth == 指定幅`・delta ≤ 0・すべての `<code>` の右端が viewport の中・`overflow` を切っていない・ellipsis でない・文字を縮めていない・文言が省略されていない）②`test_admin_reject_command_text_is_complete_and_code_wrapping_is_scoped` ③既存の `test_dom_admin_no_overflow`（6 幅）は判定を変えず、失敗時の診断（viewport の実寸・はみ出す要素の上位）だけを足した。**本物の狭い viewport の作り方**: headless Chrome のウィンドウ最小幅は 500px で、`--window-size` を 320 / 390 にしても `innerWidth` は 500 のまま（`--force-device-scale-factor` でも CSS 幅は縮まない）。500px のウィンドウの中に幅 360〜500px の iframe を置き、その中でページを動かし、`postMessage` で結果を外側に返す（`_run_in_frame`）。**既存の `[320, 390]` のテスト（他の UI フェーズ）は、実質 500px で動いている**（今回の範囲外。記録のみ）。
- 検証（ローカル）: pytest 3009 成功・1 skip（Linux 専用）。canary の判定 PASS（外部通信 0・Chrome 起動 132）。UI 修正の変異テスト 9 件すべて検出（修正を消す・効かない指定・ルートで横を切る・ellipsis・文字を縮める・全画面の code に広げる・対象を他のページへ広げる・却下の理由の一覧を短縮する 2 種）。canary 自体の変異テストは 54 件中 53 件検出 + Linux 専用の 1 件は未検証（不変）。deploy-check Errors 0。ruff: 変更ファイルは 0 件。通知以外の 7 区分も、320〜600px の 10 幅で delta 0（auditor が実証。折り返せない 90 文字の `<code>` を注入しても 0）。
- 独立の最終ゲート: reviewer・auditor とも Critical 0・High 0・Medium 0。Low: HANDOFF の古い記述（本更新で解消）／`overflow:clip` を修正と併用する変異は検出されない（何も隠していないので意味がない）／Linux 実機の iframe 内のスクロールバー・フォントは推測で、最終の canary で確認する。
- canary の guard・workflow・`scripts/ci_canary/`・canary のテストは**不変**。診断用の workflow（`ci_ui_diag.yml`）は削除。診断専用の出力（`UI_DIAG`）も削除。
- A7RV（別 issue・記録のみ）: 11-05 以降 8 回連続で `failed`（Sony の購入ページの取得。理由は空）。確認日は 11-04 のまま（偽の鮮度なし）。公式直販の期限は 14 日なので、回復しなければ 11-18 に確認済みから外れる見込み。7e-3 の範囲外で、7e-3 の完了前には調査・実装しない。

## 初回の CI 実行で想定される失敗（初回の実行の前の記述）

ローカルで見つからなかった外部通信・Linux 固有の差（`/tmp` 以外の書き込み、ubuntu の Chrome の起動、未追跡ファイルへの依存）。**初回の `workflow_dispatch` の実行結果は未確認**。

## 次の判断（ユーザー）

push 後に手動で 1 回実行し、結果を確認する。push の trigger を有効にするのは canary 成功後に別途判断する（7e-2・7c-3・7d・Product Registration Foundation・Phase31 は対象外）。
