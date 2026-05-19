# SOUBA ダッシュボード デザインアイデア

## 選定アプローチ：Bloomberg Terminal × Apple Design Language

---

<response>
<text>
## アプローチ A：Dark Terminal Precision（確率: 0.07）

**Design Movement:** Bloomberg Terminal meets Apple SF Pro — 金融情報の密度と Apple の余白美の融合

**Core Principles:**
1. 情報密度と余白の共存 — データは密に、UIは呼吸する
2. 色は意味を持つ — Green=利益、Purple=上級、Orange=警告、Blue=リンク
3. 数値が主役 — タイポグラフィは数値を際立たせるために存在する
4. 信頼感の演出 — ギラギラしない、落ち着いた高級感

**Color Philosophy:**
- 背景: #0B0F17（深宇宙ブラック）、#111827（カード背景）
- アクセント: #10B981（エメラルドグリーン）、#8B5CF6（バイオレット）、#F59E0B（アンバー）
- テキスト: #F8FAFC（プライマリ）、#94A3B8（セカンダリ）
- ボーダー: rgba(255,255,255,0.08)（極細、存在感を消す）

**Layout Paradigm:**
- ヘッダー固定、左右非対称グリッド
- Hero: 全幅 + 右側に数値パネル（Bloomberg風）
- カード: 2-3カラムマソンリー風
- テーブル: フル幅、行間隔広め

**Signature Elements:**
1. 価格変動の緑/赤グロー効果（subtle box-shadow）
2. 数値の monospace フォント（JetBrains Mono）
3. セクション区切りの細いグラデーションライン

**Interaction Philosophy:**
- hover: 0.15s ease-out、scale(1.01)、border-color変化
- tab切り替え: sliding indicator
- 数値: count-up animation on scroll

**Animation:**
- fade-in + translateY(8px) → translateY(0) on scroll
- カード hover: subtle glow
- タブ: 200ms sliding underline
- スケルトンローディング

**Typography System:**
- Display: Inter 700/800（見出し）
- Body: Inter 400/500（本文）
- Numbers: JetBrains Mono 600（価格数値）
- Label: Inter 500 uppercase tracking-wider（ラベル）
</text>
<probability>0.07</probability>
</response>

<response>
<text>
## アプローチ B：Obsidian Glass（確率: 0.06）

**Design Movement:** Arc Browser × Linear — ガラス素材とネオンアクセントの融合

**Core Principles:**
1. Glassmorphism を主役に — backdrop-blur + 半透明パネル
2. 微細なグラデーション背景 — 完全フラットを避ける
3. ネオングロー — 利益数値にのみ使用、乱用禁止
4. 流動的な境界線 — border-radius 16-24px

**Color Philosophy:**
- 背景: radial-gradient(#0D1117, #0B0F1A)
- ガラス: rgba(255,255,255,0.04) + backdrop-blur(20px)
- アクセント: #00D4AA（ティール）、#7C3AED（ディープパープル）

**Layout Paradigm:**
- フローティングカード群
- 背景に抽象的な光の粒子（CSS only）
- 非対称な2カラム

**Signature Elements:**
1. ガラスパネル（backdrop-blur）
2. 微細なノイズテクスチャ背景
3. 数値のグロー効果

**Interaction Philosophy:**
- hover: glow強化
- click: ripple effect

**Animation:**
- パーティクル背景（軽量CSS）
- カードの浮遊感

**Typography System:**
- Display: Syne 800
- Body: Inter 400
- Numbers: Space Mono
</text>
<probability>0.06</probability>
</response>

<response>
<text>
## アプローチ C：Monochrome Precision（確率: 0.05）

**Design Movement:** Stripe × Notion — 極限のミニマリズムと情報設計

**Core Principles:**
1. 白黒2色 + 1アクセントカラーのみ
2. タイポグラフィで全階層を表現
3. ボーダーは細く、影は使わない
4. 余白で格を出す

**Color Philosophy:**
- 背景: #FAFAFA（ほぼ白）
- テキスト: #0A0A0A
- アクセント: #16A34A（グリーンのみ）

**Layout Paradigm:**
- 新聞レイアウト風
- 縦長の情報密度

**Signature Elements:**
1. 太い見出しと細い本文のコントラスト
2. 罫線のみのテーブル

**Interaction Philosophy:**
- hover: 背景色変化のみ
- 極めてシンプル

**Animation:**
- なし（意図的）

**Typography System:**
- Display: Playfair Display 900
- Body: Inter 400
- Numbers: Tabular nums
</text>
<probability>0.05</probability>
</response>

---

## 選定: アプローチ A「Dark Terminal Precision」

Bloomberg Terminal × Apple Design Language の融合。
金融系ダッシュボードとしての信頼感を最優先に、数値の可読性と高級感を両立する。
