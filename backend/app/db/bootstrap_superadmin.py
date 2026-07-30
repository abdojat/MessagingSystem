import asyncio

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.superadmin_bootstrap_service import SuperadminBootstrapService


# Ensures superadmin; the application startup and service layers use it for database access.
async def ensure_superadmin() -> None:
    settings = get_settings()
    values = [settings.superadmin_username.strip(), settings.superadmin_password]
    # Return early when `not any(values)` because the remaining work is not applicable.
    if not any(values):
        return
    # Reject the operation when `not all(values)` to keep invalid state from progressing.
    if not all(values):
        raise RuntimeError("SUPERADMIN_USERNAME and SUPERADMIN_PASSWORD must be set together")

    # Keep `SessionLocal()` active while this scoped operation is performed.
    async with SessionLocal() as db:
        user, created = await SuperadminBootstrapService.ensure(
            db,
            username=settings.superadmin_username,
            password=settings.superadmin_password,
            email=settings.superadmin_email or None,
        )
        state = "created" if created else "already exists"
        print(f"superadmin {user.username!r} {state}")


# Runs the module's command-line workflow; the application startup and service layers use it for database access.
def main() -> None:
    asyncio.run(ensure_superadmin())


# Run this conditional step only when `__name__ == '__main__'` is true.
if __name__ == "__main__":
    main()
