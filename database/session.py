from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

engine = create_async_engine(DATABASE_URL, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
