#pragma once

#include "matching_engine.hpp"
#include "risk_engine.hpp"
#include "types.hpp"

#include <grpcpp/grpcpp.h>
#include <memory>
#include <string>
#include <atomic>
#include <thread>

// Generated proto stubs
#include "exchange.grpc.pb.h"
#include "exchange.pb.h"

namespace exchange {

// ============================================================
// ExchangeServiceImpl — gRPC service implementation
// ============================================================

class ExchangeServiceImpl final : public ::exchange::ExchangeService::Service {
public:
    ExchangeServiceImpl(MatchingEngine& engine, RiskEngine& risk);

    // ---- Order lifecycle ----
    grpc::Status SubmitOrder(grpc::ServerContext* ctx,
                              const ::exchange::OrderRequest* req,
                              ::exchange::OrderResponse* resp) override;

    grpc::Status CancelOrder(grpc::ServerContext* ctx,
                              const ::exchange::CancelRequest* req,
                              ::exchange::CancelResponse* resp) override;

    grpc::Status AmendOrder(grpc::ServerContext* ctx,
                             const ::exchange::AmendRequest* req,
                             ::exchange::OrderResponse* resp) override;

    // ---- Market data ----
    grpc::Status GetOrderBook(grpc::ServerContext* ctx,
                               const ::exchange::OrderBookRequest* req,
                               ::exchange::OrderBookSnapshot* resp) override;

    grpc::Status GetMarketStats(grpc::ServerContext* ctx,
                                 const ::exchange::MarketStatsRequest* req,
                                 ::exchange::MarketStats* resp) override;

    grpc::Status GetTrades(grpc::ServerContext* ctx,
                            const ::exchange::TradeHistoryRequest* req,
                            ::exchange::TradeHistoryResponse* resp) override;

    // ---- Admin ----
    grpc::Status PauseMarket(grpc::ServerContext* ctx,
                              const ::exchange::MarketControlRequest* req,
                              ::exchange::MarketControlResponse* resp) override;

    grpc::Status ResumeMarket(grpc::ServerContext* ctx,
                               const ::exchange::MarketControlRequest* req,
                               ::exchange::MarketControlResponse* resp) override;

    grpc::Status SetCircuitBreakerLimit(grpc::ServerContext* ctx,
                                         const ::exchange::CircuitBreakerConfig* req,
                                         ::exchange::MarketControlResponse* resp) override;

    // ---- Health ----
    grpc::Status Ping(grpc::ServerContext* ctx,
                       const ::exchange::Empty* req,
                       ::exchange::PongResponse* resp) override;

    grpc::Status GetEngineMetrics(grpc::ServerContext* ctx,
                                   const ::exchange::Empty* req,
                                   ::exchange::EngineMetrics* resp) override;

    // Record a trade for GetTrades history
    void record_trade(const ExecutedTrade& trade);

private:
    // Helpers
    static Order          proto_to_order(const ::exchange::OrderRequest& req);
    static ::exchange::Trade trade_to_proto(const ExecutedTrade& t);

    MatchingEngine& engine_;
    RiskEngine&     risk_;

    // Trade history ring buffer
    mutable std::mutex trades_mutex_;
    std::deque<ExecutedTrade>  trade_history_;
    static constexpr size_t kMaxTradeHistory = 100'000;

    // Start time for uptime reporting
    std::chrono::steady_clock::time_point start_time_{std::chrono::steady_clock::now()};

    std::atomic<int64_t> order_seq_{1'000'000};
};

// ============================================================
// GrpcServer — owns the gRPC server lifecycle
// ============================================================

class GrpcServer {
public:
    GrpcServer(int port, MatchingEngine& engine, RiskEngine& risk);
    ~GrpcServer();

    void start();
    void stop();

    ExchangeServiceImpl& service() { return *service_; }

private:
    int             port_;
    std::unique_ptr<ExchangeServiceImpl> service_;
    std::unique_ptr<grpc::Server>        server_;
    std::thread                          thread_;
};

} // namespace exchange
