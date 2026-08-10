import argparse
import asyncio
import json

import httpx
import websockets


async def run(url: str, token: str) -> None:
    ws_base_url = url.rstrip("/")
    http_base_url = ws_base_url.replace("ws://", "http://").replace("wss://", "https://")
    async with httpx.AsyncClient(base_url=http_base_url, timeout=10.0) as client:
        response = await client.post("/auth/ws-ticket", headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        ticket = response.json()["ticket"]
    ws_url = f"{ws_base_url}/ws?ticket={ticket}"
    async with websockets.connect(ws_url) as ws:
        print("connected")
        await ws.send(json.dumps({"type": "sync", "states": []}))
        async for message in ws:
            print(message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8000")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.token))
