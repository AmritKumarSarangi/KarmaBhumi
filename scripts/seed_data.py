import httpx
import time
import asyncio

BASE_URL = "http://localhost:8000"

USERS = [
    {"username": "krishna", "email": "krishna@karmabhumi.com", "password": "KrishnaPassword123!", "is_admin": True},
    {"username": "arjuna", "email": "arjuna@karmabhumi.com", "password": "ArjunaPassword123!", "is_admin": False},
    {"username": "karna", "email": "karna@karmabhumi.com", "password": "KarnaPassword123!", "is_admin": False},
]

INITIAL_PRICES = {
    "AAPL": 185.00,
    "GOOGL": 141.00,
    "TSLA": 248.00,
    "MSFT": 378.00,
    "AMZN": 186.00
}

async def register_user(client, user):
    try:
        r = await client.post("/api/auth/register", json={
            "email": user["email"],
            "password": user["password"]
        })
        if r.status_code == 201:  # Status code is 201 Created for register
            print(f"Registered user: {user['username']}")
            return r.json()
        else:
            print(f"Registration failed for {user['username']}: {r.text}")
    except Exception as e:
        print(f"Error registering user {user['username']}: {e}")
    return None

async def login_user(client, user):
    try:
        r = await client.post("/api/auth/login", json={
            "email": user["email"],
            "password": user["password"]
        })
        if r.status_code == 200:
            print(f"Logged in user: {user['username']}")
            return r.json().get("access_token")
    except Exception as e:
        print(f"Error logging in {user['username']}: {e}")
    return None

async def main():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        print("--- Registering Users ---")
        for u in USERS:
            await register_user(client, u)
        
        print("\n--- Logging in Traders ---")
        tokens = {}
        for u in USERS:
            t = await login_user(client, u)
            if t:
                tokens[u["username"]] = t
        
        if "arjuna" not in tokens or "karna" not in tokens:
            print("Failed to login Arjuna or Karna. Exiting seed script.")
            return

        print("\n--- Seeding Initial Order Books ---")
        # Place orders on both sides to build initial books
        for symbol, price in INITIAL_PRICES.items():
            print(f"Seeding {symbol} around {price}...")
            
            # Arjuna places bids (buy side)
            headers_t1 = {"Authorization": f"Bearer {tokens['arjuna']}"}
            bids = [price - 1.0, price - 0.50, price - 0.20]
            for b_price in bids:
                await client.post("/api/orders", json={
                    "symbol": symbol,
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "quantity": 100,
                    "price": b_price
                }, headers=headers_t1)

            # Karna places asks (sell side)
            headers_t2 = {"Authorization": f"Bearer {tokens['karna']}"}
            asks = [price + 1.0, price + 0.50, price + 0.20]
            for a_price in asks:
                await client.post("/api/orders", json={
                    "symbol": symbol,
                    "side": "SELL",
                    "order_type": "LIMIT",
                    "quantity": 100,
                    "price": a_price
                }, headers=headers_t2)

        print("\nSeed data deployed successfully!")

if __name__ == "__main__":
    asyncio.run(main())
