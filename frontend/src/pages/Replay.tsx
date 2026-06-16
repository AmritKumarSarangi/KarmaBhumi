import React, { useState, useEffect, useRef } from 'react';
import toast from 'react-hot-toast';
import styles from './Replay.module.css';

interface ReplayEvent {
  event_type: string;
  payload: any;
  timestamp: string;
  sequence_num: number;
}

export default function Replay() {
  const [symbol, setSymbol] = useState('AAPL');
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [speed, setSpeed] = useState(1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);

  // Playback state
  const [bids, setBids] = useState<{ price: number; quantity: number }[]>([]);
  const [asks, setAsks] = useState<{ price: number; quantity: number }[]>([]);
  const [trades, setTrades] = useState<{ price: number; quantity: number; timestamp: string }[]>([]);
  const [lastPrice, setLastPrice] = useState<number | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const totalEventsRef = useRef(100); // Mock target count for progress
  const processedEventsRef = useRef(0);

  const handleStartReplay = () => {
    if (isPlaying) {
      // Pause
      if (socketRef.current) {
        socketRef.current.close();
      }
      setIsPlaying(false);
      return;
    }

    // Connect to replay WebSocket
    const wsUrl = `ws://${window.location.host}/ws/replay?symbol=${symbol}&date=${date}&speed=${speed}`;
    console.log('Connecting to replay WS:', wsUrl);
    
    // Clear current state
    setBids([]);
    setAsks([]);
    setTrades([]);
    setLastPrice(null);
    setProgress(0);
    processedEventsRef.current = 0;

    const ws = new WebSocket(wsUrl);
    socketRef.current = ws;

    ws.onopen = () => {
      setIsPlaying(true);
      toast.success(`Starting replay of ${symbol} on ${date}`);
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        
        if (msg.type === 'session_info') {
          totalEventsRef.current = msg.total_events || 100;
          return;
        }

        if (msg.type === 'event') {
          const replayEvent: ReplayEvent = msg.data;
          processedEventsRef.current += 1;
          setProgress(Math.min(100, (processedEventsRef.current / totalEventsRef.current) * 100));

          // Rebuild state depending on event type
          if (replayEvent.event_type === 'ORDER_BOOK_UPDATE') {
            const payload = replayEvent.payload;
            if (payload.bids) setBids(payload.bids.slice(0, 5));
            if (payload.asks) setAsks(payload.asks.slice(0, 5));
          } else if (replayEvent.event_type === 'TRADE') {
            const t = replayEvent.payload;
            setLastPrice(t.price);
            setTrades(prev => [
              { price: t.price, quantity: t.quantity, timestamp: new Date().toLocaleTimeString() },
              ...prev.slice(0, 19)
            ]);
          }
        }
      } catch (err) {
        console.error('Failed to parse replay socket message', err);
      }
    };

    ws.onclose = () => {
      setIsPlaying(false);
      toast('Replay session completed', { icon: 'ℹ️' });
    };

    ws.onerror = () => {
      setIsPlaying(false);
      toast.error('Replay connection failed. Please make sure the backend is running.');
    };
  };

  useEffect(() => {
    return () => {
      if (socketRef.current) {
        socketRef.current.close();
      }
    };
  }, []);

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Exchange Trade Replay (Time-Machine)</h1>

      {/* Control Card */}
      <div className={styles.controlCard}>
        <div className={styles.inputs}>
          <div className={styles.group}>
            <label>Instrument</label>
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              <option value="AAPL">AAPL (Apple)</option>
              <option value="GOOGL">GOOGL (Alphabet)</option>
              <option value="TSLA">TSLA (Tesla)</option>
              <option value="MSFT">MSFT (Microsoft)</option>
              <option value="AMZN">AMZN (Amazon)</option>
            </select>
          </div>

          <div className={styles.group}>
            <label>Trading Day</label>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>

          <div className={styles.group}>
            <label>Playback Speed</label>
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
              <option value={1}>1x Normal</option>
              <option value={5}>5x Faster</option>
              <option value={10}>10x Speed</option>
              <option value={50}>50x Warp</option>
            </select>
          </div>

          <button className={`${styles.playBtn} ${isPlaying ? styles.pause : ''}`} onClick={handleStartReplay}>
            {isPlaying ? 'Pause Replay' : 'Run Session'}
          </button>
        </div>

        {/* Timeline Scrubber */}
        <div className={styles.scrubberRow}>
          <span className={styles.scrubLabel}>0%</span>
          <div className={styles.progressBar}>
            <div className={styles.progressInner} style={{ width: `${progress}%` }} />
          </div>
          <span className={styles.scrubLabel}>{Math.round(progress)}%</span>
        </div>
      </div>

      {/* Replay Viewport */}
      <div className={styles.viewport}>
        {/* Order Book Snapshot */}
        <div className={styles.panel}>
          <div className={styles.panelTitle}>Historical Depth</div>
          <div className={styles.obGrid}>
            <div className={styles.obSide}>
              <div className={styles.sideHeader}>Bids (Buy)</div>
              {bids.length === 0 ? (
                <div className={styles.noData}>No bids recorded.</div>
              ) : (
                bids.map((b, i) => (
                  <div key={i} className={styles.obRow}>
                    <span className={styles.bidPx}>₹{b.price.toFixed(2)}</span>
                    <span className={styles.qty}>{b.quantity}</span>
                  </div>
                ))
              )}
            </div>

            <div className={styles.obSide}>
              <div className={styles.sideHeader}>Asks (Sell)</div>
              {asks.length === 0 ? (
                <div className={styles.noData}>No asks recorded.</div>
              ) : (
                asks.map((a, i) => (
                  <div key={i} className={styles.obRow}>
                    <span className={styles.askPx}>₹{a.price.toFixed(2)}</span>
                    <span className={styles.qty}>{a.quantity}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Live Trades & Chart tape */}
        <div className={styles.panel}>
          <div className={styles.panelTitle}>Replay Feed</div>
          
          {lastPrice && (
            <div className={styles.priceTicker}>
              <span className={styles.tickerLabel}>Trade Price:</span>
              <span className={styles.tickerVal}>₹{lastPrice.toFixed(2)}</span>
            </div>
          )}

          <div className={styles.tradesTape}>
            <div className={styles.tapeHeader}>
              <span>Time</span>
              <span>Price</span>
              <span>Shares</span>
            </div>
            <div className={styles.tapeList}>
              {trades.length === 0 ? (
                <div className={styles.noData}>No trades triggered.</div>
              ) : (
                trades.map((t, i) => (
                  <div key={i} className={styles.tapeRow}>
                    <span className={styles.muted}>{t.timestamp}</span>
                    <span className={styles.green}>₹{t.price.toFixed(2)}</span>
                    <span>{t.quantity}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
