## 言語ルール（最優先・他のすべてに優先する）

**このプロジェクトでの応答はすべて日本語で行う。** 英語のコード・ログ・資料を読んだ直後でも日本語。質問・確認・コメント・コミットメッセージも日本語。技術用語はそのままでよい。
# プレ値商品監視・速報システム

## リポジトリと保護対象

- リモート: `estkey0001/premium-monitor`（**PUBLIC**）
- **空でも消してはいけない**: `data/logs/`（`src/notifiers/log_notifier.py` が出力先に使う）
- `audit_*` フォルダと `exports/` は自動処理が書き込む。手で動かさない

## 検証コマンド

```
python -m pytest
```

`requirements.txt` に `pytest>=7.4`。テストは `tests/` 配下。

## デプロイ構成

- GitHub Pages: `main` ブランチの `/docs` を `estkey0001.github.io/premium-monitor/` で公開
- GitHub Actions `Daily LP Update`: 毎日 12:00 JST に cron 実行（push では発火しない）
- push すると Pages が再ビルドされる。それ以外の外部発火は無い
## プロジェクト概要
iPhone / Apple製品 / カメラ / ゲーム機を対象に、公式価格・中古価格・買取価格・海外価格を横断監視し、プレ値候補を検出するシステム。自動購入は一切行わない。情報の収集・比較・通知・LP生成のみ。

## 参照資料（必要なときに読む）

| 触るもの | 読むファイル |
|---|---|
| CLI・ディレクトリ構成 | `ops/構成とCLI.md` |
| コレクター・品質チェック・LP 警告バー | `ops/コレクター運用.md` |
| 通知・eBay・楽天・Yahoo の Secrets | `ops/Secrets設定.md` |
| 価格の照合・時刻・抽選 runtime・route_id・deploy-check 番号・踏んだ罠 | `internal/DEV_NOTES.md` |
| Phase 11〜22 の監査（取得の安全性・成約・国内の網羅・商品の同一性・公式直販価格・カメラの買取・今すぐ行動・その通知・outbox・配信先と解決・Telegram の接続の試験） | `internal/audits/` |
| 新UIの仕様の正本 | `internal/uiux/UI_VIEW_MODEL_SPEC.md` |

## 技術スタック
- Python 3.10+, SQLite, Pydantic, Click, APScheduler
- Streamlit (管理画面), BeautifulSoup/Playwright (Collector)
- GitHub Actions (自動LP更新), GitHub Pages (LP公開)


## 絶対禁止
- 自動購入・自動応募・CAPTCHA突破・ログイン突破・複数アカウント運用・高頻度アクセス・規約違反行為
- 取得は必ず `src/collectors/polite.py` を通す（robots.txt・同じドメインの間隔・取得元の打ち切り・正直な User-Agent）。ブラウザを名乗らない・ブロックの後に別の手段で取り直さない・メルカリ / ラクマ / Amazon / ヤフオク / eBay・楽天の検索結果をスクレイピングしない（公式 API だけ）

## データの鮮度（偽装しない）

- 価格・在庫・成約・抽選等のデータについて、データ値または実際の source evidence が変わっていないのに、timestamp だけ更新して freshness を改善してはならない。
- collection failure 時刻を successful observation として保存してはならない。
- 人が再確認したときは、`observed_at` を書き換えずに確認日（`verified_at` や `VERIFIED_URLS_CHECKED_ON`）を更新し、確認した証拠（URL・価格）を残す。固定値・設定値の定価に、実行日の日時を付けない。
- 手動 CSV をコミットする前に、`python scripts/audit_timestamp_only_updates.py --worktree` で「値は同じで日時だけ新しい」行が無いことを確かめる（deploy-check #822 も直近のコミットを検査する）。

## 開発場所（重要）

Premium Monitor の実装は `~/Desktop/AI/ClaudeCode/premium-monitor` の1か所だけで行う。

| 項目 | 値 |
|---|---|
| ローカルのブランチ | `tcg-push`（常に `origin/main` と一致させて運用する） |
| リモート | `origin/main` |

push 先は必ず `tcg-push:main`（fast-forward のみ）。

```bash
git push origin tcg-push:main
```

2026-10-06 に、古いローカルの `main`（2026-09-08 の著者書き換えで、共通の祖先 `ec0d9cf4` から分岐した別履歴）・
`broken-design-backup`・`.claude/worktrees/` の作業ツリーを削除した（中身はすべて `origin/main` に同等のものがあることを確認済み）。

### 禁止

- `.claude/worktrees/` で実装しない
- 新しい worktree・clone を勝手に作らない
- 同じ Phase を別のセッションで並行して実装しない
- force push しない
- CI（Daily LP Update）の実行中に追加で push しない

### 作業開始時の確認（毎回）

```bash
pwd
git branch --show-current
git rev-parse HEAD
git fetch origin
git rev-parse origin/main
git status --short
git log origin/main -5
gh run list --limit 5
```

- `pwd` が上の場所でなければ実装しない
- ブランチが `tcg-push` でなければ実装しない
- HEAD と `origin/main` が違うときは、原因を確かめるまで実装しない

## 公開範囲

GitHub 上で **PUBLIC**。`estkey0001.github.io/premium-monitor/` で
「プレ値速報」のLP 274ページを公開しており、`Daily LP Update` ワークフローが毎日12:00 JSTに更新する。

コミットする前に、本名・個人メール・絶対パスが混ざっていないか確認すること
（`exports/` 配下の自動生成物と `docs/HANDOFF.md` が過去に該当した）。
経緯は `_アーカイブ/個人情報対応の記録-2026-10-02.md`。
