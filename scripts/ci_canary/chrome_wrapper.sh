#!/usr/bin/env bash
# CI canary 用の Chrome の hermetic wrapper。
# テストは CHROME_BIN を最初に見る（tests/test_ui_phase1.py の _chrome）。ここに本物の Chrome を包んだこのスクリプトを渡すと、
# ブラウザが外部へ出る道（名前解決・プロキシ・バックグラウンドの更新・同期）を塞いだ状態で起動する。
# 呼び出し側の引数より **後ろ** に付けるので、テストが別の --host-resolver-rules を渡しても上書きできない。
# IP リテラル（http://203.0.113.1/）は名前解決の規則を通らないので、プロキシも死んだローカルのポート（127.0.0.1:9）に向ける。
# ループバック（127.0.0.1・localhost）と file:// はプロキシを通らず直接届く（Chrome の既定）。
#
# 環境変数:
#   CANARY_REAL_CHROME  本物の Chrome の実行ファイル（必須）
#   CANARY_CHROME_LOG   起動の記録先（任意。1 行 = 1 回の起動。引数・URL は書かない）
set -euo pipefail

real="${CANARY_REAL_CHROME:-}"
if [ -z "$real" ] || [ ! -x "$real" ]; then
  echo "chrome_wrapper: CANARY_REAL_CHROME が未設定か実行できない" >&2
  exit 127
fi

if [ -n "${CANARY_CHROME_LOG:-}" ]; then
  printf '{"kind":"chrome_launch","pid":%s}\n' "$$" >> "$CANARY_CHROME_LOG" || true
fi

exec "$real" "$@" \
  --host-resolver-rules="MAP * ~NOTFOUND , EXCLUDE localhost , EXCLUDE 127.0.0.1" \
  --proxy-server="socks5://127.0.0.1:9" \
  --disable-background-networking \
  --disable-component-update \
  --disable-sync \
  --disable-default-apps \
  --no-first-run \
  --no-default-browser-check \
  --metrics-recording-only
