#include "order_book.hpp"
#include <algorithm>
#include <chrono>
#include <numeric>
#include <stdexcept>
#include <mutex>

namespace exchange {

OrderBook::OrderBook(std::string symbol) : symbol_(std::move(symbol)) {}

bool OrderBook::add_order(const Order& order) {
    std::unique_lock lock(book_mutex_);

    if (order_index_.count(order.order_id)) return false;

    OrderLocation loc{order.price, order.side};
    order_index_[order.order_id] = loc;

    if (order.side == ::exchange::BUY) {
        bids_[order.price].push_back(order);
    } else {
        asks_[order.price].push_back(order);
    }

    seq_num_.fetch_add(1, std::memory_order_relaxed);
    return true;
}

int OrderBook::cancel_order(const std::string& order_id) {
    std::unique_lock lock(book_mutex_);

    auto it = order_index_.find(order_id);
    if (it == order_index_.end()) return 0;

    const auto& loc = it->second;
    int cancelled_qty = 0;

    auto remove_from = [&](auto& price_map) {
        auto level_it = price_map.find(loc.price);
        if (level_it == price_map.end()) return;

        auto& dq = level_it->second;
        for (auto oit = dq.begin(); oit != dq.end(); ++oit) {
            if (oit->order_id == order_id) {
                cancelled_qty = oit->remaining;
                dq.erase(oit);
                break;
            }
        }
        if (dq.empty()) price_map.erase(level_it);
    };

    if (loc.side == ::exchange::BUY) {
        remove_from(bids_);
    } else {
        remove_from(asks_);
    }

    order_index_.erase(it);
    seq_num_.fetch_add(1, std::memory_order_relaxed);
    return cancelled_qty;
}

BookSnapshot OrderBook::get_snapshot(int depth) const {
    std::shared_lock lock(book_mutex_);

    BookSnapshot snap;
    snap.symbol     = symbol_;
    snap.seq_num    = seq_num_.load(std::memory_order_relaxed);
    snap.timestamp_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::system_clock::now().time_since_epoch()).count();

    int count = 0;
    for (const auto& [price, dq] : bids_) {
        if (count++ >= depth) break;
        BookLevel pl;
        pl.price = price;
        pl.order_count = static_cast<int>(dq.size());
        for (const auto& o : dq) pl.total_quantity += o.remaining;
        snap.bids.push_back(pl);
    }

    count = 0;
    for (const auto& [price, dq] : asks_) {
        if (count++ >= depth) break;
        BookLevel pl;
        pl.price = price;
        pl.order_count = static_cast<int>(dq.size());
        for (const auto& o : dq) pl.total_quantity += o.remaining;
        snap.asks.push_back(pl);
    }

    snap.best_bid = bids_.empty() ? 0.0 : bids_.begin()->first;
    snap.best_ask = asks_.empty() ? 0.0 : asks_.begin()->first;

    if (snap.best_bid > 0.0 && snap.best_ask > 0.0) {
        snap.spread    = snap.best_ask - snap.best_bid;
        snap.mid_price = (snap.best_bid + snap.best_ask) / 2.0;
    }

    return snap;
}

double OrderBook::get_best_bid() const {
    std::shared_lock lock(book_mutex_);
    return bids_.empty() ? 0.0 : bids_.begin()->first;
}

double OrderBook::get_best_ask() const {
    std::shared_lock lock(book_mutex_);
    return asks_.empty() ? 0.0 : asks_.begin()->first;
}

std::optional<Order> OrderBook::peek_best_bid() const {
    // Caller must hold at least shared lock
    if (bids_.empty()) return std::nullopt;
    const auto& dq = bids_.begin()->second;
    if (dq.empty()) return std::nullopt;
    return dq.front();
}

std::optional<Order> OrderBook::peek_best_ask() const {
    if (asks_.empty()) return std::nullopt;
    const auto& dq = asks_.begin()->second;
    if (dq.empty()) return std::nullopt;
    return dq.front();
}

Order OrderBook::consume_from_bid(int qty) {
    // Caller holds unique lock
    auto& dq = bids_.begin()->second;
    Order front = dq.front();

    if (qty >= front.remaining) {
        // Fully consumed — remove from book and index
        order_index_.erase(front.order_id);
        dq.pop_front();
        if (dq.empty()) bids_.erase(bids_.begin());
    } else {
        // Partially consumed — update remaining in place
        dq.front().filled_qty  += qty;
        dq.front().remaining   -= qty;
        dq.front().status       = ::exchange::PARTIAL_FILL;
    }
    seq_num_.fetch_add(1, std::memory_order_relaxed);
    return front;
}

Order OrderBook::consume_from_ask(int qty) {
    auto& dq = asks_.begin()->second;
    Order front = dq.front();

    if (qty >= front.remaining) {
        order_index_.erase(front.order_id);
        dq.pop_front();
        if (dq.empty()) asks_.erase(asks_.begin());
    } else {
        dq.front().filled_qty  += qty;
        dq.front().remaining   -= qty;
        dq.front().status       = ::exchange::PARTIAL_FILL;
    }
    seq_num_.fetch_add(1, std::memory_order_relaxed);
    return front;
}

std::optional<Order> OrderBook::find_order(const std::string& order_id) const {
    std::shared_lock lock(book_mutex_);

    auto idx = order_index_.find(order_id);
    if (idx == order_index_.end()) return std::nullopt;

    const auto& loc = idx->second;
    if (loc.side == ::exchange::BUY) {
        auto level_it = bids_.find(loc.price);
        if (level_it == bids_.end()) return std::nullopt;
        for (const auto& o : level_it->second)
            if (o.order_id == order_id) return o;
    } else {
        auto level_it = asks_.find(loc.price);
        if (level_it == asks_.end()) return std::nullopt;
        for (const auto& o : level_it->second)
            if (o.order_id == order_id) return o;
    }
    return std::nullopt;
}

int OrderBook::bid_total_qty() const {
    std::shared_lock lock(book_mutex_);
    int total = 0;
    for (const auto& [p, dq] : bids_)
        for (const auto& o : dq) total += o.remaining;
    return total;
}

int OrderBook::ask_total_qty() const {
    std::shared_lock lock(book_mutex_);
    int total = 0;
    for (const auto& [p, dq] : asks_)
        for (const auto& o : dq) total += o.remaining;
    return total;
}

int OrderBook::bid_depth() const {
    std::shared_lock lock(book_mutex_);
    return static_cast<int>(bids_.size());
}

int OrderBook::ask_depth() const {
    std::shared_lock lock(book_mutex_);
    return static_cast<int>(asks_.size());
}

} // namespace exchange
