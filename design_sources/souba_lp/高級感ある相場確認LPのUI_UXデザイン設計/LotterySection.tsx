// ============================================================
// SOUBA — Lottery Section (抽選情報)
// ステータス: 受付中 / 締切間近 / 結果待ち / 終了
// ============================================================

import { useState } from 'react';
import { Ticket, Clock, AlertTriangle, CheckCircle2, XCircle, ExternalLink, CalendarDays, TrendingUp, Users, Link2 } from 'lucide-react';
import { formatPrice } from '@/lib/data';

type LotteryStatus = 'open' | 'closing_soon' | 'pending' | 'ended';

interface LotteryItem {
  id: string;
  name: string;
  category: string;
  image: string;
  officialPrice: number;
  officialUrl: string;
  expectedResalePrice: number;
  expectedProfit: number;
  status: LotteryStatus;
  deadline: string;        // 締切日
  resultDate?: string;     // 結果発表日
  applyUrl: string;        // 応募ページURL
  storeUrls: { name: string; url: string }[];
  difficulty: 'easy' | 'medium' | 'hard';
  winRate?: string;        // 当選倍率（目安）
  notes: string;
  tags: string[];
}

const lotteryItems: LotteryItem[] = [
  // ── 受付中 ──────────────────────────────────────────────
  {
    id: 'switch2-zelda-2026',
    name: 'Nintendo Switch 2 ゼルダの伝説 王国の涙 限定版',
    category: 'ゲーム機',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp',
    officialPrice: 59980,
    officialUrl: 'https://store.nintendo.co.jp/',
    expectedResalePrice: 98000,
    expectedProfit: 38020,
    status: 'open',
    deadline: '2026年6月15日 23:59',
    resultDate: '2026年6月20日',
    applyUrl: 'https://store.nintendo.co.jp/',
    storeUrls: [
      { name: 'マイニンテンドーストア', url: 'https://store.nintendo.co.jp/' },
      { name: 'ヨドバシカメラ', url: 'https://www.yodobashi.com/' },
      { name: 'ビックカメラ', url: 'https://www.biccamera.com/' },
    ],
    difficulty: 'hard',
    winRate: '約1/50〜1/100',
    notes: '複数店舗で同時応募可能。マイニンテンドーストアは任天堂アカウント必須。',
    tags: ['限定', '高倍率', '上級者向け'],
  },
  {
    id: 'ricoh-griiix-ue',
    name: 'RICOH GR IIIx Urban Edition 2026',
    category: 'カメラ',
    image: 'https://images.unsplash.com/photo-1516035069371-29a1b244cc32?w=400&h=400&fit=crop',
    officialPrice: 119900,
    officialUrl: 'https://www.ricoh-imaging.co.jp/japan/products/gr-3x/',
    expectedResalePrice: 185000,
    expectedProfit: 65100,
    status: 'open',
    deadline: '2026年5月31日 23:59',
    resultDate: '2026年6月5日',
    applyUrl: 'https://www.mapcamera.com/',
    storeUrls: [
      { name: 'マップカメラ', url: 'https://www.mapcamera.com/' },
      { name: 'キタムラ', url: 'https://www.kitamura.jp/' },
    ],
    difficulty: 'hard',
    winRate: '約1/30〜1/80',
    notes: '限定カラー版。カメラ専門店のみでの抽選販売。',
    tags: ['限定', 'カメラ', '高倍率'],
  },
  {
    id: 'iphone-18-pro-preorder',
    name: 'iPhone 18 Pro（予約受付予定）',
    category: 'Apple',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/iphone-card-AQQUXMQPq9i68mrDJaGjy8.webp',
    officialPrice: 175800,
    officialUrl: 'https://www.apple.com/jp/iphone/',
    expectedResalePrice: 210000,
    expectedProfit: 34200,
    status: 'open',
    deadline: '2026年9月（予定）',
    resultDate: '2026年9月発売予定',
    applyUrl: 'https://www.apple.com/jp/shop/',
    storeUrls: [
      { name: 'Apple Store', url: 'https://www.apple.com/jp/shop/' },
      { name: 'ドコモオンライン', url: 'https://www.docomo.ne.jp/' },
      { name: 'auオンライン', url: 'https://www.au.com/' },
    ],
    difficulty: 'medium',
    winRate: '先着順（発売日に並ぶ必要あり）',
    notes: '抽選ではなく先着順の可能性が高い。発売日の早朝から並ぶか、オンライン予約を狙う。',
    tags: ['新商品', '先着順', '初心者可'],
  },
  // ── 締切間近 ────────────────────────────────────────────
  {
    id: 'fuji-x100vi-special',
    name: 'FUJIFILM X100VI スペシャルエディション',
    category: 'カメラ',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/camera-card-P7ZkyL9bZDbxejKJrgE9D6.webp',
    officialPrice: 198000,
    officialUrl: 'https://fujifilm-x.com/ja-jp/products/cameras/x100vi/',
    expectedResalePrice: 320000,
    expectedProfit: 122000,
    status: 'closing_soon',
    deadline: '2026年5月22日 23:59',
    resultDate: '2026年5月28日',
    applyUrl: 'https://www.mapcamera.com/',
    storeUrls: [
      { name: 'マップカメラ', url: 'https://www.mapcamera.com/' },
      { name: 'キタムラ', url: 'https://www.kitamura.jp/' },
      { name: 'ヨドバシカメラ', url: 'https://www.yodobashi.com/' },
    ],
    difficulty: 'hard',
    winRate: '約1/200以上',
    notes: '残り3日！超高倍率案件。当選すれば利益¥122,000以上。複数店舗への同時応募を推奨。',
    tags: ['締切間近', '超高倍率', '最高利益'],
  },
  {
    id: 'ps5-limited-2026',
    name: 'PlayStation 5 限定デザインモデル',
    category: 'ゲーム機',
    image: 'https://images.unsplash.com/photo-1607853202273-797f1c22a38e?w=400&h=400&fit=crop',
    officialPrice: 79980,
    officialUrl: 'https://direct.playstation.com/ja-jp/hardware/ps5',
    expectedResalePrice: 115000,
    expectedProfit: 35020,
    status: 'closing_soon',
    deadline: '2026年5月24日 18:00',
    resultDate: '2026年5月30日',
    applyUrl: 'https://direct.playstation.com/ja-jp/',
    storeUrls: [
      { name: 'PlayStation Direct', url: 'https://direct.playstation.com/ja-jp/' },
      { name: 'ゲオ', url: 'https://geo-online.co.jp/' },
    ],
    difficulty: 'medium',
    winRate: '約1/20〜1/50',
    notes: '残り5日。PlayStation Directでの抽選が主。PSNアカウント必須。',
    tags: ['締切間近', 'ゲーム機', '中難度'],
  },
  // ── 結果待ち ────────────────────────────────────────────
  {
    id: 'switch2-standard',
    name: 'Nintendo Switch 2 通常版（第2次抽選）',
    category: 'ゲーム機',
    image: 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/switch-card-iRYE9JvcA2fKHAXzMEmaRs.webp',
    officialPrice: 49980,
    officialUrl: 'https://store.nintendo.co.jp/',
    expectedResalePrice: 72000,
    expectedProfit: 22020,
    status: 'pending',
    deadline: '2026年5月10日（締切済み）',
    resultDate: '2026年5月25日（発表予定）',
    applyUrl: 'https://store.nintendo.co.jp/',
    storeUrls: [
      { name: 'マイニンテンドーストア', url: 'https://store.nintendo.co.jp/' },
    ],
    difficulty: 'medium',
    winRate: '約1/15〜1/30',
    notes: '結果発表まであと数日。当選メールを確認してください。',
    tags: ['結果待ち', 'ゲーム機'],
  },
  {
    id: 'leica-m11-limited',
    name: 'Leica M11 限定エディション',
    category: 'カメラ',
    image: 'https://images.unsplash.com/photo-1502920917128-1aa500764cbd?w=400&h=400&fit=crop',
    officialPrice: 1350000,
    officialUrl: 'https://leica-camera.com/ja-JP/',
    expectedResalePrice: 1680000,
    expectedProfit: 330000,
    status: 'pending',
    deadline: '2026年5月5日（締切済み）',
    resultDate: '2026年5月26日（発表予定）',
    applyUrl: 'https://leica-camera.com/ja-JP/',
    storeUrls: [
      { name: 'ライカストア銀座', url: 'https://leica-camera.com/ja-JP/' },
      { name: 'マップカメラ', url: 'https://www.mapcamera.com/' },
    ],
    difficulty: 'hard',
    winRate: '約1/500以上',
    notes: '超高額案件。当選すれば利益¥330,000。ライカ正規店での購入履歴が有利とされる。',
    tags: ['結果待ち', '超高額', '最高難度'],
  },
];

const statusConfig: Record<LotteryStatus, {
  label: string; color: string; bg: string; border: string; icon: React.ReactNode;
}> = {
  open:         { label: '受付中',     color: '#047857', bg: '#F0FDF8', border: '#A7F3D0', icon: <CheckCircle2 size={13} /> },
  closing_soon: { label: '締切間近',   color: '#B45309', bg: '#FFF3E0', border: '#FCD34D', icon: <AlertTriangle size={13} /> },
  pending:      { label: '結果待ち',   color: '#6040E8', bg: '#F0EEFF', border: '#C4B5FD', icon: <Clock size={13} /> },
  ended:        { label: '終了',       color: '#9CA3B8', bg: '#F4F5FD', border: '#E8EAF2', icon: <XCircle size={13} /> },
};

const difficultyConfig = {
  easy:   { label: '低',   color: '#047857', bg: '#F0FDF8' },
  medium: { label: '中',   color: '#B45309', bg: '#FFF3E0' },
  hard:   { label: '高',   color: '#DC2626', bg: '#FEF2F2' },
};

const filterTabs: { id: LotteryStatus | 'all'; label: string }[] = [
  { id: 'all',          label: 'すべて' },
  { id: 'open',         label: '受付中' },
  { id: 'closing_soon', label: '締切間近' },
  { id: 'pending',      label: '結果待ち' },
  { id: 'ended',        label: '終了' },
];

function LotteryCard({ item, index }: { item: LotteryItem; index: number }) {
  const sc = statusConfig[item.status];
  const dc = difficultyConfig[item.difficulty];
  const isClosed = item.status === 'pending' || item.status === 'ended';

  return (
    <div
      className="souba-card fade-in-up"
      style={{
        animationDelay: `${index * 70}ms`,
        overflow: 'hidden',
        opacity: item.status === 'ended' ? 0.6 : 1,
      }}
    >
      {/* Status bar */}
      <div style={{
        height: '3px',
        background: item.status === 'closing_soon'
          ? 'linear-gradient(90deg, #FF9500, #FF3B5C)'
          : item.status === 'open'
          ? 'linear-gradient(90deg, #00C896, #3B7BFF)'
          : item.status === 'pending'
          ? 'linear-gradient(90deg, #7C5CFC, #3B7BFF)'
          : '#E8EAF2',
      }} />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-start gap-3 mb-4">
          <div className="w-14 h-14 rounded-2xl overflow-hidden flex-shrink-0" style={{ background: '#F4F5FD', border: '1px solid #E8EAF2' }}>
            <img src={item.image} alt={item.name} className="w-full h-full object-cover" loading="lazy" />
          </div>
          <div className="flex-1 min-w-0">
            {/* Badges */}
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
              {/* Status */}
              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full"
                style={{ background: sc.bg, border: `1px solid ${sc.border}`, color: sc.color }}>
                {sc.icon}
                <span className="text-xs font-bold">{sc.label}</span>
              </div>
              {/* Category */}
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ background: '#F4F5FD', color: '#5B6278', border: '1px solid #E8EAF2' }}>
                {item.category}
              </span>
              {/* Tags */}
              {item.tags.slice(0, 2).map(tag => (
                <span key={tag} className="text-xs font-semibold px-1.5 py-0.5 rounded-full" style={{ background: '#F0EEFF', color: '#6040E8', fontSize: '10px' }}>
                  {tag}
                </span>
              ))}
            </div>
            <h3 className="text-sm font-bold leading-snug" style={{ color: '#0D0F1C' }}>{item.name}</h3>
          </div>
        </div>

        {/* Key info grid */}
        <div className="grid grid-cols-2 gap-3 mb-4">
          {/* Official price */}
          <div className="p-3 rounded-xl" style={{ background: '#F7F8FD', border: '1px solid #E8EAF2' }}>
            <div className="flex items-center gap-1 mb-1">
              <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#9CA3B8' }}>公式価格</span>
              <a href={item.officialUrl} target="_blank" rel="noopener noreferrer" title="公式ページ" style={{ color: '#3B7BFF' }}>
                <Link2 size={9} />
              </a>
            </div>
            <a href={item.officialUrl} target="_blank" rel="noopener noreferrer"
              className="text-sm font-bold font-mono"
              style={{ color: '#5B6278', fontFamily: "'JetBrains Mono', monospace", textDecoration: 'none' }}
            >
              {formatPrice(item.officialPrice)}
            </a>
          </div>
          {/* Expected resale */}
          <div className="p-3 rounded-xl" style={{ background: '#F7F8FD', border: '1px solid #E8EAF2' }}>
            <div className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: '#9CA3B8' }}>予想転売価格</div>
            <div className="text-sm font-bold font-mono" style={{ color: '#0D0F1C', fontFamily: "'JetBrains Mono', monospace" }}>
              {formatPrice(item.expectedResalePrice)}
            </div>
          </div>
        </div>

        {/* Expected profit */}
        <div className="flex items-center justify-between px-4 py-3 rounded-xl mb-4"
          style={{ background: 'linear-gradient(135deg, #F0FDF8, #E8FFF4)', border: '1px solid #A7F3D0' }}>
          <div>
            <div className="text-xs font-bold uppercase tracking-wider mb-0.5" style={{ color: '#047857' }}>予想利益</div>
            <div className="profit-number text-2xl font-black" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
              +{formatPrice(item.expectedProfit)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs mb-1" style={{ color: '#9CA3B8' }}>当選倍率目安</div>
            <div className="text-xs font-bold" style={{ color: '#5B6278' }}>{item.winRate ?? '—'}</div>
          </div>
        </div>

        {/* Dates */}
        <div className="space-y-2 mb-4">
          <div className="flex items-center gap-2">
            <CalendarDays size={12} style={{ color: item.status === 'closing_soon' ? '#FF9500' : '#9CA3B8', flexShrink: 0 }} />
            <span className="text-xs" style={{ color: '#5B6278' }}>
              <span className="font-semibold">締切：</span>
              <span style={{ color: item.status === 'closing_soon' ? '#FF9500' : '#0D0F1C', fontWeight: item.status === 'closing_soon' ? 700 : 400 }}>
                {item.deadline}
              </span>
            </span>
          </div>
          {item.resultDate && (
            <div className="flex items-center gap-2">
              <CheckCircle2 size={12} style={{ color: '#9CA3B8', flexShrink: 0 }} />
              <span className="text-xs" style={{ color: '#5B6278' }}>
                <span className="font-semibold">結果発表：</span>{item.resultDate}
              </span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <TrendingUp size={12} style={{ color: '#9CA3B8', flexShrink: 0 }} />
            <span className="text-xs" style={{ color: '#5B6278' }}>
              <span className="font-semibold">難易度：</span>
              <span className="px-1.5 py-0.5 rounded-full text-xs font-bold ml-1" style={{ background: dc.bg, color: dc.color }}>
                {dc.label}
              </span>
            </span>
          </div>
        </div>

        {/* Apply stores */}
        <div className="mb-4">
          <div className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: '#9CA3B8' }}>応募先</div>
          <div className="flex flex-wrap gap-2">
            {item.storeUrls.map(s => (
              <a key={s.name} href={s.url} target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-semibold press-effect transition-all"
                style={{
                  background: isClosed ? '#F4F5FD' : 'linear-gradient(135deg, #00C896, #00A876)',
                  color: isClosed ? '#9CA3B8' : '#fff',
                  border: isClosed ? '1px solid #E8EAF2' : 'none',
                  pointerEvents: isClosed ? 'none' : 'auto',
                  opacity: isClosed ? 0.6 : 1,
                }}
              >
                {s.name} <ExternalLink size={9} />
              </a>
            ))}
          </div>
        </div>

        {/* Note */}
        <div className="flex items-start gap-2 px-3 py-2.5 rounded-xl" style={{ background: '#FFFBEB', border: '1px solid #FCD34D' }}>
          <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" style={{ color: '#FF9500' }} />
          <p className="text-xs leading-relaxed" style={{ color: '#92400E' }}>{item.notes}</p>
        </div>
      </div>
    </div>
  );
}

export default function LotterySection() {
  const [activeFilter, setActiveFilter] = useState<LotteryStatus | 'all'>('all');

  const filtered = activeFilter === 'all'
    ? lotteryItems
    : lotteryItems.filter(i => i.status === activeFilter);

  const counts = {
    all:          lotteryItems.length,
    open:         lotteryItems.filter(i => i.status === 'open').length,
    closing_soon: lotteryItems.filter(i => i.status === 'closing_soon').length,
    pending:      lotteryItems.filter(i => i.status === 'pending').length,
    ended:        lotteryItems.filter(i => i.status === 'ended').length,
  };

  return (
    <section id="lottery" className="py-16" style={{ background: '#FAFBFF' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-1.5 h-5 rounded-full section-bar-purple" />
              <span className="section-label section-label-violet">抽選情報</span>
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full" style={{ background: '#F0EEFF', border: '1px solid #C4B5FD' }}>
                <div className="w-1.5 h-1.5 rounded-full live-pulse" style={{ background: '#7C5CFC' }} />
                <span className="text-xs font-bold" style={{ color: '#6040E8' }}>
                  受付中 {counts.open}件 · 締切間近 {counts.closing_soon}件
                </span>
              </div>
            </div>
            <h2 className="text-2xl font-black" style={{ color: '#0D0F1C', letterSpacing: '-0.03em' }}>抽選情報一覧</h2>
            <p className="text-sm mt-1" style={{ color: '#5B6278' }}>
              現在受付中・締切間近・結果待ちの抽選案件をすべて掲載。応募先リンク付き。
            </p>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex items-center gap-1.5 flex-wrap mb-8 p-1 rounded-2xl w-fit" style={{ background: '#F4F5FD', border: '1px solid #E8EAF2' }}>
          {filterTabs.map(tab => {
            const isActive = activeFilter === tab.id;
            const count = counts[tab.id as keyof typeof counts] ?? 0;
            const sc = tab.id !== 'all' ? statusConfig[tab.id as LotteryStatus] : null;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveFilter(tab.id as LotteryStatus | 'all')}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-sm font-semibold transition-all duration-150 press-effect whitespace-nowrap"
                style={{
                  background: isActive ? '#FFFFFF' : 'transparent',
                  color: isActive ? (sc?.color ?? '#0D0F1C') : '#9CA3B8',
                  border: isActive ? `1px solid ${sc?.border ?? '#E8EAF2'}` : '1px solid transparent',
                  boxShadow: isActive ? '0 1px 4px rgba(13,15,28,0.08)' : 'none',
                  fontWeight: isActive ? 700 : 500,
                }}
              >
                {tab.label}
                <span className="text-xs px-1.5 py-0.5 rounded-full font-bold"
                  style={{ background: isActive ? (sc?.bg ?? '#F4F5FD') : '#EAECF5', color: isActive ? (sc?.color ?? '#5B6278') : '#9CA3B8', fontSize: '10px' }}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* Warning banner */}
        <div className="flex items-start gap-3 p-4 rounded-2xl mb-8" style={{ background: '#FFF3E0', border: '1px solid #FCD34D' }}>
          <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" style={{ color: '#FF9500' }} />
          <div>
            <p className="text-sm font-bold mb-0.5" style={{ color: '#92400E' }}>抽選応募に関する注意事項</p>
            <p className="text-xs leading-relaxed" style={{ color: '#B45309' }}>
              抽選に当選した場合、必ず購入義務が発生します。キャンセルはペナルティの対象となる場合があります。
              複数アカウントでの応募は規約違反です。転売目的での応募は自己責任でお願いします。
            </p>
          </div>
        </div>

        {/* Cards */}
        {filtered.length > 0 ? (
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
            {filtered.map((item, i) => <LotteryCard key={item.id} item={item} index={i} />)}
          </div>
        ) : (
          <div className="text-center py-16 rounded-2xl" style={{ background: '#FFFFFF', border: '1px solid #E8EAF2' }}>
            <Ticket size={32} className="mx-auto mb-3" style={{ color: '#C8CADE' }} />
            <p className="text-sm font-medium" style={{ color: '#9CA3B8' }}>該当する抽選案件はありません。</p>
          </div>
        )}
      </div>
    </section>
  );
}
