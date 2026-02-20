#!/usr/bin/env python3
"""
Integration tests: Optimistic locking & Idempotency validation.

Tests:
  1. Concurrent PUTs to the same property → one 200, one 409
  2. Sequential version conflict → second PUT with stale version → 409
  3. Duplicate X-Request-ID → second PUT → 422

Usage:
    pip install requests
    docker-compose up -d        # wait ~90 seconds
    python tests/test_optimistic_locking.py
"""

import sys
import uuid
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "http://localhost:8080"

GREEN  = "\033[0;32m"
RED    = "\033[0;31m"
YELLOW = "\033[1;33m"
NC     = "\033[0m"

def passed(msg): print(f"{GREEN}[PASS]{NC} {msg}")
def failed(msg): print(f"{RED}[FAIL]{NC} {msg}")
def info(msg):   print(f"{YELLOW}[INFO]{NC} {msg}")
def sep():       print(f"\n{YELLOW}{'='*56}{NC}\n")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def get_property(region: str, prop_id: int) -> dict:
    r = requests.get(f"{BASE_URL}/{region}/properties/{prop_id}", timeout=10)
    if not r.ok:
        raise RuntimeError(f"GET /{region}/properties/{prop_id} → HTTP {r.status_code}: {r.text}")
    return r.json()


def put_property(region: str, prop_id: int, version: int, price: float) -> requests.Response:
    return requests.put(
        f"{BASE_URL}/{region}/properties/{prop_id}",
        json={"price": price, "version": version},
        headers={
            "X-Request-ID":   str(uuid.uuid4()),
            "Content-Type":   "application/json",
        },
        timeout=15,
    )


# ─────────────────────────────────────────────────────────────
# Test 1 – Concurrent optimistic locking
# ─────────────────────────────────────────────────────────────

def test_concurrent_updates():
    sep()
    info("TEST 1: Concurrent Optimistic Locking (race condition simulation)")

    PROP_ID = 10

    # Get live current version
    prop = get_property("us", PROP_ID)
    current_version = prop["version"]
    info(f"Property {PROP_ID} current version = {current_version}")

    info("Launching 2 concurrent PUTs with the same version …")
    results = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [
            ex.submit(put_property, "us", PROP_ID, current_version, 601000.00),
            ex.submit(put_property, "us", PROP_ID, current_version, 702000.00),
        ]
        for f in as_completed(futures):
            r = f.result()
            results.append(r)
            print(f"    HTTP {r.status_code}  →  {r.text[:120]}")

    statuses = sorted(r.status_code for r in results)
    if statuses == [200, 409]:
        passed("One request succeeded (200) and the other was rejected (409) — race condition handled correctly.")
    elif statuses == [200, 200]:
        failed("Both succeeded — this should not happen if optimistic locking is working.")
        sys.exit(1)
    else:
        info(f"Statuses {statuses} — property may have already been at a different version. Running explicit test …")
        test_version_conflict_explicit(PROP_ID)


# ─────────────────────────────────────────────────────────────
# Test 2 – Explicit sequential version conflict
# ─────────────────────────────────────────────────────────────

def test_version_conflict_explicit(prop_id: int = 20):
    sep()
    info(f"TEST 2: Sequential version conflict on property {prop_id}")

    prop = get_property("us", prop_id)
    version = prop["version"]
    info(f"Current version = {version}")

    # First update – must succeed
    r1 = put_property("us", prop_id, version, 450001.00)
    print(f"    First  PUT (version={version}): HTTP {r1.status_code}")
    if r1.status_code != 200:
        info(f"First PUT failed ({r1.status_code}) – skipping; check DB state.")
        return

    # Second update with the OLD version – must fail
    r2 = put_property("us", prop_id, version, 450002.00)
    print(f"    Second PUT (version={version}): HTTP {r2.status_code}  (stale version)")

    if r2.status_code == 409:
        passed("Stale version correctly rejected with 409 Conflict.")
    else:
        failed(f"Expected 409, got {r2.status_code}. Body: {r2.text}")


# ─────────────────────────────────────────────────────────────
# Test 3 – Idempotency (duplicate X-Request-ID)
# ─────────────────────────────────────────────────────────────

def test_idempotency():
    sep()
    info("TEST 3: Idempotency – duplicate X-Request-ID must return 422")

    PROP_ID = 30
    prop = get_property("us", PROP_ID)
    version = prop["version"]
    shared_rid = str(uuid.uuid4())
    info(f"Using X-Request-ID = {shared_rid}")

    r1 = requests.put(
        f"{BASE_URL}/us/properties/{PROP_ID}",
        json={"price": 299_000.00, "version": version},
        headers={"X-Request-ID": shared_rid, "Content-Type": "application/json"},
        timeout=15,
    )
    print(f"    First  PUT: HTTP {r1.status_code}")

    r2 = requests.put(
        f"{BASE_URL}/us/properties/{PROP_ID}",
        json={"price": 299_000.00, "version": version},
        headers={"X-Request-ID": shared_rid, "Content-Type": "application/json"},
        timeout=15,
    )
    print(f"    Second PUT (same X-Request-ID): HTTP {r2.status_code}  {r2.text[:120]}")

    if r1.status_code == 200 and r2.status_code == 422:
        passed("Duplicate request correctly rejected with 422 Unprocessable Entity.")
    elif r1.status_code != 200:
        info(f"First request returned {r1.status_code} – property version may not match. Check DB.")
    else:
        failed(f"Expected 422 for duplicate, got {r2.status_code}.")


# ─────────────────────────────────────────────────────────────
# Test 4 – Replication lag endpoint
# ─────────────────────────────────────────────────────────────

def test_replication_lag():
    sep()
    info("TEST 4: Replication lag endpoint returns a numeric value")

    # Trigger a US update to generate a Kafka message
    prop = get_property("us", 40)
    r = put_property("us", 40, prop["version"], 550_000.00)
    print(f"    Triggered US update: HTTP {r.status_code}")

    import time
    info("Waiting 3 seconds for replication …")
    time.sleep(3)

    lag_r = requests.get(f"{BASE_URL}/eu/replication-lag", timeout=10)
    print(f"    GET /eu/replication-lag: HTTP {lag_r.status_code}  {lag_r.text}")

    if lag_r.status_code == 200:
        data = lag_r.json()
        lag = data.get("lag_seconds", -1)
        if isinstance(lag, (int, float)) and lag >= 0:
            passed(f"Replication lag = {lag:.3f} seconds.")
        else:
            failed(f"'lag_seconds' value unexpected: {lag}")
    else:
        failed(f"Endpoint returned HTTP {lag_r.status_code}")


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Confirm system is reachable
    try:
        r = requests.get(f"{BASE_URL}/us/health", timeout=5)
        r.raise_for_status()
        info(f"System healthy: {r.json()}")
    except Exception as e:
        print(f"{RED}[ERROR]{NC} System not reachable at {BASE_URL}: {e}")
        print("  → Run: docker-compose up -d  and wait ~90 seconds")
        sys.exit(1)

    test_concurrent_updates()
    test_version_conflict_explicit()
    test_idempotency()
    test_replication_lag()

    sep()
    print(f"{GREEN}All tests completed.{NC}")
