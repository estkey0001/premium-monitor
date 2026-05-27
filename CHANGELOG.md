# CHANGELOG

## [stable-collector-2026-05-27] — 2026-05-27

### GitHub Actions 安定確認

- **Run**: [#26505153639](https://github.com/estkey0001/premium-monitor/actions/runs/26505153639)
- **Result**: `completed / success`
- **deploy-check**: Errors: 0 / Warnings: 0 / OK: 271
- **collector quality gate**: `FAILURES=0  WARNINGS=1  OPT_WARNINGS=1`
  - WARNING: 取得失敗率 54.5%（optional 店舗の失敗によるもの — LP 品質に影響なし）
- **suspicious_price**: 0
- **low_confidence**: 0

### 主要改善点

#### required 店舗の取得率改善

| 店舗 | 修正前 | 修正後 |
|------|--------|--------|
| `kaitori_itchome` × iphone17pro256 | `empty_html` (networkidle timeout) | ✅ **Y181,500** |
| `kaitori_itchome` × iphone17pro512 | `empty_html` | ✅ **Y215,000** |
| `kaitori_itchome` × iphone17pm256  | `empty_html` | ✅ **Y197,500** |
| `kaitori_itchome` × iphone17pm512  | `empty_html` | ✅ **Y231,500** |
| `geo` × switch2                   | Y50,000 ✅（維持） | ✅ Y50,000 |
| `geo` × ps5_pro                   | `price_not_found` | ✅ `product_not_listed`（正確な分類） |
| `netoff` × 全iPhone               | `price_not_found` | ✅ 全4モデル取得成功（前フェーズ修正済み） |
| `pasoko`                           | `price_not_found` | ✅ `product_not_listed`（PC専門店） |

#### OPTIONAL_SHOPS 分類整備

以下の店舗を `OPTIONAL_SHOPS` に追加。品質ゲート・LP 警告バーの required/optional 分離を実装。

| 店舗 | 分類理由 |
|------|---------|
| `geo` | iPhone 17/PS5 Pro 未掲載（Switch2 は取得成功） |
| `tsutaya` | オンライン自動見積もり非対応（`NOT_SUPPORTED_SHOPS`） |
| `janpara` | GitHub Actions IP で全リクエスト 429 ブロック |
| `sofmap` | 503 サーバー障害継続中 |
| `surugaya` | 403 ボット検知、改善不可 |

#### 技術的修正

- `buyback_kaitori_itchome.py`: `wait_for_load_state("networkidle")` → `domcontentloaded` に変更。SPA では networkidle が永遠に完了しないためタイムアウトが発生していた。2 回リトライ + 5 秒追加待機も追加。
- `buyback_geo.py`: ps5_pro / iPhone 17 を `_NOT_LISTED` に定義し `fetch()` override で `product_not_listed` を返すよう変更。
- `check_collector_quality.py`: OPTIONAL_SHOPS に geo / tsutaya 追加。Required / Optional の分離表示実装。
- `daily_lp_generator.py`: LP 警告バーを 3 段階（strong / soft / info）に分離。optional 失敗のみの場合は `collector-warn-info` の軽微な表示に。
- `deploy_check.py`: #256〜#265 の自動検証チェックを追加。

### 安定条件（この状態を維持すること）

```
workflow:            success
collector FAILURES:  0
suspicious_price:    0
low_confidence:      0
deploy-check:        0 errors / 0 warnings (GitHub Actions 上)
kaitori_itchome:     全4モデル取得成功
geo switch2:         取得成功 (Y50,000)
geo ps5_pro:         product_not_listed（許容）
tsutaya:             SKIP / not_supported（許容）
初心者/Proカード:    消失なし
```

---

## [Phase 13完了] — 2026-05 以前

Phase 13完了。LP公開準備完了。prelaunch-check PASS (0 errors, 3 warnings)。
Warnings は GA ID / note_url / site_url の未設定（公開後に設定可能）。
