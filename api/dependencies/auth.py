from __future__ import annotations

import os
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_async_db

ALGORITHMS = ["HS256"]


@lru_cache(maxsize=1)
def get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY environment variable must be set")
    return secret


def _extract_bearer_token(auth_header: str | None) -> str:
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid token")
    return auth_header.split(" ", 1)[1].strip()


async def set_service_role_context(db: AsyncSession) -> None:
    await db.execute(text("SELECT set_config('auth.role', 'service_role', true)"))


async def get_current_user_and_set_context(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> str:
    token = _extract_bearer_token(request.headers.get("Authorization"))
    try:
        payload = jwt.decode(
            token,
            get_jwt_secret(),
            algorithms=ALGORITHMS,
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token verification failed") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token verification failed")

    await db.execute(text("SELECT set_config('auth.uid', :user_id, true)"), {"user_id": str(user_id)})
    await db.execute(text("SELECT set_config('auth.role', 'authenticated', true)"))
    return str(user_id)


async def get_current_user_id(user_id: str = Depends(get_current_user_and_set_context)) -> str:
    return user_id
