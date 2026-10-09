#!/usr/bin/env bash
# 今すぐ行動の通知の台帳（outbox）を、LP の生成の前に main の最新に合わせる（Phase 20）。
#
# concurrency で待たされた実行・再実行（Re-run）は、起動したときの古いコミットから始まる。古い台帳から候補を作ると、
# 先の実行が保存した記録を上書きして同じ通知を作り直す。そこで main の最新の台帳を取り出し、その版（blob）を
# 保存の手順（persist_notification_state.sh）の比べる基準として残す。
# 出力: 基準のファイル（既定は $RUNNER_TEMP か .git の中の notification_outbox_base）に、実行の識別・main のコミット・
# 台帳の blob（無ければ空）・合わせた時刻
set -euo pipefail

STATE="${ACTIONABLE_STATE_FILE:-exports/notifications/actionable/state.json}"
# 基準のファイル: CI はジョブごとに新しい RUNNER_TEMP、手元は .git の中（/tmp を共有しない。Phase 21）
BASE_FILE="${NOTIFICATION_OUTBOX_BASE_FILE:-${RUNNER_TEMP:-$(git rev-parse --absolute-git-dir)}/notification_outbox_base}"
# この実行の識別（CI は run の ID と試行の回数。手元は作業ツリーの場所）。保存の手順はこれが同じときだけ基準を使う
RUN_ID="${GITHUB_RUN_ID:+gh-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}}"
RUN_ID="${RUN_ID:-local-$(git rev-parse --show-toplevel | sha256sum | cut -c1-16)}"

rm -f "$BASE_FILE"
git fetch -q origin main
MAIN_SHA=$(git rev-parse origin/main)
REMOTE=$(git rev-parse -q --verify "origin/main:$STATE" 2>/dev/null || true)
if [ -n "$REMOTE" ]; then
  mkdir -p "$(dirname "$STATE")"
  git show "origin/main:$STATE" > "$STATE"
  echo "main の台帳に合わせました（${REMOTE}）"
else
  rm -f "$STATE"
  echo "main に台帳がありません（次の生成は基準日）"
fi
# 基準: 実行の識別・合わせた main のコミット・その台帳の blob・合わせた時刻（保存の手順がすべて確かめる）
printf 'run=%s\nmain=%s\nblob=%s\nsynced=%s\n' "$RUN_ID" "$MAIN_SHA" "$REMOTE" "$(date +%s)" > "$BASE_FILE"
