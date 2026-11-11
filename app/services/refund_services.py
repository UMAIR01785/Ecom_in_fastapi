
import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

import stripe
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.order import Order, OrderItem, OrderStatus
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.product import Product
from app.models.refund import Refund, RefundStatus
from app.models.user import User
from app.services.inventory_service import publish_inventory_updates
from app.websockets.manager import manager


logger = logging.getLogger(__name__)
stripe.api_key = settings.stripe_secret_key


def utc_now():
    return datetime.now(timezone.utc)


# ============================================================
# REAL-TIME REFUND NOTIFICATIONS
# ============================================================

async def notify_refund_update(
    refund: Refund,
    order: Order,
    payment: Payment,
) -> None:

    message_data = {
        "refund_id": refund.id,
        "order_id": order.id,
        "refund_status": refund.status.value,
        "payment_status": payment.status.value,
        "payment_method": payment.method.value,
        "order_status": order.status.value,
        "amount": str(refund.amount),
        "completed_at": (
            refund.completed_at.isoformat()
            if refund.completed_at else None
        ),
    }

    try:
        await manager.send_to_user(
            order.user_id,
            {
                "event": "refund_status_updated",
                "data": message_data,
            },
        )
    except Exception:
        logger.exception(
            "Failed to notify customer about refund %s",
            refund.id,
        )

    try:
        await manager.send_to_admin({
            "type": "refund_status_updated",
            "user_id": order.user_id,
            **message_data,
        })
    except Exception:
        logger.exception(
            "Failed to notify admin about refund %s",
            refund.id,
        )


# ============================================================
# CUSTOMER: REQUEST A REFUND
# ============================================================

async def request_refund(
    db: AsyncSession,
    user: User,
    order_id: int,
    reason: str,
) -> Refund:

    if not reason or not reason.strip():
        raise HTTPException(422, "A refund reason is required")

    result = await db.execute(
        select(Order)
        .where(
            Order.id == order_id,
            Order.user_id == user.id,
        )
        .with_for_update()
    )
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(404, "Order not found")

    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(
            400,
            "Refunds can only be requested after delivery",
        )

    result = await db.execute(
        select(Payment)
        .where(Payment.order_id == order.id)
        .with_for_update()
    )
    payment = result.scalar_one_or_none()

    if not payment:
        raise HTTPException(400, "Payment record not found")

    if payment.status != PaymentStatus.PAID:
        raise HTTPException(
            400,
            "The payment must be marked paid before requesting a refund",
        )

    result = await db.execute(
        select(Refund).where(Refund.order_id == order.id)
    )
    existing_refund = result.scalar_one_or_none()

    if existing_refund:
        raise HTTPException(
            409,
            "A refund request already exists for this order",
        )

    refund = Refund(
        order_id=order.id,
        requested_by=user.id,
        amount=Decimal(str(payment.amount)),
        reason=reason.strip(),
        status=RefundStatus.REQUESTED,
    )

    db.add(refund)

    try:
        await db.commit()
        await db.refresh(refund)

    except Exception:
        await db.rollback()
        logger.exception("Refund request creation failed")

        raise HTTPException(
            409,
            "Could not create refund request",
        )

    return refund


# ============================================================
# CUSTOMER: VIEW OWN REFUNDS
# ============================================================

async def list_my_refunds(
    db: AsyncSession,
    user: User,
) -> list[Refund]:

    result = await db.execute(
        select(Refund)
        .where(Refund.requested_by == user.id)
        .order_by(Refund.requested_at.desc())
    )

    return result.scalars().all()


# ============================================================
# ADMIN: VIEW ALL REFUNDS
# ============================================================

async def list_refunds(
    db: AsyncSession,
) -> list[Refund]:

    result = await db.execute(
        select(Refund)
        .order_by(Refund.requested_at.desc())
    )

    return result.scalars().all()


# ============================================================
# ADMIN: APPROVE OR REJECT REFUND
# ============================================================

async def review_refund(
    db: AsyncSession,
    admin: User,
    refund_id: int,
    decision: str,
    admin_note: str | None = None,
) -> Refund:

    if decision not in {"approve", "reject"}:
        raise HTTPException(422, "Invalid decision")

    result = await db.execute(
        select(Refund)
        .where(Refund.id == refund_id)
        .with_for_update()
    )
    refund = result.scalar_one_or_none()

    if not refund:
        raise HTTPException(404, "Refund request not found")

    if refund.status != RefundStatus.REQUESTED:
        raise HTTPException(
            409,
            "Only requested refunds can be reviewed",
        )

    result = await db.execute(
        select(Order)
        .where(Order.id == refund.order_id)
        .with_for_update()
    )
    order = result.scalar_one_or_none()

    result = await db.execute(
        select(Payment)
        .where(Payment.order_id == refund.order_id)
        .with_for_update()
    )
    payment = result.scalar_one_or_none()

    if not order or not payment:
        raise HTTPException(
            404,
            "Order or payment not found",
        )

    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(
            400,
            "Order must be delivered before refund review",
        )

    refund.reviewed_by = admin.id
    refund.reviewed_at = utc_now()
    refund.admin_note = admin_note

    if decision == "reject":
        refund.status = RefundStatus.REJECTED

    else:
        if payment.status != PaymentStatus.PAID:
            raise HTTPException(
                400,
                "Payment must be paid before refund approval",
            )

        if payment.method == PaymentMethod.CARD:
            if (
                not payment.transaction_id
                or not payment.transaction_id.startswith("pi_")
            ):
                raise HTTPException(
                    400,
                    "A valid Stripe PaymentIntent ID is missing",
                )

        elif payment.method != PaymentMethod.COD:
            raise HTTPException(
                400,
                "Unsupported payment method",
            )

        refund.status = RefundStatus.APPROVED

    try:
        await db.commit()
        await db.refresh(refund)

    except Exception:
        await db.rollback()
        logger.exception(
            "Failed to review refund %s",
            refund_id,
        )

        raise HTTPException(
            500,
            "Could not save refund review",
        )

    return refund


# ============================================================
# ADMIN: RECEIVE AND INSPECT RETURNED PRODUCTS
# ============================================================

async def receive_return_and_process_refund(
    db: AsyncSession,
    admin: User,
    refund_id: int,
    restockable: bool,
) -> Refund:

    result = await db.execute(
        select(Refund)
        .where(Refund.id == refund_id)
        .with_for_update()
    )
    refund = result.scalar_one_or_none()

    if not refund:
        raise HTTPException(
            404,
            "Refund request not found",
        )

    if refund.status == RefundStatus.COMPLETED:
        return refund

    if refund.status == RefundStatus.PROCESSING:
        return refund

    if refund.status == RefundStatus.FAILED:
        raise HTTPException(
            409,
            "Refund previously failed; reconcile Stripe before retrying",
        )

    if refund.status != RefundStatus.APPROVED:
        raise HTTPException(
            409,
            "Refund must be approved before receiving the return",
        )

    result = await db.execute(
        select(Order)
        .where(Order.id == refund.order_id)
        .with_for_update()
    )
    order = result.scalar_one_or_none()

    result = await db.execute(
        select(Payment)
        .where(Payment.order_id == refund.order_id)
        .with_for_update()
    )
    payment = result.scalar_one_or_none()

    if not order or not payment:
        raise HTTPException(
            404,
            "Order or payment not found",
        )

    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(
            400,
            "Only delivered orders can be returned",
        )

    if payment.status != PaymentStatus.PAID:
        raise HTTPException(
            400,
            "Payment must be paid before refund processing",
        )

    if payment.method == PaymentMethod.CARD:
        if (
            not payment.transaction_id
            or not payment.transaction_id.startswith("pi_")
        ):
            raise HTTPException(
                400,
                "A valid Stripe PaymentIntent ID is missing",
            )

    elif payment.method != PaymentMethod.COD:
        raise HTTPException(
            400,
            "Unsupported payment method",
        )

    if payment.method == PaymentMethod.CARD and refund.stripe_refund_id:
        raise HTTPException(
            409,
            "A Stripe refund already exists; reconcile its status",
        )

    now = utc_now()
    inventory_products: list[Product] = []

    # Record return inspection.
    if refund.return_received_at is not None:

        if refund.return_restockable != restockable:
            raise HTTPException(
                409,
                "This return was already inspected with a different result",
            )

    else:
        refund.return_received_at = now
        refund.return_restockable = restockable
        refund.reviewed_by = admin.id

    # Restock inventory only once.
    if restockable and refund.restocked_at is None:

        result = await db.execute(
            select(OrderItem)
            .where(OrderItem.order_id == order.id)
            .order_by(OrderItem.product_id)
        )
        items = result.scalars().all()

        if not items:
            raise HTTPException(
                400,
                "No order items found to restock",
            )

        product_ids = sorted({
            item.product_id for item in items
        })

        result = await db.execute(
            select(Product)
            .where(Product.id.in_(product_ids))
            .order_by(Product.id)
            .with_for_update()
        )
        products = result.scalars().all()

        product_map = {
            product.id: product for product in products
        }

        if len(product_map) != len(product_ids):
            raise HTTPException(
                400,
                "One or more products were not found",
            )

        for item in items:
            product = product_map.get(item.product_id)

            if product is None:
                raise HTTPException(
                    400,
                    f"Product {item.product_id} not found",
                )

            product.stock += item.quantity

        inventory_products = list(product_map.values())
        refund.restocked_at = now

    # Persist return and inventory changes together.
    try:
        await db.commit()
        await db.refresh(refund)
        await db.refresh(payment)
        await db.refresh(order)

    except Exception:
        await db.rollback()
        logger.exception(
            "Failed to save return for refund %s",
            refund_id,
        )

        raise HTTPException(
            500,
            "Could not save return and inventory changes",
        )

    # Publish inventory changes after successful commit.
    if inventory_products:
        try:
            await publish_inventory_updates(
                inventory_products,
                reason="refund_return_restocked",
                order_id=order.id,
            )
        except Exception:
            logger.exception(
                "Inventory was saved but notification failed for refund %s",
                refund_id,
            )

    # Process Stripe refund for card payments.
    if payment.method == PaymentMethod.CARD:

        try:
            stripe_refund = await asyncio.to_thread(
                stripe.Refund.create,
                payment_intent=payment.transaction_id,
                amount=int(
                    Decimal(str(refund.amount)) * 100
                ),
                reason="requested_by_customer",
                metadata={
                    "refund_id": str(refund.id),
                    "order_id": str(order.id),
                },
                idempotency_key=f"refund-order-{order.id}",
            )

        except stripe.error.StripeError as exc:
            logger.exception(
                "Stripe refund request failed for refund %s",
                refund.id,
            )

            raise HTTPException(
                502,
                "Return recorded, but Stripe refund could not be confirmed",
            ) from exc

        refund.stripe_refund_id = stripe_refund.id

        if stripe_refund.status == "succeeded":
            refund.status = RefundStatus.COMPLETED
            refund.completed_at = utc_now()
            payment.status = PaymentStatus.REFUNDED

        elif stripe_refund.status in {
            "pending",
            "requires_action",
        }:
            refund.status = RefundStatus.PROCESSING

        else:
            refund.status = RefundStatus.FAILED

        try:
            await db.commit()
            await db.refresh(refund)
            await db.refresh(payment)

        except Exception:
            await db.rollback()
            logger.exception(
                "Failed to save Stripe refund result for refund %s",
                refund.id,
            )

            raise HTTPException(
                500,
                "Stripe refund was requested, but the result could not be saved",
            )

        await notify_refund_update(
            refund,
            order,
            payment,
        )

        return refund

    # COD: money must be returned manually.
    await notify_refund_update(
        refund,
        order,
        payment,
    )

    return refund


# ============================================================
# ADMIN: COMPLETE COD REFUND
# ============================================================

async def complete_cod_refund(
    db: AsyncSession,
    admin: User,
    refund_id: int,
) -> Refund:

    result = await db.execute(
        select(Refund)
        .where(Refund.id == refund_id)
        .with_for_update()
    )
    refund = result.scalar_one_or_none()

    if not refund:
        raise HTTPException(
            404,
            "Refund request not found",
        )

    if refund.status != RefundStatus.APPROVED:
        raise HTTPException(
            409,
            "Only approved COD refunds can be completed",
        )

    if refund.return_received_at is None:
        raise HTTPException(
            400,
            "Record and inspect the returned product before completing the refund",
        )

    if (
        refund.return_restockable is True
        and refund.restocked_at is None
    ):
        raise HTTPException(
            409,
            "Resellable returned product must be restocked before refund completion",
        )

    result = await db.execute(
        select(Order)
        .where(Order.id == refund.order_id)
        .with_for_update()
    )
    order = result.scalar_one_or_none()

    result = await db.execute(
        select(Payment)
        .where(Payment.order_id == refund.order_id)
        .with_for_update()
    )
    payment = result.scalar_one_or_none()

    if not order or not payment:
        raise HTTPException(
            404,
            "Order or payment not found",
        )

    if payment.method != PaymentMethod.COD:
        raise HTTPException(
            400,
            "Manual completion is only for COD refunds",
        )

    if payment.status != PaymentStatus.PAID:
        raise HTTPException(
            400,
            "COD payment must be paid before it can be refunded",
        )

    # Admin confirms that money has actually been returned.
    refund.status = RefundStatus.COMPLETED
    refund.completed_at = utc_now()
    refund.reviewed_by = admin.id

    payment.status = PaymentStatus.REFUNDED

    try:
        await db.commit()
        await db.refresh(refund)
        await db.refresh(payment)
        await db.refresh(order)

    except Exception:
        await db.rollback()
        logger.exception(
            "Could not complete COD refund %s",
            refund_id,
        )

        raise HTTPException(
            500,
            "Could not save COD refund completion",
        )

    await notify_refund_update(
        refund,
        order,
        payment,
    )

    return refund
