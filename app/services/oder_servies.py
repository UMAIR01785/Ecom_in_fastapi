from decimal import Decimal
from datetime import datetime, timedelta
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.services.inventory_service import publish_inventory_updates
from app.websockets.manager import manager

from app.models.cart import Cart, CartItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.order_address import OrderAddress
from app.models.payment import (
    Payment,
    PaymentMethod,
    PaymentStatus,
)
from app.models.product import Product
from app.models.user import User

from app.schemas.oder import CheckoutRequest

from app.services.payment_service import create_payment_session


CARD_RESERVATION_MINUTES = 30
# ============================================================
# CHECKOUT
# ============================================================


async def checkout_cart(
    db: Session,
    current_user: User,
    checkout_data: CheckoutRequest,
):
    try:
        # Lock the cart first to prevent two simultaneous
        # checkouts from consuming the same cart.
        cart = (
            db.query(Cart)
            .filter(Cart.user_id == current_user.id)
            .with_for_update()
            .first()
        )

        if not cart:
            raise HTTPException(404, "Cart not found")

        cart_items = (
            db.query(CartItem)
            .filter(CartItem.cart_id == cart.id)
            .order_by(CartItem.product_id)
            .all()
        )

        if not cart_items:
            raise HTTPException(400, "Cart is empty")

        if checkout_data.payment_method not in (
            PaymentMethod.CARD,
            PaymentMethod.COD,
        ):
            raise HTTPException(400, "Invalid payment method")

        # Lock products in a consistent order to reduce
        # deadlocks when multiple products are purchased.
        product_ids = sorted({
            item.product_id for item in cart_items
        })

        products = (
            db.query(Product)
            .filter(Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update()
            .all()
        )
        product_map = {p.id: p for p in products}

        total_amount = Decimal("0.00")

        for item in cart_items:
            product = product_map.get(item.product_id)

            if not product:
                raise HTTPException(400, "Product no longer exists")

            if not product.is_active:
                raise HTTPException(
                    400,
                    f"Product '{product.name}' is unavailable",
                )

            if item.quantity <= 0:
                raise HTTPException(400, "Invalid cart quantity")

            if product.stock < item.quantity:
                raise HTTPException(
                    400,
                    f"Not enough stock for '{product.name}'",
                )

            total_amount += product.price * item.quantity

        if (
            checkout_data.payment_method == PaymentMethod.CARD
            and total_amount < Decimal("140.00")
        ):
            raise HTTPException(
                400,
                "Card payment requires a higher order amount.",
            )

        
        now = datetime.utcnow()

        reservation_expiry = (
            now + timedelta(minutes=CARD_RESERVATION_MINUTES)
            if checkout_data.payment_method == PaymentMethod.CARD
            else None
        )

        order = Order(
            user_id=current_user.id,
            total_amount=total_amount,
            status=OrderStatus.PENDING,
            reservation_expires_at=reservation_expiry,
            inventory_deducted_at=now,
            inventory_released_at=None,
        )

        db.add(order)
        db.flush()


        address = checkout_data.order_address
        db.add(
            OrderAddress(
                order_id=order.id,
                full_name=address.full_name,
                phone_number=address.phone_number,
                address_line1=address.address_line1,
                address_line2=address.address_line2,
                city=address.city,
                state=address.state,
                postal_code=address.postal_code,
                country=address.country,
                landmark=address.landmark,
            )
        )

        for item in cart_items:
            product = product_map[item.product_id]

            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=item.quantity,
                    unit_price=product.price,
                )
            )

            # Reserve stock for both CARD and COD.
            product.stock -= item.quantity

        payment = Payment(
            order_id=order.id,
            amount=total_amount,
            method=checkout_data.payment_method,
            status=PaymentStatus.PENDING,
        )
        db.add(payment)
        db.flush()

        # Remove cart items within the same transaction.
        for item in cart_items:
            db.delete(item)

        payment_url = None

        if checkout_data.payment_method == PaymentMethod.CARD:
            # Flush order/payment/stock changes, but do not
            # commit before Stripe session creation succeeds.
            db.flush()

            session = await create_payment_session(order, payment)
            payment.session_id = session.id
            payment_url = session.url

        db.commit()
        db.refresh(order)

        if checkout_data.payment_method == PaymentMethod.COD:
            try:
                await manager.send_to_admin({
                    "type": "new_order",
                    "order_id": order.id,
                    "user_id": order.user_id,
                    "total_amount": str(order.total_amount),
                    "status": order.status.value,
                })
            except Exception:
                pass

        return {
            "payment_method": checkout_data.payment_method,
            "order": order,
            "payment_url": payment_url,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Checkout failed. Please try again.",
        )


def release_order_inventory(
    db: Session,
    order: Order,
) -> bool:
    """
    Restore inventory only when:
    1. The order's inventory was deducted.
    2. The inventory has not already been released.

    The caller must lock the order before calling this function.
    """
    if order.inventory_released_at is not None:
        return False

    # Do not guess for old orders whose inventory state is unknown.
    if order.inventory_deducted_at is None:
        return False

    items = (
        db.query(OrderItem)
        .filter(OrderItem.order_id == order.id)
        .order_by(OrderItem.product_id)
        .all()
    )

    product_ids = sorted({
        item.product_id for item in items
    })

    products = (
        db.query(Product)
        .filter(Product.id.in_(product_ids))
        .order_by(Product.id)
        .with_for_update()
        .all()
    )

    product_map = {product.id: product for product in products}

    for item in items:
        product = product_map.get(item.product_id)

        if product is None:
            raise RuntimeError(
                f"Product {item.product_id} is missing "
                f"while releasing order {order.id}"
            )

        product.stock += item.quantity

    # Record the release in the same transaction as the stock update.
    order.inventory_released_at = datetime.utcnow()

    return True

# ============================================================
# CANCEL ORDER
# ============================================================


async def cancel_order(
    db: Session,
    current_user: User,
    order_id: int,
):
    try:
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
            raise HTTPException(404, "Order not found")

        if order.status != OrderStatus.PENDING:
            raise HTTPException(
                400,
                "Only pending orders can be cancelled",
            )

        payment = (
            db.query(Payment)
            .filter(Payment.order_id == order.id)
            .with_for_update()
            .first()
        )

        if payment and payment.status == PaymentStatus.PAID:
            raise HTTPException(
                400,
                "A paid order cannot be cancelled through this endpoint",
            )

        # For orders created by the new checkout workflow,
        # stock is restored exactly once.
        release_order_inventory(db, order)

        order.status = OrderStatus.CANCELLED

        db.commit()
        db.refresh(order)

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            500,
            "Failed to cancel order",
        )

    try:
        await manager.send_to_admin({
            "type": "order_cancelled",
            "order_id": order.id,
            "user_id": order.user_id,
            "status": order.status.value,
        })
    except Exception:
        pass

    return order

# ============================================================
# ORDER STATUS TRANSITIONS
# ============================================================


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


# ============================================================
# UPDATE ORDER STATUS
# ============================================================
async def update_order_status(
    db: Session,
    order_id: int,
    new_status: OrderStatus,
):
    try:
        order = (
            db.query(Order)
            .filter(Order.id == order_id)
            .with_for_update()
            .first()
        )

        if not order:
            raise HTTPException(404, "Order not found")

        allowed = ALLOWED_TRANSITIONS.get(order.status, set())

        if new_status not in allowed:
            raise HTTPException(
                400,
                f"Cannot change order status from "
                f"'{order.status.value}' to '{new_status.value}'",
            )

        payment = (
            db.query(Payment)
            .filter(Payment.order_id == order.id)
            .with_for_update()
            .first()
        )

        if new_status == OrderStatus.CONFIRMED:
            if payment and payment.method == PaymentMethod.CARD:
                if payment.status != PaymentStatus.PAID:
                    raise HTTPException(
                        400,
                        "Card order cannot be confirmed before payment",
                    )

            if order.inventory_released_at is not None:
                raise HTTPException(
                    400,
                    "Cannot confirm an order whose inventory was released",
                )

        if new_status == OrderStatus.CANCELLED:
            if payment and payment.status == PaymentStatus.PAID:
                raise HTTPException(
                    400,
                    "Paid orders require the refund workflow",
                )

            release_order_inventory(db, order)

        order.status = new_status
        db.commit()
        db.refresh(order)

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise HTTPException(
            500,
            "Failed to update order status",
        )

    try:
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
    except Exception:
        pass

    return order