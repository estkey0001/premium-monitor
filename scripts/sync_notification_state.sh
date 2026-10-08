#!/usr/bin/env bash
# 今すぐ行動の通知の台帳（outbox）を、LP の生成の前に main の最新に合わせる（Phase 20）。
#
# concurrency で待たされた実行・再実行（Re-run）は、起動したときの古いコミットから始まる。古い台帳から候補を作ると、
# 先の実行が保存した記録を上書きして同じ通知を作り直す。そこで main の最新の台帳を取り出し、その版（blob）を
# 保存の手順（persist_notification_state.sh）の比べる基準として残す。
# 出力: $NOTIFICATION_OUTBOX_BASE_FILE（既定は $RUNNER_TEMP/notification_outbox_base）に main の台帳の blob（無ければ空）
set -euo pipefail

STATE="${ACTIONABLE_STATE_FILE:-exports/notifications/actionable/state.json}"
BASE_FILE="${NOTIFICATION_OUTBOX_BASE_FILE:-${RUNNER_TEMP:-/tmp}/notification_outbox_base}"

rm -f "$BASE_FILE"
git fetch -q origin main
REMOTE=$(git rev-parse -q --verify "origin/main:$STATE" 2>/dev/null || true)
if [ -n "$REMOTE" ]; then
  mkdir -p "$(dirname "$STATE")"
  git show "origin/main:$STATE" > "$STATE"
  echo "main の台帳に合わせました（${REMOTE}）"
else
  rm -f "$STATE"
  echo "main に台帳がありません（次の生成は基準日）"
fi
printf '%s' "$REMOTE" > "$BASE_FILE"
