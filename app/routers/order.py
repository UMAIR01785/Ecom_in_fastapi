from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.order import Order, OrderItem
from app.models.user import User
from app.websockets.manager import manager
from app.database import get_db
from app.dependencies.auth import get_current_user

from app.schemas.oder import CheckoutRequest, OrderResponse,CheckoutResponse
from app.services.oder_servies import checkout_cart ,cancel_order


router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
)


# ============================================
# CHECKOUT
# ============================================


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def checkout(
    checkout_data: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # --------------------------------------------------------
    # 1. Process checkout
    # --------------------------------------------------------

    checkout_result = await checkout_cart(
        db=db,
        current_user=current_user,
        shipping_address=checkout_data.shipping_address,
        payment_method=checkout_data.payment_method,
    )

    # --------------------------------------------------------
    # 2. Get Order from checkout result
    # --------------------------------------------------------

    order = checkout_result.get("order")

    # --------------------------------------------------------
    # 3. Notify admin only if an Order was actually created
    # --------------------------------------------------------

    if order:
        await manager.send_to_admin({
            "type": "new_order",
            "order_id": order.id,
            "user_id": order.user_id,
            "total_amount": str(order.total_amount),
            "status": order.status.value,
        })

    # --------------------------------------------------------
    # 4. Return checkout response to frontend
    # --------------------------------------------------------

    return checkout_result

# ============================================
# GET MY ORDERS
# ============================================

@router.get(
    "/",
    response_model=list[OrderResponse],
)
def get_my_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    orders = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product)
        )
        .filter(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
        .all()
    )

    return orders


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    order = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product)
        )
        .filter(
            Order.id == order_id,
            Order.user_id == current_user.id,
        )
        .first()
    )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    return order


@router.patch(
    "/{order_id}/cancel",
    response_model=OrderResponse,
)
async def cancel_my_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await cancel_order(
        db=db,
        current_user=current_user,
        order_id=order_id,
    )