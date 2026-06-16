#pragma once

#include <atomic>
#include <chrono>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace exchange {

// ============================================================
// Histogram — Prometheus-compatible cumulative histogram
// ============================================================

class Histogram {
public:
    // buckets: upper bounds in nanoseconds
    explicit Histogram(std::vector<double> buckets);

    void observe(double value);

    // Returns Prometheus text lines for this histogram (no trailing newline)
    std::string to_prometheus(const std::string& name,
                               const std::string& help,
                               const std::string& labels = "") const;

    double sum()   const;
    uint64_t count() const;

private:
    std::vector<double>   bounds_;   // sorted upper bounds
    mutable std::mutex    mu_;
    std::vector<uint64_t> counts_;   // cumulative bucket counts
    double                sum_{0.0};
    uint64_t              count_{0};
};

// ============================================================
// MetricsServer — simple HTTP server on configurable port
// Exposes /metrics (Prometheus text) and /health (JSON)
// ============================================================

class MetricsServer {
public:
    // Atomic counter references are expected to be owned by the engine
    struct EngineCounters {
        const std::atomic<int64_t>* total_orders   = nullptr;
        const std::atomic<int64_t>* total_trades   = nullptr;
        const std::atomic<int64_t>* total_cancels  = nullptr;
        const std::atomic<int64_t>* total_rejected = nullptr;
    };

    using LatencyFn    = std::function<double()>;
    using BookDepthFn  = std::function<std::unordered_map<std::string,
                                          std::pair<int,int>>()>;  // symbol → {bid_depth, ask_depth}

    explicit MetricsServer(int port = 8080);
    ~MetricsServer();

    void set_engine_counters(EngineCounters counters) { counters_ = counters; }
    void set_latency_fns(LatencyFn p50, LatencyFn p95, LatencyFn p99, LatencyFn p999) {
        p50_fn_  = std::move(p50);
        p95_fn_  = std::move(p95);
        p99_fn_  = std::move(p99);
        p999_fn_ = std::move(p999);
    }
    void set_book_depth_fn(BookDepthFn fn) { book_depth_fn_ = std::move(fn); }

    // Call from matching engine on every trade to record latency
    void record_latency(double ns) { latency_hist_.observe(ns); }

    // Start listening
    void start();
    void stop();

    int64_t uptime_seconds() const {
        return std::chrono::duration_cast<std::chrono::seconds>(
                   std::chrono::steady_clock::now() - start_time_).count();
    }

private:
    void server_loop();

    // HTTP handling
    std::string handle_metrics() const;
    std::string handle_health()  const;

    // Socket helpers (POSIX)
    static std::string build_response(int status,
                                       const std::string& content_type,
                                       const std::string& body);

    int  port_;
    int  server_fd_ = -1;

    std::thread       thread_;
    std::atomic<bool> running_{false};

    EngineCounters counters_;
    LatencyFn      p50_fn_, p95_fn_, p99_fn_, p999_fn_;
    BookDepthFn    book_depth_fn_;

    Histogram latency_hist_;

    std::chrono::steady_clock::time_point start_time_{std::chrono::steady_clock::now()};
};

} // namespace exchange
