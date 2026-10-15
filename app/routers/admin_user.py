
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.user import User
from app.schemas.user import UserResponse


router = APIRouter(
    prefix="/admin/users",
    tags=["Admin Users"],
)


@router.get("/", response_model=list[UserResponse])
def get_all_users(
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    users = (
        db.query(User)
        .order_by(User.id.desc())
        .all()
    )

    return users
