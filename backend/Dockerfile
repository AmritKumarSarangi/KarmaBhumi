# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install grpcio-tools and setuptools for protoc codegen
RUN pip install --no-cache-dir grpcio-tools==1.60.0 setuptools

# Generate gRPC Python stubs from the proto file
COPY proto/exchange.proto /proto/exchange.proto
RUN mkdir -p /app && python -m grpc_tools.protoc \
    --proto_path=/proto \
    --python_out=/app \
    --grpc_python_out=/app \
    /proto/exchange.proto

# Copy and install all requirements
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --ignore-installed --prefix=/install -r requirements.txt


# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy generated gRPC stubs from builder
COPY --from=builder /app /app

# ── Copy application source ───────────────────────────────────────────────────
COPY backend .

# Ensure generated stubs are importable
ENV PYTHONPATH=/app

# Non-root user for security
RUN useradd -m -u 1001 exchange
USER exchange

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
