import React, { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ArrowDownRight } from 'lucide-react';
import { Trade } from '../hooks/useWebSocket';
import styles from './TradesFeed.module.css';

interface Props {
  trades: Trade[];
}

export default function TradesFeed({ trades }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [newIds, setNewIds] = useState<Set<string>>(new Set());
  const prevTradesRef = useRef<Trade[]>([]);

  useEffect(() => {
    const prevIds = new Set(prevTradesRef.current.map(t => t.id));
    const incoming = trades.filter(t => !prevIds.has(t.id));
    if (incoming.length > 0) {
      const ids = new Set(incoming.map(t => t.id));
      setNewIds(ids);
      setTimeout(() => setNewIds(new Set()), 800);
      // Auto-scroll
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    prevTradesRef.current = trades;
  }, [trades]);

  const fmt = (n: number) =>
    n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const fmtTime = (ts: string) => {
    try {
      return new Date(ts).toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return '--:--:--';
    }
  };

  const getPriceDir = (i: number): 'up' | 'down' | 'none' => {
    if (i >= trades.length - 1) return 'none';
    const curr = trades[i].price;
    const next = trades[i + 1].price;
    if (curr > next) return 'up';
    if (curr < next) return 'down';
    return 'none';
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.title}>Trades Feed</span>
        <span className={styles.count}>{trades.length} trades</span>
      </div>

      <div className={styles.colHeaders}>
        <span>Time</span>
        <span>Price</span>
        <span>Size</span>
        <span>Dir</span>
      </div>

      <div className={styles.feed} ref={containerRef}>
        {trades.length === 0 && (
          <div className={styles.empty}>Waiting for trades…</div>
        )}
        {[...trades].reverse().map((trade, i) => {
          const dir = trade.side === 'BUY' ? 'up' : 'down';
          const isNew = newIds.has(trade.id);

          return (
            <div
              key={trade.id}
              className={`${styles.row} ${isNew ? (dir === 'up' ? styles.flashGreen : styles.flashRed) : ''}`}
            >
              <span className={styles.time}>{fmtTime(trade.timestamp)}</span>
              <span className={`${styles.price} ${dir === 'up' ? styles.priceUp : styles.priceDown}`}>
                ${fmt(trade.price)}
              </span>
              <span className={styles.qty}>{trade.quantity}</span>
              <span className={`${styles.arrow} ${dir === 'up' ? styles.arrowUp : styles.arrowDown}`}>
                {dir === 'up'
                  ? <ArrowUpRight size={13} strokeWidth={2.5} />
                  : <ArrowDownRight size={13} strokeWidth={2.5} />
                }
              </span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
