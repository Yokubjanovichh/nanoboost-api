import asyncio
import logging

from app.core.config import settings
from app.core.constants import UserRole
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.features.users.models import User
from app.features.users.repository import UserRepository

logger = logging.getLogger("nanoboost.seed")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def create_superuser() -> None:
    email = settings.SEED_SUPERUSER_EMAIL.lower()

    async with AsyncSessionLocal() as db:
        repo = UserRepository(db)
        existing = await repo.get_by_email(email)
        if existing is not None:
            logger.info("Superuser already exists: %s", email)
            return

        user = User(
            email=email,
            password_hash=hash_password(settings.SEED_SUPERUSER_PASSWORD),
            full_name=settings.SEED_SUPERUSER_NAME,
            role=UserRole.SUPERADMIN,
            is_active=True,
        )
        await repo.add(user)
        await db.commit()
        logger.info("Superuser created: %s", email)


if __name__ == "__main__":
    asyncio.run(create_superuser())
