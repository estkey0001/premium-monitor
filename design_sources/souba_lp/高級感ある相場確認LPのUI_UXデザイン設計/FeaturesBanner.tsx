// ============================================================
// SOUBA — Features Banner (Compact)
// 6枚カードをコンパクトな横スクロールチップ列に変更
// ============================================================

import { TrendingUp, Globe, Calculator, BarChart2, Bell, Zap } from 'lucide-react';

const features = [
  { icon: <TrendingUp size={14} />, label: '毎日12:00 自動更新', color: '#00C896', bg: '#F0FDF8' },
  { icon: <Calculator size={14} />, label: 'サイト間せどり計算', color: '#3B7BFF', bg: '#EEF4FF' },
  { icon: <Globe size={14} />, label: '海外相場リンク付き', color: '#7C5CFC', bg: '#F0EEFF' },
  { icon: <BarChart2 size={14} />, label: 'プロフィットスコア', color: '#FF9500', bg: '#FFF8E8' },
  { icon: <Bell size={14} />, label: 'ウォッチリスト', color: '#FF3B5C', bg: '#FFF1F3' },
  { icon: <Zap size={14} />, label: '急騰/急落アラート', color: '#FF9500', bg: '#FFF8E8' },
];

export default function FeaturesBanner() {
  return (
    <div
      className="py-3 overflow-hidden"
      style={{ background: '#FFFFFF', borderBottom: '1px solid #E8EAF2' }}
    >
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="flex items-center gap-2 overflow-x-auto tab-scroll">
          <span className="text-xs font-bold uppercase tracking-wider flex-shrink-0 pr-2" style={{ color: '#C8CADE', borderRight: '1px solid #E8EAF2' }}>
            機能
          </span>
          {features.map(f => (
            <div
              key={f.label}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full flex-shrink-0"
              style={{ background: f.bg, border: `1px solid ${f.color}30` }}
            >
              <span style={{ color: f.color }}>{f.icon}</span>
              <span className="text-xs font-semibold whitespace-nowrap" style={{ color: f.color }}>{f.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
