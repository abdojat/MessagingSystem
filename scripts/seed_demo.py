import base64
import json
import os

import httpx

BASE = os.getenv("BASE_URL", "http://localhost:8000")
PASSWORD = "password123"


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
    with httpx.Client(timeout=20) as client:
        alice = register_or_login(client, "alice", "alice@example.com")
        bob = register_or_login(client, "bob", "bob@example.com")
        carol = register_or_login(client, "carol", "carol@example.com")

        alice_h = {"Authorization": f"Bearer {alice['access_token']}"}
        bob_h = {"Authorization": f"Bearer {bob['access_token']}"}
        carol_h = {"Authorization": f"Bearer {carol['access_token']}"}

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

        invite_only_channel = client.post(
            f"{BASE}/channels",
            headers=alice_h,
            json={"name": "private-invite", "visibility": "private", "join_mode": "invite_only"},
        ).json()

        client.post(f"{BASE}/channels/{public_channel['id']}/join", headers=bob_h, json={}).raise_for_status()

        # Pending flow + approval
        client.post(f"{BASE}/channels/{private_channel['id']}/join", headers=carol_h, json={}).raise_for_status()
        client.post(
            f"{BASE}/channels/{private_channel['id']}/members/{carol['user_id']}/approve",
            headers=alice_h,
        ).raise_for_status()

        # Invite-only flow
        invite = client.post(
            f"{BASE}/channels/{invite_only_channel['id']}/invite",
            headers=alice_h,
            json={"invited_user_id": bob["user_id"], "expires_in_hours": 24},
        )
        invite.raise_for_status()
        token = invite.json()["token"]
        client.post(f"{BASE}/invites/{token}/accept", headers=bob_h).raise_for_status()

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
                    "users": {"alice": alice["user_id"], "bob": bob["user_id"], "carol": carol["user_id"]},
                    "public_channel": public_channel["id"],
                    "private_channel": private_channel["id"],
                    "invite_only_channel": invite_only_channel["id"],
                    "history_count": len(history.json()),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
