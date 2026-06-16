# KarmaBhumi — High-Performance Mini Stock Exchange

```
                   KarmaBhumi
         ┌─────────────────────────┐
         │      React Dashboard    │
         └──────────┬──────────────┘
                    │
             WebSocket Feed
                    │
         ┌──────────▼──────────┐
         │     API Gateway     │
         └──────────┬──────────┘
                    │
       ┌────────────┼────────────┐
       │            │            │
       ▼            ▼            ▼
  Risk Engine   Matching      Market Data
                 Engine         Engine
       │            │            │
       └────────────┼────────────┘
                    ▼
            Event Bus (Kafka)
                    ▼
               PostgreSQL
```

KarmaBhumi is a real-time, event-driven mini stock exchange architecture styled after the epic battlefield of Kurukshetra. It represents the ultimate field of actions and duties (Karma), featuring a low-latency C++ matching engine, an async Python FastAPI gateway, real-time WebSocket distribution, and a highly responsive React dashboard themed with Mahabharat elements.

---

## Technical Highlights & Features

- **✓ 100,000+ Simulated Orders**: Validated with a multi-threaded load test script (`load_test.py`).
- **✓ C++20 Matching Engine**: Core order-book featuring price-time priority matching with O(log n) inserts.
- **✓ Dynamic Order Types**: Full support for `LIMIT`, `MARKET`, `IOC`, `FOK`, `STOP_LOSS`, and `GTT` orders.
- **✓ Pre-Trade Risk Engine**: Enforces position limits, exposure ceilings, fat-finger detection, and circuit breakers.
- **✓ Event-Sourced Persistence**: Every transition is stored as structured Kafka events into PostgreSQL.
- **✓ Live Order Book & Charting**: Up-to-the-millisecond WebSocket feeds pushing top-10 levels, live trades, and real-time TradingView Candlestick charts.
- **✓ Observability Stack**: Full metrics exporting to Prometheus and visual monitoring via Grafana.
- **✓ Multi-Persona Simulator**: Retail, HFT, Market Maker, and Institutional bots generating realistic order flow.

---

## Directory Layout

```
KarmaBhumi/
├── proto/                     # Protocol Buffers / gRPC contract
├── matching-engine/           # C++20 matching engine service
│   ├── src/                   # Matching engine source files
│   └── Dockerfile             # Multi-stage C++ builder
├── backend/                   # Python FastAPI REST/WS Gateway
│   ├── api/                   # Router endpoints and WebSocket manager
│   ├── db/                    # DB connection and Alembic migrations
│   └── Dockerfile             # FastAPI runtime setup
├── frontend/                  # React dashboard (Vite + TS)
│   ├── src/                   # React components, pages, custom hooks
│   └── Dockerfile             # Production build & Nginx container
├── monitoring/                # Prometheus & Grafana configurations
│   ├── prometheus.yml
│   └── grafana/               # Provisioned datasources and dashboards
└── scripts/                   # Data seeding and load test script
```

---

## Getting Started (Docker Compose)

Ensure you have **Docker** and **Docker Compose** installed. Then run:

```bash
# Clone and build all containers
docker-compose up -d --build
```

Docker Compose will build and launch 11 services:
- **postgres**: Relational database storage.
- **redis**: Fast caching layer for order book snapshots.
- **zookeeper** & **kafka**: Event-streaming pipeline.
- **kafka-init**: Topic provisioning script.
- **matching-engine**: Low-latency C++ execution core.
- **backend**: Python gateway serving WS/REST API.
- **frontend**: Nginx serving the React SPA dashboard.
- **prometheus**: Scrapes metrics from backend & engine.
- **grafana**: Pre-built operations dashboards.
- **kafka-ui**: Admin Web UI to inspect Kafka topics.

---

## Service Access Endpoints

| Service | Address | Credentials (if applicable) |
|---|---|---|
| **Web Dashboard** | [http://localhost:3000](http://localhost:3000) | Log in using seed credentials below |
| **API Gateway** | [http://localhost:8000](http://localhost:8000) | REST API & WS Gateway |
| **Grafana Dashboard** | [http://localhost:3001](http://localhost:3001) | Anonymous Admin access enabled |
| **Prometheus UI** | [http://localhost:9090](http://localhost:9090) | Scraping statuses & target query |
| **Kafka Web UI** | [http://localhost:8090](http://localhost:8090) | Visualise Kafka events & lag |

---

## Seeding & Load Testing

After the docker services are healthy, run migrations and execute the helper scripts:

### 1. Database Migrations
The database schema will automatically initialize, but you can run migrations manually inside the backend container if needed.

### 2. Seed Initial User Data
Creates test accounts and places initial orders:
```bash
# Run the seed script locally or inside container
python scripts/seed_data.py
```

**Seed Credentials**:
- **Krishna (Admin)**: `krishna@karmabhumi.com` / `KrishnaPassword123!`
- **Arjuna (Trader 1)**: `arjuna@karmabhumi.com` / `ArjunaPassword123!`
- **Karna (Trader 2)**: `karna@karmabhumi.com` / `KarnaPassword123!`

### 3. Load Test (100k Orders)
Run the load testing script to stress test the matching loop:
```bash
python scripts/load_test.py
```
This script spawns 50 concurrent workers submitting a total of 100,000 orders to measure maximum throughput and verify matching resilience.
