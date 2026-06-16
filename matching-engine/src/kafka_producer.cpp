#include "kafka_producer.hpp"
#include "types.hpp"

#include <chrono>
#include <cstring>
#include <iostream>
#include <sstream>
#include <iomanip>

// librdkafka C API
#include <librdkafka/rdkafka.h>

namespace exchange {

// ============================================================
// Delivery-report callback — called by librdkafka poll
// ============================================================

static void dr_msg_cb(rd_kafka_t* /*rk*/,
                      const rd_kafka_message_t* rkmessage,
                      void* opaque) {
    if (!opaque) return;
    auto* producer = static_cast<KafkaProducer*>(opaque);

    if (rkmessage->err) {
        // Delivery failure
        // producer->messages_failed_.fetch_add(1, std::memory_order_relaxed);
        std::cerr << "[Kafka] Delivery failed: "
                  << rd_kafka_err2str(rkmessage->err) << "\n";
    }
    // Note: messages_produced_ is incremented at enqueue time (fire-and-forget).
}

// ============================================================
// Ctor
// ============================================================

KafkaProducer::KafkaProducer(const std::string& brokers,
                               const std::string& client_id) {
    char errstr[512];

    rd_kafka_conf_t* conf = rd_kafka_conf_new();

    // Delivery report callback
    rd_kafka_conf_set_dr_msg_cb(conf, dr_msg_cb);
    rd_kafka_conf_set_opaque(conf, this);

    // Broker list
    if (rd_kafka_conf_set(conf, "bootstrap.servers", brokers.c_str(),
                          errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        rd_kafka_conf_destroy(conf);
        std::cerr << "[Kafka] bootstrap.servers error: " << errstr << "\n";
        return;
    }

    // Client ID
    if (rd_kafka_conf_set(conf, "client.id", client_id.c_str(),
                          errstr, sizeof(errstr)) != RD_KAFKA_CONF_OK) {
        rd_kafka_conf_destroy(conf);
        std::cerr << "[Kafka] client.id error: " << errstr << "\n";
        return;
    }

    // Performance tuning
    rd_kafka_conf_set(conf, "queue.buffering.max.messages", "1000000",
                      errstr, sizeof(errstr));
    rd_kafka_conf_set(conf, "queue.buffering.max.ms", "5",
                      errstr, sizeof(errstr));
    rd_kafka_conf_set(conf, "batch.num.messages", "10000",
                      errstr, sizeof(errstr));
    rd_kafka_conf_set(conf, "compression.codec", "snappy",
                      errstr, sizeof(errstr));

    rk_ = rd_kafka_new(RD_KAFKA_PRODUCER, conf, errstr, sizeof(errstr));
    if (!rk_) {
        std::cerr << "[Kafka] Failed to create producer: " << errstr << "\n";
        // conf is consumed by rd_kafka_new on success but we need to destroy on failure
        // Actually rd_kafka_new takes ownership; if it fails conf may or may not be freed.
        // Safe to call destroy only if rk_ is null AND conf was not consumed.
        // Per librdkafka docs: conf is ALWAYS consumed by rd_kafka_new, even on failure.
        return;
    }

    connected_ = true;
    running_   = true;
    poll_thread_ = std::thread([this] { poll_loop(); });

    std::cout << "[Kafka] Producer connected to: " << brokers
              << " (client: " << client_id << ")\n";
}

KafkaProducer::~KafkaProducer() {
    running_ = false;

    if (rk_) {
        // Flush outstanding messages (max 5 seconds)
        rd_kafka_flush(rk_, 5000);
    }

    if (poll_thread_.joinable()) poll_thread_.join();

    if (rk_) {
        rd_kafka_destroy(rk_);
        rk_ = nullptr;
    }
}

// ============================================================
// Poll loop — drains delivery report queue
// ============================================================

void KafkaProducer::poll_loop() {
    while (running_) {
        if (rk_) {
            rd_kafka_poll(rk_, 100 /*ms*/);
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
    }
    // Final drain
    if (rk_) rd_kafka_poll(rk_, 0);
}

// ============================================================
// publish — fire and forget
// ============================================================

bool KafkaProducer::publish(const std::string& topic,
                              const std::string& key,
                              const std::string& json_payload) {
    if (!rk_ || !connected_) {
        messages_failed_.fetch_add(1, std::memory_order_relaxed);
        return false;
    }

    rd_kafka_resp_err_t err = rd_kafka_producev(
        rk_,
        RD_KAFKA_V_TOPIC(topic.c_str()),
        RD_KAFKA_V_KEY(key.data(), key.size()),
        RD_KAFKA_V_VALUE(
            const_cast<char*>(json_payload.data()),
            json_payload.size()),
        RD_KAFKA_V_MSGFLAGS(RD_KAFKA_MSG_F_COPY),
        RD_KAFKA_V_END);

    if (err != RD_KAFKA_RESP_ERR_NO_ERROR) {
        messages_failed_.fetch_add(1, std::memory_order_relaxed);
        if (err == RD_KAFKA_RESP_ERR__QUEUE_FULL) {
            // Backpressure: poll once to drain
            rd_kafka_poll(rk_, 0);
        }
        return false;
    }

    messages_produced_.fetch_add(1, std::memory_order_relaxed);
    return true;
}

// ============================================================
// Convenience: Trade
// ============================================================

bool KafkaProducer::publish_trade(const ExecutedTrade& trade) {
    return publish("trades", trade.symbol, trade_to_json(trade));
}

bool KafkaProducer::publish_book_update(const BookSnapshot& snap,
                                         int64_t seq_num) {
    return publish("order-book-updates", snap.symbol, book_to_json(snap, seq_num));
}

// ============================================================
// JSON serialisers — hand-written (no external dependency)
// ============================================================

static std::string escape_json_str(const std::string& s) {
    std::string out;
    out.reserve(s.size() + 4);
    for (char c : s) {
        if (c == '"')  { out += "\\\""; }
        else if (c == '\\') { out += "\\\\"; }
        else if (c == '\n') { out += "\\n"; }
        else if (c == '\r') { out += "\\r"; }
        else if (c == '\t') { out += "\\t"; }
        else { out += c; }
    }
    return out;
}

std::string KafkaProducer::trade_to_json(const ExecutedTrade& t) {
    std::ostringstream ss;
    ss << std::fixed << std::setprecision(6);
    ss << "{\"trade_id\":\"" << escape_json_str(t.trade_id) << "\""
       << ",\"symbol\":\""   << escape_json_str(t.symbol) << "\""
       << ",\"price\":"      << t.price
       << ",\"quantity\":"   << t.quantity
       << ",\"buy_order_id\":\"" << escape_json_str(t.buy_order_id) << "\""
       << ",\"sell_order_id\":\""<< escape_json_str(t.sell_order_id)<< "\""
       << ",\"buyer_user_id\":\"" << escape_json_str(t.buyer_user_id) << "\""
       << ",\"seller_user_id\":\""<< escape_json_str(t.seller_user_id)<< "\""
       << ",\"timestamp_ns\":"   << t.timestamp_ns
       << "}";
    return ss.str();
}

std::string KafkaProducer::book_to_json(const BookSnapshot& snap,
                                         int64_t seq_num) {
    std::ostringstream ss;
    ss << std::fixed << std::setprecision(6);
    ss << "{\"symbol\":\""  << escape_json_str(snap.symbol) << "\""
       << ",\"seq_num\":"   << seq_num
       << ",\"bids\":[";

    for (size_t i = 0; i < snap.bids.size(); ++i) {
        if (i > 0) ss << ",";
        ss << "{\"price\":" << snap.bids[i].price
           << ",\"qty\":"   << snap.bids[i].total_quantity << "}";
    }
    ss << "],\"asks\":[";
    for (size_t i = 0; i < snap.asks.size(); ++i) {
        if (i > 0) ss << ",";
        ss << "{\"price\":" << snap.asks[i].price
           << ",\"qty\":"   << snap.asks[i].total_quantity << "}";
    }
    ss << "],\"timestamp_ns\":" << snap.timestamp_ns << "}";
    return ss.str();
}

} // namespace exchange
