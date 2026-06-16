#pragma once

#include <atomic>
#include <functional>
#include <mutex>
#include <string>
#include <thread>

// Forward-declare librdkafka C types
struct rd_kafka_s;
typedef struct rd_kafka_s rd_kafka_t;
struct rd_kafka_topic_s;
typedef struct rd_kafka_topic_s rd_kafka_topic_t;
struct rd_kafka_conf_s;
typedef struct rd_kafka_conf_s rd_kafka_conf_t;

namespace exchange {

struct ExecutedTrade;
struct BookSnapshot;

// ============================================================
// KafkaProducer — thin wrapper around librdkafka C API
// Fire-and-forget async publishing with poll thread for
// delivery confirmations.
// ============================================================

class KafkaProducer {
public:
    KafkaProducer(const std::string& brokers,
                  const std::string& client_id);
    ~KafkaProducer();

    // Disable copy
    KafkaProducer(const KafkaProducer&)            = delete;
    KafkaProducer& operator=(const KafkaProducer&) = delete;

    // Fire-and-forget publish. Returns true if enqueued.
    bool publish(const std::string& topic,
                 const std::string& key,
                 const std::string& json_payload);

    // Convenience serialisers
    bool publish_trade(const ExecutedTrade& trade);
    bool publish_book_update(const BookSnapshot& snap, int64_t seq_num);

    // Statistics
    int64_t messages_produced() const { return messages_produced_.load(); }
    int64_t messages_failed()   const { return messages_failed_.load();   }

    bool is_connected() const { return connected_; }

private:
    void poll_loop();
    static std::string trade_to_json(const ExecutedTrade& trade);
    static std::string book_to_json(const BookSnapshot& snap, int64_t seq_num);

    rd_kafka_t* rk_     = nullptr;
    bool        connected_ = false;

    // Poll thread
    std::thread          poll_thread_;
    std::atomic<bool>    running_{false};

    std::atomic<int64_t> messages_produced_{0};
    std::atomic<int64_t> messages_failed_{0};
};

} // namespace exchange
