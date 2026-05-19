// ============================================================
// SOUBA — Overseas Market Links (Light Mode)
// ============================================================

import { ExternalLink, Globe } from 'lucide-react';
import { overseasLinks } from '@/lib/data';

const colorMap = {
  blue: { bg: '#EFF6FF', border: '#BFDBFE', color: '#2563EB', hoverBg: '#DBEAFE' },
  green: { bg: '#F0FDF4', border: '#BBF7D0', color: '#059669', hoverBg: '#DCFCE7' },
  purple: { bg: '#F5F3FF', border: '#DDD6FE', color: '#7C3AED', hoverBg: '#EDE9FE' },
};

export default function OverseasLinks() {
  return (
    <section className="py-12" style={{ background: '#F8FAFC' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="rounded-2xl p-6 sm:p-8" style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', boxShadow: '0 1px 4px rgba(15,23,42,0.06)' }}>
          <div className="flex items-center gap-3 mb-6">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: '#EFF6FF' }}>
              <Globe size={16} style={{ color: '#2563EB' }} />
            </div>
            <div>
              <h3 className="text-base font-bold" style={{ color: '#0F172A' }}>海外相場リンク</h3>
              <p className="text-xs" style={{ color: '#94A3B8' }}>海外市場の最新価格を直接確認</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            {overseasLinks.map((link) => {
              const colors = colorMap[link.color];
              return (
                <a
                  key={link.name}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all duration-150 press-effect"
                  style={{ background: colors.bg, border: `1px solid ${colors.border}`, color: colors.color, textDecoration: 'none' }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLElement).style.background = colors.hoverBg;
                    (e.currentTarget as HTMLElement).style.transform = 'translateY(-1px)';
                    (e.currentTarget as HTMLElement).style.boxShadow = '0 4px 12px rgba(15,23,42,0.08)';
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLElement).style.background = colors.bg;
                    (e.currentTarget as HTMLElement).style.transform = 'translateY(0)';
                    (e.currentTarget as HTMLElement).style.boxShadow = 'none';
                  }}
                >
                  {link.name}
                  <ExternalLink size={11} className="opacity-60" />
                </a>
              );
            })}
          </div>
          <p className="text-xs mt-4" style={{ color: '#CBD5E1' }}>
            ※ 海外サイトは英語表記です。為替レートは別途確認してください。
          </p>
        </div>
      </div>
    </section>
  );
}
