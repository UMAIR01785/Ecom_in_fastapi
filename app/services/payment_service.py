import stripe

from app.config import settings
from app.models.order import Order
from app.models.payment import Payment

stripe.api_key = settings.stripe_secret_key

CHECKOUT_EXPIRY_SECONDS = 30 * 60


async def create_payment_session(
    order: Order,
    payment: Payment,
):
    session = stripe.checkout.Session.create(
        mode="payment",
        expires_at=int(
            order.reservation_expires_at.timestamp()
        ),
        line_items=[
            {
                "price_data": {
                    "currency": "pkr",
                    "product_data": {
                        "name": f"Order #{order.id}",
                    },
                    "unit_amount": int(
                        payment.amount * 100
                    ),
                },
                "quantity": 1,
            }
        ],
        metadata={
            "order_id": str(order.id),
            "payment_id": str(payment.id),
        },
        payment_intent_data={
            "metadata": {
                "order_id": str(order.id),
                "payment_id": str(payment.id),
            }
        },
        success_url=(
            "http://localhost:5173/payment/success"
            "?session_id={CHECKOUT_SESSION_ID}"
        ),
        cancel_url=(
            "http://localhost:5173/payment/cancel"
        ),
        idempotency_key=f"checkout-order-{order.id}",
    )

    return session


def get_stripe_receipt_url(
    transaction_id: str | None,
) -> str | None:
    if not transaction_id:
        return None

    try:
        intent = stripe.PaymentIntent.retrieve(
            transaction_id,
            expand=["latest_charge"],
        )
        charge = intent.latest_charge

        if charge:
            return getattr(charge, "receipt_url", None)

    except stripe.error.StripeError:
        return None

    return None