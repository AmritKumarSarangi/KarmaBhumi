import React, { useRef, useEffect, useCallback, useState } from 'react';
import { OrderBook as OBType } from '../hooks/useWebSocket';
import styles from './OrderBook.module.css';

interface Props {
  orderBook: OBType | null;
  symbol: string;
}

interface LevelWithFlash {
  price: number;
  quantity: number;
  total: number;
  flash?: 'up' | 'down';
}

function usePrevious<T>(value: T): T | undefined {
  const ref = useRef<T | undefined>(undefined);
  useEffect(() => { ref.current = value; });
  return ref.current;
}

export default function OrderBook({ orderBook, symbol }: Props) {
  const [bids, setBids] = useState<LevelWithFlash[]>([]);
  const [asks, setAsks] = useState<LevelWithFlash[]>([]);
  const prevBids = usePrevious(orderBook?.bids);
  const prevAsks = usePrevious(orderBook?.asks);

  // Track flash state per price level
  const flashTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const computeLevels = useCallback(
    (
      levels: { price: number; quantity: number; total: number }[] = [],
      prev: { price: number; quantity: number }[] = [],
      side: 'bid' | 'ask'
    ): LevelWithFlash[] => {
      const prevMap = new Map(prev.map(l => [l.price, l.quantity]));
      return levels.slice(0, 10).map(l => ({
        ...l,
        flash: prevMap.has(l.price) && prevMap.get(l.price) !== l.quantity
          ? side === 'bid' ? 'up' : 'down'
          : undefined,
      }));
    },
    []
  );

  useEffect(() => {
    if (!orderBook) return;
    setBids(computeLevels(orderBook.bids, prevBids ?? [], 'bid'));
    setAsks(computeLevels(orderBook.asks, prevAsks ?? [], 'ask'));
  }, [orderBook, computeLevels]);

  const fmt = (n: number) =>
    n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const fmtQty = (n: number) =>
    n >= 1000 ? `${(n / 1000).toFixed(1)}K` : n.toFixed(0);

  const maxBidQty = Math.max(...bids.map(b => b.quantity), 1);
  const maxAskQty = Math.max(...asks.map(a => a.quantity), 1);

  const bestBid = bids[0]?.price ?? 0;
  const bestAsk = asks[0]?.price ?? 0;
  const spread = bestAsk - bestBid;
  const spreadPct = bestBid > 0 ? (spread / bestBid) * 100 : 0;

  if (!orderBook) {
    return (
      <div className={styles.container}>
        <div className={styles.header}>
          <span className={styles.title}>Order Book</span>
          <span className={styles.symbol}>{symbol}</span>
        </div>
        <div className={styles.empty}>Connecting to order book…</div>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.title}>Order Book</span>
        <span className={styles.symbol}>{symbol}</span>
      </div>

      {/* Column headers */}
      <div className={styles.colHeaders}>
        <div className={styles.colHeaderGroup}>
          <span>Total</span>
          <span>Size</span>
          <span>Bid</span>
        </div>
        <div className={styles.colHeaderGroup}>
          <span>Ask</span>
          <span>Size</span>
          <span>Total</span>
        </div>
      </div>

      <div className={styles.body}>
        {/* Bids */}
        <div className={styles.bids}>
          {bids.map((level, i) => (
            <div
              key={level.price}
              className={`${styles.row} ${styles.bidRow} ${
                level.flash ? styles.flashBid : ''
              }`}
            >
              <div
                className={styles.depthBar}
                style={{ width: `${(level.quantity / maxBidQty) * 100}%` }}
              />
              <span className={styles.total}>{fmtQty(level.total)}</span>
              <span className={styles.qty}>{fmtQty(level.quantity)}</span>
              <span className={styles.bidPrice}>{fmt(level.price)}</span>
            </div>
          ))}
        </div>

        {/* Spread indicator */}
        <div className={styles.spread}>
          <div className={styles.spreadLine} />
          <span className={styles.spreadValue}>
            Spread: <strong>${spread.toFixed(2)}</strong>
            <span className={styles.spreadPct}>({spreadPct.toFixed(3)}%)</span>
          </span>
          <div className={styles.spreadLine} />
        </div>

        {/* Asks */}
        <div className={styles.asks}>
          {asks.map((level, i) => (
            <div
              key={level.price}
              className={`${styles.row} ${styles.askRow} ${
                level.flash ? styles.flashAsk : ''
              }`}
            >
              <div
                className={`${styles.depthBar} ${styles.depthBarAsk}`}
                style={{ width: `${(level.quantity / maxAskQty) * 100}%` }}
              />
              <span className={styles.askPrice}>{fmt(level.price)}</span>
              <span className={styles.qty}>{fmtQty(level.quantity)}</span>
              <span className={styles.total}>{fmtQty(level.total)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
