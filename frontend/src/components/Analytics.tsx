import React, { useEffect, useState, useCallback } from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { api } from '../api/client';
import styles from './Analytics.module.css';

interface Props {
  symbol: string;
}

interface Stats {
  vwap: number;
  spread: number;
  spread_pct: number;
  imbalance: number;
  volume: number;
  trade_count: number;
  change_pct: number;
}

function TrendIcon({ val }: { val: number }) {
  if (val > 0)  return <TrendingUp size={13}  className={styles.trendUp} />;
  if (val < 0)  return <TrendingDown size={13} className={styles.trendDown} />;
  return <Minus size={13} className={styles.trendFlat} />;
}

export default function Analytics({ symbol }: Props) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [prev, setPrev] = useState<Stats | null>(null);

  const fetch = useCallback(async () => {
    try {
      const raw = await api.market.stats(symbol);
      // Map backend field names to component field names
      const data: Stats = {
        vwap: (raw as any).vwap ?? 0,
        spread: (raw as any).spread ?? 0,
        spread_pct: (raw as any).spread_pct ?? ((raw as any).spread > 0 && (raw as any).last_price > 0 ? ((raw as any).spread / (raw as any).last_price) * 100 : 0),
        imbalance: (raw as any).imbalance ?? (raw as any).order_imbalance ?? 0,
        volume: (raw as any).volume ?? 0,
        trade_count: (raw as any).trade_count ?? 0,
        change_pct: (raw as any).change_pct ?? 0,
      };
      setPrev(stats);
      setStats(data);
    } catch { /* silent */ }
  }, [symbol, stats]);

  useEffect(() => {
    fetch();
    const interval = setInterval(fetch, 5000);
    return () => clearInterval(interval);
  }, [symbol]);

  const fmt = (n: number, dec = 2) => n?.toFixed(dec) ?? '--';
  const fmtVol = (n: number) => {
    if (!n) return '--';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
    return n.toFixed(0);
  };

  return (
    <div className={styles.container}>
      {/* VWAP */}
      <div className={styles.card}>
        <span className={styles.cardLabel}>VWAP</span>
        <span className={styles.cardValue}>
          ${stats ? fmt(stats.vwap) : '—'}
        </span>
        <span className={styles.cardSub}>Volume-weighted avg price</span>
      </div>

      {/* Spread */}
      <div className={styles.card}>
        <span className={styles.cardLabel}>Spread</span>
        <span className={styles.cardValue}>
          ${stats ? fmt(stats.spread, 3) : '—'}
        </span>
        <span className={styles.cardSub}>
          {stats ? `${fmt(stats.spread_pct, 4)}%` : '—'}
        </span>
      </div>

      {/* Imbalance */}
      <div className={styles.card}>
        <span className={styles.cardLabel}>Imbalance</span>
        <span className={`${styles.cardValue} ${stats && stats.imbalance > 0 ? styles.valUp : styles.valDown}`}>
          {stats ? `${stats.imbalance > 0 ? '+' : ''}${fmt(stats.imbalance * 100, 1)}%` : '—'}
        </span>
        <div className={styles.imbalanceBar}>
          <div
            className={styles.imbalanceFill}
            style={{
              width: `${Math.abs((stats?.imbalance ?? 0) * 100)}%`,
              background: (stats?.imbalance ?? 0) > 0 ? 'var(--accent)' : 'var(--danger)',
              marginLeft: (stats?.imbalance ?? 0) > 0 ? '50%' : `${50 + (stats?.imbalance ?? 0) * 100}%`,
            }}
          />
          <div className={styles.imbalanceMid} />
        </div>
      </div>

      {/* Volume */}
      <div className={styles.card}>
        <span className={styles.cardLabel}>Volume</span>
        <span className={styles.cardValue}>{fmtVol(stats?.volume ?? 0)}</span>
        <div className={styles.cardSubRow}>
          <TrendIcon val={stats?.change_pct ?? 0} />
          <span className={styles.cardSub}>{stats ? `${fmt(stats.change_pct)}%` : '—'} today</span>
        </div>
      </div>

      {/* Trade Count */}
      <div className={styles.card}>
        <span className={styles.cardLabel}>Trades</span>
        <span className={styles.cardValue}>
          {stats ? stats.trade_count.toLocaleString() : '—'}
        </span>
        <div className={styles.cardSubRow}>
          <TrendIcon val={stats && prev ? stats.trade_count - prev.trade_count : 0} />
          <span className={styles.cardSub}>today</span>
        </div>
      </div>
    </div>
  );
}
