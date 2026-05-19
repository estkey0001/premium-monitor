// ============================================================
// SOUBA — Beginner Section v4
// 公式価格リンク・買取ページリンク付き
// ============================================================

import { useState } from 'react';
import { ExternalLink, TrendingUp, TrendingDown, Minus, ChevronDown, ChevronUp, AlertCircle, Store, Heart, Flame, Link2 } from 'lucide-react';
import { beginnerItems, formatPrice, categoryLabel, type BeginnerItem } from '@/lib/data';

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

function BeginnerCard({ item, index }: { item: BeginnerItem; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const [watched, setWatched]   = useState(false);
  const score  = getProfitScore(item.profitRate);
  const profit = item.topBuybackPrice - item.officialPrice;

  return (
    <div className="souba-card fade-in-up" style={{ animationDelay: `${index * 70}ms`, overflow: 'hidden' }}>
      {/* Profit bar */}
      <div style={{ height: '3px', background: `linear-gradient(90deg, #00C896 ${Math.min(item.profitRate * 4, 100)}%, #E8EAF2 0%)` }} />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-start gap-3 mb-4">
          <div className="w-14 h-14 rounded-2xl overflow-hidden flex-shrink-0" style={{ background: '#F4F5FD', border: '1px solid #E8EAF2' }}>
            <img src={item.image} alt={item.shortName} className="w-full h-full object-cover" loading="lazy" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-xs font-bold uppercase tracking-wider" style={{ color: '#9CA3B8' }}>{categoryLabel[item.category]}</span>
              <TrendIcon trend={item.trend} />
              {item.trend === 'up' && (
                <span className="text-xs px-1.5 py-0.5 rounded-full font-bold" style={{ background: '#FFF3E0', color: '#E07800', fontSize: '9px' }}>
                  <Flame size={8} style={{ display: 'inline', marginRight: 2 }} />人気
                </span>
              )}
            </div>
            <h3 className="text-sm font-bold leading-snug" style={{ color: '#0D0F1C' }}>{item.name}</h3>
            <div className="flex items-center gap-1.5 mt-1">
              <span className="text-xs" style={{ color: '#9CA3B8' }}>更新 {item.updatedAt}</span>
              <span style={{ color: '#E8EAF2' }}>·</span>
              <span className="text-xs" style={{ color: '#9CA3B8' }}>{item.storeCount}店舗</span>
            </div>
          </div>
          <div className="flex flex-col items-end gap-2 flex-shrink-0">
            <div className={`score-badge ${score.cls}`}>{score.grade}</div>
            <button
              onClick={() => setWatched(!watched)}
              className={`watchlist-btn p-1.5 rounded-lg ${watched ? 'active' : ''}`}
              style={{ background: watched ? '#FFF1F3' : '#F4F5FD', color: watched ? '#FF3B5C' : '#C8CADE', border: `1px solid ${watched ? '#FECDD3' : '#E8EAF2'}` }}
            >
              <Heart size={13} fill={watched ? '#FF3B5C' : 'none'} />
            </button>
          </div>
        </div>

        {/* Price block */}
        <div className="rounded-2xl p-4 mb-4" style={{ background: '#F7F8FD', border: '1px solid #E8EAF2' }}>
          <div className="grid grid-cols-2 gap-3 mb-3">
            {/* Official price with link */}
            <div>
              <div className="flex items-center gap-1 mb-1">
                <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#9CA3B8' }}>公式価格</span>
                <a href={item.officialUrl} target="_blank" rel="noopener noreferrer" title="公式ページで確認" style={{ color: '#3B7BFF' }}>
                  <Link2 size={10} />
                </a>
              </div>
              <a
                href={item.officialUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-base font-bold font-mono"
                style={{ color: '#5B6278', fontFamily: "'JetBrains Mono', monospace", textDecoration: 'none' }}
                onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.textDecoration = 'underline'}
                onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.textDecoration = 'none'}
              >
                {formatPrice(item.officialPrice)}
              </a>
            </div>
            {/* Top buyback */}
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: '#9CA3B8' }}>最高買取</div>
              <div className="text-base font-bold font-mono" style={{ color: '#0D0F1C', fontFamily: "'JetBrains Mono', monospace" }}>
                {formatPrice(item.topBuybackPrice)}
              </div>
            </div>
          </div>
          {/* Profit */}
          <div className="flex items-center justify-between px-4 py-3 rounded-xl"
            style={{ background: 'linear-gradient(135deg, #F0FDF8, #E8FFF4)', border: '1px solid #A7F3D0' }}>
            <div>
              <div className="text-xs font-bold uppercase tracking-wider mb-0.5" style={{ color: '#047857' }}>実質利益</div>
              <div className="profit-number profit-number-lg">+{formatPrice(profit)}</div>
            </div>
            <div className="text-right">
              <div className="text-xs mb-0.5" style={{ color: '#9CA3B8' }}>利益率</div>
              <div className="text-2xl font-black font-mono" style={{ color: '#00A876', fontFamily: "'JetBrains Mono', monospace" }}>
                +{item.profitRate}%
              </div>
            </div>
          </div>
        </div>

        {/* Store compare */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-semibold transition-all duration-150 press-effect"
          style={{ background: '#F4F5FD', color: '#5B6278', border: '1px solid #E8EAF2' }}
        >
          <div className="flex items-center gap-1.5"><Store size={12} />店舗別買取価格を比較（買取ページリンク付き）</div>
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
                  <span className="text-sm font-black font-mono" style={{ color: store.isTop ? '#00A876' : '#0D0F1C', fontFamily: "'JetBrains Mono', monospace" }}>
                    {formatPrice(store.price)}
                  </span>
                  {/* 買取ページへの直接リンク */}
                  <a
                    href={store.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-bold press-effect"
                    style={{
                      background: store.isTop ? '#00C896' : '#F4F5FD',
                      color: store.isTop ? '#fff' : '#3B7BFF',
                      border: store.isTop ? 'none' : '1px solid #E8EAF2',
                    }}
                    title={`${store.name}の買取ページへ`}
                  >
                    買取 <ExternalLink size={9} />
                  </a>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Note */}
        <div className="mt-3 flex items-start gap-2 px-3 py-2.5 rounded-xl" style={{ background: '#FFFBEB', border: '1px solid #FCD34D' }}>
          <AlertCircle size={12} className="flex-shrink-0 mt-0.5" style={{ color: '#FF9500' }} />
          <p className="text-xs leading-relaxed" style={{ color: '#92400E' }}>{item.note}</p>
        </div>
      </div>
    </div>
  );
}

export default function BeginnerSection() {
  return (
    <section id="beginner" className="py-16" style={{ background: '#FAFBFF' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="flex items-center justify-between mb-8">
          <div>
            <div className="flex items-center gap-3 mb-3">
              <span className="section-label section-label-green">Beginner</span>
              <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full" style={{ background: '#E8FFF6', border: '1px solid #A7F3D0' }}>
                <div className="w-1.5 h-1.5 rounded-full live-pulse" style={{ background: '#00C896' }} />
                <span className="text-xs font-bold" style={{ color: '#047857' }}>{beginnerItems.length}件掲載中</span>
              </div>
            </div>
            <h2 className="text-2xl font-black" style={{ color: '#0D0F1C', letterSpacing: '-0.03em' }}>初心者向け案件</h2>
            <p className="text-sm mt-1" style={{ color: '#5B6278' }}>低難度・定価購入可能・買取差益が明確な案件。公式価格・買取ページへ直接リンク。</p>
          </div>
          <div className="hidden sm:flex items-center gap-2">
            <span className="text-xs font-semibold" style={{ color: '#9CA3B8' }}>スコア:</span>
            {[{ g: 'S', c: 'score-s' }, { g: 'A', c: 'score-a' }, { g: 'B', c: 'score-b' }].map(s => (
              <div key={s.g} className={`score-badge ${s.c}`} style={{ width: 28, height: 28, fontSize: 12 }}>{s.g}</div>
            ))}
          </div>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {beginnerItems.map((item, i) => <BeginnerCard key={item.id} item={item} index={i} />)}
        </div>
      </div>
    </section>
  );
}
