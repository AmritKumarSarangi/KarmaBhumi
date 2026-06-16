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
    "kafka_producer.hpp",
    "kafka_producer.cpp",
]

for filename in files_to_edit:
    filepath = os.path.join(src_dir, filename)
    if not os.path.exists(filepath):
        continue
        
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Hide protobuf types
    content = content.replace("::exchange::OrderBookSnapshot", "PROTO_OBS_TEMP")
    content = content.replace("exchange::OrderBookSnapshot", "PROTO_OBS_TEMP")
    content = content.replace("::exchange::PriceLevel", "PROTO_PL_TEMP")
    content = content.replace("exchange::PriceLevel", "PROTO_PL_TEMP")
    content = content.replace("::exchange::MarketStats", "PROTO_MS_TEMP")
    content = content.replace("exchange::MarketStats", "PROTO_MS_TEMP")
    
    # Do replacements
    content = re.sub(r'\bPriceLevel\b', 'BookLevel', content)
    content = re.sub(r'\bOrderBookSnapshot\b', 'BookSnapshot', content)
    content = re.sub(r'\bMarketStats\b', 'InternalMarketStats', content)
    
    # Restore protobuf types
    content = content.replace("PROTO_OBS_TEMP", "::exchange::OrderBookSnapshot")
    content = content.replace("PROTO_PL_TEMP", "::exchange::PriceLevel")
    content = content.replace("PROTO_MS_TEMP", "::exchange::MarketStats")
    
    # Fix the callback in main.cpp specifically:
    if filename == "main.cpp":
        content = content.replace("const ::exchange::OrderBookSnapshot& snap", "const BookSnapshot& snap")
        content = content.replace("const exchange::OrderBookSnapshot& snap", "const BookSnapshot& snap")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

print("Renaming including kafka completed successfully.")
