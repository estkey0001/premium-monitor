# 新UIの ViewModel 仕様（案・2026-10-02）

> **位置づけ（2026-10-03）**: 新UIの現在の仕様（正本）。価格の種別は `src/market/price_types.py`、価格の根拠は `src/market/price_evidence.py` と一致させる。

新UIは、collector や DB の形を直接見ない。exports と DB から**表示用の写し（ViewModel）を作る層**を1つ置き、画面はその写しだけを使う。
抽選で使っている runtime.py の VM と同じ考え方を、ほかの画面にも広げる。

```
collectors / DB / exports  →  adapter（変換・検証。ここだけが元データを読む）  →  ViewModel（JSON）  →  画面（Python で HTML を作り、JS で閲覧時に判定し直す）
```

- adapter は元データを変えない（読むだけ）。
- ViewModel は JSON にして、`<script type="application/json">` に埋め込む（抽選の nu-lot-data と同じ）。
- 時刻で変わる判定（締切・TTL・鮮度）は、抽選と同じく Python と JS の両方に同じ関数を置き、固定時刻のテストで一致を確かめる。

## 1. 共通の型

### 1.1 Money（金額）

```
Money = {
  "amount": int | null,          # 円。null は「無い」
  "state":  "OK" | "NOT_COLLECTED" | "UNPUBLISHED" | "INVALID" | "STALE" | "CONFIRMING"
}
```

| state | 表示 | 使う場面 |
|---|---|---|
| OK | ¥123,400 | 検証を通った値 |
| NOT_COLLECTED | 未取得 | 取得の仕組みが無い・失敗した |
| UNPUBLISHED | 未発表 | 公式がまだ発表していない（推測で埋めない） |
| INVALID | 価格確認中 | 0円・負・非有限、疑わしい価格（suspicious）、使用不可（usable=false） |
| STALE | ¥123,400（更新遅延） | しきい値を超えて古い。金額は出すが、利益計算には使わない |
| CONFIRMING | 確認中 | 人による確認待ち |

### 1.2 PriceRef（どこの・どの種類の価格か）

```
PriceRef = {
  "money": Money,
  "price_type": "RETAIL" | "BUYBACK_CASH" | "TRADE_IN" | "LISTING" | "SOLD" | "SOLD_MEDIAN"
              | "CONFIGURED_REFERENCE" | "UNKNOWN",   # 正本は src/market/price_types.py
  "source_id": str, "source_name": str,
  "url": str,                     # https で、検証を通ったものだけ。無ければ ""
  "condition": "NEW_UNOPENED" | "NEW_OPENED" | "USED_A" | "USED_B" | "USED_C" | "UNKNOWN",
  "observed_at": str,             # ISO。元データの観測時刻（生成時刻で上書きしない）
  "verified_at": str,             # 人が確認した日（固定の定価など）。無ければ ""
  "evidence": "VERIFIED_CURRENT" | "VERIFIED_DATED" | "CONFIGURED_REFERENCE" | "STALE" | "UNKNOWN",
  "sold_at": str,                 # SOLD のときだけ。成約日時（無ければ期間集計に使えない）
  "sample_count": int | null,     # 集計値の件数（SOLD_MEDIAN は成約の件数、LISTING は出品の件数）
  "period_start": str, "period_end": str,   # SOLD_MEDIAN のときだけ（集計期間）
  "listing_min": Money | null, "listing_max": Money | null, "listing_median": Money | null   # LISTING のときだけ
}
```

`price_type`（価格の種別。`src/market/price_types.py`。2026-10-03 Phase 0.2）:

| 値 | 意味 | 一般向けの呼び方 |
|---|---|---|
| `RETAIL` | 定価・小売店の販売価格 | 定価 / 販売価格 |
| `BUYBACK_CASH` | 買取店の現金買取価格 | 買取価格 |
| `TRADE_IN` | 下取り価格（現金買取ではない） | 下取り価格 |
| `LISTING` | 出品中の希望価格（売れた価格ではない） | 出品価格（市場参考価格） |
| `SOLD` | 実際に成約・落札した1件の価格 | 成約価格 |
| `SOLD_MEDIAN` | 同じ商品の成約を期間で集計した中央値 | 成約価格（中央値・N件・期間） |
| `CONFIGURED_REFERENCE` | 設定値の参考価格（確認日不明） | 参考価格 |
| `UNKNOWN` | 種別が分からない（種別が記録されていない過去のデータを含む） | — |

- **出品価格を「sold」「落札」「成約」と呼ばない。** 出品の中央値を成約の中央値として扱わない。最高出品価格を「売れる価格」として扱わない。「市場価格」だけで済ませず、出品か成約かを書く。
- **SOLD は1件ごとの根拠が必要**: 1件の商品ページの URL（ダミー・検索結果の URL は不可）と成約日時（`price_types.has_sold_evidence`）。根拠の無い値は、名前に「落札」「sold」とあっても SOLD にしない。
- **種別が記録されていない過去のデータは UNKNOWN**。推測で SOLD にしない（`sale_prices.price_type` の既定値も UNKNOWN）。
- **SOLD_MEDIAN**（`price_types.sold_median`）: 同じ商品（容量・型まで同じ identity）・condition が互換・根拠のある SOLD・成約日時が集計期間内、の標本だけで計算する。出力は median / min / max / sample_count / period_start / period_end。
  件数が `MIN_SOLD_SAMPLES`（3件）未満なら `insufficient_samples` で、確定利益に使わない。
- **LISTING の集計**（`price_types.listing_stats`）: minimum_listing / maximum_listing / median_listing / listing_count。成約の中央値とは別の項目にする（listing median ≠ sold median）。
- **確定利益の売値に使えるのは `BUYBACK_CASH` と、条件を満たした `SOLD_MEDIAN` だけ**（`price_types.CONFIRMED_SELL_TYPES`）。正規→二次・二次→二次のどちらでも同じ。
  LISTING は市場参考として出してよいが、確定利益・BUY・TOP10・高利益には使わない（新UIは `home.sell_type_reject_reason`）。
- 成約データが0件なら「成約価格 未取得」「想定利益 算出前」と出す。出品価格で埋めない。

`evidence`（価格の根拠。`src/market/price_evidence.py`。2026-10-02 Phase 0.1）:

| 値 | 意味 |
|---|---|
| `VERIFIED_CURRENT` | 実際に取得・確認した値で、確認から7日以内 |
| `VERIFIED_DATED` | 確認日がある値で、180日以内（固定の定価を確認した日など） |
| `CONFIGURED_REFERENCE` | 設定値（`config/products.yaml` の定価など）。確認日が分からない |
| `STALE` | 確認日はあるが古すぎる |
| `UNKNOWN` | 価格が無い・日時が読めない・根拠の項目が無い |

既存の `freshness_basis` は `price_evidence.from_freshness_basis` で読み替える（`observed`＝取得から14日以内 → VERIFIED_CURRENT、
`verified`＝確認日から180日以内 → VERIFIED_DATED）。確認日から直接分類するとき（`classify_dated_price`）は7日で CURRENT と DATED を分ける。
どちらも「今狙える利益」に使ってよい区分なので、表示の可否は変わらない。
利益ルート（`exports/profit_routes`）と AI Opportunities には `buy_price_evidence` / `sell_price_evidence` が入る。

ルール:
- `LISTING`（出品）は**売値に使わない**。表示するのは「出品最安値」「出品最高値」として。
- `SOLD_MEDIAN` は、`period_start` / `period_end` と `sample_count` がそろい、`sample_count` が最低件数（3件。Phase 0.2 で確定）以上のときだけ使う。
- 最低件数に届かない場合は、money.state を `NOT_COLLECTED` にして「成約件数不足（N件）」と出す。

### 1.3 Freshness（鮮度）

```
Freshness = {
  "observed_at": str, "checked_at": str,
  "ttl_seconds": int,             # source ごと（DATA_SOURCE_MATRIX.md §2）
  "state": "FRESH" | "STALE" | "EXPIRED" | "UNKNOWN"   # 閲覧時に計算し直す
}
```

- 「更新 MM/DD HH:MM」には、ページの生成時刻ではなく `observed_at` を出す。
- STALE は「更新遅延」と最終確認日時を出す。EXPIRED（14日超など）は利益計算から外す。

時刻の意味（Phase 0.1 で確定。混ぜない）:

| 項目 | 意味 | 「情報確認」に出してよいか |
|---|---|---|
| `observed_at` | その値を取得元で観測した時刻 | ○ |
| `verified_at` | 人が再確認した日（固定の定価など） | ○（「確認日」として） |
| `last_success_at` | 取得元から取得に成功した最新の時刻 | ○ |
| `last_attempt_at` | 取得を試みた時刻（失敗も含む） | ×（成功時刻として出さない） |
| `generated_at` | ページ・レポートを生成した時刻 | ×（情報確認の時刻として出さない） |

- 保存はタイムゾーン付き（例: `2026-10-02T17:49:00+09:00`。08:49 UTC と同じ瞬間）。表示するときに Asia/Tokyo へ変換してから「JST」と付ける。
  observations などはタイムゾーン無しの JST の値と文字列で並べ替えるので、新しく付けるオフセットは +09:00 にそろえる（+00:00 だと並び順が最大9時間ずれる）。
  タイムゾーン無しの値に「JST」と付けるだけにしない。
- タイムゾーン無しの古い値は、UTC で作られたとコードで確かめられる場合だけ UTC として読む。根拠が無ければ補正しない。
- ユーザー向けの表示は次の形にそろえる（Phase 1 以降）。
  - 1時間以内: 「3分前確認」
  - 今日: 「本日 17:49確認」
  - それより前: 「10/01 13:20確認」
  - STALE: 「更新遅延 最終確認 09/30 11:30」

### 1.4 ProductIdentity（同一商品の照合）

```
ProductIdentity = {
  "product_id": str, "category": "smartphone" | "tcg" | "camera" | "game" | "pc" | "other",
  "name": str, "model_number": str | null, "jan": str | null,
  "capacity": str | null, "variant": str | null, "color": str | null,
  "accessories": "BODY_ONLY" | "KIT" | "UNKNOWN",
  "match_level": "EXACT" | "MODEL" | "NAME_ONLY" | "UNVERIFIED"
}
```

- ルートで2つの価格を比べてよいのは、両方が `EXACT` か `MODEL` で、capacity・variant・condition・accessories が一致するときだけ。
- `NAME_ONLY` と `UNVERIFIED` は比べない（一覧に「照合未確認」として出すだけ）。
- 照合の判定は既存の `ProductIdentityResolver` を優先して使う。

## 2. 利益計算（全画面で1つだけ）

```
ProfitBreakdown = {
  "buy_price": Money, "buy_shipping": Money, "buy_required_fees": Money,
  "acquisition_cost": Money,      # 仕入価格 + 購入送料 + 購入時必須費用
  "sell_price": PriceRef,
  "sell_fee": Money,              # 販売手数料（売値 × 料率。売り先ごとの定数）
  "sell_shipping": Money,         # 発送費用
  "other_required": Money,
  "net_profit": Money,            # 想定売値 − 取得原価 − 販売手数料 − 発送費用 − その他必須費用
  "roi_percent": float | null,    # 想定純利益 ÷ 取得原価 × 100
  "state": "CALCULATED" | "NOT_CALCULABLE",
  "missing": [str]                # 計算できない理由（例: "sell_price", "sell_fee", "buy_shipping"）
}
```

ルール:
- どれか1つでも `OK` 以外（費用が不明・売値が未取得など）なら、`state = NOT_CALCULABLE`、`net_profit.state = NOT_COLLECTED` にして「想定利益 算出前」と表示する。**0円で埋めない。**
- 費用は**売り先ごとの1つの定数表**（例: `config/fees.yaml`。Phase 0 で作る）から引く。
  - 買取は販売手数料0、発送は店ごと。
  - メルカリは10%と発送の実費。
  - eBay は最終価値手数料・国際送料・為替（決済手数料との二重計上をしない）。
- **安全マージンは費用に入れない**。必要なら「控えめに見た利益」として別の項目に出す。
- **海外の売値に輸入側のコスト（送料3000円＋輸入税10%）を足さない**（今の `csv_importer.py:149-152` と `ebay.py:71-76` の動きは、売り側の値としては使わない）。
- Python と JS の両方に同じ関数を置き、固定値のテストで一致を確かめる（抽選の runtime と同じ方法）。
- 既存の利益判定（`generate_profit_routes.py` など）は変えない。adapter の中で、既存の出力から新しい定義で計算し直して表示する。値が食い違う場合は、照合表（parity と同じ考え方）で理由を記録する。

## 3. OpportunityView（利益商品の1行）

```
OpportunityView = {
  "id": str, "identity": ProductIdentity,
  "route_type": "OFFICIAL_TO_SECONDARY" | "SECONDARY_TO_SECONDARY" | "SECONDARY_TO_BUYBACK"
              | "OFFICIAL_TO_BUYBACK" | "SECONDARY_TO_OVERSEAS",
  "buy": PriceRef, "buy_stock": "IN_STOCK" | "OUT_OF_STOCK" | "UNKNOWN",
  "sell": PriceRef,
  "profit": ProfitBreakdown,
  "status": "ACTIONABLE" | "WATCH" | "NOT_CALCULABLE" | "INVALID",
  "freshness": Freshness,
  "flags": ["RESTOCKED" | "BUYBACK_SURGE" | "NEW" ...],   # データがあるものだけ
  "last_verified_at": str
}
```

- `ACTIONABLE` は次をすべて満たすときだけ。
  - profit.state=CALCULATED で、net_profit が 0 より大きい。
  - 買い側・売り側とも FRESH。
  - 照合が EXACT か MODEL。
  - 買い側が IN_STOCK（不明なら WATCH）。
  - 買い側・売り側とも `evidence` が `VERIFIED_CURRENT` か `VERIFIED_DATED`。
- **`CONFIGURED_REFERENCE`・`STALE`・`UNKNOWN` の価格を使った利益は、HOME の「今すぐ狙う」「TOP10」
  「BUY 件数」「高利益商品」に昇格させない**（`src/content/ui/home.py` の `evidence_reject_reason`）。
  表示する場合は「参考定価 ¥119,980（確認日不明）」「参考差額 +¥70,220」のように、確定利益と区別する。
- 一覧の列: 商品 / 買う場所 / 仕入価格 / 売る場所 / 売値（種類と期間・件数）/ 想定純利益 / ROI / 在庫・状態 / 更新時刻。
- PC は表、モバイルはカード。どちらも同じ項目を出す。

## 4. RouteView（せどりルートの詳細）

```
RouteView = OpportunityView ＋ {
  "steps": [ {"role": "buy" | "sell", "source_name", "url", "price": PriceRef} ],
  "breakdown_rows": [ ("仕入価格", Money), ("購入送料", Money), ("販売手数料", Money),
                      ("発送費用", Money), ("想定純利益", Money), ("ROI", ...) ],
  "last_checked_at": str
}
```

- 優先するのは `OFFICIAL_TO_SECONDARY`（正規→二次）と `SECONDARY_TO_SECONDARY`（二次→二次）。
- 今ある `SECONDARY_TO_BUYBACK` などは残す。表示するかどうかは、利用状況とデータ品質で決める（勝手に消さない）。

## 5. ProductView（商品詳細）

```
ProductView = {
  "identity": ProductIdentity,
  "header": {"status", "latest_change": str, "best_net_profit": Money, "best_roi": float | null,
             "required_capital": Money},     # 必要な仕入資金 = 最良ルートの取得原価
  "tabs": {
    "sources": {"buy": [PriceRef], "sell": [PriceRef]},          # 仕入・売却先
    "history": [ {"date", "price_type", "price": Money} ] | "NOT_COLLECTED",   # 価格推移
    "changes": [ {"at", "kind", "text"} ]                         # 最近の変化
  }
}
```

- 内部はタブで切り替える。全部を縦に並べない。
- 価格推移は、履歴のデータがそろうまで「未取得」にする（DB が毎回作り直されるため、今は海外の history しかない）。

## 6. LotteryReservationView（抽選・予約）

今の `runtime.py` の VM を広げる（状態の判定は `compute_lottery_status` のまま）。

```
LotteryReservationView = 今の抽選 VM ＋ {
  "category": "tcg" | "smartphone" | "camera" | "game" | "other",
  "kind": "LOTTERY" | "PREORDER" | "RELEASE",
  "release_state": "AWAITING_ANNOUNCEMENT" | "AWAITING_PREORDER" | "AWAITING_RELEASE"
                 | "LOTTERY_OPEN" | "ON_SALE" | null,
  "retail_price": Money,          # 未発表なら UNPUBLISHED
  "market_ref": PriceRef,         # 成約中央値。無ければ NOT_COLLECTED
  "profit": ProfitBreakdown,      # 売値が無ければ NOT_CALCULABLE
  "eligibility": str, "result_at": ..., "purchase_deadline": ..., "official_url": str,
  "source_url": str, "last_verified_at": str
}
```

- 分類: すべて / 抽選受付中 / 今日締切 / 予約・発売待ち。
- 公式の根拠が無いものは、抽選にも予約にもしない（新型 iPhone などを推測で載せない）。

## 7. RestockView（在庫再開）

```
RestockView = {
  "identity": ProductIdentity, "retailer": str, "url": str,
  "price": Money, "purchase_limit": str | null,
  "current_stock_state": "IN_STOCK" | "OUT_OF_STOCK" | "UNKNOWN",
  "restocked_at": str | null,      # 在庫が戻ったことを最初に確認した時刻
  "last_checked_at": str,          # 最後に確認した時刻
  "ttl_seconds": int,
  "profit": ProfitBreakdown, "source_url": str
}
```

- 表示の切り替え: 「購入可能」（current_stock_state=IN_STOCK で、TTL 内）と「再開履歴すべて」。
- 過去に再開していても、今在庫が無い・TTL を過ぎた・不明なら、「購入可能」に出さない（閲覧時に判定し直す）。
- **今は一般商品のデータが無い**（DATA_CAPABILITY_AUDIT.md §5）。TCG だけ、既存の TTL で作れる。

## 8. 画面の状態（すべての一覧で共通）

| 状態 | 表示 |
|---|---|
| empty | 「今は該当がありません」と、次に起きること（「毎日 12:00 に更新します」など） |
| stale | 金額は出すが「更新遅延」と最終確認日時。利益は出さない |
| out of stock | 「在庫なし」（購入可能の一覧からは外す） |
| unpublished | 「未発表」 |
| not collected | 「未取得」 |
| source conflict | 「日程要確認」「価格要確認」（どちらの値も採用しない） |
| invalid price | 「価格確認中」 |
| missing fee / missing shipping | 「想定利益 算出前」と、足りない項目（例: 「販売手数料が未設定」） |
| insufficient sold samples | 「成約件数不足（N件）」 |

## 9. 一般の画面と管理画面

- 一般の画面に出すのは、「一部情報の更新が遅れています」という1行だけ。
- 品質の警告は重大度を分ける（`scripts/check_collector_quality.py`）。
  - ERROR: 商品の誤マッチ・誤った価格（定価の3倍超・別SKUと同額・容量の逆転など）・鮮度の偽装・必須の取得元の整合性違反。
  - WARNING: 前回から大きく変動した価格（相場の実際の変動もありうる。公開は止めない）。
  - INFO: optional の取得元の失敗。
  - 一般の画面には「⚠ 前回から大きく変動した買取価格が N件あります」程度だけを出し、内部のチェック番号・理由コードは出さない。
- collector のエラー、HTTP ステータス、API の設定、circuit breaker、deploy、生の DQ は `/admin/` だけに出す（段階 E）。
- 新UIのインライン JS に入っているソースのコメント（ファイルパスなど）は、公開前に取り除く（ビルド時の minify でよい）。
