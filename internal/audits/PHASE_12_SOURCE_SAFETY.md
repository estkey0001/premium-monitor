# Phase 12 取得の安全性と売却データ（2026-10-07）

基準は Phase 11 の最終値（CI 37566048081・生成 2026-10-07 13:41）。

## 1. 取得経路の監査（変更前 → 変更後）

### 変更前（CI 37566048081 のログとコードから確認）

| 経路 | CI 時間 | robots.txt | rate_limit_sec | 打ち切り | UA | 確定値への寄与 |
|---|---|---|---|---|---|---|
| 買取 CSV（update_buyback_prices） | 13.6分 | 見ない | 無視（固定 1.5〜8秒） | なし | 一部ブラウザ偽装 | 買取商店 9件 |
| カメラ買取（update_camera_buyback） | 18.0分 | 見ない | 無視（待ちなし） | なし | ブラウザ偽装 | 0件（フジヤは参考） |
| resale（collect_resale_prices） | 26.5分 | 見ない | 無視（固定2秒） | なし | ブラウザ偽装 | 0件 |
| 海外 eBay（update_overseas_prices） | 3.7分 | 見ない | 無視（固定5秒） | なし | ブラウザ偽装 | 0件 |
| 抽選（update_lottery_events） | 1.1分 | 見ない | 無視（固定1.5秒） | なし | ブラウザ偽装 | 抽選3件 |
| 公式（collect-official） | 6.0分 | 見る | 守る（60秒以上） | 実質なし | 正直 | 定価の確認 |
| TCG（collect_tcg_events） | 13.6分 | 見る | 守る（60秒以上） | なし | ブラウザ偽装 | イベント14件 |

経路ごとの問題:

- **resale:** ラクマ（約22.5分）とメルカリをスクレイピングしていた。どちらも規約上、許された取得の経路が無い。
- **じゃんぱら:** 429 を 30秒・60秒待ちで3回再試行し、約10分かかっていた。
- **モバイル一番と基底:** 403・429 の後に Playwright で取り直していた。
- **resale と eBay:** 失敗した同じ URL を urllib・requests で取り直していた。
- **カメラ:** 価格に使わない urllib の取得を60回していた。

### 変更後

| 経路 | robots.txt | 間隔 | 打ち切り | UA |
|---|---|---|---|---|
| 買取 CSV | 見る | 守る | 店ごと | 正直 |
| カメラ | 見る | 守る | 店ごと | 正直 |
| resale | 見る | 守る | 取得元ごと | 正直 |
| 海外 eBay | 見る | 守る | 1回でも止まったら以後なし | 正直 |
| 抽選 | 見る | 守る | 403/429/robots の後に Playwright で取り直さない | 正直 |
| TCG | 見る | 守る（変更なし） | — | 正直 |

すべて新しい共通部品 `src/collectors/polite.py` を通す。中身は既存の RobotsChecker と RateLimiter を使う。

- **User-Agent:** `PremiumMonitor/1.0 (+https://github.com/estkey0001/premium-monitor)`。ブラウザの名前もブラウザ互換の形も名乗らない。
- **robots.txt の照合:** 名前 `PremiumMonitor/1.0` で行う。以前の TCG は UA の全文を渡していたため、「mozilla」として照合されていた。
- **robots.txt を取得できないとき（5xx・通信の失敗）:** 取りに行かない（RFC 9309）。robots.txt が無いとき（4xx）は制限なし。

- **間隔:** sources.yaml の rate_limit_sec、Crawl-delay、60秒のうち最大の値をドメインごとに空ける。
- **打ち切りの基準:**
  - 即打ち切る: http_403、http_401、site_blocked、rate_limited_429、robots_disallowed など。
  - 2回続いたら打ち切る: 一時的な失敗、ページの形の不一致。
  - 数えない: 未掲載。
  - 打ち切りは、その実行の中だけ。次の実行では再び試す。
- **再試行しないもの:** 429、ブロック、未掲載、パーサーの不一致。
- **再試行するもの:** 一時的な失敗のみ（タイムアウトなど。1回まで）。
- **メルカリとラクマ:** 規約で禁止されていて公式の価格 API も無いので、取得しない。状態は not_supported とする。CLI からも呼べないようにした。
- **eBay の検索結果のページ:** API が使えないときに HTML を取りに行くのは API の失敗の回り道なので、取得をやめた。即打ち切り（html_scraping_disabled）。
- **Amazon の検索結果のページ:** 取得をやめた（公式の API は未接続）。
- **楽天:** 公式 API だけで取る。API の失敗・未設定のときに検索結果の HTML を取らない（HTML の取得のコードは削除した）。
- **ヤフオクの検索結果のページ:** 規約が自動の取得を許すか確認できていないので取得をやめた。出品の参考の価格で、確定の利益には使っていなかった。再開は規約の確認の後のユーザー判断。
- **robots.txt に到達できないとき:** 理由は robots_unreachable で、禁止（robots_disallowed）と分けて記録する。どちらも、その実行では以後を取りに行かない。
- **ブロックの後:** 403/429 の後と接続の失敗の後に、Playwright で取り直さない。Playwright の応答が 401/403/429 のときも拒否として扱う。
- **同じ URL への2回目の取得:** 再試行・Playwright での取り直しの前も、同じドメインの間隔をあける。
- **キャッシュ:** 1回の実行で同じページは1回だけ取得する。キャッシュから返したときの HTTP 状態は、その時の値（L2）。
- **記録:** 打ち切りの結果を各レポートの shop_cutoffs に、店ごとに送ったリクエスト数を collector_metrics に残す。

### 時間の見積もり（推定。本番の CI で確かめる）

60秒以上の間隔だけを入れると逆に遅くなる。打ち切り・キャッシュ・取得の停止を一緒に入れた場合の見積もりは次のとおり。

| 経路 | 前回 | 見積もり | 主な理由 |
|---|---|---|---|
| 買取 | 13.6分 | 12〜16分 | じゃんぱらの再試行（約10分）が消える。買取商店の5ページは各90秒あける |
| カメラ | 18分 | 約30〜40分 | フジヤは機種ごとに最大2候補×90秒。前回当たった候補を先に試す。マップカメラ・キタムラは最初のブロックで打ち切る |
| resale | 26.5分 | 数分 | ラクマ・メルカリ・Amazon・ヤフオク・eBay の HTML を取らない。楽天は公式 API だけ |
| 海外 | 3.7分 | 1分未満 | eBay の HTML を取らない |
| 抽選 | 1.1分 | 2〜4分 | 60秒の間隔 |

合計は前回の84分から、おおむね同じか短くなる見込み。

## 2. 売却データ（SOLD）

| 経路 | 状況 | 結論 |
|---|---|---|
| eBay Finding API | `findItemsByKeywords`・`findCompletedItems` は 2025-02-05 に廃止された | 既存の `market_apis.ebay_fetch_items` はキーを入れても動かない |
| eBay Marketplace Insights API（item_sales/search） | 成約を取れる唯一の公式の経路。過去90日分。審査で許可された開発者だけが使える（Limited Release）。OAuth のクライアント認証が必要 | 下の3つが必要（ユーザーの作業） |
| ヤフオク | 今の取得は出品中の一覧（LISTING） | 成約の落札相場（/closedsearch）は、規約・robots.txt の確認と商品ページ・落札日時の取得方法が決まるまで実装しない |
| メルカリ・ラクマ | 公式 API なし | 取得しない（手動の確認のみ） |

eBay Marketplace Insights を使うために必要なもの:

- eBay の開発者アカウントで Marketplace Insights の利用許可を得る（審査）
- GitHub Secrets に `EBAY_CLIENT_ID`（または `EBAY_APP_ID`）を登録する
- GitHub Secrets に `EBAY_CLIENT_SECRET` を登録する

### 作ったもの（本番では未起動）

**`src/collectors/api/ebay_insights.py`**
- リクエストの組み立て（q・lastSoldDate・conditionIds・limit は最大200・offset）。
- token のリクエストの組み立て。token は保存も表示もしない。
- 応答の読み取り（itemSales・ページ送り）。商品ページの URL は `https://www.ebay.com/itm/<番号>` の形にそろえる。
- 同一性は既存の ProductIdentityResolver で判定する。成約日時・状態（conditionId）を確認する。USD は fx_rates.yaml の値で円に換算する。
- 1回の実行のリクエスト数に上限を設ける。429 の再試行は最大2回。
- 秘密の値（eBay の token の `v^1.1#...` の形を含む）は redact で伏せる。dry-run の出力を持つ。
- 成約の履歴には取得元の商品名（title）を保存しない。eBay の API のデータを公開のリポジトリ（exports/）に残してよいかは、有効にする前に API の利用規約で確かめる（ユーザー判断）。

**`scripts/collect_ebay_sold.py`**
- `--dry-run` は送るリクエストの一覧だけを出す。
- 資格情報がそろい、`ENABLE_EBAY_API=true` を明示したら、まず1商品（PS5 Pro）で canary を行う。
- canary の合格（`exports/sold_history/canary.json`。検索が通り、使える成約が1件以上）が無ければ、段階（EBAY_API_STAGE）を上げても1商品のまま。
- CI からは呼ばない。

**`src/market/sold_history.py`**
- 成約1件の検証:
  - 商品ページの URL があること。
  - 成約日時があること。observed_at で代用しない。
  - 同一性を確認済みであること。
  - 状態が分かること。
  - 価格が正であること。
- 重複は、取得元・商品ページ・成約日時で除く。再取り込みでは observed_at を新しくしない。
- 履歴は `exports/sold_history/latest.json` に保存する（CI をまたいで残る）。
- 成約中央値の条件:
  - 3件以上（MIN_SOLD_SAMPLES）であること。1〜2件では中央値を作らない。成約1件ずつを参考の観測にする（参考ルートにだけなる）。
  - 集計期間は売値の鮮度の基準 STALE_DAYS（14日）をそのまま使う。新しい期間は作っていない。
  - 状態の系統は混ぜない。
  - 出品は入れない。

**`normalized_prices.build_observations`**
- 成約中央値を観測に加える。今の本番は履歴が0件なので、何も加わらない。

**ルートの扱い:**
- eBay API 由来の成約中央値は overseas_sold_price・collector_method=api として、既存のルート生成の経路（`_sell_ok`）に乗る。
- 費用は既存の海外の手数料（13%+4%+3%）・送料5,000円・安全余裕で計算する。
- fixture で確かめた結果:
  - 成約3件 → 確定ルート1件（RETAIL_TO_SOLD_MEDIAN・SECONDARY_TO_SOLD_MEDIAN）。
  - 成約2件 → 参考のみ。

### 見つけた食い違い（直した）

- `classify_link_type` がフリマ・オークション・eBay の商品ページを unknown にしていた。そのため、二次流通で仕入れるルートは確定できなかった。
  - `price_types.is_item_url` に合う URL は item にした。
  - ダミーの番号の URL は unknown にした。
- 正規店の商品ページのうち、/product/ の形（ヨドバシなど）は item と判定しない。この判定は変えていない。確定ルートの仕入れ先に使える正規店は /dp/・/item・/detail などの形だけ。

## 3. ユーザーの設定待ち

- eBay の Marketplace Insights の許可と、Secrets 2つ（EBAY_CLIENT_ID・EBAY_CLIENT_SECRET）。設定後は、まず `python scripts/collect_ebay_sold.py --dry-run` で確かめ、次に canary を行う。
- 楽天・Yahoo!ショッピングの API キー（新品の価格。成約ではない）。
- eBay の成約のデータを公開のリポジトリに保存してよいか（eBay の API の利用規約の確認）。
- ヤフオクの落札相場を取るかどうかの判断、出品の一覧の取得を再開するかどうかの判断（どちらも規約・robots.txt の確認を含む）。

## 4. 残している既存の点（今回は変えていない）

- ドスパラの予備の URL の逆引き: 空白の検索語と %20 に変換した URL を比べているので、予備に入らない。直すと取得が増えるので、直していない。
- `normalized_prices` の海外の価格: 取得元に ebay を含むものを成約（SOLD）として扱う。ただし成約中央値の条件を満たさないので、確定ルートには入らない。
- eBay の成約で数量の多い出品は、売れるたびに成約日時が変わる。そのため、同じ出品が中央値の多くを占めることがある。有効にした後に canary で確かめる。
- 国内の成約中央値（flea_sold_price）は、ルートの売値の種別に入っていない。国内の成約の取得元が無いので、今は使わない。
