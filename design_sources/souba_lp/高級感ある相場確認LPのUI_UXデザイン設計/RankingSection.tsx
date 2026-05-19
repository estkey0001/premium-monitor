// ============================================================
// SOUBA — Ranking Section (Light Mode)
// ============================================================

import { useState } from 'react';
import { Crown } from 'lucide-react';
import { rankingData, formatPrice, categoryLabel, type RankingItem } from '@/lib/data';

type RankingTab = 'overall' | 'iphone' | 'camera' | 'game';

const tabs: { id: RankingTab; label: string; color: string; bg: string }[] = [
  { id: 'overall', label: '総合', color: '#059669', bg: '#F0FDF4' },
  { id: 'iphone', label: 'iPhone', color: '#0F172A', bg: '#F1F5F9' },
  { id: 'camera', label: 'カメラ', color: '#D97706', bg: '#FFFBEB' },
  { id: 'game', label: 'ゲーム機', color: '#7C3AED', bg: '#F5F3FF' },
];

function RankingRow({ item, isFirst }: { item: RankingItem; isFirst: boolean }) {
  return (
    <div
      className="flex items-center gap-4 p-4 rounded-xl transition-all duration-150 mb-2"
      style={{
        background: isFirst ? '#FFFBEB' : '#FFFFFF',
        border: `1px solid ${isFirst ? '#FDE68A' : '#E2E8F0'}`,
        boxShadow: isFirst ? '0 2px 8px rgba(217,119,6,0.1)' : '0 1px 3px rgba(15,23,42,0.04)',
      }}
      onMouseEnter={(e) => { if (!isFirst) (e.currentTarget as HTMLElement).style.background = '#F8FAFC'; }}
      onMouseLeave={(e) => { if (!isFirst) (e.currentTarget as HTMLElement).style.background = '#FFFFFF'; }}
    >
      <div className="w-8 flex-shrink-0 text-center">
        {isFirst ? (
          <Crown size={18} style={{ color: '#D97706', margin: '0 auto' }} />
        ) : (
          <span className="text-base font-bold font-mono" style={{ color: '#CBD5E1', fontFamily: "'JetBrains Mono', monospace" }}>
            {item.rank}
          </span>
        )}
      </div>
      <div className="w-10 h-10 rounded-lg overflow-hidden flex-shrink-0" style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}>
        <img src={item.image} alt={item.name} className="w-full h-full object-cover" loading="lazy" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold truncate" style={{ color: '#0F172A' }}>{item.name}</div>
        <div className="text-xs" style={{ color: '#94A3B8' }}>{categoryLabel[item.category]}</div>
      </div>
      <div className="text-right flex-shrink-0">
        <div className="text-base font-bold font-mono" style={{ color: '#059669', fontFamily: "'JetBrains Mono', monospace" }}>
          +{formatPrice(item.profit)}
        </div>
        <div className="text-xs font-semibold" style={{ color: '#16A34A' }}>+{item.profitRate}%</div>
      </div>
    </div>
  );
}

export default function RankingSection() {
  const [activeTab, setActiveTab] = useState<RankingTab>('overall');
  const items = rankingData[activeTab];

  return (
    <section id="ranking" className="py-16" style={{ background: '#FFFFFF' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-1.5 h-5 rounded-full section-bar-amber" />
          <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#D97706' }}>Ranking</span>
        </div>
        <h2 className="text-2xl font-bold mb-1" style={{ color: '#0F172A', fontFamily: 'Inter, system-ui', letterSpacing: '-0.02em' }}>
          今日の利益ランキング
        </h2>
        <p className="text-sm mb-8" style={{ color: '#64748B' }}>本日の利益額・利益率上位案件</p>

        <div className="flex items-center gap-1 mb-6 p-1 rounded-xl w-fit" style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}>
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className="px-4 py-1.5 rounded-lg text-sm font-medium transition-all duration-150 press-effect"
              style={{
                background: activeTab === tab.id ? '#FFFFFF' : 'transparent',
                color: activeTab === tab.id ? tab.color : '#94A3B8',
                border: activeTab === tab.id ? '1px solid #E2E8F0' : '1px solid transparent',
                boxShadow: activeTab === tab.id ? '0 1px 3px rgba(15,23,42,0.06)' : 'none',
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="max-w-2xl">
          {items.map((item, index) => (
            <RankingRow key={item.name} item={item} isFirst={index === 0} />
          ))}
        </div>
      </div>
    </section>
  );
}
