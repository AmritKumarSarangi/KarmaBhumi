import React, { useEffect, useRef, useState } from 'react';
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  HistogramData,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts';
import { Trade } from '../hooks/useWebSocket';
import { api } from '../api/client';
import styles from './Chart.module.css';

interface Props {
  symbol: string;
  trades: Trade[];
}

type CandleMap = Map<number, CandlestickData & { volume: number }>;

function tradeToCandleTime(ts: string, intervalMs = 60_000): number {
  const t = new Date(ts).getTime();
  return Math.floor(t / intervalMs) * (intervalMs / 1000);
}

export default function Chart({ symbol, trades }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const candleMapRef = useRef<CandleMap>(new Map());
  const [loading, setLoading] = useState(true);
  const INTERVAL_MS = 60_000; // 1 minute candles

  /* ── Chart Initialization ── */
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#6b7280',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: 'rgba(0,212,170,0.4)',
          width: 1,
          style: 1,
          labelBackgroundColor: '#00d4aa',
        },
        horzLine: {
          color: 'rgba(0,212,170,0.4)',
          width: 1,
          style: 1,
          labelBackgroundColor: '#00d4aa',
        },
      },
      rightPriceScale: {
        borderColor: 'rgba(255,255,255,0.08)',
        textColor: '#6b7280',
      },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.08)',
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (t: number) => {
          const d = new Date(t * 1000);
          return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
        },
      },
      handleScale: { axisPressedMouseMove: { price: true, time: true } },
    });
    chartRef.current = chart;

    // Candlestick series
    const cSeries = chart.addCandlestickSeries({
      upColor: '#00d4aa',
      downColor: '#ff4757',
      borderUpColor: '#00d4aa',
      borderDownColor: '#ff4757',
      wickUpColor: '#00d4aa',
      wickDownColor: '#ff4757',
    });
    candleSeriesRef.current = cSeries;

    // Volume series (uses a secondary pane via priceScaleId)
    const vSeries = chart.addHistogramSeries({
      color: 'rgba(0,212,170,0.3)',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.85, bottom: 0 },
    });
    volumeSeriesRef.current = vSeries;

    // ResizeObserver
    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight,
        });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  /* ── Load Historical Candles ── */
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    candleMapRef.current = new Map();

    api.market.candles(symbol, '1m', 200)
      .then(candles => {
        if (cancelled) return;
        const map: CandleMap = new Map();
        const cData: CandlestickData[] = [];
        const vData: HistogramData[] = [];

        candles.forEach(c => {
          map.set(c.time, { time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume });
          cData.push({ time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close });
          vData.push({
            time: c.time as any,
            value: c.volume,
            color: c.close >= c.open ? 'rgba(0,212,170,0.35)' : 'rgba(255,71,87,0.35)',
          });
        });

        candleMapRef.current = map;
        candleSeriesRef.current?.setData(cData);
        volumeSeriesRef.current?.setData(vData);
        chartRef.current?.timeScale().fitContent();
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [symbol]);

  /* ── Real-time Candle Updates from Trades ── */
  useEffect(() => {
    if (trades.length === 0) return;
    const latest = trades[0];
    if (!latest) return;

    const candleTime = tradeToCandleTime(latest.timestamp, INTERVAL_MS);
    const price = latest.price;
    const qty = latest.quantity;

    const existing = candleMapRef.current.get(candleTime);
    let updated: CandlestickData & { volume: number };

    if (existing) {
      updated = {
        ...existing,
        high: Math.max(existing.high, price),
        low: Math.min(existing.low, price),
        close: price,
        volume: existing.volume + qty,
      };
    } else {
      updated = {
        time: candleTime as any,
        open: price,
        high: price,
        low: price,
        close: price,
        volume: qty,
      };
    }

    candleMapRef.current.set(candleTime, updated);
    candleSeriesRef.current?.update({ time: updated.time, open: updated.open, high: updated.high, low: updated.low, close: updated.close });
    volumeSeriesRef.current?.update({
      time: updated.time,
      value: updated.volume,
      color: updated.close >= updated.open ? 'rgba(0,212,170,0.35)' : 'rgba(255,71,87,0.35)',
    });
  }, [trades]);

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <span className={styles.title}>{symbol} — 1m Candlestick</span>
        {loading && <span className={styles.loading}>Loading…</span>}
      </div>
      <div className={styles.chart} ref={containerRef} />
    </div>
  );
}
