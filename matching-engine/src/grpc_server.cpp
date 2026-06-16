#include "grpc_server.hpp"

#include <chrono>
#include <iostream>
#include <sstream>

namespace exchange {

// ============================================================
// Proto ↔ internal conversion helpers
// ============================================================

static int64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
               std::chrono::system_clock::now().time_since_epoch()).count();
}

Order ExchangeServiceImpl::proto_to_order(const ::exchange::OrderRequest& req) {
    Order o;
    o.user_id  = req.user_id();
    o.symbol   = req.symbol();
    o.price    = req.price();
    o.stop_price = req.stop_price();
    o.quantity = req.quantity();
    o.remaining = req.quantity();
    o.expire_time_ms = req.expire_time_ms();
    o.timestamp_ns   = now_ns();

    // Side
    switch (req.side()) {
        case ::exchange::BUY:  o.side = ::exchange::BUY;  break;
        case ::exchange::SELL: o.side = ::exchange::SELL; break;
        default:               o.side = ::exchange::SIDE_UNKNOWN; break;
    }

    // Order type
    switch (req.order_type()) {
        case ::exchange::LIMIT:      o.type = ::exchange::LIMIT;      break;
        case ::exchange::MARKET:     o.type = ::exchange::MARKET;     break;
        case ::exchange::STOP_LOSS:  o.type = ::exchange::STOP_LOSS;  break;
        case ::exchange::STOP_LIMIT: o.type = ::exchange::STOP_LIMIT; break;
        case ::exchange::IOC:        o.type = ::exchange::IOC;        break;
        case ::exchange::FOK:        o.type = ::exchange::FOK;        break;
        case ::exchange::GTT:        o.type = ::exchange::GTT;        break;
        default:                     o.type = ::exchange::ORDER_TYPE_UNKNOWN;    break;
    }

    return o;
}

::exchange::Trade ExchangeServiceImpl::trade_to_proto(const ExecutedTrade& t) {
    ::exchange::Trade pt;
    pt.set_trade_id(t.trade_id);
    pt.set_symbol(t.symbol);
    pt.set_price(t.price);
    pt.set_quantity(t.quantity);
    pt.set_buy_order_id(t.buy_order_id);
    pt.set_sell_order_id(t.sell_order_id);
    pt.set_buyer_user_id(t.buyer_user_id);
    pt.set_seller_user_id(t.seller_user_id);
    pt.set_timestamp_ns(t.timestamp_ns);
    return pt;
}

// ============================================================
// ExchangeServiceImpl — ctor
// ============================================================

ExchangeServiceImpl::ExchangeServiceImpl(MatchingEngine& engine, RiskEngine& risk)
    : engine_(engine), risk_(risk) {}

// ============================================================
// SubmitOrder
// ============================================================

grpc::Status ExchangeServiceImpl::SubmitOrder(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::OrderRequest* req,
    ::exchange::OrderResponse* resp) {

    int64_t t0 = now_ns();

    // Build internal order
    Order order = proto_to_order(*req);

    // Generate server-side order ID
    order.order_id = "ORD-" + std::to_string(
        order_seq_.fetch_add(1, std::memory_order_relaxed));

    // Risk check
    RejectionReason risk_result = risk_.check(order);
    if (risk_result != ::exchange::REASON_NONE) {
        resp->set_order_id(order.order_id);
        resp->set_client_order_id(req->client_order_id());
        resp->set_status(::exchange::REJECTED);
        resp->set_rejection_reason(
            static_cast<::exchange::RejectionReason>(static_cast<int>(risk_result)));
        resp->set_rejection_message("Risk check failed");
        resp->set_timestamp_ns(t0);
        return grpc::Status::OK;
    }

    // Process order synchronously (returns MatchResult)
    MatchResult result = engine_.process_order_sync(order);

    // Fill response
    resp->set_order_id(order.order_id);
    resp->set_client_order_id(req->client_order_id());
    resp->set_filled_quantity(result.filled_qty);
    resp->set_remaining_quantity(result.remaining_qty);
    resp->set_avg_fill_price(result.avg_fill_price);
    resp->set_timestamp_ns(t0);
    resp->set_matching_latency_ns(result.matching_latency_ns);

    // Map internal status to proto status
    switch (result.status) {
        case ::exchange::FILLED:       resp->set_status(::exchange::FILLED);       break;
        case ::exchange::PARTIAL_FILL: resp->set_status(::exchange::PARTIAL_FILL); break;
        case ::exchange::ACCEPTED:     resp->set_status(::exchange::ACCEPTED);     break;
        case ::exchange::CANCELLED:    resp->set_status(::exchange::CANCELLED);    break;
        case ::exchange::EXPIRED:      resp->set_status(::exchange::EXPIRED);      break;
        case ::exchange::PENDING:      resp->set_status(::exchange::PENDING);      break;
        case ::exchange::REJECTED:
            resp->set_status(::exchange::REJECTED);
            resp->set_rejection_reason(
                static_cast<::exchange::RejectionReason>(
                    static_cast<int>(result.rejection)));
            resp->set_rejection_message(result.rejection_msg);
            break;
        default: resp->set_status(::exchange::STATUS_UNKNOWN); break;
    }

    // Embed trades
    for (const auto& t : result.trades) {
        *resp->add_trades() = trade_to_proto(t);
    }

    return grpc::Status::OK;
}

// ============================================================
// CancelOrder
// ============================================================

grpc::Status ExchangeServiceImpl::CancelOrder(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::CancelRequest* req,
    ::exchange::CancelResponse* resp) {

    bool ok = engine_.cancel_order(req->order_id(),
                                    req->symbol(),
                                    req->user_id());

    resp->set_success(ok);
    resp->set_order_id(req->order_id());
    resp->set_message(ok ? "Order cancelled" : "Order not found or already filled");
    return grpc::Status::OK;
}

// ============================================================
// AmendOrder (cancel + resubmit)
// ============================================================

grpc::Status ExchangeServiceImpl::AmendOrder(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::AmendRequest* req,
    ::exchange::OrderResponse* resp) {

    // Find the existing order by scanning the book — simplified implementation.
    // A full implementation would maintain a global order map. Here we cancel
    // and re-create if the user provides a symbol via metadata; since the proto
    // doesn't include symbol in AmendRequest we cannot look it up without an
    // order cache. We return an error indicating this needs the order cache.
    resp->set_status(::exchange::REJECTED);
    resp->set_rejection_message(
        "Amend not supported without order cache; cancel and resubmit");
    (void)req;
    return grpc::Status::OK;
}

// ============================================================
// GetOrderBook
// ============================================================

grpc::Status ExchangeServiceImpl::GetOrderBook(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::OrderBookRequest* req,
    ::exchange::OrderBookSnapshot* resp) {

    int depth = (req->depth() > 0) ? req->depth() : 10;
    BookSnapshot snap = engine_.get_book_snapshot(req->symbol(), depth);

    resp->set_symbol(snap.symbol);
    resp->set_best_bid(snap.best_bid);
    resp->set_best_ask(snap.best_ask);
    resp->set_spread(snap.spread);
    resp->set_mid_price(snap.mid_price);
    resp->set_sequence_number(snap.seq_num);
    resp->set_timestamp_ns(snap.timestamp_ns);

    for (const auto& pl : snap.bids) {
        auto* b = resp->add_bids();
        b->set_price(pl.price);
        b->set_total_quantity(pl.total_quantity);
        b->set_order_count(pl.order_count);
    }
    for (const auto& pl : snap.asks) {
        auto* a = resp->add_asks();
        a->set_price(pl.price);
        a->set_total_quantity(pl.total_quantity);
        a->set_order_count(pl.order_count);
    }

    return grpc::Status::OK;
}

// ============================================================
// GetMarketStats
// ============================================================

grpc::Status ExchangeServiceImpl::GetMarketStats(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::MarketStatsRequest* req,
    ::exchange::MarketStats* resp) {

    const auto& sym = req->symbol();
    BookSnapshot snap = engine_.get_book_snapshot(sym, 1);

    resp->set_symbol(sym);
    resp->set_last_price(snap.best_bid);  // Approximate
    resp->set_spread(snap.spread);
    resp->set_is_halted(engine_.is_halted(sym));
    resp->set_timestamp_ns(now_ns());

    // Volume / trade count from per-symbol stats
    const auto& stats_map = engine_.symbol_stats();
    auto it = stats_map.find(sym);
    if (it != stats_map.end()) {
        resp->set_volume(it->second->volume.load());
        resp->set_trade_count(it->second->trade_count.load());
        resp->set_bid_depth(static_cast<int32_t>(it->second->order_count.load()));
    }

    return grpc::Status::OK;
}

// ============================================================
// GetTrades
// ============================================================

grpc::Status ExchangeServiceImpl::GetTrades(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::TradeHistoryRequest* req,
    ::exchange::TradeHistoryResponse* resp) {

    std::lock_guard lk(trades_mutex_);

    int limit = (req->limit() > 0) ? req->limit() : 100;
    int count = 0;

    // Iterate in reverse (most recent first)
    for (auto it = trade_history_.rbegin();
         it != trade_history_.rend() && count < limit; ++it) {

        const ExecutedTrade& t = *it;
        if (!req->symbol().empty() && t.symbol != req->symbol()) continue;
        if (req->from_timestamp_ns() > 0 && t.timestamp_ns < req->from_timestamp_ns()) continue;
        if (req->to_timestamp_ns()   > 0 && t.timestamp_ns > req->to_timestamp_ns())   continue;

        *resp->add_trades() = trade_to_proto(t);
        ++count;
    }

    resp->set_total_count(count);
    return grpc::Status::OK;
}

// ============================================================
// PauseMarket
// ============================================================

grpc::Status ExchangeServiceImpl::PauseMarket(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::MarketControlRequest* req,
    ::exchange::MarketControlResponse* resp) {

    const auto& sym = req->symbol();
    engine_.halt_symbol(sym);
    risk_.halt_symbol(sym);

    resp->set_success(true);
    resp->set_symbol(sym);
    resp->set_is_halted(true);
    resp->set_message("Market paused for " + sym);
    return grpc::Status::OK;
}

// ============================================================
// ResumeMarket
// ============================================================

grpc::Status ExchangeServiceImpl::ResumeMarket(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::MarketControlRequest* req,
    ::exchange::MarketControlResponse* resp) {

    const auto& sym = req->symbol();
    engine_.resume_symbol(sym);
    risk_.resume_symbol(sym);

    resp->set_success(true);
    resp->set_symbol(sym);
    resp->set_is_halted(false);
    resp->set_message("Market resumed for " + sym);
    return grpc::Status::OK;
}

// ============================================================
// SetCircuitBreakerLimit
// ============================================================

grpc::Status ExchangeServiceImpl::SetCircuitBreakerLimit(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::CircuitBreakerConfig* req,
    ::exchange::MarketControlResponse* resp) {

    // Update risk limits for this symbol globally
    RiskLimits limits = risk_.get_limits("");
    limits.circuit_breaker_pct      = req->price_change_pct();
    limits.circuit_breaker_window_s = req->window_seconds();
    risk_.set_limits("", limits);

    if (!req->enabled()) {
        risk_.resume_symbol(req->symbol());
    }

    resp->set_success(true);
    resp->set_symbol(req->symbol());
    resp->set_message("Circuit breaker config updated");
    return grpc::Status::OK;
}

// ============================================================
// Ping
// ============================================================

grpc::Status ExchangeServiceImpl::Ping(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::Empty* /*req*/,
    ::exchange::PongResponse* resp) {

    resp->set_message("pong");
    resp->set_timestamp_ns(now_ns());
    resp->set_version("1.0.0");
    return grpc::Status::OK;
}

// ============================================================
// GetEngineMetrics
// ============================================================

grpc::Status ExchangeServiceImpl::GetEngineMetrics(
    grpc::ServerContext* /*ctx*/,
    const ::exchange::Empty* /*req*/,
    ::exchange::EngineMetrics* resp) {

    resp->set_total_orders_received(engine_.total_orders());
    resp->set_total_orders_matched(engine_.total_trades());
    resp->set_total_orders_cancelled(engine_.total_cancels());
    resp->set_total_trades_executed(engine_.total_trades());
    resp->set_total_orders_rejected(engine_.total_rejected());
    resp->set_p50_latency_ns(engine_.p50_ns());
    resp->set_p95_latency_ns(engine_.p95_ns());
    resp->set_p99_latency_ns(engine_.p99_ns());
    resp->set_p999_latency_ns(engine_.p999_ns());

    int64_t uptime = std::chrono::duration_cast<std::chrono::seconds>(
                         std::chrono::steady_clock::now() - start_time_).count();
    resp->set_uptime_seconds(uptime);

    // Per-symbol metrics
    for (const auto& [sym, stats] : engine_.symbol_stats()) {
        auto* sm = resp->add_symbol_metrics();
        sm->set_symbol(sym);
        sm->set_order_count(stats->order_count.load());
        sm->set_trade_count(stats->trade_count.load());
        sm->set_volume(static_cast<double>(stats->volume.load()));
        sm->set_is_halted(engine_.is_halted(sym));
    }

    return grpc::Status::OK;
}

// ============================================================
// record_trade — called from on_trade callback
// ============================================================

void ExchangeServiceImpl::record_trade(const ExecutedTrade& trade) {
    std::lock_guard lk(trades_mutex_);
    trade_history_.push_back(trade);
    while (trade_history_.size() > kMaxTradeHistory) {
        trade_history_.pop_front();
    }
}

// ============================================================
// GrpcServer
// ============================================================

GrpcServer::GrpcServer(int port, MatchingEngine& engine, RiskEngine& risk)
    : port_(port),
      service_(std::make_unique<ExchangeServiceImpl>(engine, risk)) {}

GrpcServer::~GrpcServer() { stop(); }

void GrpcServer::start() {
    std::string addr = "0.0.0.0:" + std::to_string(port_);

    grpc::ServerBuilder builder;
    builder.AddListeningPort(addr, grpc::InsecureServerCredentials());
    builder.RegisterService(service_.get());
    builder.SetMaxReceiveMessageSize(64 * 1024 * 1024);  // 64 MB
    builder.SetMaxSendMessageSize(64 * 1024 * 1024);

    server_ = builder.BuildAndStart();
    if (!server_) {
        throw std::runtime_error("[gRPC] Failed to start server on " + addr);
    }

    std::cout << "[gRPC] Server listening on " << addr << "\n";

    thread_ = std::thread([this] { server_->Wait(); });
}

void GrpcServer::stop() {
    if (server_) {
        server_->Shutdown();
        server_.reset();
    }
    if (thread_.joinable()) thread_.join();
}

} // namespace exchange
