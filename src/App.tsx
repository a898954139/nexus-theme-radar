import React, { useEffect, useMemo, useRef, useState } from 'react';
import { EmptyState } from './components/common/EmptyState';
import { NavTabBar } from './components/common/NavTabBar';
import { StatusBar } from './components/common/StatusBar';
import { WavePhysicsLoader } from './components/common/WavePhysicsLoader';
import { InstitutionalFlows } from './components/flows/InstitutionalFlows';
import { ThemeRadarHome } from './components/home/ThemeRadarHome';
import { ThemeMomentum } from './components/momentum/ThemeMomentum';
import { SourceStatus } from './components/sources/SourceStatus';
import { StockDetail } from './components/stock/StockDetail';
import { StockWatchlist, WatchlistView } from './components/watchlist/StockWatchlist';
import { useSiteMetrics } from './hooks/useSiteMetrics';
import { fetchStockWatchlist, loadRadarData, fetchBrokerMap, fetchInstitutionalFlows, fetchStockFundamentals, fetchPreMarket } from './services/dataService';
import { DeviceType, PageType, PreMarketData, RadarData, StockTab, StockWatchlistData } from './types';

interface RouteState {
  page: PageType;
  code: string;
  exchange?: string;
  tab: StockTab;
  view: WatchlistView;
  q: string;
}

const DATA_REFRESH_INTERVAL_MS = 5 * 60 * 1000;

function readRoute(): RouteState {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const page = (params.get('page') as PageType | null) ?? 'index';
  const view: WatchlistView = params.get('view') === 'long' ? 'long' : params.get('view') === 'search' ? 'search' : 'short';
  const exchange = params.get('exchange');
  return {
    page: ['index', 'momentum', 'flows', 'watchlist', 'stock', 'sources'].includes(page) ? page : 'index',
    code: params.get('code') ?? '',
    exchange: exchange === 'TWSE' || exchange === 'TPEX' ? exchange : undefined,
    tab: params.get('tab') === 'technical' ? 'technical' : params.get('tab') === 'flows' ? 'flows' : params.get('tab') === 'broker' ? 'broker' : 'fundamentals',
    view,
    q: view === 'search' ? params.get('q') ?? '' : ''
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
  const [preMarket, setPreMarket] = useState<PreMarketData | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [watchlistData, setWatchlistData] = useState<StockWatchlistData | null>(null);
  const [watchlistLoading, setWatchlistLoading] = useState(true);
  const [watchlistError, setWatchlistError] = useState(false);
  const [watchlistRequest, setWatchlistRequest] = useState(0);
  const [refreshKey, setRefreshKey] = useState(0);
  const radarRefreshInFlight = useRef(false);
  const watchlistRefreshInFlight = useRef(false);
  const [stockData, setStockData] = useState<{
    fundamentals: Awaited<ReturnType<typeof fetchStockFundamentals>>;
    flows: Awaited<ReturnType<typeof fetchInstitutionalFlows>>;
    brokerMap: Awaited<ReturnType<typeof fetchBrokerMap>>;
  }>({ fundamentals: null, flows: [], brokerMap: null });
  const [brokerLoading, setBrokerLoading] = useState(false);
  // Latched rather than tracking route.page directly: navigating away from the
  // index and back must not re-run the effect and record a second view.
  const [metricsStarted, setMetricsStarted] = useState(() => readRoute().page === 'index');
  const counts = useSiteMetrics(metricsStarted);
  const defaultInstrument = useMemo(
    () => radarData?.themeRanking.themes.flatMap((theme) => theme.direct_mentions)[0],
    [radarData]
  );
  const stockCode = route.code || defaultInstrument?.symbol || '';
  const stockInstrument = useMemo(
    () => instrumentForCode(radarData, stockCode, route.exchange) ?? (!route.code ? defaultInstrument : undefined),
    [defaultInstrument, radarData, route.code, route.exchange, stockCode]
  );
  const stockExchange = route.exchange ?? stockInstrument?.exchange;

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
    if (route.page === 'index') setMetricsStarted(true);
  }, [route.page]);

  useEffect(() => {
    let active = true;
    setWatchlistLoading(true);
    setWatchlistError(false);
    fetchStockWatchlist()
      .then((data) => {
        if (active) setWatchlistData(data);
      })
      .catch(() => {
        if (active) setWatchlistError(true);
      })
      .finally(() => {
        if (active) setWatchlistLoading(false);
      });
    return () => {
      active = false;
    };
  }, [watchlistRequest]);

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

  // Loaded separately from the radar payload: the pre-market board depends on
  // two third-party sources, and neither should be able to block the page.
  useEffect(() => {
    let active = true;
    fetchPreMarket().then((data) => {
      if (active) setPreMarket(data);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    const refreshRadar = () => {
      if (!active || radarRefreshInFlight.current) return;
      radarRefreshInFlight.current = true;
      loadRadarData(true)
        .then((data) => {
          if (!active) return;
          setRadarData(data);
          setLoadError(false);
          setRefreshKey((key) => key + 1);
        })
        .catch(() => {
          // Keep the last good snapshot visible during a transient refresh failure.
        })
        .finally(() => {
          radarRefreshInFlight.current = false;
        });
    };

    const refreshWatchlist = () => {
      if (!active || watchlistRefreshInFlight.current) return;
      watchlistRefreshInFlight.current = true;
      fetchStockWatchlist(true)
        .then((data) => {
          if (!active) return;
          setWatchlistData(data);
          setWatchlistError(false);
        })
        .catch(() => {
          // Keep the last good snapshot visible during a transient refresh failure.
        })
        .finally(() => {
          watchlistRefreshInFlight.current = false;
        });
    };

    const refresh = () => {
      refreshRadar();
      refreshWatchlist();
    };
    const timer = window.setInterval(refresh, DATA_REFRESH_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (route.page !== 'stock') return;
    if (route.tab === 'technical') {
      setBrokerLoading(false);
      return;
    }
    let active = true;
    setBrokerLoading(route.tab === 'broker');
    Promise.all([
      fetchStockFundamentals(stockCode, stockExchange, refreshKey > 0),
      fetchInstitutionalFlows(stockCode, stockExchange, refreshKey > 0),
      route.tab === 'broker' ? fetchBrokerMap(stockCode, refreshKey > 0).catch(() => null) : Promise.resolve(null)
    ]).then(([fundamentals, flows, brokerMap]) => {
      if (active) {
        setStockData({ fundamentals, flows, brokerMap });
        setBrokerLoading(false);
      }
    });
    return () => {
      active = false;
    };
  }, [route.page, route.tab, stockCode, stockExchange, refreshKey]);

  const updateHash = (page: PageType, code?: string, exchange?: string, tab?: StockTab) => {
    const params = new URLSearchParams({ page });
    if (code) params.set('code', code);
    if (exchange) params.set('exchange', exchange);
    if (tab) params.set('tab', tab);
    window.location.hash = params.toString();
  };

  const updateWatchlistHash = (view: WatchlistView, query = '', replace = false) => {
    const params = new URLSearchParams({ page: 'watchlist', view });
    if (view === 'search' && query) params.set('q', query);
    const nextHash = `#${params.toString()}`;
    if (replace) {
      window.history.replaceState(null, '', nextHash);
      setRoute(readRoute());
    } else {
      window.location.hash = params.toString();
    }
  };

  const goStock = (code: string, exchange?: string, tab: StockTab = 'fundamentals') => {
    updateHash('stock', code, exchange, tab);
  };

  const showLoader = !radarData && !loadError;
  const showCoreLoader = route.page !== 'watchlist' && !radarData && !loadError;
  const showEmpty = route.page !== 'watchlist' && (loadError || radarData?.themeRanking.themes.length === 0);

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
          counts={counts}
        />

        {showCoreLoader ? <WavePhysicsLoader scale={device === 'mobile' ? 0.72 : 1} /> : null}
        {showEmpty && !showLoader ? <EmptyState page={route.page} /> : null}

        {route.page === 'watchlist' ? (
          <StockWatchlist
            payload={watchlistData}
            view={route.view}
            query={route.q}
            onViewChange={(view) => updateWatchlistHash(view, view === 'search' ? route.q : '')}
            onQueryChange={(query) => updateWatchlistHash('search', query, true)}
            onGoStock={goStock}
            loading={watchlistLoading}
            error={watchlistError}
            onRetry={() => setWatchlistRequest((request) => request + 1)}
            onGoHome={() => updateHash('index')}
          />
        ) : null}

        {!showLoader && !showEmpty && radarData ? (
          <>
            {route.page === 'index' ? (
              <ThemeRadarHome
                data={radarData}
                preMarket={preMarket}
                device={device}
                onGoMomentum={() => updateHash('momentum')}
                onGoStock={goStock}
              />
            ) : null}
            {route.page === 'momentum' ? (
              <ThemeMomentum data={radarData} device={device} onGoStock={goStock} />
            ) : null}
            {route.page === 'flows' ? (
              <InstitutionalFlows data={radarData} device={device} onGoStock={goStock} refreshKey={refreshKey} />
            ) : null}
            {route.page === 'stock' ? (
              <StockDetail
                code={stockCode}
                exchange={stockExchange ?? stockInstrument?.exchange}
                name={stockInstrument?.name_zh}
                fundamentals={stockData.fundamentals}
                flows={stockData.flows}
                brokerMap={stockData.brokerMap}
                brokerLoading={brokerLoading}
                device={device}
                initialTab={route.tab}
                onBack={() => updateHash('index')}
                onTabChange={(tab) => updateHash('stock', stockCode, stockExchange, tab)}
                onGoStock={goStock}
              />
            ) : null}
            {route.page === 'sources' ? <SourceStatus data={radarData.sourceStatus} device={device} /> : null}
          </>
        ) : null}
      </main>
    </div>
  );
};
