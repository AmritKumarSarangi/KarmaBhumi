#include "risk_engine.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>

namespace exchange {

// ============================================================
// Ctor
// ============================================================

RiskEngine::RiskEngine(RiskLimits default_limits)
    : default_limits_(std::move(default_limits)) {}

// ============================================================
// Main check — returns NONE to allow, or a rejection code
// ============================================================

RejectionReason RiskEngine::check(const Order& order) {
    if (order.quantity <= 0 || order.symbol.empty() || order.user_id.empty()) {
        return ::exchange::INVALID_ORDER;
    }

    // For market orders price can be 0; for limit orders price must be positive
    if (order.type == ::exchange::LIMIT && order.price <= 0.0) {
        return ::exchange::INVALID_ORDER;
    }

    // Retrieve this user's effective limits
    RiskLimits limits = [&] {
        std::shared_lock lk(limits_mutex_);
        auto it = user_limits_.find(order.user_id);
        return (it != user_limits_.end()) ? it->second : default_limits_;
    }();

    // 1. Circuit breaker check (symbol-level)
    if (auto r = check_circuit_breaker(order); r != ::exchange::REASON_NONE) return r;

    // 2. Fat-finger check (per-order price sanity)
    if (auto r = check_fat_finger(order, limits); r != ::exchange::REASON_NONE) return r;

    // 3. Position limit check
    if (auto r = check_position(order, limits); r != ::exchange::REASON_NONE) return r;

    // 4. Notional exposure check
    if (auto r = check_exposure(order, limits); r != ::exchange::REASON_NONE) return r;

    return ::exchange::REASON_NONE;
}

// ============================================================
// Position limit
// ============================================================

RejectionReason RiskEngine::check_position(const Order& order,
                                             const RiskLimits& limits) const {
    std::shared_lock lk(pos_mutex_);

    auto uid_it = positions_.find(order.user_id);
    if (uid_it == positions_.end()) return ::exchange::REASON_NONE;

    auto sym_it = uid_it->second.find(order.symbol);
    int current = (sym_it != uid_it->second.end()) ? sym_it->second : 0;

    int signed_qty = (order.side == ::exchange::BUY) ? order.quantity : -order.quantity;
    int projected  = std::abs(current + signed_qty);

    if (projected > limits.max_position_per_symbol) {
        return ::exchange::POSITION_LIMIT_EXCEEDED;
    }
    return ::exchange::REASON_NONE;
}

// ============================================================
// Exposure limit
// ============================================================

RejectionReason RiskEngine::check_exposure(const Order& order,
                                             const RiskLimits& limits) const {
    // For market orders, use last known price to estimate notional
    double price = order.price;
    if (price <= 0.0) {
        std::shared_lock lk(price_mutex_);
        auto it = last_price_.find(order.symbol);
        price = (it != last_price_.end()) ? it->second : 0.0;
    }

    double order_notional = price * static_cast<double>(order.quantity);

    std::shared_lock lk(exp_mutex_);
    auto it = exposure_.find(order.user_id);
    double current = (it != exposure_.end()) ? it->second : 0.0;

    if (current + order_notional > limits.max_exposure_total) {
        return ::exchange::EXPOSURE_LIMIT_EXCEEDED;
    }
    return ::exchange::REASON_NONE;
}

// ============================================================
// Fat-finger check
// ============================================================

RejectionReason RiskEngine::check_fat_finger(const Order& order,
                                               const RiskLimits& limits) const {
    if (order.price <= 0.0) return ::exchange::REASON_NONE; // Market orders skip

    double ref_price = 0.0;
    {
        std::shared_lock lk(price_mutex_);
        auto it = last_price_.find(order.symbol);
        if (it == last_price_.end()) return ::exchange::REASON_NONE; // No reference yet
        ref_price = it->second;
    }

    if (ref_price <= 0.0) return ::exchange::REASON_NONE;

    double ratio = order.price / ref_price;
    if (ratio > limits.fat_finger_multiplier || ratio < 1.0 / limits.fat_finger_multiplier) {
        return ::exchange::FAT_FINGER_DETECTED;
    }
    return ::exchange::REASON_NONE;
}

// ============================================================
// Circuit breaker check
// ============================================================

RejectionReason RiskEngine::check_circuit_breaker(const Order& order) const {
    std::lock_guard lk(cb_mutex_);

    auto cb_it = cb_active_.find(order.symbol);
    if (cb_it != cb_active_.end() && cb_it->second) {
        return ::exchange::CIRCUIT_BREAKER_ACTIVE;
    }
    return ::exchange::REASON_NONE;
}

// ============================================================
// on_trade — update positions, exposure, price history
// ============================================================

void RiskEngine::on_trade(const ExecutedTrade& trade) {
    // Update positions
    {
        std::unique_lock lk(pos_mutex_);
        positions_[trade.buyer_user_id][trade.symbol]  += trade.quantity;
        positions_[trade.seller_user_id][trade.symbol] -= trade.quantity;
    }

    // Update exposure (reduce for the completed portion)
    double notional = trade.price * static_cast<double>(trade.quantity);
    {
        std::unique_lock lk(exp_mutex_);
        auto& buyer_exp  = exposure_[trade.buyer_user_id];
        auto& seller_exp = exposure_[trade.seller_user_id];
        buyer_exp  = std::max(0.0, buyer_exp  - notional);
        seller_exp = std::max(0.0, seller_exp - notional);
    }

    // Update last price
    update_last_price(trade.symbol, trade.price);

    // Circuit breaker: record tick and check if price moved > N% in window
    {
        std::lock_guard lk(cb_mutex_);
        int64_t now_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                             std::chrono::system_clock::now().time_since_epoch()).count();

        auto& hist = price_history_[trade.symbol];
        hist.push_back({now_ns, trade.price});

        // Evict ticks older than the window
        // Use a cached default window of 300 seconds
        int64_t window_ns = static_cast<int64_t>(default_limits_.circuit_breaker_window_s)
                            * 1'000'000'000LL;
        while (!hist.empty() && (now_ns - hist.front().timestamp_ns) > window_ns) {
            hist.pop_front();
        }

        if (hist.size() >= 2) {
            double oldest_price = hist.front().price;
            double newest_price = hist.back().price;

            if (oldest_price > 0.0) {
                double pct_change = std::abs(newest_price - oldest_price) / oldest_price * 100.0;
                if (pct_change >= default_limits_.circuit_breaker_pct) {
                    if (!cb_active_[trade.symbol]) {
                        cb_active_[trade.symbol] = true;
                        std::cerr << "[RISK] Circuit breaker ACTIVATED for "
                                  << trade.symbol
                                  << " — price moved " << pct_change << "% in window\n";
                    }
                }
            }
        }
    }
}

// ============================================================
// Admin API
// ============================================================

void RiskEngine::set_limits(const std::string& user_id, const RiskLimits& limits) {
    if (user_id.empty()) {
        default_limits_ = limits;
        return;
    }
    std::unique_lock lk(limits_mutex_);
    user_limits_[user_id] = limits;
}

RiskLimits RiskEngine::get_limits(const std::string& user_id) const {
    std::shared_lock lk(limits_mutex_);
    auto it = user_limits_.find(user_id);
    return (it != user_limits_.end()) ? it->second : default_limits_;
}

void RiskEngine::halt_symbol(const std::string& symbol) {
    std::lock_guard lk(cb_mutex_);
    cb_active_[symbol] = true;
}

void RiskEngine::resume_symbol(const std::string& symbol) {
    std::lock_guard lk(cb_mutex_);
    cb_active_[symbol] = false;
    // Clear price history so the CB starts fresh
    price_history_[symbol].clear();
}

bool RiskEngine::is_circuit_breaker_active(const std::string& symbol) const {
    std::lock_guard lk(cb_mutex_);
    auto it = cb_active_.find(symbol);
    return (it != cb_active_.end()) && it->second;
}

void RiskEngine::update_last_price(const std::string& symbol, double price) {
    std::unique_lock lk(price_mutex_);
    last_price_[symbol] = price;
}

} // namespace exchange
