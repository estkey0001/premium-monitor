// ============================================================
// SOUBA — Sticky Tabs v6
// Order: ランキング → せどり計算 → 初心者 → 上級者 → 急騰/急落 → 抽選情報
//        → ジャンル: スマホ / タブレット / PC / カメラ / ゲーム機
// ============================================================

import { useEffect, useRef, useState } from 'react';
import {
  BarChart2, Calculator, Star, Sparkles, Zap, Ticket,
  Smartphone, Tablet, Monitor, Camera, Gamepad2,
} from 'lucide-react';

export type TabId =
  | 'ranking' | 'sedori' | 'beginner' | 'advanced' | 'surge' | 'lottery'
  | 'smartphone' | 'tablet' | 'pc' | 'camera' | 'game';

interface Tab {
  id: TabId;
  label: string;
  icon: React.ReactNode;
  badge?: string;
  badgeStyle?: React.CSSProperties;
  group: 'main' | 'genre';
}

const tabs: Tab[] = [
  { id: 'ranking',    label: 'ランキング',   icon: <BarChart2 size={12} />,   group: 'main' },
  { id: 'sedori',     label: 'せどり計算',   icon: <Calculator size={12} />,  badge: 'NEW', badgeStyle: { background: '#EEF4FF', color: '#1D4ED8' }, group: 'main' },
  { id: 'beginner',   label: '初心者向け',   icon: <Star size={12} />,        badge: '12',  badgeStyle: { background: '#E8FFF6', color: '#047857' }, group: 'main' },
  { id: 'advanced',   label: '上級者向け',   icon: <Sparkles size={12} />,    badge: '8',   badgeStyle: { background: '#F0EEFF', color: '#6040E8' }, group: 'main' },
  { id: 'surge',      label: '急騰/急落',    icon: <Zap size={12} />,         badge: 'HOT', badgeStyle: { background: '#FFF3E0', color: '#E07800' }, group: 'main' },
  { id: 'lottery',    label: '抽選情報',     icon: <Ticket size={12} />,      badge: '6',   badgeStyle: { background: '#F0EEFF', color: '#7C5CFC' }, group: 'main' },
  { id: 'smartphone', label: 'スマホ',       icon: <Smartphone size={12} />,  group: 'genre' },
  { id: 'tablet',     label: 'タブレット',   icon: <Tablet size={12} />,      group: 'genre' },
  { id: 'pc',         label: 'PC',           icon: <Monitor size={12} />,     group: 'genre' },
  { id: 'camera',     label: 'カメラ',       icon: <Camera size={12} />,      group: 'genre' },
  { id: 'game',       label: 'ゲーム機',     icon: <Gamepad2 size={12} />,    group: 'genre' },
];

const activeColors: Record<TabId, { text: string; bg: string; indicator: string }> = {
  ranking:    { text: '#1D4ED8', bg: '#EEF4FF',  indicator: '#3B7BFF' },
  sedori:     { text: '#1D4ED8', bg: '#EEF4FF',  indicator: '#3B7BFF' },
  beginner:   { text: '#047857', bg: '#F0FDF8',  indicator: '#00C896' },
  advanced:   { text: '#6040E8', bg: '#F0EEFF',  indicator: '#7C5CFC' },
  surge:      { text: '#B45309', bg: '#FFF8E8',  indicator: '#FF9500' },
  lottery:    { text: '#6040E8', bg: '#F5F3FF',  indicator: '#7C5CFC' },
  smartphone: { text: '#0D0F1C', bg: '#F4F5FD',  indicator: '#0D0F1C' },
  tablet:     { text: '#1D4ED8', bg: '#EEF4FF',  indicator: '#3B7BFF' },
  pc:         { text: '#1D4ED8', bg: '#EEF4FF',  indicator: '#3B7BFF' },
  camera:     { text: '#B45309', bg: '#FFF8E8',  indicator: '#FF9500' },
  game:       { text: '#6040E8', bg: '#F0EEFF',  indicator: '#7C5CFC' },
};

interface StickyTabsProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
}

export default function StickyTabs({ activeTab, onTabChange }: StickyTabsProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [ind, setInd] = useState({ left: 0, width: 0 });
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  useEffect(() => {
    const el = tabRefs.current[activeTab];
    if (el && scrollRef.current) {
      const cr = scrollRef.current.getBoundingClientRect();
      const er = el.getBoundingClientRect();
      setInd({ left: er.left - cr.left + scrollRef.current.scrollLeft, width: er.width });
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
  }, [activeTab]);

  const mainTabs  = tabs.filter(t => t.group === 'main');
  const genreTabs = tabs.filter(t => t.group === 'genre');

  return (
    <div
      data-sticky-tabs
      className="sticky z-40"
      style={{ top: 0, background: 'rgba(250,251,255,0.95)', backdropFilter: 'blur(20px)', borderBottom: '1px solid #E8EAF2', boxShadow: '0 1px 0 rgba(13,15,28,0.04)' }}
    >
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="relative">
          <div ref={scrollRef} className="tab-scroll flex items-center gap-0.5 overflow-x-auto py-2">
            <div
              className="absolute bottom-0 h-0.5 rounded-full tab-indicator"
              style={{ left: `${ind.left}px`, width: `${ind.width}px`, background: activeColors[activeTab]?.indicator ?? '#00C896' }}
            />
            {mainTabs.map(tab => (
              <TabBtn key={tab.id} tab={tab} activeTab={activeTab} tabRefs={tabRefs} onTabChange={onTabChange} />
            ))}
            <div className="w-px h-4 mx-2 flex-shrink-0" style={{ background: '#E8EAF2' }} />
            <span className="text-xs font-black uppercase tracking-widest px-1 flex-shrink-0" style={{ color: '#C8CADE' }}>ジャンル</span>
            {genreTabs.map(tab => (
              <TabBtn key={tab.id} tab={tab} activeTab={activeTab} tabRefs={tabRefs} onTabChange={onTabChange} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function TabBtn({
  tab, activeTab, tabRefs, onTabChange,
}: {
  tab: Tab;
  activeTab: TabId;
  tabRefs: React.MutableRefObject<Record<string, HTMLButtonElement | null>>;
  onTabChange: (tab: TabId) => void;
}) {
  const isActive = activeTab === tab.id;
  const colors   = activeColors[tab.id];
  return (
    <button
      ref={(el) => { tabRefs.current[tab.id] = el; }}
      onClick={() => onTabChange(tab.id)}
      className="relative flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-semibold whitespace-nowrap transition-all duration-150 press-effect flex-shrink-0"
      style={{ color: isActive ? colors.text : '#9CA3B8', background: isActive ? colors.bg : 'transparent', border: 'none', cursor: 'pointer' }}
      onMouseEnter={(e) => { if (!isActive) { (e.currentTarget as HTMLElement).style.background = '#F4F5FD'; (e.currentTarget as HTMLElement).style.color = '#0D0F1C'; } }}
      onMouseLeave={(e) => { if (!isActive) { (e.currentTarget as HTMLElement).style.background = 'transparent'; (e.currentTarget as HTMLElement).style.color = '#9CA3B8'; } }}
    >
      <span style={{ color: isActive ? colors.text : '#C8CADE' }}>{tab.icon}</span>
      {tab.label}
      {tab.badge && (
        <span className="text-xs px-1.5 py-0.5 rounded-full font-bold" style={{ ...tab.badgeStyle, fontSize: '10px', lineHeight: 1 }}>
          {tab.badge}
        </span>
      )}
    </button>
  );
}
