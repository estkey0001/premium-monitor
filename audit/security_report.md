# Security Report — Secrets 検査結果

検査対象キーワード: `API_KEY` / `SECRET` / `TOKEN` / `PASSWORD` / `COOKIE` / `APP_ID` / `WEBHOOK`
検査範囲: リポジトリ全体（`.git` / `.venv` / `__pycache__` を除外）
対象拡張子: `.py .yaml .yml .json .csv .md .txt .env*`

## 総合判定

**✅ 実値の機密情報（実際のAPIキー・トークン・パスワード・Cookie）はリポジトリ内に存在しません。**

キーワードのヒット（約167件）はすべて以下のいずれかであり、実値ではありません。
そのため監査パッケージに含めるにあたり**マスクが必要な実値はありませんでした**。

## 分類別の内訳

### 1. 環境変数「名」の参照（実値ではない）
コード／設定は実値を持たず、実行時に環境変数から読み込む設計。
- `config/notifications.yaml`: `token_env: "LINE_NOTIFY_TOKEN"`, `webhook_url_env: "DISCORD_WEBHOOK_URL"`, `bot_token_env: "TELEGRAM_BOT_TOKEN"`, `chat_id_env: "TELEGRAM_CHAT_ID"`
- `scripts/*.py`, `src/**/*.py`: `os.environ.get("EBAY_APP_ID")` 等の参照のみ

### 2. GitHub Actions の Secrets 注入（実値はGitHub側に保管）
`.github/workflows/daily_lp.yml` は実値を持たず `${{ secrets.X }}` で注入:
- `EBAY_APP_ID: ${{ secrets.EBAY_APP_ID }}`
- `DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}`
- `TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}`
- `TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}`

### 3. `.env.example`（プレースホルダのみ・監査パッケージには含めず）
- `LINE_NOTIFY_TOKEN=your_line_notify_token_here`
- `DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy`
- `TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here`
- `EBAY_APP_ID=`（空）
> いずれもダミー値。実値の `.env` は `.gitignore` 済みでリポジトリに未コミット。

### 4. レポート内のラベル文字列（実値ではない）
- `exports/.../*.json`: `"label_jp": "Cloud IP制限中（EBAY_APP_ID推奨）"`, `"ebay_app_id_configured": false`, `"needs_ebay_app_id": true`
  → 設定有無のフラグ／表示テキストであり値ではない。

## マスクした実値一覧

| # | ファイル | 種別 | 対応 |
|---|---|---|---|
| — | （該当なし） | — | 実値の機密情報は検出されませんでした |

## 推奨事項
- `.gitignore` に `.env` が含まれていることを継続維持（確認済み）。
- GitHub Secrets（`EBAY_APP_ID` 等）は引き続きリポジトリ外で管理。
- 監査ZIPには `.env` / `.env.example` / `data/*.db`（生データ）/ `.git` を含めていません。
