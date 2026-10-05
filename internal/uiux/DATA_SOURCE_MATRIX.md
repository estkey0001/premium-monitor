# データソース一覧（2026-10-02 時点）

> **位置づけ（2026-10-03 更新）**: 2026-10-02 時点の一覧。Phase 0.2 でヤフオクの行を訂正した（落札ではなく出品中の一覧）。価格の種別の正本は `src/market/price_types.py`。

詳しい根拠は DATA_CAPABILITY_AUDIT.md にある。件数は CI run 36949841607（2026-10-02 11:37 JST）の生成物から数えた。
Frequency の「1日1回」は GitHub Actions の 12:00 JST の定時実行を指す（手動実行も可）。

## 1. データの種類ごと

| Data | Source | Method | Frequency | Current Coverage | Match Quality | Failure Behavior |
|---|---|---|---|---|---|---|
| Retail（公式定価） | RICOH 公式 HTML / Apple は `audit_official_sources.py` の固定値 / `config/products.yaml` の手入力定価 / 手動の販売 CSV | requests でスクレイピング、直書きの辞書、手動 CSV | 1日1回 | 45商品のうち Web から実際に取れているのは4件（RICOH）。Apple の9件は固定値、32件は yaml の定価。Canon / Nikon / Sony は動いていない | **低**。GR IV 系の3商品が同じ価格。Apple の容量の割り当ても曖昧 | スキップして続行する。ただし固定値や yaml の定価に毎回「今」の日時が付き、新しく見える |
| Stock（在庫） | ヨドバシ / ビックの collector（CI では動いていない）、公式ページの在庫の文言、TCG は公式ニュースと CSV | HTML の文言判定 | 量販店は常駐スケジューラだけ（本番では動いていない）。TCG は1日1回 | 一般商品は 0件。TCG の再入荷も 0件 | **低**。予約を在庫ありと扱う。Apple は常に在庫あり。RICOH は不明を在庫ありにする | TCG は TTL で ENDED / UNVERIFIED に下げる。一般商品には判定の仕組みが無い |
| Buyback（買取） | 携帯・ゲーム機は16店、カメラは3店（フジヤ / マップカメラ / キタムラ）、手動 CSV | requests / Playwright とキーワード・正規表現。状態は設定値。1店1価格 | 1日1回 | 携帯・ゲーム機は 13/55 が OK。カメラは 20/60 が OK（全件フジヤ）。正規化後に使えるのは 11/143 | **低**。買取商店の ¥435,000 / ¥900,000、フジヤの下取り価格と限定版への誤マッチが、公開 LP に出ている | price=0 と fetch_failed で記録し、前回の値は引き継がない。観測時刻は「失敗した時刻」になる。疑わしい価格を検出しても LP は公開される |
| Secondary Listing（出品） | メルカリ（出品中）、ラクマ、楽天、Amazon、手動 CSV | HTML / Playwright の検索結果の中央値。最安値・最高値・件数は保存しない | 1日1回 | 今日は Amazon が一部だけ。メルカリとラクマは blocked、楽天は失敗。手動分はすべて stale（8/12〜8/22） | **低**。タイトル照合が無い。状態の推定が機能していない。比較の段階で成約価格や中古販売価格と混ぜて最大値を取る | 状態を status JSON に記録して続行する |
| Secondary Sold（成約） | ~~ヤフオク落札（自動 HTML）~~ → **出品中の一覧だった（Phase 0.2 で訂正。今は LISTING として保存）**、手動 CSV（メルカリ / ヤフオク。URL はダミーで成約日時なし → 成約に使わない）、eBay（API 未設定・手動のみ） | 自動で取れる成約は0件。手動は CSV（以下の列は 2026-10-02 時点の記録） | 1日1回。手動は不定期（最後は 8/22） | 有効なのはヤフオクの5件（カメラ）だけ。メルカリ 0、ラクマ 0（NOT_IMPLEMENTED）、eBay 0 | **低〜中**。タイトル照合が無い（Pro と Pro Max が同額）。成約日が無い。手動 CSV の URL はダミー。eBay の成約価格が出品扱いになっている | 14日を超えたら除外し、成約データ 0件のまま LP を更新する |
| Lottery（抽選） | TCG: PCO（手動確認）・GEO（HTML）ほか 17 source の registry。旧来の抽選: `data/lottery_events.csv` | HTML と手動 CSV。状態は `compute_lottery_status`。新UIは閲覧時に判定し直す | 1日1回（新UIは閲覧中も判定し直す） | TCG 6件（PCO の2件は受付中・確認待ち、GEO の4件は終了）。旧来の抽選 8件（すべて終了） | **中〜高**（公式ドメイン・人による確認・日程の食い違いの判定あり）。旧来の抽選の RICOH の定価は固定値 | 失敗した source は監視状況に出し、前回の行は残す。PCO は 403 のため手動 |
| Reservation（予約） | TCG の event_type=PREORDER だけ | 分類だけで、予約開始日の専用項目は無い | 1日1回 | TCG 以外は **NOT_IMPLEMENTED** | — | — |
| Release information（発売・公式発表） | ポケモン公式の商品 API、ONE PIECE 公式の商品ページ / TCG 以外は `new_product_watchlist.yaml`（手動・推測） | API / HTML と手動の yaml | TCG は1日1回。watchlist は手動（CI の外） | TCG は21商品、イベント13件（COMING_SOON 11）。TCG 以外は **NOT_IMPLEMENTED** | TCG は高（推測で埋めない）。watchlist は推測値で、予定日も過ぎている | TCG は日付が分からなければ None / UNVERIFIED。watchlist は推測値を official_price に保存する（LP には出ていない） |

## 2. 鮮度（source ごと）

| Source | 最終成功の記録 | TTL / stale のしきい値 | 実装箇所 | 失敗時の動き |
|---|---|---|---|---|
| 買取（自動） | 行ごとの observed_at と `exports/collector_report/latest.json` | 表示は 24h / 48h。利益判定は 7日で要更新、14日で除外 | `daily_lp_generator.py:6680-6735, 6974-7024` | price=0 で記録。観測時刻が「最終更新」に混ざる（`repository.py:1146-1155`） |
| 手動 CSV（買取・相場・販売・成約） | CSV の observed_at（最新は 8/22） | 14日（`normalized_prices.py:20`） | 同上 | 値を変えずに時刻だけ新しくした前例がある（commit `c214ea40`） |
| カメラの買取 | `exports/camera_buyback_status.json` | 買取と同じ | `update_camera_buyback.py` | 手動の確認データに切り替える |
| 公式定価 | `product_source_config.last_verified_at` | なし | `normalized_prices.py:280-296` | 正規化の段階で観測時刻が常に「今」になる |
| 海外 | `exports/overseas_prices/latest.json` の fetched_at | 48h | `src/collectors/overseas/base_overseas.py:12,87-95` | stale でも選ばれる（`overseas/orchestrator.py:111-132`） |
| 二次流通 | sale_prices.observed_at（取得時刻） | 14日 | `normalized_prices.py` | 取れた行だけ更新する |
| TCG | `exports/tcg/latest.json` の source_health（last_checked / last_success） | ゲリラ 30分、店頭 2h、EC 15分、コンビニ 2h。抽選・予約は締切まで | `src/tcg/freshness.py:24-157` | 空の payload で続行する（前回のイベントは引き継がない） |
| 抽選（旧来） | `data/lottery_events.csv` の checked_at | 締切の日時 | `_lottery_status_from_dates` | 前回の行を残す |

## 3. 新UIが使ってよいもの・使ってはいけないもの

| 値 | 新UIでの扱い |
|---|---|
| 抽選の状態・日時・公式 URL | 使ってよい（runtime で閲覧時に判定し直す） |
| TCG の発売日・定価（verified のもの） | 使ってよい。未確認の値は「未定」「未発表」と表示する |
| 公式定価（`official_price`） | **今は使ってはいけない**。E4・E5 が直るまでは「定価（参考）」として、確認日を付けずに出すだけにする |
| 買取価格 | **今は「おすすめ」に使ってはいけない**。E1〜E3 が直るまでは、疑わしい価格と使用不可の価格を一覧に出さない |
| 出品価格 | 「出品最安値」として出してよいが、今は保存されていない（中央値1つだけ）。**売値の代わりに使ってはいけない** |
| 成約中央値 | 有効なデータがほぼ無い。期間・件数が無いものは「成約価格 未取得」とする |
| 在庫 / 再入荷 | 一般商品は「未取得」。TCG は TTL を閲覧時に判定し直すまでは、「今買える」を出さない |
| 予約・発売予定（TCG 以外） | 「未取得」。watchlist の推測値は使ってはいけない |

## 4. 抽選・予約（UI Phase 3。2026-10-03 時点）

件数は CI run 37102875219（2026-10-03 16:54 JST）の生成物から数えた。新UIの表示モデルは `src/content/ui/lottery_view.py`、
状態の判定は runtime（`runtime.derive_runtime_state` / `lottery_runtime.js`）だけ。

| Source | Category | Method | Frequency | Coverage | Last Success | Blocked | Manual fallback |
|---|---|---|---|---|---|---|---|
| ポケモンセンターオンライン | TCG | 公式ニュース一覧のリンクから発見（`pco_lottery`） | 1日1回 | 受付中2件（手動転記・確認待ち） | 10/03 16:16 | **403**（回避しない） | `data/tcg_verified_lotteries.csv`（人の確認待ちは応募ボタンなし） |
| ポケモンカード公式（ニュース・商品） | TCG | 公式ニュース・商品 API | 1日1回 | 抽選0件。発売予定9件（発売日・商品1点の価格あり） | 10/03 16:17 | なし | — |
| GEO | TCG | HTML（`geo_lottery`） | 1日1回 | 4件（すべて受付終了） | 10/03 16:17 | なし | — |
| ローソン / ONE PIECE 公式 / プレミアムバンダイ | TCG | HTML・公式ニュース | 1日1回 | 0件 | 10/03 16:23〜24 | なし | — |
| トイザらス / Joshin / ヨドバシ | TCG | 未実装 | — | — | — | **403・ブロック** | なし |
| ヤマダ / ビック | TCG | 未実装 | — | — | — | 到達不可 | なし |
| エディオン / TSUTAYA / Amazon / 楽天ブックス / セブンネット / ONE PIECE 公式ショップ | TCG | 未実装（告知一覧を発見できず） | — | — | — | なし | なし |
| RICOH 公式ストア | カメラ | 商品ページの HTML（`update_lottery_events.py`） | 1日1回 | 3件（すべて受付終了） | 10/03 16:09 | なし | — |
| Sony Store / My Nintendo Store | ゲーム | 商品ページの HTML | 1日1回 | 5件（すべて受付終了。日程なし） | 10/03 16:09 | なし | — |
| （なし） | スマホ・PC | **NOT_IMPLEMENTED** | — | — | — | — | — |

新UIでの扱い:
- 「応募する」「予約する」は公式ドメインの https・受付中・人の確認済み・日程の食い違いなし、のときだけ。締切の時刻で runtime が消す
- 旧来の抽選（公式ストア）の価格は読み取りに誤りがある（GR IV Monochrome: CSV ¥283,800 / 本文の抜粋「定価 ¥299,800」）ので使わず、
  同じ商品の確認済みの定価（利益商品の仕入れ値）があるときだけ出す
- 発売予定は公式の https のページで、年月日が読めるものだけ。発売日の 0 時を過ぎたら一覧から外す（在庫は確認していない）
- 予約・発売待ち・抽選を在庫ありとは扱わない

### 更新頻度（推奨。本番のスケジュールは変えていない）

| 用途 | 推奨 | 今 | runtime で足りるか |
|---|---|---|---|
| 新しい抽選の発見 | 30〜60分ごと | 1日1回 | **足りない**（collector の実行が必要） |
| 締切・開始の監視 | 15〜30分ごと | 1日1回 | **足りる**（既知の開始・締切は閲覧時に判定し直す。ボタンも締切で消える） |
| 予約開始・条件の変更 | 30〜60分ごと | 1日1回 | 足りない（collector の実行が必要） |
| 発売情報 | 数時間〜1日 | 1日1回 | 足りる（発売日は既知） |
| 在庫の開始（店頭・EC） | 15〜30分ごと | 1日1回 | 足りない（Phase 4 の在庫再開で扱う） |

## 5. 在庫再開（UI Phase 4。2026-10-03 時点）

在庫の状態の正本は `src/market/stock_state.py`（IN_STOCK / OUT_OF_STOCK / UNKNOWN / RESERVATION / LOTTERY / PREORDER /
RELEASE_WAIT）。状態の変化は `src/market/stock_history.py` が `exports/stock_history/latest.json` に残す（CI の DB は毎回
作り直されるため）。新UIは `restock_view.py` / `restock_page.py`。

| Source | Category | Method | Frequency | Stock field | Coverage |
|---|---|---|---|---|---|
| 公式ストア（RICOH / Apple / 汎用） | カメラ・スマホ・ゲーム | 商品ページの在庫表示（明示があるときだけ） | 1日1回 | `official_stock_status` + `official_stock_observed_at`（価格の時刻とは別） | 在庫ありを確認できる商品は今0件。RICOH は抽選・SOLD OUT の表示 |
| 人が公式ページで確認した在庫 | ゲーム（PS5 Pro） | `audit_official_sources.VERIFIED_URLS` の stock / stock_checked_at | 確認したとき | 同上 | 1件（入荷待ち） |
| TCG の販売・入荷情報 | TCG | 公式・販売店のニュース・商品ページ（AVAILABLE_NOW / SOLD_OUT） | 1日1回 | events の status・observed_at | 今買える 0件。発売予定 13件（抽選・予約のページで扱う） |
| 量販店の在庫（ヨドバシ / ビック） | 全般 | collector はあるが CI では動いていない | — | — | **NOT_IMPLEMENTED（本番）** |

購入可能の条件: 在庫あり・確認から `stock_state.freshness_seconds`（公式ストア・人の確認 3時間 / TCG は既存の TTL:
EC 在庫復活 15分・店頭 2時間ほか）以内・公式（承認済み）の https の販売ページ・商品の特定。ブラウザでも閲覧時の時刻で判定し直す。

### 更新頻度（推奨。本番のスケジュールは変えていない）

| 用途 | 推奨 | 今 |
|---|---|---|
| 高需要の在庫（TCG の EC・人気のゲーム機） | 15〜30分ごと | 1日1回 |
| 一般の EC（公式ストア） | 30〜120分ごと | 1日1回 |
| TCG の入荷・先着 | 15〜30分ごと | 1日1回 |
| 公式定価 | 1日〜週 | 1日1回 |

抽選と違い、**新しい在庫の復活はブラウザの runtime では検出できない**（collector が取得するまで分からない）。
runtime ができるのは、既知の在庫ありの観測を期限で「更新待ち」に落とすことだけ。

## 6. せどりルート（UI Phase 5。2026-10-04 時点）

確定ルートは `src/content/ui/route_view.py`（RouteView）。判定は利益商品と同じ `opportunity.eligibility` に、
ルートの条件 `opportunity.route_identity_reasons` を足したもの。

| 条件 | 内容 |
|---|---|
| 売値 | 買取価格か、成約中央値（件数3以上・集計期間の開始と終了あり） |
| 商品の同一性 | 仕入れ・売却とも `is_exact_product_match`（正規化データの照合）が True |
| 仕入れ先の URL | 二次流通で買う場合は商品ページ単位の URL（`price_types.is_item_url`。検索結果・カテゴリ・トップ・ダミーは不可）。正規店の新品は link_type=item |
| 状態 | 系統が同じ（新品・未使用・開封済み・中古・TCG の各状態を混ぜない。不明は不可） |
| 費用 | 購入送料・販売手数料・発送・その他がすべて分かる（項目が無ければ算出前。0円とみなさない） |
| 鮮度 | 仕入れ・売却とも確認から14日以内 |

2026-10-04 時点の生成物: 候補1件（RICOH GR IV: Amazon の検索結果の出品 ¥107,491 → フジヤ買取）。
商品の照合が未了（`unverified_title_price_band_pending`）・検索結果の価格で、Phase 2 の判定では確定になり本番に出ていた。
Phase 5 で確定から外した。成約データ（Yahoo / eBay / メルカリ / ラクマ）は有効0件のまま。

**Phase 5.1（2026-10-04）**: 旧UI（通常の URL）も同じ判定を使う。入口は `opportunity.route_reasons` /
`reference_route_reasons` / `confirmed_routes` / `deal_reasons`。`generate_profit_routes.py` は判定を通らないルートを
`main_routes` に入れず `excluded_routes`（理由つき）に分ける。旧UIのせどりタブ・AI Opportunities・通知・HOME の件数も同じ入口を通す。
定価→買取の案件は旧UIの生成時に `deal_reasons` を通し、確定以外は監視中へ降格（定価の根拠だけ未確認のものは「参考差額」として残すが、
ランキング・Hero・初心者ルート一覧には出さない）。

**Phase 5.2（2026-10-05）**: 利益ルートには `route_id`（`opportunity.route_key`）を付け、AI Opportunities・資金配分・実行履歴・通知に
引き継ぐ。表示・生成の側は今の確定・参考ルートと `route_id` で照合する（商品単位で照合しない）。公式の購入送料は
`src/market/official_shipping.py`（一次情報の URL・確認日つき。分からなければ確定にしない）。

**Phase 6（2026-10-05）**: 商品詳細（`product_detail.py`）は、上の正本のビューと正規化データだけを使う。価格の履歴は
`exports/price_history/latest.json`（実際に観測した値だけ。2026-10-05 から蓄積。それより前は無い）。
利益・ROI・取得原価・利益の根拠の内訳は OpportunityView の値のまま（再計算しない）。仕入価格の確認時刻は正規化データの公式の観測の確認日。

出品価格の参考（`ListingRef`）は、価格の種別が出品のもの（`*_listing_price` / LISTING）を商品×市場ごとに最新1件。
最安・最高は保存していないので「未取得」。利益・ROI は出さず、件数にも数えない。
