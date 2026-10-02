
from decimal import Decimal
from app.models.payment import (
    Payment,
    PaymentMethod,
    PaymentStatus,
)

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.websockets.manager import manager
from app.models.cart import Cart, CartItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User
from app.services.payment_service import create_payment_session


# ============================================================
# CHECKOUT
# ============================================================

async def checkout_cart(
    db: Session,
    current_user: User,
    shipping_address: str,
    payment_method: PaymentMethod,
):

    # ========================================================
    # 1. Get user's cart
    # ========================================================

    cart = (
        db.query(Cart)
        .options(
            joinedload(Cart.items)
            .joinedload(CartItem.product)
        )
        .filter(
            Cart.user_id == current_user.id
        )
        .first()
    )

    if not cart:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart not found",
        )

    # ========================================================
    # 2. Check empty cart
    # ========================================================

    if not cart.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cart is empty",
        )

    # ========================================================
    # 3. Lock products + validate stock + calculate total
    # ========================================================

    total_amount = Decimal("0.00")

    locked_products = {}

    for cart_item in cart.items:

        product = (
            db.query(Product)
            .filter(
                Product.id == cart_item.product.id
            )
            .with_for_update()
            .first()
        )

        if not product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A product in your cart no longer exists",
            )

        locked_products[product.id] = product

        # ----------------------------------------------------
        # Product inactive
        # ----------------------------------------------------

        if not product.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Product '{product.name}' "
                    "is no longer available"
                ),
            )

        # ----------------------------------------------------
        # Check stock
        # ----------------------------------------------------

        if product.stock < cart_item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Not enough stock for "
                    f"'{product.name}'"
                ),
            )

        # ----------------------------------------------------
        # Calculate total using current DB price
        # ----------------------------------------------------

        total_amount += (
            product.price * cart_item.quantity
        )

    # ========================================================
    # 4. COD FLOW
    # ========================================================

    if payment_method == PaymentMethod.COD:

        # ----------------------------------------------------
        # Create Order
        # ----------------------------------------------------

        order = Order(
            user_id=current_user.id,
            status=OrderStatus.PENDING,
            total_amount=total_amount,
            shipping_address=shipping_address,
        )

        db.add(order)

        # Generate order.id
        db.flush()

        # ----------------------------------------------------
        # Create OrderItems + decrease stock
        # ----------------------------------------------------

        for cart_item in cart.items:

            product = locked_products[
                cart_item.product.id
            ]

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=cart_item.quantity,
                unit_price=product.price,
            )

            db.add(order_item)

            # Reserve/remove stock
            product.stock -= cart_item.quantity

        # ----------------------------------------------------
        # Create COD Payment
        # ----------------------------------------------------

        payment = Payment(
            order_id=order.id,
            amount=total_amount,
            method=PaymentMethod.COD,
            status=PaymentStatus.PENDING,
        )

        db.add(payment)

        # ----------------------------------------------------
        # Clear cart
        # ----------------------------------------------------

        for cart_item in cart.items:
            db.delete(cart_item)

        # ----------------------------------------------------
        # Commit everything
        # ----------------------------------------------------

        try:

            db.commit()

        except Exception:

            db.rollback()

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="COD checkout failed",
            )

        # ----------------------------------------------------
        # Refresh
        # ----------------------------------------------------

        db.refresh(order)

        return {
            "payment_method": PaymentMethod.COD,
            "order": order,
            "payment": payment,
            "payment_url": None,
        }

    # ========================================================
    # 5. CARD FLOW
    # ========================================================

    if payment_method == PaymentMethod.CARD:

        # ----------------------------------------------------
        # IMPORTANT:
        #
        # DO NOT create Order
        # DO NOT create OrderItem
        # DO NOT decrease stock
        #
        # because payment has not succeeded yet.
        # ----------------------------------------------------

        payment = Payment(
    order_id=order.id,
    amount=order.total_amount,
    method=PaymentMethod.CARD,
    status=PaymentStatus.PENDING
)

        db.add(payment)

        # Generate payment.id
        db.flush()

        # ----------------------------------------------------
        # Create Stripe Checkout Session
        # ----------------------------------------------------

        try:

            payment_session = (
                await create_payment_session(
                    amount=total_amount,
                    payment=payment,
                    shipping_address=shipping_address,
                    user_id=current_user.id,
                )
            )

            # ------------------------------------------------
            # Save Stripe session ID
            # ------------------------------------------------

            payment.session_id = payment_session.id

            # ------------------------------------------------
            # Commit payment + Stripe session ID
            # ------------------------------------------------

            db.commit()

        except Exception:

            db.rollback()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to create payment session",
            )

        # ----------------------------------------------------
        # Refresh payment
        # ----------------------------------------------------

        db.refresh(payment)

        # ----------------------------------------------------
        # Return Stripe URL
        # ----------------------------------------------------

        return {
            "payment_method": PaymentMethod.CARD,
            "order": None,
            "payment": payment,
            "payment_url": payment_session.url,
        }

    # ========================================================
    # 6. Invalid payment method
    # ========================================================

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid payment method",
    )
    
# CANCEL ORDER
# ============================================================

async def cancel_order(
    db: Session,
    current_user: User,
    order_id: int,
):

    # ========================================================
    # 1. Get and lock user's order
    # ========================================================

    order = (
        db.query(Order)
        .filter(
            Order.id == order_id,
            Order.user_id == current_user.id,
        )
        .with_for_update()
        .first()
    )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    # ========================================================
    # 2. Only pending orders can be cancelled
    # ========================================================

    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending orders can be cancelled",
        )

    # ========================================================
    # 3. Restore product stock
    # ========================================================

    for order_item in order.items:

        product = (
            db.query(Product)
            .filter(Product.id == order_item.product_id)
            .with_for_update()
            .first()
        )

        if product:
            product.stock += order_item.quantity

    # ========================================================
    # 4. Change order status
    # ========================================================

    order.status = OrderStatus.CANCELLED

    # ========================================================
    # 5. Commit transaction
    # ========================================================

    try:

        db.commit()
      

    except Exception:

        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel order",
        )

    # ========================================================
    # 6. Refresh order
    # ========================================================

    db.refresh(order)
    
    try:
        await manager.send_to_admin({
        "type": "order_cancelled",
        "order_id": order.id,
        "user_id": order.user_id,
        "status": order.status.value,
    })
    except Exception:
    # Do not rollback here because the DB transaction
    # has already been committed.
        pass

    return order



ALLOWED_TRANSITIONS = {
    OrderStatus.PENDING: {
        OrderStatus.CONFIRMED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.CONFIRMED: {
        OrderStatus.PROCESSING,
    },
    OrderStatus.PROCESSING: {
        OrderStatus.SHIPPED,
    },
    OrderStatus.SHIPPED: {
        OrderStatus.DELIVERED,
    },
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
}


async def update_order_status(
    db: Session,
    order_id: int,
    new_status: OrderStatus,
):
    # 1. Get and lock the order
    order = (
        db.query(Order)
        .filter(Order.id == order_id)
        .with_for_update()
        .first()
    )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    # 2. Get allowed next statuses
    allowed_statuses = ALLOWED_TRANSITIONS[order.status]

    # 3. Check whether transition is valid
    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot change order status "
                f"from '{order.status.value}' "
                f"to '{new_status.value}'"
            ),
        )

    # 4. Change status
    order.status = new_status

    # 5. Save transaction
    try:
        db.commit()

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update order status",
        )

    # 6. Reload updated order
    db.refresh(order)
     # --------------------------------------------------------
    # 7. Send real-time WebSocket event
    # --------------------------------------------------------

    await manager.send_to_user(
        order.user_id,
        {
            "event": "order_status_updated",
            "data": {
                "order_id": order.id,
                "status": order.status.value,
            },
        },
    )

    return order