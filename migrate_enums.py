import os
import re

src_dir = r"e:\exchangeX\matching-engine\src"

# Files to process (all except types.hpp which we already rewrote)
files = [
    "order_book.hpp", "order_book.cpp",
    "matching_engine.hpp", "matching_engine.cpp",
    "risk_engine.hpp", "risk_engine.cpp",
    "grpc_server.hpp", "grpc_server.cpp",
    "metrics.hpp", "metrics.cpp",
    "kafka_producer.hpp", "kafka_producer.cpp",
    "market_simulator.hpp",
    "main.cpp",
]

# Mapping from old enum class values to protobuf enum values (plain int)
replacements = {
    # Side
    "Side::UNKNOWN": "::exchange::SIDE_UNKNOWN",
    "Side::BUY":     "::exchange::BUY",
    "Side::SELL":    "::exchange::SELL",
    
    # OrderType
    "OrderType::UNKNOWN":    "::exchange::ORDER_TYPE_UNKNOWN",
    "OrderType::LIMIT":      "::exchange::LIMIT",
    "OrderType::MARKET":     "::exchange::MARKET",
    "OrderType::STOP_LOSS":  "::exchange::STOP_LOSS",
    "OrderType::STOP_LIMIT": "::exchange::STOP_LIMIT",
    "OrderType::IOC":        "::exchange::IOC",
    "OrderType::FOK":        "::exchange::FOK",
    "OrderType::GTT":        "::exchange::GTT",
    
    # OrderStatus
    "OrderStatus::UNKNOWN":      "::exchange::STATUS_UNKNOWN",
    "OrderStatus::ACCEPTED":     "::exchange::ACCEPTED",
    "OrderStatus::REJECTED":     "::exchange::REJECTED",
    "OrderStatus::FILLED":       "::exchange::FILLED",
    "OrderStatus::PARTIAL_FILL": "::exchange::PARTIAL_FILL",
    "OrderStatus::CANCELLED":    "::exchange::CANCELLED",
    "OrderStatus::EXPIRED":      "::exchange::EXPIRED",
    "OrderStatus::PENDING":      "::exchange::PENDING",
    
    # RejectionReason
    "RejectionReason::NONE":                    "::exchange::REASON_NONE",
    "RejectionReason::INSUFFICIENT_FUNDS":      "::exchange::INSUFFICIENT_FUNDS",
    "RejectionReason::POSITION_LIMIT_EXCEEDED": "::exchange::POSITION_LIMIT_EXCEEDED",
    "RejectionReason::EXPOSURE_LIMIT_EXCEEDED": "::exchange::EXPOSURE_LIMIT_EXCEEDED",
    "RejectionReason::FAT_FINGER_DETECTED":     "::exchange::FAT_FINGER_DETECTED",
    "RejectionReason::CIRCUIT_BREAKER_ACTIVE":  "::exchange::CIRCUIT_BREAKER_ACTIVE",
    "RejectionReason::MARKET_HALTED":           "::exchange::MARKET_HALTED",
    "RejectionReason::INVALID_ORDER":           "::exchange::INVALID_ORDER",
    "RejectionReason::FOK_NOT_FILLABLE":        "::exchange::FOK_NOT_FILLABLE",
    "RejectionReason::SYMBOL_NOT_FOUND":        "::exchange::SYMBOL_NOT_FOUND",
}

# Type replacements in declarations
type_replacements = {
    # In function signatures and variable declarations
    "exchange::RejectionReason": "int",
    "RejectionReason ": "int ",
    "OrderStatus ":     "int ",
}

for filename in files:
    filepath = os.path.join(src_dir, filename)
    if not os.path.exists(filepath):
        print(f"  SKIP (not found): {filename}")
        continue
    
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    original = content
    
    # Sort replacements by length (longest first) to avoid partial matches
    sorted_reps = sorted(replacements.items(), key=lambda x: len(x[0]), reverse=True)
    
    for old, new in sorted_reps:
        content = content.replace(old, new)
    
    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  UPDATED: {filename}")
    else:
        print(f"  no change: {filename}")

print("\nDone! Enum migration complete.")
