// ============================================================
// SOUBA — Live Ticker Bar
// Scrolling price updates, creates urgency
// ============================================================

import { TrendingUp, TrendingDown } from 'lucide-react';

const tickerItems = [
  { name: 'iPhone 16 Pro 256GB', profit: '+¥26,400', up: true },
  { name: 'AirPods Pro 2', profit: '+¥8,700', up: true },
  { name: 'FUJIFILM X100VI', profit: '+¥131,000', up: true },
  { name: 'MacBook Air M3', profit: '+¥20,200', up: true },
  { name: 'Switch 2 ゼルダ限定', profit: '+¥38,000', up: true },
  { name: 'RICOH GR IIIx', profit: '+¥45,100', up: true },
  { name: 'iPad Air M2 11"', profit: '+¥13,200', up: true },
  { name: 'iPhone 15 Pro Max', profit: '-¥8,000', up: false },
  { name: 'MacBook Pro M4', profit: '+¥23,200', up: true },
  { name: 'PS5 本体', profit: '+¥4,500', up: true },
];

export default function LiveTicker() {
  const doubled = [...tickerItems, ...tickerItems]; // seamless loop

  return (
    <div
      className="overflow-hidden py-2.5"
      style={{ background: '#0D0F1C', borderTop: '1px solid rgba(255,255,255,0.06)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}
    >
      <div className="flex items-center gap-0">
        {/* Label */}
        <div className="flex-shrink-0 flex items-center gap-2 px-4 py-1 mr-4 z-10" style={{ background: '#0D0F1C' }}>
          <div className="w-1.5 h-1.5 rounded-full live-pulse" style={{ background: '#00C896' }} />
          <span className="text-xs font-black uppercase tracking-widest" style={{ color: '#00C896' }}>LIVE</span>
        </div>

        {/* Scrolling items */}
        <div className="flex-1 overflow-hidden">
          <div className="ticker-track flex items-center gap-6 w-max">
            {doubled.map((item, i) => (
              <div key={i} className="flex items-center gap-2 flex-shrink-0">
                <span className="text-xs font-medium" style={{ color: 'rgba(255,255,255,0.5)' }}>{item.name}</span>
                <div className="flex items-center gap-1">
                  {item.up
                    ? <TrendingUp size={10} style={{ color: '#00C896' }} />
                    : <TrendingDown size={10} style={{ color: '#FF3B5C' }} />
                  }
                  <span className="text-xs font-black font-mono" style={{ color: item.up ? '#00C896' : '#FF3B5C', fontFamily: "'JetBrains Mono', monospace" }}>
                    {item.profit}
                  </span>
                </div>
                <span style={{ color: 'rgba(255,255,255,0.1)', fontSize: 16 }}>·</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
