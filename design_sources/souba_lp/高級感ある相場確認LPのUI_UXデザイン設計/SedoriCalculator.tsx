// ============================================================
// SOUBA — Sedori Calculator (サイト間せどり計算)
// Design: Light Premium — Stripe × Apple
// 
// 機能:
// - 複数店舗の買取価格・販売価格を一覧表示
// - 「どこで買ってどこで売れば最大利益か」を自動計算
// - 最適ルートをハイライト表示
// - 手数料・送料を考慮した実質利益計算
// ============================================================

import { useState, useMemo } from 'react';
import { ArrowRight, Crown, TrendingUp, AlertCircle, Calculator, RefreshCw, ChevronDown, Info } from 'lucide-react';
import { formatPrice } from '@/lib/data';

interface StoreData {
  id: string;
  name: string;
  buyPrice: number;   // 買取価格（この店が買い取る価格）
  sellPrice: number;  // 販売価格（この店で売られている価格）
  url: string;
  fee: number;        // 手数料率 (%)
  shippingCost: number; // 送料目安
}

interface SedoriProduct {
  id: string;
  name: string;
  category: string;
  stores: StoreData[];
}

const sedoriProducts: SedoriProduct[] = [
  {
    id: 'iphone-16-pro-256',
    name: 'iPhone 16 Pro 256GB ナチュラルチタニウム',
    category: 'Apple',
    stores: [
      { id: 'geo', name: 'ゲオ', buyPrice: 186200, sellPrice: 195000, url: 'https://geo-online.co.jp', fee: 0, shippingCost: 0 },
      { id: 'bookoff', name: 'ブックオフ', buyPrice: 182000, sellPrice: 192000, url: 'https://bookoff.co.jp', fee: 0, shippingCost: 0 },
      { id: 'hardoff', name: 'ハードオフ', buyPrice: 178000, sellPrice: 188000, url: 'https://hardoff.co.jp', fee: 0, shippingCost: 0 },
      { id: 'iosys', name: 'イオシス', buyPrice: 175000, sellPrice: 185000, url: 'https://iosys.co.jp', fee: 0, shippingCost: 0 },
      { id: 'janpara', name: 'じゃんぱら', buyPrice: 172000, sellPrice: 183000, url: 'https://janpara.co.jp', fee: 0, shippingCost: 0 },
    ],
  },
  {
    id: 'iphone-16-128',
    name: 'iPhone 16 128GB ブラック',
    category: 'Apple',
    stores: [
      { id: 'geo', name: 'ゲオ', buyPrice: 143000, sellPrice: 152000, url: 'https://geo-online.co.jp', fee: 0, shippingCost: 0 },
      { id: 'bookoff', name: 'ブックオフ', buyPrice: 138000, sellPrice: 148000, url: 'https://bookoff.co.jp', fee: 0, shippingCost: 0 },
      { id: 'hardoff', name: 'ハードオフ', buyPrice: 135000, sellPrice: 145000, url: 'https://hardoff.co.jp', fee: 0, shippingCost: 0 },
      { id: 'iosys', name: 'イオシス', buyPrice: 132000, sellPrice: 142000, url: 'https://iosys.co.jp', fee: 0, shippingCost: 0 },
      { id: 'janpara', name: 'じゃんぱら', buyPrice: 130000, sellPrice: 140000, url: 'https://janpara.co.jp', fee: 0, shippingCost: 0 },
    ],
  },
  {
    id: 'macbook-air-m3',
    name: 'MacBook Air M3 13インチ 8GB/256GB',
    category: 'Apple',
    stores: [
      { id: 'geo', name: 'ゲオ', buyPrice: 185000, sellPrice: 198000, url: 'https://geo-online.co.jp', fee: 0, shippingCost: 0 },
      { id: 'bookoff', name: 'ブックオフ', buyPrice: 180000, sellPrice: 193000, url: 'https://bookoff.co.jp', fee: 0, shippingCost: 0 },
      { id: 'pckoubou', name: 'パソコン工房', buyPrice: 175000, sellPrice: 188000, url: 'https://pc-koubou.jp', fee: 0, shippingCost: 0 },
      { id: 'sofmap', name: 'ソフマップ', buyPrice: 172000, sellPrice: 185000, url: 'https://sofmap.com', fee: 0, shippingCost: 0 },
      { id: 'hardoff', name: 'ハードオフ', buyPrice: 168000, sellPrice: 182000, url: 'https://hardoff.co.jp', fee: 0, shippingCost: 0 },
    ],
  },
  {
    id: 'fuji-x100vi',
    name: 'FUJIFILM X100VI（中古・美品）',
    category: 'カメラ',
    stores: [
      { id: 'mapcamera', name: 'マップカメラ', buyPrice: 298000, sellPrice: 318000, url: 'https://mapcamera.com', fee: 0, shippingCost: 0 },
      { id: 'kitamura', name: 'キタムラ', buyPrice: 285000, sellPrice: 305000, url: 'https://kitamura.jp', fee: 0, shippingCost: 0 },
      { id: 'hardoff', name: 'ハードオフ', buyPrice: 265000, sellPrice: 285000, url: 'https://hardoff.co.jp', fee: 0, shippingCost: 0 },
      { id: 'secondstreet', name: '2nd STREET', buyPrice: 258000, sellPrice: 278000, url: 'https://2ndstreet.jp', fee: 0, shippingCost: 0 },
      { id: 'mercari', name: 'メルカリ（参考）', buyPrice: 0, sellPrice: 310000, url: 'https://mercari.com', fee: 10, shippingCost: 1500 },
    ],
  },
  {
    id: 'switch-oled',
    name: 'Nintendo Switch 有機ELモデル ホワイト',
    category: 'ゲーム機',
    stores: [
      { id: 'geo', name: 'ゲオ', buyPrice: 44000, sellPrice: 48000, url: 'https://geo-online.co.jp', fee: 0, shippingCost: 0 },
      { id: 'bookoff', name: 'ブックオフ', buyPrice: 42000, sellPrice: 46000, url: 'https://bookoff.co.jp', fee: 0, shippingCost: 0 },
      { id: 'hardoff', name: 'ハードオフ', buyPrice: 40000, sellPrice: 44500, url: 'https://hardoff.co.jp', fee: 0, shippingCost: 0 },
      { id: 'surugaya', name: 'ゲーム駿河屋', buyPrice: 38500, sellPrice: 43000, url: 'https://suruga-ya.jp', fee: 0, shippingCost: 0 },
      { id: 'mercari', name: 'メルカリ（参考）', buyPrice: 0, sellPrice: 47000, url: 'https://mercari.com', fee: 10, shippingCost: 800 },
    ],
  },
];

interface RouteResult {
  buyStore: StoreData;
  sellStore: StoreData;
  grossProfit: number;
  netProfit: number;
  fees: number;
  profitRate: number;
  isBest: boolean;
}

function calcRoutes(product: SedoriProduct, shippingCost: number): RouteResult[] {
  const results: RouteResult[] = [];
  const buyableStores = product.stores.filter(s => s.sellPrice > 0);
  const sellableStores = product.stores.filter(s => s.buyPrice > 0);

  for (const buyStore of buyableStores) {
    for (const sellStore of sellableStores) {
      if (buyStore.id === sellStore.id) continue;
      const buyAt = buyStore.sellPrice;
      const sellAt = sellStore.buyPrice;
      const grossProfit = sellAt - buyAt;
      const fees = Math.round(sellAt * (sellStore.fee / 100)) + shippingCost;
      const netProfit = grossProfit - fees;
      const profitRate = buyAt > 0 ? Math.round((netProfit / buyAt) * 1000) / 10 : 0;
      results.push({ buyStore, sellStore, grossProfit, netProfit, fees, profitRate, isBest: false });
    }
  }

  results.sort((a, b) => b.netProfit - a.netProfit);
  if (results.length > 0) results[0].isBest = true;
  return results;
}

export default function SedoriCalculator() {
  const [selectedProduct, setSelectedProduct] = useState(sedoriProducts[0].id);
  const [shippingCost, setShippingCost] = useState(0);
  const [showAll, setShowAll] = useState(false);

  const product = sedoriProducts.find(p => p.id === selectedProduct)!;
  const routes = useMemo(() => calcRoutes(product, shippingCost), [product, shippingCost]);
  const bestRoute = routes[0];
  const displayRoutes = showAll ? routes : routes.slice(0, 6);

  return (
    <section id="sedori" className="py-16" style={{ background: '#F8FAFC' }}>
      <div className="max-w-[1200px] mx-auto px-4 sm:px-6">
        {/* Section Header */}
        <div className="flex items-center gap-2 mb-2">
          <div className="w-1.5 h-5 rounded-full section-bar-blue" />
          <span className="text-xs font-semibold uppercase tracking-widest" style={{ color: '#2563EB' }}>
            Advanced Tool
          </span>
        </div>
        <h2 className="text-2xl font-bold mb-1" style={{ color: '#0F172A', fontFamily: 'Inter, system-ui', letterSpacing: '-0.02em' }}>
          サイト間せどり計算
        </h2>
        <p className="text-sm mb-8" style={{ color: '#64748B' }}>
          複数店舗の買取・販売価格を比較し、最大利益のルートを自動計算
        </p>

        {/* Controls */}
        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          {/* Product selector */}
          <div className="flex-1">
            <label className="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style={{ color: '#64748B' }}>
              商品を選択
            </label>
            <div className="relative">
              <select
                value={selectedProduct}
                onChange={(e) => { setSelectedProduct(e.target.value); setShowAll(false); }}
                className="w-full px-4 py-2.5 rounded-xl text-sm font-medium outline-none appearance-none pr-10"
                style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', color: '#0F172A', boxShadow: '0 1px 3px rgba(15,23,42,0.06)' }}
              >
                {sedoriProducts.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none" style={{ color: '#94A3B8' }} />
            </div>
          </div>

          {/* Shipping cost */}
          <div className="sm:w-48">
            <label className="block text-xs font-semibold mb-1.5 uppercase tracking-wider" style={{ color: '#64748B' }}>
              送料・手数料（円）
            </label>
            <input
              type="number"
              value={shippingCost}
              onChange={(e) => setShippingCost(Number(e.target.value))}
              placeholder="0"
              className="w-full px-4 py-2.5 rounded-xl text-sm font-medium outline-none"
              style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', color: '#0F172A', boxShadow: '0 1px 3px rgba(15,23,42,0.06)' }}
            />
          </div>
        </div>

        {/* Best Route Highlight */}
        {bestRoute && bestRoute.netProfit > 0 && (
          <div
            className="rounded-2xl p-5 mb-6 fade-in-up"
            style={{ background: 'linear-gradient(135deg, #F0FDF4, #ECFDF5)', border: '2px solid #86EFAC', boxShadow: '0 4px 20px rgba(5,150,105,0.12)' }}
          >
            <div className="flex items-center gap-2 mb-3">
              <Crown size={16} style={{ color: '#D97706' }} />
              <span className="text-sm font-bold" style={{ color: '#059669' }}>最大利益ルート</span>
              <span className="text-xs px-2 py-0.5 rounded-full font-semibold" style={{ background: '#DCFCE7', color: '#16A34A' }}>
                推奨
              </span>
            </div>
            <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3">
              {/* Buy */}
              <div className="flex-1 p-3 rounded-xl" style={{ background: '#FFFFFF', border: '1px solid #BBF7D0' }}>
                <div className="text-xs font-semibold mb-1 uppercase tracking-wider" style={{ color: '#94A3B8' }}>仕入れ先</div>
                <div className="text-base font-bold" style={{ color: '#0F172A' }}>{bestRoute.buyStore.name}</div>
                <div className="text-lg font-bold font-mono mt-1" style={{ color: '#DC2626', fontFamily: "'JetBrains Mono', monospace" }}>
                  {formatPrice(bestRoute.buyStore.sellPrice)}
                  <span className="text-xs font-normal ml-1" style={{ color: '#94A3B8' }}>で購入</span>
                </div>
              </div>

              <ArrowRight size={20} style={{ color: '#059669', flexShrink: 0 }} />

              {/* Sell */}
              <div className="flex-1 p-3 rounded-xl" style={{ background: '#FFFFFF', border: '1px solid #BBF7D0' }}>
                <div className="text-xs font-semibold mb-1 uppercase tracking-wider" style={{ color: '#94A3B8' }}>売却先</div>
                <div className="text-base font-bold" style={{ color: '#0F172A' }}>{bestRoute.sellStore.name}</div>
                <div className="text-lg font-bold font-mono mt-1" style={{ color: '#059669', fontFamily: "'JetBrains Mono', monospace" }}>
                  {formatPrice(bestRoute.sellStore.buyPrice)}
                  <span className="text-xs font-normal ml-1" style={{ color: '#94A3B8' }}>で売却</span>
                </div>
              </div>

              {/* Profit */}
              <div className="p-3 rounded-xl text-center sm:text-right" style={{ background: '#FFFFFF', border: '1px solid #BBF7D0', minWidth: '140px' }}>
                <div className="text-xs font-semibold mb-1 uppercase tracking-wider" style={{ color: '#94A3B8' }}>実質利益</div>
                <div className="text-3xl font-bold font-mono profit-glow" style={{ color: '#059669', fontFamily: "'JetBrains Mono', monospace" }}>
                  +{formatPrice(bestRoute.netProfit)}
                </div>
                <div className="text-sm font-semibold mt-0.5" style={{ color: '#16A34A' }}>
                  +{bestRoute.profitRate}%
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Store Price Table */}
        <div className="rounded-2xl overflow-hidden mb-6" style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', boxShadow: '0 1px 4px rgba(15,23,42,0.06)' }}>
          {/* Table header */}
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid #F1F5F9', background: '#F8FAFC' }}>
            <div className="flex items-center gap-2">
              <Calculator size={14} style={{ color: '#2563EB' }} />
              <span className="text-sm font-semibold" style={{ color: '#0F172A' }}>店舗別 買取・販売価格一覧</span>
              <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: '#EFF6FF', color: '#2563EB' }}>
                {product.category}
              </span>
            </div>
            <div className="flex items-center gap-1.5" style={{ color: '#94A3B8' }}>
              <Info size={12} />
              <span className="text-xs">買取価格 = この店が買い取る価格</span>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: '1px solid #F1F5F9' }}>
                  {['店舗名', '販売価格（購入可）', '買取価格（売却可）', '差額', ''].map((col) => (
                    <th key={col} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider" style={{ color: '#94A3B8' }}>
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {product.stores.map((store, index) => {
                  const spread = store.buyPrice > 0 && store.sellPrice > 0 ? store.buyPrice - store.sellPrice : null;
                  const isHighBuy = store.buyPrice === Math.max(...product.stores.map(s => s.buyPrice));
                  const isLowSell = store.sellPrice > 0 && store.sellPrice === Math.min(...product.stores.filter(s => s.sellPrice > 0).map(s => s.sellPrice));

                  return (
                    <tr
                      key={store.id}
                      className="table-row-hover transition-colors duration-100"
                      style={{ borderBottom: index < product.stores.length - 1 ? '1px solid #F1F5F9' : 'none' }}
                    >
                      {/* Store name */}
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-2">
                          {isHighBuy && (
                            <span className="text-xs px-1.5 py-0.5 rounded font-bold" style={{ background: '#F0FDF4', color: '#059669', fontSize: '9px' }}>
                              買取最高値
                            </span>
                          )}
                          {isLowSell && (
                            <span className="text-xs px-1.5 py-0.5 rounded font-bold" style={{ background: '#EFF6FF', color: '#2563EB', fontSize: '9px' }}>
                              最安仕入れ
                            </span>
                          )}
                          <span className="text-sm font-semibold" style={{ color: '#0F172A' }}>{store.name}</span>
                          {store.fee > 0 && (
                            <span className="text-xs" style={{ color: '#94A3B8' }}>手数料{store.fee}%</span>
                          )}
                        </div>
                      </td>

                      {/* Sell price (purchase) */}
                      <td className="px-4 py-3.5">
                        {store.sellPrice > 0 ? (
                          <div>
                            <span className="text-sm font-bold font-mono" style={{ color: isLowSell ? '#2563EB' : '#0F172A', fontFamily: "'JetBrains Mono', monospace" }}>
                              {formatPrice(store.sellPrice)}
                            </span>
                            {isLowSell && <div className="text-xs mt-0.5" style={{ color: '#2563EB' }}>← ここで買う</div>}
                          </div>
                        ) : (
                          <span className="text-xs" style={{ color: '#CBD5E1' }}>取扱なし</span>
                        )}
                      </td>

                      {/* Buy price (sell to) */}
                      <td className="px-4 py-3.5">
                        {store.buyPrice > 0 ? (
                          <div>
                            <span className="text-sm font-bold font-mono" style={{ color: isHighBuy ? '#059669' : '#0F172A', fontFamily: "'JetBrains Mono', monospace" }}>
                              {formatPrice(store.buyPrice)}
                            </span>
                            {isHighBuy && <div className="text-xs mt-0.5" style={{ color: '#059669' }}>← ここで売る</div>}
                          </div>
                        ) : (
                          <span className="text-xs" style={{ color: '#CBD5E1' }}>買取不可</span>
                        )}
                      </td>

                      {/* Spread */}
                      <td className="px-4 py-3.5">
                        {spread !== null ? (
                          <span className="text-sm font-mono" style={{ color: spread > 0 ? '#059669' : '#DC2626', fontFamily: "'JetBrains Mono', monospace" }}>
                            {spread > 0 ? '+' : ''}{formatPrice(spread)}
                          </span>
                        ) : (
                          <span className="text-xs" style={{ color: '#CBD5E1' }}>—</span>
                        )}
                      </td>

                      {/* Link */}
                      <td className="px-4 py-3.5">
                        <a href={store.url} target="_blank" rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all duration-150 press-effect"
                          style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', color: '#64748B' }}
                        >
                          確認
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* All Routes Table */}
        <div className="rounded-2xl overflow-hidden" style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', boxShadow: '0 1px 4px rgba(15,23,42,0.06)' }}>
          <div className="px-5 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid #F1F5F9', background: '#F8FAFC' }}>
            <div className="flex items-center gap-2">
              <TrendingUp size={14} style={{ color: '#059669' }} />
              <span className="text-sm font-semibold" style={{ color: '#0F172A' }}>全ルート利益計算</span>
            </div>
            <span className="text-xs" style={{ color: '#94A3B8' }}>{routes.length}通りのルート</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: '1px solid #F1F5F9' }}>
                  {['#', '仕入れ先（購入）', '売却先（買取）', '仕入れ価格', '売却価格', '粗利', '手数料等', '実質利益', '利益率'].map((col) => (
                    <th key={col} className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider whitespace-nowrap" style={{ color: '#94A3B8' }}>
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displayRoutes.map((route, index) => (
                  <tr
                    key={`${route.buyStore.id}-${route.sellStore.id}`}
                    className="transition-colors duration-100"
                    style={{
                      borderBottom: index < displayRoutes.length - 1 ? '1px solid #F1F5F9' : 'none',
                      background: route.isBest ? '#F0FDF4' : 'transparent',
                    }}
                    onMouseEnter={(e) => { if (!route.isBest) (e.currentTarget as HTMLElement).style.background = '#F8FAFC'; }}
                    onMouseLeave={(e) => { if (!route.isBest) (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                  >
                    {/* Rank */}
                    <td className="px-3 py-3">
                      {route.isBest ? (
                        <Crown size={14} style={{ color: '#D97706' }} />
                      ) : (
                        <span className="text-xs font-mono" style={{ color: '#CBD5E1', fontFamily: "'JetBrains Mono', monospace" }}>
                          {index + 1}
                        </span>
                      )}
                    </td>

                    {/* Buy store */}
                    <td className="px-3 py-3">
                      <span className="text-sm font-medium" style={{ color: '#0F172A' }}>{route.buyStore.name}</span>
                    </td>

                    {/* Sell store */}
                    <td className="px-3 py-3">
                      <span className="text-sm font-medium" style={{ color: '#0F172A' }}>{route.sellStore.name}</span>
                    </td>

                    {/* Buy price */}
                    <td className="px-3 py-3">
                      <span className="text-sm font-mono" style={{ color: '#DC2626', fontFamily: "'JetBrains Mono', monospace" }}>
                        {formatPrice(route.buyStore.sellPrice)}
                      </span>
                    </td>

                    {/* Sell price */}
                    <td className="px-3 py-3">
                      <span className="text-sm font-mono" style={{ color: '#059669', fontFamily: "'JetBrains Mono', monospace" }}>
                        {formatPrice(route.sellStore.buyPrice)}
                      </span>
                    </td>

                    {/* Gross profit */}
                    <td className="px-3 py-3">
                      <span className="text-sm font-mono" style={{ color: route.grossProfit >= 0 ? '#0F172A' : '#DC2626', fontFamily: "'JetBrains Mono', monospace" }}>
                        {route.grossProfit >= 0 ? '+' : ''}{formatPrice(route.grossProfit)}
                      </span>
                    </td>

                    {/* Fees */}
                    <td className="px-3 py-3">
                      <span className="text-sm font-mono" style={{ color: '#94A3B8', fontFamily: "'JetBrains Mono', monospace" }}>
                        {route.fees > 0 ? `-${formatPrice(route.fees)}` : '—'}
                      </span>
                    </td>

                    {/* Net profit */}
                    <td className="px-3 py-3">
                      <span
                        className="text-sm font-bold font-mono"
                        style={{
                          color: route.netProfit > 0 ? '#059669' : '#DC2626',
                          fontFamily: "'JetBrains Mono', monospace",
                          ...(route.isBest ? { textShadow: '0 0 12px rgba(5,150,105,0.3)' } : {}),
                        }}
                      >
                        {route.netProfit >= 0 ? '+' : ''}{formatPrice(route.netProfit)}
                      </span>
                    </td>

                    {/* Profit rate */}
                    <td className="px-3 py-3">
                      <span
                        className="text-xs px-2 py-0.5 rounded-full font-semibold"
                        style={{
                          background: route.netProfit > 0 ? '#F0FDF4' : '#FEF2F2',
                          color: route.netProfit > 0 ? '#059669' : '#DC2626',
                        }}
                      >
                        {route.netProfit >= 0 ? '+' : ''}{route.profitRate}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Show more */}
          {routes.length > 6 && (
            <div className="px-5 py-3 flex items-center justify-between" style={{ borderTop: '1px solid #F1F5F9' }}>
              <button
                onClick={() => setShowAll(!showAll)}
                className="flex items-center gap-1.5 text-sm font-medium transition-colors press-effect"
                style={{ color: '#2563EB' }}
              >
                <RefreshCw size={12} />
                {showAll ? '折りたたむ' : `残り${routes.length - 6}ルートを表示`}
              </button>
              <p className="text-xs" style={{ color: '#94A3B8' }}>
                ※ 価格は参考値です。実際の査定額は店舗・状態により異なります。
              </p>
            </div>
          )}
        </div>

        {/* Disclaimer */}
        <div className="mt-4 flex items-start gap-2 px-4 py-3 rounded-xl" style={{ background: '#FFFBEB', border: '1px solid #FDE68A' }}>
          <AlertCircle size={14} className="flex-shrink-0 mt-0.5" style={{ color: '#D97706' }} />
          <p className="text-xs leading-relaxed" style={{ color: '#92400E' }}>
            掲載価格は参考値です。実際の買取査定額は商品の状態・付属品の有無・店舗の在庫状況により大幅に異なる場合があります。
            必ず各店舗の最新情報を確認してから取引を行ってください。
          </p>
        </div>
      </div>
    </section>
  );
}
