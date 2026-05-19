# SOUBA 相場ダッシュボード — Claude Code 実装仕様書

> **対象**: Claude Code（AI駆動開発環境）でSOUBAのUIデザインを既存システムに組み込む際の完全リファレンス  
> **バージョン**: v6（2026年5月19日時点）  
> **スタック**: React 19 + TypeScript + Tailwind CSS 4 + Vite

---

## 目次

1. [プロジェクト概要](#1-プロジェクト概要)
2. [技術スタック・依存関係](#2-技術スタック依存関係)
3. [デザインシステム](#3-デザインシステム)
4. [ファイル構成](#4-ファイル構成)
5. [コンポーネント仕様](#5-コンポーネント仕様)
6. [データ型・インターフェース](#6-データ型インターフェース)
7. [ナビゲーション設計](#7-ナビゲーション設計)
8. [APIデータ連携方法](#8-apiデータ連携方法)
9. [Claude Codeへの指示テンプレート](#9-claude-codeへの指示テンプレート)
10. [よくある実装パターン](#10-よくある実装パターン)

---

## 1. プロジェクト概要

### 目的
転売・プレ値・買取価格・海外相場を毎日確認できる**金融系相場ダッシュボード**。

### ターゲットユーザー
| ユーザー層 | 主な用途 |
|---|---|
| 初心者 | iPhone・AirPodsなどの買取差額確認、低難度案件 |
| 上級者 | カメラのプレ値・海外差益・サイト間せどり計算 |

### 主要機能
- **ランキング**: 今日の利益額・利益率上位案件
- **せどり計算**: 複数店舗の買取・販売価格比較、最大利益ルート自動計算
- **初心者向け**: 公式価格・買取価格・実質利益の一覧（買取ページリンク付き）
- **上級者向け**: プレ値・海外相場（eBay/B&H/MPB/KEH/StockX）
- **抽選情報**: 受付中・締切間近・結果待ちの抽選案件
- **ジャンル別**: スマホ/タブレット/PC/カメラ/ゲーム機 × メーカー別サブタブ
- **急騰/急落**: 本日の価格変動アラート

---

## 2. 技術スタック・依存関係

### コアスタック
```json
{
  "react": "^19.2.1",
  "typescript": "5.6.3",
  "tailwindcss": "^4.1.14",
  "vite": "^7.1.7",
  "wouter": "^3.3.5"
}
```

### 主要UIライブラリ
```json
{
  "lucide-react": "^0.453.0",
  "framer-motion": "^12.23.22",
  "recharts": "^2.15.2",
  "@radix-ui/react-*": "各種"
}
```

### インストールコマンド
```bash
pnpm install
pnpm dev
```

---

## 3. デザインシステム

### デザインコンセプト
**「Luxury SaaS meets Financial Terminal」**  
Linear × Vercel × Stripe のデザイン言語を参考に構築。

### カラーパレット

#### ページ背景
```css
--page-bg:     #FAFBFF   /* メインページ背景（白に青みがかった色） */
--surface:     #FFFFFF   /* カード背景 */
--surface-2:   #F7F8FD   /* セカンダリ背景 */
--surface-3:   #F4F5FD   /* タブ・インプット背景 */
```

#### テキスト
```css
--ink-primary:   #0D0F1C  /* 主要テキスト */
--ink-secondary: #5B6278  /* 補助テキスト */
--ink-muted:     #9CA3B8  /* ミュートテキスト */
--ink-disabled:  #C8CADE  /* 無効テキスト */
```

#### アクセントカラー（意味を持つ色）
```css
/* 利益・成功 */
--profit:        #00C896  /* エメラルドグリーン */
--profit-dark:   #00A876
--profit-bg:     #F0FDF8
--profit-border: #A7F3D0

/* 上級者・プレミアム */
--advanced:      #7C5CFC  /* エレクトリックバイオレット */
--advanced-dark: #6040E8
--advanced-bg:   #F0EEFF
--advanced-border: #C4B5FD

/* 注意・警告 */
--warning:       #FF9500  /* アンバー */
--warning-bg:    #FFF8E8
--warning-border: #FCD34D

/* 損失・危険 */
--danger:        #FF3B5C  /* レッド */
--danger-bg:     #FFF1F3
--danger-border: #FECDD3

/* リンク・情報 */
--link:          #3B7BFF  /* ブルー */
--link-bg:       #EEF4FF
--link-border:   #BFDBFE

/* ランキング1位 */
--gold:          #F5A623
```

#### ボーダー
```css
--border-default: #E8EAF2
--border-subtle:  #F1F2F8
```

### タイポグラフィ

#### フォント
```html
<!-- Google Fonts（index.htmlに追加） -->
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet" />
```

| 用途 | フォント | ウェイト |
|---|---|---|
| 見出し・UI | Inter | 700〜900 |
| 本文 | Inter | 400〜500 |
| 価格数値 | JetBrains Mono | 600〜800 |
| ラベル | Inter | 600, uppercase |

#### 価格表示の必須スタイル
```tsx
// 価格数値は必ずfont-monoクラスを使用
<span
  className="font-mono"
  style={{ fontFamily: "'JetBrains Mono', monospace", fontFeatureSettings: '"tnum"' }}
>
  ¥159,800
</span>
```

### スペーシング
- カードパディング: `p-5`（20px）
- セクション間: `py-16`（64px）
- カードギャップ: `gap-5`（20px）
- ボーダーRadius: `rounded-2xl`（16px）カード、`rounded-xl`（12px）ボタン

### シャドウ
```css
/* カード通常 */
box-shadow: 0 1px 3px rgba(13,15,28,0.05), 0 1px 2px rgba(13,15,28,0.04);

/* カードホバー */
box-shadow: 0 12px 40px rgba(13,15,28,0.1), 0 4px 12px rgba(13,15,28,0.06);

/* プライマリボタン */
box-shadow: 0 4px 16px rgba(0,200,150,0.35);
```

### CSSクラス（カスタム）

```css
/* カード */
.souba-card { /* 白背景・ボーダー・ホバーアニメーション */ }

/* ボタン */
.btn-primary { /* グリーングラデーション */ }
.btn-violet  { /* バイオレットグラデーション */ }
.btn-ghost   { /* 半透明白 */ }

/* プロフィットスコアバッジ */
.score-s { /* 金色グラデーション */ }
.score-a { /* グリーン */ }
.score-b { /* ブルー */ }
.score-c { /* グレー */ }

/* テーブル */
.souba-table    { /* Bloomberg風テーブル */ }
.souba-table th { /* ヘッダースタイル */ }
.souba-table td { /* セルスタイル */ }
.row-best       { /* 最高値行ハイライト */ }

/* アニメーション */
.fade-in-up  { /* スクロール時フェードイン */ }
.live-pulse  { /* ライブインジケーター点滅 */ }
.press-effect { /* ボタン押下エフェクト */ }
.tab-scroll  { /* スクロールバー非表示 */ }
```

---

## 4. ファイル構成

```
client/src/
├── pages/
│   └── Home.tsx                 # メインページ（タブ状態管理）
├── components/
│   ├── SiteHeader.tsx           # 固定ヘッダー（onTabChange prop必須）
│   ├── HeroSection.tsx          # ヒーロー（onTabChange prop必須）
│   ├── LiveTicker.tsx           # 価格スクロールティッカー
│   ├── FeaturesBanner.tsx       # 機能チップ一覧（コンパクト）
│   ├── StickyTabs.tsx           # スティッキータブナビ（TabId型）
│   ├── GenreDrillDown.tsx       # ジャンル→メーカー2段階ナビ
│   ├── RankingSection.tsx       # ランキング（総合/iPhone/カメラ/ゲーム）
│   ├── SedoriCalculator.tsx     # せどり計算テーブル
│   ├── BeginnerSection.tsx      # 初心者向けカード
│   ├── BuybackTable.tsx         # 買取価格比較テーブル
│   ├── AdvancedSection.tsx      # 上級者向けカード
│   ├── OverseasLinks.tsx        # 海外相場リンクチップ
│   ├── SurgeSection.tsx         # 急騰/急落
│   ├── LotterySection.tsx       # 抽選情報
│   ├── GenreSection.tsx         # ジャンル別（メーカーサブタブ付き）
│   ├── NewProductsSection.tsx   # 新商品速報
│   ├── NoteCTA.tsx              # note誘導CTA
│   └── SiteFooter.tsx           # フッター（onTabChange prop必須）
├── lib/
│   └── data.ts                  # 型定義・モックデータ・ヘルパー関数
├── hooks/
│   └── useScrollAnimation.ts    # スクロールアニメーション
└── index.css                    # デザインシステム（全CSSカスタムクラス）
```

---

## 5. コンポーネント仕様

### 5.1 Home.tsx（状態管理の中心）

```tsx
// タブIDの型
export type TabId =
  | 'ranking' | 'sedori' | 'beginner' | 'advanced' | 'surge' | 'lottery'
  | 'smartphone' | 'tablet' | 'pc' | 'camera' | 'game';

// 状態
const [activeTab, setActiveTab] = useState<TabId>('ranking');

// タブ切り替え関数（全コンポーネントに渡す）
const handleTabChange = useCallback((tab: TabId) => {
  setActiveTab(tab);
  // StickyTabsまでスクロール
  setTimeout(() => {
    const el = document.querySelector('[data-sticky-tabs]');
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + scrollY - 10, behavior: 'smooth' });
  }, 80);
}, []);

// Props渡しパターン
<SiteHeader onTabChange={handleTabChange} />
<HeroSection onTabChange={handleTabChange} />
<SiteFooter onTabChange={handleTabChange} />
```

### 5.2 SiteHeader.tsx

```tsx
interface SiteHeaderProps {
  onTabChange: (tab: TabId) => void;
}

// ナビゲーション項目（順序固定）
const navItems = [
  { label: 'スマホ',     tab: 'smartphone' },
  { label: 'タブレット', tab: 'tablet' },
  { label: 'PC',         tab: 'pc' },
  { label: 'カメラ',     tab: 'camera' },
  { label: 'ゲーム機',   tab: 'game' },
  { label: 'せどり計算', tab: 'sedori' },
  { label: 'ランキング', tab: 'ranking' },
  { label: '抽選情報',   tab: 'lottery' },
];
```

### 5.3 StickyTabs.tsx

```tsx
// タブ順序（変更禁止）
// Main: ranking → sedori → beginner → advanced → surge → lottery
// Genre: smartphone → tablet → pc → camera → game

// data-sticky-tabs属性が必須（スクロールターゲット）
<div data-sticky-tabs className="sticky z-40" ...>
```

### 5.4 GenreSection.tsx

```tsx
export type GenreId = 'smartphone' | 'tablet' | 'pc' | 'camera' | 'game';

interface GenreSectionProps {
  genre: GenreId;
}

// メーカーサブタブ構造
const makerTabs: Record<GenreId, { id: string; label: string }[]> = {
  smartphone: ['all', 'apple', 'samsung', 'google', 'sony', 'sharp'],
  tablet:     ['all', 'apple', 'samsung', 'microsoft', 'amazon'],
  pc:         ['all', 'apple', 'microsoft', 'lenovo', 'dell', 'hp'],
  camera:     ['all', 'fujifilm', 'ricoh', 'leica', 'sony', 'nikon', 'canon'],
  game:       ['all', 'nintendo', 'sony', 'microsoft'],
};
```

### 5.5 SedoriCalculator.tsx

```tsx
interface StoreData {
  id: string;
  name: string;
  buyPrice: number;    // 買取価格（この店が買い取る価格）
  sellPrice: number;   // 販売価格（この店で売られている価格）
  url: string;
  fee: number;         // 手数料率(%)
  shippingCost: number;
}

// 利益計算ロジック
const grossProfit = sellStore.buyPrice - buyStore.sellPrice;
const fees = Math.round(sellStore.buyPrice * (sellStore.fee / 100)) + shippingCost;
const netProfit = grossProfit - fees;
const profitRate = Math.round((netProfit / buyStore.sellPrice) * 1000) / 10;
```

### 5.6 LotterySection.tsx

```tsx
type LotteryStatus = 'open' | 'closing_soon' | 'pending' | 'ended';

interface LotteryItem {
  id: string;
  name: string;
  category: string;
  image: string;
  officialPrice: number;
  officialUrl: string;          // 公式ページURL（必須）
  expectedResalePrice: number;
  expectedProfit: number;
  status: LotteryStatus;
  deadline: string;
  resultDate?: string;
  applyUrl: string;             // 応募ページURL（必須）
  storeUrls: { name: string; url: string }[];
  difficulty: 'easy' | 'medium' | 'hard';
  winRate?: string;
  notes: string;
  tags: string[];
}
```

---

## 6. データ型・インターフェース

### BeginnerItem（初心者向け案件）

```typescript
interface BeginnerItem {
  id: string;
  name: string;
  shortName: string;
  category: 'apple' | 'camera' | 'game' | 'pc';
  image: string;
  officialPrice: number;
  officialUrl: string;          // ★ Apple Store等の公式購入ページURL
  topBuybackPrice: number;
  profit: number;               // topBuybackPrice - officialPrice
  profitRate: number;           // (profit / officialPrice) * 100
  updatedAt: string;            // "12:00" 形式
  storeCount: number;
  stores: StorePrice[];
  note: string;
  trend: 'up' | 'down' | 'stable';
}

interface StorePrice {
  name: string;
  price: number;
  url: string;                  // ★ 各店舗の買取ページURL（必須）
  isTop?: boolean;
}
```

### 買取ページURL一覧（実際のURL）

```typescript
// 各店舗の買取ページURL（スマホカテゴリ例）
const buybackUrls = {
  geo:       'https://geo-online.co.jp/store/contents/buy/smartphone/',
  bookoff:   'https://www.bookoffonline.co.jp/old/0001-mobile-kaitori.html',
  hardoff:   'https://www.hardoff.co.jp/kaitori/',
  iosys:     'https://iosys.co.jp/kaitori/',
  janpara:   'https://www.janpara.co.jp/sale/kaitori/',
  sofmap:    'https://www.sofmap.com/buy/',
  biccamera: 'https://www.biccamera.com/bc/c/kaitori/',
  yamada:    'https://www.yamada-denki.jp/service/kaitori/',
  // カメラ系
  mapcamera: 'https://www.mapcamera.com/kaitori/',
  kitamura:  'https://www.kitamura.jp/service/kaitori/',
  // ゲーム系
  surugaya:  'https://www.suruga-ya.jp/kaitori',
};

// 公式購入ページURL（カテゴリ別）
const officialUrls = {
  iphone16pro:    'https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro',
  iphone16:       'https://www.apple.com/jp/shop/buy-iphone/iphone-16',
  macbookAirM3:   'https://www.apple.com/jp/shop/buy-mac/macbook-air/13-inch',
  macbookProM4:   'https://www.apple.com/jp/shop/buy-mac/macbook-pro/14-inch',
  ipadAirM2:      'https://www.apple.com/jp/shop/buy-ipad/ipad-air',
  ipadProM4:      'https://www.apple.com/jp/shop/buy-ipad/ipad-pro',
  airpodsPro2:    'https://www.apple.com/jp/shop/buy-airpods/airpods-pro',
  appleWatchU2:   'https://www.apple.com/jp/shop/buy-watch/apple-watch-ultra',
  switchOled:     'https://store.nintendo.co.jp/category/NINTENDO_SWITCH_MAIN_UNIT/HAC-S-KAAAA.html',
  switch2:        'https://store.nintendo.co.jp/',
  ps5slim:        'https://direct.playstation.com/ja-jp/hardware/ps5',
  fujiX100vi:     'https://fujifilm-x.com/ja-jp/products/cameras/x100vi/',
  ricohGrIIIx:    'https://www.ricoh-imaging.co.jp/japan/products/gr-3x/',
  leicaQ3:        'https://leica-camera.com/ja-JP/photography/cameras/q/q3-black',
};
```

### ヘルパー関数

```typescript
// 価格フォーマット
export const formatPrice = (price: number): string =>
  `¥${price.toLocaleString('ja-JP')}`;

export const formatUSD = (price: number): string =>
  `$${price.toLocaleString('en-US')}`;

// プロフィットスコア計算
function getProfitScore(profitRate: number): { grade: 'S'|'A'|'B'|'C'; cssClass: string } {
  if (profitRate >= 20) return { grade: 'S', cssClass: 'score-s' };
  if (profitRate >= 15) return { grade: 'A', cssClass: 'score-a' };
  if (profitRate >= 10) return { grade: 'B', cssClass: 'score-b' };
  return { grade: 'C', cssClass: 'score-c' };
}
```

---

## 7. ナビゲーション設計

### タブ遷移フロー

```
ユーザーアクション
    │
    ▼
handleTabChange(tab: TabId)
    │
    ├─ setActiveTab(tab)        // React状態更新
    │
    └─ scrollToContent()        // [data-sticky-tabs]要素までスクロール
         └─ setTimeout 80ms     // DOM更新後にスクロール実行
```

### タブ順序（変更禁止）

```
[ランキング] [せどり計算 NEW] [初心者向け 12] [上級者向け 8] [急騰/急落 HOT] [抽選情報 6]
 ─────────────────────────────────────────────────────────────────────────────
 ジャンル: [スマホ] [タブレット] [PC] [カメラ] [ゲーム機]
```

### ジャンル→メーカー2段階ドリルダウン

```
GenreDrillDown コンポーネント
    │
    ├─ ジャンルボタンクリック
    │   ├─ onTabChange(genre)    // タブ切り替え
    │   └─ setSelectedGenre()    // メーカー一覧を展開
    │
    └─ メーカーボタンクリック
        └─ onTabChange(genre)    // 同ジャンルのGenreSectionへ
                                  // ※ GenreSection内でメーカーフィルター
```

---

## 8. APIデータ連携方法

### 現在の構造（モックデータ）

```typescript
// client/src/lib/data.ts
// 現在はすべてハードコードされたモックデータ
export const beginnerItems: BeginnerItem[] = [...];
export const rankingData = { overall: [...], iphone: [...], ... };
```

### APIに切り替える場合

```typescript
// 推奨パターン: useEffect + fetch
import { useState, useEffect } from 'react';

function BeginnerSection() {
  const [items, setItems] = useState<BeginnerItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch('/api/items/beginner')
      .then(r => r.json())
      .then(data => setItems(data))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="souba-card p-5">
            <div className="skeleton h-14 w-14 rounded-2xl mb-4" />
            <div className="skeleton h-4 w-3/4 rounded mb-2" />
            <div className="skeleton h-8 w-full rounded" />
          </div>
        ))}
      </div>
    );
  }

  return <div className="grid ...">...</div>;
}
```

### 推奨APIエンドポイント設計

```typescript
// GET /api/items/beginner
// Response: BeginnerItem[]

// GET /api/items/advanced
// Response: AdvancedItem[]

// GET /api/ranking?category=overall|iphone|camera|game
// Response: RankingItem[]

// GET /api/lottery?status=open|closing_soon|pending|ended
// Response: LotteryItem[]

// GET /api/genre?type=smartphone|tablet|pc|camera|game&maker=all|apple|...
// Response: ProductItem[]

// GET /api/sedori/products
// Response: SedoriProduct[]

// GET /api/stats/hero
// Response: { updatedAt, beginnerCount, advancedCount, maxProfit, totalItems }
```

### リアルタイム更新（WebSocket）

```typescript
// 価格ティッカーのリアルタイム化
useEffect(() => {
  const ws = new WebSocket('wss://your-api.com/prices');
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    setTickerItems(data.prices);
  };
  return () => ws.close();
}, []);
```

---

## 9. Claude Codeへの指示テンプレート

### 基本指示（プロジェクト開始時）

```
このプロジェクトはSOUBA相場ダッシュボードです。
- React 19 + TypeScript + Tailwind CSS 4 + Vite
- デザインシステム: client/src/index.css に定義済み
- 型定義: client/src/lib/data.ts を参照
- 全ナビゲーションは onTabChange(tab: TabId) 関数で統一
- 価格数値は必ず font-mono クラス + JetBrains Mono フォントを使用
- 公式価格には officialUrl リンクを必ず付与
- 買取価格の各店舗には buyUrl（実際の買取ページURL）を必ず付与
```

### コンポーネント追加時の指示

```
新しいコンポーネントを追加する場合:
1. client/src/components/ に配置
2. souba-card クラスを使用（カードUI）
3. fade-in-up クラスでスクロールアニメーション
4. 価格は formatPrice() 関数でフォーマット
5. プロフィットスコアは getProfitScore() 関数を使用
6. ボタンは btn-primary / btn-violet / btn-ghost クラスを使用
7. タブ遷移が必要な場合は onTabChange prop を受け取る
```

### データ更新時の指示

```
商品データを更新する場合:
- client/src/lib/data.ts の該当配列を編集
- officialUrl: 公式購入ページのURL（必須）
- stores[].url: 各店舗の買取ページURL（必須、ダミーURL不可）
- profit = topBuybackPrice - officialPrice で計算
- profitRate = (profit / officialPrice * 100) を小数点1桁で設定
```

### API連携時の指示

```
モックデータをAPIに切り替える場合:
1. client/src/lib/data.ts のエクスポートをAPI呼び出しに変更
2. ローディング中は .skeleton クラスでスケルトンUI表示
3. エラー時は AlertCircle アイコン + エラーメッセージ表示
4. キャッシュは useState + useEffect で管理（SWR/React Query推奨）
```

---

## 10. よくある実装パターン

### パターン1: 新しいカードコンポーネント

```tsx
// 標準的なカードの構造
function ProductCard({ item, index }: { item: ProductItem; index: number }) {
  return (
    <div
      className="souba-card fade-in-up"
      style={{ animationDelay: `${index * 70}ms`, overflow: 'hidden' }}
    >
      {/* 利益率プログレスバー（上部） */}
      <div style={{
        height: '3px',
        background: `linear-gradient(90deg, #00C896 ${Math.min(item.profitRate * 4, 100)}%, #E8EAF2 0%)`
      }} />

      <div className="p-5">
        {/* 商品画像 + 名前 + スコア */}
        <div className="flex items-start gap-3 mb-4">
          <div className="w-14 h-14 rounded-2xl overflow-hidden flex-shrink-0"
            style={{ background: '#F4F5FD', border: '1px solid #E8EAF2' }}>
            <img src={item.image} alt={item.name} className="w-full h-full object-cover" loading="lazy" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-bold" style={{ color: '#0D0F1C' }}>{item.name}</h3>
          </div>
          {/* プロフィットスコアバッジ */}
          <div className={`score-badge ${getProfitScore(item.profitRate).cssClass}`}>
            {getProfitScore(item.profitRate).grade}
          </div>
        </div>

        {/* 価格ブロック */}
        <div className="rounded-2xl p-4 mb-4" style={{ background: '#F7F8FD', border: '1px solid #E8EAF2' }}>
          <div className="grid grid-cols-2 gap-3 mb-3">
            {/* 公式価格（リンク付き） */}
            <div>
              <div className="flex items-center gap-1 mb-1">
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#9CA3B8' }}>
                  公式価格
                </span>
                <a href={item.officialUrl} target="_blank" rel="noopener noreferrer" style={{ color: '#3B7BFF' }}>
                  <Link2 size={10} />
                </a>
              </div>
              <a href={item.officialUrl} target="_blank" rel="noopener noreferrer"
                className="text-base font-bold font-mono"
                style={{ color: '#5B6278', fontFamily: "'JetBrains Mono', monospace", textDecoration: 'none' }}>
                {formatPrice(item.officialPrice)}
              </a>
            </div>
            {/* 最高買取価格 */}
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: '#9CA3B8' }}>
                最高買取
              </div>
              <div className="text-base font-bold font-mono"
                style={{ color: '#0D0F1C', fontFamily: "'JetBrains Mono', monospace" }}>
                {formatPrice(item.topBuybackPrice)}
              </div>
            </div>
          </div>

          {/* 利益ハイライト */}
          <div className="flex items-center justify-between px-4 py-3 rounded-xl"
            style={{ background: 'linear-gradient(135deg, #F0FDF8, #E8FFF4)', border: '1px solid #A7F3D0' }}>
            <div>
              <div className="text-xs font-bold uppercase tracking-wider mb-0.5" style={{ color: '#047857' }}>
                実質利益
              </div>
              <div className="text-2xl font-black font-mono"
                style={{ color: '#00C896', fontFamily: "'JetBrains Mono', monospace" }}>
                +{formatPrice(item.profit)}
              </div>
            </div>
            <div className="text-right">
              <div className="text-xs mb-0.5" style={{ color: '#9CA3B8' }}>利益率</div>
              <div className="text-xl font-black font-mono"
                style={{ color: '#00A876', fontFamily: "'JetBrains Mono', monospace" }}>
                +{item.profitRate}%
              </div>
            </div>
          </div>
        </div>

        {/* 注意文 */}
        <div className="flex items-start gap-2 px-3 py-2.5 rounded-xl"
          style={{ background: '#FFFBEB', border: '1px solid #FCD34D' }}>
          <AlertCircle size={12} className="flex-shrink-0 mt-0.5" style={{ color: '#FF9500' }} />
          <p className="text-xs leading-relaxed" style={{ color: '#92400E' }}>{item.note}</p>
        </div>
      </div>
    </div>
  );
}
```

### パターン2: 店舗比較行（買取ページリンク付き）

```tsx
// 店舗比較の標準パターン
{stores.map((store) => (
  <div key={store.name}
    className="flex items-center justify-between px-3 py-2.5 rounded-xl"
    style={{
      background: store.isTop ? '#F0FDF8' : '#FAFBFF',
      border: `1px solid ${store.isTop ? '#A7F3D0' : '#E8EAF2'}`
    }}>
    <div className="flex items-center gap-2">
      {store.isTop && (
        <span className="text-xs px-1.5 py-0.5 rounded-full font-black"
          style={{ background: '#00C896', color: '#fff', fontSize: '9px' }}>TOP</span>
      )}
      <span className="text-xs font-semibold" style={{ color: store.isTop ? '#0D0F1C' : '#5B6278' }}>
        {store.name}
      </span>
    </div>
    <div className="flex items-center gap-2">
      <span className="text-sm font-black font-mono"
        style={{ color: store.isTop ? '#00A876' : '#0D0F1C', fontFamily: "'JetBrains Mono', monospace" }}>
        {formatPrice(store.price)}
      </span>
      {/* 買取ページへの直接リンク（必須） */}
      <a href={store.url} target="_blank" rel="noopener noreferrer"
        className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-bold press-effect"
        style={{
          background: store.isTop ? '#00C896' : '#F4F5FD',
          color: store.isTop ? '#fff' : '#3B7BFF',
          border: store.isTop ? 'none' : '1px solid #E8EAF2'
        }}>
        買取 <ExternalLink size={9} />
      </a>
    </div>
  </div>
))}
```

### パターン3: セクションヘッダー

```tsx
// 標準セクションヘッダーパターン
<div className="flex items-center justify-between mb-8">
  <div>
    <div className="flex items-center gap-3 mb-3">
      <div className="w-1.5 h-5 rounded-full section-bar-green" />  {/* 色はgreen/purple/amber/blue */}
      <span className="section-label section-label-green">Beginner</span>
      <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full"
        style={{ background: '#E8FFF6', border: '1px solid #A7F3D0' }}>
        <div className="w-1.5 h-1.5 rounded-full live-pulse" style={{ background: '#00C896' }} />
        <span className="text-xs font-bold" style={{ color: '#047857' }}>12件掲載中</span>
      </div>
    </div>
    <h2 className="text-2xl font-black" style={{ color: '#0D0F1C', letterSpacing: '-0.03em' }}>
      セクションタイトル
    </h2>
    <p className="text-sm mt-1" style={{ color: '#5B6278' }}>サブタイトル</p>
  </div>
</div>
```

### パターン4: タブ切り替えボタン（セクション内）

```tsx
// セクション内のフィルタータブ
<div className="flex items-center gap-1.5 flex-wrap mb-8 p-1 rounded-2xl w-fit"
  style={{ background: '#F4F5FD', border: '1px solid #E8EAF2' }}>
  {tabs.map(tab => {
    const isActive = activeFilter === tab.id;
    return (
      <button key={tab.id} onClick={() => setActiveFilter(tab.id)}
        className="px-3.5 py-1.5 rounded-xl text-sm font-semibold transition-all duration-150 press-effect whitespace-nowrap"
        style={{
          background: isActive ? '#FFFFFF' : 'transparent',
          color: isActive ? activeColor : '#9CA3B8',
          border: isActive ? `1px solid ${activeBorder}` : '1px solid transparent',
          boxShadow: isActive ? '0 1px 4px rgba(13,15,28,0.08)' : 'none',
          fontWeight: isActive ? 700 : 500,
        }}>
        {tab.label}
      </button>
    );
  })}
</div>
```

---

## 付録: 重要なURL一覧

### 海外相場サイト
| サービス | URL | 用途 |
|---|---|---|
| eBay Sold | `https://www.ebay.com/sch/i.html?_nkw=...&LH_Sold=1&LH_Complete=1` | 落札済み価格 |
| B&H Photo | `https://www.bhphotovideo.com` | 米国カメラ専門店 |
| MPB | `https://www.mpb.com` | 中古カメラ英国 |
| KEH Camera | `https://www.keh.com` | 中古カメラ米国 |
| Adorama | `https://www.adorama.com` | 米国カメラ・家電 |
| StockX | `https://stockx.com` | スニーカー・ゲーム機 |
| Swappa | `https://swappa.com` | 中古スマホ米国 |
| Back Market | `https://www.backmarket.com` | 欧州リファービッシュ |

### 国内買取サイト（カテゴリ別）
| 店舗 | スマホ | タブレット | PC | カメラ | ゲーム |
|---|---|---|---|---|---|
| ゲオ | [リンク](https://geo-online.co.jp/store/contents/buy/smartphone/) | [リンク](https://geo-online.co.jp/store/contents/buy/tablet/) | [リンク](https://geo-online.co.jp/store/contents/buy/pc/) | — | [リンク](https://geo-online.co.jp/store/contents/buy/game/) |
| ブックオフ | [リンク](https://www.bookoffonline.co.jp/old/0001-mobile-kaitori.html) | [リンク](https://www.bookoffonline.co.jp/old/0001-tablet-kaitori.html) | [リンク](https://www.bookoffonline.co.jp/old/0001-pc-kaitori.html) | — | [リンク](https://www.bookoffonline.co.jp/old/0001-game-kaitori.html) |
| ハードオフ | [リンク](https://www.hardoff.co.jp/kaitori/) | [リンク](https://www.hardoff.co.jp/kaitori/) | [リンク](https://www.hardoff.co.jp/kaitori/) | [リンク](https://www.hardoff.co.jp/kaitori/) | [リンク](https://www.hardoff.co.jp/kaitori/) |
| マップカメラ | — | — | — | [リンク](https://www.mapcamera.com/kaitori/) | — |
| キタムラ | — | — | — | [リンク](https://www.kitamura.jp/service/kaitori/) | — |
| 駿河屋 | — | — | — | — | [リンク](https://www.suruga-ya.jp/kaitori) |

---

*このドキュメントはSOUBA v6（2026年5月19日）時点の仕様です。*
