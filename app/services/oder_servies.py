
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
    # 1. Get cart
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

    if not cart.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cart is empty",
        )

    # ========================================================
    # 2. Validate products and calculate total
    # ========================================================

    total_amount = Decimal("0.00")

    locked_products = {}

    for cart_item in cart.items:

        product = (
            db.query(Product)
            .filter(Product.id == cart_item.product_id)
            .with_for_update()
            .first()
        )

        if not product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product no longer exists",
            )

        if not product.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Product '{product.name}' "
                    "is no longer available"
                ),
            )

        if product.stock < cart_item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Not enough stock for "
                    f"'{product.name}'"
                ),
            )

        locked_products[product.id] = product

        total_amount += (
            product.price * cart_item.quantity
        )

    # ========================================================
    # 3. Create Order
    # ========================================================

    order = Order(
        user_id=current_user.id,
        total_amount=total_amount,
        status=OrderStatus.PENDING,
        shipping_address=shipping_address,
    )

    db.add(order)

    # Get generated order.id
    db.flush()

    # ========================================================
    # 4. Create OrderItems
    # ========================================================

    for cart_item in cart.items:

        product = locked_products[
            cart_item.product_id
        ]

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=cart_item.quantity,
            unit_price=product.price,
        )

        db.add(order_item)

    # ========================================================
    # 5. Create Payment
    # ========================================================

    payment = Payment(
        order_id=order.id,
        amount=total_amount,
        method=payment_method,
        status=PaymentStatus.PENDING,
    )

    db.add(payment)

    # Get generated payment.id
    db.flush()

    # ========================================================
    # 6. CARD
    # ========================================================

    if payment_method == PaymentMethod.CARD:
        
        if total_amount < Decimal("140.00"):
            raise HTTPException(
                status_code=400,
                detail="Card payment requires a higher order amount."
            )

        try:

            payment_session = await create_payment_session(
                order=order,
                payment=payment,
            )

            payment.session_id = payment_session.id

            # We can commit the Order + Payment +
            # Stripe session ID together.
            db.commit()

        except Exception:

            db.rollback()

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unable to create payment session",
            )

        db.refresh(order)
        db.refresh(payment)

        # Clear cart after checkout snapshot has been created.
        for cart_item in list(cart.items):
            db.delete(cart_item)

        db.commit()

        db.refresh(order)

        return {
            "payment_method": PaymentMethod.CARD,
            "order": order,
            "payment_url": payment_session.url,
        }

    # ========================================================
    # 7. COD
    # ========================================================

    if payment_method == PaymentMethod.COD:
        

        # For COD, order is accepted immediately.
        # Payment remains pending because customer
        # pays when receiving the order.

        order.status = OrderStatus.CONFIRMED

        # Reserve/decrease stock now.
        for cart_item in cart.items:

            product = locked_products[
                cart_item.product_id
            ]

            product.stock -= cart_item.quantity

            db.delete(cart_item)

        try:

            db.commit()

        except Exception:

            db.rollback()

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="COD checkout failed",
            )

        db.refresh(order)

        try:

            await manager.send_to_admin({
                "type": "new_order",
                "order_id": order.id,
                "user_id": order.user_id,
                "total_amount": str(order.total_amount),
                "status": order.status.value,
            })

        except Exception:
            # WebSocket failure must not
            # undo the database transaction.
            pass

        return {
            "payment_method": PaymentMethod.COD,
            "order": order,
            "payment_url": None,
        }

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