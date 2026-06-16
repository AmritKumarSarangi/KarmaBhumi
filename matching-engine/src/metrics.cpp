#include "metrics.hpp"

#include <algorithm>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <iostream>
#include <numeric>
#include <sstream>

// POSIX socket includes (available on Linux in Docker)
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

namespace exchange {

// ============================================================
// Histogram
// ============================================================

Histogram::Histogram(std::vector<double> buckets)
    : bounds_(std::move(buckets)),
      counts_(bounds_.size() + 1, 0) {
    std::sort(bounds_.begin(), bounds_.end());
}

void Histogram::observe(double value) {
    std::lock_guard lk(mu_);
    sum_   += value;
    count_ += 1;
    // Find the first bucket whose upper bound >= value
    for (size_t i = 0; i < bounds_.size(); ++i) {
        if (value <= bounds_[i]) {
            // Increment this and all higher buckets (cumulative)
            for (size_t j = i; j < counts_.size(); ++j) ++counts_[j];
            return;
        }
    }
    // Falls into +Inf bucket only
    ++counts_.back();
}

double Histogram::sum() const {
    std::lock_guard lk(mu_);
    return sum_;
}

uint64_t Histogram::count() const {
    std::lock_guard lk(mu_);
    return count_;
}

std::string Histogram::to_prometheus(const std::string& name,
                                      const std::string& help,
                                      const std::string& labels) const {
    std::lock_guard lk(mu_);
    std::ostringstream ss;
    ss << "# HELP " << name << " " << help << "\n"
       << "# TYPE " << name << " histogram\n";

    std::string label_prefix = labels.empty() ? "" : ("," + labels);

    for (size_t i = 0; i < bounds_.size(); ++i) {
        ss << name << "_bucket{le=\"" << bounds_[i] << "\"" << label_prefix << "} "
           << counts_[i] << "\n";
    }
    ss << name << "_bucket{le=\"+Inf\"" << label_prefix << "} "
       << counts_.back() << "\n";
    ss << name << "_sum"   << (labels.empty() ? "" : "{" + labels + "}") << " " << sum_ << "\n";
    ss << name << "_count" << (labels.empty() ? "" : "{" + labels + "}") << " " << count_ << "\n";

    return ss.str();
}

// ============================================================
// MetricsServer
// ============================================================

MetricsServer::MetricsServer(int port)
    : port_(port),
      latency_hist_({100, 500, 1000, 5000, 10000, 50000, 100000, 500000, 1000000}) {}

MetricsServer::~MetricsServer() { stop(); }

void MetricsServer::start() {
    running_ = true;
    thread_  = std::thread([this] { server_loop(); });
    std::cout << "[Metrics] HTTP server starting on port " << port_ << "\n";
}

void MetricsServer::stop() {
    running_ = false;
    if (server_fd_ >= 0) {
        ::shutdown(server_fd_, SHUT_RDWR);
        ::close(server_fd_);
        server_fd_ = -1;
    }
    if (thread_.joinable()) thread_.join();
}

// ============================================================
// Server loop — minimal blocking I/O
// ============================================================

void MetricsServer::server_loop() {
    server_fd_ = ::socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd_ < 0) {
        std::cerr << "[Metrics] socket() failed: " << strerror(errno) << "\n";
        return;
    }

    int opt = 1;
    ::setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port        = htons(static_cast<uint16_t>(port_));

    if (::bind(server_fd_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        std::cerr << "[Metrics] bind() failed: " << strerror(errno) << "\n";
        ::close(server_fd_);
        server_fd_ = -1;
        return;
    }

    if (::listen(server_fd_, 10) < 0) {
        std::cerr << "[Metrics] listen() failed: " << strerror(errno) << "\n";
        ::close(server_fd_);
        server_fd_ = -1;
        return;
    }

    std::cout << "[Metrics] Listening on port " << port_ << "\n";

    while (running_) {
        sockaddr_in client{};
        socklen_t   client_len = sizeof(client);
        int client_fd = ::accept(server_fd_,
                                  reinterpret_cast<sockaddr*>(&client),
                                  &client_len);
        if (client_fd < 0) {
            if (running_) {
                std::cerr << "[Metrics] accept() error: " << strerror(errno) << "\n";
            }
            break;
        }

        // Read request (blocking, up to 4KB)
        char buf[4096] = {};
        ssize_t n = ::recv(client_fd, buf, sizeof(buf) - 1, 0);
        if (n > 0) {
            std::string req(buf, static_cast<size_t>(n));
            std::string response;

            if (req.find("GET /metrics") != std::string::npos) {
                std::string body = handle_metrics();
                response = build_response(200, "text/plain; version=0.0.4; charset=utf-8", body);
            } else if (req.find("GET /health") != std::string::npos) {
                std::string body = handle_health();
                response = build_response(200, "application/json", body);
            } else {
                response = build_response(404, "text/plain", "Not Found");
            }

            ::send(client_fd, response.data(), response.size(), 0);
        }

        ::close(client_fd);
    }
}

// ============================================================
// Metrics output (Prometheus text format)
// ============================================================

std::string MetricsServer::handle_metrics() const {
    std::ostringstream ss;

    // Counters
    ss << "# HELP exchange_orders_total Total orders received\n"
       << "# TYPE exchange_orders_total counter\n";
    if (counters_.total_orders)
        ss << "exchange_orders_total " << counters_.total_orders->load() << "\n";

    ss << "# HELP exchange_trades_total Total trades executed\n"
       << "# TYPE exchange_trades_total counter\n";
    if (counters_.total_trades)
        ss << "exchange_trades_total " << counters_.total_trades->load() << "\n";

    ss << "# HELP exchange_cancels_total Total orders cancelled\n"
       << "# TYPE exchange_cancels_total counter\n";
    if (counters_.total_cancels)
        ss << "exchange_cancels_total " << counters_.total_cancels->load() << "\n";

    ss << "# HELP exchange_rejected_total Total orders rejected\n"
       << "# TYPE exchange_rejected_total counter\n";
    if (counters_.total_rejected)
        ss << "exchange_rejected_total " << counters_.total_rejected->load() << "\n";

    // Latency histogram
    ss << latency_hist_.to_prometheus(
        "exchange_matching_latency_ns",
        "Order matching latency in nanoseconds");

    // Latency gauges from engine
    ss << "# HELP exchange_latency_p50_ns P50 matching latency nanoseconds\n"
       << "# TYPE exchange_latency_p50_ns gauge\n";
    if (p50_fn_) ss << "exchange_latency_p50_ns " << p50_fn_() << "\n";

    ss << "# HELP exchange_latency_p95_ns P95 matching latency nanoseconds\n"
       << "# TYPE exchange_latency_p95_ns gauge\n";
    if (p95_fn_) ss << "exchange_latency_p95_ns " << p95_fn_() << "\n";

    ss << "# HELP exchange_latency_p99_ns P99 matching latency nanoseconds\n"
       << "# TYPE exchange_latency_p99_ns gauge\n";
    if (p99_fn_) ss << "exchange_latency_p99_ns " << p99_fn_() << "\n";

    ss << "# HELP exchange_latency_p999_ns P999 matching latency nanoseconds\n"
       << "# TYPE exchange_latency_p999_ns gauge\n";
    if (p999_fn_) ss << "exchange_latency_p999_ns " << p999_fn_() << "\n";

    // Book depth gauges
    if (book_depth_fn_) {
        auto depths = book_depth_fn_();
        ss << "# HELP exchange_order_book_depth Number of price levels per side\n"
           << "# TYPE exchange_order_book_depth gauge\n";
        for (const auto& [sym, sides] : depths) {
            ss << "exchange_order_book_depth{symbol=\"" << sym << "\",side=\"bid\"} "
               << sides.first << "\n";
            ss << "exchange_order_book_depth{symbol=\"" << sym << "\",side=\"ask\"} "
               << sides.second << "\n";
        }
    }

    // Uptime
    ss << "# HELP exchange_uptime_seconds Seconds since engine start\n"
       << "# TYPE exchange_uptime_seconds gauge\n"
       << "exchange_uptime_seconds " << uptime_seconds() << "\n";

    return ss.str();
}

std::string MetricsServer::handle_health() const {
    std::ostringstream ss;
    ss << "{\"status\":\"ok\",\"uptime_seconds\":" << uptime_seconds() << "}";
    return ss.str();
}

std::string MetricsServer::build_response(int status,
                                           const std::string& content_type,
                                           const std::string& body) {
    std::string status_text = (status == 200) ? "OK"
                            : (status == 404) ? "Not Found"
                                              : "Internal Server Error";
    std::ostringstream ss;
    ss << "HTTP/1.1 " << status << " " << status_text << "\r\n"
       << "Content-Type: " << content_type << "\r\n"
       << "Content-Length: " << body.size() << "\r\n"
       << "Connection: close\r\n"
       << "\r\n"
       << body;
    return ss.str();
}

} // namespace exchange
