
import logging
from datetime import datetime

import stripe

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.config import settings
from app.database import SessionLocal, get_db

from app.models.order import (
    Order,
    OrderStatus,
    OrderItem,
)

from app.models.payment import (
    Payment,
    PaymentMethod,
    PaymentStatus,
)

from app.models.user import User

from app.schemas.payment import (
    PaymentReceiptResponse,
    PaymentReceiptItem,
)

from app.websockets.manager import manager
from app.dependencies.auth import get_current_user


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


# ============================================================
# REAL-TIME PAYMENT NOTIFICATIONS
# ============================================================

async def broadcast_payment_status(
    order: Order,
    payment: Payment,
) -> None:
    """
    Notify the customer and admin after payment state is saved.
    """

    payment_data = {
        "order_id": order.id,
        "payment_id": payment.id,
        "payment_method": payment.method.value,
        "payment_status": payment.status.value,
        "order_status": order.status.value,
        "amount": str(payment.amount),
        "transaction_id": payment.transaction_id,
        "paid_at": (
            payment.paid_at.isoformat()
            if payment.paid_at
            else None
        ),
    }

    # Send to customer using /ws/orders.
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
            "Failed to notify customer about payment %s",
            payment.id,
        )

    # Send to admin using /ws/admin/orders.
    try:
        await manager.send_to_admin({
            "type": "payment_status_updated",
            "user_id": order.user_id,
            **payment_data,
        })
    except Exception:
        logger.exception(
            "Failed to notify admin about payment %s",
            payment.id,
        )


# ============================================================
# STRIPE WEBHOOK
# ============================================================

@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Stripe signature",
        )

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            settings.stripe_webhook_secret,
        )

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid payload",
        )

    except stripe.error.SignatureVerificationError:
        raise HTTPException(
            status_code=400,
            detail="Invalid Stripe signature",
        )

    event_type = event["type"]

    if event_type not in {
        "checkout.session.completed",
        "checkout.session.expired",
    }:
        return {
            "received": True,
            "message": "Event ignored",
        }

    session = event["data"]["object"].to_dict()
    metadata = session.get("metadata") or {}

    try:
        payment_id = int(metadata["payment_id"])
        order_id = int(metadata["order_id"])

    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Payment metadata missing or invalid",
        )

    # SessionLocal is an async_sessionmaker in your
    # updated database configuration.
    async with SessionLocal() as db:

        try:
            # ------------------------------------------------
            # LOCK ORDER
            # ------------------------------------------------

            order_result = await db.execute(
                select(Order)
                .where(Order.id == order_id)
                .with_for_update()
            )

            order = order_result.scalar_one_or_none()

            # ------------------------------------------------
            # LOCK PAYMENT
            # ------------------------------------------------

            payment_result = await db.execute(
                select(Payment)
                .where(Payment.id == payment_id)
                .with_for_update()
            )

            payment = payment_result.scalar_one_or_none()

            if not order or not payment:
                raise HTTPException(
                    status_code=404,
                    detail="Order or payment not found",
                )

            if payment.order_id != order.id:
                raise HTTPException(
                    status_code=400,
                    detail="Payment/order mismatch",
                )

            if payment.session_id != session.get("id"):
                raise HTTPException(
                    status_code=400,
                    detail="Stripe session mismatch",
                )

            if payment.method != PaymentMethod.CARD:
                raise HTTPException(
                    status_code=400,
                    detail="Unexpected payment method",
                )

            # ------------------------------------------------
            # CHECKOUT SESSION EXPIRED
            # ------------------------------------------------

            if event_type == "checkout.session.expired":

                if (
                    order.status == OrderStatus.PENDING
                    and payment.status == PaymentStatus.PENDING
                    and order.inventory_released_at is None
                ):
                    from app.services.oder_servies import (
                        release_order_inventory,
                    )

                    # This service must also be async.
                    await release_order_inventory(db, order)

                    order.status = OrderStatus.CANCELLED
                    payment.status = PaymentStatus.FAILED

                # Save before sending WebSocket messages.
                await db.commit()

                await db.refresh(order)
                await db.refresh(payment)

                # Notify customer about order status.
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
                    logger.exception(
                        "Failed to notify customer of checkout expiry "
                        "for order %s",
                        order.id,
                    )

                await broadcast_payment_status(order, payment)

                return {
                    "received": True,
                    "message": "Checkout expiry processed",
                }

            # ------------------------------------------------
            # CHECK PAYMENT RESULT
            # ------------------------------------------------

            if session.get("payment_status") != "paid":
                return {
                    "received": True,
                    "message": "Payment not completed",
                }

            expected_amount = int(payment.amount * 100)

            if session.get("amount_total") != expected_amount:
                raise HTTPException(
                    status_code=400,
                    detail="Payment amount mismatch",
                )

            # ------------------------------------------------
            # IDEMPOTENCY
            # ------------------------------------------------

            # Stripe can send the same webhook multiple times.
            if payment.status == PaymentStatus.PAID:

                await db.commit()

                await db.refresh(order)
                await db.refresh(payment)

                await broadcast_payment_status(order, payment)

                return {
                    "received": True,
                    "message": "Payment already processed",
                }

            # Never confirm a cancelled order after payment.
            if (
                order.status == OrderStatus.CANCELLED
                or order.inventory_released_at is not None
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Payment arrived after cancellation or inventory "
                        "release; payment reconciliation is required"
                    ),
                )

            # ------------------------------------------------
            # UPDATE PAYMENT AND ORDER
            # ------------------------------------------------

            payment.status = PaymentStatus.PAID
            payment.transaction_id = session.get("payment_intent")
            payment.paid_at = datetime.utcnow()

            order.status = OrderStatus.CONFIRMED

            # Save both changes first.
            await db.commit()

            await db.refresh(order)
            await db.refresh(payment)

            # ------------------------------------------------
            # REAL-TIME PAYMENT UPDATE
            # ------------------------------------------------

            await broadcast_payment_status(order, payment)

            # ------------------------------------------------
            # KEEP EXISTING ADMIN EVENT
            # ------------------------------------------------

            try:
                await manager.send_to_admin({
                    "type": "payment_completed",
                    "payment_id": payment.id,
                    "order_id": order.id,
                    "user_id": order.user_id,
                    "amount": str(payment.amount),
                    "status": payment.status.value,
                    "transaction_id": payment.transaction_id,
                })

            except Exception:
                logger.exception(
                    "Failed to send legacy payment_completed event "
                    "for order %s",
                    order.id,
                )

            return {
                "received": True,
                "message": "Payment processed successfully",
            }

        except HTTPException:
            await db.rollback()
            raise

        except SQLAlchemyError:
            await db.rollback()

            logger.exception(
                "Database error while processing Stripe webhook"
            )

            raise HTTPException(
                status_code=500,
                detail="Database error while processing webhook",
            )

        except Exception:
            await db.rollback()

            logger.exception(
                "Stripe webhook processing failed"
            )

            raise HTTPException(
                status_code=500,
                detail="Webhook processing failed",
            )


# ============================================================
# CUSTOMER PAYMENT RECEIPT
# ============================================================

@router.get(
    "/{payment_id}/receipt",
    response_model=PaymentReceiptResponse,
)
async def get_payment_receipt(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Load payment with order, items, products and customer.
    query = (
        select(Payment)
        .options(
            selectinload(Payment.order)
            .selectinload(Order.items)
            .joinedload(OrderItem.product),

            joinedload(Payment.order)
            .joinedload(Order.user),

            joinedload(Payment.order)
            .joinedload(Order.shipping_address),
        )
        .where(Payment.id == payment_id)
    )

    result = await db.execute(query)

    payment = result.unique().scalar_one_or_none()

    if payment is None:
        raise HTTPException(
            status_code=404,
            detail="Payment not found",
        )

    order = payment.order

    if not order:
        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    # Customers can only view their own receipts.
    if order.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to view this payment receipt",
        )

    receipt_items = []

    for order_item in order.items:
        receipt_items.append(
            PaymentReceiptItem(
                product_id=order_item.product_id,
                product_name=order_item.product.name,
                quantity=order_item.quantity,
                unit_price=order_item.unit_price,
                subtotal=(
                    order_item.unit_price
                    * order_item.quantity
                ),
            )
        )

    return PaymentReceiptResponse(
        payment_id=payment.id,
        payment_status=payment.status,
        payment_method=payment.method,
        amount=payment.amount,
        transaction_id=payment.transaction_id,
        session_id=payment.session_id,
        order_id=order.id,
        order_status=order.status,
        user_id=order.user_id,
        customer_name=(
            f"{order.user.first_name} "
            f"{order.user.last_name}"
        ),
        customer_email=order.user.email,
        shipping_address=order.shipping_address,
        items=receipt_items,
        paid_at=payment.paid_at,
        created_at=payment.created_at,
        receipt_url=None,
    )
