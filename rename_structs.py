import os
import re

src_dir = r"e:\exchangeX\matching-engine\src"

files_to_edit = [
    "types.hpp",
    "main.cpp",
    "matching_engine.hpp",
    "matching_engine.cpp",
    "order_book.hpp",
    "order_book.cpp",
    "grpc_server.hpp",
    "grpc_server.cpp",
    "metrics.hpp",
    "metrics.cpp",
    "market_simulator.hpp",
    "market_simulator.cpp",
]

for filename in files_to_edit:
    filepath = os.path.join(src_dir, filename)
    if not os.path.exists(filepath):
        continue
        
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # We want to replace PriceLevel -> BookLevel, OrderBookSnapshot -> BookSnapshot, MarketStats -> InternalMarketStats
    # But ONLY the internal ones, NOT the ones from exchange:: or ::exchange:: protobuf types.
    
    # Temporarily hide protobuf types
    content = content.replace("::exchange::OrderBookSnapshot", "PROTO_OBS_TEMP")
    content = content.replace("exchange::OrderBookSnapshot", "PROTO_OBS_TEMP")
    content = content.replace("::exchange::PriceLevel", "PROTO_PL_TEMP")
    content = content.replace("exchange::PriceLevel", "PROTO_PL_TEMP")
    content = content.replace("::exchange::MarketStats", "PROTO_MS_TEMP")
    content = content.replace("exchange::MarketStats", "PROTO_MS_TEMP")
    
    # Now do the internal replacements
    content = re.sub(r'\bPriceLevel\b', 'BookLevel', content)
    content = re.sub(r'\bOrderBookSnapshot\b', 'BookSnapshot', content)
    content = re.sub(r'\bMarketStats\b', 'InternalMarketStats', content)
    
    # Restore protobuf types
    content = content.replace("PROTO_OBS_TEMP", "::exchange::OrderBookSnapshot")
    content = content.replace("PROTO_PL_TEMP", "::exchange::PriceLevel")
    content = content.replace("PROTO_MS_TEMP", "::exchange::MarketStats")
    
    # Fix the std::make_pair we just added in main.cpp if it's there
    content = content.replace(
        "depth_map[sym] = std::make_pair(static_cast<int>(snap.bids.size()), static_cast<int>(snap.asks.size()));",
        "depth_map[sym] = {static_cast<int>(snap.bids.size()), static_cast<int>(snap.asks.size())};"
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

print("Renaming completed successfully.")
