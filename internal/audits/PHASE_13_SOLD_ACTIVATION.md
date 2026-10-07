# Phase 13 — 成約の有効化と CI の組み込み・カメラの取得時間

作成: 2026-10-07。対象のコミット: Phase 13 の段階A（CI の組み込みと関門）・段階B（カメラの取得時間）。

## 1. 始めたときの状態（基準）

- 生成物: 01b3f5bb（Run 37599795597 の生成コミット）。定時の Run 37602159390 は、手動の実行と重なって push に失敗した
  （push の前の `git pull --rebase` が未ステージの変更で失敗し、push も拒否された。生成コミットは入っていない）。
- `production_coverage_metrics.py` の値（Phase 12 の after と同じ）:

| 指標 | 値 |
|---|---:|
| 有効な成約（Valid SOLD） | 0 |
| 成約のある商品 | 0 |
| 成約中央値（SOLD_MEDIAN） | 0 |
| 成約中央値のある商品 | 0 |
| 確定ルート / 参考ルート | 0 / 0 |
| 買取の成功 | 15 / 54 |
| 健康度 | 37.8 |

- CI の所要時間: 約99〜100分（Run 37599795597 は 98.9分、37602159390 は 100.0分）。
  ステップ別: カメラ 67.6分・TCG 12.0分・買取 6.1〜7.7分・公式 6.0分・抽選 5.8分・中古 1秒未満・海外 約1秒。

## 2. eBay の関門（2026-10-07 に確認）

| 条件 | 状態 | 確認したこと |
|---|---|---|
| 資格情報（Secrets: EBAY_CLIENT_ID・EBAY_CLIENT_SECRET） | 無し | `gh secret list` が空（名前だけを見た。値は見ていない） |
| Marketplace Insights API の承認 | 確認できない | 審査制（Limited Release）。承認の記録は無い |
| 公開リポジトリに成約を保存してよいか（ライセンス） | 確認できない | API の利用規約の解釈は推測しない |
| 取得の明示（Variables: ENABLE_EBAY_API） | 未設定（CI の既定は false） | `gh variable list` が空 |

→ 状態は **PENDING_USER_CONFIGURATION**（同時に PENDING_EBAY_APPROVAL・PENDING_LICENSE_CONFIRMATION）。本物のリクエストは送っていない。

## 3. 作ったもの（段階A）

- **CI のステップ**「eBay SOLD (Marketplace Insights)」（正規化の前）。既定はすべて安全側
  （ENABLE_EBAY_API・EBAY_INSIGHTS_APPROVED・EBAY_SOLD_LICENSE_CONFIRMED は false、EBAY_SOLD_CANARY は true、
  API_DRY_RUN は true）。条件が欠けていれば通信0で状態だけを書き、CI を失敗にしない。
- **関門の順番**（`ebay_insights.status()`）: 資格情報 → 承認 → ライセンス → 取得の明示 → dry-run。
  `ENABLE_EBAY_API=true` だけでは取りに行かない。
- **canary**: 1商品だけ。取得・変換・報告（`exports/sold_history/canary.json`）まで。履歴に書かない。
  canary の商品は `EBAY_SOLD_CANARY_PRODUCT` で段階の一覧の中から変えられる（コードの変更なしで）。
- **段階**: canary に合格し、人が `EBAY_SOLD_CANARY=false` にした後に、`EBAY_SOLD_STAGE`（1 → 3 → 10 商品）。
  段階ごとの関門（誤った成約・同一性の誤り・秘密の値・アクセス制限・重複・取得の失敗がすべて0、使える成約1件以上）を
  通ったときだけ履歴に書く。前の段階を通っていなければ段階を上げない。10商品より先には広げない。
- **重複**: 同じ取得元・同じ商品ページ（eBay なら item ID）は1件。数量の多い出品で成約日時が新しくなったときは
  置き換える（件数は増えない）。Phase 12 では成約日時もキーに入れていたので、同じ出品が毎回1件ずつ増えうる作りだった。
- **状態**: 整備品・傷あり新品・ジャンクは使わない（理由を数える）。開封済み（1500）は新品と混ぜない。
- **為替**: 換算の根拠（レート・出どころ・時刻）を note に残す。
- **失敗の区別**: token の 401 → AUTH_FAILED、400（invalid_scope）・403 → PENDING_EBAY_APPROVAL、
  429 → Retry-After（秒数・HTTP-date）に従い、120秒を超える待ちならその実行では取りに行かない（RATE_LIMITED）。
- **token の形**（v^1.1#...）は、前置き（Bearer・access_token=）が無くても伏せる。
- **CI の保存**: `exports/sold_history/` を生成物のコミットに入れた（Phase 12 では入っておらず、履歴が CI をまたいで残らなかった）。
- **push の競合**: push が拒否されたら、未ステージの変更を退避して取り込み直してから push する（生成物はこの実行の側）。
- **廃止された Finding API を呼ぶコードを削除**（`ebay_completed._fetch_via_api`・`market_apis.ebay_fetch_items`）。
  以前は `EBAY_CLIENT_ID` を登録すると、廃止された API へ client id を URL に入れて送る作りだった。
- **楽天・Yahoo!ショッピング**: キーがあっても `ENABLE_RAKUTEN_API` / `ENABLE_YAHOO_API` が false なら通信0
  （以前は中古の取得のステップにスイッチが渡されず、キーを登録すると止められなかった）。
- **文言**: 楽天の「HTML取得失敗」→「API未設定・停止（HTML取得は停止）」、取れたときは「API」。eBay の
  「Finding API を使え」の案内を削除。TCG で robots.txt に到達できないときを「アクセス拒否」ではなく
  「接続できない」（robots_unreachable）にした（禁止の robots_disallowed とは別に記録）。
- deploy-check: #845（eBay の成約の関門を動かして確かめる）・#846（Finding API を呼ぶコードが無い）。
  #296・#297・#485・#718・#206e3 は Finding API・古い push の手順を前提にしていたので、今の意図に合わせた。

### レビュー・監査で直したこと

- 429・401・403・連続の失敗で取得が止まったら、残りの商品へ送らない（以前は長い待ちを商品の数だけ重ねえた）。
  1実行のリクエストの上限は HTTP の回数（再試行を含む）で数える。eBay へのリクエストにも正直な User-Agent を付ける。
- 段階の関門の「同一性の誤り」は、resolver の判定に加えて、取得元の商品名に名前・型番の目印（IDENTITY_MARKERS）が
  あるかを独立に確かめる（以前は作りの上で必ず0だった）。
- canary の合格は商品と結びつける（合格の後に canary の商品を変えたら、やり直す）。
- 成約の履歴は、増えた・置き換えたときだけ書く。rollout.json は入れ子の時刻も除いて比べる（時刻だけの更新をしない）。
- CI の push の取り込み直しで `-X theirs` をやめた。衝突したのが生成物（exports/・audit_health/・docs の自動生成の
  ページ）だけならこの実行の側を採り、それ以外（data/ の CSV など人も変えるファイル）が衝突したら止める。
  使い捨てのリポジトリで、生成物の衝突は push でき、CSV の衝突は止まる（人の変更が残る）ことを確かめた。
- 楽天・Yahoo!ショッピングは `ENABLE_*_API=true` と明示したときだけ使う（未設定・知らない値は使わない）。
- カメラ: GR IV HDF と GR IV Monochrome を互いに除外。使い回したことを status（reused_page）に残す。
- deploy-check #297 は collect を実際に呼んで通信0・html_blocked を確かめる。#846 は eBay の検索結果の HTML を
  取るコード（`_fetch_via_html`・`src.collectors.price.ebay`）の呼び戻しも検出する。

## 4. canary の報告（未実施）

承認・資格情報・ライセンスが無いので、本物の canary はしていない。実行したときに `exports/sold_history/canary.json`
に書かれる項目: 検索語・マーケット（EBAY_US）・返ってきた件数・使えた件数・使わなかった件数と理由・成約日時の範囲・
状態・価格の範囲（円・ドル）・item ID・ライセンスの状態・関門の結果・合格か。秘密の値と生の応答は保存しない。

canary の商品の選び方: 既定は PS5 Pro だが、DB の型番は日本向け（CFI-7000A01）で、eBay US の出品は地域の型番
（CFI-7000 / CFI-7100 / CFI-7014 など）が混ざる。canary の報告で同一性で落ちた件数が多ければ、型番が世界共通の
商品（`prod_x100vi`・`prod_a1ii` など）に `EBAY_SOLD_CANARY_PRODUCT` で変える。

## 5. カメラの取得元の価値（Phase 12 の本番 CI より）

| 取得元 | リクエスト | 時間 | 確定に使える | 参考 | 商品数 |
|---|---:|---:|---:|---:|---:|
| マップカメラ | 1（robots.txt が 403 → site_blocked で打ち切り） | 数秒 | 0 | 0 | 0 |
| カメラのキタムラ（net-chuko） | 1（同上） | 数秒 | 0 | 0 | 0 |
| フジヤカメラ | 約44回の待ち（1回ごとに約90秒） | 約66分 | 0 | 17（used_s・新品同様） | 17 |

フジヤの値は検索結果のページ由来（link_type=search）なので、確定の売値には使わない（商品照合未了）。参考としては
17商品の「新品同様」の買取価格で、毎日の値として価値がある。

### 時間が長かった原因（実物で確認）

ローカルから1回だけ取得して確かめた（robots.txt 許可・90秒の間隔・正直な User-Agent）:
`networkidle` で開くと、ページは1回の取得で全部そろっている（「GR IV」「買取金額」がある）のに、広告・計測のタグの
通信が続くので25秒でタイムアウトする。以前はこのとき、90秒待ってから同じ URL をもう一度開いていた。CI では
2秒前後で失敗して開き直していた（理由は CI のログに残っていない）。1商品あたり、間隔の待ちが2回になっていた。

### 短縮（段階B。間隔90秒・robots・UA・打ち切りは変えない）

1. 1回だけ開く（`domcontentloaded` で開き、静まるのは通信を増やさない範囲で最大8秒だけ待つ）。開けなかったとき
   だけ、間隔をあけて開き直す（以前と同じ）。
2. 大文字・小文字・空白だけが違う検索語を重ねない（Leica M11 / LEICA M11。CI で同じ件数を確認）。
3. この実行で取得済みのページに、機種の厳密一致の買取価格があれば使い回す（「RICOH GR IV」の検索結果に GR IV HDF・
   GR IV Monochrome も載る）。選定は自分の検索のときと同じ `_select_camera_buyback`。実物の1ページで、使い回した
   値が CI でそれぞれの検索語で取った値と同じことを確認した（GR IV 151,000・HDF 194,000・Monochrome 194,000、
   すべて used_s）。

見込み: フジヤのリクエストは約44回 → 約19回、カメラのステップは約68分 → 約30分、CI 全体は約99分 → 約62分。
CI で「開けない」が続く場合は開き直しが残るので、実測で確かめる。

### 別のワークフローに分ける案・頻度を下げる案（評価のみ。実施しない）

- 分ける: カメラの買取は同じ実行の DB（CI の中で毎回作り直す）に書き、正規化・ルート・LP が読む。別のワークフローに
  すると、DB を保存して受け渡す仕組みが要る。上の短縮で十分に短くなる見込みなので、今は分けない。
- 頻度を下げる: 参考の値（新品同様）なので、毎日でなくてもよい可能性はある。ただし値が14日を過ぎると古い扱いに
  なる。前回の値を引き継ぐ仕組みが無いので、今は変えない（実測の後に判断する）。

## 6. 定時の実行の遅れ

Phase 11 で定時の実行が数時間遅れた。今回の定時の実行（37602159390）は、手動の実行（37599795597）が終わるまで
約79分待った（concurrency で待機）。CI が短くなれば、重なったときの待ちも短くなる。

## 7. 使われていないコード（整理の候補。削除はしていない）

- `src/collectors/price/mercari.py`・`src/collectors/price/ebay.py`: どこからも import されていない。
- `scripts/collect_resale_prices.py` の `MercariResaleCollector`・`RakumaResaleCollector`: skip の定数が True なので
  作られない。
- `config/sources.yaml` の src_mercari・src_rakuma・src_ebay の collector_module: 読む経路が無い。
- `src/orchestrator.py` の PRICE_SOURCES の src_mercari・src_yahoo_auction・src_ebay は、COLLECTOR_MAP に無いので
  以前から実行されていなかった。誤解を招くので名前だけ消した。

ファイルの削除は破壊的な変更なので、ユーザーの判断を待つ。

## 8. ユーザーの設定・判断が必要なこと

1. eBay の Marketplace Insights API の利用許可（eBay の審査）。
2. Secrets: `EBAY_CLIENT_ID`・`EBAY_CLIENT_SECRET`。
3. 成約を公開リポジトリに保存してよいか、eBay の API の利用規約で確認する。確認できたら
   Variables: `EBAY_INSIGHTS_APPROVED=true`・`EBAY_SOLD_LICENSE_CONFIRMED=true`・`ENABLE_EBAY_API=true`・`API_DRY_RUN=false`。
4. canary の報告を見て合格なら `EBAY_SOLD_CANARY=false`。その後 `EBAY_SOLD_STAGE` を 1 → 3 → 10。
