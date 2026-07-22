# Profit Discovery Audit

生成: 2026-07-22 14:54 JST / NPO: 2026-06-20 03:07 JST
main profit routes: **1** / reference: 4 / EBAY_APP_ID: **未設定**

> 本監査は診断のみ（コード修正なし）。各タスク: 原因→根拠→改善案。

## Task1: 除外された利益候補（全件）

| 商品 | 状態 | buy | sell | gross | net | ROI | 除外理由 |
|---|---|---|---|---|---|---|---|
| FUJIFILM X100VI | usable両方あるが未成立 | ¥255000 | ¥220000 | ¥373900 | ¥-41600 | -16% | 国内完結が赤字（sell≤buy） |
| RICOH GR IV | 候補不足 | ¥61267 | ¥318725 | ¥257458 | ¥252958 | 413% | 全 sell が除外（stale_over_14d） |
| RICOH GR IV HDF | 候補不足 | ¥44105 | ¥213400 | ¥169295 | ¥164795 | 374% | 全 buy が除外（stale_over_14d） |
| Nintendo Switch  | 候補不足 | ¥46000 | ¥190000 | ¥148500 | ¥139500 | 303% | 全 sell が除外（price_zero） |
| iPhone 17 Pro 25 | 候補不足 | ¥169800 | ¥310200 | ¥140400 | ¥135504 | 80% | 全 sell が除外（stale_over_14d） |
| iPhone 17 Pro Ma | 候補不足 | ¥154800 | ¥232000 | ¥77200 | ¥72604 | 47% | 全 sell が除外（price_zero） |
| PlayStation 5 Pr | 候補不足 | ¥128000 | ¥190000 | ¥125000 | ¥57500 | 45% | 全 sell が除外（price_zero） |
| iPhone 17 Pro Ma | 候補不足 | ¥236544 | ¥268000 | ¥31456 | ¥25225 | 11% | 全 sell が除外（price_zero） |
| RICOH GR IIIx | 成立(main) | ¥150000 | ¥167200 | ¥92000 | ¥12700 | 8% | —（成立） |
| iPhone 17 Pro 51 | 候補不足 | ¥204800 | ¥223000 | ¥18200 | ¥12604 | 6% | 全 sell が除外（price_zero） |
| Nintendo Switch  | 候補不足 | ¥53000 | ¥67000 | ¥14000 | ¥9500 | 18% | 全 sell が除外（stale_over_14d） |
| MacBook Air M4 1 | 候補不足 | ¥145000 | ¥143000 | ¥-2000 | ¥-6500 | -4% | 全 sell が除外（stale_over_14d） |
| RICOH GR IV Mono | 候補不足 | ¥300000 | ¥213400 | ¥-85000 | ¥-94100 | -31% | 全 buy が除外（stale_over_14d） |
| iPhone 17 256GB  | 候補不足 | — | ¥135000 | — | — | — | 全 sell が除外（stale_over_14d） |
| iPhone 16 Pro 25 | 候補不足 | — | ¥152000 | — | — | — | 全 sell が除外（stale_over_14d） |
| iPhone 16 Pro Ma | 候補不足 | — | ¥216425 | — | — | — | 全 sell が除外（stale_over_14d） |
| MacBook Air M4 1 | 候補不足 | — | ¥175000 | — | — | — | 全 sell が除外（stale_over_14d） |
| MacBook Pro M4 1 | 候補不足 | — | ¥220000 | — | — | — | 全 sell が除外（stale_over_14d） |
| Mac mini M4 | 候補不足 | — | ¥78000 | — | — | — | 全 sell が除外（stale_over_14d） |
| iPad Pro M4 11イン | 候補不足 | — | ¥148000 | — | — | — | 全 sell が除外（stale_over_14d） |
| iPad Pro M4 13イン | 候補不足 | — | ¥192000 | — | — | — | 全 sell が除外（stale_over_14d） |
| iPad Air M3 | 候補不足 | — | ¥78000 | — | — | — | 全 sell が除外（stale_over_14d） |
| Apple Watch Seri | 候補不足 | — | ¥48000 | — | — | — | 全 sell が除外（stale_over_14d） |
| Apple Watch Ultr | 候補不足 | — | ¥105000 | — | — | — | 全 sell が除外（stale_over_14d） |
| AirPods Pro 3 | 候補不足 | — | ¥32000 | — | — | — | 全 sell が除外（stale_over_14d） |
| AirPods Max | 候補不足 | — | ¥68000 | — | — | — | 全 sell が除外（stale_over_14d） |
| PlayStation 5 Di | 候補不足 | — | ¥65000 | — | — | — | 全 sell が除外（stale_over_14d） |
| Xbox Series X | 候補不足 | — | ¥50000 | — | — | — | 全 sell が除外（stale_over_14d） |
| FUJIFILM GFX100R | 候補不足 | — | ¥432300 | — | — | — | buy候補なし |
| FUJIFILM X-T5 | 候補不足 | — | ¥223300 | — | — | — | 全 sell が除外（accessory_or_wrong_product） |
| SONY α7R V | 候補不足 | — | ¥236500 | — | — | — | buy候補なし |
| SONY α1 II | 候補不足 | — | ¥584100 | — | — | — | buy候補なし |
| SONY α7CR | 候補不足 | — | ¥242000 | — | — | — | buy候補なし |
| SONY FX3 | 候補不足 | — | ¥421300 | — | — | — | buy候補なし |
| Canon EOS R5 Mar | 候補不足 | — | ¥517000 | — | — | — | 全 sell が除外（accessory_or_wrong_product） |
| Canon EOS R3 | 候補不足 | — | ¥282700 | — | — | — | 全 sell が除外（accessory_or_wrong_product） |
| Nikon Z8 | 候補不足 | — | ¥309100 | — | — | — | buy候補なし |
| Nikon Z9 | 候補不足 | — | ¥346500 | — | — | — | 全 sell が除外（accessory_or_wrong_product） |
| Leica Q3 | 候補不足 | — | ¥833800 | — | — | — | buy候補なし |
| Leica M11 | 候補不足 | — | ¥1375400 | — | — | — | buy候補なし |

## Task2: 未成立原因ランキング（件数順）

| 順位 | 原因 | 件数 |
|---|---|---|
| 1 | stale_over_14d | 458 |
| 2 | price_zero | 410 |
| 3 | accessory_or_wrong_product | 4 |
| 4 | route_gross_negative(国内赤字) | 1 |

## Task3: 改善インパクトランキング（潜在利益順）

| 施策 | 解放ルート | 潜在利益 | 備考 |
|---|---|---|---|
| EBAY_API (海外sold fresh化) | 3 | +¥228,794 | 現状stale/manualの海外soldをAPI fresh化 |
| Mercari/Yahoo Sold (安い仕入れ取得) | 1 | +¥833 | target_buy_price 以下の国内sold取得で国内買取ルート成立 |
| 買取店fresh化: 買取商店 | 0 | +¥0 | stale買取をfresh化(daily取得)でsell候補が復活しうる |
| 買取店fresh化: イオシス | 0 | +¥0 | stale買取をfresh化(daily取得)でsell候補が復活しうる |
| 買取店fresh化: モバイル一番 | 0 | +¥0 | stale買取をfresh化(daily取得)でsell候補が復活しうる |
| 買取店fresh化: 買取一丁目 | 0 | +¥0 | stale買取をfresh化(daily取得)でsell候補が復活しうる |
| 買取店fresh化: じゃんぱら | 0 | +¥0 | stale買取をfresh化(daily取得)でsell候補が復活しうる |
| 買取店fresh化: ゲオ | 0 | +¥0 | stale買取をfresh化(daily取得)でsell候補が復活しうる |
| 買取店fresh化: マップカメラ | 0 | +¥0 | stale買取をfresh化(daily取得)でsell候補が復活しうる |
| 買取店fresh化: カメラのキタムラ | 0 | +¥0 | stale買取をfresh化(daily取得)でsell候補が復活しうる |

## Task4: 商品別「あと何円で成立」

| 商品 | buy | sell | 現net | ROI | 状態 | 必要改善 |
|---|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥255,000 | ¥220,000 | -41,600 | -16% | 未成立 | buy -¥54,350 または sell +¥54,350 で ROI5%成立 |
| RICOH GR IIIx | ¥150,000 | ¥167,200 | +12,700 | 8% | 成立(ROI≥5%) | 既に成立 |

## Task5: 価格ソース一覧

| ソース | 件数 | fresh率 | item_url率 | 中央age | method |
|---|---|---|---|---|---|
| じゃんぱら | 140 | 0% | 34% | 27.3d | ['manual', 'fetch_failed'] |
| イオシス | 114 | 0% | 74% | 26.3d | ['manual', 'fetch_failed', 'auto_scraped'] |
| 買取商店 | 95 | 0% | 81% | 26.2d | ['manual', 'fetch_failed', 'auto_scraped'] |
| モバイル一番 | 66 | 0% | 42% | 26.2d | ['manual', 'fetch_failed', 'auto_scraped'] |
| 買取一丁目 | 56 | 0% | 50% | 26.2d | ['manual', 'fetch_failed', 'auto_scraped'] |
| ゲオ | 53 | 0% | 57% | 31.6d | ['manual', 'fetch_failed', 'auto_scraped'] |
| メーカー公式/定価 | 44 | 100% | 0% | 0.0d | ['retail_concept'] |
| ソフマップ | 40 | 0% | 25% | 26.2d | ['manual', 'fetch_failed'] |
| ゲオモバイル | 32 | 0% | 0% | 25.5d | ['fetch_failed'] |
| セカンドストリート | 32 | 0% | 0% | 25.5d | ['fetch_failed'] |
| ネットオフ | 32 | 0% | 25% | 25.5d | ['fetch_failed', 'auto_scraped'] |
| フジヤカメラ | 28 | 57% | 43% | 0.7d | ['manual', 'auto_scraped'] |
| ブックオフ | 20 | 0% | 0% | 26.2d | ['fetch_failed'] |
| 駿河屋 | 20 | 0% | 0% | 26.2d | ['fetch_failed'] |
| TSUTAYA | 20 | 0% | 0% | 26.2d | ['fetch_failed'] |
| ハードオフ | 16 | 0% | 0% | 25.5d | ['fetch_failed'] |
| ドスパラ | 16 | 0% | 0% | 25.5d | ['fetch_failed'] |
| eBay sold(新品) | 15 | 0% | 100% | 21.7d | ['manual'] |
| メルカリ未使用 | 15 | 0% | 100% | 21.7d | ['manual'] |
| マップカメラ | 13 | 0% | 77% | 30.6d | ['manual'] |
| カメラのキタムラ | 13 | 0% | 77% | 30.6d | ['manual'] |
| パソコン工房 | 10 | 0% | 0% | 26.2d | ['fetch_failed'] |
| ヤフオク (新品/未使用落札) | 10 | 0% | 0% | 18.3d | ['resale_market_manual'] |
| Amazon新品出品 | 9 | 0% | 100% | 21.7d | ['manual'] |
| 楽天市場新品 | 6 | 0% | 100% | 21.7d | ['manual'] |
| src_ebay | 6 | 0% | 0% | 30.7d | ['manual', 'overseas_history'] |
| Amazon JP (新品出品) | 5 | 0% | 0% | 18.3d | ['resale_market_manual'] |
| Yahoo Auction sold | 3 | 100% | 100% | 11.4d | ['flea_sold'] |
| Mercari sold | 3 | 100% | 100% | 10.8d | ['flea_sold'] |
| src_bhphoto | 2 | 0% | 0% | 30.7d | ['overseas_history'] |

## Task6: 店舗品質ランキング（100点）

| 順位 | 店舗 | スコア | 価格 | リンク | 鮮度 | 取得率 | 誤検出 |
|---|---|---|---|---|---|---|---|
| 1 | Yahoo Auction so | 90.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| 2 | Mercari sold | 90.0 | 1.0 | 1.0 | 1.0 | 1.0 | 0.0 |
| 3 | メーカー公式/定価 | 70.0 | 1.0 | 0.0 | 1.0 | 1.0 | 0.0 |
| 4 | eBay sold(新品) | 70.0 | 1.0 | 1.0 | 0.0 | 1.0 | 0.0 |
| 5 | メルカリ未使用 | 70.0 | 1.0 | 1.0 | 0.0 | 1.0 | 0.0 |
| 6 | Amazon新品出品 | 70.0 | 1.0 | 1.0 | 0.0 | 1.0 | 0.0 |
| 7 | 楽天市場新品 | 70.0 | 1.0 | 1.0 | 0.0 | 1.0 | 0.0 |
| 8 | フジヤカメラ | 68.6 | 1.0 | 0.43 | 0.57 | 1.0 | 0.14 |
| 9 | マップカメラ | 65.4 | 1.0 | 0.77 | 0.0 | 1.0 | 0.0 |
| 10 | カメラのキタムラ | 65.4 | 1.0 | 0.77 | 0.0 | 1.0 | 0.0 |
| 11 | 買取商店 | 56.7 | 0.81 | 0.81 | 0.0 | 0.81 | 0.0 |
| 12 | ゲオ | 53.8 | 0.85 | 0.57 | 0.0 | 0.85 | 0.0 |
| 13 | イオシス | 51.6 | 0.74 | 0.74 | 0.0 | 0.74 | 0.0 |
| 14 | ヤフオク (新品/未使用落札) | 50.0 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 |
| 15 | src_ebay | 50.0 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 |
| 16 | src_bhphoto | 50.0 | 1.0 | 0.0 | 0.0 | 1.0 | 0.0 |
| 17 | Amazon JP (新品出品) | 46.0 | 1.0 | 0.0 | 0.0 | 1.0 | 0.4 |
| 18 | 買取一丁目 | 35.0 | 0.5 | 0.5 | 0.0 | 0.5 | 0.0 |
| 19 | ソフマップ | 30.0 | 0.5 | 0.25 | 0.0 | 0.5 | 0.0 |
| 20 | モバイル一番 | 29.7 | 0.42 | 0.42 | 0.0 | 0.42 | 0.0 |
| 21 | じゃんぱら | 28.9 | 0.44 | 0.34 | 0.0 | 0.44 | 0.0 |
| 22 | ネットオフ | 17.5 | 0.25 | 0.25 | 0.0 | 0.25 | 0.0 |
| 23 | ブックオフ | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 24 | 駿河屋 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 25 | TSUTAYA | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 26 | ゲオモバイル | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 27 | セカンドストリート | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 28 | ハードオフ | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 29 | ドスパラ | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 30 | パソコン工房 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## Task7: 商品別データ不足ランキング

| 商品 | 不足数 | 不足データ |
|---|---|---|
| iPhone 16 Pro Max  | 5 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh), item_url |
| RICOH GR III HDF | 5 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh), item_url |
| RICOH GR III | 5 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh), item_url |
| Canon EOS R6 Mark  | 5 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh), item_url |
| Nikon Zf | 5 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh), item_url |
| iPhone 17 Pro 256G | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| iPhone 17 Pro 512G | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| iPhone 17 Pro Max  | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| iPhone 17 Pro Max  | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| iPhone 17 256GB SI | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| iPhone 16 Pro 256G | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| iPhone 16 Pro Max  | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| MacBook Air M4 13イ | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| MacBook Air M4 15イ | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| MacBook Pro M4 14イ | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| Mac mini M4 | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| iPad Pro M4 11インチ | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| iPad Pro M4 13インチ | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| iPad Air M3 | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| Apple Watch Series | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| Apple Watch Ultra  | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| AirPods Pro 3 | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| AirPods Max | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| Nintendo Switch 2  | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |
| PlayStation 5 Digi | 4 | 海外sold(fresh), フリマsold, 店舗販売価格, 買取価格(fresh) |

## Task8: ボトルネック TOP20

| 順位 | ボトルネック | 根拠 | インパクト |
|---|---|---|---|
| 1 | 海外sold が stale/manual（EBAY_APP_ID未設定） | reference4件が全てstale・main昇格不可 | ★★★★★ |
| 2 | stale価格が多数（458件） | 手動CSV/海外が14日超で除外 | ★★★★★ |
| 3 | 除外: stale_over_14d（458件） | NPO rejection集計 | ★★★★★ |
| 4 | 除外: price_zero（410件） | NPO rejection集計 | ★★★★★ |
| 5 | price=0(取得失敗) 410件 | PS5/Switch買取店の¥0多数 | ★★★★ |
| 6 | フリマsoldが手動キュレーションのみ | 自動取得なし・裾データ薄い | ★★★★ |
| 7 | 国内完結ルートは構造的に薄利 | 人気機種は買取>販売でROI<5% | ★★★★ |
| 8 | official_price 未登録（retail_concept依存） | 全カメラで公式価格None | ★★★ |
| 9 | item_url率が低い | 買取/販売の多くが検索/店舗トップ | ★★★ |
| 10 | Mapcamera/Kitamura 買取が取得困難 | Akamai/site_blocked | ★★★ |
| 11 | 同条件sold件数が少なく再現性低 | GR IIIx再現性45(低) | ★★ |
| 12 | camera買取はローカルに無くCI依存 | 監査はCI status注入で代替 | ★★ |
| 13 | 除外: accessory_or_wrong_product（4件） | NPO rejection集計 | ★ |

## Task9: 改善ROIランキング（工数別）

| 優先 | 工数 | 施策 | 効果 |
|---|---|---|---|
| 1 | 1時間 | EBAY_APP_ID を GitHub Secrets に設定 | 参考4ルート→main昇格、潜在+¥183,582解放 |
| 2 | 1時間 | manual_flea_sold_prices.csv に確認済みsoldを追記運用 | 国内買取ルートの裾を拡大（商品ごと+数千〜1万） |
| 3 | 4時間 | 買取店のstale再取得（daily fresh化の安定化） | sell候補復活・reference→main化の前提 |
| 4 | 4時間 | official_price を products.yaml に登録 | 差益基準の信頼性・beginner精度向上 |
| 5 | 1日 | item_url を買取/販売で個別ページ化 | 再現性スコア+30・確認導線改善 |
| 6 | 1日 | ヤフオク落札(公開closedsearch)取得の半自動化 | フリマsold件数増→同条件≥3で再現性中〜高 |
| 7 | 3日 | eBay Finding API 連携実装＋為替反映 | 海外sold常時fresh・海外売却ルート量産 |
| 8 | 1週間 | 価格ソース横断のfreshness監視＋自動再取得基盤 | stale率恒常低下・利益発見率の底上げ |

## Task10: 最終判定

### 総合完成度: **75.6 / 100**

| 観点 | 点数 |
|---|---|
| データ品質 | 78 |
| 利益発見能力 | 55 |
| スクレイピング品質 | 62 |
| UI | 80 |
| 利益精度 | 88 |
| 保守性 | 82 |
| 速度 | 75 |
| 将来性 | 85 |

### 今もっともやるべきこと TOP10

1. EBAY_APP_ID 設定（海外sold fresh化・最大の利益解放）
2. フリマsold（メルカリ/ヤフオク落札）の継続取得運用
3. 買取店 stale の daily fresh 化安定運用
4. official_price を products.yaml へ登録
5. 買取/販売リンクの item_url 個別ページ化
6. ヤフオク closedsearch の半自動取得
7. eBay Finding API 本実装（為替バッファ込み）
8. PS5/Switch の買取¥0(取得失敗)の原因対処 or optional化
9. 同条件sold件数を増やし再現性スコアを引き上げ
10. freshness横断監視＋自動再取得の基盤化
