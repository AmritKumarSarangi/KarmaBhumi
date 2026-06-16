#include "matching_engine.hpp"
#include <algorithm>
#include <chrono>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>

namespace exchange {

// ============================================================
// LatencyTracker
// ============================================================

LatencyTracker::LatencyTracker(size_t capacity)
    : capacity_(capacity) {
    samples_.resize(capacity, 0);
}

void LatencyTracker::record(int64_t ns) {
    std::lock_guard lk(mu_);
    samples_[head_] = ns;
    head_ = (head_ + 1) % capacity_;
    if (head_ == 0) full_ = true;
}

double LatencyTracker::percentile(double p) const {
    std::lock_guard lk(mu_);
    size_t sz = full_ ? capacity_ : head_;
    if (sz == 0) return 0.0;

    std::vector<int64_t> tmp(samples_.begin(),
                              samples_.begin() + static_cast<ptrdiff_t>(sz));
    std::sort(tmp.begin(), tmp.end());

    size_t idx = static_cast<size_t>(p * static_cast<double>(sz - 1));
    if (idx >= sz) idx = sz - 1;
    return static_cast<double>(tmp[idx]);
}

size_t LatencyTracker::count() const {
    std::lock_guard lk(mu_);
    return full_ ? capacity_ : head_;
}

// ============================================================
// MatchingEngine — ctor/dtor
// ============================================================

MatchingEngine::MatchingEngine(std::vector<std::string> symbols)
    : symbols_(std::move(symbols)),
      start_time_(std::chrono::steady_clock::now()) {

    for (const auto& sym : symbols_) {
        books_[sym]        = std::make_unique<OrderBook>(sym);
        halted_[sym]       = false;
        last_price_[sym]   = 0.0;
        stop_orders_[sym]  = {};
        symbol_stats_[sym] = std::make_unique<SymbolStats>();
    }
}

MatchingEngine::~MatchingEngine() { stop(); }

void MatchingEngine::start() {
    running_ = true;
    worker_thread_ = std::thread([this] { worker_loop(); });
    gtt_thread_    = std::thread([this] { gtt_expiry_loop(); });
}

void MatchingEngine::stop() {
    running_ = false;
    queue_cv_.notify_all();
    if (worker_thread_.joinable()) worker_thread_.join();
    if (gtt_thread_.joinable())    gtt_thread_.join();
}

// ============================================================
// Submit / Cancel
// ============================================================

void MatchingEngine::submit_order(Order order) {
    {
        std::lock_guard lk(queue_mutex_);
        order_queue_.push(std::move(order));
    }
    queue_cv_.notify_one();
}

bool MatchingEngine::cancel_order(const std::string& order_id,
                                   const std::string& symbol,
                                   const std::string& /*user_id*/) {
    auto* book = get_book(symbol);
    if (!book) return false;

    int qty = book->cancel_order(order_id);
    if (qty > 0) {
        total_cancels_.fetch_add(1, std::memory_order_relaxed);
        if (on_book_update_) on_book_update_(book->get_snapshot(10));
        return true;
    }
    return false;
}

// ============================================================
// Worker loop
// ============================================================

void MatchingEngine::worker_loop() {
    while (running_) {
        Order order;
        {
            std::unique_lock lk(queue_mutex_);
            queue_cv_.wait(lk, [this] {
                return !order_queue_.empty() || !running_;
            });
            if (!running_ && order_queue_.empty()) break;
            order = std::move(order_queue_.front());
            order_queue_.pop();
        }
        process_order(order);
    }
}

// ============================================================
// GTT expiry loop
// ============================================================

void MatchingEngine::gtt_expiry_loop() {
    while (running_) {
        std::this_thread::sleep_for(std::chrono::seconds(1));

        int64_t now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                             std::chrono::system_clock::now().time_since_epoch())
                             .count();

        std::vector<Order> expired;
        {
            std::lock_guard lk(gtt_mutex_);
            auto it = gtt_orders_.begin();
            while (it != gtt_orders_.end() && it->first <= now_ms) {
                expired.push_back(it->second);
                it = gtt_orders_.erase(it);
            }
        }

        for (auto& exp : expired) {
            auto* book = get_book(exp.symbol);
            if (!book) continue;
            int qty = book->cancel_order(exp.order_id);
            if (qty > 0) {
                total_cancels_.fetch_add(1, std::memory_order_relaxed);
                if (on_book_update_) on_book_update_(book->get_snapshot(10));
            }
        }
    }
}

// ============================================================
// Synchronous entry point (used by gRPC server)
// ============================================================

MatchResult MatchingEngine::process_order_sync(Order order) {
    return process_order(order);
}

// ============================================================
// Internal dispatch
// ============================================================

MatchResult MatchingEngine::process_order(Order& order) {
    auto t0 = std::chrono::steady_clock::now();

    total_orders_.fetch_add(1, std::memory_order_relaxed);

    // Initialise remaining
    if (order.remaining == 0) order.remaining = order.quantity;

    // Check halt
    {
        std::shared_lock lk(halt_mutex_);
        auto it = halted_.find(order.symbol);
        if (it != halted_.end() && it->second) {
            total_rejected_.fetch_add(1, std::memory_order_relaxed);
            MatchResult r;
            r.status        = ::exchange::REJECTED;
            r.rejection     = ::exchange::MARKET_HALTED;
            r.rejection_msg = "Market halted for " + order.symbol;
            return r;
        }
    }

    MatchResult result;
    switch (order.type) {
        case ::exchange::LIMIT:      result = match_limit(order);   break;
        case ::exchange::MARKET:     result = match_market(order);  break;
        case ::exchange::IOC:        result = match_ioc(order);     break;
        case ::exchange::FOK:        result = match_fok(order);     break;
        case ::exchange::STOP_LOSS:
        case ::exchange::STOP_LIMIT: result = match_stop(order);    break;
        case ::exchange::GTT:        result = match_gtt(order);     break;
        default:
            total_rejected_.fetch_add(1, std::memory_order_relaxed);
            result.status    = ::exchange::REJECTED;
            result.rejection = ::exchange::INVALID_ORDER;
            break;
    }

    auto t1 = std::chrono::steady_clock::now();
    int64_t latency = std::chrono::duration_cast<std::chrono::nanoseconds>(t1 - t0).count();
    latency_.record(latency);
    result.matching_latency_ns = latency;

    if (auto it = symbol_stats_.find(order.symbol); it != symbol_stats_.end()) {
        it->second->order_count.fetch_add(1, std::memory_order_relaxed);
    }

    return result;
}

// ============================================================
// LIMIT
// ============================================================

MatchResult MatchingEngine::match_limit(Order& order) {
    auto* book = get_book(order.symbol);
    if (!book) {
        total_rejected_.fetch_add(1, std::memory_order_relaxed);
        MatchResult r;
        r.status    = ::exchange::REJECTED;
        r.rejection = ::exchange::SYMBOL_NOT_FOUND;
        return r;
    }

    std::vector<ExecutedTrade> trades = generate_trades(order, *book);

    MatchResult result;
    result.trades    = std::move(trades);
    result.filled_qty    = order.filled_qty;
    result.remaining_qty = order.remaining;

    if (order.remaining > 0) {
        order.status = (order.filled_qty > 0) ? ::exchange::PARTIAL_FILL
                                               : ::exchange::ACCEPTED;
        book->add_order(order);
        result.status = order.status;
    } else {
        result.status = ::exchange::FILLED;
        order.status  = ::exchange::FILLED;
    }

    if (!result.trades.empty()) {
        double notional = 0.0;
        for (const auto& t : result.trades) notional += t.price * t.quantity;
        result.avg_fill_price = notional / result.filled_qty;
    }

    if (on_book_update_) on_book_update_(book->get_snapshot(10));
    return result;
}

// ============================================================
// MARKET
// ============================================================

MatchResult MatchingEngine::match_market(Order& order) {
    auto* book = get_book(order.symbol);
    if (!book) {
        total_rejected_.fetch_add(1, std::memory_order_relaxed);
        MatchResult r;
        r.status    = ::exchange::REJECTED;
        r.rejection = ::exchange::SYMBOL_NOT_FOUND;
        return r;
    }

    // Effective price: aggressive enough to sweep the entire book
    order.price = (order.side == ::exchange::BUY) ? 1e12 : 0.0;

    std::vector<ExecutedTrade> trades = generate_trades(order, *book);

    MatchResult result;
    result.trades        = std::move(trades);
    result.filled_qty    = order.filled_qty;
    result.remaining_qty = order.remaining;
    result.status        = (order.remaining == 0) ? ::exchange::FILLED
                         : (order.filled_qty  > 0) ? ::exchange::PARTIAL_FILL
                                                    : ::exchange::ACCEPTED;

    if (!result.trades.empty()) {
        double notional = 0.0;
        for (const auto& t : result.trades) notional += t.price * t.quantity;
        result.avg_fill_price = notional / result.filled_qty;
    }

    if (on_book_update_) on_book_update_(book->get_snapshot(10));
    return result;
}

// ============================================================
// IOC
// ============================================================

MatchResult MatchingEngine::match_ioc(Order& order) {
    auto* book = get_book(order.symbol);
    if (!book) {
        total_rejected_.fetch_add(1, std::memory_order_relaxed);
        MatchResult r;
        r.status    = ::exchange::REJECTED;
        r.rejection = ::exchange::SYMBOL_NOT_FOUND;
        return r;
    }

    std::vector<ExecutedTrade> trades = generate_trades(order, *book);

    MatchResult result;
    result.trades        = std::move(trades);
    result.filled_qty    = order.filled_qty;
    result.remaining_qty = 0;  // Remainder is always discarded

    if (order.filled_qty == 0) {
        result.status = ::exchange::CANCELLED;
    } else if (order.remaining == 0) {
        result.status = ::exchange::FILLED;
    } else {
        result.status = ::exchange::PARTIAL_FILL;
        total_cancels_.fetch_add(1, std::memory_order_relaxed);
    }

    if (!result.trades.empty()) {
        double notional = 0.0;
        for (const auto& t : result.trades) notional += t.price * t.quantity;
        result.avg_fill_price = notional / result.filled_qty;
    }

    if (on_book_update_) on_book_update_(book->get_snapshot(10));
    return result;
}

// ============================================================
// FOK
// ============================================================

MatchResult MatchingEngine::match_fok(Order& order) {
    auto* book = get_book(order.symbol);
    if (!book) {
        total_rejected_.fetch_add(1, std::memory_order_relaxed);
        MatchResult r;
        r.status    = ::exchange::REJECTED;
        r.rejection = ::exchange::SYMBOL_NOT_FOUND;
        return r;
    }

    if (!is_fully_fillable(order, *book)) {
        total_rejected_.fetch_add(1, std::memory_order_relaxed);
        MatchResult r;
        r.status        = ::exchange::REJECTED;
        r.rejection     = ::exchange::FOK_NOT_FILLABLE;
        r.rejection_msg = "FOK order cannot be fully filled";
        r.remaining_qty = order.quantity;
        return r;
    }

    std::vector<ExecutedTrade> trades = generate_trades(order, *book);

    MatchResult result;
    result.trades        = std::move(trades);
    result.filled_qty    = order.filled_qty;
    result.remaining_qty = order.remaining;
    result.status        = (order.remaining == 0) ? ::exchange::FILLED
                                                   : ::exchange::CANCELLED;

    if (!result.trades.empty()) {
        double notional = 0.0;
        for (const auto& t : result.trades) notional += t.price * t.quantity;
        result.avg_fill_price = notional / result.filled_qty;
    }

    if (on_book_update_) on_book_update_(book->get_snapshot(10));
    return result;
}

// ============================================================
// STOP_LOSS / STOP_LIMIT
// ============================================================

MatchResult MatchingEngine::match_stop(Order& order) {
    {
        std::lock_guard lk(stop_mutex_);
        stop_orders_[order.symbol].push_back(order);
    }
    MatchResult result;
    result.status        = ::exchange::PENDING;
    result.remaining_qty = order.quantity;
    return result;
}

// ============================================================
// GTT
// ============================================================

MatchResult MatchingEngine::match_gtt(Order& order) {
    auto result = match_limit(order);

    if (result.status != ::exchange::FILLED && order.expire_time_ms > 0) {
        std::lock_guard lk(gtt_mutex_);
        gtt_orders_.emplace(order.expire_time_ms, order);
    }

    return result;
}

// ============================================================
// Core crossing loop — price-time priority
// ============================================================

std::vector<ExecutedTrade> MatchingEngine::generate_trades(Order& incoming,
                                                    OrderBook& book,
                                                    int /*max_qty*/) {
    std::vector<ExecutedTrade> trades;
    std::unique_lock lock(book.mutex());

    bool is_buy = (incoming.side == ::exchange::BUY);

    while (incoming.remaining > 0) {
        if (is_buy) {
            auto& asks_ref = book.asks();
            if (asks_ref.empty()) break;

            auto it_level = asks_ref.begin();
            double best_ask = it_level->first;

            // Price check for limit orders
            if (incoming.type != ::exchange::MARKET && incoming.price < best_ask) break;

            auto& dq = it_level->second;
            if (dq.empty()) { asks_ref.erase(it_level); continue; }

            Order& resting  = dq.front();
            int fill_qty    = std::min(incoming.remaining, resting.remaining);

            ExecutedTrade t;
            t.trade_id       = generate_trade_id();
            t.symbol         = incoming.symbol;
            t.price          = best_ask;
            t.quantity       = fill_qty;
            t.buy_order_id   = incoming.order_id;
            t.sell_order_id  = resting.order_id;
            t.buyer_user_id  = incoming.user_id;
            t.seller_user_id = resting.user_id;
            t.timestamp_ns   = std::chrono::duration_cast<std::chrono::nanoseconds>(
                                   std::chrono::system_clock::now().time_since_epoch()).count();

            incoming.filled_qty += fill_qty;
            incoming.remaining  -= fill_qty;

            resting.filled_qty  += fill_qty;
            resting.remaining   -= fill_qty;
            resting.status       = (resting.remaining == 0) ? ::exchange::FILLED
                                                             : ::exchange::PARTIAL_FILL;

            if (resting.remaining == 0) {
                book.order_index_no_lock_erase(resting.order_id);
                dq.pop_front();
                if (dq.empty()) asks_ref.erase(it_level);
            }

            trades.push_back(std::move(t));
            total_trades_.fetch_add(1, std::memory_order_relaxed);

        } else {
            // SELL — match against bids (descending)
            auto& bids_ref = book.bids();
            if (bids_ref.empty()) break;

            auto it_level = bids_ref.begin();
            double best_bid = it_level->first;

            if (incoming.type != ::exchange::MARKET && incoming.price > best_bid) break;

            auto& dq = it_level->second;
            if (dq.empty()) { bids_ref.erase(it_level); continue; }

            Order& resting  = dq.front();
            int fill_qty    = std::min(incoming.remaining, resting.remaining);

            ExecutedTrade t;
            t.trade_id       = generate_trade_id();
            t.symbol         = incoming.symbol;
            t.price          = best_bid;
            t.quantity       = fill_qty;
            t.buy_order_id   = resting.order_id;
            t.sell_order_id  = incoming.order_id;
            t.buyer_user_id  = resting.user_id;
            t.seller_user_id = incoming.user_id;
            t.timestamp_ns   = std::chrono::duration_cast<std::chrono::nanoseconds>(
                                   std::chrono::system_clock::now().time_since_epoch()).count();

            incoming.filled_qty += fill_qty;
            incoming.remaining  -= fill_qty;

            resting.filled_qty  += fill_qty;
            resting.remaining   -= fill_qty;
            resting.status       = (resting.remaining == 0) ? ::exchange::FILLED
                                                             : ::exchange::PARTIAL_FILL;

            if (resting.remaining == 0) {
                book.order_index_no_lock_erase(resting.order_id);
                dq.pop_front();
                if (dq.empty()) bids_ref.erase(it_level);
            }

            trades.push_back(std::move(t));
            total_trades_.fetch_add(1, std::memory_order_relaxed);
        }
    }

    lock.unlock();

    // Post-trade updates (no book lock needed)
    if (!trades.empty()) {
        double last_px = trades.back().price;

        {
            std::lock_guard lk(price_mutex_);
            last_price_[incoming.symbol] = last_px;
        }

        // Update per-symbol stats
        if (auto sit = symbol_stats_.find(incoming.symbol); sit != symbol_stats_.end()) {
            int64_t vol = 0;
            for (const auto& t : trades) vol += t.quantity;
            sit->second->trade_count.fetch_add(
                static_cast<int64_t>(trades.size()), std::memory_order_relaxed);
            sit->second->volume.fetch_add(vol, std::memory_order_relaxed);
        }

        // Fire callbacks
        for (const auto& t : trades) {
            if (on_trade_) on_trade_(t);
        }

        // Check if any stop orders should trigger
        check_stop_triggers(incoming.symbol, last_px);
    }

    return trades;
}

// ============================================================
// FOK fillability check (read-only)
// ============================================================

bool MatchingEngine::is_fully_fillable(const Order& order, const OrderBook& book) const {
    // Take a shared lock on the book
    std::shared_lock lock(const_cast<std::shared_mutex&>(
        const_cast<OrderBook&>(book).mutex()));

    int needed  = order.quantity;
    bool is_buy = (order.side == ::exchange::BUY);

    if (is_buy) {
        for (const auto& [price, dq] : book.asks()) {
            if (order.type != ::exchange::MARKET && price > order.price) break;
            for (const auto& o : dq) needed -= o.remaining;
            if (needed <= 0) return true;
        }
    } else {
        for (const auto& [price, dq] : book.bids()) {
            if (order.type != ::exchange::MARKET && price < order.price) break;
            for (const auto& o : dq) needed -= o.remaining;
            if (needed <= 0) return true;
        }
    }
    return needed <= 0;
}

// ============================================================
// Stop trigger
// ============================================================

void MatchingEngine::check_stop_triggers(const std::string& symbol,
                                          double last_trade_price) {
    std::vector<Order> triggered;
    {
        std::lock_guard lk(stop_mutex_);
        auto it = stop_orders_.find(symbol);
        if (it == stop_orders_.end()) return;

        auto& sv = it->second;
        sv.erase(std::remove_if(sv.begin(), sv.end(), [&](const Order& o) {
            bool fire = false;
            if (o.side == ::exchange::BUY  && last_trade_price >= o.stop_price) fire = true;
            if (o.side == ::exchange::SELL && last_trade_price <= o.stop_price) fire = true;
            if (fire) triggered.push_back(o);
            return fire;
        }), sv.end());
    }

    for (auto& trig : triggered) {
        if (trig.type == ::exchange::STOP_LOSS) {
            trig.type  = ::exchange::MARKET;
            trig.price = 0.0;
        } else {
            // STOP_LIMIT → limit at stop_price
            trig.type  = ::exchange::LIMIT;
            trig.price = trig.stop_price;
        }
        trig.remaining = trig.quantity - trig.filled_qty;
        submit_order(trig);
    }
}

// ============================================================
// Halt / Resume
// ============================================================

void MatchingEngine::halt_symbol(const std::string& symbol) {
    std::unique_lock lk(halt_mutex_);
    halted_[symbol] = true;
}

void MatchingEngine::resume_symbol(const std::string& symbol) {
    std::unique_lock lk(halt_mutex_);
    halted_[symbol] = false;
}

bool MatchingEngine::is_halted(const std::string& symbol) const {
    std::shared_lock lk(halt_mutex_);
    auto it = halted_.find(symbol);
    return (it != halted_.end()) && it->second;
}

// ============================================================
// Snapshot
// ============================================================

BookSnapshot MatchingEngine::get_book_snapshot(const std::string& symbol,
                                                     int depth) const {
    const auto* book = get_book(symbol);
    if (!book) return BookSnapshot{};
    return book->get_snapshot(depth);
}

// ============================================================
// Internal helpers
// ============================================================

OrderBook* MatchingEngine::get_book(const std::string& symbol) {
    auto it = books_.find(symbol);
    return (it != books_.end()) ? it->second.get() : nullptr;
}

const OrderBook* MatchingEngine::get_book(const std::string& symbol) const {
    auto it = books_.find(symbol);
    return (it != books_.end()) ? it->second.get() : nullptr;
}

std::string MatchingEngine::generate_trade_id() {
    int64_t seq = trade_seq_.fetch_add(1, std::memory_order_relaxed);
    return "TRD-" + std::to_string(seq);
}

} // namespace exchange
