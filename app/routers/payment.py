import stripe

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)
from sqlalchemy.orm import Session , joinedload 

from app.config import settings
from app.database import SessionLocal
from app.models.order import Order, OrderStatus
from app.models.payment import (
    Payment,
    PaymentStatus,
)
from app.models.product import Product
from app.websockets.manager import manager


router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
):
    # ========================================================
    # 1. Get raw Stripe request
    # ========================================================

    payload = await request.body()

    signature = request.headers.get(
        "stripe-signature"
    )

    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Stripe signature",
        )

    # ========================================================
    # 2. Verify Stripe signature
    # ========================================================

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

    # ========================================================
    # 3. Ignore events we don't handle
    # ========================================================

    if event["type"] != "checkout.session.completed":

        return {
            "received": True
        }

    # ========================================================
    # 4. Get Stripe Checkout Session
    # ========================================================

    session = event["data"]["object"]

    # ========================================================
    # 5. Make sure Stripe says payment is actually paid
    # ========================================================

    if session.get("payment_status") != "paid":

        return {
            "received": True,
            "message": "Payment is not paid yet",
        }

    # ========================================================
    # 6. Get metadata
    # ========================================================

    metadata = session.get("metadata") or {}

    payment_id = metadata.get("payment_id")
    order_id = metadata.get("order_id")

    if not payment_id or not order_id:

        raise HTTPException(
            status_code=400,
            detail="Payment metadata missing",
        )

    db: Session = SessionLocal()

    try:

        # ====================================================
        # 7. Find Payment and lock it
        # ====================================================

        payment = (
            db.query(Payment)
            .filter(
                Payment.id == int(payment_id)
            )
            .with_for_update()
            .first()
        )

        if not payment:

            raise HTTPException(
                status_code=404,
                detail="Payment not found",
            )

        # ====================================================
        # 8. Idempotency
        # ====================================================

        if payment.status == PaymentStatus.PAID:

            return {
                "received": True,
                "message": "Payment already processed",
            }

        # ====================================================
        # 9. Verify Stripe session belongs to Payment
        # ====================================================

        if payment.session_id != session["id"]:

            raise HTTPException(
                status_code=400,
                detail="Stripe session does not match payment",
            )

        # ====================================================
        # 10. Verify Payment belongs to this Order
        # ====================================================

        if payment.order_id != int(order_id):

            raise HTTPException(
                status_code=400,
                detail="Payment does not belong to order",
            )

        # ====================================================
        # 11. Get existing Order
        # ====================================================

        order = (
        db.query(Order)
        .options(
            joinedload(Order.items)
        )
        .filter(
            Order.id == int(order_id)
        )
        .with_for_update()
        .first()
)

        if not order:

            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        # ====================================================
        # 12. Verify amount
        # ====================================================

        stripe_amount = session.get(
            "amount_total"
        )

        if stripe_amount is None:

            raise HTTPException(
                status_code=400,
                detail="Stripe amount missing",
            )

        expected_amount = int(
            payment.amount * 100
        )

        if stripe_amount != expected_amount:

            raise HTTPException(
                status_code=400,
                detail="Payment amount mismatch",
            )

        # ====================================================
        # 13. Get OrderItems
        # ====================================================

        for order_item in order.items:

            product = (
                db.query(Product)
                .filter(
                    Product.id == order_item.product_id
                )
                .with_for_update()
                .first()
            )

            if not product:

                raise HTTPException(
                    status_code=400,
                    detail="Product no longer exists",
                )

            if not product.is_active:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Product '{product.name}' "
                        "is no longer available"
                    ),
                )

            if product.stock < order_item.quantity:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Not enough stock for "
                        f"'{product.name}'"
                    ),
                )

            # Reduce stock after successful payment
            product.stock -= order_item.quantity

        # ====================================================
        # 14. Update Payment
        # ====================================================

        payment.status = PaymentStatus.PAID

        payment.transaction_id = (
            session.get("payment_intent")
        )

        # ====================================================
        # 15. Update Order
        # ====================================================

        order.status = OrderStatus.CONFIRMED

        # ====================================================
        # 16. Clear cart
        # ====================================================

        # IMPORTANT:
        # Do not blindly delete the customer's current
        # cart here. The customer may have changed it
        # after starting checkout.
        #
        # We will handle cart lifecycle separately.
        #
        # For now, don't touch the cart here.

        # ====================================================
        # 17. Commit
        # ====================================================

        db.commit()

        db.refresh(order)

        # ====================================================
        # 18. Notify admin
        # ====================================================

        try:

            await manager.send_to_admin({
                "type": "new_order",
                "order_id": order.id,
                "user_id": order.user_id,
                "total_amount": str(
                    order.total_amount
                ),
                "status": order.status.value,
            })

        except Exception:
            # Payment is already committed.
            # WebSocket failure must not rollback it.
            pass

        return {
            "received": True,
            "message": "Payment processed successfully",
        }

    except HTTPException:

        db.rollback()
        raise

    except stripe.error.StripeError as e:
        db.rollback()

        print("STRIPE ERROR:", str(e))

        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    finally:

        db.close()