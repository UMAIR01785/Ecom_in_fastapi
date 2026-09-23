from fastapi import APIRouter, Depends, status,HTTPException
from sqlalchemy.orm import Session, joinedload
from app.websockets.manager import manager
from app.schemas.admin_order import OrderStatusUpdate
from app.database import get_db
from app.models.order import Order, OrderItem
from app.models.user import User
from app.dependencies.permissions import admin_required
from app.services.oder_servies import update_order_status


router = APIRouter(
    prefix="/admin/orders",
    tags=["Admin Orders"]
)


@router.get("/")
def get_all_orders(
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    orders = (
        db.query(Order)
        .options(
            joinedload(Order.user),
            joinedload(Order.items)
            .joinedload(OrderItem.product)
        )
        .order_by(Order.created_at.desc())
        .all()
    )

    return orders


@router.patch("/{order_id}/status")
async def update_order_status_admin(
    order_id: int,
    data: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    return await update_order_status(
        db=db,
        order_id=order_id,
        new_status=data.status,
    )


@router.get("/{order_id}")
def get_order_detail(
    order_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    order = (
        db.query(Order)
        .options(
            joinedload(Order.user),
            joinedload(Order.items)
            .joinedload(OrderItem.product)
        )
        .filter(Order.id == order_id)
        .first()
    )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found"
        )

    return order