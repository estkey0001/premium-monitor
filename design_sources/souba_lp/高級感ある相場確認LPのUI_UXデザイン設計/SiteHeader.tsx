// ============================================================
// SOUBA — Site Header v6
// Fix: Nav links now use onTabChange instead of href anchors
// ============================================================

import { useState } from 'react';
import { TrendingUp, ExternalLink, Menu, X, Sparkles } from 'lucide-react';
import type { TabId } from './StickyTabs';

interface NavItem {
  label: string;
  tab: TabId;
}

const navItems: NavItem[] = [
  { label: 'スマホ',     tab: 'smartphone' },
  { label: 'タブレット', tab: 'tablet' },
  { label: 'PC',         tab: 'pc' },
  { label: 'カメラ',     tab: 'camera' },
  { label: 'ゲーム機',   tab: 'game' },
  { label: 'せどり計算', tab: 'sedori' },
  { label: 'ランキング', tab: 'ranking' },
  { label: '抽選情報',   tab: 'lottery' },
];

interface SiteHeaderProps {
  onTabChange: (tab: TabId) => void;
}

export default function SiteHeader({ onTabChange }: SiteHeaderProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  const handleNav = (tab: TabId) => {
    setMenuOpen(false);
    onTabChange(tab);
    // Scroll to sticky tabs
    setTimeout(() => {
      const el = document.querySelector('[data-sticky-tabs]');
      if (el) {
        const top = el.getBoundingClientRect().top + window.scrollY - 10;
        window.scrollTo({ top, behavior: 'smooth' });
      }
    }, 80);
  };

  return (
    <>
      {/* Announcement Bar */}
      <div
        className="w-full py-2 px-4 text-center text-xs font-semibold"
        style={{ background: 'linear-gradient(90deg, #00C896, #3B7BFF, #7C5CFC)', color: '#fff', letterSpacing: '0.02em' }}
      >
        <button
          onClick={() => handleNav('beginner')}
          className="hover:underline"
          style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', font: 'inherit' }}
        >
          🎯 本日 <strong>12件</strong> の初心者向け案件を更新 — 最大利益 <strong>¥131,000</strong> を確認 →
        </button>
      </div>

      <header
        className="sticky top-0 left-0 right-0 z-50"
        style={{ background: 'rgba(250,251,255,0.92)', backdropFilter: 'blur(24px)', WebkitBackdropFilter: 'blur(24px)', borderBottom: '1px solid #E8EAF2', boxShadow: '0 1px 0 rgba(13,15,28,0.04)' }}
      >
        <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-14">
            {/* Logo */}
            <button
              onClick={() => handleNav('ranking')}
              className="flex items-center gap-2.5 press-effect"
              style={{ background: 'none', border: 'none', cursor: 'pointer' }}
            >
              <div className="w-8 h-8 rounded-xl flex items-center justify-center"
                style={{ background: 'linear-gradient(135deg, #00C896, #00A876)', boxShadow: '0 2px 8px rgba(0,200,150,0.35)' }}>
                <TrendingUp size={15} className="text-white" />
              </div>
              <div className="flex items-baseline gap-1.5">
                <span className="text-base font-black tracking-tight" style={{ color: '#0D0F1C', letterSpacing: '-0.03em' }}>SOUBA</span>
                <span className="hidden sm:block text-xs font-medium" style={{ color: '#9CA3B8' }}>相場ダッシュボード</span>
              </div>
            </button>

            {/* Desktop Nav */}
            <nav className="hidden xl:flex items-center gap-0.5">
              {navItems.map((item) => (
                <button
                  key={item.label}
                  onClick={() => handleNav(item.tab)}
                  className="px-2.5 py-1.5 text-sm font-medium rounded-lg transition-all duration-150 press-effect"
                  style={{ color: '#5B6278', background: 'none', border: 'none', cursor: 'pointer' }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = '#0D0F1C'; (e.currentTarget as HTMLElement).style.background = '#F4F5FD'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = '#5B6278'; (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                >
                  {item.label}
                </button>
              ))}
            </nav>

            {/* Right */}
            <div className="flex items-center gap-2">
              <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full"
                style={{ background: '#E8FFF6', border: '1px solid #A7F3D0' }}>
                <div className="w-1.5 h-1.5 rounded-full live-pulse" style={{ background: '#00C896' }} />
                <span className="text-xs font-bold" style={{ color: '#047857' }}>LIVE</span>
              </div>
              <a href="https://note.com" target="_blank" rel="noopener noreferrer"
                className="hidden sm:flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-bold btn-primary press-effect">
                <Sparkles size={13} />
                note で読む
              </a>
              <button className="xl:hidden p-2 rounded-lg" style={{ color: '#5B6278', background: 'none', border: 'none', cursor: 'pointer' }}
                onClick={() => setMenuOpen(!menuOpen)}>
                {menuOpen ? <X size={18} /> : <Menu size={18} />}
              </button>
            </div>
          </div>
        </div>

        {/* Mobile Menu */}
        {menuOpen && (
          <div style={{ background: '#FFFFFF', borderTop: '1px solid #E8EAF2', boxShadow: '0 8px 24px rgba(13,15,28,0.08)' }}>
            <div className="max-w-[1200px] mx-auto px-4 py-3 grid grid-cols-2 gap-1">
              {navItems.map((item) => (
                <button
                  key={item.label}
                  onClick={() => handleNav(item.tab)}
                  className="px-3 py-2.5 text-sm font-medium rounded-xl text-left press-effect"
                  style={{ color: '#5B6278', background: 'none', border: 'none', cursor: 'pointer' }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#F4F5FD'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="px-4 pb-3">
              <a href="https://note.com" target="_blank" rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-bold btn-primary">
                <Sparkles size={13} /> note で読む
              </a>
            </div>
          </div>
        )}
      </header>
    </>
  );
}
