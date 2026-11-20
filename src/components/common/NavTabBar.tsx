import React from 'react';
import { DeviceType, PageType } from '../../types';

export type ThemeMode = 'dark' | 'light';

interface NavTabBarProps {
  page: PageType;
  setPage: (page: PageType) => void;
  device: DeviceType;
  mobileTitle?: string;
  theme: ThemeMode;
  onToggleTheme: () => void;
}

const tabs: Array<{ id: PageType; label: string }> = [
  // The index is the 訊息流 (feed) board; themes live on the momentum page.
  { id: 'index', label: '訊息流' },
  { id: 'momentum', label: '題材動能' },
  { id: 'watchlist', label: '個股雷達' },
  { id: 'flows', label: '資金流向' },
  { id: 'sources', label: '來源狀態' }
];

const ICON: Record<string, React.ReactNode> = {
  index: <path d="M4 6h16M4 12h16M4 18h10" />,
  momentum: <path d="M4 18l5-6 4 3 7-9" />,
  watchlist: <><circle cx="11" cy="11" r="6" /><path d="M20 20l-4.5-4.5" /></>,
  flows: <path d="M5 19V9M12 19V5M19 19v-7" />,
  sources: <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></>,
};

const NavIcon: React.FC<{ id: string }> = ({ id }) => (
  <svg className="nav-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{ICON[id]}</svg>
);

export const NavTabBar: React.FC<NavTabBarProps> = ({ page, setPage, device, mobileTitle, theme, onToggleTheme }) => {
  const mobileTitles: Record<PageType, string> = {
    index: '訊息流',
    momentum: '題材動能',
    watchlist: '個股雷達',
    flows: '三大法人資金流向',
    stock: '個股',
    sources: '來源狀態詳情'
  };
  const themeButton = (
    <button type="button" className="theme-toggle" onClick={onToggleTheme} aria-label={theme === 'dark' ? '切換為亮色' : '切換為暗色'}>
      {theme === 'dark' ? '亮色' : '暗色'}
    </button>
  );
  const nav = (
    <nav className={`main-nav ${device === 'mobile' ? 'mobile-nav' : 'side-nav'}`} aria-label="主要導覽">
      <div className="brand-lockup">
        <span className="brand-name">Nexus</span>
        <span className="brand-divider" aria-hidden="true" />
        <span className="brand-title">{device === 'mobile' ? (mobileTitle ?? mobileTitles[page]) : '台股題材雷達'}</span>
        {device === 'mobile' ? themeButton : null}
        <a className="nav-feedback-mobile" href="https://forms.gle/KwFAL59UjcnEBCNj6" target="_blank" rel="noreferrer">意見回饋 ↗</a>
      </div>
      <div className="nav-tabs">
        {tabs.map((tab) => (
          <button
            className={page === tab.id ? 'is-active' : ''}
            key={tab.id}
            type="button"
            aria-current={page === tab.id ? 'page' : undefined}
            onClick={() => setPage(tab.id)}
          >
            <NavIcon id={tab.id} />
            <span>{tab.label}</span>
          </button>
        ))}
      </div>
      {device === 'mobile' ? null : (
        <div className="side-foot">
          {themeButton}
          <a className="nav-feedback" href="https://forms.gle/KwFAL59UjcnEBCNj6" target="_blank" rel="noreferrer">意見回饋 ↗</a>
        </div>
      )}
    </nav>
  );

  if (device === 'mobile') {
    return (
      <>
        {nav}
        <nav className="mobile-bottom-nav" aria-label="手機主要導覽">
          {tabs.map((tab) => (
            <button
              className={page === tab.id ? 'is-active' : ''}
              key={tab.id}
              type="button"
              onClick={() => setPage(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </>
    );
  }

  return nav;
};
