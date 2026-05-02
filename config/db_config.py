from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from config.env import get_bool_env, get_env, get_int_env


async_engine = create_async_engine(
    get_env("EKKO_DATABASE_URL"),
    echo=get_bool_env("EKKO_DB_ECHO", default=False),
    pool_size=get_int_env("EKKO_DB_POOL_SIZE", default=10),
    max_overflow=get_int_env("EKKO_DB_MAX_OVERFLOW", default=20),
)


AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
