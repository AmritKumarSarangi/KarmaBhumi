import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import toast from 'react-hot-toast';

/* ── Base Axios Instance ── */
export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

/* ── Auth Interceptor ── */
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('exchangex_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

/* ── Error Interceptor ── */
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string }>) => {
    if (error.response?.status === 401) {
      const isAuthUrl = error.config?.url?.includes('/auth/login') || error.config?.url?.includes('/auth/register');
      if (!isAuthUrl) {
        localStorage.removeItem('exchangex_token');
        localStorage.removeItem('exchangex_user');
        window.location.href = '/';
      }
    } else if (error.response?.status === 429) {
      toast.error('Rate limit exceeded. Please slow down.');
    } else if (error.response && error.response.status >= 500) {
      toast.error('Server error. Please try again.');
    }
    return Promise.reject(error);
  }
);

/* ── Order Types ── */
export type OrderSide = 'BUY' | 'SELL';
export type OrderType = 'LIMIT' | 'MARKET' | 'IOC' | 'FOK' | 'STOP_LOSS' | 'GTT';
export type OrderStatus = 'PENDING' | 'ACCEPTED' | 'REJECTED' | 'FILLED' | 'PARTIAL_FILL' | 'CANCELLED' | 'EXPIRED';

export interface PlaceOrderPayload {
  symbol: string;
  side: OrderSide;
  order_type: OrderType;
  quantity: number;
  price?: number;
  stop_price?: number;
  expire_at?: string;
}

export interface Order {
  id: string;
  symbol: string;
  side: OrderSide;
  order_type: OrderType;
  quantity: number;
  filled_quantity: number;
  price?: number;
  stop_price?: number;
  status: OrderStatus;
  created_at: string;
  updated_at: string;
}

export interface Portfolio {
  user_id: string;
  cash_balance: number;
  total_equity: number;
  total_market_value: number;
  total_unrealized_pnl: number;
  total_realized_pnl: number;
  positions: Position[];
}

export interface Position {
  symbol: string;
  quantity: number;
  avg_cost: number;
  last_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  market_value: number;
}

export interface PnLHistory {
  date: string;
  equity: number;
  daily_pnl: number;
  cumulative_pnl: number;
}

export interface AdminMetrics {
  orders_per_sec: number;
  trades_per_sec: number;
  latency_p50: number;
  latency_p95: number;
  latency_p99: number;
  active_websockets: number;
  total_orders_today: number;
  total_trades_today: number;
  queue_depth: number;
  cpu_usage: number;
  memory_usage: number;
}

export interface CircuitBreaker {
  symbol: string;
  status: 'active' | 'paused' | 'halted';
  reason?: string;
  paused_at?: string;
}

export interface SystemUser {
  user_id: string;
  email: string;
  is_admin: boolean;
  balance: number;
  created_at: string;
}

/* ── Typed API Surface ── */
export const api = {
  orders: {
    place: (data: PlaceOrderPayload) =>
      apiClient.post<Order>('/orders', data).then(r => r.data),
    cancel: (id: string) =>
      apiClient.delete<{ message: string }>(`/orders/${id}`).then(r => r.data),
    list: (params?: { symbol?: string; status?: OrderStatus; limit?: number }) =>
      apiClient.get<{ orders: Order[]; total: number; page: number; page_size: number }>('/orders', { params }).then(r => r.data.orders ?? r.data),
  },

  market: {
    orderBook: (symbol: string) =>
      apiClient.get<{
        bids: { price: number; quantity: number; total: number }[];
        asks: { price: number; quantity: number; total: number }[];
      }>(`/market/orderbook/${symbol}`).then(r => r.data),

    trades: (symbol: string, limit = 50) =>
      apiClient.get<{
        id: string;
        price: number;
        quantity: number;
        side: string;
        timestamp: string;
      }[]>(`/market/trades/${symbol}`, { params: { limit } }).then(r => r.data),

    stats: (symbol: string) =>
      apiClient.get<{
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
      }>(`/market/stats/${symbol}`).then(r => r.data),

    candles: (symbol: string, interval = '1m', limit = 200) =>
      apiClient.get<{
        time: number;
        open: number;
        high: number;
        low: number;
        close: number;
        volume: number;
      }[]>(`/market/candles/${symbol}`, { params: { interval, limit } }).then(r => r.data),

    symbols: () =>
      apiClient.get<{ symbol: string; name: string; last_price: number; change_pct: number }[]>(
        '/market/symbols'
      ).then(r => r.data),
  },

  portfolio: {
    get: () => apiClient.get<Portfolio>('/portfolio').then(r => r.data),
    history: (days = 30) =>
      apiClient.get<PnLHistory[]>('/portfolio/history', { params: { days } }).then(r => r.data),
  },

  admin: {
    metrics: () => apiClient.get<AdminMetrics>('/admin/metrics').then(r => r.data),
    pause: (symbol: string) =>
      apiClient.post<{ message: string }>(`/admin/circuit-breaker/${symbol}/pause`).then(r => r.data),
    resume: (symbol: string) =>
      apiClient.post<{ message: string }>(`/admin/circuit-breaker/${symbol}/resume`).then(r => r.data),
    circuitBreakers: () =>
      apiClient.get<CircuitBreaker[]>('/admin/circuit-breakers').then(r => r.data),
    users: () =>
      apiClient.get<SystemUser[]>('/admin/users').then(r => r.data),
    activityLog: () =>
      apiClient.get<{ timestamp: string; event: string; severity: string }[]>(
        '/admin/activity-log'
      ).then(r => r.data),
    updateRiskLimits: (data: { symbol: string; price_change_pct: number; window_seconds: number; enabled: boolean }) =>
      apiClient.put<{ message: string }>('/admin/risk-limits', data).then(r => r.data),
  },

  replay: {
    sessions: (symbol: string, date: string) =>
      apiClient.get<{ start_time: string; end_time: string; trade_count: number }>(
        `/replay/sessions`, { params: { symbol, date } }
      ).then(r => r.data),
    snapshot: (symbol: string, timestamp: string) =>
      apiClient.get(`/replay/snapshot`, { params: { symbol, timestamp } }).then(r => r.data),
  },

  bots: {
    status: () =>
      apiClient.get<{
        bot_type: string;
        orders_per_min: number;
        last_order: string;
        active: boolean;
        symbol: string;
      }[]>('/bots/status').then(r => r.data),
  },
};
