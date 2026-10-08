#!/usr/bin/env bash
# 今すぐ行動の通知の台帳（outbox）を、ほかの生成物とは別のコミットで main に保存する（Phase 20）。
#
# - 生成物のコミット（最後の「Commit and push」）・deploy-check・Pages の成否に関わらず、台帳だけを先に残す
#   （送った記録が消えて、次の実行で同じ通知を送り直さないように）
# - 作業ツリーには触れない: main の最新を一時的な worktree に取り出し、台帳のファイルだけを写してコミットする
#   （ほかの生成物の未コミットの変更を stash・rebase しない。衝突の印が生成物に残らない）
# - main の台帳が、同期（sync_notification_state.sh）・前回の保存の後に変わっていたら上書きせずに止める
#   （別の実行の記録を消さない。止まったら送信の手順は動かない）
# - 内容が変わっていなければ何もしない。出力: GITHUB_OUTPUT に sha（保存した台帳の SHA-256）
# - 台帳には配信先の URL・トークン・チャット ID を入れない（公開のリポジトリ）
set -euo pipefail

STATE="${ACTIONABLE_STATE_FILE:-exports/notifications/actionable/state.json}"
BASE_FILE="${NOTIFICATION_OUTBOX_BASE_FILE:-${RUNNER_TEMP:-/tmp}/notification_outbox_base}"
out() { if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "$1" >> "$GITHUB_OUTPUT"; fi; echo "$1"; }

if [ ! -f "$STATE" ]; then
  echo "台帳がありません（基準日の前）: $STATE"
  out "sha="
  exit 0
fi

# 秘密の値の形が入っていたら保存しない（公開のリポジトリ。deploy-check の _SECRET_PATTERNS と同じ形。大文字小文字を区別しない）
if grep -Eiq 'discord(app)?\.com/api(/v[0-9]+)?/webhooks/|api\.telegram\.org/bot[0-9]+:|\b[0-9]{8,10}:[A-Za-z0-9_-]{35}\b|hooks\.slack\.com/services/|authorization["'"'"']?[[:space:]]*:|bearer [A-Za-z0-9._-]{20,}' "$STATE"; then
  echo "::error::通知の台帳に配信先の URL・トークンの形があるため保存しません"
  exit 1
fi

if [ ! -f "$BASE_FILE" ]; then
  echo "::error::台帳を main に合わせていません（sync_notification_state.sh が動いていない）。保存しません"
  exit 1
fi
SHA=$(sha256sum "$STATE" | cut -d' ' -f1)
LOCAL_BLOB=$(git hash-object "$STATE")

for i in 1 2 3; do
  git fetch -q origin main
  REMOTE=$(git rev-parse -q --verify "origin/main:$STATE" 2>/dev/null || true)
  EXPECTED=$(cat "$BASE_FILE")
  if [ "$REMOTE" = "$LOCAL_BLOB" ]; then
    echo "$LOCAL_BLOB" > "$BASE_FILE"
    echo "台帳は main と同じです"
    out "sha=$SHA"
    exit 0
  fi
  if [ "$REMOTE" != "$EXPECTED" ]; then
    echo "::error::main の台帳が、合わせた後に別の実行で変わりました（上書きしません。送信の手順は動きません）"
    exit 1
  fi
  WT=$(mktemp -d)
  git worktree add -q --detach "$WT" origin/main
  mkdir -p "$WT/$(dirname "$STATE")"
  cp "$STATE" "$WT/$STATE"
  git -C "$WT" add -- "$STATE"
  git -C "$WT" -c user.name="github-actions[bot]" -c user.email="github-actions[bot]@users.noreply.github.com" \
    commit -q -m "通知の台帳の保存 [auto notification state]" -- "$STATE"
  if git -C "$WT" push -q origin HEAD:main; then
    git worktree remove --force "$WT"
    echo "$LOCAL_BLOB" > "$BASE_FILE"
    out "sha=$SHA"
    exit 0
  fi
  git worktree remove --force "$WT"
  echo "push に失敗（$i 回目）。main を取り直して確かめます"
done
echo "::error::台帳を保存できませんでした（送信の手順は実行しません）"
exit 1
