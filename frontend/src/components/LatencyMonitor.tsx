import React, { useEffect, useState, useCallback } from 'react';
import styles from './LatencyMonitor.module.css';

function getColor(ms: number): string {
  if (ms < 1)  return '#00d4aa';
  if (ms < 5)  return '#ffa502';
  return '#ff4757';
}

function CircularGauge({ label, value, max = 10 }: { label: string; value: number; max?: number }) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const pct = Math.min(value / max, 1);
  const dashOffset = circumference * (1 - pct);
  const color = getColor(value);
  const colorClass = value < 1 ? styles.green : value < 5 ? styles.yellow : styles.red;

  return (
    <div className={styles.gauge}>
      <svg viewBox="0 0 100 100" className={styles.gaugeSvg}>
        {/* Background arc */}
        <circle
          cx="50" cy="50" r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * 0.25}
          transform="rotate(135 50 50)"
        />
        {/* Value arc */}
        <circle
          cx="50" cy="50" r={radius}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * 0.25 + circumference * 0.75 * (1 - pct)}
          transform="rotate(135 50 50)"
          style={{
            filter: `drop-shadow(0 0 4px ${color})`,
            transition: 'stroke-dashoffset 0.6s ease, stroke 0.6s ease',
          }}
        />
        {/* Center text */}
        <text x="50" y="46" textAnchor="middle" className={styles.gaugeVal} fill={color}>
          {value < 0.1 ? value.toFixed(2) : value < 10 ? value.toFixed(1) : value.toFixed(0)}
        </text>
        <text x="50" y="60" textAnchor="middle" className={styles.gaugeUnit} fill="#6b7280">
          ms
        </text>
      </svg>
      <span className={`${styles.gaugeLabel} ${colorClass}`}>{label}</span>
    </div>
  );
}

interface LatencyData {
  p50_latency_ns: number;
  p95_latency_ns: number;
  p99_latency_ns: number;
  orders_per_second: number;
  trades_per_second: number;
  mock?: boolean;
}

export default function LatencyMonitor() {
  const [metrics, setMetrics] = useState<LatencyData | null>(null);

  const fetchMetrics = useCallback(async () => {
    try {
      // Use the public /api/latency endpoint (no auth required)
      const res = await fetch('/api/latency');
      if (res.ok) {
        const data = await res.json();
        setMetrics(data);
      }
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 2000);
    return () => clearInterval(interval);
  }, [fetchMetrics]);

  const nsToMs = (ns: number) => ns > 0 ? ns / 1_000_000 : 0;
  const p50 = nsToMs(metrics?.p50_latency_ns ?? 0);
  const p95 = nsToMs(metrics?.p95_latency_ns ?? 0);
  const p99 = nsToMs(metrics?.p99_latency_ns ?? 0);
  const ordersPerSec = metrics?.orders_per_second ?? 0;
  const tradesPerSec = metrics?.trades_per_second ?? 0;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.title}>Matching Latency</span>
        <div className={styles.legend}>
          <span className={styles.legendItem}><span className={`${styles.dot} ${styles.green}`} /> &lt;1ms</span>
          <span className={styles.legendItem}><span className={`${styles.dot} ${styles.yellow}`} /> 1-5ms</span>
          <span className={styles.legendItem}><span className={`${styles.dot} ${styles.red}`} /> &gt;5ms</span>
        </div>
      </div>
      <div className={styles.gauges}>
        <CircularGauge label="P50" value={p50} max={10} />
        <CircularGauge label="P95" value={p95} max={10} />
        <CircularGauge label="P99" value={p99} max={10} />
      </div>
      {metrics && (
        <div className={styles.extra}>
          <div className={styles.extraItem}>
            <span className={styles.extraLabel}>Orders/s</span>
            <span className={styles.extraVal}>{ordersPerSec.toFixed(0)}</span>
          </div>
          <div className={styles.extraItem}>
            <span className={styles.extraLabel}>Trades/s</span>
            <span className={styles.extraVal}>{tradesPerSec.toFixed(0)}</span>
          </div>
        </div>
      )}
    </div>
  );
}
