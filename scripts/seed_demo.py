import base64
import json
import os

import httpx

BASE = os.getenv("BASE_URL", "http://localhost:8000")
PASSWORD = "password123"
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev").lower()


def _decode_sub(access_token: str) -> str:
    payload_b64 = access_token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")))
    return payload["sub"]


def register_or_login(client: httpx.Client, username: str, email: str) -> dict:
    r = client.post(f"{BASE}/auth/register", json={"username": username, "email": email, "password": PASSWORD})
    if r.status_code not in (201, 409):
        raise RuntimeError(r.text)
    l = client.post(f"{BASE}/auth/login", json={"username_or_email": username, "password": PASSWORD})
    l.raise_for_status()
    data = l.json()
    data["user_id"] = _decode_sub(data["access_token"])
    return data


def main() -> None:
    if ENVIRONMENT not in {"dev", "local", "test"}:
        raise RuntimeError(f"seed script is disabled outside dev/test environments (ENVIRONMENT={ENVIRONMENT})")
    with httpx.Client(timeout=20) as client:
        alice = register_or_login(client, "alice", "alice@example.com")
        bob = register_or_login(client, "bob", "bob@example.com")
        carol = register_or_login(client, "carol", "carol@example.com")
        dave = register_or_login(client, "dave", "dave@example.com")

        alice_h = {"Authorization": f"Bearer {alice['access_token']}"}
        bob_h = {"Authorization": f"Bearer {bob['access_token']}"}
        carol_h = {"Authorization": f"Bearer {carol['access_token']}"}
        dave_h = {"Authorization": f"Bearer {dave['access_token']}"}

        public_channel = client.post(
            f"{BASE}/channels",
            headers=alice_h,
            json={"name": "public-open", "visibility": "public", "join_mode": "open"},
        ).json()

        private_channel = client.post(
            f"{BASE}/channels",
            headers=alice_h,
            json={"name": "private-approval", "visibility": "private", "join_mode": "approval_required"},
        ).json()

        client.post(f"{BASE}/channels/{public_channel['id']}/join", headers=bob_h, json={}).raise_for_status()  # member
        client.post(
            f"{BASE}/channels/{public_channel['id']}/members/{bob['user_id']}/promote",
            headers=alice_h,
        ).raise_for_status()  # admin

        client.post(f"{BASE}/channels/{public_channel['id']}/join", headers=carol_h, json={}).raise_for_status()  # member
        client.post(f"{BASE}/channels/{private_channel['id']}/join", headers=dave_h, json={}).raise_for_status()  # pending
        client.post(
            f"{BASE}/channels/{private_channel['id']}/members/{dave['user_id']}/approve",
            headers=alice_h,
        ).raise_for_status()

        client.post(
            f"{BASE}/channels/{public_channel['id']}/messages",
            headers=alice_h,
            json={"content_text": "hello from alice"},
        ).raise_for_status()
        client.post(
            f"{BASE}/channels/{public_channel['id']}/messages",
            headers=alice_h,
            json={"content_json": {"kind": "demo", "value": 42}},
        ).raise_for_status()

        history = client.get(f"{BASE}/channels/{public_channel['id']}/messages", headers=bob_h)
        history.raise_for_status()

        print("Seed complete")
        print(
            json.dumps(
                {
                    "users": {
                        "alice_owner": alice["user_id"],
                        "bob_admin": bob["user_id"],
                        "carol_member": carol["user_id"],
                        "dave_pending_then_member": dave["user_id"],
                    },
                    "public_channel": public_channel["id"],
                    "private_channel": private_channel["id"],
                    "history_count": len(history.json().get("items", [])),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
