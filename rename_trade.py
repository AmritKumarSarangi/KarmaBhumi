import os
import re

src_dir = r"e:\exchangeX\matching-engine\src"

files_to_edit = [
    "types.hpp",
    "main.cpp",
    "matching_engine.hpp",
    "matching_engine.cpp",
    "risk_engine.hpp",
    "risk_engine.cpp",
    "market_simulator.hpp",
    "grpc_server.hpp",
    "grpc_server.cpp",
    "kafka_producer.hpp",
    "kafka_producer.cpp",
]

def rename_trade(content):
    # First, mask `::exchange::Trade` and `exchange::Trade` (protobuf) if any, but wait, 
    # in main.cpp, `const exchange::Trade&` refers to the internal one!
    # Because there is `using namespace exchange;` or something? No, main.cpp is outside namespace exchange.
    
    # We want to replace the exact token `Trade` with `ExecutedTrade`
    # EXCEPT when it is `::exchange::Trade` (which is proto).
    
    # Mask proto type
    content = content.replace("::exchange::Trade", "PROTO_TRADE_TEMP")
    content = content.replace("TradeHistory", "TRADE_HIST_TEMP")
    content = content.replace("TradeCallback", "TRADE_CB_TEMP")
    content = content.replace("LastTrade", "LAST_TRADE_TEMP")
    
    # For main.cpp specifically: `const exchange::Trade&` -> `const exchange::ExecutedTrade&`
    content = content.replace("exchange::Trade", "exchange::ExecutedTrade")
    
    # In types.hpp: struct Trade { -> struct ExecutedTrade {
    content = content.replace("struct Trade {", "struct ExecutedTrade {")
    
    # std::vector<Trade> -> std::vector<ExecutedTrade>
    content = content.replace("std::vector<Trade>", "std::vector<ExecutedTrade>")
    
    # std::deque<Trade> -> std::deque<ExecutedTrade>
    content = content.replace("std::deque<Trade>", "std::deque<ExecutedTrade>")
    
    # const Trade& -> const ExecutedTrade&
    content = content.replace("const Trade&", "const ExecutedTrade&")
    
    # Trade t; -> ExecutedTrade t;
    content = content.replace("Trade t;", "ExecutedTrade t;")
    
    # Trade t = -> ExecutedTrade t =
    content = content.replace("Trade t =", "ExecutedTrade t =")
    
    # Restore masks
    content = content.replace("PROTO_TRADE_TEMP", "::exchange::Trade")
    content = content.replace("TRADE_HIST_TEMP", "TradeHistory")
    content = content.replace("TRADE_CB_TEMP", "TradeCallback")
    content = content.replace("LAST_TRADE_TEMP", "LastTrade")
    
    return content

for fname in files_to_edit:
    fpath = os.path.join(src_dir, fname)
    if not os.path.exists(fpath):
        continue
    with open(fpath, "r", encoding="utf-8") as f:
        original = f.read()
        
    modified = rename_trade(original)
    
    if original != modified:
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(modified)
        print(f"Updated {fname}")

print("Done.")
