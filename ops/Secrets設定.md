# Secrets と外部 API の設定

通知・海外価格・公式 API の有効化手順。`CLAUDE.md` から移した。

## 通知 Secrets 設定（Discord / Telegram）

Daily LP Update ワークフローの結果通知を有効にするには、GitHub リポジトリの
Settings → Secrets and variables → Actions に以下のシークレットを設定してください。

| Secret 名 | 説明 | 必須 |
|-----------|------|------|
| `DISCORD_WEBHOOK_URL` | Discord webhook URL | どちらか一方でOK |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | どちらか一方でOK |
| `TELEGRAM_CHAT_ID` | Telegram Chat ID | TELEGRAM_BOT_TOKEN と対で必要 |

- どちらか一方だけでも通知可能
- 未設定の場合は自動でスキップ（エラーにならない）
- 通知スクリプト: `scripts/notify_workflow_result.py`（`--dry-run` オプションで動作確認可能）
- Secrets を渡すのは送信の手順だけ（今は「Notify workflow result」だけ）。収集・LP の生成・通知のイベントの生成・Pages・テストには
  渡さない（deploy-check #857 が検査する。Phase 21）

### 今すぐ行動の通知（ACTIONABLE_NOW）の本番の送信（Phase 21 の時点では無効）

今すぐ行動の通知は outbox（`src/notifiers/outbox.py`）から送る。本番の送信は、次が**すべて**そろうまで動かない
（`python -m src.cli notification gate` で各条件の可否だけを確かめられる。値は出さない）。

| 条件 | 設定する場所 | 今 |
|---|---|---|
| 送信の部品（HTTP の transport）がある | コード（`adapters.REAL_SEND_IMPLEMENTED`） | 無い（Phase 21 では作らない） |
| ユーザーの明示の許可 | Variables: `NOTIFICATION_REAL_SEND=true`（既定 false。ワークフローは "false" に固定） | false |
| dry-run を外す | `NOTIFICATION_DRY_RUN=false`（既定 true。ワークフローは "true" に固定） | true |
| 配信先の選択 | Variables: `NOTIFICATION_PROVIDERS=discord,telegram` | 未設定 |
| 配信先の設定（形を検査する） | Secrets: `DISCORD_WEBHOOK_URL` / `TELEGRAM_BOT_TOKEN`・`TELEGRAM_CHAT_ID`（「Send notifications」の手順にだけ渡す） | 未設定・渡していない |

届いたか不明（UNKNOWN_DELIVERY）の配信は自動では送り直さない。人が配信先で確かめて、手元で解決する:

```bash
python -m src.cli notification list-unknown
python -m src.cli notification resolve <通知の ID> delivered|not-delivered|cancel|keep-unknown --confirm
```

解決は main の台帳と手元の台帳が同じときだけ書き換える（`git pull` で合わせてから）。台帳だけをコミットして
`git push origin tcg-push:main`（CI の実行中は push しない）。


## eBay の成約（Marketplace Insights API。Phase 13）

eBay の成約（売れた価格・成約日時）は **Marketplace Insights API** だけで取る。CI の「eBay SOLD (Marketplace Insights)」
のステップ（`scripts/collect_ebay_sold.py`）が毎回呼ばれ、次の4つが**すべて**そろったときだけ取りに行く。
1つでも欠けていれば通信0で、状態だけを `exports/sold_history/collect_status.json` に書く（CI は失敗にしない）。

| 順 | 条件 | 設定する場所 | 欠けているときの状態 |
|---|---|---|---|
| 1 | 資格情報 | Secrets: `EBAY_CLIENT_ID`・`EBAY_CLIENT_SECRET` | `PENDING_USER_CONFIGURATION` |
| 2 | Marketplace Insights API の利用許可（eBay の審査制・Limited Release）を人が確認した | Variables: `EBAY_INSIGHTS_APPROVED=true` | `PENDING_EBAY_APPROVAL` |
| 3 | 成約のデータを**公開リポジトリ**（`exports/`）に保存してよいと、eBay の API の利用規約で人が確認した | Variables: `EBAY_SOLD_LICENSE_CONFIRMED=true` | `PENDING_LICENSE_CONFIRMATION` |
| 4 | 取得の明示・dry-run でない | Variables: `ENABLE_EBAY_API=true`・`API_DRY_RUN=false` | `DISABLED` / `DRY_RUN` |

- `ENABLE_EBAY_API=true` だけでは取りに行かない。`ENABLE_EBAY_API=false` にすれば、いつでも通信0に戻せる（停止スイッチ）。
- `API_DRY_RUN=false` は楽天・Yahoo の API のステップにも効く。
- 利用規約の解釈は推測しない。確認できるまで 3 を true にしない。
- token の取得で 401 が返ったら `AUTH_FAILED`（資格情報の誤り）、400（invalid_scope）か 403 が返ったら `PENDING_EBAY_APPROVAL`（許可が無い）。
- 429 は Retry-After（秒数・HTTP-date）に従う。120秒を超える待ちを求められたら、その実行では取りに行かない。

### 段階（勝手に広げない）

1. **canary**（`EBAY_SOLD_CANARY=true` が既定）: 1商品（`EBAY_SOLD_CANARY_PRODUCT`。既定は `prod_ps5_pro`）だけを取る。
   取得・変換・報告（`exports/sold_history/canary.json`）までで、**成約の履歴には書かない**（ルート・利益商品に入らない）。
   報告の内容: 検索語・マーケット（EBAY_US）・返ってきた件数・使えた件数・使わなかった件数と理由・成約日時の範囲・
   状態・価格の範囲・item ID・ライセンスの状態・関門の結果。
   - PS5 Pro は eBay US では地域の型番（CFI-7000 / CFI-7100 / CFI-7014 など）が混ざる。canary の報告で使えた件数が
     少なければ、`EBAY_SOLD_CANARY_PRODUCT` を段階の一覧の別の商品（`prod_x100vi` など、型番が世界共通の商品）に変える
2. canary が合格（`passed: true`）したら、人が報告を見てから `EBAY_SOLD_CANARY=false` にする。
   ここから成約の履歴（`exports/sold_history/latest.json`）に書く。段階は `EBAY_SOLD_STAGE`（1 → 3 → 10 商品）。
3. 段階ごとの関門: 誤った成約・同一性の誤り・秘密の値・アクセス制限・重複・取得の失敗がすべて0で、使える成約が1件以上。
   通らなければ履歴に書かない。前の段階を通っていなければ（`exports/sold_history/rollout.json`）、指定しても段階を上げない。
   10商品より先には広げない（全商品への展開はしない）。

### ローカルでの確認

```bash
python scripts/collect_ebay_sold.py --dry-run
```

送る予定のリクエストと、4つの条件の状態だけを出す（ネットワークに出ない・秘密の値は出さない）。

### 使わなくなったもの

- `EBAY_APP_ID` と Finding API（`findItemsByKeywords`・`findCompletedItems`）: 2025-02-05 に廃止された。呼ぶコードは
  Phase 13 で削除した（`EBAY_CLIENT_ID` を登録しても、廃止された API へ client id を送らない）。
- eBay の検索結果の HTML: Phase 12 で取得を停止した。`scripts/update_overseas_prices.py` は eBay を取らない。


## 自動取得の拡張（2026-07-23）— キー投入で自動起動

「できるだけ自動取得」方針。以下は**Secret を登録するだけで自動化が起動**する設計。
未設定でも動作する（手動キュレーションが働く。HTML の取得には戻らない）。

### 公式定価コレクター（キー不要・実装済み）
- `apple/ricoh/fujifilm` に加え `canon/nikon/sony` を追加（`src/collectors/official/`）。
- 日次CIで `python -m src.cli collect-official` が走り公式定価を自動更新。
- **canon/nikon/sony を実際に収集するには** `product_source_config` に各商品の
  公式ストア `target_url` を登録する必要がある（未登録の商品は安全にスキップ）。
- robots.txt 準拠・`rate_limit_sec` 遵守で低頻度アクセス。

### 公式API統合（env-gated・キー投入で自動有効化）
`src/collectors/api/official_apis.py`。GitHub Secrets にキーを登録し、Variables の `ENABLE_RAKUTEN_API` /
`ENABLE_YAHOO_API` を true と明示したときだけ API を使う（CI の既定は false。キーが無い・true 以外なら通信0。Phase 13）:

| Secret 名 | 用途 | 効果 |
|-----------|------|------|
| `RAKUTEN_APP_ID` | 楽天 Ichiba Item Search API | 楽天の新品価格を API で取得（HTML の取得は停止）|
| `RAKUTEN_AFFILIATE_ID` | 楽天アフィリ（任意）| 任意 |
| `YAHOO_SHOPPING_APP_ID` | Yahoo!ショッピング API | 新品ショッピング価格（※落札soldとは別種・混在させない）|

### 自動化できない領域（ToS・正直な上限）
- **メルカリ / ラクマ**: スクレイピング禁止・公式価格APIなし → **手動キュレーション継続**が正しい設計。
- **クラウドIPブロック**: GitHub Actions のIPは多くの日本の小売サイトにブロックされる（成功率が上がらない主因）。ブロックは回避しない（プロキシ・偽装はしない。取得元の判断を尊重して、その実行では打ち切る）。

