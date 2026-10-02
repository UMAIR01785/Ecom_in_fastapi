import stripe

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import SessionLocal
from app.dependencies.auth import get_current_user
from app.models.order import Order, OrderStatus
from app.models.order import OrderItem
from app.models.payment import Payment, PaymentStatus
from app.models.product import Product
from app.models.user import User
from app.schemas.payment import (
    PaymentReceiptItem,
    PaymentReceiptResponse,
)
from app.services.payment_service import get_stripe_receipt_url
from app.websockets import manager


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

    signature = request.headers.get(
        "stripe-signature"
    )

    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload",
        )

    except stripe.error.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Stripe signature",
        )

    # --------------------------------------------------------
    # Only process completed checkout sessions
    # --------------------------------------------------------

    if event["type"] != "checkout.session.completed":
        return {
            "received": True,
            "message": "Event ignored",
        }

    session = event["data"]["object"]

    # --------------------------------------------------------
    # Make sure Stripe says payment is actually paid
    # --------------------------------------------------------

    if session.get("payment_status") != "paid":
        return {
            "received": True,
            "message": "Payment is not marked as paid",
        }

    metadata = session.get("metadata") or {}

    payment_id = metadata.get("payment_id")
    order_id = metadata.get("order_id")

    if not payment_id or not order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing payment or order metadata",
        )

    db: Session = SessionLocal()

    try:

        # ----------------------------------------------------
        # Lock payment row
        # ----------------------------------------------------

        payment = (
            db.query(Payment)
            .filter(Payment.id == int(payment_id))
            .with_for_update()
            .first()
        )

        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found",
            )

        # ----------------------------------------------------
        # Idempotency
        # ----------------------------------------------------

        if payment.status == PaymentStatus.PAID:
            return {
                "received": True,
                "message": "Payment already processed",
            }

        # ----------------------------------------------------
        # Verify Stripe session
        # ----------------------------------------------------

        if payment.session_id != session.get("id"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stripe session does not match payment",
            )

        # ----------------------------------------------------
        # Verify order
        # ----------------------------------------------------

        order = (
            db.query(Order)
            .options(
                joinedload(Order.items)
                .joinedload(OrderItem.product)
            )
            .filter(Order.id == int(order_id))
            .with_for_update()
            .first()
        )

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )

        if payment.order_id != order.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment does not belong to this order",
            )

        # ----------------------------------------------------
        # Verify Stripe amount
        # ----------------------------------------------------

        stripe_amount = session.get("amount_total")

        expected_amount = int(
            payment.amount * 100
        )

        if stripe_amount != expected_amount:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment amount mismatch",
            )

        # ----------------------------------------------------
        # Reserve/decrease stock
        # ----------------------------------------------------

        for item in order.items:

            product = (
                db.query(Product)
                .filter(Product.id == item.product_id)
                .with_for_update()
                .first()
            )

            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Product {item.product_id} not found",
                )

            if not product.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Product {product.name} is inactive",
                )

            if product.stock < item.quantity:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Insufficient stock for "
                        f"{product.name}"
                    ),
                )

            product.stock -= item.quantity

        # ----------------------------------------------------
        # Update payment
        # ----------------------------------------------------

        payment.status = PaymentStatus.PAID

        payment.transaction_id = session.get(
            "payment_intent"
        )

        # ----------------------------------------------------
        # Update order
        # ----------------------------------------------------

        order.status = OrderStatus.CONFIRMED

        db.commit()

        # ----------------------------------------------------
        # Notify admin through websocket
        # ----------------------------------------------------

        await manager.send_to_admin(
            {
                "type": "payment_completed",
                "payment_id": payment.id,
                "order_id": order.id,
                "user_id": order.user_id,
                "amount": str(payment.amount),
                "status": payment.status.value,
                "transaction_id": payment.transaction_id,
            }
        )

        return {
            "received": True,
            "message": "Payment processed successfully",
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(
        lambda: SessionLocal()
    ),
):

    payment = (
        db.query(Payment)
        .options(
            joinedload(Payment.order)
            .joinedload(Order.user),

            joinedload(Payment.order)
            .joinedload(Order.items)
            .joinedload(OrderItem.product),
        )
        .filter(Payment.id == payment_id)
        .first()
    )

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )

    # --------------------------------------------------------
    # Security:
    # Customer can only see their own payment
    # --------------------------------------------------------

    if payment.order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot access this payment",
        )

    order = payment.order
    user = order.user

    receipt_items = []

    for item in order.items:

        subtotal = (
            item.unit_price * item.quantity
        )

        receipt_items.append(
            PaymentReceiptItem(
                product_id=item.product_id,
                product_name=item.product.name,
                quantity=item.quantity,
                unit_price=item.unit_price,
                subtotal=subtotal,
            )
        )

    receipt_url = None

    if payment.status == PaymentStatus.PAID:
        receipt_url = get_stripe_receipt_url(
            payment.transaction_id
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

        user_id=user.id,

        customer_name=(
            f"{user.first_name} "
            f"{user.last_name}"
        ),

        customer_email=user.email,

        shipping_address=order.shipping_address,

        items=receipt_items,

        paid_at=(
            payment.updated_at
            if payment.status == PaymentStatus.PAID
            else None
        ),

        created_at=payment.created_at,

        receipt_url=receipt_url,
    )