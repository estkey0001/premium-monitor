// ============================================================
// SOUBA — Advanced Section (Light Mode)
// ============================================================

import { ExternalLink, Flame, Globe, Ticket, AlertTriangle, TrendingUp } from 'lucide-react';
import { advancedItems, formatPrice, formatUSD, type AdvancedItem } from '@/lib/data';

const tagConfig: Record<string, { bg: string; color: string; icon?: React.ReactNode }> = {
  'プレ値': { bg: '#FFFBEB', color: '#D97706', icon: <Flame size={10} /> },
  '高難度': { bg: '#FEF2F2', color: '#DC2626', icon: <AlertTriangle size={10} /> },
  '海外差益': { bg: '#EFF6FF', color: '#2563EB', icon: <Globe size={10} /> },
  '限定': { bg: '#F5F3FF', color: '#7C3AED', icon: <Flame size={10} /> },
  '抽選': { bg: '#F5F3FF', color: '#7C3AED', icon: <Ticket size={10} /> },
  '急騰': { bg: '#F0FDF4', color: '#059669', icon: <TrendingUp size={10} /> },
  '新商品': { bg: '#EFF6FF', color: '#2563EB', icon: null },
  '上級者向け': { bg: '#F5F3FF', color: '#7C3AED', icon: null },
};

const overseasSources = [
  { key: 'ebayPrice', label: 'eBay Sold', url: 'https://www.ebay.com', color: '#2563EB' },
  { key: 'bnhPrice', label: 'B&H', url: 'https://www.bhphotovideo.com', color: '#2563EB' },
  { key: 'mpbPrice', label: 'MPB', url: 'https://www.mpb.com', color: '#059669' },
  { key: 'kehPrice', label: 'KEH', url: 'https://www.keh.com', color: '#059669' },
  { key: 'stockxPrice', label: 'StockX', url: 'https://stockx.com', color: '#7C3AED' },
];

function StatusBadge({ status }: { status: AdvancedItem['status'] }) {
  const config = {
    active: { label: '取引中', bg: '#F0FDF4', color: '#059669', border: '#BBF7D0' },
    soldout: { label: 'SOLD OUT', bg: '#F8FAFC', color: '#94A3B8', border: '#E2E8F0' },
    lottery: { label: '抽選販売', bg: '#F5F3FF', color: '#7C3AED', border: '#DDD6FE' },
    preorder: { label: '予約受付', bg: '#EFF6FF', color: '#2563EB', border: '#BFDBFE' },
  }[status];
  return (
    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full" style={{ background: config.bg, border: `1px solid ${config.border}` }}>
      <div className="w-1.5 h-1.5 rounded-full live-pulse" style={{ background: config.color }} />
      <span className="text-xs font-semibold" style={{ color: config.color }}>{config.label}</span>
    </div>
  );
}

function AdvancedCard({ item, index }: { item: AdvancedItem; index: number }) {
  const premiumColor = item.premiumRate > 50 ? '#DC2626' : item.premiumRate > 30 ? '#D97706' : '#059669';
  const premiumBg = item.premiumRate > 50 ? '#FEF2F2' : item.premiumRate > 30 ? '#FFFBEB' : '#F0FDF4';
  const premiumBorder = item.premiumRate > 50 ? '#FECACA' : item.premiumRate > 30 ? '#FDE68A' : '#BBF7D0';

  return (
    <div className="souba-card fade-in-up" style={{ animationDelay: `${index * 100}ms` }}>
      {/* Difficulty bar */}
      <div className="h-1 rounded-t-[14px]" style={{
        background: item.difficulty === 'very-high'
          ? 'linear-gradient(90deg, #7C3AED, #EC4899)'
          : 'linear-gradient(90deg, #D97706, #DC2626)',
      }} />

      <div className="p-5">
        <div className="flex items-start gap-4 mb-4">
          <div className="w-14 h-14 rounded-xl overflow-hidden flex-shrink-0" style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}>
            <img src={item.image} alt={item.shortName} className="w-full h-full object-cover" loading="lazy" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
              <StatusBadge status={item.status} />
              {item.tags.map(tag => {
                const cfg = tagConfig[tag] ?? { bg: '#F8FAFC', color: '#64748B' };
                return (
                  <span key={tag} className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-semibold"
                    style={{ background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.color}30` }}>
                    {cfg.icon}{tag}
                  </span>
                );
              })}
            </div>
            <h3 className="text-sm font-bold leading-tight" style={{ color: '#0F172A' }}>{item.name}</h3>
            {item.lotteryDeadline && (
              <div className="flex items-center gap-1 mt-1">
                <Ticket size={10} style={{ color: '#7C3AED' }} />
                <span className="text-xs" style={{ color: '#7C3AED' }}>抽選締切: {item.lotteryDeadline}</span>
              </div>
            )}
          </div>
        </div>

        {/* Premium Rate */}
        {item.premiumRate > 0 && (
          <div className="flex items-center justify-between p-3 rounded-xl mb-4" style={{ background: premiumBg, border: `1px solid ${premiumBorder}` }}>
            <div>
              <div className="text-xs mb-0.5 uppercase tracking-wider" style={{ color: '#94A3B8' }}>プレミアム率</div>
              <div className="text-2xl font-bold font-mono" style={{ color: premiumColor, fontFamily: "'JetBrains Mono', monospace" }}>
                +{item.premiumRate}%
              </div>
            </div>
            {item.domesticUsedPrice && (
              <div className="text-right">
                <div className="text-xs mb-0.5" style={{ color: '#94A3B8' }}>国内中古相場</div>
                <div className="text-lg font-bold font-mono" style={{ color: '#0F172A', fontFamily: "'JetBrains Mono', monospace" }}>
                  {formatPrice(item.domesticUsedPrice)}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Overseas */}
        <div className="mb-4">
          <div className="flex items-center gap-1.5 mb-2">
            <Globe size={12} style={{ color: '#2563EB' }} />
            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#2563EB' }}>海外相場</span>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {overseasSources.map(src => {
              const price = (item as unknown as Record<string, number | null>)[src.key];
              return (
                <a key={src.key} href={src.url} target="_blank" rel="noopener noreferrer"
                  className="flex flex-col items-center p-2 rounded-lg transition-all duration-150"
                  style={{
                    background: price ? '#F8FAFC' : '#FAFAFA',
                    border: `1px solid ${price ? '#E2E8F0' : '#F1F5F9'}`,
                    opacity: price ? 1 : 0.5,
                    textDecoration: 'none',
                  }}
                  onMouseEnter={(e) => { if (price) (e.currentTarget as HTMLElement).style.borderColor = src.color + '60'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = price ? '#E2E8F0' : '#F1F5F9'; }}
                >
                  <span className="text-xs font-semibold mb-0.5" style={{ color: price ? src.color : '#CBD5E1' }}>{src.label}</span>
                  <span className="text-xs font-bold font-mono" style={{ color: price ? '#0F172A' : '#CBD5E1', fontFamily: "'JetBrains Mono', monospace" }}>
                    {price ? formatUSD(price) : 'N/A'}
                  </span>
                </a>
              );
            })}
          </div>
        </div>

        <p className="text-xs leading-relaxed" style={{ color: '#64748B' }}>{item.note}</p>
      </div>
    </div>
  );
}

export default function AdvancedSection() {
  return (
    <section id="advanced" className="py-16" style={{ background: '#F8FAFC' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="flex items-center justify-between mb-8">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <div className="w-1.5 h-5 rounded-full section-bar-purple" />
              <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#7C3AED' }}>Advanced</span>
            </div>
            <h2 className="text-2xl font-bold" style={{ color: '#0F172A', fontFamily: 'Inter, system-ui', letterSpacing: '-0.02em' }}>
              上級者向け案件
            </h2>
            <p className="text-sm mt-1" style={{ color: '#64748B' }}>プレ値・抽選・海外差益・限定品の相場情報</p>
          </div>
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full" style={{ background: '#F5F3FF', border: '1px solid #DDD6FE' }}>
            <Flame size={12} style={{ color: '#7C3AED' }} />
            <span className="text-xs font-semibold" style={{ color: '#7C3AED' }}>高難度案件</span>
          </div>
        </div>

        <div className="flex items-start gap-3 p-4 rounded-xl mb-8" style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}>
          <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" style={{ color: '#D97706' }} />
          <p className="text-sm" style={{ color: '#92400E' }}>
            上級者向け案件は難易度が高く、仕入れリスクが伴います。海外相場は為替レートにより変動します。必ず最新情報を確認してから判断してください。
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-5">
          {advancedItems.map((item, index) => (
            <AdvancedCard key={item.id} item={item} index={index} />
          ))}
        </div>
      </div>
    </section>
  );
}
