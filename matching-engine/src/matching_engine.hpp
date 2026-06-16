#pragma once

#include "order_book.hpp"
#include "types.hpp"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <queue>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace exchange {

// ============================================================
// Latency tracker — maintains a fixed-capacity ring of
// nanosecond samples and computes percentiles on demand.
// ============================================================

class LatencyTracker {
public:
    explicit LatencyTracker(size_t capacity = 1'000'000);

    void record(int64_t ns);

    // Percentile 0.0–1.0. Returns 0 if no samples.
    double percentile(double p) const;
    double p50() const { return percentile(0.50); }
    double p95() const { return percentile(0.95); }
    double p99() const { return percentile(0.99); }
    double p999() const { return percentile(0.999); }
    size_t count() const;

private:
    mutable std::mutex   mu_;
    std::vector<int64_t> samples_;
    size_t               head_{0};
    size_t               capacity_;
    bool                 full_{false};
};

// ============================================================
// MatchingEngine
// ============================================================

class MatchingEngine {
public:
    // Callbacks wired at construction time
    using TradeCallback      = std::function<void(const ExecutedTrade&)>;
    using BookUpdateCallback = std::function<void(const BookSnapshot&)>;

    explicit MatchingEngine(std::vector<std::string> symbols);
    ~MatchingEngine();

    // Starts worker + GTT-expiry + metrics threads
    void start();
    void stop();

    // Submit an order (thread-safe; enqueues for processing)
    void submit_order(Order order);

    // Cancel an order (processed immediately under the book's lock)
    bool cancel_order(const std::string& order_id,
                      const std::string& symbol,
                      const std::string& user_id);

    // Book snapshot for a symbol
    BookSnapshot get_book_snapshot(const std::string& symbol, int depth = 10) const;

    // Register callbacks
    void set_trade_callback(TradeCallback cb)           { on_trade_   = std::move(cb); }
    void set_book_update_callback(BookUpdateCallback cb){ on_book_update_ = std::move(cb); }

    // Halt / resume a symbol (circuit breaker / admin)
    void halt_symbol(const std::string& symbol);
    void resume_symbol(const std::string& symbol);
    bool is_halted(const std::string& symbol) const;

    // Atomic counters exposed for metrics (values)
    int64_t total_orders()   const { return total_orders_.load();   }
    int64_t total_trades()   const { return total_trades_.load();   }
    int64_t total_cancels()  const { return total_cancels_.load();  }
    int64_t total_rejected() const { return total_rejected_.load(); }

    // Atomic references for MetricsServer
    const std::atomic<int64_t>& atomic_total_orders()   const { return total_orders_;   }
    const std::atomic<int64_t>& atomic_total_trades()   const { return total_trades_;   }
    const std::atomic<int64_t>& atomic_total_cancels()  const { return total_cancels_;  }
    const std::atomic<int64_t>& atomic_total_rejected() const { return total_rejected_; }

    // Latency percentiles
    double p50_ns()  const { return latency_.p50();  }
    double p95_ns()  const { return latency_.p95();  }
    double p99_ns()  const { return latency_.p99();  }
    double p999_ns() const { return latency_.p999(); }

    // Per-symbol metrics
    struct SymbolStats {
        std::atomic<int64_t> order_count{0};
        std::atomic<int64_t> trade_count{0};
        std::atomic<int64_t> volume{0};
    };
    const std::unordered_map<std::string, std::unique_ptr<SymbolStats>>& symbol_stats() const {
        return symbol_stats_;
    }

    // Synchronous match — used by gRPC server for immediate result
    MatchResult process_order_sync(Order order);

private:
    // Internal processing
    MatchResult process_order(Order& order);

    MatchResult match_limit(Order& order);
    MatchResult match_market(Order& order);
    MatchResult match_ioc(Order& order);
    MatchResult match_fok(Order& order);
    MatchResult match_stop(Order& order);
    MatchResult match_gtt(Order& order);

    // Core crossing loop; fills the incoming order against the book.
    // max_qty: stop after consuming this many shares (used by FOK check).
    // Returns list of trades generated.
    std::vector<ExecutedTrade> generate_trades(Order& incoming, OrderBook& book, int max_qty = INT32_MAX);

    // Check FOK fillability without touching the book
    bool is_fully_fillable(const Order& order, const OrderBook& book) const;

    // Trigger stop orders whose stop price has been crossed
    void check_stop_triggers(const std::string& symbol, double last_trade_price);

    // GTT expiry loop (separate thread)
    void gtt_expiry_loop();

    // Worker thread entry
    void worker_loop();

    // Book lookup helpers
    OrderBook* get_book(const std::string& symbol);
    const OrderBook* get_book(const std::string& symbol) const;

    std::string generate_trade_id();

    // --------------------------------------------------------
    // Data members
    // --------------------------------------------------------

    std::vector<std::string> symbols_;

    // Per-symbol order books
    std::unordered_map<std::string, std::unique_ptr<OrderBook>> books_;

    // Per-symbol halt flags
    mutable std::shared_mutex               halt_mutex_;
    std::unordered_map<std::string, bool>   halted_;

    // Pending stop orders: symbol → list of Orders
    mutable std::mutex                                              stop_mutex_;
    std::unordered_map<std::string, std::vector<Order>>            stop_orders_;

    // GTT orders: expiry_ms → list of Orders
    mutable std::mutex                                              gtt_mutex_;
    std::multimap<int64_t, Order>                                   gtt_orders_;

    // Last trade price per symbol (for circuit breaker / stop triggers)
    mutable std::mutex                                              price_mutex_;
    std::unordered_map<std::string, double>                        last_price_;

    // Inbound order queue
    mutable std::mutex             queue_mutex_;
    std::condition_variable        queue_cv_;
    std::queue<Order>              order_queue_;

    // Callbacks
    TradeCallback       on_trade_;
    BookUpdateCallback  on_book_update_;

    // Threads
    std::thread  worker_thread_;
    std::thread  gtt_thread_;
    std::atomic<bool> running_{false};

    // Counters
    std::atomic<int64_t> total_orders_{0};
    std::atomic<int64_t> total_trades_{0};
    std::atomic<int64_t> total_cancels_{0};
    std::atomic<int64_t> total_rejected_{0};

    std::atomic<int64_t> trade_seq_{0};

    LatencyTracker latency_;

    // Per-symbol stats
    std::unordered_map<std::string, std::unique_ptr<SymbolStats>> symbol_stats_;

    // Start timestamp for uptime
    std::chrono::steady_clock::time_point start_time_;
};

} // namespace exchange
