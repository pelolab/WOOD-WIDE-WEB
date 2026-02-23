from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_user_id
from database.session import get_db
from models.circle_member import CircleMember
from models.social_voucher import SocialVoucher
from models.user import User
from models.user_verification import UserVerification

router = APIRouter(prefix="/api/identity", tags=["Identity"])


@router.post("/vouch/{prospect_id}")
async def vouch_for_user(
    prospect_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    An existing member confirms they know and trust the prospect.
    If 2 members vouch, Tier 1 is automatically marked as 'verified'.
    """
    # 1. Verify the current_user is an ACTIVE member of at least one circle
    active_member = await db.execute(
        select(CircleMember).where(
            CircleMember.user_id == UUID(current_user_id),
            CircleMember.status == "active",
        )
    )
    if not active_member.scalar():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only active circle members can vouch.",
        )

    # 2. Record the voucher
    try:
        stmt = insert(SocialVoucher).values(
            prospect_id=prospect_id,
            voucher_id=UUID(current_user_id),
        )
        await db.execute(stmt)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already vouched for this user.",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record voucher.",
        ) from exc

    # 3. Check if Tier 1 is now complete
    vouch_count_result = await db.execute(
        select(func.count(SocialVoucher.id)).where(SocialVoucher.prospect_id == prospect_id)
    )
    vouch_count = vouch_count_result.scalar() or 0

    if vouch_count >= 2:
        await db.execute(
            update(UserVerification)
            .where(
                UserVerification.user_id == prospect_id,
                UserVerification.tier == 1,
            )
            .values(status="verified", verified_at=func.now())
        )

    await db.commit()
    return {"status": "vouch_recorded"}


@router.get("/prospect/{prospect_id}")
async def get_prospect_info(
    prospect_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Allows a potential voucher to see who they are vouching for.
    Must be an authenticated user to prevent scraping.
    """
    # Ensure caller is authenticated through dependency and parseable as UUID.
    UUID(current_user_id)

    stmt = select(User.full_name).where(User.id == prospect_id)
    result = await db.execute(stmt)
    full_name = result.scalar()

    if not full_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prospect not found.")

    status_stmt = select(UserVerification.status).where(
        UserVerification.user_id == prospect_id,
        UserVerification.tier == 1,
    )
    status_res = await db.execute(status_stmt)
    tier1_status = status_res.scalar() or "none"

    return {"full_name": full_name, "tier1_status": tier1_status}
