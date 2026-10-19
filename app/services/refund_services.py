import logging
from datetime import datetime
from decimal import Decimal

import stripe
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.models.user import User

logger = logging.getLogger(__name__)
stripe.api_key = settings.stripe_secret_key


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

    if (
        payment.method == PaymentMethod.CARD
        and payment.status != PaymentStatus.PAID
    ):
        raise HTTPException(
            400,
            "Only successfully paid card orders can be refunded",
        )

    if (
        payment.method == PaymentMethod.COD
        and payment.status not in (
            PaymentStatus.PENDING,
            PaymentStatus.PAID,
        )
    ):
        raise HTTPException(400, "COD payment is not eligible")

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
            "Could not create refund request; check whether one already exists",
        )

    return refund


def list_my_refunds(db: Session, user: User) -> list[Refund]:
    return (
        db.query(Refund)
        .filter(Refund.requested_by == user.id)
        .order_by(Refund.requested_at.desc())
        .all()
    )


def list_refunds(db: Session) -> list[Refund]:
    return (
        db.query(Refund)
        .order_by(Refund.requested_at.desc())
        .all()
    )


def review_refund(
    db: Session,
    admin: User,
    refund_id: int,
    decision: str,
    admin_note: str | None = None,
) -> Refund:
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
            "Order must be delivered to process a refund",
        )

    refund.reviewed_by = admin.id
    refund.reviewed_at = datetime.utcnow()
    refund.admin_note = admin_note

    if decision == "reject":
        refund.status = RefundStatus.REJECTED
        db.commit()
        db.refresh(refund)
        return refund

    if decision != "approve":
        raise HTTPException(422, "Invalid decision")

    if payment.method == PaymentMethod.CARD:
        if payment.status != PaymentStatus.PAID:
            raise HTTPException(400, "Card payment is not paid")

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
            db.rollback()
            logger.exception("Stripe refund failed")
            raise HTTPException(
                502,
                "Stripe could not process the refund",
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
        return refund

    # COD: approval does not itself return the money.
    refund.status = RefundStatus.APPROVED
    db.commit()
    db.refresh(refund)
    return refund


def complete_cod_refund(
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

    payment = (
        db.query(Payment)
        .filter(Payment.order_id == refund.order_id)
        .with_for_update()
        .first()
    )

    if not payment or payment.method != PaymentMethod.COD:
        raise HTTPException(
            400,
            "Manual completion is only for COD refunds",
        )

    # Call this endpoint only after the money has actually been returned.
    refund.status = RefundStatus.COMPLETED
    refund.completed_at = datetime.utcnow()
    refund.reviewed_by = admin.id
    payment.status = PaymentStatus.REFUNDED

    db.commit()
    db.refresh(refund)
    return refund