from fastapi import APIRouter, Depends ,HTTPException,status
from sqlalchemy.orm import Session, joinedload
from app.schemas.admin_order import OrderStatusUpdate
from app.database import get_db
from app.models.order import Order,OrderItem
from app.models.user import User
from app.models.order import OrderStatus
from app.dependencies.permissions import admin_required


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
def update_order_status(
    order_id: int,
    data: OrderStatusUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    order = (
        db.query(Order)
        .filter(Order.id == order_id)
        .first()
    )

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found"
        )

    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(
            status_code=400,
            detail="Cancelled orders cannot be updated"
        )

    order.status = data.status

    db.commit()
    db.refresh(order)

    return order


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