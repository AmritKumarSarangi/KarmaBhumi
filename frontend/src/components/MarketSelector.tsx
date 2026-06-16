import React, { useEffect, useState, useCallback } from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import { useMarket } from '../App';
import { api } from '../api/client';
import styles from './MarketSelector.module.css';

const SYMBOLS = ['AAPL', 'GOOGL', 'TSLA', 'MSFT', 'AMZN'];

interface SymbolData {
  symbol: string;
  last_price: number;
  change_pct: number;
  prev_price?: number;
}

export default function MarketSelector() {
  const { symbol, setSymbol } = useMarket();
  const [data, setData] = useState<Record<string, SymbolData>>(() =>
    Object.fromEntries(
      SYMBOLS.map(s => [s, {
        symbol: s,
        last_price: { AAPL: 185, GOOGL: 141, TSLA: 248, MSFT: 378, AMZN: 186 }[s] ?? 100,
        change_pct: 0,
      }])
    )
  );
  const [flash, setFlash] = useState<Record<string, 'up' | 'down' | null>>({});

  const fetchPrices = useCallback(async () => {
    try {
      const symbols = await api.market.symbols();
      const next: Record<string, SymbolData> = { ...data };
      symbols.forEach(sym => {
        const prev = data[sym.symbol]?.last_price;
        next[sym.symbol] = { ...sym, prev_price: prev };
        if (prev !== undefined && prev !== sym.last_price) {
          setFlash(f => ({ ...f, [sym.symbol]: sym.last_price > prev ? 'up' : 'down' }));
          setTimeout(() => {
            setFlash(f => ({ ...f, [sym.symbol]: null }));
          }, 700);
        }
      });
      setData(next);
    } catch {
      // silently fail — use stale data
    }
  }, []);

  useEffect(() => {
    fetchPrices();
    const interval = setInterval(fetchPrices, 3000);
    return () => clearInterval(interval);
  }, [fetchPrices]);

  const fmt = (n: number) =>
    n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div className={styles.container}>
      {SYMBOLS.map(sym => {
        const info = data[sym];
        const isActive = sym === symbol;
        const flashDir = flash[sym];
        const pct = info?.change_pct ?? 0;
        const isUp = pct >= 0;

        return (
          <button
            key={sym}
            className={`${styles.tab} ${isActive ? styles.tabActive : ''} ${
              flashDir === 'up' ? styles.flashUp : flashDir === 'down' ? styles.flashDown : ''
            }`}
            onClick={() => setSymbol(sym)}
          >
            <span className={styles.symbol}>{sym}</span>
            <span className={styles.price}>${fmt(info?.last_price ?? 0)}</span>
            <span className={`${styles.change} ${isUp ? styles.changeUp : styles.changeDown}`}>
              {isUp ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
              {isUp ? '+' : ''}{pct.toFixed(2)}%
            </span>
          </button>
        );
      })}
    </div>
  );
}
