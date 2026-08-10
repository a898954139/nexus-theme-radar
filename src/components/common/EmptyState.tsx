import React from 'react';
import { PageType } from '../../types';

const copy: Record<PageType, { title: string; body: string }> = {
  index: { title: '等待題材資料', body: '題材排行資料載入後，這裡會顯示最新五個題材與關聯標的。' },
  momentum: { title: '等待歷史資料', body: '題材動能分數歷史圖資料載入後顯示；缺少的小時會保留為斷點。' },
  watchlist: { title: '目前沒有可顯示的個股雷達資料', body: '下一輪 pipeline 產生候選池後，這裡會顯示短線與長線關注清單。' },
  flows: { title: '等待籌碼資料', body: '三大法人買賣超彙總資料載入後，即可切換三種檢視方式。' },
  stock: { title: '等待財務資料', body: '個股季度財報與三大法人資料載入後，這裡會顯示摘要與趨勢。' },
  sources: { title: '等待來源狀態', body: '來源狀態資料載入後，這裡會顯示採集來源與目前狀態。' }
};

export const EmptyState: React.FC<{ page: PageType }> = ({ page }) => (
  <section className="empty-state">
    <span className="page-kicker">NO DATA YET</span>
    <h1>{copy[page].title}</h1>
    <div className="gold-rule muted-rule" />
    <p>{copy[page].body}</p>
  </section>
);
