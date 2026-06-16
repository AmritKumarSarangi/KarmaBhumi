# ============================================================
# Stage 1: Build binary
# ============================================================
FROM ubuntu:22.04 AS builder

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
    cmake \
    g++ \
    git \
    pkg-config \
    libgrpc++-dev \
    libprotobuf-dev \
    protobuf-compiler \
    protobuf-compiler-grpc \
    librdkafka-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy proto schema and C++ code
COPY proto/exchange.proto /app/proto/exchange.proto
COPY matching-engine/ /app/matching-engine/

# Build
WORKDIR /app/matching-engine
RUN mkdir build && cd build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release && \
    make -j$(nproc)

# ============================================================
# Stage 2: Runtime image
# ============================================================
FROM ubuntu:22.04 AS runner

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    libgrpc++-dev \
    libprotobuf-dev \
    librdkafka1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy build binary from stage 1
COPY --from=builder /app/matching-engine/build/exchange_engine /app/exchange_engine

# Exposed ports
EXPOSE 50051
EXPOSE 8080

# Run
CMD ["./exchange_engine"]
