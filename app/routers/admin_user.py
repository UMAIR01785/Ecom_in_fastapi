
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.user import User
from app.schemas.user import UserResponse


router = APIRouter(
    prefix="/admin/users",
    tags=["Admin Users"],
)


@router.get("/", response_model=list[UserResponse])
async def get_all_users(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    result = await db.execute(
        select(User).order_by(User.id.desc())
    )

    users = result.scalars().all()

    return users
