#!/usr/bin/env python3
"""Run safe, repeatable release checks without touching application data.

The backend suite uses uniquely named disposable PostgreSQL/Redis containers.
The data-creating supervisor scenario remains a separate command:
``scripts/verify_release_candidate.py``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]


def run(label: str, command: Sequence[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n[CHECK] {label}", flush=True)
    completed = subprocess.run(command, cwd=cwd, env=env, check=False)
    if completed.returncode:
        raise RuntimeError(f"{label} failed with exit code {completed.returncode}")
    print(f"[PASS] {label}", flush=True)


def verify_locales() -> None:
    print("\n[CHECK] locale JSON, key, and placeholder parity", flush=True)
    locale_dir = ROOT / "frontend" / "src" / "locales"
    catalogs = {
        name: json.loads((locale_dir / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("en", "ar")
    }

    def flatten(value: object, prefix: str = "") -> dict[str, object]:
        if not isinstance(value, dict):
            return {prefix: value}
        flattened: dict[str, object] = {}
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(flatten(child, child_prefix))
        return flattened

    def placeholders(value: object) -> set[str]:
        import re

        return set(re.findall(r"\{([A-Za-z0-9_]+)\}", str(value)))

    en = flatten(catalogs["en"])
    ar = flatten(catalogs["ar"])
    if en.keys() != ar.keys():
        raise RuntimeError("English and Arabic locale keys differ")
    mismatches = [key for key in en if placeholders(en[key]) != placeholders(ar[key])]
    if mismatches:
        raise RuntimeError(f"locale placeholder mismatch: {mismatches[:10]}")
    print(f"[PASS] locale parity ({len(en)} leaf keys per catalog)", flush=True)


def wait_for_postgres(container: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "exec", container, "pg_isready", "-U", "postgres", "-d", "channels"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("disposable PostgreSQL did not become ready")


def backend_checks(run_id: str) -> None:
    network = f"messaging-release-{run_id}"
    postgres = f"{network}-postgres"
    redis = f"{network}-redis"
    image = f"messaging-release-verify:{run_id}"
    password = secrets.token_urlsafe(24)
    try:
        run("canonical backend image build", ["docker", "build", "-t", image, "-f", "backend/Dockerfile", "."])
        run("create disposable test network", ["docker", "network", "create", network])
        run(
            "start disposable PostgreSQL",
            [
                "docker", "run", "-d", "--name", postgres, "--network", network,
                "--network-alias", "postgres", "-e", f"POSTGRES_PASSWORD={password}",
                "-e", "POSTGRES_DB=channels", "postgres:16",
            ],
        )
        run(
            "start disposable Redis",
            [
                "docker", "run", "-d", "--name", redis, "--network", network,
                "--network-alias", "redis", "redis:7-alpine",
            ],
        )
        wait_for_postgres(postgres)
        run(
            "complete backend test suite",
            [
                "docker", "run", "--rm", "--network", network,
                "-v", f"{(ROOT / 'frontend').resolve()}:/frontend:ro",
                "-v", f"{(ROOT / 'docker-compose.production.yml').resolve()}:/docker-compose.production.yml:ro",
                "-e", "ENVIRONMENT=test",
                "-e", f"DATABASE_URL=postgresql+asyncpg://postgres:{password}@postgres:5432/channels",
                "-e", "PHASE10_TEST_REDIS_URL=redis://redis:6379/15",
                image, "python", "-B", "-m", "pytest", "-p", "no:cacheprovider", "-q",
            ],
        )
        run("Alembic single-head check", ["docker", "run", "--rm", image, "python", "-B", "-m", "alembic", "heads"])
    finally:
        subprocess.run(["docker", "rm", "-f", postgres, redis], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "image", "rm", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run safe release-candidate verification")
    parser.add_argument(
        "--production-env-file",
        type=Path,
        help="Optional production env file used only for Compose configuration validation",
    )
    parser.add_argument("--skip-backend", action="store_true", help="Skip disposable backend build/tests")
    parser.add_argument("--skip-frontend-build", action="store_true", help="Run typecheck but skip Next.js build")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if shutil.which("docker") is None:
        raise RuntimeError("Docker is required for release verification")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    run_id = secrets.token_hex(4)
    if not args.skip_backend:
        backend_checks(run_id)

    run("frontend typecheck", [npm, "run", "typecheck"], cwd=ROOT / "frontend")
    if not args.skip_frontend_build:
        run("frontend production build", [npm, "run", "build"], cwd=ROOT / "frontend")
    verify_locales()
    run("development Compose render", ["docker", "compose", "config", "--quiet"])
    run(
        "hardened Compose render",
        ["docker", "compose", "-f", "docker-compose.hardened.yml", "config", "--quiet"],
    )

    if args.production_env_file:
        env_path = args.production_env_file.resolve()
        if not env_path.is_file():
            raise RuntimeError(f"production env file does not exist: {env_path}")
        run(
            "production Compose render",
            [
                "docker", "compose", "--env-file", str(env_path),
                "-f", "docker-compose.production.yml", "config", "--quiet",
            ],
        )
    else:
        print("\n[SKIP] production Compose render (pass --production-env-file)", flush=True)

    run(
        "Nginx hardened configuration syntax",
        [
            "docker", "run", "--rm", "--add-host", "backend:127.0.0.1",
            "--add-host", "frontend:127.0.0.1", "-v",
            f"{(ROOT / 'deploy' / 'nginx' / 'nginx.conf').resolve()}:/etc/nginx/nginx.conf:ro",
            "nginx:1.27-alpine", "nginx", "-t",
        ],
    )
    print("\n[PASS] Safe release verification completed", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"\n[FAIL] {exc}", file=sys.stderr)
        raise SystemExit(1)
