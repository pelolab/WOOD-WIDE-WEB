from __future__ import annotations

import os

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.session import get_db

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-sovereign-secret-key")
ALGORITHMS = ["HS256"]


def _extract_bearer_token(auth_header: str | None) -> str:
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid token",
        )
    return auth_header.split(" ", 1)[1].strip()


async def get_current_user_and_set_context(
    request: Request,
    db: Session = Depends(get_db),
) -> str:
    """
    1. Extract and verify the JWT.
    2. Inject the user context into the Postgres session for RLS.
    """

    token = _extract_bearer_token(request.headers.get("Authorization"))

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=ALGORITHMS)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed",
        ) from exc

    user_id = payload.get("sub")
    role = payload.get("role", "authenticated")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed",
        )

    # Set per-transaction variables (equivalent to SET LOCAL) using bind params.
    db.execute(text("SELECT set_config('auth.uid', :user_id, true)"), {"user_id": str(user_id)})
    db.execute(text("SELECT set_config('auth.role', :role, true)"), {"role": str(role)})

    return str(user_id)


async def get_current_user_id(
    user_id: str = Depends(get_current_user_and_set_context),
) -> str:
    """Return authenticated user id after DB RLS context has been set."""
    return user_id
