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
BASE_FILE="${NOTIFICATION_OUTBOX_BASE_FILE:-${RUNNER_TEMP:-$(git rev-parse --absolute-git-dir 2>/dev/null || echo /nonexistent)}/notification_outbox_base}"
RUN_ID="${GITHUB_RUN_ID:+gh-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}}"
MAX_AGE_SECONDS="${NOTIFICATION_OUTBOX_BASE_MAX_AGE:-21600}"   # 手元の基準は6時間まで（CI は実行の識別で縛る）
out() { if [ -n "${GITHUB_OUTPUT:-}" ]; then echo "$1" >> "$GITHUB_OUTPUT"; fi; echo "$1"; }

if [ ! -f "$STATE" ]; then
  echo "台帳がありません（基準日の前）: $STATE"
  out "sha="
  exit 0
fi

# 秘密の値の形が入っていたら保存しない（公開のリポジトリ。deploy-check の _SECRET_PATTERNS と同じ形。大文字小文字を区別しない）
if grep -Eiq 'discord(app)?\.com/api(/v[0-9]+)?/webhooks/|api\.telegram\.org/bot[0-9]+:|(^|[^0-9])[0-9]{5,12}:[A-Za-z0-9_-]{30,}|hooks\.slack\.com/services/|authorization["'"'"']?[[:space:]]*:|bearer [A-Za-z0-9._-]{20,}' "$STATE"; then
  echo "::error::通知の台帳に配信先の URL・トークンの形があるため保存しません"
  exit 1
fi

if [ ! -f "$BASE_FILE" ]; then
  echo "::error::台帳を main に合わせていません（sync_notification_state.sh が動いていない）。保存しません"
  exit 1
fi
RUN_ID="${RUN_ID:-local-$(git rev-parse --show-toplevel | sha256sum | cut -c1-16)}"
field() { sed -n "s/^$1=//p" "$BASE_FILE" | head -1; }
B_RUN=$(field run); B_MAIN=$(field main); B_BLOB=$(field blob); B_AT=$(field synced)
# 古い基準・別の実行の基準を使わない（Phase 21）: 実行の識別・合わせた main のコミットの台帳・時刻を確かめる
if [ -z "$B_RUN" ] || [ -z "$B_MAIN" ] || [ -z "$B_AT" ]; then
  echo "::error::基準のファイルの形が違います（sync_notification_state.sh で合わせ直してください）"
  exit 1
fi
if [ "$B_RUN" != "$RUN_ID" ]; then
  echo "::error::基準のファイルが別の実行のものです（合わせ直してください）"
  exit 1
fi
case "$B_AT" in
  ''|*[!0-9]*) echo "::error::基準のファイルの時刻が読めません（合わせ直してください）"; exit 1 ;;
esac
NOW_S=$(date +%s)
if [ "$B_AT" -gt "$NOW_S" ] || { [ -z "${GITHUB_RUN_ID:-}" ] && [ $(( NOW_S - B_AT )) -gt "$MAX_AGE_SECONDS" ]; }; then
  echo "::error::基準のファイルが古すぎます・未来の時刻です（合わせ直してください）"
  exit 1
fi
if ! git cat-file -e "${B_MAIN}^{commit}" 2>/dev/null; then
  echo "::error::基準の main のコミットがありません（合わせ直してください）"
  exit 1
fi
AT_MAIN=$(git rev-parse -q --verify "${B_MAIN}:$STATE" 2>/dev/null || true)
if [ "$AT_MAIN" != "$B_BLOB" ]; then
  echo "::error::基準の台帳が、基準の main のコミットの台帳と違います（合わせ直してください）"
  exit 1
fi
SHA=$(sha256sum "$STATE" | cut -d' ' -f1)
LOCAL_BLOB=$(git hash-object "$STATE")

for i in 1 2 3; do
  git fetch -q origin main
  REMOTE=$(git rev-parse -q --verify "origin/main:$STATE" 2>/dev/null || true)
  EXPECTED=$(field blob)
  if [ "$REMOTE" = "$LOCAL_BLOB" ]; then
    printf 'run=%s\nmain=%s\nblob=%s\nsynced=%s\n' "$RUN_ID" "$(git rev-parse origin/main)" "$LOCAL_BLOB" "$B_AT" > "$BASE_FILE"
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
    NEW_MAIN=$(git -C "$WT" rev-parse HEAD)
    git worktree remove --force "$WT"
    git fetch -q origin main
    printf 'run=%s\nmain=%s\nblob=%s\nsynced=%s\n' "$RUN_ID" "$NEW_MAIN" "$LOCAL_BLOB" "$B_AT" > "$BASE_FILE"
    out "sha=$SHA"
    exit 0
  fi
  git worktree remove --force "$WT"
  echo "push に失敗（$i 回目）。main を取り直して確かめます"
done
echo "::error::台帳を保存できませんでした（送信の手順は実行しません）"
exit 1
