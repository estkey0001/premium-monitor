// ============================================================
// SOUBA — Home Page v6
// Fix: Hero buttons, all CTAs, tab navigation, genre drill-down
// ============================================================

import { useState, useRef, useCallback } from 'react';
import SiteHeader from '@/components/SiteHeader';
import HeroSection from '@/components/HeroSection';
import LiveTicker from '@/components/LiveTicker';
import FeaturesBanner from '@/components/FeaturesBanner';
import StickyTabs, { type TabId } from '@/components/StickyTabs';
import BeginnerSection from '@/components/BeginnerSection';
import BuybackTable from '@/components/BuybackTable';
import AdvancedSection from '@/components/AdvancedSection';
import OverseasLinks from '@/components/OverseasLinks';
import RankingSection from '@/components/RankingSection';
import NewProductsSection from '@/components/NewProductsSection';
import SurgeSection from '@/components/SurgeSection';
import SiteFooter from '@/components/SiteFooter';
import NoteCTA from '@/components/NoteCTA';
import SedoriCalculator from '@/components/SedoriCalculator';
import GenreSection, { type GenreId } from '@/components/GenreSection';
import LotterySection from '@/components/LotterySection';
import GenreDrillDown from '@/components/GenreDrillDown';

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabId>('ranking');
  const contentRef = useRef<HTMLDivElement>(null);

  const scrollToContent = useCallback(() => {
    setTimeout(() => {
      if (contentRef.current) {
        const offset = 110;
        const top = contentRef.current.getBoundingClientRect().top + window.scrollY - offset;
        window.scrollTo({ top, behavior: 'smooth' });
      }
    }, 80);
  }, []);

  const handleTabChange = useCallback((tab: TabId) => {
    setActiveTab(tab);
    scrollToContent();
  }, [scrollToContent]);

  // Genre tabs that show the drill-down UI
  const isGenreTab = ['smartphone', 'tablet', 'pc', 'camera', 'game'].includes(activeTab);

  return (
    <div
      className="min-h-screen"
      style={{ background: '#FAFBFF', fontFamily: 'Inter, system-ui, -apple-system, sans-serif' }}
    >
      <SiteHeader onTabChange={handleTabChange} />
      <HeroSection onTabChange={handleTabChange} />
      <LiveTicker />
      <FeaturesBanner />
      <StickyTabs activeTab={activeTab} onTabChange={handleTabChange} />

      {/* Tab Content */}
      <div ref={contentRef}>
        {activeTab === 'ranking'    && <RankingSection />}
        {activeTab === 'sedori'     && <SedoriCalculator />}
        {activeTab === 'beginner'   && <><BeginnerSection /><BuybackTable /></>}
        {activeTab === 'advanced'   && <><AdvancedSection /><OverseasLinks /></>}
        {activeTab === 'surge'      && <SurgeSection />}
        {activeTab === 'lottery'    && <LotterySection />}
        {isGenreTab && (
          <GenreSection genre={activeTab as GenreId} />
        )}
      </div>

      {/* Genre drill-down always visible below tabs */}
      <GenreDrillDown onTabChange={handleTabChange} />

      {/* Always-visible sections */}
      <div style={{ borderTop: '1px solid #E8EAF2' }} />
      <LotterySection />
      <SedoriCalculator />
      <RankingSection />
      <OverseasLinks />
      <NewProductsSection />
      <NoteCTA />
      <SiteFooter onTabChange={handleTabChange} />
    </div>
  );
}
