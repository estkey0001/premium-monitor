# Premium Monitor Completion Gap Analysis（2026-11-13）

方針転換（PRODUCT-FIRST → DISCOVERY-FIRST・「毎日せどりに使える」ことが最優先）を受けた、コード変更前の現状分析。
事実は 2026-11-12 の定時 run の公開データ（`exports/`）とコードの確認による。推測は「推定」と書く。

## 0. 結論（先に）

- **骨格は既にある。足りないのは「発見」と「売値の幅」と「利益が出る商品の数」。** 通知（outbox・dedupe・Telegram）・鮮度・同一性・UI・Phase24 は作り込み済みで、壊さず使える。
- **一番の欠落は P0（AI / Web 調査型の発見）。** 今の TCG の発見は「既定の 22 取得元の告知一覧を読む」だけ。取得元に載っていない抽選・予約は永久に見つからない。AI / 検索の層は**ゼロ**（`src` に LLM・検索 API の利用なし）。
- **次の欠落は P2 の売値。** 売値（買取）が確定している商品は 47 件中 15 件、成約（SOLD）は 0 件。TCG の売値（買取・二次流通）はほぼ空（`config/tcg_retail_prices.yaml` は空、`data/tcg_secondary_prices.csv` は手入力）。
- **結果として「今日の利益商品」が空。** 確定ルート 0 件（`profit_routes` の main_route_count=0）・確定の利益商品 1 件・今すぐ行動できる 0 件・抽選の受付中 0 件（`lottery_report`）。サイトの中心に置く素材が、今はほぼ無い。
- **開発凍結（2026-10-14〜）は、今回のユーザー指示で解除する扱い**（メモを更新する）。

## 1. 状態の語彙の対応（ユーザーの指定 ↔ 現在の実装）

| 指定 | 現在 | ギャップ |
|---|---|---|
| DISCOVERED | 調査候補 `status_counts.DISCOVERED`（9）・発見の候補 `exports/discovery/`（PENDING_REVIEW / REVIEW_REQUIRED など） | 語彙は近いが**2 系統**（research と discovery）に分かれ、統一されていない |
| VERIFIED | research の `VERIFIED`（1）・公式の確認済み（16 / 47） | 概念は有る。TCG のイベントには適用されていない |
| CONFIRMED | 「確定の利益」（`confirmed_opportunities`=1） | 名前は違うが同義 |
| ACTIONABLE | `src/market/actionability.py`（今すぐ行動できる=0） | 有る（正本） |
| MONITORED | 無い（登録 = REGISTERED のみ） | **MISSING**。登録後に自動で価格取得に入る道が人手 |

→ 新しい状態機械を作らず、**既存の 2 系統を 1 本の `stage`（DISCOVERED → RESEARCH_CANDIDATE → VERIFIED → MONITORED → CONFIRMED → ACTIONABLE）に写像する薄い層**を足す方針（後述）。

## 2. Phase 別ギャップ

判定は DONE / PARTIAL / MISSING。

### P0 Market Discovery Engine

| 項目 | 判定 | 現状 | 必要 |
|---|---|---|---|
| 取得元の告知一覧から抽選を発見 | DONE | 22 取得元・11 実装・稼働 9（`collect_tcg_events`）。抽選イベント 19 件を発見、うち受付中 0 | — |
| 商品が未登録でも候補化 | PARTIAL | `src/discovery/tcg.py`（246 行）が日程の無い告知・予約・先着・再販のタイトルを `ANNOUNCEMENT_REVIEW_REQUIRED` 候補にする。**ただし入力は既存取得元の生成物だけ**。候補はイベント 127 件・商品 43 件 | 取得元に無いものを見つける**独立の発見経路** |
| AI / Web 調査型の発見 | **MISSING** | 無い | 検索 → 抽出 → 公式 URL の検証 → 候補化 |
| 検索対象（メーカー公式・量販店・カードショップ・EC・公式ニュース） | PARTIAL | 公式ニュース（ポケカ公式・ONE PIECE 公式）・量販店の一部。到達不能 / 遮断が 9 件（robots・403・タイムアウト）。11 件は未実装 | 検索 AI が見つけた**未知の取得元の URL** を扱う入口 |
| 抽出項目（商品名・店・種別・応募開始・締切・当選発表・購入期間・価格・条件・公式 URL） | PARTIAL | `src/tcg/models.py`・`lottery/` に項目は揃うが、日程が無い告知は空のまま（推測しない設計） | 抽出の出力契約（根拠の文と URL を各項目に付ける） |
| 検証（AI の回答だけで確定しない） | PARTIAL | 応募 URL は取得元の公式ドメインの https だけ（`action_url.py`）。human_confirmed の仕組みもある | AI が出した URL を `polite.py` で取り直して**一次情報で裏取り**する関門 |
| 重複排除（商品 × 店 × 種別 × 期間） | DONE | `src/tcg/dedupe.py`・`cluster.py`・lottery pipeline の `normalize_url`。重複は 0 | AI 発見分も同じ鍵に載せる |
| 受入ベンチマーク（precision / recall / 重複率 / 古さ / 公式率 / 締切の正しさ） | **MISSING** | 計測なし。`detection_delay`（検知の遅れ）の測定はあるが 0 件測定 | 正解表（人が出す「今日の抽選」）との突き合わせ |

**P0 の最大の論点（ユーザーの判断が要る）**: AI 検索を CI で回すには LLM / 検索の API と **Secret（API キー）と費用**が要る。禁止事項「取得は `polite.py` を通す・検索結果の HTML をスクレイピングしない（公式 API だけ）」とは、**検索は公式 API・ページの取得は `polite.py`** と分ければ両立する。

### P1 Automatic Product Onboarding

| 項目 | 判定 | 現状 | 必要 |
|---|---|---|---|
| DISCOVERED → RESEARCH_CANDIDATE | DONE | `src/research/candidates.py`（調査候補）・買取起点の候補 595 件 | — |
| → VERIFIED | PARTIAL | 公式の確認済み 16 / 47。Apple 以外は人が公式ページを見て登録（Wave 7c-2 など） | TCG の商品・イベントの検証の自動化 |
| → MONITORED | **MISSING** | 登録（`register-product-candidate`）は人が 1 件ずつ・dry-run 既定・`--confirm` | 低リスクな項目だけ自動で監視対象へ |
| 自動で許す項目（ジャンル・正規化名・店・公式 URL・イベント情報・別名候補） | PARTIAL | 抽出はあるが、正本（`config/products.yaml`）への書き込みは人 | TCG イベントは**正本に入れず**イベント台帳（候補）に自動で入れる |
| 人のレビュー必須（JAN・容量・色・バンドル・世代・型番・部品番号・公式価格・送料） | DONE | 証拠が足りなければ確定しない。この安全側は維持 | — |

### P2 Buy / Sell Price Engine

| 項目 | 判定 | 現状 | 必要 |
|---|---|---|---|
| 買い（公式） | PARTIAL | 公式の確認済み 16 / 47。Sony は parser の失敗（A7RV）・Fujifilm は CI で 403 | 取得できる取得元の優先・対象の拡大 |
| 買い（小売） | PARTIAL | 小売の価格の照会（ニコンダイレクト・ソニーストア・Samsung・Apple）。Canon・Samsung は規約の確認待ち | 規約の確認が済んだ取得元から |
| 買い（二次流通） | MISSING | 成約・中古の API（eBay Marketplace Insights）は承認待ち（PENDING_USER_CONFIGURATION）。メルカリ・ヤフオク等は禁止 | 公式 API だけ |
| 売り（買取） | PARTIAL | 買取は 773 行の台帳・確定 15 / 47。**買取商店 1 つ（`kaitori_shouten`）への依存が大きい**（HANDOFF）。ゲオ・ドスパラ・ハードオフ等は robots 禁止や HTTP エラー（本日のログ） | 取得できる別の取得元を増やす（遮断の回避はしない） |
| 売り（SOLD） | MISSING | `marketplace_sold_coverage.valid_sold_rows = 0` | 公式 API の承認後 |
| TCG の買う・売る | MISSING | TCG は利益・今すぐ行動・通知に**意図的に未接続**。定価 `tcg_retail_prices.yaml` は空・二次流通は手入力 CSV | TCG の定価（公式）と買取・成約の取得元 |

### P3 Opportunity Engine

| 項目 | 判定 | 現状 | 必要 |
|---|---|---|---|
| 利益の式（買値・購入送料・手数料・発送・その他） | DONE | `src/market/profit_formula.py` が正本。購入送料が分からなければ確定にしない | 式は触らない |
| BUY / WATCH / WAIT / SKIP | PARTIAL | UI の語は BUY / WAIT / SKIP（`status.py`）。WATCH は利用者向けの通知の種類（WATCH_TO_BUY）にはあるが、状態の一覧では未対応 | 4 値の判定を 1 か所に（閾値は既存を維持） |
| ROI | DONE | 計算あり | — |
| 閾値 | DONE | `config/scoring_rules.yaml` 等。変更しない | — |
| 利益商品の実数 | **PARTIAL（実質ほぼ空）** | 確定ルート 0・確定の利益商品 1・行動可能 0 | 数を増やすのは P2（売値の幅）で決まる |

### P4 Event / Price Notification

| 項目 | 判定 | 現状 | 必要 |
|---|---|---|---|
| exactly-once・dedupe・outbox | DONE | Phase 19〜26。Telegram は接続試験で 1 件送信済み・商品の通知は受入待ち（PHASE24_WAITING） | 壊さない |
| NEW LOTTERY / LOTTERY ENDING | PARTIAL | 抽選の通知の仕組み（`lottery_notifications`）あり。受付中が 0 のため実績が少ない | P0 で件数が増えたあとに検証 |
| PREORDER OPEN / RESTOCK | PARTIAL | RESTOCK は計画あり（restocks 0 件） | 予約の種別を P0 の抽出に含める |
| BUY OPPORTUNITY / WATCH→BUY / NET PROFIT / ROI | DONE（仕組み） | ACTIONABLE_NOW（dry-run の計画まで）・利用者向けの種類あり | 本番の送信は**ユーザーの許可が別途必要**（変えない） |
| BUYBACK PRICE SURGE | PARTIAL | `signals.momentum()`（前回の台帳を引き継げた日だけ）。通知には未接続 | 通知の種類に追加するだけ |

### P5 Website Completion

| 項目 | 判定 | 現状 | 必要 |
|---|---|---|---|
| HOME 上部（今日の利益商品・抽選・在庫復活・買取急騰） | PARTIAL | `src/content/ui/home.py` は BUY / WAIT / SKIP のカードを出す。抽選・在庫（`lottery_page`・`restock_page`）は別ページ | HOME に 4 区画を集約。**データが空のときの見せ方**を先に決める |
| OPPORTUNITY CARD（商品・買う場所・仕入・売る場所・売値・純利益・ROI・更新日時・在庫・状態） | PARTIAL | `opportunity.py` に大半あり | 項目の欠けを確認して揃える |
| LOTTERY カード（店・応募状態・締切・価格・条件・当選・購入期限・公式 URL） | PARTIAL | `lottery_card.py`。当選・購入期限は取得元が出す場合のみ | P0 の抽出項目と対応させる |
| スマホ優先 | PARTIAL | 狭い viewport のテストあり（Wave 7e-3 で 500px の欠陥を修正）。「数秒で今何を買うか分かる」の検証はまだ | 実機相当の確認 |

## 3. 最短で完成へ向かう実装計画

優先順位の根拠: **売値の取得元を増やすより先に、「見つけたものが画面に出る」道を通す**（P0 → P5 を薄く縦に貫く）。TCG は利益計算に使わず「抽選・予約」として先に価値を出せる（定価・買取が空でも成立する）。

| 段階 | 内容 | 規模の見込み | 依存・判断 |
|---|---|---|---|
| **P0-a**（最優先） | 発見の出力契約と検証関門。AI の出力は DISCOVERED の「主張」（根拠の文・URL・取得日時つき）として受け、**公式ドメインの URL を `polite.py` で取り直して日程・商品名が一致したときだけ VERIFIED**。AI 調査の入口はアダプタ 1 つ（検索 API は差し替え可能）。既存の dedupe の鍵に載せる | 中（新規 ~600〜900 行 + テスト） | **API の種類・キー・費用はユーザーの判断**（下記） |
| **P0-b** | 受入ベンチ。人が出した「今日のポケカ抽選」の正解表（YAML）と、Premium Monitor の出力を突き合わせて precision / recall / 重複率 / 古さ / 公式率 / 締切の正しさを出す | 小〜中 | **正解表は人が用意**（Muse 等の結果の貼り付けで可） |
| **P1-a** | イベント台帳に VERIFIED の TCG イベントを自動投入（正本の `config/products.yaml` には入れない）。`stage` の写像層を追加（既存の 2 系統を壊さない） | 小〜中 | — |
| **P5-a** | HOME 上部の 4 区画（今日の利益・抽選予約・在庫復活・買取急騰）と、空のときの見せ方。P0 の VERIFIED が出たらすぐ画面に出る | 中 | — |
| **P4-a** | NEW LOTTERY / LOTTERY ENDING / PREORDER OPEN を、既存の outbox・dedupe に載せる（dry-run まで。本番送信は別許可） | 小 | 送信は許可制のまま |
| **P2-a** | 買取の取得元の分散（取得できる取得元の追加）。遮断の回避はしない。TCG の定価（公式）の自動取得 | 大（取得元ごと）。**サイトごとの parser を先に大量実装しない**方針に従い、P0 の結果で必要な取得元に絞る | 規約・robots の確認 |
| **P3-a** | 4 値（BUY/WATCH/WAIT/SKIP）の判定を 1 か所に。閾値は変えない | 小 | — |
| **P2-b** | 成約（SOLD）の公式 API | 承認待ち | 外部の承認 |

停止・統合する既存の作業（提案）:
- **Phase31・7e-2・7c-3・7d・Product Registration Foundation は個別には進めない。** 中身は P1 / P2 に統合する。
- 監査・観測性の追加 Wave は、本番の誤り（誤価格・fake freshness・identity mismatch・秘密の漏れ・外部送信の事故）以外では新設しない。
- CI Canary（7e-3）は維持（手動のみ・費用ゼロ）。

## 4. 決める必要があること（ユーザーの判断）

1. **P0 の AI 調査に使う API**: 検索付きの LLM API（例: Anthropic の API の Web 検索ツール）を使うなら、API キーを GitHub Secrets に置く必要がある。費用が発生する。キーは私が作れない・入れられない（ユーザー作業）。
   - 代案（キー不要）: ローカルで私が検索して候補を YAML に書き、CI は検証だけ行う。毎日自動にはならない。
2. **実行の場所**: 発見は GitHub Actions の定時 run に載せるか（毎日 1 回・約 1 時間 45 分の run がさらに延びる）、別の workflow に分けるか。推奨は別 workflow（本番の定時を遅らせない）。
3. **正解表の用意**: P0-b の受入に、人が出した「今日のポケカ抽選情報」（Muse 等の回答の貼り付け）が必要。
4. **外部送信**: 通知の本番送信（Telegram の商品通知）は、これまでどおりユーザーの許可を別に取る。

## 5. 守るもの（変えない）

利益の式・閾値・鮮度の規則（値が変わらないのに日時だけ更新しない）・同一性の関門・`polite.py` 経由の取得・outbox の exactly-once・Phase24 / 26 の受入の関門・公開データに秘密と個人情報を出さない。
**DISCOVERED は表示してよいが、利益計算・BUY・通知には VERIFIED / CONFIRMED / ACTIONABLE だけが進む。**
