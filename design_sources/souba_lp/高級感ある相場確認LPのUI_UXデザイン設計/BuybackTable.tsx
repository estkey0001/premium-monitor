// ============================================================
// SOUBA — Premium Buyback Table v3
// ============================================================

import { useState } from 'react';
import { ExternalLink, ChevronUp, ChevronDown, Crown, ArrowUpRight } from 'lucide-react';
import { formatPrice, beginnerItems } from '@/lib/data';

const productOptions = [
  { id: 'iphone-16-pro-256', label: 'iPhone 16 Pro 256GB' },
  { id: 'iphone-16-128', label: 'iPhone 16 128GB' },
  { id: 'macbook-air-m3', label: 'MacBook Air M3' },
  { id: 'airpods-pro-2', label: 'AirPods Pro 2' },
  { id: 'switch-oled', label: 'Switch OLED ホワイト' },
];

export default function BuybackTable() {
  const [selectedProduct, setSelectedProduct] = useState('iphone-16-pro-256');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const product = beginnerItems.find(i => i.id === selectedProduct);
  const stores = product
    ? [...product.stores].sort((a, b) => sortDir === 'desc' ? b.price - a.price : a.price - b.price)
    : [];
  const topPrice = stores[0]?.price ?? 0;

  return (
    <section id="buyback" className="py-16" style={{ background: '#FFFFFF' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8">
          <div>
            <span className="section-label section-label-blue mb-3 inline-flex">Buyback Comparison</span>
            <h2 className="text-2xl font-black" style={{ color: '#0D0F1C', letterSpacing: '-0.03em' }}>買取価格ランキング</h2>
            <p className="text-sm mt-1" style={{ color: '#5B6278' }}>どこが一番高く買い取るか、一目で確認</p>
          </div>
          <div className="relative">
            <select
              value={selectedProduct}
              onChange={(e) => setSelectedProduct(e.target.value)}
              className="pl-4 pr-10 py-2.5 rounded-xl text-sm font-semibold outline-none appearance-none"
              style={{ background: '#F4F5FD', border: '1px solid #E8EAF2', color: '#0D0F1C', minWidth: '200px' }}
            >
              {productOptions.map(opt => <option key={opt.id} value={opt.id}>{opt.label}</option>)}
            </select>
            <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: '#9CA3B8' }} />
          </div>
        </div>

        <div className="rounded-2xl overflow-hidden" style={{ border: '1px solid #E8EAF2', boxShadow: '0 2px 12px rgba(13,15,28,0.06)' }}>
          <div className="px-5 py-3.5 flex items-center justify-between" style={{ background: '#F7F8FD', borderBottom: '1px solid #E8EAF2' }}>
            <div className="flex items-center gap-2">
              <Crown size={15} style={{ color: '#F5A623' }} />
              <span className="text-sm font-bold" style={{ color: '#0D0F1C' }}>
                {product?.shortName ?? '—'} — 買取価格比較
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs" style={{ color: '#9CA3B8' }}>最終更新: 12:00 JST</span>
              <button
                onClick={() => setSortDir(d => d === 'desc' ? 'asc' : 'desc')}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-semibold press-effect"
                style={{ background: '#EAECF5', color: '#5B6278' }}
              >
                {sortDir === 'desc' ? <ChevronDown size={11} /> : <ChevronUp size={11} />}
                {sortDir === 'desc' ? '高い順' : '低い順'}
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="souba-table">
              <thead>
                <tr>
                  {['順位', '買取店', '買取価格', '差額', '更新', '確認'].map(col => (
                    <th key={col}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stores.map((store, index) => {
                  const isTop = index === 0;
                  const diff = store.price - topPrice;
                  return (
                    <tr key={store.name} className={isTop ? 'row-best' : ''}>
                      <td>
                        {isTop ? (
                          <div className="flex items-center gap-1.5">
                            <Crown size={14} style={{ color: '#F5A623' }} />
                            <span className="font-black font-mono text-sm" style={{ color: '#F5A623', fontFamily: "'JetBrains Mono', monospace" }}>1</span>
                          </div>
                        ) : (
                          <span className="font-mono text-sm" style={{ color: '#C8CADE', fontFamily: "'JetBrains Mono', monospace" }}>{index + 1}</span>
                        )}
                      </td>
                      <td>
                        <div className="flex items-center gap-2">
                          {isTop && <span className="text-xs px-2 py-0.5 rounded-full font-black" style={{ background: '#00C896', color: '#fff', fontSize: '9px' }}>最高値</span>}
                          <span className="text-sm font-semibold" style={{ color: '#0D0F1C' }}>{store.name}</span>
                        </div>
                      </td>
                      <td>
                        <span className="text-sm font-black font-mono" style={{ color: isTop ? '#00A876' : '#0D0F1C', fontFamily: "'JetBrains Mono', monospace" }}>
                          {formatPrice(store.price)}
                        </span>
                      </td>
                      <td>
                        {isTop ? (
                          <span className="profit-pill">基準</span>
                        ) : (
                          <span className="text-sm font-bold font-mono" style={{ color: '#FF3B5C', fontFamily: "'JetBrains Mono', monospace" }}>{formatPrice(diff)}</span>
                        )}
                      </td>
                      <td><span className="text-xs" style={{ color: '#9CA3B8' }}>12:00</span></td>
                      <td>
                        <a href={store.url || '#'} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-bold press-effect transition-all"
                          style={{ background: isTop ? 'linear-gradient(135deg, #00C896, #00A876)' : '#F4F5FD', color: isTop ? '#fff' : '#5B6278', border: isTop ? 'none' : '1px solid #E8EAF2' }}
                        >
                          確認 <ArrowUpRight size={10} />
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="px-5 py-3 flex items-center justify-between" style={{ background: '#F7F8FD', borderTop: '1px solid #E8EAF2' }}>
            <p className="text-xs" style={{ color: '#9CA3B8' }}>※ 未開封・付属品完備の参考価格。実際の査定額は状態により異なります。</p>
            <span className="text-xs font-semibold" style={{ color: '#C8CADE' }}>{stores.length}店舗</span>
          </div>
        </div>
      </div>
    </section>
  );
}
