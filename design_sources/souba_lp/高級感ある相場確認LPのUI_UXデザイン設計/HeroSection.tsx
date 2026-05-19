// ============================================================
// SOUBA — Hero Section v6
// Fix: All buttons now trigger tab changes via onTabChange prop
// ============================================================

import { TrendingUp, Users, Award, Clock, Shield, Zap, Star } from 'lucide-react';
import { heroStats, formatPrice } from '@/lib/data';
import type { TabId } from './StickyTabs';

const HERO_BG = 'https://d2xsxph8kpxj0f.cloudfront.net/310419663030377484/PizjkmtuJMCiHjAwN7LHkR/hero-premium-EsPEQZvUgdo3RRV6EnioqH.webp';

const socialProof = [
  { icon: <Users size={14} />, value: '12,400+', label: '月間利用者' },
  { icon: <TrendingUp size={14} />, value: '¥2.1億+', label: '累計確認利益' },
  { icon: <Star size={14} />, value: '4.9/5.0', label: 'ユーザー評価' },
];

const liveItems = [
  { name: 'iPhone 16 Pro 256GB', profit: '+¥26,400', rate: '+16.5%' },
  { name: 'AirPods Pro 2', profit: '+¥8,700', rate: '+21.9%' },
  { name: 'FUJIFILM X100VI', profit: '+¥131,000', rate: '+78.4%' },
  { name: 'MacBook Air M3', profit: '+¥20,200', rate: '+12.3%' },
  { name: 'Switch 2 ゼルダ限定', profit: '+¥38,000', rate: '+63.3%' },
];

interface HeroSectionProps {
  onTabChange: (tab: TabId) => void;
}

export default function HeroSection({ onTabChange }: HeroSectionProps) {
  return (
    <section
      className="relative overflow-hidden"
      style={{ background: 'linear-gradient(160deg, #0D0F1C 0%, #131629 50%, #0F1A2E 100%)', minHeight: '92vh', display: 'flex', alignItems: 'center' }}
    >
      <div className="absolute inset-0" style={{ backgroundImage: `url(${HERO_BG})`, backgroundSize: 'cover', backgroundPosition: 'center', opacity: 0.18 }} />
      <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse 80% 60% at 50% 0%, rgba(0,200,150,0.08) 0%, transparent 70%)' }} />
      <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse 60% 50% at 80% 50%, rgba(124,92,252,0.06) 0%, transparent 70%)' }} />
      <div className="absolute bottom-0 left-0 right-0 h-32" style={{ background: 'linear-gradient(to bottom, transparent, #FAFBFF)' }} />

      <div className="relative z-10 max-w-[1200px] mx-auto px-4 sm:px-6 w-full py-20">
        <div className="grid lg:grid-cols-[1fr_480px] gap-16 items-center">

          {/* Left */}
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full mb-6 fade-in-up"
              style={{ background: 'rgba(0,200,150,0.12)', border: '1px solid rgba(0,200,150,0.3)' }}>
              <div className="w-2 h-2 rounded-full live-pulse" style={{ background: '#00C896' }} />
              <span className="text-xs font-bold uppercase tracking-widest" style={{ color: '#00C896' }}>毎日12:00 更新中</span>
              <span className="text-xs" style={{ color: 'rgba(255,255,255,0.4)' }}>{heroStats.updatedAt}</span>
            </div>

            <h1 className="fade-in-up delay-100" style={{
              fontFamily: 'Inter, system-ui',
              fontSize: 'clamp(2.4rem, 5.5vw, 4rem)',
              fontWeight: 900,
              lineHeight: 1.05,
              letterSpacing: '-0.04em',
              color: '#FFFFFF',
              marginBottom: '1.5rem',
            }}>
              転売で稼ぐための
              <br />
              <span style={{
                background: 'linear-gradient(135deg, #00C896 0%, #3B7BFF 60%, #7C5CFC 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
              }}>
                相場情報、全部ここに。
              </span>
            </h1>

            <p className="fade-in-up delay-200 text-lg leading-relaxed mb-8" style={{ color: 'rgba(255,255,255,0.65)', maxWidth: '520px' }}>
              スマホ・カメラ・ゲーム機の<strong style={{ color: 'rgba(255,255,255,0.9)' }}>定価・買取・海外相場</strong>を毎日整理。
              初心者の低難度案件から、上級者のサイト間せどりまで。
            </p>

            {/* CTAs — all use onTabChange */}
            <div className="flex flex-wrap gap-3 mb-8 fade-in-up delay-300">
              <button
                onClick={() => onTabChange('ranking')}
                className="inline-flex items-center gap-2 px-6 py-3.5 rounded-2xl text-base font-bold btn-primary press-effect"
              >
                今日の案件を見る →
              </button>
              <button
                onClick={() => onTabChange('sedori')}
                className="inline-flex items-center gap-2 px-6 py-3.5 rounded-2xl text-base font-bold press-effect"
                style={{ background: 'rgba(124,92,252,0.15)', border: '1px solid rgba(124,92,252,0.4)', color: '#A78BFA' }}
              >
                <Zap size={15} />
                せどり計算を試す
              </button>
              <button
                onClick={() => onTabChange('lottery')}
                className="inline-flex items-center gap-2 px-6 py-3.5 rounded-2xl text-base font-bold press-effect"
                style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.15)', color: 'rgba(255,255,255,0.7)' }}
              >
                抽選情報を見る
              </button>
            </div>

            {/* Social proof */}
            <div className="flex flex-wrap gap-5 fade-in-up delay-400">
              {socialProof.map(item => (
                <div key={item.label} className="flex items-center gap-2">
                  <div style={{ color: '#00C896' }}>{item.icon}</div>
                  <div>
                    <div className="text-base font-black" style={{ color: '#FFFFFF', fontFamily: "'JetBrains Mono', monospace", letterSpacing: '-0.02em' }}>{item.value}</div>
                    <div className="text-xs" style={{ color: 'rgba(255,255,255,0.4)' }}>{item.label}</div>
                  </div>
                </div>
              ))}
            </div>

            {/* Trust badges */}
            <div className="flex flex-wrap items-center gap-3 mt-6 fade-in-up delay-500">
              {[
                { icon: <Shield size={11} />, label: '参考価格のみ・安全' },
                { icon: <Clock size={11} />, label: '毎日正午更新' },
                { icon: <Users size={11} />, label: '8店舗以上比較' },
              ].map(item => (
                <div key={item.label} className="flex items-center gap-1.5 px-2.5 py-1 rounded-full"
                  style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)' }}>
                  <span style={{ color: 'rgba(255,255,255,0.4)' }}>{item.icon}</span>
                  <span className="text-xs" style={{ color: 'rgba(255,255,255,0.5)' }}>{item.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Right: Live panel */}
          <div className="fade-in-up delay-300">
            <div className="relative">
              <div className="absolute -inset-4 rounded-3xl opacity-30" style={{ background: 'radial-gradient(ellipse, rgba(0,200,150,0.4), transparent 70%)', filter: 'blur(20px)' }} />
              <div className="relative rounded-2xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', backdropFilter: 'blur(20px)' }}>
                <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full live-pulse" style={{ background: '#00C896' }} />
                    <span className="text-xs font-bold uppercase tracking-wider" style={{ color: '#00C896' }}>今日の利益レポート</span>
                  </div>
                  <span className="text-xs" style={{ color: 'rgba(255,255,255,0.3)' }}>{heroStats.updatedAt}</span>
                </div>
                <div className="p-4 space-y-2">
                  {liveItems.map((item, i) => (
                    <button
                      key={item.name}
                      onClick={() => onTabChange(i < 2 ? 'beginner' : i === 2 ? 'camera' : i === 3 ? 'pc' : 'lottery')}
                      className="w-full flex items-center justify-between px-4 py-3 rounded-xl press-effect transition-all fade-in-up text-left"
                      style={{
                        animationDelay: `${400 + i * 80}ms`,
                        background: i === 0 ? 'rgba(0,200,150,0.08)' : 'rgba(255,255,255,0.03)',
                        border: `1px solid ${i === 0 ? 'rgba(0,200,150,0.2)' : 'rgba(255,255,255,0.06)'}`,
                        cursor: 'pointer',
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = i === 0 ? 'rgba(0,200,150,0.14)' : 'rgba(255,255,255,0.07)'; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = i === 0 ? 'rgba(0,200,150,0.08)' : 'rgba(255,255,255,0.03)'; }}
                    >
                      <span className="text-sm font-medium" style={{ color: i === 0 ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.6)' }}>{item.name}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-black font-mono" style={{ color: '#00C896', fontFamily: "'JetBrains Mono', monospace" }}>{item.profit}</span>
                        <span className="text-xs px-2 py-0.5 rounded-full font-bold" style={{ background: 'rgba(0,200,150,0.15)', color: '#00C896' }}>{item.rate}</span>
                      </div>
                    </button>
                  ))}
                </div>
                <div className="grid grid-cols-3 gap-px" style={{ borderTop: '1px solid rgba(255,255,255,0.08)', background: 'rgba(255,255,255,0.04)' }}>
                  {[
                    { label: '最大利益', value: formatPrice(heroStats.maxProfit), color: '#00C896', tab: 'camera' as TabId },
                    { label: '初心者向け', value: `${heroStats.beginnerCount}件`, color: '#FFFFFF', tab: 'beginner' as TabId },
                    { label: '上級者向け', value: `${heroStats.advancedCount}件`, color: '#A78BFA', tab: 'advanced' as TabId },
                  ].map(stat => (
                    <button key={stat.label} onClick={() => onTabChange(stat.tab)}
                      className="px-4 py-3 text-center press-effect transition-all"
                      style={{ background: 'rgba(13,15,28,0.3)', cursor: 'pointer' }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.06)'; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'rgba(13,15,28,0.3)'; }}
                    >
                      <div className="text-xs mb-1" style={{ color: 'rgba(255,255,255,0.35)' }}>{stat.label}</div>
                      <div className="text-base font-black font-mono" style={{ color: stat.color, fontFamily: "'JetBrains Mono', monospace" }}>{stat.value}</div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
