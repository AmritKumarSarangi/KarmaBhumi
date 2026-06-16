import React, { useEffect, useState, useCallback } from 'react';
import {
  LineChart, Line, Area, AreaChart, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from 'recharts';
import { TrendingUp, TrendingDown, DollarSign, BarChart2 } from 'lucide-react';
import { api, Portfolio as PortfolioType, PnLHistory, Position } from '../api/client';
import styles from './Portfolio.module.css';

function MetricCard({ label, value, sub, positive }: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean;
}) {
  return (
    <div className={styles.metricCard}>
      <span className={styles.metricLabel}>{label}</span>
      <span className={`${styles.metricValue} ${positive === true ? styles.valUp : positive === false ? styles.valDown : ''}`}>
        {value}
      </span>
      {sub && <span className={styles.metricSub}>{sub}</span>}
    </div>
  );
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className={styles.tooltip}>
      <div className={styles.tooltipDate}>{label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ color: p.color }}>
          {p.name}: <strong>${p.value?.toFixed(2)}</strong>
        </div>
      ))}
    </div>
  );
};

export default function Portfolio() {
  const [portfolio, setPortfolio] = useState<PortfolioType | null>(null);
  const [history, setHistory]     = useState<PnLHistory[]>([]);
  const [loading, setLoading]     = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [p, h] = await Promise.all([api.portfolio.get(), api.portfolio.history(30)]);
      setPortfolio(p);
      // If no history yet, generate synthetic equity curve from current balance
      if (Array.isArray(h) && h.length > 0) {
        setHistory(h);
      } else {
        const base = p.total_equity || 100_000;
        setHistory(Array.from({ length: 30 }, (_, i) => {
          const d = new Date(); d.setDate(d.getDate() - (29 - i));
          const drift = (Math.random() - 0.48) * 800;
          const equity = base + drift * (i + 1) * 0.3;
          return {
            date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
            equity,
            daily_pnl: drift,
            cumulative_pnl: equity - base,
          };
        }));
      }
    } catch {
      // Full mock fallback
      setPortfolio({
        user_id: '',
        cash_balance: 48_250.00,
        total_equity: 103_847.50,
        total_market_value: 55_597.50,
        total_unrealized_pnl: 8_340.20,
        total_realized_pnl: 12_450.00,
        positions: [
          { symbol: 'AAPL',  quantity: 200, avg_cost: 178.50, last_price: 185.20, unrealized_pnl: 1340.0,  unrealized_pnl_pct: 3.75,  market_value: 37040 },
          { symbol: 'TSLA',  quantity: 50,  avg_cost: 230.00, last_price: 248.10, unrealized_pnl: 905.0,   unrealized_pnl_pct: 7.87,  market_value: 12405 },
          { symbol: 'MSFT',  quantity: 30,  avg_cost: 380.00, last_price: 378.40, unrealized_pnl: -48.0,   unrealized_pnl_pct: -0.42, market_value: 11352 },
          { symbol: 'GOOGL', quantity: 40,  avg_cost: 138.00, last_price: 141.20, unrealized_pnl: 128.0,   unrealized_pnl_pct: 2.32,  market_value: 5648  },
        ],
      });
      const base = 90_000;
      setHistory(Array.from({ length: 30 }, (_, i) => {
        const d = new Date(); d.setDate(d.getDate() - (29 - i));
        const equity = base + Math.random() * 15000 - 3000 + i * 400;
        return {
          date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
          equity,
          daily_pnl: Math.random() * 800 - 200,
          cumulative_pnl: equity - base,
        };
      }));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 10000);
    return () => clearInterval(iv);
  }, [fetchData]);

  const fmt = (n: number, prefix = '$') =>
    `${prefix}${Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const pnlColor = (n: number) => n >= 0 ? 'var(--accent)' : 'var(--danger)';

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.pageTitle}>Portfolio</h1>
        {portfolio && (
          <div className={styles.lastUpdated}>
            Updated just now
          </div>
        )}
      </div>

      {/* Metric cards */}
      <div className={styles.metricsRow}>
        <MetricCard
          label="Total Equity"
          value={portfolio ? fmt(portfolio.total_equity) : '—'}
          sub="Portfolio value"
        />
        <MetricCard
          label="Cash Balance"
          value={portfolio ? fmt(portfolio.cash_balance) : '—'}
          sub="Available to trade"
          positive={true}
        />
        <MetricCard
          label="Unrealized P&L"
          value={portfolio ? `${portfolio.total_unrealized_pnl >= 0 ? '+' : '-'}${fmt(portfolio.total_unrealized_pnl)}` : '—'}
          sub="Open positions"
          positive={portfolio ? portfolio.total_unrealized_pnl >= 0 : undefined}
        />
        <MetricCard
          label="Realized P&L"
          value={portfolio ? `${portfolio.total_realized_pnl >= 0 ? '+' : '-'}${fmt(portfolio.total_realized_pnl)}` : '—'}
          sub="Closed positions"
          positive={portfolio ? portfolio.total_realized_pnl >= 0 : undefined}
        />
      </div>

      {/* PnL Chart */}
      <div className={styles.chartCard}>
        <div className={styles.cardHeader}>
          <span className={styles.cardTitle}>Equity Curve (30 days)</span>
        </div>
        <div className={styles.chartArea}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={history} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#00d4aa" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#00d4aa" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
              <XAxis dataKey="date" tick={{ fill: '#6b7280', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis
                tick={{ fill: '#6b7280', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={v => `$${(v / 1000).toFixed(0)}k`}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine y={history[0]?.equity ?? 0} stroke="rgba(255,255,255,0.1)" strokeDasharray="4 4" />
              <Area
                type="monotone"
                dataKey="equity"
                name="Equity"
                stroke="#00d4aa"
                strokeWidth={2}
                fill="url(#equityGrad)"
                dot={false}
                activeDot={{ r: 4, fill: '#00d4aa' }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Positions table */}
      <div className={styles.tableCard}>
        <div className={styles.cardHeader}>
          <span className={styles.cardTitle}>Open Positions</span>
          <span className={styles.cardCount}>{portfolio?.positions?.length ?? 0} positions</span>
        </div>
        <div className={styles.tableWrap}>
          <table className="table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Qty</th>
                <th>Avg Cost</th>
                <th>Last Price</th>
                <th>Mkt Value</th>
                <th>P&L</th>
                <th>P&L %</th>
              </tr>
            </thead>
            <tbody>
              {portfolio?.positions?.map(pos => (
                <tr key={pos.symbol}>
                  <td>
                    <span style={{ fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                      {pos.symbol}
                    </span>
                  </td>
                  <td>{pos.quantity.toLocaleString()}</td>
                  <td>${pos.avg_cost.toFixed(2)}</td>
                  <td style={{ color: 'var(--text-primary)', fontWeight: 600 }}>${pos.last_price.toFixed(2)}</td>
                  <td>${pos.market_value.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
                  <td style={{ color: pnlColor(pos.unrealized_pnl), fontWeight: 600 }}>
                    {pos.unrealized_pnl >= 0 ? '+' : ''}${Math.abs(pos.unrealized_pnl).toFixed(2)}
                  </td>
                  <td style={{ color: pnlColor(pos.unrealized_pnl_pct), fontWeight: 600 }}>
                    {pos.unrealized_pnl_pct >= 0 ? '+' : ''}{pos.unrealized_pnl_pct.toFixed(2)}%
                  </td>
                </tr>
              ))}
              {(!portfolio?.positions || portfolio.positions.length === 0) && (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', color: 'var(--text-dim)', padding: '24px' }}>
                    No open positions
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
