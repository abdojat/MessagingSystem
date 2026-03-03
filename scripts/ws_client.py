import argparse
import asyncio
import json

import websockets


async def run(url: str, token: str) -> None:
    ws_url = f"{url.rstrip('/')}/ws?token={token}"
    async with websockets.connect(ws_url) as ws:
        print("connected", ws_url)
        await ws.send(json.dumps({"type": "sync", "states": []}))
        async for message in ws:
            print(message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8000")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.token))
