import stripe

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
)
from datetime import datetime, timedelta
from sqlalchemy.orm import Session, joinedload

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

from app.models.product import Product
from app.models.user import User

from app.schemas.payment import (
    PaymentReceiptResponse,
    PaymentReceiptItem,
)

from app.websockets.manager import manager

# IMPORTANT:
# Use the actual location of get_current_user
# from your project.
from app.dependencies.auth import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


# ============================================================
# STRIPE WEBHOOK
# ============================================================

@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("stripe-signature")

    if not signature:
        raise HTTPException(400, "Missing Stripe signature")

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            settings.stripe_webhook_secret,
        )
    except ValueError:
        raise HTTPException(400, "Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(400, "Invalid Stripe signature")

    event_type = event["type"]

    if event_type not in {
        "checkout.session.completed",
        "checkout.session.expired",
    }:
        return {"received": True, "message": "Event ignored"}

    session = event["data"]["object"].to_dict()
    metadata = session.get("metadata") or {}

    try:
        payment_id = int(metadata["payment_id"])
        order_id = int(metadata["order_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "Payment metadata missing or invalid")

    db = SessionLocal()

    try:
        # Always lock the order and payment in the same order
        # in all payment lifecycle handlers.
        order = (
            db.query(Order)
            .filter(Order.id == order_id)
            .with_for_update()
            .first()
        )

        payment = (
            db.query(Payment)
            .filter(Payment.id == payment_id)
            .with_for_update()
            .first()
        )

        if not order or not payment:
            raise HTTPException(404, "Order or payment not found")

        if payment.order_id != order.id:
            raise HTTPException(400, "Payment/order mismatch")

        if payment.session_id != session.get("id"):
            raise HTTPException(400, "Stripe session mismatch")

        if payment.method != PaymentMethod.CARD:
            raise HTTPException(400, "Unexpected payment method")

        if event_type == "checkout.session.expired":
            if (
                order.status == OrderStatus.PENDING
                and payment.status == PaymentStatus.PENDING
                and order.inventory_released_at is None
            ):
                from app.services.oder_servies import (
                    release_order_inventory,
                )

                release_order_inventory(db, order)
                order.status = OrderStatus.CANCELLED
                payment.status = PaymentStatus.FAILED

            db.commit()
            return {
                "received": True,
                "message": "Checkout expiry processed",
            }

        # A completed event is only treated as paid when
        # Stripe explicitly reports payment_status=paid.
        if session.get("payment_status") != "paid":
            db.commit()
            return {
                "received": True,
                "message": "Payment not completed",
            }

        expected_amount = int(payment.amount * 100)

        if session.get("amount_total") != expected_amount:
            raise HTTPException(400, "Payment amount mismatch")

        if payment.status == PaymentStatus.PAID:
            db.commit()
            return {
                "received": True,
                "message": "Payment already processed",
            }

        # Never resurrect a canceled order or an order whose
        # inventory was released. Refund handling is required.
        if (
            order.status == OrderStatus.CANCELLED
            or order.inventory_released_at is not None
        ):
            db.rollback()
            raise HTTPException(
                409,
                "Payment arrived after cancellation or inventory release; "
                "payment reconciliation is required",
            )

        payment.status = PaymentStatus.PAID
        payment.transaction_id = session.get("payment_intent")
        payment.paid_at = datetime.utcnow()
        order.status = OrderStatus.CONFIRMED

        # Stock was already deducted at checkout.
        db.commit()

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
            pass

        return {
            "received": True,
            "message": "Payment processed successfully",
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Stripe webhook processing failed")
        raise HTTPException(500, "Webhook processing failed")
    finally:
        db.close()
# ============================================================
# CUSTOMER PAYMENT RECEIPT
# ============================================================

@router.get(
    "/{payment_id}/receipt",
    response_model=PaymentReceiptResponse,
)
def get_payment_receipt(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    # ========================================================
    # 1. Find payment
    #
    # Load:
    # Payment
    #   └── Order
    #       ├── User
    #       └── OrderItems
    #           └── Product
    # ========================================================

    payment = (
        db.query(Payment)
        .options(
            joinedload(Payment.order)
            .joinedload(Order.items)
            .joinedload(OrderItem.product),

            joinedload(Payment.order)
            .joinedload(Order.user),
        )
        .filter(
            Payment.id == payment_id
        )
        .first()
    )

    # ========================================================
    # 2. Payment not found
    # ========================================================

    if not payment:

        raise HTTPException(
            status_code=404,
            detail="Payment not found",
        )

    # ========================================================
    # 3. Get order
    # ========================================================

    order = payment.order

    if not order:

        raise HTTPException(
            status_code=404,
            detail="Order not found",
        )

    # ========================================================
    # 4. Security check
    #
    # Customer can only see their own receipt.
    # ========================================================

    if order.user_id != current_user.id:

        raise HTTPException(
            status_code=403,
            detail=(
                "You are not allowed to "
                "view this payment receipt"
            ),
        )

    # ========================================================
    # 5. Build receipt items
    # ========================================================

    receipt_items = []

    for order_item in order.items:

        receipt_items.append(
            PaymentReceiptItem(

                product_id=
                    order_item.product_id,

                product_name=
                    order_item.product.name,

                quantity=
                    order_item.quantity,

                unit_price=
                    order_item.unit_price,

                subtotal=(
                    order_item.unit_price
                    * order_item.quantity
                ),
            )
        )

    # ========================================================
    # 6. Return receipt
    # ========================================================

    return PaymentReceiptResponse(

        payment_id=
            payment.id,

        payment_status=
            payment.status,

        payment_method=
            payment.method,

        amount=
            payment.amount,

        transaction_id=
            payment.transaction_id,

        session_id=
            payment.session_id,

        order_id=
            order.id,

        order_status=
            order.status,

        user_id=
            order.user_id,

        customer_name=(
            f"{order.user.first_name} "
            f"{order.user.last_name}"
        ),

        customer_email=
            order.user.email,

        shipping_address=
            order.shipping_address,

        items=
            receipt_items,

        paid_at=
            payment.paid_at,

        created_at=
            payment.created_at,

        receipt_url=None,
    )