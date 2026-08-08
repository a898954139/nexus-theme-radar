import React from 'react';
import { DeviceType, PageType } from '../../types';

interface NavTabBarProps {
  page: PageType;
  setPage: (page: PageType) => void;
  device: DeviceType;
  mobileTitle?: string;
}

const tabs: Array<{ id: PageType; label: string }> = [
  { id: 'index', label: '題材雷達' },
  { id: 'momentum', label: '題材動能' },
  { id: 'flows', label: '資金流向' },
  { id: 'stock', label: '個股' },
  { id: 'sources', label: '源狀態' }
];

export const NavTabBar: React.FC<NavTabBarProps> = ({ page, setPage, device, mobileTitle }) => {
  const mobileTitles: Record<PageType, string> = {
    index: '台股最近熱什麼',
    momentum: '題材動能',
    flows: '三大法人資金流向',
    stock: '個股',
    sources: '源狀態詳情'
  };
  const nav = (
    <nav className={`main-nav ${device === 'mobile' ? 'mobile-nav' : ''}`} aria-label="主要導覽">
      <div className="brand-lockup">
        <span className="brand-name">NEXUS</span>
        <span className="brand-divider" aria-hidden="true" />
        <span className="brand-title">{device === 'mobile' ? (mobileTitle ?? mobileTitles[page]) : '台股題材雷達'}</span>
      </div>
      <div className="nav-tabs">
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
      </div>
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
