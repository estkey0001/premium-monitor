// ============================================================
// SOUBA — Site Footer v6
// Fix: Internal links use onTabChange
// ============================================================

import { TrendingUp, ExternalLink, Twitter, Mail } from 'lucide-react';
import type { TabId } from './StickyTabs';

interface SiteFooterProps {
  onTabChange: (tab: TabId) => void;
}

export default function SiteFooter({ onTabChange }: SiteFooterProps) {
  const categories: { label: string; tab: TabId }[] = [
    { label: 'スマートフォン', tab: 'smartphone' },
    { label: 'タブレット',     tab: 'tablet' },
    { label: 'PC・ノートPC',   tab: 'pc' },
    { label: 'カメラ',         tab: 'camera' },
    { label: 'ゲーム機',       tab: 'game' },
    { label: '抽選情報',       tab: 'lottery' },
    { label: 'せどり計算',     tab: 'sedori' },
    { label: 'ランキング',     tab: 'ranking' },
  ];

  return (
    <footer style={{ background: '#0D0F1C', borderTop: '1px solid rgba(255,255,255,0.06)' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6 py-14">
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-10 mb-12">
          {/* Brand */}
          <div className="lg:col-span-2">
            <button
              onClick={() => onTabChange('ranking')}
              className="flex items-center gap-2.5 mb-4 press-effect"
              style={{ background: 'none', border: 'none', cursor: 'pointer' }}
            >
              <div className="w-8 h-8 rounded-xl flex items-center justify-center" style={{ background: 'linear-gradient(135deg, #00C896, #00A876)', boxShadow: '0 2px 8px rgba(0,200,150,0.3)' }}>
                <TrendingUp size={15} className="text-white" />
              </div>
              <span className="text-lg font-black" style={{ color: '#FFFFFF', letterSpacing: '-0.04em' }}>SOUBA</span>
            </button>
            <p className="text-sm leading-relaxed mb-5" style={{ color: 'rgba(255,255,255,0.4)', maxWidth: '320px' }}>
              スマホ・カメラ・ゲーム機の定価・買取価格・海外相場を毎日整理。転売・せどりに必要な情報をすべて1ページで。
            </p>
            <div className="flex items-center gap-3">
              <a href="https://note.com" target="_blank" rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-bold btn-primary press-effect">
                <ExternalLink size={12} /> note
              </a>
              <a href="#" className="w-9 h-9 rounded-xl flex items-center justify-center press-effect"
                style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.4)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <Twitter size={15} />
              </a>
              <a href="#" className="w-9 h-9 rounded-xl flex items-center justify-center press-effect"
                style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.4)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <Mail size={15} />
              </a>
            </div>
          </div>

          {/* Categories */}
          <div>
            <h4 className="text-xs font-black uppercase tracking-widest mb-5" style={{ color: 'rgba(255,255,255,0.25)' }}>カテゴリ</h4>
            <ul className="space-y-3">
              {categories.slice(0, 4).map(item => (
                <li key={item.label}>
                  <button
                    onClick={() => onTabChange(item.tab)}
                    className="text-sm font-medium transition-colors press-effect text-left"
                    style={{ color: 'rgba(255,255,255,0.4)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                    onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = 'rgba(255,255,255,0.8)'}
                    onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = 'rgba(255,255,255,0.4)'}
                  >
                    {item.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h4 className="text-xs font-black uppercase tracking-widest mb-5" style={{ color: 'rgba(255,255,255,0.25)' }}>ツール</h4>
            <ul className="space-y-3">
              {categories.slice(4).map(item => (
                <li key={item.label}>
                  <button
                    onClick={() => onTabChange(item.tab)}
                    className="text-sm font-medium transition-colors press-effect text-left"
                    style={{ color: 'rgba(255,255,255,0.4)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                    onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = 'rgba(255,255,255,0.8)'}
                    onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = 'rgba(255,255,255,0.4)'}
                  >
                    {item.label}
                  </button>
                </li>
              ))}
              {[
                { label: 'eBay Sold', url: 'https://www.ebay.com/sch/i.html?_nkw=iphone+16+pro&LH_Sold=1&LH_Complete=1' },
                { label: 'B&H Photo', url: 'https://www.bhphotovideo.com' },
                { label: 'MPB', url: 'https://www.mpb.com' },
              ].map(item => (
                <li key={item.label}>
                  <a href={item.url} target="_blank" rel="noopener noreferrer"
                    className="text-sm font-medium flex items-center gap-1 transition-colors" style={{ color: 'rgba(255,255,255,0.4)' }}
                    onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.color = '#3B7BFF'}
                    onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.color = 'rgba(255,255,255,0.4)'}
                  >
                    {item.label} <ExternalLink size={10} />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-8" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <p className="text-xs" style={{ color: 'rgba(255,255,255,0.2)' }}>
            © 2026 SOUBA. 掲載情報は参考値です。実際の取引は自己責任でお願いします。
          </p>
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full live-pulse" style={{ background: '#00C896' }} />
            <span className="text-xs font-semibold" style={{ color: 'rgba(255,255,255,0.25)' }}>毎日12:00 JST更新</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
