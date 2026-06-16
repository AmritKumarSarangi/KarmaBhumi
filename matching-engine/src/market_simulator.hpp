#pragma once

#include "types.hpp"
#include <atomic>
#include <chrono>
#include <functional>
#include <memory>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace exchange {

// ============================================================
//  Bot persona base
// ============================================================

class BotBase {
public:
    explicit BotBase(std::string id, std::string name,
                     std::vector<std::string> symbols,
                     std::function<void(Order)> submit)
        : id_(std::move(id)), name_(std::move(name)),
          symbols_(std::move(symbols)), submit_(std::move(submit)),
          rng_(std::random_device{}()), running_(false) {}

    virtual ~BotBase() { stop(); }

    void start() {
        running_ = true;
        thread_ = std::thread([this] { loop(); });
    }

    void stop() {
        running_ = false;
        if (thread_.joinable()) thread_.join();
    }

    const std::string& id()   const { return id_; }
    const std::string& name() const { return name_; }

    // Called by the simulator to update the last known price
    void set_last_price(const std::string& symbol, double price) {
        std::lock_guard<std::mutex> lk(price_mtx_);
        last_price_[symbol] = price;
    }

protected:
    virtual void loop() = 0;

    double last_price(const std::string& symbol) {
        std::lock_guard<std::mutex> lk(price_mtx_);
        auto it = last_price_.find(symbol);
        return (it != last_price_.end()) ? it->second : 100.0;
    }

    Order make_order(const std::string& symbol, Side side,
                     OrderType type, double price, int qty) {
        Order o;
        o.order_id    = next_order_id();
        o.user_id     = id_;
        o.symbol      = symbol;
        o.side        = side;
        o.type        = type;
        o.price       = price;
        o.quantity    = qty;
        o.timestamp_ns = now_ns();
        return o;
    }

    std::string next_order_id() {
        return id_ + "-" + std::to_string(order_seq_.fetch_add(1));
    }

    int64_t now_ns() {
        return std::chrono::duration_cast<std::chrono::nanoseconds>(
                   std::chrono::system_clock::now().time_since_epoch())
            .count();
    }

    const std::string              id_, name_;
    const std::vector<std::string> symbols_;
    std::function<void(Order)>     submit_;

    std::mt19937                         rng_;
    std::atomic<bool>                    running_;
    std::thread                          thread_;
    std::atomic<int64_t>                 order_seq_{0};
    std::mutex                           price_mtx_;
    std::unordered_map<std::string, double> last_price_;
};

// ============================================================
// 1. Retail Bot — slow, emotional, random direction
//    Sends LIMIT and occasional MARKET orders. Sometimes
//    chases price up/down after a big move. Long sleep intervals.
// ============================================================

class RetailBot : public BotBase {
public:
    using BotBase::BotBase;

protected:
    void loop() override {
        std::uniform_int_distribution<int>  sleep_ms(800, 3000);
        std::uniform_int_distribution<int>  qty_dist(1, 50);
        std::uniform_real_distribution<double> price_offset(-2.0, 2.0);
        std::uniform_int_distribution<int>  side_dist(0, 1);
        std::uniform_int_distribution<int>  type_dist(0, 4); // 0-3=LIMIT, 4=MARKET
        std::uniform_int_distribution<int>  sym_idx(0, (int)symbols_.size() - 1);

        while (running_) {
            const auto& sym   = symbols_[sym_idx(rng_)];
            double      base  = last_price(sym);
            Side        side  = side_dist(rng_) ? ::exchange::BUY : ::exchange::SELL;
            OrderType   otype = (type_dist(rng_) == 4) ? ::exchange::MARKET
                                                       : ::exchange::LIMIT;
            double price = (otype == ::exchange::MARKET)
                               ? 0.0
                               : std::round((base + price_offset(rng_)) * 100) / 100.0;
            int qty = qty_dist(rng_);

            if (price > 0 || otype == ::exchange::MARKET)
                submit_(make_order(sym, side, otype, price, qty));

            std::this_thread::sleep_for(
                std::chrono::milliseconds(sleep_ms(rng_)));
        }
    }
};

// ============================================================
// 2. HFT Bot — extremely fast, reacts to spread & imbalance.
//    Places LIMIT orders just inside the spread, cancels &
//    replaces on every tick. Uses IOC for aggressive fills.
// ============================================================

class HFTBot : public BotBase {
public:
    HFTBot(std::string id, std::string name,
           std::vector<std::string> symbols,
           std::function<void(Order)> submit,
           std::function<BookSnapshot(const std::string&)> get_book)
        : BotBase(std::move(id), std::move(name),
                  std::move(symbols), std::move(submit)),
          get_book_(std::move(get_book)) {}

protected:
    void loop() override {
        std::uniform_int_distribution<int>    sleep_us(50, 500);
        std::uniform_int_distribution<int>    qty_dist(10, 200);
        std::uniform_int_distribution<int>    sym_idx(0, (int)symbols_.size() - 1);
        std::uniform_real_distribution<double> edge(0.01, 0.05);

        while (running_) {
            const auto& sym  = symbols_[sym_idx(rng_)];
            auto        snap = get_book_(sym);

            if (snap.best_bid > 0 && snap.best_ask > 0) {
                double spread = snap.best_ask - snap.best_bid;

                if (spread > 0.02) {
                    // Place orders just inside the spread
                    double bid_price = snap.best_bid + edge(rng_);
                    double ask_price = snap.best_ask - edge(rng_);
                    int    qty       = qty_dist(rng_);

                    bid_price = std::round(bid_price * 100) / 100.0;
                    ask_price = std::round(ask_price * 100) / 100.0;

                    if (bid_price < ask_price) {
                        submit_(make_order(sym, ::exchange::BUY,  ::exchange::LIMIT, bid_price, qty));
                        submit_(make_order(sym, ::exchange::SELL, ::exchange::LIMIT, ask_price, qty));
                    }
                } else {
                    // Tight spread — fire an IOC to grab liquidity
                    int qty = qty_dist(rng_);
                    submit_(make_order(sym, ::exchange::BUY,
                                       ::exchange::IOC, snap.best_ask, qty));
                }
            }

            std::this_thread::sleep_for(
                std::chrono::microseconds(sleep_us(rng_)));
        }
    }

private:
    std::function<BookSnapshot(const std::string&)> get_book_;
};

// ============================================================
// 3. Market Maker Bot — always quotes two-sided market.
//    Maintains bid and ask at fixed spread around mid-price.
//    Adjusts quotes on every cycle to stay competitive.
//    Never lets one side drift too far from the other.
// ============================================================

class MarketMakerBot : public BotBase {
public:
    MarketMakerBot(std::string id, std::string name,
                   std::vector<std::string> symbols,
                   std::function<void(Order)> submit,
                   double spread_pct = 0.001)  // 0.1% spread
        : BotBase(std::move(id), std::move(name),
                  std::move(symbols), std::move(submit)),
          spread_pct_(spread_pct) {}

protected:
    void loop() override {
        std::uniform_int_distribution<int>    sleep_ms(100, 300);
        std::uniform_int_distribution<int>    qty_dist(50, 500);
        std::uniform_int_distribution<int>    sym_idx(0, (int)symbols_.size() - 1);
        std::uniform_real_distribution<double> skew(-0.0005, 0.0005);

        while (running_) {
            const auto& sym  = symbols_[sym_idx(rng_)];
            double      mid  = last_price(sym);

            if (mid <= 0) {
                std::this_thread::sleep_for(std::chrono::milliseconds(200));
                continue;
            }

            // Slight inventory skew so the MM doesn't accumulate one side
            double sk    = skew(rng_);
            double half  = mid * spread_pct_ / 2.0;
            double bid   = std::round((mid - half + sk) * 100) / 100.0;
            double ask   = std::round((mid + half + sk) * 100) / 100.0;
            int    qty   = qty_dist(rng_);

            if (bid > 0 && ask > bid) {
                submit_(make_order(sym, ::exchange::BUY,  ::exchange::LIMIT, bid, qty));
                submit_(make_order(sym, ::exchange::SELL, ::exchange::LIMIT, ask, qty));
            }

            std::this_thread::sleep_for(
                std::chrono::milliseconds(sleep_ms(rng_)));
        }
    }

private:
    double spread_pct_;
};

// ============================================================
// 4. Institution Bot — large block trades, patient, uses
//    iceberg-style splitting to minimize market impact.
//    Occasionally fires a GTT (Good-Till-Time) order.
// ============================================================

class InstitutionBot : public BotBase {
public:
    using BotBase::BotBase;

protected:
    void loop() override {
        std::uniform_int_distribution<int>    sleep_ms(2000, 8000);
        std::uniform_int_distribution<int>    block_qty(500, 5000);
        std::uniform_int_distribution<int>    slice_count(3, 10);
        std::uniform_int_distribution<int>    sym_idx(0, (int)symbols_.size() - 1);
        std::uniform_real_distribution<double> price_offset(-1.0, 1.0);
        std::uniform_int_distribution<int>    side_dist(0, 1);
        std::uniform_int_distribution<int>    order_style(0, 4); // 0-3=LIMIT, 4=GTT

        while (running_) {
            const auto& sym    = symbols_[sym_idx(rng_)];
            double      base   = last_price(sym);
            Side        side   = side_dist(rng_) ? ::exchange::BUY : ::exchange::SELL;
            int         total  = block_qty(rng_);
            int         slices = slice_count(rng_);
            int         per_slice = total / slices;
            bool        use_gtt  = (order_style(rng_) == 4);

            for (int i = 0; i < slices && running_; ++i) {
                double price  = std::round((base + price_offset(rng_)) * 100) / 100.0;
                OrderType ot  = use_gtt ? ::exchange::GTT : ::exchange::LIMIT;

                Order o = make_order(sym, side, ot, price, per_slice);
                if (use_gtt) {
                    // Expire 60 seconds from now
                    o.expire_time_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                                           std::chrono::system_clock::now().time_since_epoch())
                                           .count() + 60000;
                }
                submit_(o);

                // Brief pause between slices (TWAP-style)
                std::this_thread::sleep_for(
                    std::chrono::milliseconds(200 + rng_() % 500));
            }

            std::this_thread::sleep_for(
                std::chrono::milliseconds(sleep_ms(rng_)));
        }
    }
};

// ============================================================
//  MarketSimulator — owns all bots, manages the order stream
//
//   Retail Bot ──┐
//   HFT Bot ─────┼──► Order Stream ──► Matching Engine
//   Market Maker ┤
//   Institution ─┘
// ============================================================

class MarketSimulator {
public:
    MarketSimulator(std::vector<std::string> symbols,
                    std::function<void(Order)> order_stream,
                    std::function<BookSnapshot(const std::string&)> get_book,
                    int retail_count    = 3,
                    int hft_count       = 2,
                    int mm_count        = 1,
                    int institution_count = 1)
        : symbols_(std::move(symbols)),
          order_stream_(std::move(order_stream)),
          get_book_(std::move(get_book)) {

        // Create Retail bots
        for (int i = 0; i < retail_count; ++i) {
            auto bot = std::make_unique<RetailBot>(
                "retail-" + std::to_string(i),
                "Retail Trader " + std::to_string(i + 1),
                symbols_, order_stream_);
            bots_.push_back(std::move(bot));
        }

        // Create HFT bots
        for (int i = 0; i < hft_count; ++i) {
            auto bot = std::make_unique<HFTBot>(
                "hft-" + std::to_string(i),
                "HFT Bot " + std::to_string(i + 1),
                symbols_, order_stream_, get_book_);
            bots_.push_back(std::move(bot));
        }

        // Create Market Maker bots
        for (int i = 0; i < mm_count; ++i) {
            auto bot = std::make_unique<MarketMakerBot>(
                "mm-" + std::to_string(i),
                "Market Maker " + std::to_string(i + 1),
                symbols_, order_stream_,
                0.001 + 0.0005 * i);  // Slightly different spreads
            bots_.push_back(std::move(bot));
        }

        // Create Institution bots
        for (int i = 0; i < institution_count; ++i) {
            auto bot = std::make_unique<InstitutionBot>(
                "inst-" + std::to_string(i),
                "Institution " + std::to_string(i + 1),
                symbols_, order_stream_);
            bots_.push_back(std::move(bot));
        }
    }

    void start() {
        running_ = true;
        for (auto& bot : bots_) bot->start();
    }

    void stop() {
        running_ = false;
        for (auto& bot : bots_) bot->stop();
    }

    // Feed latest trade price back to all bots so they stay anchored
    void on_trade(const std::string& symbol, double price) {
        for (auto& bot : bots_)
            bot->set_last_price(symbol, price);
    }

    size_t bot_count() const { return bots_.size(); }

private:
    std::vector<std::string>                       symbols_;
    std::function<void(Order)>                     order_stream_;
    std::function<BookSnapshot(const std::string&)> get_book_;
    std::vector<std::unique_ptr<BotBase>>          bots_;
    std::atomic<bool>                              running_{false};
};

} // namespace exchange
