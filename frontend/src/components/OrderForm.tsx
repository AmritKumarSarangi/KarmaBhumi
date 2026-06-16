import React, { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { Minus, Plus, Loader2 } from 'lucide-react';
import { useMarket } from '../App';
import { api, PlaceOrderPayload, OrderType, OrderSide } from '../api/client';
import styles from './OrderForm.module.css';

const SYMBOLS = ['AAPL', 'GOOGL', 'TSLA', 'MSFT', 'AMZN'];
const ORDER_TYPES: OrderType[] = ['LIMIT', 'MARKET', 'IOC', 'FOK', 'STOP_LOSS', 'GTT'];

const PRICE_SHOWN_FOR: OrderType[] = ['LIMIT', 'IOC', 'FOK', 'GTT'];
const STOP_SHOWN_FOR: OrderType[]  = ['STOP_LOSS'];
const EXPIRE_SHOWN_FOR: OrderType[] = ['GTT'];

export default function OrderForm() {
  const { symbol: contextSymbol, setSymbol } = useMarket();

  const [side, setSide] = useState<OrderSide>('BUY');
  const [orderType, setOrderType] = useState<OrderType>('LIMIT');
  const [price, setPrice] = useState<string>('');
  const [stopPrice, setStopPrice] = useState<string>('');
  const [quantity, setQuantity] = useState<number>(100);
  const [expireAt, setExpireAt] = useState<string>('');
  const [loading, setLoading] = useState(false);

  const showPrice  = PRICE_SHOWN_FOR.includes(orderType);
  const showStop   = STOP_SHOWN_FOR.includes(orderType);
  const showExpire = EXPIRE_SHOWN_FOR.includes(orderType);

  const estimatedValue = showPrice && price
    ? (parseFloat(price) * quantity).toLocaleString('en-US', { style: 'currency', currency: 'USD' })
    : orderType === 'MARKET'
    ? `~Market × ${quantity}`
    : null;

  const handleQtyChange = (delta: number) => {
    setQuantity(q => Math.max(1, q + delta));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;

    const payload: PlaceOrderPayload = {
      symbol: contextSymbol,
      side,
      order_type: orderType,
      quantity,
      ...(showPrice && price   ? { price: parseFloat(price) } : {}),
      ...(showStop  && stopPrice ? { stop_price: parseFloat(stopPrice) } : {}),
      ...(showExpire && expireAt  ? { expire_at: new Date(expireAt).toISOString() } : {}),
    };

    setLoading(true);
    try {
      await api.orders.place(payload);
      toast.success(`${side.toUpperCase()} ${quantity} ${contextSymbol} @ ${orderType} submitted`);
      // Reset form partials
      setPrice('');
      setStopPrice('');
      setQuantity(100);
    } catch (err: any) {
      let msg = err?.response?.data?.detail || 'Order failed';
      if (Array.isArray(msg)) {
        msg = msg.map(m => `${m.loc.join('.')}: ${m.msg}`).join(', ');
      } else if (typeof msg === 'object') {
        msg = JSON.stringify(msg);
      }
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.title}>Place Order</span>
        <select
          className={styles.symbolSelect}
          value={contextSymbol}
          onChange={e => setSymbol(e.target.value)}
        >
          {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      <form onSubmit={handleSubmit} className={styles.form}>
        {/* Side Toggle */}
        <div className={styles.sideToggle}>
          <button
            type="button"
            className={`${styles.sideBtn} ${side === 'BUY' ? styles.sideBtnBuy : ''}`}
            onClick={() => setSide('BUY')}
          >
            BUY
          </button>
          <button
            type="button"
            className={`${styles.sideBtn} ${side === 'SELL' ? styles.sideBtnSell : ''}`}
            onClick={() => setSide('SELL')}
          >
            SELL
          </button>
        </div>

        {/* Order Type */}
        <div className={styles.field}>
          <label className={styles.label}>Order Type</label>
          <select
            className={`input ${styles.select}`}
            value={orderType}
            onChange={e => setOrderType(e.target.value as OrderType)}
          >
            {ORDER_TYPES.map(t => (
              <option key={t} value={t}>{t.replace('_', ' ')}</option>
            ))}
          </select>
        </div>

        {/* Price */}
        {showPrice && (
          <div className={styles.field}>
            <label className={styles.label}>Limit Price</label>
            <div className={styles.priceInput}>
              <span className={styles.pricePrefix}>$</span>
              <input
                type="number"
                className={`input ${styles.numInput}`}
                placeholder="0.00"
                value={price}
                onChange={e => setPrice(e.target.value)}
                min="0.01"
                step="0.01"
                required
              />
            </div>
          </div>
        )}

        {/* Stop Price */}
        {showStop && (
          <div className={styles.field}>
            <label className={styles.label}>Stop Price</label>
            <div className={styles.priceInput}>
              <span className={styles.pricePrefix}>$</span>
              <input
                type="number"
                className={`input ${styles.numInput}`}
                placeholder="0.00"
                value={stopPrice}
                onChange={e => setStopPrice(e.target.value)}
                min="0.01"
                step="0.01"
                required
              />
            </div>
          </div>
        )}

        {/* Quantity */}
        <div className={styles.field}>
          <label className={styles.label}>Quantity</label>
          <div className={styles.qtyControl}>
            <button type="button" className={styles.qtyBtn} onClick={() => handleQtyChange(-10)}>
              <Minus size={13} />
            </button>
            <input
              type="number"
              className={`input ${styles.qtyInput}`}
              value={quantity}
              onChange={e => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
              min="1"
              required
            />
            <button type="button" className={styles.qtyBtn} onClick={() => handleQtyChange(10)}>
              <Plus size={13} />
            </button>
          </div>
        </div>

        {/* GTT Expire */}
        {showExpire && (
          <div className={styles.field}>
            <label className={styles.label}>Expire At</label>
            <input
              type="datetime-local"
              className="input"
              value={expireAt}
              onChange={e => setExpireAt(e.target.value)}
              required
            />
          </div>
        )}

        {/* Preview */}
        {estimatedValue && (
          <div className={styles.preview}>
            <span className={styles.previewLabel}>Est. Value</span>
            <span className={styles.previewValue}>{estimatedValue}</span>
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          className={`${styles.submitBtn} ${side === 'BUY' ? styles.submitBuy : styles.submitSell}`}
          disabled={loading}
        >
          {loading
            ? <><Loader2 size={15} className="animate-spin" /> Processing…</>
            : `${side.toUpperCase()} ${contextSymbol}`
          }
        </button>
      </form>
    </div>
  );
}
