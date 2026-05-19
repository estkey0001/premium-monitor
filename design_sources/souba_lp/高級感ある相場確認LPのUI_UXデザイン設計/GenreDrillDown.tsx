// ============================================================
// SOUBA — Genre Drill-Down Navigation
// ランキング/せどり/抽選の後に表示するジャンル→メーカー2段階ナビ
// ============================================================

import { useState } from 'react';
import { Smartphone, Tablet, Monitor, Camera, Gamepad2, ChevronRight } from 'lucide-react';
import type { TabId } from './StickyTabs';
import type { GenreId } from './GenreSection';

const genres: { id: GenreId; label: string; icon: React.ReactNode; color: string; bg: string; border: string }[] = [
  { id: 'smartphone', label: 'スマホ',     icon: <Smartphone size={16} />, color: '#0D0F1C', bg: '#F4F5FD', border: '#C8CADE' },
  { id: 'tablet',     label: 'タブレット', icon: <Tablet size={16} />,     color: '#1D4ED8', bg: '#EEF4FF', border: '#BFDBFE' },
  { id: 'pc',         label: 'PC',         icon: <Monitor size={16} />,    color: '#1D4ED8', bg: '#EEF4FF', border: '#BFDBFE' },
  { id: 'camera',     label: 'カメラ',     icon: <Camera size={16} />,     color: '#B45309', bg: '#FFF8E8', border: '#FCD34D' },
  { id: 'game',       label: 'ゲーム機',   icon: <Gamepad2 size={16} />,   color: '#6040E8', bg: '#F0EEFF', border: '#C4B5FD' },
];

const makers: Record<GenreId, { id: string; label: string }[]> = {
  smartphone: [
    { id: 'apple',   label: 'Apple (iPhone)' },
    { id: 'samsung', label: 'Samsung' },
    { id: 'google',  label: 'Google Pixel' },
    { id: 'sony',    label: 'Sony Xperia' },
    { id: 'sharp',   label: 'SHARP AQUOS' },
  ],
  tablet: [
    { id: 'apple',     label: 'Apple (iPad)' },
    { id: 'samsung',   label: 'Samsung Galaxy Tab' },
    { id: 'microsoft', label: 'Microsoft Surface' },
    { id: 'amazon',    label: 'Amazon Fire' },
  ],
  pc: [
    { id: 'apple',     label: 'Apple (MacBook)' },
    { id: 'microsoft', label: 'Microsoft Surface' },
    { id: 'lenovo',    label: 'Lenovo ThinkPad' },
    { id: 'dell',      label: 'Dell XPS' },
    { id: 'hp',        label: 'HP Spectre' },
  ],
  camera: [
    { id: 'fujifilm', label: 'FUJIFILM' },
    { id: 'ricoh',    label: 'RICOH GR' },
    { id: 'leica',    label: 'Leica' },
    { id: 'sony',     label: 'Sony α' },
    { id: 'nikon',    label: 'Nikon Z' },
    { id: 'canon',    label: 'Canon EOS' },
  ],
  game: [
    { id: 'nintendo',  label: 'Nintendo Switch' },
    { id: 'sony',      label: 'PlayStation' },
    { id: 'microsoft', label: 'Xbox' },
  ],
};

interface GenreDrillDownProps {
  onTabChange: (tab: TabId) => void;
}

export default function GenreDrillDown({ onTabChange }: GenreDrillDownProps) {
  const [selectedGenre, setSelectedGenre] = useState<GenreId | null>(null);

  const handleGenreClick = (genre: GenreId) => {
    setSelectedGenre(prev => prev === genre ? null : genre);
    onTabChange(genre);
  };

  const handleMakerClick = (genre: GenreId) => {
    onTabChange(genre);
  };

  return (
    <section className="py-10" style={{ background: '#FFFFFF', borderTop: '1px solid #E8EAF2' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        {/* Header */}
        <div className="flex items-center gap-2 mb-5">
          <div className="w-1 h-4 rounded-full" style={{ background: 'linear-gradient(180deg, #00C896, #3B7BFF)' }} />
          <h3 className="text-base font-black" style={{ color: '#0D0F1C', letterSpacing: '-0.02em' }}>
            ジャンル別に探す
          </h3>
          <span className="text-xs" style={{ color: '#9CA3B8' }}>— タップしてメーカー別に絞り込み</span>
        </div>

        {/* Genre row */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
          {genres.map(g => {
            const isSelected = selectedGenre === g.id;
            return (
              <button
                key={g.id}
                onClick={() => handleGenreClick(g.id)}
                className="flex items-center gap-2.5 px-4 py-3 rounded-2xl font-semibold text-sm transition-all duration-150 press-effect"
                style={{
                  background: isSelected ? g.bg : '#F7F8FD',
                  border: `2px solid ${isSelected ? g.border : '#E8EAF2'}`,
                  color: isSelected ? g.color : '#5B6278',
                  boxShadow: isSelected ? `0 2px 12px ${g.color}20` : 'none',
                }}
              >
                <span style={{ color: isSelected ? g.color : '#9CA3B8' }}>{g.icon}</span>
                {g.label}
                <ChevronRight size={12} className="ml-auto" style={{ color: isSelected ? g.color : '#C8CADE', transform: isSelected ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }} />
              </button>
            );
          })}
        </div>

        {/* Maker sub-row (expands when genre selected) */}
        {selectedGenre && (
          <div
            className="fade-in-up p-4 rounded-2xl"
            style={{ background: '#F7F8FD', border: '1px solid #E8EAF2' }}
          >
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-bold uppercase tracking-wider" style={{ color: '#9CA3B8' }}>
                {genres.find(g => g.id === selectedGenre)?.label} のメーカーを選択
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {makers[selectedGenre].map(m => (
                <button
                  key={m.id}
                  onClick={() => handleMakerClick(selectedGenre)}
                  className="px-3.5 py-2 rounded-xl text-sm font-semibold transition-all duration-150 press-effect"
                  style={{ background: '#FFFFFF', border: '1px solid #E8EAF2', color: '#0D0F1C', boxShadow: '0 1px 3px rgba(13,15,28,0.06)' }}
                  onMouseEnter={(e) => {
                    const g = genres.find(x => x.id === selectedGenre)!;
                    (e.currentTarget as HTMLElement).style.background = g.bg;
                    (e.currentTarget as HTMLElement).style.borderColor = g.border;
                    (e.currentTarget as HTMLElement).style.color = g.color;
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.background = '#FFFFFF';
                    (e.currentTarget as HTMLElement).style.borderColor = '#E8EAF2';
                    (e.currentTarget as HTMLElement).style.color = '#0D0F1C';
                  }}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
