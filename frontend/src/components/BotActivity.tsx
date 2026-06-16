import React, { useEffect, useState, useCallback } from 'react';
import { Bot, Zap, Building2, TrendingUp, Users } from 'lucide-react';
import { api } from '../api/client';
import styles from './BotActivity.module.css';

interface BotStatus {
  bot_type: string;
  orders_per_min: number;
  last_order: string;
  active: boolean;
  symbol: string;
}

const BOT_CONFIG: Record<string, {
  displayName: string;
  icon: React.ReactNode;
  color: string;
  desc: string;
  maxRate: number;
}> = {
  Retail:         { displayName: 'Uttara Kumara', icon: <Users size={16} />,     color: '#e74c3c', desc: 'Panic-prone retail flow', maxRate: 60 },
  HFT:            { displayName: 'Ashwatthama',   icon: <Zap size={16} />,       color: '#f1c40f', desc: 'Ultra-swift algorithmic strikes', maxRate: 600 },
  'Market Maker': { displayName: 'Bhishma Pitamah',icon: <TrendingUp size={16} />, color: '#ff9f43', desc: 'Steadfast bid/ask foundation', maxRate: 200 },
  Institution:    { displayName: 'Yudhishthira',  icon: <Building2 size={16} />, color: '#3498db', desc: 'Massive, patient block orders', maxRate: 20 },
};

export default function BotActivity() {
  const [bots, setBots] = useState<BotStatus[]>([]);

  const fetchBots = useCallback(async () => {
    try {
      const data = await api.bots.status();
      setBots(data);
    } catch {
      // Show mock data if backend not available
      setBots([
        { bot_type: 'Retail',        orders_per_min: 42,  last_order: 'BUY 100 AAPL @ 185.50', active: true,  symbol: 'AAPL' },
        { bot_type: 'HFT',           orders_per_min: 480, last_order: 'SELL 10 TSLA @ 248.20',  active: true,  symbol: 'TSLA' },
        { bot_type: 'Market Maker',  orders_per_min: 180, last_order: 'BID 50 MSFT @ 377.90',   active: true,  symbol: 'MSFT' },
        { bot_type: 'Institution',   orders_per_min: 8,   last_order: 'BUY 5000 GOOGL @ 141.1', active: false, symbol: 'GOOGL' },
      ]);
    }
  }, []);

  useEffect(() => {
    fetchBots();
    const interval = setInterval(fetchBots, 3000);
    return () => clearInterval(interval);
  }, [fetchBots]);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.title}>Bot Activity</span>
        <span className={styles.subtitle}>{bots.filter(b => b.active).length}/{bots.length} active</span>
      </div>
      <div className={styles.grid}>
        {bots.map(bot => {
          const cfg = BOT_CONFIG[bot.bot_type] ?? { displayName: bot.bot_type, color: '#6b7280', icon: <Bot size={16} />, desc: 'Bot', maxRate: 100 };
          const ratePct = Math.min((bot.orders_per_min / cfg.maxRate) * 100, 100);

          return (
            <div
              key={bot.bot_type}
              className={`${styles.card} ${!bot.active ? styles.inactive : ''}`}
              style={{ '--bot-color': cfg.color } as React.CSSProperties}
            >
              <div className={styles.cardTop}>
                <div className={styles.botIcon} style={{ color: cfg.color, background: `${cfg.color}18` }}>
                  {cfg.icon}
                </div>
                <div className={styles.botInfo}>
                  <span className={styles.botName}>{cfg.displayName}</span>
                  <span className={styles.botDesc}>{cfg.desc}</span>
                </div>
                <div className={styles.statusBadge}>
                  {bot.active
                    ? <><span className={styles.activeDot} style={{ background: cfg.color }} />Active</>
                    : <>Idle</>
                  }
                </div>
              </div>

              {/* Rate bar */}
              <div className={styles.rateSection}>
                <div className={styles.rateHeader}>
                  <span className={styles.rateLabel}>Orders/min</span>
                  <span className={styles.rateValue} style={{ color: cfg.color }}>
                    {bot.orders_per_min}
                  </span>
                </div>
                <div className={styles.rateBar}>
                  <div
                    className={styles.rateFill}
                    style={{
                      width: `${ratePct}%`,
                      background: cfg.color,
                      boxShadow: `0 0 6px ${cfg.color}60`,
                    }}
                  />
                </div>
              </div>

              {/* Last order */}
              <div className={styles.lastOrder}>
                <span className={styles.lastOrderLabel}>Last:</span>
                <span className={styles.lastOrderValue}>{bot.last_order || '—'}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
