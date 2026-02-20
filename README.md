# 🌍 Multi-Region Property Listing Backend

A distributed, globally-resilient property listing system that simulates **US and EU** geographic regions using Docker Compose, NGINX, Apache Kafka, and PostgreSQL — with optimistic locking, idempotency, and cross-region replication.

---

## 📐 Architecture

```
                        ┌─────────────┐
         HTTP :8080     │             │
  Client ─────────────► │    NGINX    │  Reverse Proxy + Failover
                        │  :80        │
                        └──────┬──────┘
                               │
              ┌────────────────┴────────────────┐
              │  /us/*                 /eu/*     │
              ▼                                  ▼
     ┌─────────────────┐             ┌─────────────────┐
     │   backend-us    │             │   backend-eu    │
     │   FastAPI :8000 │             │   FastAPI :8000 │
     └────────┬────────┘             └────────┬────────┘
              │  asyncpg                       │  asyncpg
              ▼                                ▼
     ┌─────────────────┐             ┌─────────────────┐
     │     db-us       │             │     db-eu       │
     │  PostgreSQL 14  │             │  PostgreSQL 14  │
     └─────────────────┘             └─────────────────┘
              │                                │
              └──────────────┬─────────────────┘
                             │  Kafka  (property-updates topic)
                    ┌────────┴────────┐
                    │      Kafka      │
                    │  + Zookeeper    │
                    └─────────────────┘
```

**Failover:** If `backend-us` goes down, NGINX automatically routes `/us/*` traffic to `backend-eu` (and vice-versa).

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Git, curl, bash

### 1. Clone and configure
```bash
git clone https://github.com/yaswanthpentakota/Multi-Region-Property-.git
cd "Multi-Region-Property-"
cp .env.example .env   # edit if needed
```

### 2. Start all services
```bash
docker-compose up -d
```

> Wait ~90 seconds for all services to become healthy (Kafka takes the longest).

### 3. Verify health
```bash
curl http://localhost:8080/us/health
# {"status":"ok","region":"us"}

curl http://localhost:8080/eu/health
# {"status":"ok","region":"eu"}
```

---

## 📡 API Reference

### Health Check
```
GET /health
```
Response:
```json
{ "status": "ok", "region": "us" }
```

### Update Property
```
PUT /{region}/properties/{id}
Headers: X-Request-ID: <uuid>  (required for idempotency)
         Content-Type: application/json
Body:    { "price": 500000.00, "version": 1 }
```
Response (200 OK):
```json
{
  "id": 1,
  "price": 500000.00,
  "bedrooms": 3,
  "bathrooms": 2,
  "region_origin": "us",
  "version": 2,
  "updated_at": "2024-01-01T12:00:00.000000"
}
```

### Replication Lag
```
GET /{region}/replication-lag
```
Response:
```json
{ "lag_seconds": 1.234 }
```

---

## 🔒 Key Concepts

### Optimistic Locking
Every property has a `version` field. A PUT request must supply the current version:

- **Match** → update succeeds, version incremented to `version + 1`
- **Mismatch** → `409 Conflict` returned

**Conflict resolution guidance for clients:**
1. Receive `409 Conflict`
2. Re-fetch the property to get the latest `version`
3. Apply your changes to the latest data
4. Retry the PUT with the new `version`

This prevents lost updates in concurrent scenarios.

### Idempotency
All PUT requests should include an `X-Request-ID` header (UUID):

- **First request** with a given ID → processed normally (200)
- **Duplicate request** with the same ID → rejected with `422 Unprocessable Entity`

This protects against duplicate processing caused by client retries.

### Cross-Region Replication
When a property is updated in region A:
1. The change is committed to the local DB
2. An event is published to Kafka topic `property-updates`
3. The consumer in region B reads the event, filters out its own region's events, and applies the update to its local DB

---

## 🧪 Testing

### Optimistic Locking + Idempotency Tests
```bash
pip install requests
python tests/test_optimistic_locking.py
```

### Failover Demonstration
```bash
bash tests/demonstrate_failover.sh
```

This script:
1. Confirms both backends are healthy
2. Makes a request to `/us/health`
3. Stops `backend-us` container
4. Shows `/us/health` is still **200 OK** (served by `backend-eu`)
5. Restarts `backend-us`

---

## 🔧 Useful Commands

```bash
# View NGINX logs (includes upstream_response_time)
docker logs nginx_proxy

# Connect to US database
docker exec -it db_us psql -U propuser -d properties

# Connect to EU database
docker exec -it db_eu psql -U propuser -d properties

# Check property count
SELECT COUNT(*) FROM properties;

# Consume Kafka messages manually
docker exec -it kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic property-updates \
  --from-beginning

# Stop US backend (simulate failure)
docker stop backend_us

# Restart all services
docker-compose restart
```

---

## 📋 Environment Variables

See [`.env.example`](.env.example) for all required variables:

| Variable | Description | Default |
|---|---|---|
| `POSTGRES_USER` | PostgreSQL username | `propuser` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `proppassword` |
| `POSTGRES_DB` | Database name | `properties` |
| `KAFKA_BROKER` | Kafka broker address | `kafka:29092` |

---

## 📁 Project Structure

```
.
├── docker-compose.yml          # All 7 services with health checks
├── .env.example                # Environment variable documentation
├── nginx/
│   └── nginx.conf              # Reverse proxy + failover + custom logs
├── app/                        # Shared FastAPI backend
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # App entry point + Kafka consumer startup
│   ├── config.py               # Env-based configuration
│   ├── database.py             # asyncpg connection pool
│   ├── models.py               # Pydantic schemas
│   ├── kafka_producer.py       # Publishes to property-updates topic
│   ├── kafka_consumer.py       # Replicates from other region
│   └── routes/
│       ├── health.py           # GET /health
│       ├── properties.py       # PUT /{region}/properties/{id}
│       └── replication_lag.py  # GET /replication-lag
├── seeds/
│   ├── init-us.sql             # US DB schema + 1500 rows (region_origin='us')
│   └── init-eu.sql             # EU DB schema + 1500 rows (region_origin='eu')
└── tests/
    ├── test_optimistic_locking.py   # Integration tests
    └── demonstrate_failover.sh      # Automated failover demo
```
