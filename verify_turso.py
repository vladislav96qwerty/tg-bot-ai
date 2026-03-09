import asyncio
import os
from dotenv import load_dotenv
import libsql_client

load_dotenv()

async def main():
    url = os.getenv("TURSO_DATABASE_URL")
    if url and url.startswith("libsql://"):
        url = url.replace("libsql://", "https://")
        
    token = os.getenv("TURSO_AUTH_TOKEN")
    
    print(f"Connecting to: {url}")
    
    try:
        async with libsql_client.create_client(url=url, auth_token=token) as client:
            result = await client.execute("SELECT 1")
            print("Successfully connected to Turso!")
            print(f"Result: {result.rows[0][0]}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
