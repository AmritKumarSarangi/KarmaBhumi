import { useEffect, useRef, useState, useCallback } from 'react';

export interface Trade {
  id: string;
  symbol: string;
  price: number;
  quantity: number;
  side: 'BUY' | 'SELL';
  timestamp: string;
}

export interface OrderBookLevel {
  price: number;
  quantity: number;
  total: number;
}

export interface OrderBook {
  symbol: string;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  timestamp: string;
}

export interface MarketStats {
  symbol: string;
  last_price: number;
  open_price: number;
  high_price: number;
  low_price: number;
  volume: number;
  trade_count: number;
  vwap: number;
  spread: number;
  spread_pct: number;
  imbalance: number;
  change_pct: number;
  timestamp: string;
}

export interface WSAlert {
  type: 'circuit_breaker' | 'risk_limit' | 'fat_finger' | 'system';
  symbol?: string;
  message: string;
  severity: 'info' | 'warning' | 'error';
  timestamp: string;
}

interface WSState {
  trades: Trade[];
  orderBook: OrderBook | null;
  stats: MarketStats | null;
  alerts: WSAlert[];
  connected: boolean;
}

const MAX_TRADES = 50;
const INITIAL_BACKOFF = 1000;
const MAX_BACKOFF = 30000;

async function fetchInitialTrades(symbol: string): Promise<Trade[]> {
  try {
    const res = await fetch(`/api/trades/${symbol}?limit=50`);
    if (!res.ok) return [];
    const data = await res.json();
    // Normalize DB trade format to WS trade format
    return data.map((t: any) => ({
      id: t.id,
      symbol: t.symbol,
      price: t.price,
      quantity: t.quantity,
      side: (t.side ?? 'BUY') as 'BUY' | 'SELL',
      timestamp: t.timestamp,
    }));
  } catch {
    return [];
  }
}

export function useWebSocket(symbol: string): WSState {
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(INITIAL_BACKOFF);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const [state, setState] = useState<WSState>({
    trades: [],
    orderBook: null,
    stats: null,
    alerts: [],
    connected: false,
  });

  // Load initial trades from REST API when symbol changes
  useEffect(() => {
    fetchInitialTrades(symbol).then(trades => {
      if (mountedRef.current && trades.length > 0) {
        setState(prev => ({ ...prev, trades }));
      }
    });
  }, [symbol]);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }

    const wsUrl = `ws://${window.location.hostname}:8000/ws/${symbol}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      backoffRef.current = INITIAL_BACKOFF;
      setState(prev => ({ ...prev, connected: true }));
      // Subscribe to symbol
      ws.send(JSON.stringify({ action: 'subscribe', symbol }));
    };

    ws.onmessage = (event: MessageEvent) => {
      if (!mountedRef.current) return;
      try {
        const msg = JSON.parse(event.data as string);
        switch (msg.type) {
          case 'trade':
            setState(prev => ({
              ...prev,
              trades: [msg.data as Trade, ...prev.trades].slice(0, MAX_TRADES),
            }));
            break;
          case 'book':
            setState(prev => ({ ...prev, orderBook: msg.data as OrderBook }));
            break;
          case 'stats':
            setState(prev => ({ ...prev, stats: msg.data as MarketStats }));
            break;
          case 'alert':
            setState(prev => ({
              ...prev,
              alerts: [msg.data as WSAlert, ...prev.alerts].slice(0, 20),
            }));
            break;
          case 'snapshot':
            // Full snapshot on connect
            if (msg.trades)    setState(prev => ({ ...prev, trades: msg.trades }));
            if (msg.orderBook) setState(prev => ({ ...prev, orderBook: msg.orderBook }));
            if (msg.stats)     setState(prev => ({ ...prev, stats: msg.stats }));
            break;
          default:
            break;
        }
      } catch {
        // Ignore parse errors
      }
    };

    ws.onerror = () => {
      // Will trigger onclose automatically
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setState(prev => ({ ...prev, connected: false }));

      // Exponential backoff reconnect
      const delay = backoffRef.current;
      backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF);
      reconnectTimer.current = setTimeout(connect, delay);
    };
  }, [symbol]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  return state;
}
