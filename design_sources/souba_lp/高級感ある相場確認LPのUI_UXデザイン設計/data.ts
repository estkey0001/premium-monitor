// ============================================================
// SOUBA — Mock Data & Types v4
// 買取ページURL・公式ページURL付き
// ============================================================

export type Difficulty = 'beginner' | 'advanced';
export type Category   = 'apple' | 'camera' | 'game' | 'pc';
export type Status     = 'active' | 'soldout' | 'lottery' | 'preorder';

export interface BeginnerItem {
  id: string;
  name: string;
  shortName: string;
  category: Category;
  image: string;
  officialPrice: number;
  officialUrl: string;          // 公式購入ページ
  topBuybackPrice: number;
  profit: number;
  profitRate: number;
  updatedAt: string;
  storeCount: number;
  stores: StorePrice[];
  note: string;
  trend: 'up' | 'down' | 'stable';
}

export interface StorePrice {
  name: string;
  price: number;
  url: string;      // 買取ページURL
  isTop?: boolean;
}

export interface BuybackStore {
  rank: number;
  name: string;
  price: number;
  diff: number;
  updatedAt: string;
  url: string;      // 買取ページURL
  isTop?: boolean;
}

export interface AdvancedItem {
  id: string;
  name: string;
  shortName: string;
  category: Category;
  image: string;
  tags: string[];
  status: Status;
  domesticUsedPrice: number | null;
  ebayPrice: number | null;
  bnhPrice: number | null;
  mpbPrice: number | null;
  kehPrice: number | null;
  stockxPrice: number | null;
  premiumRate: number;
  updatedAt: string;
  lotteryDeadline?: string;
  note: string;
  difficulty: 'high' | 'very-high';
}

export interface RankingItem {
  rank: number;
  name: string;
  category: Category;
  profit: number;
  profitRate: number;
  image: string;
}

export interface NewProduct {
  id: string;
  name: string;
  category: Category;
  releaseDate: string;
  status: 'lottery' | 'preorder' | 'upcoming';
  targetUser: Difficulty;
  expectedProfit: number | null;
  reason: string;
  image: string;
}

// ============================================================
// Beginner Items — 公式URL・買取ページURL付き
// ============================================================

export const beginnerItems: BeginnerItem[] = [
  {
    id: 'iphone-16-pro-256',
    name: 'iPhone 16 Pro 256GB ナチュラルチタニウム',
    shortName: 'iPhone 16 Pro 256GB',
    category: 'apple',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp',
    officialPrice: 159800,
    officialUrl: 'https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro',
    topBuybackPrice: 186200,
    profit: 26400,
    profitRate: 16.5,
    updatedAt: '12:00',
    storeCount: 8,
    stores: [
      { name: 'ゲオ',       price: 186200, url: 'https://geo-online.co.jp/store/contents/buy/smartphone/', isTop: true },
      { name: 'ブックオフ', price: 182000, url: 'https://www.bookoffonline.co.jp/old/0001-mobile-kaitori.html' },
      { name: 'ハードオフ', price: 178000, url: 'https://www.hardoff.co.jp/kaitori/' },
      { name: 'イオシス',   price: 175000, url: 'https://iosys.co.jp/kaitori/' },
      { name: 'じゃんぱら', price: 172000, url: 'https://www.janpara.co.jp/sale/kaitori/' },
      { name: 'ソフマップ', price: 169000, url: 'https://www.sofmap.com/buy/' },
      { name: 'ビックカメラ', price: 165000, url: 'https://www.biccamera.com/bc/c/kaitori/' },
      { name: 'ヤマダ電機', price: 162000, url: 'https://www.yamada-denki.jp/service/kaitori/' },
    ],
    note: '未開封・付属品完備が条件。箱の状態で査定額が変動する場合あり。SIMフリー版のみ対象。',
    trend: 'up',
  },
  {
    id: 'iphone-16-128',
    name: 'iPhone 16 128GB ブラック',
    shortName: 'iPhone 16 128GB',
    category: 'apple',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp',
    officialPrice: 124800,
    officialUrl: 'https://www.apple.com/jp/shop/buy-iphone/iphone-16',
    topBuybackPrice: 143000,
    profit: 18200,
    profitRate: 14.6,
    updatedAt: '12:00',
    storeCount: 7,
    stores: [
      { name: 'ゲオ',       price: 143000, url: 'https://geo-online.co.jp/store/contents/buy/smartphone/', isTop: true },
      { name: 'ブックオフ', price: 138000, url: 'https://www.bookoffonline.co.jp/old/0001-mobile-kaitori.html' },
      { name: 'ハードオフ', price: 135000, url: 'https://www.hardoff.co.jp/kaitori/' },
      { name: 'イオシス',   price: 132000, url: 'https://iosys.co.jp/kaitori/' },
      { name: 'じゃんぱら', price: 130000, url: 'https://www.janpara.co.jp/sale/kaitori/' },
    ],
    note: 'SIMフリー版のみ対象。キャリア版は査定額が下がる場合あり。',
    trend: 'stable',
  },
  {
    id: 'macbook-air-m3',
    name: 'MacBook Air M3 13インチ 8GB/256GB',
    shortName: 'MacBook Air M3 13"',
    category: 'apple',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/macbook-card-joe6xf4Z3fF5WnnBRLbnFX.webp',
    officialPrice: 164800,
    officialUrl: 'https://www.apple.com/jp/shop/buy-mac/macbook-air/13-inch',
    topBuybackPrice: 185000,
    profit: 20200,
    profitRate: 12.3,
    updatedAt: '12:00',
    storeCount: 6,
    stores: [
      { name: 'ゲオ',         price: 185000, url: 'https://geo-online.co.jp/store/contents/buy/pc/', isTop: true },
      { name: 'ブックオフ',   price: 180000, url: 'https://www.bookoffonline.co.jp/old/0001-pc-kaitori.html' },
      { name: 'パソコン工房', price: 175000, url: 'https://www.pc-koubou.jp/guide/kaitori.php' },
      { name: 'ソフマップ',   price: 172000, url: 'https://www.sofmap.com/buy/' },
    ],
    note: '未開封品のみ。開封済みは査定額が大幅に下がる。',
    trend: 'up',
  },
  {
    id: 'airpods-pro-2',
    name: 'AirPods Pro 第2世代 MagSafe対応',
    shortName: 'AirPods Pro 2',
    category: 'apple',
    image: 'https://images.unsplash.com/photo-1606220945770-b5b6c2c55bf1?w=400&h=400&fit=crop',
    officialPrice: 39800,
    officialUrl: 'https://www.apple.com/jp/shop/buy-airpods/airpods-pro',
    topBuybackPrice: 48500,
    profit: 8700,
    profitRate: 21.9,
    updatedAt: '12:00',
    storeCount: 9,
    stores: [
      { name: 'ゲオ',       price: 48500, url: 'https://geo-online.co.jp/store/contents/buy/audio/', isTop: true },
      { name: 'ブックオフ', price: 46000, url: 'https://www.bookoffonline.co.jp/old/0001-audio-kaitori.html' },
      { name: 'ハードオフ', price: 44000, url: 'https://www.hardoff.co.jp/kaitori/' },
      { name: 'じゃんぱら', price: 42000, url: 'https://www.janpara.co.jp/sale/kaitori/' },
    ],
    note: '利益率が高い優良案件。未開封必須。',
    trend: 'up',
  },
  {
    id: 'switch-oled',
    name: 'Nintendo Switch 有機ELモデル ホワイト',
    shortName: 'Switch OLED ホワイト',
    category: 'game',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp',
    officialPrice: 37980,
    officialUrl: 'https://store.nintendo.co.jp/category/NINTENDO_SWITCH_MAIN_UNIT/HAC-S-KAAAA.html',
    topBuybackPrice: 44000,
    profit: 6020,
    profitRate: 15.9,
    updatedAt: '12:00',
    storeCount: 10,
    stores: [
      { name: 'ゲオ',       price: 44000, url: 'https://geo-online.co.jp/store/contents/buy/game/', isTop: true },
      { name: 'ブックオフ', price: 42000, url: 'https://www.bookoffonline.co.jp/old/0001-game-kaitori.html' },
      { name: 'ハードオフ', price: 40000, url: 'https://www.hardoff.co.jp/kaitori/' },
      { name: '駿河屋',     price: 38500, url: 'https://www.suruga-ya.jp/kaitori' },
    ],
    note: '在庫が安定している定番案件。',
    trend: 'stable',
  },
  {
    id: 'ipad-air-m2',
    name: 'iPad Air M2 11インチ Wi-Fi 128GB',
    shortName: 'iPad Air M2 11"',
    category: 'apple',
    image: 'https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?w=400&h=400&fit=crop',
    officialPrice: 98800,
    officialUrl: 'https://www.apple.com/jp/shop/buy-ipad/ipad-air',
    topBuybackPrice: 112000,
    profit: 13200,
    profitRate: 13.4,
    updatedAt: '12:00',
    storeCount: 7,
    stores: [
      { name: 'ゲオ',       price: 112000, url: 'https://geo-online.co.jp/store/contents/buy/tablet/', isTop: true },
      { name: 'ブックオフ', price: 108000, url: 'https://www.bookoffonline.co.jp/old/0001-tablet-kaitori.html' },
      { name: 'ハードオフ', price: 105000, url: 'https://www.hardoff.co.jp/kaitori/' },
    ],
    note: 'Wi-Fiモデルのみ対象。セルラーは別途確認。',
    trend: 'down',
  },
];

// ============================================================
// Buyback Stores — 買取ページURL付き
// ============================================================

export const buybackStores: BuybackStore[] = [
  { rank: 1, name: 'ゲオ（GEO）',   price: 186200, diff: 0,      updatedAt: '12:00', url: 'https://geo-online.co.jp/store/contents/buy/smartphone/', isTop: true },
  { rank: 2, name: 'ブックオフ',    price: 182000, diff: -4200,  updatedAt: '12:00', url: 'https://www.bookoffonline.co.jp/old/0001-mobile-kaitori.html' },
  { rank: 3, name: 'ハードオフ',    price: 178000, diff: -8200,  updatedAt: '12:00', url: 'https://www.hardoff.co.jp/kaitori/' },
  { rank: 4, name: 'イオシス',      price: 175000, diff: -11200, updatedAt: '12:00', url: 'https://iosys.co.jp/kaitori/' },
  { rank: 5, name: 'じゃんぱら',    price: 172000, diff: -14200, updatedAt: '12:00', url: 'https://www.janpara.co.jp/sale/kaitori/' },
  { rank: 6, name: 'ソフマップ',    price: 169000, diff: -17200, updatedAt: '11:30', url: 'https://www.sofmap.com/buy/' },
  { rank: 7, name: 'ビックカメラ',  price: 165000, diff: -21200, updatedAt: '11:30', url: 'https://www.biccamera.com/bc/c/kaitori/' },
  { rank: 8, name: 'ヤマダ電機',    price: 162000, diff: -24200, updatedAt: '11:00', url: 'https://www.yamada-denki.jp/service/kaitori/' },
];

// ============================================================
// Advanced Items
// ============================================================

export const advancedItems: AdvancedItem[] = [
  {
    id: 'fuji-x100vi',
    name: 'FUJIFILM X100VI シルバー',
    shortName: 'X100VI',
    category: 'camera',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/camera-card-P7ZkyL9bZDbxejKJrgE9D6.webp',
    tags: ['プレ値', '高難度', '海外差益'],
    status: 'active',
    domesticUsedPrice: 298000,
    ebayPrice: 1850,
    bnhPrice: null,
    mpbPrice: 1420,
    kehPrice: 1380,
    stockxPrice: null,
    premiumRate: 78.5,
    updatedAt: '12:00',
    note: '定価¥167,000に対し国内中古¥298,000。海外eBayでも$1,850以上で取引中。',
    difficulty: 'high',
  },
  {
    id: 'ricoh-gr-iiix',
    name: 'RICOH GR IIIx Urban Edition',
    shortName: 'GR IIIx UE',
    category: 'camera',
    image: 'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=400&h=400&fit=crop',
    tags: ['限定', '抽選', '高難度'],
    status: 'lottery',
    domesticUsedPrice: 185000,
    ebayPrice: 1250,
    bnhPrice: null,
    mpbPrice: null,
    kehPrice: 980,
    stockxPrice: null,
    premiumRate: 54.2,
    updatedAt: '12:00',
    lotteryDeadline: '2026-05-31',
    note: '限定版。抽選販売のみ。定価¥119,900に対し中古¥185,000。',
    difficulty: 'very-high',
  },
  {
    id: 'switch-zelda-limited',
    name: 'Nintendo Switch 2 ゼルダ限定版',
    shortName: 'Switch 2 ゼルダ',
    category: 'game',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp',
    tags: ['限定', '抽選', '急騰'],
    status: 'lottery',
    domesticUsedPrice: 98000,
    ebayPrice: 680,
    bnhPrice: null,
    mpbPrice: null,
    kehPrice: null,
    stockxPrice: 720,
    premiumRate: 63.3,
    updatedAt: '12:00',
    lotteryDeadline: '2026-06-15',
    note: '抽選販売中。定価¥59,980に対し転売価格¥98,000超。',
    difficulty: 'very-high',
  },
  {
    id: 'iphone-18-pro',
    name: 'iPhone 18 Pro（発売予定）',
    shortName: 'iPhone 18 Pro',
    category: 'apple',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp',
    tags: ['新商品', '上級者向け', '海外差益'],
    status: 'preorder',
    domesticUsedPrice: null,
    ebayPrice: null,
    bnhPrice: null,
    mpbPrice: null,
    kehPrice: null,
    stockxPrice: null,
    premiumRate: 0,
    updatedAt: '12:00',
    note: '2026年秋発売予定。過去モデルの傾向から発売直後のプレ値を予測。',
    difficulty: 'high',
  },
];

// ============================================================
// Ranking
// ============================================================

export const rankingData = {
  overall: [
    { rank: 1, name: 'AirPods Pro 2',       category: 'apple' as Category, profit: 8700,   profitRate: 21.9, image: 'https://images.unsplash.com/photo-1606220945770-b5b6c2c55bf1?w=100&h=100&fit=crop' },
    { rank: 2, name: 'iPhone 16 Pro 256GB', category: 'apple' as Category, profit: 26400,  profitRate: 16.5, image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp' },
    { rank: 3, name: 'Switch OLED ホワイト', category: 'game' as Category, profit: 6020,   profitRate: 15.9, image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp' },
    { rank: 4, name: 'iPhone 16 128GB',     category: 'apple' as Category, profit: 18200,  profitRate: 14.6, image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp' },
    { rank: 5, name: 'iPad Air M2 11"',     category: 'apple' as Category, profit: 13200,  profitRate: 13.4, image: 'https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?w=100&h=100&fit=crop' },
  ],
  iphone: [
    { rank: 1, name: 'iPhone 16 Pro 256GB',      category: 'apple' as Category, profit: 26400, profitRate: 16.5, image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp' },
    { rank: 2, name: 'iPhone 16 128GB',          category: 'apple' as Category, profit: 18200, profitRate: 14.6, image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp' },
    { rank: 3, name: 'iPhone 16 Pro Max 256GB',  category: 'apple' as Category, profit: 22000, profitRate: 11.8, image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp' },
  ],
  camera: [
    { rank: 1, name: 'FUJIFILM X100VI',  category: 'camera' as Category, profit: 131000, profitRate: 78.5, image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/camera-card-P7ZkyL9bZDbxejKJrgE9D6.webp' },
    { rank: 2, name: 'RICOH GR IIIx UE', category: 'camera' as Category, profit: 65100,  profitRate: 54.2, image: 'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=100&h=100&fit=crop' },
    { rank: 3, name: 'Leica Q3',          category: 'camera' as Category, profit: 85000,  profitRate: 22.1, image: 'https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=100&h=100&fit=crop' },
  ],
  game: [
    { rank: 1, name: 'Switch 2 ゼルダ限定版', category: 'game' as Category, profit: 38020, profitRate: 63.3, image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp' },
    { rank: 2, name: 'Switch OLED ホワイト',  category: 'game' as Category, profit: 6020,  profitRate: 15.9, image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp' },
    { rank: 3, name: 'PS5 スリム版',          category: 'game' as Category, profit: 4520,  profitRate: 6.7,  image: 'https://images.unsplash.com/photo-1607853202273-797f1c22a38e?w=100&h=100&fit=crop' },
  ],
};

// ============================================================
// New Products
// ============================================================

export const newProducts: NewProduct[] = [
  {
    id: 'iphone-18-pro',
    name: 'iPhone 18 Pro',
    category: 'apple',
    releaseDate: '2026年9月（予定）',
    status: 'upcoming',
    targetUser: 'advanced',
    expectedProfit: 35000,
    reason: '過去モデルの傾向から発売直後に¥30,000〜¥40,000の利益が見込まれる。海外価格差も期待大。',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp',
  },
  {
    id: 'switch-2-limited',
    name: 'Nintendo Switch 2 限定版',
    category: 'game',
    releaseDate: '2026年6月（抽選）',
    status: 'lottery',
    targetUser: 'advanced',
    expectedProfit: 40000,
    reason: '抽選販売のみ。過去の限定版は発売直後に2倍以上のプレ値がつく傾向。',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp',
  },
  {
    id: 'ricoh-gr-iv',
    name: 'RICOH GR IV（発売予定）',
    category: 'camera',
    releaseDate: '2026年下半期（予定）',
    status: 'upcoming',
    targetUser: 'advanced',
    expectedProfit: 80000,
    reason: 'GRシリーズは発売直後から慢性的な品薄状態。X100VIと同様の相場形成が予想される。',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/camera-card-P7ZkyL9bZDbxejKJrgE9D6.webp',
  },
  {
    id: 'macbook-pro-m5',
    name: 'MacBook Pro M5',
    category: 'apple',
    releaseDate: '2026年秋（予定）',
    status: 'upcoming',
    targetUser: 'beginner',
    expectedProfit: 25000,
    reason: 'M4からの買い替え需要で発売直後の買取価格が高騰する見込み。初心者でも狙いやすい。',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/macbook-card-joe6xf4Z3fF5WnnBRLbnFX.webp',
  },
];

// ============================================================
// Overseas Links
// ============================================================

export const overseasLinks = [
  { name: 'eBay Sold',  url: 'https://www.ebay.com/sch/i.html?_nkw=iphone+16+pro&LH_Sold=1&LH_Complete=1', color: 'blue' as const, description: '落札済み価格を確認' },
  { name: 'B&H Photo',  url: 'https://www.bhphotovideo.com', color: 'blue' as const, description: '米国カメラ専門店' },
  { name: 'MPB',        url: 'https://www.mpb.com',          color: 'green' as const, description: '中古カメラ英国' },
  { name: 'KEH Camera', url: 'https://www.keh.com',          color: 'green' as const, description: '中古カメラ米国' },
  { name: 'Adorama',    url: 'https://www.adorama.com',      color: 'blue' as const, description: '米国カメラ・家電' },
  { name: 'StockX',     url: 'https://stockx.com',           color: 'purple' as const, description: 'スニーカー・ゲーム機' },
  { name: 'Swappa',     url: 'https://swappa.com',           color: 'green' as const, description: '中古スマホ米国' },
  { name: 'Back Market', url: 'https://www.backmarket.com',  color: 'blue' as const, description: '欧州リファービッシュ' },
];

// ============================================================
// Hero Stats
// ============================================================

export const heroStats = {
  updatedAt: '2026年5月19日 12:00 JST',
  beginnerCount: 12,
  advancedCount: 8,
  maxProfit: 131000,
  totalItems: 47,
};

// ============================================================
// Helpers
// ============================================================

export const formatPrice = (price: number): string =>
  `¥${price.toLocaleString('ja-JP')}`;

export const formatUSD = (price: number): string =>
  `$${price.toLocaleString('en-US')}`;

export const categoryLabel: Record<Category, string> = {
  apple:  'Apple',
  camera: 'カメラ',
  game:   'ゲーム機',
  pc:     'PC・タブレット',
};

export const categoryColor: Record<Category, string> = {
  apple:  'text-slate-600',
  camera: 'text-amber-600',
  game:   'text-violet-600',
  pc:     'text-blue-600',
};
