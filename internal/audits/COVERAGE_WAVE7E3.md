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

## 初回の CI 実行で想定される失敗

ローカルで見つからなかった外部通信・Linux 固有の差（`/tmp` 以外の書き込み、ubuntu の Chrome の起動、未追跡ファイルへの依存）。**初回の `workflow_dispatch` の実行結果は未確認**。

## 次の判断（ユーザー）

push 後に手動で 1 回実行し、結果を確認する。push の trigger を有効にするのは canary 成功後に別途判断する（7e-2・7c-3・7d・Product Registration Foundation・Phase31 は対象外）。
