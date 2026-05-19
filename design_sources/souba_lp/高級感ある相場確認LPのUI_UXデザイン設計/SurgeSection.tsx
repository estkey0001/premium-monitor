// ============================================================
// SOUBA — Surge Section (Light Mode)
// ============================================================

import { TrendingUp, TrendingDown, Zap } from 'lucide-react';

const surgeItems = [
  { id: 1, name: 'FUJIFILM X100VI', change: '+¥18,000', changeRate: '+6.4%', currentPrice: '¥298,000', direction: 'up' as const, reason: '海外需要増加により急騰', time: '本日 09:30' },
  { id: 2, name: 'Nintendo Switch 2 ゼルダ限定版', change: '+¥12,000', changeRate: '+13.9%', currentPrice: '¥98,000', direction: 'up' as const, reason: '抽選結果発表後に急騰', time: '本日 10:15' },
  { id: 3, name: 'iPhone 15 Pro Max 512GB', change: '-¥8,000', changeRate: '-5.3%', currentPrice: '¥142,000', direction: 'down' as const, reason: 'iPhone 16シリーズの影響で下落', time: '本日 11:00' },
  { id: 4, name: 'PS5 本体 (CFI-2000)', change: '+¥3,500', changeRate: '+6.3%', currentPrice: '¥59,000', direction: 'up' as const, reason: '新作ゲーム発売前の需要増', time: '本日 08:45' },
];

export default function SurgeSection() {
  return (
    <section id="surge" className="py-16" style={{ background: '#F8FAFC' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-1.5 h-5 rounded-full section-bar-amber" />
          <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#D97706' }}>Surge / Drop</span>
        </div>
        <h2 className="text-2xl font-bold mb-1" style={{ color: '#0F172A', fontFamily: 'Inter, system-ui', letterSpacing: '-0.02em' }}>
          急騰 / 急落
        </h2>
        <p className="text-sm mb-8" style={{ color: '#64748B' }}>本日の価格変動が大きい案件</p>

        <div className="grid sm:grid-cols-2 gap-4">
          {surgeItems.map((item, index) => {
            const isUp = item.direction === 'up';
            return (
              <div
                key={item.id}
                className="souba-card fade-in-up"
                style={{ animationDelay: `${index * 80}ms`, padding: '16px 20px' }}
              >
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <div className="w-6 h-6 rounded-lg flex items-center justify-center"
                        style={{ background: isUp ? '#F0FDF4' : '#FEF2F2' }}>
                        {isUp
                          ? <TrendingUp size={12} style={{ color: '#059669' }} />
                          : <TrendingDown size={12} style={{ color: '#DC2626' }} />
                        }
                      </div>
                      <span className="text-xs font-semibold" style={{ color: isUp ? '#059669' : '#DC2626' }}>
                        {isUp ? '急騰' : '急落'}
                      </span>
                      <span className="text-xs" style={{ color: '#94A3B8' }}>{item.time}</span>
                    </div>
                    <h3 className="text-sm font-bold" style={{ color: '#0F172A' }}>{item.name}</h3>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <div className="text-xl font-bold font-mono" style={{ color: isUp ? '#059669' : '#DC2626', fontFamily: "'JetBrains Mono', monospace" }}>
                      {item.change}
                    </div>
                    <div className="text-sm font-semibold" style={{ color: isUp ? '#16A34A' : '#EF4444' }}>
                      {item.changeRate}
                    </div>
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Zap size={11} style={{ color: '#D97706' }} />
                    <span className="text-xs" style={{ color: '#64748B' }}>{item.reason}</span>
                  </div>
                  <span className="text-xs font-mono font-semibold" style={{ color: '#64748B', fontFamily: "'JetBrains Mono', monospace" }}>
                    {item.currentPrice}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
