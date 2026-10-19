import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.cart import Cart, CartItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.order_address import OrderAddress
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.product import Product
from app.models.user import User

from app.schemas.oder import CheckoutRequest

from app.services.inventory_service import publish_inventory_updates
from app.services.payment_service import create_payment_session
from app.websockets.manager import manager


logger = logging.getLogger(__name__)

CARD_RESERVATION_MINUTES = 30


# ============================================================
# HELPER: GET PRODUCTS BELONGING TO AN ORDER
# ============================================================

def get_order_products(db: Session, order_id: int) -> list[Product]:
    items = (
        db.query(OrderItem)
        .filter(OrderItem.order_id == order_id)
        .all()
    )

    product_ids = sorted({
        item.product_id for item in items
    })

    if not product_ids:
        return []

    return (
        db.query(Product)
        .filter(Product.id.in_(product_ids))
        .order_by(Product.id)
        .all()
    )


# ============================================================
# CHECKOUT
# ============================================================

async def checkout_cart(
    db: Session,
    current_user: User,
    checkout_data: CheckoutRequest,
):
    try:
        # Lock the cart to prevent concurrent checkouts.
        cart = (
            db.query(Cart)
            .filter(Cart.user_id == current_user.id)
            .with_for_update()
            .first()
        )

        if not cart:
            raise HTTPException(
                status_code=404,
                detail="Cart not found",
            )

        cart_items = (
            db.query(CartItem)
            .filter(CartItem.cart_id == cart.id)
            .order_by(CartItem.product_id)
            .all()
        )

        if not cart_items:
            raise HTTPException(
                status_code=400,
                detail="Cart is empty",
            )

        if checkout_data.payment_method not in (
            PaymentMethod.CARD,
            PaymentMethod.COD,
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid payment method",
            )

        # Lock products in a consistent order.
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

        product_map = {
            product.id: product
            for product in products
        }

        total_amount = Decimal("0.00")

        # Validate products and calculate the order total.
        for item in cart_items:
            product = product_map.get(item.product_id)

            if product is None:
                raise HTTPException(
                    status_code=400,
                    detail="Product no longer exists",
                )

            if not product.is_active:
                raise HTTPException(
                    status_code=400,
                    detail=f"Product '{product.name}' is unavailable",
                )

            if item.quantity <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid cart quantity",
                )

            if product.stock < item.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Not enough stock for '{product.name}'",
                )

            total_amount += product.price * item.quantity

        # Keep your existing minimum amount rule for card payments.
        if (
            checkout_data.payment_method == PaymentMethod.CARD
            and total_amount < Decimal("140.00")
        ):
            raise HTTPException(
                status_code=400,
                detail="Card payment requires a higher order amount.",
            )

        now = datetime.utcnow()

        reservation_expiry = (
            now + timedelta(minutes=CARD_RESERVATION_MINUTES)
            if checkout_data.payment_method == PaymentMethod.CARD
            else None
        )

        # Create the order.
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

        # Save the shipping address.
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

        # Create order items and reserve inventory.
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

            product.stock -= item.quantity

        # Create the payment record.
        payment = Payment(
            order_id=order.id,
            amount=total_amount,
            method=checkout_data.payment_method,
            status=PaymentStatus.PENDING,
        )

        db.add(payment)
        db.flush()

        # Clear the cart in the same transaction.
        for item in cart_items:
            db.delete(item)

        payment_url = None

        # Create a Stripe Checkout Session for card payments.
        if checkout_data.payment_method == PaymentMethod.CARD:
            db.flush()

            session = await create_payment_session(order, payment)

            payment.session_id = session.id
            payment_url = session.url

        # Commit database changes before broadcasting events.
        db.commit()
        db.refresh(order)

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        logger.exception("Checkout failed")

        raise HTTPException(
            status_code=500,
            detail="Failed to create order",
        )

    # Broadcast inventory and order events for BOTH CARD and COD.
    try:
        await publish_inventory_updates(
            products,
            reason="order_placed",
            order_id=order.id,
        )

        await manager.send_to_admin({
            "type": "new_order",
            "order_id": order.id,
            "user_id": order.user_id,
            "total_amount": str(order.total_amount),
            "status": getattr(order.status, "value", str(order.status)),
            "payment_method": getattr(
                checkout_data.payment_method,
                "value",
                str(checkout_data.payment_method),
            ),
        })

    except Exception:
        # The order is already committed; do not report checkout failure
        # just because a WebSocket notification failed.
        logger.exception(
            "Failed to broadcast checkout events for order %s",
            order.id,
        )

    return {
        "payment_method": checkout_data.payment_method,
        "order": order,
        "payment_url": payment_url,
    }


# ============================================================
# RELEASE ORDER INVENTORY
# ============================================================

def release_order_inventory(
    db: Session,
    order: Order,
) -> bool:
    """
    Restore inventory only when it was deducted and has not
    already been released.

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

    product_map = {
        product.id: product
        for product in products
    }

    for item in items:
        product = product_map.get(item.product_id)

        if product is None:
            raise RuntimeError(
                f"Product {item.product_id} is missing "
                f"while releasing order {order.id}"
            )

        product.stock += item.quantity

    # Record release in the same transaction as the stock update.
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
    inventory_products = []
    inventory_changed = False

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
            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        if order.status != OrderStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail="Only pending orders can be cancelled",
            )

        payment = (
            db.query(Payment)
            .filter(Payment.order_id == order.id)
            .with_for_update()
            .first()
        )

        if payment and payment.status == PaymentStatus.PAID:
            raise HTTPException(
                status_code=400,
                detail=(
                    "A paid order cannot be cancelled through "
                    "this endpoint"
                ),
            )

        # Restore stock exactly once.
        inventory_changed = release_order_inventory(db, order)

        if inventory_changed:
            inventory_products = get_order_products(db, order.id)

        order.status = OrderStatus.CANCELLED

        db.commit()
        db.refresh(order)

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        logger.exception("Failed to cancel order %s", order_id)

        raise HTTPException(
            status_code=500,
            detail="Failed to cancel order",
        )

    # Send WebSocket notifications after the successful commit.
    try:
        await manager.send_to_admin({
            "type": "order_cancelled",
            "order_id": order.id,
            "user_id": order.user_id,
            "status": getattr(order.status, "value", str(order.status)),
        })

        if inventory_changed:
            await publish_inventory_updates(
                inventory_products,
                reason="order_cancelled",
                order_id=order.id,
            )

    except Exception:
        logger.exception(
            "Failed to broadcast cancellation events for order %s",
            order.id,
        )

    return order


# ============================================================
# ALLOWED ORDER STATUS TRANSITIONS
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
# ============================================================
# UPDATE ORDER STATUS + REAL-TIME PAYMENT NOTIFICATIONS
# ============================================================

async def update_order_status(
    db: Session,
    order_id: int,
    new_status: OrderStatus,
):
    inventory_products = []
    inventory_changed = False

    try:
        # Lock the order to prevent simultaneous status updates.
        order = (
            db.query(Order)
            .filter(Order.id == order_id)
            .with_for_update()
            .first()
        )

        if not order:
            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        allowed = ALLOWED_TRANSITIONS.get(order.status, set())

        if new_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot change order status from "
                    f"'{getattr(order.status, 'value', order.status)}' "
                    f"to '{getattr(new_status, 'value', new_status)}'"
                ),
            )

        # Find and lock the payment associated with this order.
        payment = (
            db.query(Payment)
            .filter(Payment.order_id == order.id)
            .with_for_update()
            .first()
        )

        # Card orders cannot be confirmed before payment succeeds.
        if new_status == OrderStatus.CONFIRMED:
            if (
                payment
                and payment.method == PaymentMethod.CARD
                and payment.status != PaymentStatus.PAID
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Card order cannot be confirmed before payment",
                )

            if order.inventory_released_at is not None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Cannot confirm an order whose inventory "
                        "was released"
                    ),
                )

        # Restore stock if the admin cancels an unpaid order.
        if new_status == OrderStatus.CANCELLED:
            if payment and payment.status == PaymentStatus.PAID:
                raise HTTPException(
                    status_code=400,
                    detail="Paid orders require the refund workflow",
                )

            inventory_changed = release_order_inventory(db, order)

            if inventory_changed:
                inventory_products = get_order_products(db, order.id)

        # ----------------------------------------------------
        # COD PAYMENT UPDATE ON DELIVERY
        # ----------------------------------------------------
        if new_status == OrderStatus.DELIVERED:
            if not payment:
                raise HTTPException(
                    status_code=400,
                    detail="Payment record not found for this order",
                )

            if payment.method == PaymentMethod.COD:
                if payment.status == PaymentStatus.PENDING:
                    # Assumes cash was collected at delivery.
                    payment.status = PaymentStatus.PAID
                    payment.paid_at = datetime.utcnow()

                elif payment.status != PaymentStatus.PAID:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "COD payment cannot be marked paid "
                            "from its current status"
                        ),
                    )

            elif payment.method == PaymentMethod.CARD:
                if payment.status != PaymentStatus.PAID:
                    raise HTTPException(
                        status_code=400,
                        detail="Card payment must be paid before delivery",
                    )

        # Update order status.
        order.status = new_status

        # Save order and payment changes together.
        db.commit()

        db.refresh(order)

        if payment:
            db.refresh(payment)

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()

        logger.exception(
            "Failed to update status for order %s",
            order_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to update order status",
        )

    # --------------------------------------------------------
    # PREPARE DATA AFTER THE DATABASE COMMIT
    # --------------------------------------------------------
    order_status = getattr(
        order.status,
        "value",
        str(order.status),
    )

    payment_status = (
        getattr(payment.status, "value", str(payment.status))
        if payment
        else None
    )

    payment_method = (
        getattr(payment.method, "value", str(payment.method))
        if payment
        else None
    )

    payment_data = {
        "order_id": order.id,
        "payment_id": payment.id if payment else None,
        "payment_method": payment_method,
        "payment_status": payment_status,
        "order_status": order_status,
        "paid_at": (
            payment.paid_at.isoformat()
            if payment and payment.paid_at
            else None
        ),
    }

    # --------------------------------------------------------
    # NOTIFY CUSTOMER OF ORDER STATUS
    # --------------------------------------------------------
    try:
        await manager.send_to_user(
            order.user_id,
            {
                "event": "order_status_updated",
                "data": {
                    "order_id": order.id,
                    "status": order_status,
                },
            },
        )
    except Exception:
        logger.exception(
            "Failed to notify customer of order status for order %s",
            order.id,
        )

    # --------------------------------------------------------
    # NOTIFY ADMIN OF ORDER STATUS
    # --------------------------------------------------------
    try:
        await manager.send_to_admin({
            "type": "order_status_updated",
            "user_id": order.user_id,
            **payment_data,
        })
    except Exception:
        logger.exception(
            "Failed to notify admin of order status for order %s",
            order.id,
        )

    # --------------------------------------------------------
    # REAL-TIME COD PAYMENT EVENT
    # --------------------------------------------------------
    if (
        new_status == OrderStatus.DELIVERED
        and payment is not None
        and payment.method == PaymentMethod.COD
        and payment.status == PaymentStatus.PAID
    ):
        # Notify the customer.
        try:
            await manager.send_to_user(
                order.user_id,
                {
                    "event": "payment_status_updated",
                    "data": payment_data,
                },
            )
        except Exception:
            logger.exception(
                "Failed to send COD payment update to customer for order %s",
                order.id,
            )

        # Notify the admin.
        try:
            await manager.send_to_admin({
                "type": "payment_status_updated",
                "user_id": order.user_id,
                **payment_data,
            })
        except Exception:
            logger.exception(
                "Failed to send COD payment update to admin for order %s",
                order.id,
            )

    # --------------------------------------------------------
    # BROADCAST INVENTORY UPDATE IF CANCELLATION RESTORED STOCK
    # --------------------------------------------------------
    if inventory_changed:
        try:
            await publish_inventory_updates(
                inventory_products,
                reason="order_cancelled",
                order_id=order.id,
            )
        except Exception:
            logger.exception(
                "Failed to broadcast restored inventory for order %s",
                order.id,
            )

    return order