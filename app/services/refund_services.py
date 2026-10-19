import logging
from datetime import datetime
from decimal import Decimal

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.models.user import User

from app.services.inventory_service import publish_inventory_updates
from app.websockets.manager import manager


logger = logging.getLogger(__name__)
stripe.api_key = settings.stripe_secret_key


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
            if refund.completed_at
            else None
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
# CUSTOMER: REQUEST REFUND
# ============================================================

def request_refund(
    db: Session,
    user: User,
    order_id: int,
    reason: str,
) -> Refund:

    order = (
        db.query(Order)
        .filter(
            Order.id == order_id,
            Order.user_id == user.id,
        )
        .with_for_update()
        .first()
    )

    if not order:
        raise HTTPException(404, "Order not found")

    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(
            400,
            "Refunds can only be requested after delivery",
        )

    payment = (
        db.query(Payment)
        .filter(Payment.order_id == order.id)
        .with_for_update()
        .first()
    )

    if not payment:
        raise HTTPException(400, "Payment record not found")

    # Only successfully paid orders may be refunded.
    if payment.status != PaymentStatus.PAID:
        raise HTTPException(
            400,
            "The payment must be marked paid before requesting a refund",
        )

    existing = (
        db.query(Refund)
        .filter(Refund.order_id == order.id)
        .first()
    )

    if existing:
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
        db.commit()
        db.refresh(refund)
    except Exception:
        db.rollback()
        logger.exception("Refund request creation failed")
        raise HTTPException(
            409,
            "Could not create refund request",
        )

    return refund


# ============================================================
# CUSTOMER: VIEW OWN REFUNDS
# ============================================================

def list_my_refunds(
    db: Session,
    user: User,
) -> list[Refund]:

    return (
        db.query(Refund)
        .filter(Refund.requested_by == user.id)
        .order_by(Refund.requested_at.desc())
        .all()
    )


# ============================================================
# ADMIN: VIEW ALL REFUNDS
# ============================================================

def list_refunds(db: Session) -> list[Refund]:
    return (
        db.query(Refund)
        .order_by(Refund.requested_at.desc())
        .all()
    )


# ============================================================
# ADMIN: APPROVE OR REJECT REFUND
# Approval does not mean the money has been returned.
# ============================================================

def review_refund(
    db: Session,
    admin: User,
    refund_id: int,
    decision: str,
    admin_note: str | None = None,
) -> Refund:

    if decision not in {"approve", "reject"}:
        raise HTTPException(422, "Invalid decision")

    refund = (
        db.query(Refund)
        .filter(Refund.id == refund_id)
        .with_for_update()
        .first()
    )

    if not refund:
        raise HTTPException(404, "Refund request not found")

    if refund.status != RefundStatus.REQUESTED:
        raise HTTPException(
            409,
            "Only requested refunds can be reviewed",
        )

    order = (
        db.query(Order)
        .filter(Order.id == refund.order_id)
        .with_for_update()
        .first()
    )

    payment = (
        db.query(Payment)
        .filter(Payment.order_id == refund.order_id)
        .with_for_update()
        .first()
    )

    if not order or not payment:
        raise HTTPException(404, "Order or payment not found")

    if order.status != OrderStatus.DELIVERED:
        raise HTTPException(
            400,
            "Order must be delivered before refund review",
        )

    refund.reviewed_by = admin.id
    refund.reviewed_at = datetime.utcnow()
    refund.admin_note = admin_note

    if decision == "reject":
        refund.status = RefundStatus.REJECTED

        db.commit()
        db.refresh(refund)
        return refund

    if payment.status != PaymentStatus.PAID:
        raise HTTPException(
            400,
            "The payment must be marked paid before a refund can be approved",
        )

    refund.status = RefundStatus.APPROVED

    # IMPORTANT:
    # Do not refund money here.
    # First receive and inspect the returned product.

    db.commit()
    db.refresh(refund)

    return refund


# ============================================================
# ADMIN: RECEIVE AND INSPECT RETURNED PRODUCTS
#
# restockable=True:
#     Product is received and safe to resell.
#
# restockable=False:
#     Product is received but must not return to sellable stock.
#
# This implementation supports a FULL-ORDER return only.
# ============================================================

async def receive_return_and_process_refund(
    db: Session,
    admin: User,
    refund_id: int,
    restockable: bool,
) -> Refund:

    refund = (
        db.query(Refund)
        .filter(Refund.id == refund_id)
        .with_for_update()
        .first()
    )

    if not refund:
        raise HTTPException(404, "Refund request not found")

    # Avoid processing the same completed refund a second time.
    if refund.status == RefundStatus.COMPLETED:
        return refund

    # A pending Stripe refund must be reconciled rather than
    # creating another refund.
    if refund.status == RefundStatus.PROCESSING:
        return refund

    if refund.status == RefundStatus.FAILED:
        raise HTTPException(
            409,
            "Refund previously failed; reconcile its payment before retrying",
        )

    if refund.status != RefundStatus.APPROVED:
        raise HTTPException(
            409,
            "Refund must be approved before receiving the return",
        )

    order = (
        db.query(Order)
        .filter(Order.id == refund.order_id)
        .with_for_update()
        .first()
    )

    payment = (
        db.query(Payment)
        .filter(Payment.order_id == refund.order_id)
        .with_for_update()
        .first()
    )

    if not order or not payment:
        raise HTTPException(404, "Order or payment not found")

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

    now = datetime.utcnow()
    inventory_products: list[Product] = []

    # --------------------------------------------------------
    # RECORD PHYSICAL RETURN AND INSPECTION
    # --------------------------------------------------------

    if refund.return_received_at is not None:
        # Do not silently change the inspection result on retries.
        if refund.return_restockable != restockable:
            raise HTTPException(
                409,
                "This return was already inspected with a different result",
            )
    else:
        refund.return_received_at = now
        refund.return_restockable = restockable

    # --------------------------------------------------------
    # RESTOCK ONLY ONCE, AND ONLY IF SELLABLE
    # --------------------------------------------------------

    if restockable and refund.restocked_at is None:
        order_items = (
            db.query(OrderItem)
            .filter(OrderItem.order_id == order.id)
            .order_by(OrderItem.product_id)
            .all()
        )

        if not order_items:
            raise HTTPException(
                400,
                "No order items found to restock",
            )

        product_ids = sorted({
            item.product_id for item in order_items
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

        for item in order_items:
            product = product_map.get(item.product_id)

            if product is None:
                raise HTTPException(
                    400,
                    f"Product {item.product_id} not found; stock was not restocked",
                )

            product.stock += item.quantity

        inventory_products = list(product_map.values())
        refund.restocked_at = now

    # Commit the physical return and stock update together.
    try:
        db.commit()
        db.refresh(refund)
        db.refresh(payment)
        db.refresh(order)
    except Exception:
        db.rollback()
        logger.exception(
            "Could not save returned inventory for refund %s",
            refund.id,
        )
        raise HTTPException(
            500,
            "Could not save return and inventory changes",
        )

    # Notify admin/storefront about stock changes after commit.
    if inventory_products:
        try:
            await publish_inventory_updates(
                inventory_products,
                reason="refund_return_restocked",
                order_id=order.id,
            )
        except Exception:
            logger.exception(
                "Stock saved but inventory notification failed for refund %s",
                refund.id,
            )

    # --------------------------------------------------------
    # CARD: INITIATE STRIPE REFUND AFTER RETURN INSPECTION
    # --------------------------------------------------------

    if payment.method == PaymentMethod.CARD:

        if not payment.transaction_id:
            raise HTTPException(
                400,
                "Stripe PaymentIntent ID is missing",
            )

        try:
            stripe_refund = stripe.Refund.create(
                payment_intent=payment.transaction_id,
                amount=int(Decimal(str(refund.amount)) * 100),
                reason="requested_by_customer",
                metadata={
                    "refund_id": str(refund.id),
                    "order_id": str(order.id),
                },
                idempotency_key=f"refund-order-{order.id}",
            )
        except stripe.error.StripeError as exc:
            # Receipt and any eligible restock have already committed.
            # The refund remains approved so it can be reconciled.
            db.rollback()
            logger.exception(
                "Stripe refund failed for refund %s",
                refund.id,
            )
            raise HTTPException(
                502,
                "Returned item was recorded, but Stripe could not process the refund",
            ) from exc

        refund.stripe_refund_id = stripe_refund.id

        if stripe_refund.status == "succeeded":
            refund.status = RefundStatus.COMPLETED
            refund.completed_at = datetime.utcnow()
            payment.status = PaymentStatus.REFUNDED

        elif stripe_refund.status in ("pending", "requires_action"):
            refund.status = RefundStatus.PROCESSING

        else:
            refund.status = RefundStatus.FAILED

        db.commit()
        db.refresh(refund)
        db.refresh(payment)

        await notify_refund_update(refund, order, payment)

        return refund

    # --------------------------------------------------------
    # COD: RECORD RETURN, THEN ADMIN RETURNS MONEY MANUALLY
    # --------------------------------------------------------

    # Do not mark COD payment as refunded until the admin confirms
    # that the money has actually been returned to the customer.
    await notify_refund_update(refund, order, payment)

    return refund


# ============================================================
# ADMIN: COMPLETE COD REFUND
#
# Call only after the customer has actually received their money.
# ============================================================

async def complete_cod_refund(
    db: Session,
    admin: User,
    refund_id: int,
) -> Refund:

    refund = (
        db.query(Refund)
        .filter(Refund.id == refund_id)
        .with_for_update()
        .first()
    )

    if not refund:
        raise HTTPException(404, "Refund request not found")

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

    order = (
        db.query(Order)
        .filter(Order.id == refund.order_id)
        .with_for_update()
        .first()
    )

    payment = (
        db.query(Payment)
        .filter(Payment.order_id == refund.order_id)
        .with_for_update()
        .first()
    )

    if not order or not payment:
        raise HTTPException(404, "Order or payment not found")

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

    # The admin confirms the money has actually been returned.
    refund.status = RefundStatus.COMPLETED
    refund.completed_at = datetime.utcnow()
    refund.reviewed_by = admin.id

    payment.status = PaymentStatus.REFUNDED

    db.commit()
    db.refresh(refund)
    db.refresh(payment)

    await notify_refund_update(refund, order, payment)

    return refund