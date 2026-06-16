#pragma once

#include "types.hpp"
#include <atomic>
#include <chrono>
#include <deque>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <unordered_map>

namespace exchange {

// ============================================================
// RiskLimits — per-user configurable limits
// ============================================================

struct RiskLimits {
    int    max_position_per_symbol = 1000;          // Shares per symbol
    double max_exposure_total      = 10'000'000.0;  // Total notional
    double fat_finger_multiplier   = 5.0;           // Reject if price > N × last_trade_price
    double circuit_breaker_pct     = 20.0;          // Halt if price moves > N% in window
    int    circuit_breaker_window_s = 300;           // 5-minute window
};

// ============================================================
// RiskEngine — called BEFORE matching to validate orders
// ============================================================

class RiskEngine {
public:
    explicit RiskEngine(RiskLimits default_limits = {});

    // Primary check — returns NONE if order should proceed
    RejectionReason check(const Order& order);

    // Called after every trade to update positions and last-trade tracking
    void on_trade(const ExecutedTrade& trade);

    // Admin: update limits for a specific user (or global default if user_id empty)
    void set_limits(const std::string& user_id, const RiskLimits& limits);
    RiskLimits get_limits(const std::string& user_id) const;

    // Admin: manually activate/deactivate circuit breaker for a symbol
    void halt_symbol(const std::string& symbol);
    void resume_symbol(const std::string& symbol);
    bool is_circuit_breaker_active(const std::string& symbol) const;

    // Update last known price for a symbol (used by fat-finger check)
    void update_last_price(const std::string& symbol, double price);

private:
    RejectionReason check_position(const Order& order,
                                    const RiskLimits& limits) const;
    RejectionReason check_exposure(const Order& order,
                                    const RiskLimits& limits) const;
    RejectionReason check_fat_finger(const Order& order,
                                      const RiskLimits& limits) const;
    RejectionReason check_circuit_breaker(const Order& order) const;

    // --------------------------------------------------------
    // State
    // --------------------------------------------------------

    RiskLimits default_limits_;

    // Per-user limits (empty = use default)
    mutable std::shared_mutex limits_mutex_;
    std::unordered_map<std::string, RiskLimits> user_limits_;

    // Positions: user_id → symbol → net position (buy=+, sell=-)
    mutable std::shared_mutex pos_mutex_;
    std::unordered_map<std::string,
        std::unordered_map<std::string, int>> positions_;

    // Open-order notional exposure: user_id → total notional
    mutable std::shared_mutex exp_mutex_;
    std::unordered_map<std::string, double> exposure_;

    // Last trade price per symbol
    mutable std::shared_mutex price_mutex_;
    std::unordered_map<std::string, double> last_price_;

    // Circuit breaker: symbol → deque of {timestamp_ns, price}
    // Used to detect >N% movement within the window.
    struct PriceTick {
        int64_t timestamp_ns;
        double  price;
    };
    mutable std::mutex cb_mutex_;
    std::unordered_map<std::string, std::deque<PriceTick>> price_history_;
    std::unordered_map<std::string, bool>                   cb_active_;
};

} // namespace exchange
