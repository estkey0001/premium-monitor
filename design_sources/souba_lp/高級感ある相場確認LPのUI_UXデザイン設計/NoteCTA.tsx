// ============================================================
// SOUBA — Note CTA v6 (standalone, no tab dependency)
// ============================================================

import { ExternalLink, BookOpen, TrendingUp, Users, Star, CheckCircle2 } from 'lucide-react';

const benefits = [
  '各案件の詳細な仕入れ手順',
  'リスク管理・損切りの判断基準',
  '海外発送・関税の実務ガイド',
  '月収10万円達成ロードマップ',
];

export default function NoteCTA() {
  return (
    <section className="py-20" style={{ background: 'linear-gradient(160deg, #0D0F1C 0%, #131629 60%, #0F1A2E 100%)' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        <div className="relative overflow-hidden rounded-3xl p-8 sm:p-14"
          style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', backdropFilter: 'blur(20px)' }}>
          <div className="absolute top-0 right-0 w-96 h-96 rounded-full opacity-10" style={{ background: 'radial-gradient(circle, #00C896, transparent)', transform: 'translate(30%, -30%)' }} />
          <div className="absolute bottom-0 left-0 w-64 h-64 rounded-full opacity-10" style={{ background: 'radial-gradient(circle, #7C5CFC, transparent)', transform: 'translate(-30%, 30%)' }} />

          <div className="relative z-10 flex flex-col lg:flex-row items-center gap-12">
            <div className="flex-1 text-center lg:text-left">
              <div className="flex items-center justify-center lg:justify-start gap-1 mb-4">
                {[...Array(5)].map((_, i) => <Star key={i} size={16} fill="#F5A623" style={{ color: '#F5A623' }} />)}
                <span className="text-sm font-bold ml-2" style={{ color: 'rgba(255,255,255,0.7)' }}>4.9 / 5.0 (2,400件の評価)</span>
              </div>
              <h2 className="text-3xl sm:text-4xl font-black mb-4" style={{ color: '#FFFFFF', letterSpacing: '-0.04em', lineHeight: 1.1 }}>
                ダッシュボードだけじゃ
                <br />
                <span style={{ background: 'linear-gradient(135deg, #00C896, #3B7BFF)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
                  足りない人へ。
                </span>
              </h2>
              <p className="text-base leading-relaxed mb-6" style={{ color: 'rgba(255,255,255,0.55)', maxWidth: '480px' }}>
                価格差を見つけた後の「実際の動き方」を、note で毎週解説しています。
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-8">
                {benefits.map(b => (
                  <div key={b} className="flex items-center gap-2">
                    <CheckCircle2 size={14} style={{ color: '#00C896', flexShrink: 0 }} />
                    <span className="text-sm" style={{ color: 'rgba(255,255,255,0.7)' }}>{b}</span>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap justify-center lg:justify-start gap-6">
                {[
                  { icon: <Users size={14} />, value: '2,400+', label: '読者' },
                  { icon: <BookOpen size={14} />, value: '48本', label: '記事' },
                  { icon: <TrendingUp size={14} />, value: '¥18,000', label: '平均利益' },
                ].map(s => (
                  <div key={s.label} className="flex items-center gap-2">
                    <span style={{ color: '#00C896' }}>{s.icon}</span>
                    <div>
                      <div className="text-base font-black font-mono" style={{ color: '#FFFFFF', fontFamily: "'JetBrains Mono', monospace" }}>{s.value}</div>
                      <div className="text-xs" style={{ color: 'rgba(255,255,255,0.35)' }}>{s.label}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex-shrink-0 w-full lg:w-72">
              <div className="rounded-2xl p-6" style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)' }}>
                <div className="text-center mb-5">
                  <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: 'rgba(255,255,255,0.4)' }}>今すぐ読める</div>
                  <div className="text-3xl font-black" style={{ color: '#FFFFFF' }}>無料</div>
                  <div className="text-xs mt-1" style={{ color: 'rgba(255,255,255,0.35)' }}>登録不要・すぐ読める</div>
                </div>
                <a
                  href="https://note.com"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-2 w-full px-6 py-4 rounded-2xl text-base font-black btn-primary press-effect mb-3"
                >
                  <ExternalLink size={16} />
                  note を読む
                </a>
                <p className="text-center text-xs" style={{ color: 'rgba(255,255,255,0.3)' }}>
                  有料プランもあり（月額¥980〜）
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
