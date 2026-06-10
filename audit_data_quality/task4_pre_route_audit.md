# Task4: Pro ルート生成前監査（候補価格の4条件チェック）

## サマリ

- Pro対象候補(buy/sell系): 884
- 本体一致 pass: 873 / stale否 pass: 252 / 非0円 pass: 474 / conf≥medium pass: 873
- **4条件すべて pass: 147**（= 利益ルート計算に投入可能な健全価格）
- 不合格内訳: {'body_match_fail': 11, 'stale_fail': 632, 'zero_fail': 410, 'conf_fail': 11}

## 4条件すべて pass した健全価格（最大40件）

| product | role | type | price | source | body | fresh | conf |
|---|---|---|---|---|---|---|---|
| iPhone 17 Pro 256G | sell | buyback_price | ¥181,500 | モバイル一番 | ○ | ○ | ○ |
| iPhone 17 Pro 256G | sell | buyback_price | ¥181,500 | 買取商店 | ○ | ○ | ○ |
| iPhone 17 Pro 256G | sell | buyback_price | ¥157,000 | イオシス | ○ | ○ | ○ |
| iPhone 17 Pro 256G | sell | buyback_price | ¥159,600 | ネットオフ | ○ | ○ | ○ |
| iPhone 17 Pro 512G | sell | buyback_price | ¥215,000 | 買取商店 | ○ | ○ | ○ |
| iPhone 17 Pro 512G | sell | buyback_price | ¥187,000 | イオシス | ○ | ○ | ○ |
| iPhone 17 Pro 512G | sell | buyback_price | ¥190,050 | ネットオフ | ○ | ○ | ○ |
| iPhone 17 Pro Max  | sell | buyback_price | ¥197,500 | モバイル一番 | ○ | ○ | ○ |
| iPhone 17 Pro Max  | sell | buyback_price | ¥197,500 | 買取商店 | ○ | ○ | ○ |
| iPhone 17 Pro Max  | sell | buyback_price | ¥172,000 | イオシス | ○ | ○ | ○ |
| iPhone 17 Pro Max  | sell | buyback_price | ¥173,250 | ネットオフ | ○ | ○ | ○ |
| iPhone 17 Pro Max  | sell | buyback_price | ¥227,000 | 買取商店 | ○ | ○ | ○ |
| iPhone 17 Pro Max  | sell | buyback_price | ¥205,000 | イオシス | ○ | ○ | ○ |
| iPhone 17 Pro Max  | sell | buyback_price | ¥204,750 | ネットオフ | ○ | ○ | ○ |
| Nintendo Switch 2 | sell | buyback_price | ¥50,000 | ゲオ | ○ | ○ | ○ |
| Nintendo Switch 2 | sell | buyback_price | ¥46,000 | イオシス | ○ | ○ | ○ |
| Nintendo Switch 2 | sell | buyback_price | ¥49,800 | 買取商店 | ○ | ○ | ○ |
| PlayStation 5 Pro | sell | buyback_price | ¥100,000 | イオシス | ○ | ○ | ○ |
| PlayStation 5 Pro | sell | buyback_price | ¥134,500 | 買取商店 | ○ | ○ | ○ |
| PlayStation 5 Pro | sell | buyback_price | ¥134,500 | モバイル一番 | ○ | ○ | ○ |
| FUJIFILM X100VI | sell | buyback_price | ¥445,000 | マップカメラ | ○ | ○ | ○ |
| FUJIFILM X100VI | sell | buyback_price | ¥442,000 | カメラのキタムラ | ○ | ○ | ○ |
| FUJIFILM X100VI | sell | buyback_price | ¥440,000 | フジヤカメラ | ○ | ○ | ○ |
| FUJIFILM X100VI | sell | buyback_price | ¥435,000 | ソフマップ | ○ | ○ | ○ |
| FUJIFILM X100VI | sell | buyback_price | ¥430,000 | じゃんぱら | ○ | ○ | ○ |
| FUJIFILM X100VI | sell | buyback_price | ¥428,000 | 買取商店 | ○ | ○ | ○ |
| RICOH GR IV | sell | buyback_price | ¥198,000 | マップカメラ | ○ | ○ | ○ |
| RICOH GR IV | sell | buyback_price | ¥196,000 | カメラのキタムラ | ○ | ○ | ○ |
| RICOH GR IV | sell | buyback_price | ¥194,000 | フジヤカメラ | ○ | ○ | ○ |
| RICOH GR IV | sell | buyback_price | ¥190,000 | ソフマップ | ○ | ○ | ○ |
| RICOH GR IV | sell | buyback_price | ¥188,000 | じゃんぱら | ○ | ○ | ○ |
| RICOH GR IV | sell | buyback_price | ¥185,000 | 買取商店 | ○ | ○ | ○ |
| RICOH GR IV HDF | sell | buyback_price | ¥205,000 | マップカメラ | ○ | ○ | ○ |
| RICOH GR IV HDF | sell | buyback_price | ¥203,000 | カメラのキタムラ | ○ | ○ | ○ |
| RICOH GR IV HDF | sell | buyback_price | ¥200,000 | フジヤカメラ | ○ | ○ | ○ |
| RICOH GR IV HDF | sell | buyback_price | ¥196,000 | ソフマップ | ○ | ○ | ○ |
| RICOH GR IV Monoch | sell | buyback_price | ¥215,000 | マップカメラ | ○ | ○ | ○ |
| RICOH GR IV Monoch | sell | buyback_price | ¥212,000 | カメラのキタムラ | ○ | ○ | ○ |
| RICOH GR IV Monoch | sell | buyback_price | ¥210,000 | フジヤカメラ | ○ | ○ | ○ |
| RICOH GR IV Monoch | sell | buyback_price | ¥205,000 | ソフマップ | ○ | ○ | ○ |
