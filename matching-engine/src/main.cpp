#include "types.hpp"
#include "matching_engine.hpp"
#include "risk_engine.hpp"
#include "grpc_server.hpp"
#include "metrics.hpp"
#include "kafka_producer.hpp"
#include "market_simulator.hpp"

#include <iostream>
#include <vector>
#include <string>
#include <sstream>
#include <csignal>
#include <thread>
#include <chrono>
#include <memory>

std::atomic<bool> g_running{true};

void signal_handler(int signal) {
    if (signal == SIGINT || signal == SIGTERM) {
        std::cout << "\n[Main] Shutdown signal received. Stopping exchange services..." << std::endl;
        g_running = false;
    }
}

std::vector<std::string> split_symbols(const std::string& str, char delimiter) {
    std::vector<std::string> internal;
    std::stringstream ss(str);
    std::string tok;
    while (std::getline(ss, tok, delimiter)) {
        if (!tok.empty()) {
            internal.push_back(tok);
        }
    }
    return internal;
}

int main() {
    // Register signal handlers
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::cout << "==================================================" << std::endl;
    std::cout << "     EXCHANGEX — C++ MATCHING ENGINE SERVICE     " << std::endl;
    std::cout << "==================================================" << std::endl;

    // Load environment variables
    const char* env_brokers = std::getenv("KAFKA_BROKERS");
    std::string kafka_brokers = env_brokers ? env_brokers : "kafka:9092";

    const char* env_grpc_port = std::getenv("GRPC_PORT");
    int grpc_port = env_grpc_port ? std::stoi(env_grpc_port) : 50051;

    const char* env_metrics_port = std::getenv("METRICS_PORT");
    int metrics_port = env_metrics_port ? std::stoi(env_metrics_port) : 8080;

    const char* env_symbols = std::getenv("SYMBOLS");
    std::string symbols_str = env_symbols ? env_symbols : "AAPL,GOOGL,TSLA,MSFT,AMZN";
    std::vector<std::string> symbols = split_symbols(symbols_str, ',');

    std::cout << "[Main] Kafka Brokers: " << kafka_brokers << std::endl;
    std::cout << "[Main] gRPC Port:     " << grpc_port << std::endl;
    std::cout << "[Main] Metrics Port:  " << metrics_port << std::endl;
    std::cout << "[Main] Trade Symbols: ";
    for (size_t i = 0; i < symbols.size(); ++i) {
        std::cout << symbols[i] << (i == symbols.size() - 1 ? "" : ", ");
    }
    std::cout << std::endl;

    // 1. Initialize Kafka Producer
    std::cout << "[Main] Initializing Kafka Producer..." << std::endl;
    auto producer = std::make_unique<exchange::KafkaProducer>(kafka_brokers, "matching-engine-prod");

    // 2. Initialize Risk Engine
    std::cout << "[Main] Initializing Risk Engine..." << std::endl;
    exchange::RiskLimits default_limits;
    default_limits.max_position_per_symbol = 50000;
    default_limits.max_exposure_total = 100'000'000.0;
    default_limits.fat_finger_multiplier = 5.0;
    default_limits.circuit_breaker_pct = 20.0;
    default_limits.circuit_breaker_window_s = 300;
    auto risk_engine = std::make_unique<exchange::RiskEngine>(default_limits);

    // 3. Initialize Matching Engine
    std::cout << "[Main] Initializing Matching Engine..." << std::endl;
    auto matching_engine = std::make_unique<exchange::MatchingEngine>(symbols);

    // 4. Initialize gRPC Server
    std::cout << "[Main] Initializing gRPC Server on port " << grpc_port << "..." << std::endl;
    auto grpc_server = std::make_unique<exchange::GrpcServer>(grpc_port, *matching_engine, *risk_engine);

    // 5. Initialize Metrics Server
    std::cout << "[Main] Initializing Metrics Server on port " << metrics_port << "..." << std::endl;
    auto metrics_server = std::make_unique<exchange::MetricsServer>(metrics_port);

    // 6. Connect callbacks and hooks
    std::cout << "[Main] Wiring event callbacks..." << std::endl;

    // MatchingEngine -> Kafka, Risk, gRPC, and Metrics
    matching_engine->set_trade_callback([&](const exchange::ExecutedTrade& trade) {
        // Publish trade event to Kafka
        producer->publish_trade(trade);

        // Update positions/limits in risk engine
        risk_engine->on_trade(trade);

        // Record trade in gRPC service history
        grpc_server->service().record_trade(trade);
    });

    matching_engine->set_book_update_callback([&](const exchange::BookSnapshot& snap) {
        // Publish book update to Kafka
        producer->publish_book_update(snap, snap.seq_num);
    });

    // Setup Metrics Server endpoints/hooks
    exchange::MetricsServer::EngineCounters counters;
    counters.total_orders = &matching_engine->atomic_total_orders();
    counters.total_trades = &matching_engine->atomic_total_trades();
    counters.total_cancels = &matching_engine->atomic_total_cancels();
    counters.total_rejected = &matching_engine->atomic_total_rejected();
    metrics_server->set_engine_counters(counters);

    metrics_server->set_latency_fns(
        [&]() { return matching_engine->p50_ns(); },
        [&]() { return matching_engine->p95_ns(); },
        [&]() { return matching_engine->p99_ns(); },
        [&]() { return matching_engine->p999_ns(); }
    );

    metrics_server->set_book_depth_fn([&]() {
        std::unordered_map<std::string, std::pair<int, int>> depth_map;
        for (const auto& sym : symbols) {
            auto snap = matching_engine->get_book_snapshot(sym, 1);
            depth_map[sym] = std::make_pair(static_cast<int>(snap.bids.size()), static_cast<int>(snap.asks.size()));
        }
        return depth_map;
    });

    // 7. Start Services
    std::cout << "[Main] Starting Matching Engine thread loop..." << std::endl;
    matching_engine->start();

    std::cout << "[Main] Starting gRPC Server listener..." << std::endl;
    grpc_server->start();

    std::cout << "[Main] Starting Metrics HTTP Server..." << std::endl;
    metrics_server->start();

    // 8. Initialize and Start Market Simulator (Bots)
    std::cout << "[Main] Starting Market Simulator (Bots)..." << std::endl;
    // Callback to submit simulated orders to matching engine
    auto sim_submit_cb = [&](exchange::Order order) {
        // Perform pre-trade risk check on simulated orders
        exchange::RejectionReason rej = risk_engine->check(order);
        if (rej == ::exchange::REASON_NONE) {
            matching_engine->submit_order(std::move(order));
        } else {
            // Simulated order rejected by risk engine, no-op or metrics
        }
    };

    // Callback to get snapshots for bots to quote
    auto sim_get_book_cb = [&](const std::string& symbol) {
        return matching_engine->get_book_snapshot(symbol, 10);
    };

    auto simulator = std::make_unique<exchange::MarketSimulator>(
        symbols,
        sim_submit_cb,
        sim_get_book_cb,
        4, // retail bots
        3, // HFT bots
        2, // Market Makers
        1  // Institution bots
    );
    
    // Wire matching engine trades back to simulator to update bot pricing anchors
    matching_engine->set_trade_callback([&](const exchange::ExecutedTrade& trade) {
        producer->publish_trade(trade);
        risk_engine->on_trade(trade);
        grpc_server->service().record_trade(trade);
        simulator->on_trade(trade.symbol, trade.price);
    });

    simulator->start();

    std::cout << "[Main] System is fully operational. Press Ctrl+C to stop." << std::endl;

    // Keep running until signals tell us to stop
    while (g_running) {
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    std::cout << "[Main] Stopping Market Simulator..." << std::endl;
    simulator->stop();

    std::cout << "[Main] Stopping Metrics Server..." << std::endl;
    metrics_server->stop();

    std::cout << "[Main] Stopping gRPC Server..." << std::endl;
    grpc_server->stop();

    std::cout << "[Main] Stopping Matching Engine..." << std::endl;
    matching_engine->stop();

    std::cout << "[Main] Services stopped. Exiting." << std::endl;
    return 0;
}
