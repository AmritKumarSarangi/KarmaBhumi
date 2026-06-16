import asyncio
import httpx
import time
import random

BASE_URL = "http://localhost:8000"
SYMBOLS = ["AAPL", "GOOGL", "TSLA", "MSFT", "AMZN"]
ORDER_TYPES = ["LIMIT", "MARKET", "IOC", "FOK"]
SIDES = ["BUY", "SELL"]

async def register_load_users(client):
    """Registers two distinct users for the load test and returns their tokens"""
    tokens = []
    for i in range(2):
        username = f"loaduser_{i}_{random.randint(1000, 9999)}"
        email = f"{username}@loadtest.com"
        password = "LoadPassword123!"
        
        # Register
        await client.post("/api/auth/register", json={
            "email": email,
            "password": password
        })
        
        # Login
        r = await client.post("/api/auth/login", json={
            "email": email,
            "password": password
        })
        if r.status_code == 200:
            tokens.append(r.json().get("access_token"))
    return tokens

async def send_worker_orders(client, token, count, worker_id):
    success_count = 0
    err_count = 0
    headers = {"Authorization": f"Bearer {token}"}
    
    for _ in range(count):
        symbol = random.choice(SYMBOLS)
        side = random.choice(SIDES)
        otype = random.choices(ORDER_TYPES, weights=[60, 25, 10, 5], k=1)[0]
        qty = random.randint(10, 200)
        
        # Select price around simulated baseline
        base_price = 200.0
        price = round(random.uniform(base_price - 5.0, base_price + 5.0), 2)
        
        payload = {
            "symbol": symbol,
            "side": side,
            "order_type": otype,
            "quantity": qty
        }
        if otype != "MARKET":
            payload["price"] = price

        try:
            r = await client.post("/api/orders", json=payload, headers=headers)
            if r.status_code in [200, 201]:
                success_count += 1
            else:
                err_count += 1
        except Exception:
            err_count += 1
            
    return success_count, err_count

async def main():
    print("==================================================")
    # Target 100,000 orders total
    total_orders = 100000
    concurrency = 50
    orders_per_worker = total_orders // concurrency
    
    print(f"Starting ExchangeX Load Test...")
    print(f"Total target orders: {total_orders}")
    print(f"Concurrency level:    {concurrency} workers")
    print(f"Orders per worker:    {orders_per_worker}")
    print("==================================================")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # Register/login users to get JWT tokens
        print("[LoadTest] Preparing load test accounts...")
        tokens = await register_load_users(client)
        if len(tokens) < 2:
            print("[LoadTest] Error: could not register users. Is the backend running?")
            return
        
        print("[LoadTest] Ready! Running stress test...")
        start_time = time.perf_loop_time() if hasattr(time, "perf_loop_time") else time.perf_counter()
        
        tasks = []
        for i in range(concurrency):
            token = tokens[i % 2]
            tasks.append(send_worker_orders(client, token, orders_per_worker, i))
            
        results = await asyncio.gather(*tasks)
        end_time = time.perf_loop_time() if hasattr(time, "perf_loop_time") else time.perf_counter()
        
        # Calculate stats
        total_success = sum(r[0] for r in results)
        total_errors = sum(r[1] for r in results)
        elapsed = end_time - start_time
        throughput = total_success / elapsed
        
        print("\n=================== RESULTS ===================")
        print(f"Completed in:      {elapsed:.2f} seconds")
        print(f"Successful orders: {total_success:,}")
        print(f"Errors/Rejections: {total_errors:,}")
        print(f"Throughput:        {throughput:.2f} orders/sec")
        print("===============================================")

if __name__ == "__main__":
    asyncio.run(main())
