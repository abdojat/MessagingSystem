import asyncio

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.superadmin_bootstrap_service import SuperadminBootstrapService


async def ensure_superadmin() -> None:
    settings = get_settings()
    values = [settings.superadmin_username.strip(), settings.superadmin_password]
    if not any(values):
        return
    if not all(values):
        raise RuntimeError("SUPERADMIN_USERNAME and SUPERADMIN_PASSWORD must be set together")

    async with SessionLocal() as db:
        user, created = await SuperadminBootstrapService.ensure(
            db,
            username=settings.superadmin_username,
            password=settings.superadmin_password,
            email=settings.superadmin_email or None,
        )
        state = "created" if created else "already exists"
        print(f"superadmin {user.username!r} {state}")


def main() -> None:
    asyncio.run(ensure_superadmin())


if __name__ == "__main__":
    main()
