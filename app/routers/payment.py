# app/routers/payment.py

import stripe

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session ,joinedload

from app.config import settings
from app.database import SessionLocal

from app.models.payment import Payment, PaymentStatus
from app.models.order import Order, OrderItem, OrderStatus
from app.models.cart import Cart, CartItem
from app.models.product import Product

from app.websockets.manager import manager


router = APIRouter(
    prefix="/payments",
    tags=["Payments"],
)


@router.post("/webhook")
async def stripe_webhook(request: Request):

    # ========================================================
    # 1. Get raw Stripe body
    # ========================================================

    payload = await request.body()

    # ========================================================
    # 2. Get Stripe signature
    # ========================================================

    signature = request.headers.get("stripe-signature")

    if not signature:
        raise HTTPException(
            status_code=400,
            detail="Missing Stripe signature",
        )

    # ========================================================
    # 3. Verify Stripe event
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
    # 4. Only handle successful checkout
    # ========================================================

    if event["type"] != "checkout.session.completed":

        return {
            "received": True
        }

    # ========================================================
    # 5. Get Stripe session
    # ========================================================

    session = event["data"]["object"]

    # ========================================================
    # 6. Get metadata
    # ========================================================

    metadata = (
        session["metadata"]
        if session.get("metadata")
        else {}
    )

    payment_id = metadata.get("payment_id")
    user_id = metadata.get("user_id")
    shipping_address = metadata.get("shipping_address")

    if not payment_id:
        raise HTTPException(
            status_code=400,
            detail="Payment metadata missing",
        )

    if not user_id:
        raise HTTPException(
            status_code=400,
            detail="User ID missing",
        )

    if not shipping_address:
        raise HTTPException(
            status_code=400,
            detail="Shipping address missing",
        )

    db: Session = SessionLocal()

    try:

        # ====================================================
        # 7. Find payment
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
        # 8. Idempotency protection
        # ====================================================

        if payment.status == PaymentStatus.PAID:

            return {
                "received": True,
                "message": "Payment already processed",
            }

        # ====================================================
        # 9. Get customer's cart
        # ====================================================

        cart = (
            db.query(Cart)
            .options(
                joinedload(Cart.items)
                .joinedload(CartItem.product)
            )
            .filter(
                Cart.user_id == int(user_id)
            )
            .first()
        )

        if not cart or not cart.items:

            raise HTTPException(
                status_code=400,
                detail="Cart is empty or no longer exists",
            )

        # ====================================================
        # 10. Validate cart again
        # ====================================================

        total_amount = payment.amount

        order = Order(
            user_id=int(user_id),
            total_amount=total_amount,
            status=OrderStatus.CONFIRMED,
            shipping_address=shipping_address,
        )

        db.add(order)

        db.flush()

        # ====================================================
        # 11. Create OrderItems
        # ====================================================

        for cart_item in cart.items:

            product = (
                db.query(Product)
                .filter(
                    Product.id == cart_item.product_id
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
                    detail=f"Product '{product.name}' is no longer available",
                )

            if product.stock < cart_item.quantity:

                raise HTTPException(
                    status_code=400,
                    detail=f"Not enough stock for '{product.name}'",
                )

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=cart_item.quantity,
                unit_price=product.price,
            )

            db.add(order_item)

            # Reduce stock only after successful payment
            product.stock -= cart_item.quantity

        # ====================================================
        # 12. Update payment
        # ====================================================

        payment.status = PaymentStatus.PAID

        payment.transaction_id = session.get(
            "payment_intent"
        )

        payment.order_id = order.id

        # ====================================================
        # 13. Clear cart
        # ====================================================

        for cart_item in list(cart.items):

            db.delete(cart_item)

        # ====================================================
        # 14. Commit everything together
        # ====================================================

        db.commit()

        db.refresh(order)

        # ====================================================
        # 15. Notify admin
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

            # WebSocket failure must not
            # undo successful payment.
            pass

        return {
            "received": True
        }

    except Exception:

        db.rollback()

        raise

    finally:

        db.close()