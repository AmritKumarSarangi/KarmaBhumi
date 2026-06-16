import React, { useEffect } from 'react';
import MarketSelector from '../components/MarketSelector';
import Chart from '../components/Chart';
import OrderBook from '../components/OrderBook';
import OrderForm from '../components/OrderForm';
import TradesFeed from '../components/TradesFeed';
import Analytics from '../components/Analytics';
import BotActivity from '../components/BotActivity';
import LatencyMonitor from '../components/LatencyMonitor';
import { useWebSocket } from '../hooks/useWebSocket';
import { useMarket } from '../App';
import styles from './Dashboard.module.css';

interface DashboardProps {
  onConnectionChange?: (connected: boolean) => void;
}

export default function Dashboard({ onConnectionChange }: DashboardProps) {
  const { symbol } = useMarket();
  const { trades, orderBook, connected } = useWebSocket(symbol);

  useEffect(() => {
    onConnectionChange?.(connected);
  }, [connected, onConnectionChange]);

  return (
    <div className={styles.page}>
      {/* Market selector */}
      <div className={styles.marketBar}>
        <MarketSelector />
        <div className={styles.connBadge}>
          <span className={`${styles.connDot} ${connected ? styles.connOk : styles.connErr}`} />
          <span className={styles.connLabel}>{connected ? 'WS Connected' : 'Reconnecting…'}</span>
        </div>
      </div>

      {/* Main content */}
      <div className={styles.main}>
        {/* Left panel — Chart + OrderBook */}
        <div className={styles.leftPanel}>
          <div className={styles.chartArea}>
            <Chart symbol={symbol} trades={trades} />
          </div>
          <div className={styles.obArea}>
            <OrderBook orderBook={orderBook} symbol={symbol} />
          </div>
        </div>

        {/* Right panel — OrderForm + TradesFeed + Analytics */}
        <div className={styles.rightPanel}>
          <div className={styles.formArea}>
            <OrderForm />
          </div>
          <div className={styles.feedArea}>
            <TradesFeed trades={trades} />
          </div>
        </div>
      </div>

      {/* Analytics row */}
      <div className={styles.analyticsRow}>
        <Analytics symbol={symbol} />
      </div>

      {/* Bottom row — BotActivity + LatencyMonitor */}
      <div className={styles.bottomRow}>
        <div className={styles.botSection}>
          <BotActivity />
        </div>
        <div className={styles.latencySection}>
          <LatencyMonitor />
        </div>
      </div>
    </div>
  );
}
