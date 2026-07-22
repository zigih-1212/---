import asyncio
import httpx
import sys
sys.path.insert(0, ".")
from services.db import get_db

async def main():
    conn = get_db()
    conn.row_factory = None
    row = conn.execute("SELECT access_token, expires_at FROM admitad_tokens ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    if not row:
        print("No token in DB")
        return
    token = row[0]
    
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://api.admitad.com/advcampaigns/",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": "Сотка", "limit": 10}
        )
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            for c in data.get("results", []):
                print(f"\n=== {c.get('name')} (id={c.get('id')}) ===")
                print(f"  image: {c.get('image')}")
                print(f"  description: {str(c.get('description',''))[:300]}")
                print(f"  more_rules: {str(c.get('more_rules',''))[:300]}")
                print(f"  site_url: {c.get('site_url')}")
        else:
            print(resp.text[:500])

asyncio.run(main())
