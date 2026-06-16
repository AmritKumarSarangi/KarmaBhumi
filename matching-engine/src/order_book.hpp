#pragma once

#include "types.hpp"
#include <atomic>
#include <deque>
#include <functional>
#include <map>
#include <optional>
#include <shared_mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace exchange {

// ============================================================
// OrderBook — per-symbol, thread-safe with shared_mutex
// Bids: descending price (highest first)
// Asks: ascending price (lowest first)
// Within each price level: FIFO (deque)
// ============================================================

class OrderBook {
public:
    explicit OrderBook(std::string symbol);

    // Returns false if order_id already exists
    bool add_order(const Order& order);

    // Returns the cancelled quantity (0 if not found or already filled)
    int cancel_order(const std::string& order_id);

    // Snapshot of the top N price levels on each side
    BookSnapshot get_snapshot(int depth = 10) const;

    // Best prices (returns 0.0 if side is empty)
    double get_best_bid() const;
    double get_best_ask() const;

    // Sequence number incremented on every book change
    int64_t sequence_number() const { return seq_num_.load(std::memory_order_relaxed); }

    const std::string& symbol() const { return symbol_; }

    // --------------------------------------------------------
    // Matching helpers — called only by MatchingEngine (which
    // holds the write lock via pop_top_bid / pop_top_ask)
    // --------------------------------------------------------

    // Peek at the front order of the best bid/ask level (read lock held externally)
    std::optional<Order> peek_best_bid() const;
    std::optional<Order> peek_best_ask() const;

    // Consume qty from the front of the best bid / ask level.
    // Removes the order if fully consumed.
    // Returns the order that was at the front (before consumption).
    // Caller must hold unique (write) lock on book_mutex_.
    Order consume_from_bid(int qty);
    Order consume_from_ask(int qty);

    // Accessors for matching engine to use scoped_lock externally
    std::shared_mutex& mutex() { return book_mutex_; }

    // Called by MatchingEngine which already holds the unique_lock on book_mutex_
    // to erase an order from the index without re-acquiring the lock.
    void order_index_no_lock_erase(const std::string& order_id) {
        order_index_.erase(order_id);
    }

    // Raw access needed by matching engine under lock
    std::map<double, std::deque<Order>, std::greater<double>>& bids() { return bids_; }
    std::map<double, std::deque<Order>>& asks() { return asks_; }
    const std::map<double, std::deque<Order>, std::greater<double>>& bids() const { return bids_; }
    const std::map<double, std::deque<Order>>& asks() const { return asks_; }

    // Lookup by order_id (read)
    std::optional<Order> find_order(const std::string& order_id) const;

    // Total active quantity on each side (for metrics)
    int bid_total_qty() const;
    int ask_total_qty() const;
    int bid_depth() const;
    int ask_depth() const;

private:
    void remove_from_index(const std::string& order_id);

    std::string symbol_;

    // Price-time priority maps
    std::map<double, std::deque<Order>, std::greater<double>> bids_;  // descending
    std::map<double, std::deque<Order>>                        asks_;  // ascending

    // Fast lookup by order_id → {price, side} for O(1) cancel
    struct OrderLocation {
        double price;
        int    side;
    };
    std::unordered_map<std::string, OrderLocation> order_index_;

    mutable std::shared_mutex book_mutex_;
    std::atomic<int64_t>      seq_num_{0};
};

} // namespace exchange
