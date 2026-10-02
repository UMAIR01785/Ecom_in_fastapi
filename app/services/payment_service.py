# app/services/payment_service.py

import stripe

from app.config import settings
from app.models.payment import Payment


stripe.api_key = settings.stripe_secret_key


async def create_payment_session(
    amount,
    payment: Payment,
    shipping_address: str,
    user_id: int,
):

    session = stripe.checkout.Session.create(

        # ----------------------------------------------------
        # Payment type
        # ----------------------------------------------------

        mode="payment",

        # ----------------------------------------------------
        # What customer is paying for
        # ----------------------------------------------------

        line_items=[
            {
                "price_data": {
                    "currency": "pkr",

                    "product_data": {
                        "name": "E-Commerce Order",
                    },

                    # Stripe expects smallest currency unit
                    "unit_amount": int(amount * 100),
                },

                "quantity": 1,
            }
        ],

        # ----------------------------------------------------
        # Information we need later in webhook
        # ----------------------------------------------------

        metadata={
            "payment_id": str(payment.id),
            "user_id": str(user_id),
            "shipping_address": shipping_address,
        },

        # ----------------------------------------------------
        # Customer returns here after successful payment
        # ----------------------------------------------------

        success_url=(
            "http://localhost:5173/payment/success"
            "?session_id={CHECKOUT_SESSION_ID}"
        ),

        # ----------------------------------------------------
        # Customer returns here if payment is cancelled
        # ----------------------------------------------------

        cancel_url=(
            "http://localhost:5173/payment/cancel"
        ),
    )

    return session