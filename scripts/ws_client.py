import argparse
import asyncio
import json

import websockets


# Runs; the command-line verification workflow uses it.
async def run(url: str, token: str) -> None:
    ws_url = f"{url.rstrip('/')}/ws?token={token}"
    # Keep `websockets.connect(ws_url)` active while this scoped operation is performed.
    async with websockets.connect(ws_url) as ws:
        print("connected", ws_url)
        await ws.send(json.dumps({"type": "sync", "states": []}))
        # Process each `message` from `ws` to apply this step to the full collection.
        async for message in ws:
            print(message)


# Run this conditional step only when `__name__ == '__main__'` is true.
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8000")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.token))
