# Phase 29 — 発見から登録した商品の公式直販価格・買取の照合

作成: 2026-10-17。Phase 28 で正本に登録した iPhone Air 256GB（prod_iphoneair_256）に、公式直販価格・同一性・送料・買取の
証拠をそろえ、既存の利益の判定に接続する。利益を出すことを目的にしない（証拠が無ければ未算出、売値が安ければ no_profit）。
外部への送信 0。

## 1. 開始の時点

| 指標 | 値 |
|---|---:|
| 正本の商品 | 46 |
| iPhone Air の公式の価格 | 設定値の参考（CONFIGURED_REFERENCE・VERIFY_FROM_OFFICIAL） |
| iPhone Air の在庫 / 買取 / 利益 | 作らない / 未取得 / 未算出（unverified_buy_price・no_sell_price） |
| 登録した候補 | REGISTERED（Phase 28 の後の Apple の発見はまだ iphone-air を読んでいない） |
| Phase 24 の受入状態 | PHASE24_WAITING |
| CI の所要時間 | 1時間13分 |
| pytest | 2054 passed |

## 2. 公式直販価格（`src/market/official_registry.py`）

- 2026-10-17 23:21 JST、公式の購入ページ（https://www.apple.com/jp/shop/buy-iphone/iphone-air）を取得の共通の作法
  （`recheck_official._fetch`: robots.txt・正直な User-Agent・間隔・リダイレクトをたどらない）で1回取得。商品データ
  （partNumber・price.fullPrice・name）で 256GB の4色がどれも 189,800円:
  MG274J/A Space Black・MG284J/A Cloud White・MG294J/A Light Gold・MG2A4J/A Sky Blue（512GB 224,800円・1TB 294,800円は別の行）
- VERIFIED_URLS（price_kind official_direct・item・checked_on 2026-10-17）・IDENTITY_EVIDENCE（model_name iPhone Air・
  色違いの部品番号の組 = 正本の part_numbers）・OFFICIAL_DIRECT_OFFERS（容量 256GB・日本向け（SIM フリー）・NORMAL・
  在庫 UNKNOWN）。`official_direct_gate` は理由なしで通る。呼び方は「公式直販価格」（希望小売価格・定価と呼ばない）
- 設定値（retail_price）だけでは確定にしない（証拠が無ければ関門で `no_official_direct_evidence`）
- 送料: 既存の Apple の記録（Apple Online Store は配送料無料。2026-10-05 確認）を URL のホストで使う
- 再確認: `scripts/recheck_official.py` の対象に加えた（apple_parts。4つの部品番号の価格がすべて同じときだけ読む）。価格が
  変われば changed（人の確認待ち・確定に使わない）・リダイレクトは moved（失敗）。確認から14日を過ぎれば使わない

## 3. 買取の照合（`src/collectors/buyback_kaitori_shouten.py`・`scripts/update_buyback_prices.py`）

- 買取商店の iPhone Air の一覧（/category/1/709。2026-10-17 23:22 に1回取得して形を確認）。表の「新品買取」の列だけを読む。
  行の「強化」は店の強化買取の目印（全12行に付く・商品名の外）で、価格の欄は無条件の新品買取の値。毎日取り直し、失敗した日は
  行を残さないので、終わった強化の価格が残る経路は無い。行に条件の注記（「条件」「要〜」など）が付くようになったら除外の語に加える
- 規則 `iphoneair_256`: 「iPhone Air 256GB」で始まる・SIMフリーの明示が必須・キャリア版（au / docomo / softbank / 楽天）・
  Pro / Max / Plus・中古 / 未使用 / 開封済を除く・行の部品番号がちょうど1つで、公式で確かめた4つのどれか
- 色で買取価格が違う（2026-10-17: スカイブルー 133,000円・ほか3色 135,000円）。色の最高値を使わず、最も低い色の行
  （その行の商品ページ /products/detail/NNN を出典）を使う（その色を公式で買えば実際に成り立つ値。売値を色で混ぜて高く見せない）
- 取得に失敗した日に前回の行を残さない（KEEP_PREVIOUS_ON_FAILURE に入れない。鮮度を偽装しない）。新しい取得元は足さない
  （既存の買取商店だけ。リクエストは1回増える）
- 確定の売値は既存の判定（`normalized_prices.sell_confirmation_reasons`: 自動取得・商品ページ・14日以内・新品）。店のトップ・
  検索・古い・中古・手入力は確定にしない

## 4. 利益・今すぐ行動

- 既存の正本の計算（`beginner_deal_scanner.scan_product` → `opportunity.deal_reasons`）だけ。UI で計算し直さない
- 2026-10-17 の値では 133,000 − 189,800 − 費用 < 0 → no_profit（案件は monitoring。利益は出さない）
- 正の利益になっても、公式の在庫は UNKNOWN（初期表示に在庫の情報が無い）なので今すぐ行動できない（stock_unknown）
- 送料が分からない・売る側の同一性が未確認・設定値の価格のどれかなら確定にしない

## 5. 表示・検査

- 運営者向け「新商品・新しいイベントの発見」に「発見から登録した商品の状態」（公式の価格の根拠・公式の価格・買取・利益。
  診断の値のまま）
- 既存の公式直販価格の監査の表・商品詳細・検索（名前・容量・部品番号）に、そのまま出る
- deploy-check #864: 登録した商品の公式の証拠（URL・部品番号の組 = 正本・容量・価格・在庫）・設定値だけでは関門を通らない・
  買取の規則（容量・SIMフリー・キャリア版・部品番号・色は最も低い行）を関数で確かめる・前回の行を残さない・登録した候補が
  正本と一致・同じ商品の候補を作り直さない

## 6. テスト

- tests/test_phase29_activation.py（22件）。ページは本物と同じ形の小さな HTML（通信しない）
- 既存のテストの更新（意図は変えない）: test_phase15_identity の正本の件数 45 → 46（Phase 28 の登録）
- mutation: 19/19（DB の行で正本を引かない・正本を読めないときに通す・設定値の公式で確定と表示・関門で正本の部品番号の組を見ない・管理画面で別のルートを混ぜる・設定値だけで確定・容量違いの番号を証拠に・部品番号を1つ落とす・容量違い / キャリア版 / SIMフリーの推測 /
  部品番号を見ない / 色の最高値 / 中古を買取で通す・前回の行を残す・登録の後に候補を作り直す・管理画面で no_profit を未算出に・
  店のトップの価格を確定に・不明な送料を 0 に）

## 7. レビュー・監査の指摘

- Medium（レビュー）: 公式直販価格の関門が正本の part_numbers・capacity を見ていなかった（正本を書き換えても実行時は確定の
  まま）→ 正本に組・容量がある商品は証拠と完全に同じときだけ（`_variant_group_ok`）
- Medium（レビュー）: 管理画面の表が、利益が確定した状態を「—」と出し、別のルートの理由で上書きした → 公式 → 買取の候補だけ・
  除外の理由が無ければ「確定（診断で除外の理由なし）」
- Low（レビュー）: #864 の「設定値だけ」の検査を、登録した商品の証拠を一時的に外して関門を呼ぶ形に・買取を取りに行く登録した
  商品に規則が無ければ error・取得の docstring・既存の iPhone 17 の重複価格の巻き込みを DEV_NOTES に

- Low（記録）: 「強化」の目印の意味を §3 に記録した
- Low（#864）: 候補の重複の検査を商品名の完全一致から「機種 + 容量」（`parse_name`）の一致に
- Low（既知）: `update_buyback_prices.OFFICIAL_PRICES` は公式の登録簿と別に価格を持つ（異常値の判定だけ。既存の商品と同じ形）
- Medium（再レビュー）: 公式の価格を DB に書く経路（audit_official_sources の DB の行に part_numbers の列が無い）では、関門の
  組・容量の照合が飛ばされた → 関門が正本（config/products.yaml）の part_numbers・capacity を引いて照合する
  （`_canonical_identity`。ファイルが変われば読み直す）。正本を読めないときは確定にしない（通す側に倒さない）
- Low（再レビュー・再監査）: 管理画面の「確定」は公式の根拠が VERIFIED_CURRENT / VERIFIED_DATED のときだけ・#864 の証拠の
  一時退避は dict ごと（キーの順番を保つ）・test_phase28_review に止まる理由のコメント
- Low（既知）: 関門が引く正本のパスは本物の config に固定（一時の正本で DB の形の行を試すテストは無い）

## 8. 本番の確認（2026-10-18）

- Daily LP の手動の実行（Run 39044103870・success・1時間16分）・生成コミット 9f862a27（生成物だけ）
- 公式: 再確認が unchanged（189,800円）。診断の公式の価格は VERIFIED_CURRENT（src_apple_jp・公式直販）
- 買取: 買取商店の取得 ok。正規化の売値は 133,000円（スカイブルーの行・/products/detail/24681・item・照合済み・新しい・
  新品未開封 SIMフリー）
- 利益: RETAIL_TO_BUYBACK は no_profit（133,000 − 189,800 − 費用 < 0）。利益ルート 0・確定の案件 2 → 2（変化なし）・今すぐ
  行動 0。在庫は作らない（UNKNOWN）
- 発見: この実行の Apple は iphone-16・iphone-17 を読んだ（まだ読んでいなかった機種が先）。iPhone Air 256GB の候補は1件のまま
  REGISTERED（重複 0・照らし合わせで戻した 0）。iphone-air のページは、読もうとした日の古い順で次の定時の実行で読む（取得の順を
  変えない。正本との一致はテストと #864 で確かめた）
- deploy-check エラー 0（#864 OK）・prelaunch ❌ 0・健康度 38.4 → 38.4・Phase 24 の受入状態は PHASE24_WAITING・外部への送信 0
