// ============================================================
// SOUBA — New Products Section (Light Mode)
// ============================================================

import { Calendar, Ticket, Clock, Star, Sparkles } from 'lucide-react';
import { newProducts, formatPrice, type NewProduct } from '@/lib/data';

const statusConfig = {
  lottery: { label: '抽選販売', bg: '#F5F3FF', color: '#7C3AED', border: '#DDD6FE', icon: <Ticket size={11} /> },
  preorder: { label: '予約受付中', bg: '#EFF6FF', color: '#2563EB', border: '#BFDBFE', icon: <Clock size={11} /> },
  upcoming: { label: '発売予定', bg: '#FFFBEB', color: '#D97706', border: '#FDE68A', icon: <Calendar size={11} /> },
};

function NewProductCard({ item, index }: { item: NewProduct; index: number }) {
  const status = statusConfig[item.status];
  const isAdvanced = item.targetUser === 'advanced';

  return (
    <div className="souba-card fade-in-up" style={{ animationDelay: `${index * 80}ms`, overflow: 'hidden' }}>
      <div className="h-1 rounded-t-[14px]" style={{
        background: isAdvanced
          ? 'linear-gradient(90deg, #7C3AED, #2563EB)'
          : 'linear-gradient(90deg, #059669, #0284C7)',
      }} />
      <div className="p-5">
        <div className="flex items-start gap-4 mb-4">
          <div className="w-12 h-12 rounded-xl overflow-hidden flex-shrink-0" style={{ background: '#F8FAFC', border: '1px solid #E2E8F0' }}>
            <img src={item.image} alt={item.name} className="w-full h-full object-cover" loading="lazy" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full" style={{ background: status.bg, border: `1px solid ${status.border}` }}>
                <span style={{ color: status.color }}>{status.icon}</span>
                <span className="text-xs font-semibold" style={{ color: status.color }}>{status.label}</span>
              </div>
              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full"
                style={{ background: isAdvanced ? '#F5F3FF' : '#F0FDF4', border: `1px solid ${isAdvanced ? '#DDD6FE' : '#BBF7D0'}` }}>
                {isAdvanced ? <Sparkles size={10} style={{ color: '#7C3AED' }} /> : <Star size={10} style={{ color: '#059669' }} />}
                <span className="text-xs font-semibold" style={{ color: isAdvanced ? '#7C3AED' : '#059669' }}>
                  {isAdvanced ? '上級者向け' : '初心者向け'}
                </span>
              </div>
            </div>
            <h3 className="text-sm font-bold" style={{ color: '#0F172A' }}>{item.name}</h3>
            <div className="flex items-center gap-1 mt-1">
              <Calendar size={10} style={{ color: '#94A3B8' }} />
              <span className="text-xs" style={{ color: '#94A3B8' }}>{item.releaseDate}</span>
            </div>
          </div>
        </div>

        {item.expectedProfit && (
          <div className="flex items-center justify-between p-3 rounded-xl mb-4" style={{ background: '#F0FDF4', border: '1px solid #BBF7D0' }}>
            <div>
              <div className="text-xs mb-0.5 uppercase tracking-wider" style={{ color: '#94A3B8' }}>予想利益</div>
              <div className="text-xl font-bold font-mono" style={{ color: '#059669', fontFamily: "'JetBrains Mono', monospace" }}>
                +{formatPrice(item.expectedProfit)}〜
              </div>
            </div>
            <div className="text-xs px-2.5 py-1 rounded-lg font-semibold" style={{ background: '#DCFCE7', color: '#16A34A' }}>予測値</div>
          </div>
        )}

        <p className="text-xs leading-relaxed" style={{ color: '#64748B' }}>{item.reason}</p>
      </div>
    </div>
  );
}

export default function NewProductsSection() {
  return (
    <section id="new-products" className="py-16" style={{ background: '#FFFFFF' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-1.5 h-5 rounded-full section-bar-blue" />
          <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#2563EB' }}>New Products</span>
        </div>
        <h2 className="text-2xl font-bold mb-1" style={{ color: '#0F172A', fontFamily: 'Inter, system-ui', letterSpacing: '-0.02em' }}>
          新商品速報
        </h2>
        <p className="text-sm mb-8" style={{ color: '#64748B' }}>発売予定・抽選・予約情報と予想利益</p>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {newProducts.map((item, index) => (
            <NewProductCard key={item.id} item={item} index={index} />
          ))}
        </div>
      </div>
    </section>
  );
}
