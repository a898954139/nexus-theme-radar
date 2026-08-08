import React, { useEffect, useMemo, useState } from 'react';
import { EmptyState } from './components/common/EmptyState';
import { NavTabBar } from './components/common/NavTabBar';
import { StatusBar } from './components/common/StatusBar';
import { WavePhysicsLoader } from './components/common/WavePhysicsLoader';
import { InstitutionalFlows } from './components/flows/InstitutionalFlows';
import { ThemeRadarHome } from './components/home/ThemeRadarHome';
import { ThemeMomentum } from './components/momentum/ThemeMomentum';
import { SourceStatus } from './components/sources/SourceStatus';
import { StockDetail } from './components/stock/StockDetail';
import { loadRadarData, fetchInstitutionalFlows, fetchStockFundamentals } from './services/dataService';
import { DeviceType, PageType, RadarData, StockTab } from './types';

interface RouteState {
  page: PageType;
  code: string;
  exchange?: string;
  tab: StockTab;
}

function readRoute(): RouteState {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const page = (params.get('page') as PageType | null) ?? 'index';
  return {
    page: ['index', 'momentum', 'flows', 'stock', 'sources'].includes(page) ? page : 'index',
    code: params.get('code') ?? '',
    exchange: params.get('exchange') ?? undefined,
    tab: params.get('tab') === 'flows' ? 'flows' : 'fundamentals'
  };
}

function instrumentForCode(data: RadarData | null, code: string, exchange?: string) {
  if (!data) return undefined;
  const all = data.themeRanking.themes.flatMap((theme) => [
    ...theme.direct_mentions,
    ...theme.supply_chain_candidates
  ]);
  const fromRanking = all.find((item) => item.symbol === code && (!exchange || item.exchange === exchange));
  if (fromRanking) return fromRanking;
  const fromMomentum = data.momentumLatest.themes.flatMap((theme) => [
    ...theme.direct_symbols,
    ...theme.related_symbols
  ]).find((item) => item.symbol === code && (!exchange || item.exchange === exchange));
  return fromMomentum;
}

export const App: React.FC = () => {
  const [route, setRoute] = useState<RouteState>(readRoute);
  const [device, setDevice] = useState<DeviceType>(() => window.innerWidth < 720 ? 'mobile' : 'desktop');
  const [radarData, setRadarData] = useState<RadarData | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [stockData, setStockData] = useState<{
    fundamentals: Awaited<ReturnType<typeof fetchStockFundamentals>>;
    flows: Awaited<ReturnType<typeof fetchInstitutionalFlows>>;
  }>({ fundamentals: null, flows: [] });
  const defaultInstrument = useMemo(
    () => radarData?.themeRanking.themes.flatMap((theme) => theme.direct_mentions)[0],
    [radarData]
  );
  const stockCode = route.code || defaultInstrument?.symbol || '';
  const stockExchange = route.exchange || defaultInstrument?.exchange;

  useEffect(() => {
    const updateDevice = () => setDevice(window.innerWidth < 720 ? 'mobile' : 'desktop');
    window.addEventListener('resize', updateDevice);
    return () => window.removeEventListener('resize', updateDevice);
  }, []);

  useEffect(() => {
    const onHashChange = () => setRoute(readRoute());
    window.addEventListener('hashchange', onHashChange);
    onHashChange();
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  useEffect(() => {
    let active = true;
    loadRadarData()
      .then((data) => {
        if (active) setRadarData(data);
      })
      .catch(() => {
        if (active) setLoadError(true);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (route.page !== 'stock') return;
    let active = true;
    Promise.all([
      fetchStockFundamentals(stockCode, stockExchange),
      fetchInstitutionalFlows(stockCode, stockExchange)
    ]).then(([fundamentals, flows]) => {
      if (active) setStockData({ fundamentals, flows });
    });
    return () => {
      active = false;
    };
  }, [route.page, stockCode, stockExchange]);

  const updateHash = (page: PageType, code?: string, exchange?: string, tab?: StockTab) => {
    const params = new URLSearchParams({ page });
    if (code) params.set('code', code);
    if (exchange) params.set('exchange', exchange);
    if (tab) params.set('tab', tab);
    window.location.hash = params.toString();
  };

  const stockInstrument = useMemo(
    () => instrumentForCode(radarData, stockCode, stockExchange) ?? defaultInstrument,
    [defaultInstrument, radarData, stockCode, stockExchange]
  );

  const goStock = (code: string, exchange?: string, tab: StockTab = 'fundamentals') => {
    updateHash('stock', code, exchange, tab);
  };

  const showLoader = !radarData && !loadError;
  const showEmpty = loadError || radarData?.themeRanking.themes.length === 0;

  return (
    <div className={`app-root ${device === 'mobile' ? 'is-mobile' : 'is-desktop'}`}>
      <main className="app-frame">
        <NavTabBar
          page={route.page}
          setPage={(page) => page === 'stock'
            ? updateHash(page, defaultInstrument?.symbol, defaultInstrument?.exchange)
            : updateHash(page)}
          device={device}
          mobileTitle={route.page === 'stock' ? `${stockCode}${stockInstrument?.name_zh ? ` ${stockInstrument.name_zh}` : ''}` : undefined}
        />
        <StatusBar
          device={device}
          generatedAt={radarData?.themeRanking.generated_at}
          sourceStatusOk={radarData ? radarData.sourceStatus.failed_count === 0 : true}
          onGoSources={() => updateHash('sources')}
        />

        {showLoader ? <WavePhysicsLoader scale={device === 'mobile' ? 0.72 : 1} /> : null}
        {showEmpty && !showLoader ? <EmptyState page={route.page} /> : null}

        {!showLoader && !showEmpty && radarData ? (
          <>
            {route.page === 'index' ? (
              <ThemeRadarHome
                data={radarData}
                device={device}
                onGoMomentum={() => updateHash('momentum')}
                onGoStock={goStock}
              />
            ) : null}
            {route.page === 'momentum' ? (
              <ThemeMomentum data={radarData} device={device} onGoStock={goStock} />
            ) : null}
            {route.page === 'flows' ? (
              <InstitutionalFlows data={radarData} device={device} onGoStock={goStock} />
            ) : null}
            {route.page === 'stock' ? (
              <StockDetail
                code={stockCode}
                exchange={stockExchange ?? stockInstrument?.exchange}
                name={stockInstrument?.name_zh}
                fundamentals={stockData.fundamentals}
                flows={stockData.flows}
                device={device}
                initialTab={route.tab}
                onBack={() => updateHash('index')}
                onTabChange={(tab) => updateHash('stock', stockCode, stockExchange, tab)}
              />
            ) : null}
            {route.page === 'sources' ? <SourceStatus data={radarData.sourceStatus} device={device} /> : null}
          </>
        ) : null}
      </main>
    </div>
  );
};
