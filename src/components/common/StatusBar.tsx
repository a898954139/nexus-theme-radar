import React from 'react';
import { DeviceType } from '../../types';

interface StatusBarProps {
  device: DeviceType;
  generatedAt?: string;
  sourceStatusOk: boolean;
  onGoSources: () => void;
}

function formatDate(value?: string) {
  const date = value ? new Date(value) : new Date(0);
  if (!value || Number.isNaN(date.getTime())) return { date: '—', time: '—', next: '—' };
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hour = String(date.getHours()).padStart(2, '0');
  const minute = String(date.getMinutes()).padStart(2, '0');
  const next = new Date(date.getTime());
  next.setHours(next.getHours() + 1, 0, 0, 0);
  return {
    date: `${year}-${month}-${day}`,
    time: `${hour}:${minute}`,
    next: `${String(next.getHours()).padStart(2, '0')}:00`
  };
}

export const StatusBar: React.FC<StatusBarProps> = ({ device, generatedAt, sourceStatusOk, onGoSources }) => {
  const formatted = formatDate(generatedAt);
  return (
    <div className={`status-bar ${device === 'mobile' ? 'status-bar-mobile' : ''}`}>
      <span>更新時間 <strong>{formatted.date} {formatted.time}</strong></span>
      <button type="button" onClick={onGoSources}>
        源狀態 <strong className={sourceStatusOk ? 'status-up' : 'status-down'}>{sourceStatusOk ? '正常' : '異常'}</strong>
        <span className="status-detail">詳情 →</span>
      </button>
      <a className="status-feedback" href="https://forms.gle/KwFAL59UjcnEBCNj6" target="_blank" rel="noreferrer">功能反饋 ↗</a>
      <span>預計下次更新 <strong>{formatted.next}</strong></span>
    </div>
  );
};
