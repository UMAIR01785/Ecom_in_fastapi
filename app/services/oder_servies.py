
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.cart import Cart, CartItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User


# ============================================================
# CHECKOUT
# ============================================================

def checkout_cart(
    db: Session,
    current_user: User,
    shipping_address: str,
):

    # ========================================================
    # 1. Get user's cart
    # ========================================================

    cart = (
        db.query(Cart)
        .options(
            joinedload(Cart.items)
            .joinedload(CartItem.product)
        )
        .filter(Cart.user_id == current_user.id)
        .first()
    )

    if not cart:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart not found",
        )

    # ========================================================
    # 2. Check empty cart
    # ========================================================

    if not cart.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cart is empty",
        )

    # ========================================================
    # 3. Lock products, validate stock,
    #    and calculate total
    # ========================================================

    total_amount = Decimal("0.00")

    locked_products = {}

    for cart_item in cart.items:

        product = (
            db.query(Product)
            .filter(Product.id == cart_item.product.id)
            .with_for_update()
            .first()
        )

        if not product:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A product in your cart no longer exists",
            )

        locked_products[product.id] = product

        # Product inactive
        if not product.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Product '{product.name}' is no longer available",
            )

        # Not enough stock
        if product.stock < cart_item.quantity:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Not enough stock for '{product.name}'",
            )

        # Calculate total using database price
        total_amount += product.price * cart_item.quantity

    # ========================================================
    # 4. Create order
    # ========================================================

    order = Order(
        user_id=current_user.id,
        status=OrderStatus.PENDING,
        total_amount=total_amount,
        shipping_address=shipping_address,
    )

    db.add(order)

    # Generate order.id before creating OrderItems
    db.flush()

    # ========================================================
    # 5. Create OrderItems + decrease stock
    # ========================================================

    for cart_item in cart.items:

        # Use the already locked product
        product = locked_products[cart_item.product.id]

        order_item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=cart_item.quantity,
            unit_price=product.price,
        )

        db.add(order_item)

        # Reduce stock
        product.stock -= cart_item.quantity

    # ========================================================
    # 6. Clear cart
    # ========================================================

    for cart_item in cart.items:
        db.delete(cart_item)

    # ========================================================
    # 7. Commit transaction
    # ========================================================

    try:

        db.commit()

    except Exception:

        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Checkout failed",
        )

    # ========================================================
    # 8. Refresh order
    # ========================================================

    db.refresh(order)

    return order


# ============================================================
# CANCEL ORDER
# ============================================================

def cancel_order(
    db: Session,
    current_user: User,
    order_id: int,
):

    # ========================================================
    # 1. Get and lock user's order
    # ========================================================

    order = (
        db.query(Order)
        .filter(
            Order.id == order_id,
            Order.user_id == current_user.id,
        )
        .with_for_update()
        .first()
    )

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    # ========================================================
    # 2. Only pending orders can be cancelled
    # ========================================================

    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending orders can be cancelled",
        )

    # ========================================================
    # 3. Restore product stock
    # ========================================================

    for order_item in order.items:

        product = (
            db.query(Product)
            .filter(Product.id == order_item.product_id)
            .with_for_update()
            .first()
        )

        if product:
            product.stock += order_item.quantity

    # ========================================================
    # 4. Change order status
    # ========================================================

    order.status = OrderStatus.CANCELLED

    # ========================================================
    # 5. Commit transaction
    # ========================================================

    try:

        db.commit()

    except Exception:

        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel order",
        )

    # ========================================================
    # 6. Refresh order
    # ========================================================

    db.refresh(order)

    return order

