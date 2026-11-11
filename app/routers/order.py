
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.database import get_db
from app.dependencies.auth import get_current_user

from app.models.order import Order, OrderItem
from app.models.user import User

from app.schemas.oder import (
    CheckoutRequest,
    CheckoutResponse,
    OrderResponse,
)

from app.services.oder_servies import (
    checkout_cart,
    cancel_order,
)


router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
)


# ============================================================
# CHECKOUT
# ============================================================

@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def checkout(
    checkout_data: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await checkout_cart(
        db=db,
        current_user=current_user,
        checkout_data=checkout_data,
    )


# ============================================================
# GET MY ORDERS
# ============================================================

@router.get(
    "/",
    response_model=list[OrderResponse],
)
async def get_my_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(Order)
        .options(
            # Order items and their products
            selectinload(Order.items).joinedload(
                OrderItem.product
            ),

            # Payment
            selectinload(Order.payment),

            # Shipping address
            selectinload(Order.shipping_address),
        )
        .where(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
    )

    result = await db.execute(query)

    orders = result.scalars().all()

    return orders


# ============================================================
# GET SINGLE ORDER
# ============================================================

@router.get(
    "/{order_id}",
    response_model=OrderResponse,
)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(Order)
        .options(
            # Order items and their products
            selectinload(Order.items).joinedload(
                OrderItem.product
            ),

            # Payment
            selectinload(Order.payment),

            # Shipping address
            selectinload(Order.shipping_address),
        )
        .where(
            Order.id == order_id,
            Order.user_id == current_user.id,
        )
    )

    result = await db.execute(query)

    order = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    return order


# ============================================================
# CANCEL MY ORDER
# ============================================================

@router.patch(
    "/{order_id}/cancel",
    response_model=OrderResponse,
)
async def cancel_my_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await cancel_order(
        db=db,
        current_user=current_user,
        order_id=order_id,
    )
