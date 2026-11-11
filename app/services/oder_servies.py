
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import Cart, CartItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.order_address import OrderAddress
from app.models.orderitem_lot import OrderItemLot
from app.models.invertory_lots import InventoryLot
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.product import Product
from app.models.product_variant import ProductVariant
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

async def get_order_products(
    db: AsyncSession,
    order_id: int,
) -> list[Product]:

    result = await db.execute(
        select(OrderItem.product_id)
        .where(OrderItem.order_id == order_id)
        .distinct()
    )

    product_ids = sorted(result.scalars().all())

    if not product_ids:
        return []

    result = await db.execute(
        select(Product)
        .where(Product.id.in_(product_ids))
        .order_by(Product.id)
    )

    return result.scalars().all()


# ============================================================
# HELPER: GET VARIANTS BELONGING TO AN ORDER
# ============================================================

async def get_order_variants(
    db: AsyncSession,
    order_id: int,
) -> list[ProductVariant]:

    result = await db.execute(
        select(OrderItem.variant_id)
        .where(
            OrderItem.order_id == order_id,
            OrderItem.variant_id.is_not(None),
        )
        .distinct()
    )

    variant_ids = sorted(
        result.scalars().all()
    )

    if not variant_ids:
        return []

    result = await db.execute(
        select(ProductVariant)
        .where(ProductVariant.id.in_(variant_ids))
        .order_by(ProductVariant.id)
    )

    return result.scalars().all()


# ============================================================
# CONSUME INVENTORY LOTS
# ============================================================

async def consume_inventory_lots(
    db: AsyncSession,
    order_item: OrderItem,
    product_id: int,
    variant_id: int | None,
    quantity: int,
) -> None:
    """
    Deduct stock from inventory lots and record allocations.

    FEFO: earliest expiry first.
    Lots without expiry dates are used after dated lots.
    Expired and depleted lots are excluded.

    The caller must commit or roll back the surrounding transaction.
    """

    now = datetime.utcnow()

    query = select(InventoryLot).where(
        InventoryLot.quantity_remaining > 0,
        or_(
            InventoryLot.expires_at.is_(None),
            InventoryLot.expires_at > now,
        ),
    )

    if variant_id is not None:
        query = query.where(
            InventoryLot.variant_id == variant_id,
            InventoryLot.product_id.is_(None),
        )
    else:
        query = query.where(
            InventoryLot.product_id == product_id,
            InventoryLot.variant_id.is_(None),
        )

    query = (
        query
        .order_by(
            InventoryLot.expires_at.asc().nullslast(),
            InventoryLot.received_at.asc(),
            InventoryLot.id.asc(),
        )
        .with_for_update()
    )

    result = await db.execute(query)
    lots = result.scalars().all()

    available = sum(
        lot.quantity_remaining for lot in lots
    )

    if available < quantity:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient eligible inventory lots for "
                f"product {product_id}"
            ),
        )

    remaining = quantity

    for lot in lots:
        if remaining == 0:
            break

        deducted = min(
            lot.quantity_remaining,
            remaining,
        )

        lot.quantity_remaining -= deducted

        allocation = OrderItemLot(
            order_item_id=order_item.id,
            inventory_lot_id=lot.id,
            quantity=deducted,
        )

        db.add(allocation)

        remaining -= deducted

    await db.flush()


# ============================================================
# CHECKOUT
# ============================================================

async def checkout_cart(
    db: AsyncSession,
    current_user: User,
    checkout_data: CheckoutRequest,
):
    try:
        # ----------------------------------------------------
        # 1. LOCK CUSTOMER CART
        # ----------------------------------------------------

        result = await db.execute(
            select(Cart)
            .where(Cart.user_id == current_user.id)
            .with_for_update()
        )

        cart = result.scalar_one_or_none()

        if not cart:
            raise HTTPException(
                status_code=404,
                detail="Cart not found",
            )

        # ----------------------------------------------------
        # 2. GET CART ITEMS
        # ----------------------------------------------------

        result = await db.execute(
            select(CartItem)
            .where(CartItem.cart_id == cart.id)
            .order_by(
                CartItem.product_id,
                CartItem.variant_id,
                CartItem.id,
            )
        )

        cart_items = result.scalars().all()

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

        # ----------------------------------------------------
        # 3. LOCK PRODUCTS
        # ----------------------------------------------------

        product_ids = sorted({
            item.product_id for item in cart_items
        })

        result = await db.execute(
            select(Product)
            .where(Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update()
        )

        products = result.scalars().all()

        product_map = {
            product.id: product
            for product in products
        }

        # ----------------------------------------------------
        # 4. LOCK VARIANTS
        # ----------------------------------------------------

        result = await db.execute(
            select(ProductVariant)
            .where(
                ProductVariant.product_id.in_(product_ids)
            )
            .order_by(ProductVariant.id)
            .with_for_update()
        )

        variants = result.scalars().all()

        variant_map = {
            variant.id: variant
            for variant in variants
        }

        variants_by_product = {}

        for variant in variants:
            variants_by_product.setdefault(
                variant.product_id,
                [],
            ).append(variant)

        # ----------------------------------------------------
        # 5. VALIDATE PRODUCTS AND CALCULATE TOTAL
        # ----------------------------------------------------

        total_amount = Decimal("0.00")

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

            variant = None

            if item.variant_id is not None:
                variant = variant_map.get(item.variant_id)

                if (
                    variant is None
                    or variant.product_id != product.id
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Selected variant for "
                            f"'{product.name}' is invalid"
                        ),
                    )

                if not variant.is_active:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Selected size/color for "
                            f"'{product.name}' is unavailable"
                        ),
                    )

            elif variants_by_product.get(product.id):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Select a size and color for "
                        f"'{product.name}'"
                    ),
                )

            available_stock = (
                variant.stock
                if variant is not None
                else product.stock
            )

            if available_stock < item.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Not enough stock for '{product.name}'",
                )

            unit_price = (
                Decimal(str(variant.price))
                if variant is not None and variant.price is not None
                else Decimal(str(product.price))
            )

            total_amount += unit_price * item.quantity

        # ----------------------------------------------------
        # 6. CARD PAYMENT MINIMUM AMOUNT
        # ----------------------------------------------------

        if (
            checkout_data.payment_method == PaymentMethod.CARD
            and total_amount < Decimal("140.00")
        ):
            raise HTTPException(
                status_code=400,
                detail="Card payment requires a higher order amount.",
            )

        # ----------------------------------------------------
        # 7. ORDER RESERVATION
        # ----------------------------------------------------

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

        await db.flush()

        # ----------------------------------------------------
        # 8. SAVE SHIPPING ADDRESS
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 9. CREATE ORDER ITEMS AND CONSUME INVENTORY
        # ----------------------------------------------------

        changed_variants = []

        for item in cart_items:
            product = product_map[item.product_id]

            variant = (
                variant_map.get(item.variant_id)
                if item.variant_id is not None
                else None
            )

            unit_price = (
                Decimal(str(variant.price))
                if variant is not None and variant.price is not None
                else Decimal(str(product.price))
            )

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                variant_id=(
                    variant.id if variant is not None else None
                ),
                variant_sku=(
                    variant.sku if variant is not None else None
                ),
                variant_size=(
                    variant.size if variant is not None else None
                ),
                variant_color=(
                    variant.color if variant is not None else None
                ),
                quantity=item.quantity,
                unit_price=unit_price,
            )

            db.add(order_item)

            await db.flush()

            # Deduct from exact inventory lots using FEFO.
            await consume_inventory_lots(
                db=db,
                order_item=order_item,
                product_id=product.id,
                variant_id=(
                    variant.id if variant is not None else None
                ),
                quantity=item.quantity,
            )

            # Maintain aggregate stock fields.
            if variant is not None:
                variant.stock -= item.quantity
                changed_variants.append(variant)
            else:
                product.stock -= item.quantity

        # ----------------------------------------------------
        # 10. CREATE PAYMENT
        # ----------------------------------------------------

        payment = Payment(
            order_id=order.id,
            amount=total_amount,
            method=checkout_data.payment_method,
            status=PaymentStatus.PENDING,
        )

        db.add(payment)

        await db.flush()

        # ----------------------------------------------------
        # 11. CLEAR CART
        # ----------------------------------------------------

        for item in cart_items:
            await db.delete(item)

        payment_url = None

        # ----------------------------------------------------
        # 12. CREATE STRIPE SESSION
        # ----------------------------------------------------

        if checkout_data.payment_method == PaymentMethod.CARD:
            await db.flush()

            stripe_session = await create_payment_session(
                order,
                payment,
            )

            payment.session_id = stripe_session.id
            payment_url = stripe_session.url

        # ----------------------------------------------------
        # 13. COMMIT TRANSACTION
        # ----------------------------------------------------

        await db.commit()

        await db.refresh(order)

    except HTTPException:
        await db.rollback()
        raise

    except Exception:
        await db.rollback()

        logger.exception("Checkout failed")

        raise HTTPException(
            status_code=500,
            detail="Failed to create order",
        )

    # ========================================================
    # BROADCAST AFTER SUCCESSFUL COMMIT
    # ========================================================

    try:
        await publish_inventory_updates(
            products,
            variants=changed_variants,
            reason="order_placed",
            order_id=order.id,
        )

        await manager.send_to_admin({
            "type": "new_order",
            "order_id": order.id,
            "user_id": order.user_id,
            "total_amount": str(order.total_amount),
            "status": getattr(
                order.status,
                "value",
                str(order.status),
            ),
            "payment_method": getattr(
                checkout_data.payment_method,
                "value",
                str(checkout_data.payment_method),
            ),
        })

    except Exception:
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

async def release_order_inventory(
    db: AsyncSession,
    order: Order,
) -> bool:
    """
    Restore aggregate stock and the exact lots consumed by an order.

    The caller must lock the order before calling this function.
    The caller is responsible for committing the transaction.
    """

    if order.inventory_released_at is not None:
        return False

    if order.inventory_deducted_at is None:
        return False

    # --------------------------------------------------------
    # 1. LOAD ORDER ITEMS
    # --------------------------------------------------------

    result = await db.execute(
        select(OrderItem)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.product_id, OrderItem.id)
    )

    items = result.scalars().all()

    product_ids = sorted({
        item.product_id for item in items
    })

    variant_ids = sorted({
        item.variant_id
        for item in items
        if item.variant_id is not None
    })

    # --------------------------------------------------------
    # 2. LOCK PRODUCTS
    # --------------------------------------------------------

    if product_ids:
        result = await db.execute(
            select(Product)
            .where(Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update()
        )

        products = result.scalars().all()
    else:
        products = []

    product_map = {
        product.id: product
        for product in products
    }

    # --------------------------------------------------------
    # 3. LOCK VARIANTS
    # --------------------------------------------------------

    if variant_ids:
        result = await db.execute(
            select(ProductVariant)
            .where(ProductVariant.id.in_(variant_ids))
            .order_by(ProductVariant.id)
            .with_for_update()
        )

        variants = result.scalars().all()
    else:
        variants = []

    variant_map = {
        variant.id: variant
        for variant in variants
    }

    # --------------------------------------------------------
    # 4. LOAD INVENTORY ALLOCATIONS
    # --------------------------------------------------------

    result = await db.execute(
        select(OrderItemLot)
        .join(
            OrderItem,
            OrderItem.id == OrderItemLot.order_item_id,
        )
        .where(OrderItem.order_id == order.id)
        .order_by(
            OrderItemLot.inventory_lot_id,
            OrderItemLot.id,
        )
    )

    allocations = result.scalars().all()

    allocations_by_item = {}

    for allocation in allocations:
        allocations_by_item.setdefault(
            allocation.order_item_id,
            [],
        ).append(allocation)

    # --------------------------------------------------------
    # 5. LOCK REFERENCED LOTS
    # --------------------------------------------------------

    lot_ids = sorted({
        allocation.inventory_lot_id
        for allocation in allocations
    })

    if lot_ids:
        result = await db.execute(
            select(InventoryLot)
            .where(InventoryLot.id.in_(lot_ids))
            .order_by(InventoryLot.id)
            .with_for_update()
        )

        lots = result.scalars().all()
    else:
        lots = []

    lot_map = {
        lot.id: lot
        for lot in lots
    }

    # --------------------------------------------------------
    # 6. VALIDATE ALLOCATIONS BEFORE RESTORING
    # --------------------------------------------------------

    for item in items:
        item_allocations = allocations_by_item.get(
            item.id,
            [],
        )

        allocated_quantity = sum(
            allocation.quantity
            for allocation in item_allocations
        )

        if allocated_quantity != item.quantity:
            raise RuntimeError(
                f"Order {order.id}, item {item.id}: expected "
                f"{item.quantity} allocated units, found "
                f"{allocated_quantity}. Inventory was not released."
            )

        for allocation in item_allocations:
            if allocation.inventory_lot_id not in lot_map:
                raise RuntimeError(
                    f"Inventory lot {allocation.inventory_lot_id} "
                    f"is missing for order {order.id}"
                )

    # --------------------------------------------------------
    # 7. RESTORE LOTS AND AGGREGATE STOCK
    # --------------------------------------------------------

    for item in items:
        item_allocations = allocations_by_item.get(
            item.id,
            [],
        )

        for allocation in item_allocations:
            lot = lot_map[allocation.inventory_lot_id]

            lot.quantity_remaining += allocation.quantity

        if item.variant_id is not None:
            variant = variant_map.get(item.variant_id)

            if variant is None:
                raise RuntimeError(
                    f"Variant {item.variant_id} is missing "
                    f"while releasing order {order.id}"
                )

            variant.stock += item.quantity

        else:
            product = product_map.get(item.product_id)

            if product is None:
                raise RuntimeError(
                    f"Product {item.product_id} is missing "
                    f"while releasing order {order.id}"
                )

            product.stock += item.quantity

    order.inventory_released_at = datetime.utcnow()

    await db.flush()

    return True


# ============================================================
# CANCEL ORDER
# ============================================================

async def cancel_order(
    db: AsyncSession,
    current_user: User,
    order_id: int,
):
    inventory_products = []
    inventory_variants = []
    inventory_changed = False

    try:
        # ----------------------------------------------------
        # 1. LOCK CUSTOMER ORDER
        # ----------------------------------------------------

        result = await db.execute(
            select(Order)
            .where(
                Order.id == order_id,
                Order.user_id == current_user.id,
            )
            .with_for_update()
        )

        order = result.scalar_one_or_none()

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

        # ----------------------------------------------------
        # 2. LOCK PAYMENT
        # ----------------------------------------------------

        result = await db.execute(
            select(Payment)
            .where(Payment.order_id == order.id)
            .with_for_update()
        )

        payment = result.scalar_one_or_none()

        if payment and payment.status == PaymentStatus.PAID:
            raise HTTPException(
                status_code=400,
                detail=(
                    "A paid order cannot be cancelled through "
                    "this endpoint"
                ),
            )

        # ----------------------------------------------------
        # 3. RESTORE INVENTORY
        # ----------------------------------------------------

        inventory_changed = await release_order_inventory(
            db,
            order,
        )

        if inventory_changed:
            inventory_products = await get_order_products(
                db,
                order.id,
            )

            inventory_variants = await get_order_variants(
                db,
                order.id,
            )

        order.status = OrderStatus.CANCELLED

        await db.commit()
        await db.refresh(order)

    except HTTPException:
        await db.rollback()
        raise

    except Exception:
        await db.rollback()

        logger.exception(
            "Failed to cancel order %s",
            order_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to cancel order",
        )

    # --------------------------------------------------------
    # 4. WEBSOCKET NOTIFICATIONS AFTER COMMIT
    # --------------------------------------------------------

    try:
        await manager.send_to_admin({
            "type": "order_cancelled",
            "order_id": order.id,
            "user_id": order.user_id,
            "status": getattr(
                order.status,
                "value",
                str(order.status),
            ),
        })

        if inventory_changed:
            await publish_inventory_updates(
                inventory_products,
                variants=inventory_variants,
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

async def update_order_status(
    db: AsyncSession,
    order_id: int,
    new_status: OrderStatus,
):
    inventory_products = []
    inventory_variants = []
    inventory_changed = False

    try:
        # ----------------------------------------------------
        # 1. LOCK ORDER
        # ----------------------------------------------------

        result = await db.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
        )

        order = result.scalar_one_or_none()

        if not order:
            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        allowed = ALLOWED_TRANSITIONS.get(
            order.status,
            set(),
        )

        if new_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot change order status from "
                    f"'{getattr(order.status, 'value', order.status)}' "
                    f"to '{getattr(new_status, 'value', new_status)}'"
                ),
            )

        # ----------------------------------------------------
        # 2. LOCK PAYMENT
        # ----------------------------------------------------

        result = await db.execute(
            select(Payment)
            .where(Payment.order_id == order.id)
            .with_for_update()
        )

        payment = result.scalar_one_or_none()

        # ----------------------------------------------------
        # 3. VALIDATE CARD CONFIRMATION
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # 4. RESTORE STOCK IF ADMIN CANCELS UNPAID ORDER
        # ----------------------------------------------------

        if new_status == OrderStatus.CANCELLED:

            if payment and payment.status == PaymentStatus.PAID:
                raise HTTPException(
                    status_code=400,
                    detail="Paid orders require the refund workflow",
                )

            inventory_changed = await release_order_inventory(
                db,
                order,
            )

            if inventory_changed:
                inventory_products = await get_order_products(
                    db,
                    order.id,
                )

                inventory_variants = await get_order_variants(
                    db,
                    order.id,
                )

        # ----------------------------------------------------
        # 5. COD PAYMENT UPDATE ON DELIVERY
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

        # ----------------------------------------------------
        # 6. SAVE ORDER AND PAYMENT
        # ----------------------------------------------------

        order.status = new_status

        await db.commit()

        await db.refresh(order)

        if payment:
            await db.refresh(payment)

    except HTTPException:
        await db.rollback()
        raise

    except Exception:
        await db.rollback()

        logger.exception(
            "Failed to update status for order %s",
            order_id,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to update order status",
        )

    # ========================================================
    # PREPARE DATA AFTER COMMIT
    # ========================================================

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
    # 7. NOTIFY CUSTOMER OF ORDER STATUS
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
    # 8. NOTIFY ADMIN OF ORDER STATUS
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
    # 9. COD PAYMENT EVENT
    # --------------------------------------------------------

    if (
        new_status == OrderStatus.DELIVERED
        and payment is not None
        and payment.method == PaymentMethod.COD
        and payment.status == PaymentStatus.PAID
    ):

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
                "Failed to send COD payment update to customer "
                "for order %s",
                order.id,
            )

        try:
            await manager.send_to_admin({
                "type": "payment_status_updated",
                "user_id": order.user_id,
                **payment_data,
            })

        except Exception:
            logger.exception(
                "Failed to send COD payment update to admin "
                "for order %s",
                order.id,
            )

    # --------------------------------------------------------
    # 10. BROADCAST RESTORED INVENTORY
    # --------------------------------------------------------

    if inventory_changed:
        try:
            await publish_inventory_updates(
                inventory_products,
                variants=inventory_variants,
                reason="order_cancelled",
                order_id=order.id,
            )

        except Exception:
            logger.exception(
                "Failed to broadcast restored inventory for order %s",
                order.id,
            )

    return order
