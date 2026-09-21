from decimal import Decimal

from fastapi import HTTPException, status

from sqlalchemy.orm import Session, joinedload

from app.models.cart import Cart, CartItem
from app.models.product import Product


def get_or_create_guest_cart(
    db: Session,
    guest_id: str,
) -> Cart:

    cart = (
        db.query(Cart)
        .filter(Cart.guest_id == guest_id)
        .first()
    )

    if cart:
        return cart

    cart = Cart(
        guest_id=guest_id
    )

    db.add(cart)
    db.commit()
    db.refresh(cart)

    return cart


def get_or_create_user_cart(
    db: Session,
    user_id: int,
) -> Cart:

    cart = (
        db.query(Cart)
        .filter(Cart.user_id == user_id)
        .first()
    )

    if cart:
        return cart

    cart = Cart(
        user_id=user_id
    )

    db.add(cart)
    db.commit()
    db.refresh(cart)

    return cart


def get_cart_by_guest_id(
    db: Session,
    guest_id: str,
) -> Cart | None:

    return (
        db.query(Cart)
        .options(
            joinedload(Cart.items)
            .joinedload(CartItem.product)
        )
        .filter(Cart.guest_id == guest_id)
        .first()
    )


def get_cart_by_user_id(
    db: Session,
    user_id: int,
) -> Cart | None:

    return (
        db.query(Cart)
        .options(
            joinedload(Cart.items)
            .joinedload(CartItem.product)
        )
        .filter(Cart.user_id == user_id)
        .first()
    )


def add_to_cart(
    db: Session,
    cart: Cart,
    product_id: int,
    quantity: int,
) -> Cart:

    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product is not available"
        )

    if product.stock <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product is out of stock"
        )

    cart_item = (
        db.query(CartItem)
        .filter(
            CartItem.cart_id == cart.id,
            CartItem.product_id == product_id
        )
        .first()
    )

    if cart_item:

        new_quantity = cart_item.quantity + quantity

        if new_quantity > product.stock:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Not enough stock available"
            )

        cart_item.quantity = new_quantity

    else:

        if quantity > product.stock:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Not enough stock available"
            )

        cart_item = CartItem(
            cart_id=cart.id,
            product_id=product_id,
            quantity=quantity
        )

        db.add(cart_item)

    db.commit()

    return get_cart_by_user_id(
        db,
        cart.user_id
    ) if cart.user_id else get_cart_by_guest_id(
        db,
        cart.guest_id
    )


def update_cart_item(
    db: Session,
    cart: Cart,
    product_id: int,
    quantity: int,
) -> Cart:

    cart_item = (
        db.query(CartItem)
        .filter(
            CartItem.cart_id == cart.id,
            CartItem.product_id == product_id
        )
        .first()
    )

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product is not in the cart"
        )

    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found"
        )

    if quantity > product.stock:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not enough stock available"
        )

    cart_item.quantity = quantity

    db.commit()

    return (
        get_cart_by_user_id(db, cart.user_id)
        if cart.user_id
        else get_cart_by_guest_id(db, cart.guest_id)
    )


def remove_from_cart(
    db: Session,
    cart: Cart,
    product_id: int,
) -> Cart:

    cart_item = (
        db.query(CartItem)
        .filter(
            CartItem.cart_id == cart.id,
            CartItem.product_id == product_id
        )
        .first()
    )

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product is not in the cart"
        )

    db.delete(cart_item)
    db.commit()

    return (
        get_cart_by_user_id(db, cart.user_id)
        if cart.user_id
        else get_cart_by_guest_id(db, cart.guest_id)
    )


def clear_cart(
    db: Session,
    cart: Cart,
) -> None:

    db.query(CartItem).filter(
        CartItem.cart_id == cart.id
    ).delete()

    db.commit()


def calculate_subtotal(
    cart: Cart,
) -> Decimal:

    subtotal = Decimal("0.00")

    for item in cart.items:

        subtotal += (
            item.product.price *
            item.quantity
        )

    return subtotal


def merge_guest_cart_into_user_cart(
    db: Session,
    guest_cart: Cart,
    user_cart: Cart,
) -> Cart:

    for guest_item in guest_cart.items:

        user_item = (
            db.query(CartItem)
            .filter(
                CartItem.cart_id == user_cart.id,
                CartItem.product_id == guest_item.product_id
            )
            .first()
        )

        if user_item:

            new_quantity = (
                user_item.quantity +
                guest_item.quantity
            )

            if new_quantity > guest_item.product.stock:
                new_quantity = guest_item.product.stock

            user_item.quantity = new_quantity

        else:

            user_item = CartItem(
                cart_id=user_cart.id,
                product_id=guest_item.product_id,
                quantity=guest_item.quantity
            )

            db.add(user_item)

    db.delete(guest_cart)

    db.commit()

    return get_cart_by_user_id(
        db,
        user_cart.user_id
    )