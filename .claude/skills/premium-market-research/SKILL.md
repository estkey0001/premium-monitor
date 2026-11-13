---
name: premium-market-research
description: Premium Monitor 用の市場リサーチ。「今日のポケカ抽選」「ONE PIECE の予約」「新発売の商品」「iPhone の買取比較」「カメラの仕入れと売却」を、Web 検索・ページ取得で実際に調べ、FACT / INFERENCE / UNKNOWN に分けて出力する。結果は DISCOVERED 候補であって VERIFIED / CONFIRMED / ACTIONABLE ではない。
argument-hint: [tcg | new-product | iphone | camera] [補足]
---

# Premium Market Research

対象: $ARGUMENTS（省略時は 4 モードすべて）

目的: 利用者が「今、何を買い、どこで売れば、いくら利益になるか」を知るための**一次情報つきの発見**。
**AI が決めてよいのは DISCOVERED まで。** VERIFIED / CONFIRMED / ACTIONABLE は、後段の決定論的な検証（`src/` の `polite.py` 経由の取得・同一性・鮮度の関門）だけが決める。

## 共通の規則

1. **今日の日付を最初に確かめる**（システムの日付。推測しない）。検索には年月を入れる。
2. **一般的な例を返さない。** 実際に取得した現在の情報だけを返す。見つからなければ「見つからない」と書く。
3. **検索結果の要約を事実にしない。** 検索結果はリンクの手がかり。日程・価格は**そのページを開いて**確かめる。ページを開けなかった項目は `UNVERIFIED`。
4. **過去の情報を現在の抽選にしない。** 応募開始・締切・当選発表・購入期限を今の日時と比べ、`status` を決める（下記）。日程が読めなければ `OPEN` にしない（`UNKNOWN`）。
5. **推測を FACT に混ぜない。** ページに書いてあることだけが FACT。利益の見込みなどは INFERENCE。取れなかった情報は UNKNOWN。
6. **取得の作法**: robots・利用規約・アクセス制限を尊重する。ログイン・CAPTCHA・WAF の回避、プロキシ、大量アクセスはしない。ブロックされたら別の手段で取り直さず `BLOCKED` と記録する。メルカリ・ラクマ・Amazon・ヤフオク・eBay・楽天の**検索結果ページ**は読まない（公式 API だけ）。1 つのドメインに短時間で何度もアクセスしない。
7. 個人情報・Secret・ログイン情報を出力に含めない。

## 出力形式（1 件 1 オブジェクト・日本語）

```
kind:            LOTTERY_OPEN | LOTTERY_ENDING | LOTTERY_UPCOMING | PREORDER_OPEN | RESERVATION_OPEN | FIRST_COME |
                 WINNER_ANNOUNCEMENT | WINNER_PURCHASE_PERIOD | RESTOCK | NEW_PRODUCT | PRICE_ROUTE
product_name / series / tcg (POKEMON|ONE_PIECE|OTHER)
retailer / channel (STORE|ONLINE)
application_start / application_end / winner_announcement / purchase_start / purchase_end / release_date   （ISO 8601・JST。無ければ null）
retail_price（税込・円）/ eligibility / requirements
official_url          … 公式または一次情報のページ
source_url / source_type  … OFFICIAL | RETAILER | MAKER | NEWS | AGGREGATOR | SNS
checked_at            … ページを開いた日時（JST）
status                … OPEN | UPCOMING | ENDING_SOON(24〜48 時間以内) | ENDED | UNKNOWN
confidence            … high（公式ページで日程まで確認）| medium（一次情報だが一部未確認）| low（二次情報だけ）
fact: [ページで確認した事実]   inference: [推定]   unknown: [取れなかった項目]
classification        … FOUND | VERIFIED | UNVERIFIED | STALE | DUPLICATE
```

分類: **VERIFIED** = 公式/一次情報のページを開き、日程・商品・店が一致。**UNVERIFIED** = 二次情報だけ・ページ未取得。**STALE** = 締切後・古い記事。**DUPLICATE** = 同じ（商品・店・種別・期間）。ただし**ここでの VERIFIED は調査上の印**で、Premium Monitor の VERIFIED（決定論的な検証の結果）とは別物。

## モード

### tcg — LIVE LOTTERY
ポケモンカード・ONE PIECE カードゲームの、日本国内の抽選・予約・先着・当選発表・購入期間・再販。
- 取得元の候補: 公式ニュース（pokemon-card.com・onepiece-cardgame.com）、ポケモンセンターオンライン、プレミアムバンダイ、ヨドバシ・ビック・ヤマダ・Joshin・エディオン・トイザらス・楽天ブックス・セブンネット・カードラボ等の告知、まとめ記事（**手がかりとしてだけ**使い、公式で裏を取る）。
- 「締切が今日・明日」「当選発表が近い」「購入期限が近い」を必ず別に拾う。
- 既存の台帳（`exports/discovery/event_candidates.json`・`exports/tcg/lotteries.json`）にあるか調べ、**新規 / 既知**を分けて報告する（recall の測定に使う）。

### new-product — NEW PRODUCT DISCOVERY
直近（約 60 日）に発売・発表された iPhone / Apple 製品 / カメラ（RICOH・FUJIFILM・Sony・Canon・Nikon）/ ゲーム機 / 新しい TCG の BOX。**既存の正本（`config/products.yaml`）に無いもの**を優先して報告。発売日・定価・公式 URL・予約/抽選の有無。

### iphone — IPHONE ARBITRAGE
SKU 単位（世代・モデル・容量・色・SIM の区別・部品番号があれば）。Apple の定価（公式ページ）と、複数の国内買取店（新品・未開封）の買取価格・条件・確認日時。**1 店舗だけで判断しない**。最高買取店と、概算の純利益・ROI は INFERENCE（費用は `src/market/profit_formula.py` の式に従い、分からない費用は UNKNOWN と書き、0 円としない）。

### camera — CAMERA ARBITRAGE
新品の仕入れ（メーカー公式・正規量販店・専門店・取れれば二次流通）と売却（買取専門店・総合買取・二次流通）。限定品・人気商品の抽選/予約/先着/再販。二次流通は**価格を混ぜず** LISTING LOW/HIGH（出品中）と SOLD LOW/HIGH/MEDIAN・サンプル数・期間を別に書く。**最高出品価格を売れる価格として使わない。**

## 禁止

- AI の判断だけで VERIFIED / CONFIRMED / ACTIONABLE にしない・BUY と書かない（BUY/WATCH/WAIT/SKIP は利益エンジンが決める）
- 古い記事を現在の抽選にする・日程を推測する
- 取れなかったものを埋める（UNKNOWN と書く）

## 最後に

分類ごとの件数・取得できなかった範囲（BLOCKED・ページ未取得・検索が出さなかった領域）・既知との重複を要約する。
