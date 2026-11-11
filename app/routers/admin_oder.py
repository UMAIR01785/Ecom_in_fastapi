
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.schemas.admin_order import OrderStatusUpdate
from app.database import get_db

from app.models.order import (
    Order,
    OrderItem,
)

from app.models.user import User
from app.dependencies.permissions import admin_required

from app.services.oder_servies import (
    update_order_status,
)


router = APIRouter(
    prefix="/admin/orders",
    tags=["Admin Orders"],
)


# ============================================================
# GET ALL ORDERS
# ============================================================

@router.get("/")
async def get_all_orders(
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    result = await db.execute(
        select(Order)
        .options(
            # Customer
            joinedload(Order.user),

            # Order items + product
            selectinload(Order.items).joinedload(
                OrderItem.product
            ),

            # Shipping address
            joinedload(Order.shipping_address),

            # Payment
            joinedload(Order.payment),
        )
        .order_by(Order.created_at.desc())
    )

    orders = result.scalars().all()

    return orders


# ============================================================
# UPDATE ORDER STATUS
# ============================================================

@router.patch("/{order_id}/status")
async def update_order_status_admin(
    order_id: int,
    data: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    return await update_order_status(
        db=db,
        order_id=order_id,
        new_status=data.status,
    )


# ============================================================
# GET SINGLE ORDER DETAIL
# ============================================================

@router.get("/{order_id}")
async def get_order_detail(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    result = await db.execute(
        select(Order)
        .options(
            # Customer
            joinedload(Order.user),

            # Order items + product
            selectinload(Order.items).joinedload(
                OrderItem.product
            ),

            # Shipping address
            joinedload(Order.shipping_address),

            # Payment
            joinedload(Order.payment),
        )
        .where(Order.id == order_id)
    )

    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    return order
