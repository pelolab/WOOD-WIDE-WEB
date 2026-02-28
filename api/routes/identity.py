from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_async_db, get_current_user_id
from models import CircleMember, SocialVoucher, User, UserVerification
from app.rate_limiter import limiter

router = APIRouter(prefix="/api/identity", tags=["Identity"])


@router.post("/request-vouch")
async def request_vouch(current_user_id: str = Depends(get_current_user_id)):
    return {"prospect_id": current_user_id}


@router.get("/status")
async def get_identity_status(
    db: AsyncSession = Depends(get_async_db),
    current_user_id: str = Depends(get_current_user_id),
):
    result = await db.execute(
        select(UserVerification.tier, UserVerification.status).where(UserVerification.user_id == UUID(current_user_id))
    )
    rows = result.all()
    status_map = {tier: stat for tier, stat in rows}
    return {
        "user_id": current_user_id,
        "tier1_status": status_map.get(1, "unverified"),
        "tier2_status": status_map.get(2, "unverified"),
        "tier3_status": status_map.get(3, "unverified"),
    }


@router.get("/prospect/{prospect_id}")
async def get_prospect_info(
    prospect_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _current_user_id: str = Depends(get_current_user_id),
):
    full_name = (await db.execute(select(User.full_name).where(User.id == prospect_id))).scalar()
    if not full_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prospect not found.")

    tier1_status = (
        await db.execute(
            select(UserVerification.status).where(UserVerification.user_id == prospect_id, UserVerification.tier == 1)
        )
    ).scalar() or "none"

    return {"full_name": full_name, "tier1_status": tier1_status}


@router.post("/vouch/{prospect_id}")
@limiter.limit("5/minute")
async def vouch_for_user(
    request: Request,
    prospect_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user_id: str = Depends(get_current_user_id),
):
    active_member = await db.execute(
        select(CircleMember).where(CircleMember.user_id == UUID(current_user_id), CircleMember.status == "active")
    )
    if not active_member.scalar():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only active circle members can vouch.")

    try:
        await db.execute(insert(SocialVoucher).values(prospect_id=prospect_id, voucher_id=UUID(current_user_id)))
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already vouched for this user.") from exc

    verification_row = (
        await db.execute(
            select(UserVerification)
            .where(UserVerification.user_id == prospect_id, UserVerification.tier == 1)
            .with_for_update()
        )
    ).scalar_one_or_none()

    if verification_row is None:
        verification_row = UserVerification(user_id=prospect_id, tier=1, status="unverified")
        db.add(verification_row)
        await db.flush()

    vouch_count = (
        await db.execute(select(func.count(SocialVoucher.id)).where(SocialVoucher.prospect_id == prospect_id))
    ).scalar() or 0

    if vouch_count >= 2:
        await db.execute(
            update(UserVerification)
            .where(UserVerification.user_id == prospect_id, UserVerification.tier == 1)
            .values(status="verified", verified_at=func.now())
        )

    await db.commit()
    return {"status": "vouch_recorded"}
