// ============================================================
// SOUBA — Genre Section v5
// ジャンル: スマホ / タブレット / PC / カメラ / ゲーム機
// メーカー別サブタブ付き + 公式価格リンク + 買取ページリンク
// ============================================================

import { useState } from 'react';
import { ExternalLink, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronUp, AlertCircle, Store, Heart, Flame, Link2 } from 'lucide-react';
import { formatPrice } from '@/lib/data';

export type GenreId = 'smartphone' | 'tablet' | 'pc' | 'camera' | 'game';

// ── Maker sub-tabs ─────────────────────────────────────────────
const makerTabs: Record<GenreId, { id: string; label: string }[]> = {
  smartphone: [
    { id: 'all',     label: 'すべて' },
    { id: 'apple',   label: 'Apple' },
    { id: 'samsung', label: 'Samsung' },
    { id: 'google',  label: 'Google' },
    { id: 'sony',    label: 'Sony' },
    { id: 'sharp',   label: 'SHARP' },
  ],
  tablet: [
    { id: 'all',       label: 'すべて' },
    { id: 'apple',     label: 'Apple' },
    { id: 'samsung',   label: 'Samsung' },
    { id: 'microsoft', label: 'Microsoft' },
    { id: 'amazon',    label: 'Amazon' },
  ],
  pc: [
    { id: 'all',       label: 'すべて' },
    { id: 'apple',     label: 'Apple' },
    { id: 'microsoft', label: 'Microsoft' },
    { id: 'lenovo',    label: 'Lenovo' },
    { id: 'dell',      label: 'Dell' },
    { id: 'hp',        label: 'HP' },
  ],
  camera: [
    { id: 'all',      label: 'すべて' },
    { id: 'fujifilm', label: 'FUJIFILM' },
    { id: 'ricoh',    label: 'RICOH' },
    { id: 'leica',    label: 'Leica' },
    { id: 'sony',     label: 'Sony' },
    { id: 'nikon',    label: 'Nikon' },
    { id: 'canon',    label: 'Canon' },
  ],
  game: [
    { id: 'all',       label: 'すべて' },
    { id: 'nintendo',  label: 'Nintendo' },
    { id: 'sony',      label: 'PlayStation' },
    { id: 'microsoft', label: 'Xbox' },
  ],
};

// ── Genre config ───────────────────────────────────────────────
const genreConfig: Record<GenreId, { label: string; color: string; bg: string; border: string; barClass: string; desc: string }> = {
  smartphone: { label: 'スマートフォン', color: '#0D0F1C', bg: '#F4F5FD', border: '#C8CADE', barClass: 'section-bar-blue',   desc: 'iPhone・Android・Pixel など各メーカーのスマホ買取・相場情報' },
  tablet:     { label: 'タブレット',     color: '#1D4ED8', bg: '#EEF4FF', border: '#BFDBFE', barClass: 'section-bar-blue',   desc: 'iPad・Surface・Galaxy Tab など各メーカーのタブレット買取・相場情報' },
  pc:         { label: 'PC・ノートPC',   color: '#1D4ED8', bg: '#EEF4FF', border: '#BFDBFE', barClass: 'section-bar-blue',   desc: 'MacBook・Surface・ThinkPad など各メーカーのPC買取・相場情報' },
  camera:     { label: 'カメラ',         color: '#B45309', bg: '#FFF8E8', border: '#FCD34D', barClass: 'section-bar-amber',  desc: 'FUJIFILM・RICOH・Leica・Sony・Nikon・Canon のプレ値・海外相場情報' },
  game:       { label: 'ゲーム機',       color: '#6040E8', bg: '#F0EEFF', border: '#C4B5FD', barClass: 'section-bar-purple', desc: 'Nintendo Switch・PlayStation・Xbox の抽選・転売相場情報' },
};

// ── Product data ───────────────────────────────────────────────
interface ProductItem {
  id: string;
  name: string;
  maker: string;
  officialPrice: number;
  officialUrl: string;
  topBuybackPrice: number;
  profitRate: number;
  image: string;
  trend: 'up' | 'down' | 'stable';
  note: string;
  stores: { name: string; price: number; buyUrl: string; isTop?: boolean }[];
}

const genreProducts: Record<GenreId, ProductItem[]> = {
  smartphone: [
    {
      id: 'iphone-16-pro-256',
      name: 'iPhone 16 Pro 256GB ナチュラルチタニウム',
      maker: 'apple',
      officialPrice: 159800,
      officialUrl: 'https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro',
      topBuybackPrice: 186200,
      profitRate: 16.5,
      image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp',
      trend: 'up',
      note: '未開封・付属品完備が条件。SIMフリー版のみ対象。',
      stores: [
        { name: 'ゲオ',       price: 186200, buyUrl: 'https://geo-online.co.jp/store/contents/buy/smartphone/', isTop: true },
        { name: 'ブックオフ', price: 182000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-mobile-kaitori.html' },
        { name: 'ハードオフ', price: 178000, buyUrl: 'https://www.hardoff.co.jp/kaitori/' },
        { name: 'イオシス',   price: 175000, buyUrl: 'https://iosys.co.jp/kaitori/' },
        { name: 'じゃんぱら', price: 172000, buyUrl: 'https://www.janpara.co.jp/sale/kaitori/' },
      ],
    },
    {
      id: 'iphone-16-128',
      name: 'iPhone 16 128GB ブラック',
      maker: 'apple',
      officialPrice: 124800,
      officialUrl: 'https://www.apple.com/jp/shop/buy-iphone/iphone-16',
      topBuybackPrice: 143000,
      profitRate: 14.6,
      image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp',
      trend: 'stable',
      note: 'SIMフリー版のみ対象。キャリア版は査定額が下がる場合あり。',
      stores: [
        { name: 'ゲオ',       price: 143000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/smartphone/', isTop: true },
        { name: 'ブックオフ', price: 138000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-mobile-kaitori.html' },
        { name: 'ハードオフ', price: 135000, buyUrl: 'https://www.hardoff.co.jp/kaitori/' },
        { name: 'イオシス',   price: 132000, buyUrl: 'https://iosys.co.jp/kaitori/' },
      ],
    },
    {
      id: 'galaxy-s25-ultra',
      name: 'Samsung Galaxy S25 Ultra 256GB',
      maker: 'samsung',
      officialPrice: 189800,
      officialUrl: 'https://www.samsung.com/jp/smartphones/galaxy-s25-ultra/',
      topBuybackPrice: 198000,
      profitRate: 4.3,
      image: 'https://images.unsplash.com/photo-1610945415295-d9bbf067e59c?w=400&h=400&fit=crop',
      trend: 'stable',
      note: 'SIMフリー版のみ対象。利益率は低めだが安定した案件。',
      stores: [
        { name: 'ゲオ',       price: 198000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/smartphone/', isTop: true },
        { name: 'ブックオフ', price: 192000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-mobile-kaitori.html' },
        { name: 'じゃんぱら', price: 188000, buyUrl: 'https://www.janpara.co.jp/sale/kaitori/' },
      ],
    },
    {
      id: 'pixel-9-pro',
      name: 'Google Pixel 9 Pro 128GB',
      maker: 'google',
      officialPrice: 159900,
      officialUrl: 'https://store.google.com/jp/product/pixel_9_pro',
      topBuybackPrice: 168000,
      profitRate: 5.1,
      image: 'https://images.unsplash.com/photo-1598327105666-5b89351aff97?w=400&h=400&fit=crop',
      trend: 'stable',
      note: 'SIMフリー版のみ対象。',
      stores: [
        { name: 'ゲオ',       price: 168000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/smartphone/', isTop: true },
        { name: 'ブックオフ', price: 162000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-mobile-kaitori.html' },
      ],
    },
    {
      id: 'xperia-1-vi',
      name: 'Sony Xperia 1 VI 256GB',
      maker: 'sony',
      officialPrice: 189900,
      officialUrl: 'https://www.sony.jp/xperia/products/XQ-EC44/',
      topBuybackPrice: 195000,
      profitRate: 2.7,
      image: 'https://images.unsplash.com/photo-1598327105666-5b89351aff97?w=400&h=400&fit=crop',
      trend: 'down',
      note: 'SIMフリー版のみ対象。利益率は低め。',
      stores: [
        { name: 'ゲオ',       price: 195000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/smartphone/', isTop: true },
        { name: 'じゃんぱら', price: 190000, buyUrl: 'https://www.janpara.co.jp/sale/kaitori/' },
      ],
    },
  ],
  tablet: [
    {
      id: 'ipad-air-m2',
      name: 'iPad Air M2 11インチ Wi-Fi 128GB',
      maker: 'apple',
      officialPrice: 98800,
      officialUrl: 'https://www.apple.com/jp/shop/buy-ipad/ipad-air',
      topBuybackPrice: 112000,
      profitRate: 13.4,
      image: 'https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?w=400&h=400&fit=crop',
      trend: 'down',
      note: 'Wi-Fiモデルのみ対象。セルラーは別途確認。',
      stores: [
        { name: 'ゲオ',       price: 112000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/tablet/', isTop: true },
        { name: 'ブックオフ', price: 108000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-tablet-kaitori.html' },
        { name: 'ハードオフ', price: 105000, buyUrl: 'https://www.hardoff.co.jp/kaitori/' },
      ],
    },
    {
      id: 'ipad-pro-m4-11',
      name: 'iPad Pro M4 11インチ Wi-Fi 256GB',
      maker: 'apple',
      officialPrice: 168800,
      officialUrl: 'https://www.apple.com/jp/shop/buy-ipad/ipad-pro',
      topBuybackPrice: 188000,
      profitRate: 11.4,
      image: 'https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?w=400&h=400&fit=crop',
      trend: 'up',
      note: 'M4チップ搭載。Wi-Fiモデルのみ対象。',
      stores: [
        { name: 'ゲオ',       price: 188000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/tablet/', isTop: true },
        { name: 'ブックオフ', price: 182000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-tablet-kaitori.html' },
      ],
    },
    {
      id: 'surface-pro-11',
      name: 'Microsoft Surface Pro 11 Copilot+ PC',
      maker: 'microsoft',
      officialPrice: 198880,
      officialUrl: 'https://www.microsoft.com/ja-jp/d/surface-pro-11th-edition',
      topBuybackPrice: 210000,
      profitRate: 5.6,
      image: 'https://images.unsplash.com/photo-1593642632559-0c6d3fc62b89?w=400&h=400&fit=crop',
      trend: 'stable',
      note: '新品未開封のみ。Copilot+ PC需要で安定。',
      stores: [
        { name: 'ゲオ',         price: 210000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/pc/', isTop: true },
        { name: 'パソコン工房', price: 205000, buyUrl: 'https://www.pc-koubou.jp/guide/kaitori.php' },
      ],
    },
    {
      id: 'galaxy-tab-s10',
      name: 'Samsung Galaxy Tab S10+ Wi-Fi 256GB',
      maker: 'samsung',
      officialPrice: 148800,
      officialUrl: 'https://www.samsung.com/jp/tablets/galaxy-tab-s/galaxy-tab-s10-plus/',
      topBuybackPrice: 155000,
      profitRate: 4.2,
      image: 'https://images.unsplash.com/photo-1544244015-0df4b3ffc6b0?w=400&h=400&fit=crop',
      trend: 'stable',
      note: 'Wi-Fiモデルのみ対象。利益率は低め。',
      stores: [
        { name: 'ゲオ',       price: 155000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/tablet/', isTop: true },
        { name: 'ブックオフ', price: 150000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-tablet-kaitori.html' },
      ],
    },
  ],
  pc: [
    {
      id: 'macbook-air-m3',
      name: 'MacBook Air M3 13インチ 8GB/256GB',
      maker: 'apple',
      officialPrice: 164800,
      officialUrl: 'https://www.apple.com/jp/shop/buy-mac/macbook-air/13-inch',
      topBuybackPrice: 185000,
      profitRate: 12.3,
      image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/macbook-card-joe6xf4Z3fF5WnnBRLbnFX.webp',
      trend: 'up',
      note: '未開封品のみ対象。開封済みは査定額が大幅に下がる。',
      stores: [
        { name: 'ゲオ',         price: 185000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/pc/', isTop: true },
        { name: 'ブックオフ',   price: 180000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-pc-kaitori.html' },
        { name: 'パソコン工房', price: 175000, buyUrl: 'https://www.pc-koubou.jp/guide/kaitori.php' },
        { name: 'ソフマップ',   price: 172000, buyUrl: 'https://www.sofmap.com/buy/' },
      ],
    },
    {
      id: 'macbook-pro-m4',
      name: 'MacBook Pro M4 14インチ 16GB/512GB',
      maker: 'apple',
      officialPrice: 248800,
      officialUrl: 'https://www.apple.com/jp/shop/buy-mac/macbook-pro/14-inch',
      topBuybackPrice: 272000,
      profitRate: 9.3,
      image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/macbook-card-joe6xf4Z3fF5WnnBRLbnFX.webp',
      trend: 'stable',
      note: '未開封品のみ対象。M4チップ搭載で需要が高い。',
      stores: [
        { name: 'ゲオ',       price: 272000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/pc/', isTop: true },
        { name: 'ブックオフ', price: 265000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-pc-kaitori.html' },
        { name: 'ソフマップ', price: 260000, buyUrl: 'https://www.sofmap.com/buy/' },
      ],
    },
    {
      id: 'surface-laptop-7',
      name: 'Microsoft Surface Laptop 7 15インチ',
      maker: 'microsoft',
      officialPrice: 228880,
      officialUrl: 'https://www.microsoft.com/ja-jp/d/surface-laptop-7th-edition',
      topBuybackPrice: 238000,
      profitRate: 4.0,
      image: 'https://images.unsplash.com/photo-1593642632559-0c6d3fc62b89?w=400&h=400&fit=crop',
      trend: 'stable',
      note: '新品未開封のみ。Copilot+ PC搭載。',
      stores: [
        { name: 'ゲオ',         price: 238000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/pc/', isTop: true },
        { name: 'パソコン工房', price: 232000, buyUrl: 'https://www.pc-koubou.jp/guide/kaitori.php' },
      ],
    },
    {
      id: 'thinkpad-x1-carbon',
      name: 'Lenovo ThinkPad X1 Carbon Gen 12',
      maker: 'lenovo',
      officialPrice: 298000,
      officialUrl: 'https://www.lenovo.com/jp/ja/laptops/thinkpad/thinkpad-x1/ThinkPad-X1-Carbon-Gen-12/',
      topBuybackPrice: 305000,
      profitRate: 2.3,
      image: 'https://images.unsplash.com/photo-1593642632559-0c6d3fc62b89?w=400&h=400&fit=crop',
      trend: 'stable',
      note: '法人向けモデルは査定額が異なる場合あり。',
      stores: [
        { name: 'パソコン工房', price: 305000, buyUrl: 'https://www.pc-koubou.jp/guide/kaitori.php', isTop: true },
        { name: 'ソフマップ',   price: 298000, buyUrl: 'https://www.sofmap.com/buy/' },
      ],
    },
  ],
  camera: [
    {
      id: 'fuji-x100vi',
      name: 'FUJIFILM X100VI シルバー（中古・美品）',
      maker: 'fujifilm',
      officialPrice: 167000,
      officialUrl: 'https://fujifilm-x.com/ja-jp/products/cameras/x100vi/',
      topBuybackPrice: 298000,
      profitRate: 78.4,
      image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/camera-card-P7ZkyL9bZDbxejKJrgE9D6.webp',
      trend: 'up',
      note: '定価¥167,000に対し中古相場¥298,000超。プレ値案件。',
      stores: [
        { name: 'マップカメラ', price: 298000, buyUrl: 'https://www.mapcamera.com/kaitori/', isTop: true },
        { name: 'キタムラ',     price: 285000, buyUrl: 'https://www.kitamura.jp/service/kaitori/' },
        { name: 'ハードオフ',   price: 265000, buyUrl: 'https://www.hardoff.co.jp/kaitori/' },
        { name: '2nd STREET',   price: 258000, buyUrl: 'https://www.2ndstreet.jp/kaitori/' },
      ],
    },
    {
      id: 'ricoh-griiix',
      name: 'RICOH GR IIIx（新品）',
      maker: 'ricoh',
      officialPrice: 119900,
      officialUrl: 'https://www.ricoh-imaging.co.jp/japan/products/gr-3x/',
      topBuybackPrice: 165000,
      profitRate: 37.6,
      image: 'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=400&h=400&fit=crop',
      trend: 'up',
      note: '在庫があれば定価購入→高値売却が可能。入荷情報を要チェック。',
      stores: [
        { name: 'マップカメラ', price: 165000, buyUrl: 'https://www.mapcamera.com/kaitori/', isTop: true },
        { name: 'キタムラ',     price: 155000, buyUrl: 'https://www.kitamura.jp/service/kaitori/' },
        { name: 'ハードオフ',   price: 148000, buyUrl: 'https://www.hardoff.co.jp/kaitori/' },
      ],
    },
    {
      id: 'leica-q3',
      name: 'Leica Q3（新品）',
      maker: 'leica',
      officialPrice: 985600,
      officialUrl: 'https://leica-camera.com/ja-JP/photography/cameras/q/q3-black',
      topBuybackPrice: 1070000,
      profitRate: 8.6,
      image: 'https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=400&h=400&fit=crop',
      trend: 'stable',
      note: '高額案件。未開封品のみ対象。',
      stores: [
        { name: 'マップカメラ', price: 1070000, buyUrl: 'https://www.mapcamera.com/kaitori/', isTop: true },
        { name: 'キタムラ',     price: 1050000, buyUrl: 'https://www.kitamura.jp/service/kaitori/' },
      ],
    },
    {
      id: 'sony-a7rv',
      name: 'Sony α7R V ボディ（新品）',
      maker: 'sony',
      officialPrice: 598000,
      officialUrl: 'https://www.sony.jp/ichigan/products/ILCE-7RM5/',
      topBuybackPrice: 625000,
      profitRate: 4.5,
      image: 'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=400&h=400&fit=crop',
      trend: 'stable',
      note: '高額案件。未開封品のみ。利益率は低めだが金額が大きい。',
      stores: [
        { name: 'マップカメラ', price: 625000, buyUrl: 'https://www.mapcamera.com/kaitori/', isTop: true },
        { name: 'キタムラ',     price: 610000, buyUrl: 'https://www.kitamura.jp/service/kaitori/' },
      ],
    },
  ],
  game: [
    {
      id: 'switch-oled',
      name: 'Nintendo Switch 有機ELモデル ホワイト',
      maker: 'nintendo',
      officialPrice: 37980,
      officialUrl: 'https://store.nintendo.co.jp/category/NINTENDO_SWITCH_MAIN_UNIT/HAC-S-KAAAA.html',
      topBuybackPrice: 44000,
      profitRate: 15.9,
      image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp',
      trend: 'stable',
      note: '在庫が安定している定番案件。',
      stores: [
        { name: 'ゲオ',       price: 44000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/game/', isTop: true },
        { name: 'ブックオフ', price: 42000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-game-kaitori.html' },
        { name: 'ハードオフ', price: 40000, buyUrl: 'https://www.hardoff.co.jp/kaitori/' },
        { name: '駿河屋',     price: 38500, buyUrl: 'https://www.suruga-ya.jp/kaitori' },
      ],
    },
    {
      id: 'switch2-zelda',
      name: 'Nintendo Switch 2 ゼルダ限定版（抽選）',
      maker: 'nintendo',
      officialPrice: 59980,
      officialUrl: 'https://store.nintendo.co.jp/',
      topBuybackPrice: 98000,
      profitRate: 63.3,
      image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp',
      trend: 'up',
      note: '抽選販売のみ。定価¥59,980に対し転売価格¥98,000超。',
      stores: [
        { name: 'ゲオ',       price: 98000, buyUrl: 'https://geo-online.co.jp/store/contents/buy/game/', isTop: true },
        { name: 'ブックオフ', price: 94000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-game-kaitori.html' },
        { name: '駿河屋',     price: 90000, buyUrl: 'https://www.suruga-ya.jp/kaitori' },
      ],
    },
    {
      id: 'ps5-slim',
      name: 'PlayStation 5 スリム版 ディスクあり',
      maker: 'sony',
      officialPrice: 66980,
      officialUrl: 'https://direct.playstation.com/ja-jp/hardware/ps5',
      topBuybackPrice: 71500,
      profitRate: 6.7,
      image: 'https://images.unsplash.com/photo-1607853202273-797f1c22a38e?w=400&h=400&fit=crop',
      trend: 'stable',
      note: '利益率は低めだが在庫が安定。定番案件。',
      stores: [
        { name: 'ゲオ',       price: 71500, buyUrl: 'https://geo-online.co.jp/store/contents/buy/game/', isTop: true },
        { name: 'ブックオフ', price: 69000, buyUrl: 'https://www.bookoffonline.co.jp/old/0001-game-kaitori.html' },
        { name: 'ハードオフ', price: 67000, buyUrl: 'https://www.hardoff.co.jp/kaitori/' },
      ],
    },
  ],
};

// ── Helpers ────────────────────────────────────────────────────
function getProfitScore(rate: number) {
  if (rate >= 20) return { grade: 'S', cls: 'score-s' };
  if (rate >= 15) return { grade: 'A', cls: 'score-a' };
  if (rate >= 10) return { grade: 'B', cls: 'score-b' };
  return { grade: 'C', cls: 'score-c' };
}

function TrendIcon({ trend }: { trend: 'up' | 'down' | 'stable' }) {
  if (trend === 'up')   return <TrendingUp   size={11} style={{ color: '#00C896' }} />;
  if (trend === 'down') return <TrendingDown size={11} style={{ color: '#FF3B5C' }} />;
  return <Minus size={11} style={{ color: '#9CA3B8' }} />;
}

// ── Product Card ───────────────────────────────────────────────
function ProductCard({ item, index }: { item: ProductItem; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const [watched, setWatched]   = useState(false);
  const score  = getProfitScore(item.profitRate);
  const profit = item.topBuybackPrice - item.officialPrice;

  return (
    <div className="souba-card fade-in-up" style={{ animationDelay: `${index * 70}ms`, overflow: 'hidden' }}>
      <div style={{ height: '3px', background: `linear-gradient(90deg, #00C896 ${Math.min(item.profitRate * 4, 100)}%, #E8EAF2 0%)` }} />
      <div className="p-5">
        {/* Header */}
        <div className="flex items-start gap-3 mb-4">
          <div className="w-14 h-14 rounded-2xl overflow-hidden flex-shrink-0" style={{ background: '#F4F5FD', border: '1px solid #E8EAF2' }}>
            <img src={item.image} alt={item.name} className="w-full h-full object-cover" loading="lazy" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-1">
              <TrendIcon trend={item.trend} />
              {item.trend === 'up' && (
                <span className="text-xs px-1.5 py-0.5 rounded-full font-bold" style={{ background: '#FFF3E0', color: '#E07800', fontSize: '9px' }}>
                  <Flame size={8} style={{ display: 'inline', marginRight: 2 }} />人気
                </span>
              )}
            </div>
            <h3 className="text-sm font-bold leading-snug" style={{ color: '#0D0F1C' }}>{item.name}</h3>
          </div>
          <div className="flex flex-col items-end gap-2 flex-shrink-0">
            <div className={`score-badge ${score.cls}`}>{score.grade}</div>
            <button onClick={() => setWatched(!watched)}
              className={`watchlist-btn p-1.5 rounded-lg ${watched ? 'active' : ''}`}
              style={{ background: watched ? '#FFF1F3' : '#F4F5FD', color: watched ? '#FF3B5C' : '#C8CADE', border: `1px solid ${watched ? '#FECDD3' : '#E8EAF2'}` }}>
              <Heart size={13} fill={watched ? '#FF3B5C' : 'none'} />
            </button>
          </div>
        </div>

        {/* Prices */}
        <div className="rounded-2xl p-4 mb-4" style={{ background: '#F7F8FD', border: '1px solid #E8EAF2' }}>
          <div className="grid grid-cols-2 gap-3 mb-3">
            <div>
              <div className="flex items-center gap-1 mb-1">
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#9CA3B8' }}>公式価格</span>
                <a href={item.officialUrl} target="_blank" rel="noopener noreferrer" title="公式ページ" style={{ color: '#3B7BFF' }}><Link2 size={10} /></a>
              </div>
              <a href={item.officialUrl} target="_blank" rel="noopener noreferrer"
                className="text-base font-bold font-mono"
                style={{ color: '#5B6278', fontFamily: "'JetBrains Mono', monospace", textDecoration: 'none' }}
                onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.textDecoration = 'underline'}
                onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.textDecoration = 'none'}
              >{formatPrice(item.officialPrice)}</a>
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: '#9CA3B8' }}>最高買取</div>
              <div className="text-base font-bold font-mono" style={{ color: '#0D0F1C', fontFamily: "'JetBrains Mono', monospace" }}>{formatPrice(item.topBuybackPrice)}</div>
            </div>
          </div>
          <div className="flex items-center justify-between px-4 py-3 rounded-xl" style={{ background: 'linear-gradient(135deg, #F0FDF8, #E8FFF4)', border: '1px solid #A7F3D0' }}>
            <div>
              <div className="text-xs font-bold uppercase tracking-wider mb-0.5" style={{ color: '#047857' }}>実質利益</div>
              <div className="profit-number profit-number-lg">+{formatPrice(profit)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs mb-0.5" style={{ color: '#9CA3B8' }}>利益率</div>
              <div className="text-2xl font-black font-mono" style={{ color: '#00A876', fontFamily: "'JetBrains Mono', monospace" }}>+{item.profitRate}%</div>
            </div>
          </div>
        </div>

        {/* Store compare */}
        <button onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-semibold transition-all duration-150 press-effect"
          style={{ background: '#F4F5FD', color: '#5B6278', border: '1px solid #E8EAF2' }}>
          <div className="flex items-center gap-1.5"><Store size={12} />店舗別買取価格（買取ページリンク付き）</div>
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>

        {expanded && (
          <div className="mt-2 space-y-1.5">
            {item.stores.map((store) => (
              <div key={store.name} className="flex items-center justify-between px-3 py-2.5 rounded-xl"
                style={{ background: store.isTop ? '#F0FDF8' : '#FAFBFF', border: `1px solid ${store.isTop ? '#A7F3D0' : '#E8EAF2'}` }}>
                <div className="flex items-center gap-2">
                  {store.isTop && <span className="text-xs px-1.5 py-0.5 rounded-full font-black" style={{ background: '#00C896', color: '#fff', fontSize: '9px' }}>TOP</span>}
                  <span className="text-xs font-semibold" style={{ color: store.isTop ? '#0D0F1C' : '#5B6278' }}>{store.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-black font-mono" style={{ color: store.isTop ? '#00A876' : '#0D0F1C', fontFamily: "'JetBrains Mono', monospace" }}>{formatPrice(store.price)}</span>
                  <a href={store.buyUrl} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-bold press-effect"
                    style={{ background: store.isTop ? '#00C896' : '#F4F5FD', color: store.isTop ? '#fff' : '#3B7BFF', border: store.isTop ? 'none' : '1px solid #E8EAF2' }}>
                    買取 <ExternalLink size={9} />
                  </a>
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="mt-3 flex items-start gap-2 px-3 py-2.5 rounded-xl" style={{ background: '#FFFBEB', border: '1px solid #FCD34D' }}>
          <AlertCircle size={12} className="flex-shrink-0 mt-0.5" style={{ color: '#FF9500' }} />
          <p className="text-xs leading-relaxed" style={{ color: '#92400E' }}>{item.note}</p>
        </div>
      </div>
    </div>
  );
}

// ── Main Component ─────────────────────────────────────────────
interface GenreSectionProps {
  genre: GenreId;
}

export default function GenreSection({ genre }: GenreSectionProps) {
  const config  = genreConfig[genre];
  const makers  = makerTabs[genre];
  const [activeMaker, setActiveMaker] = useState('all');

  const products = genreProducts[genre].filter(p =>
    activeMaker === 'all' || p.maker === activeMaker
  );

  return (
    <section id={genre} className="py-16" style={{ background: '#FAFBFF' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-3 mb-3">
              <div className={`w-1.5 h-5 rounded-full ${config.barClass}`} />
              <span className="section-label" style={{ background: config.bg, color: config.color, border: `1px solid ${config.border}` }}>
                {config.label}
              </span>
            </div>
            <h2 className="text-2xl font-black" style={{ color: '#0D0F1C', letterSpacing: '-0.03em' }}>{config.label}の相場情報</h2>
            <p className="text-sm mt-1" style={{ color: '#5B6278' }}>{config.desc}</p>
          </div>
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full" style={{ background: config.bg, border: `1px solid ${config.border}` }}>
            <div className="w-1.5 h-1.5 rounded-full live-pulse" style={{ background: config.color }} />
            <span className="text-xs font-bold" style={{ color: config.color }}>{products.length}件掲載中</span>
          </div>
        </div>

        {/* Maker sub-tabs */}
        <div className="flex items-center gap-1.5 flex-wrap mb-8 p-1 rounded-2xl w-fit" style={{ background: '#F4F5FD', border: '1px solid #E8EAF2' }}>
          {makers.map(m => {
            const isActive = activeMaker === m.id;
            return (
              <button key={m.id} onClick={() => setActiveMaker(m.id)}
                className="px-3.5 py-1.5 rounded-xl text-sm font-semibold transition-all duration-150 press-effect whitespace-nowrap"
                style={{
                  background: isActive ? '#FFFFFF' : 'transparent',
                  color: isActive ? config.color : '#9CA3B8',
                  border: isActive ? `1px solid ${config.border}` : '1px solid transparent',
                  boxShadow: isActive ? '0 1px 4px rgba(13,15,28,0.08)' : 'none',
                  fontWeight: isActive ? 700 : 500,
                }}>
                {m.label}
              </button>
            );
          })}
        </div>

        {/* Cards */}
        {products.length > 0 ? (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {products.map((item, i) => <ProductCard key={item.id} item={item} index={i} />)}
          </div>
        ) : (
          <div className="text-center py-16 rounded-2xl" style={{ background: '#FFFFFF', border: '1px solid #E8EAF2' }}>
            <p className="text-sm font-medium" style={{ color: '#9CA3B8' }}>このメーカーの案件は準備中です。</p>
          </div>
        )}
      </div>
    </section>
  );
}
