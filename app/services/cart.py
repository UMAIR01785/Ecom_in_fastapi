
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.cart import Cart, CartItem
from app.models.product import Product
from app.models.product_variant import ProductVariant


def _load_cart(db: Session, cart: Cart) -> Cart:
    query = (
        db.query(Cart)
        .options(
            joinedload(Cart.items).joinedload(CartItem.product),
            joinedload(Cart.items).joinedload(CartItem.variant),
        )
    )

    if cart.user_id is not None:
        return query.filter(Cart.id == cart.id).one()

    return query.filter(Cart.id == cart.id).one()


def get_or_create_guest_cart(db: Session, guest_id: str) -> Cart:
    cart = db.query(Cart).filter(Cart.guest_id == guest_id).first()

    if cart:
        return cart

    cart = Cart(guest_id=guest_id)
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return cart


def get_or_create_user_cart(db: Session, user_id: int) -> Cart:
    cart = db.query(Cart).filter(Cart.user_id == user_id).first()

    if cart:
        return cart

    cart = Cart(user_id=user_id)
    db.add(cart)
    db.commit()
    db.refresh(cart)
    return cart


def get_cart_by_guest_id(db: Session, guest_id: str) -> Cart | None:
    return (
        db.query(Cart)
        .options(
            joinedload(Cart.items).joinedload(CartItem.product),
            joinedload(Cart.items).joinedload(CartItem.variant),
        )
        .filter(Cart.guest_id == guest_id)
        .first()
    )


def get_cart_by_user_id(db: Session, user_id: int) -> Cart | None:
    return (
        db.query(Cart)
        .options(
            joinedload(Cart.items).joinedload(CartItem.product),
            joinedload(Cart.items).joinedload(CartItem.variant),
        )
        .filter(Cart.user_id == user_id)
        .first()
    )


def _get_product_and_variant(
    db: Session,
    product_id: int,
    variant_id: int | None,
) -> tuple[Product, ProductVariant | None]:
    product = db.query(Product).filter(Product.id == product_id).first()

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product is not available",
        )

    active_variants_exist = (
        db.query(ProductVariant.id)
        .filter(
            ProductVariant.product_id == product_id,
            ProductVariant.is_active.is_(True),
        )
        .first()
        is not None
    )

    if variant_id is None:
        if active_variants_exist:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Select a shoe size and color variant",
            )

        if product.stock <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Product is out of stock",
            )

        return product, None

    variant = (
        db.query(ProductVariant)
        .filter(
            ProductVariant.id == variant_id,
            ProductVariant.product_id == product_id,
        )
        .first()
    )

    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant not found for this product",
        )

    if not variant.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This variant is not available",
        )

    if variant.stock <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This variant is out of stock",
        )

    return product, variant


def _available_stock(
    product: Product,
    variant: ProductVariant | None,
) -> int:
    return variant.stock if variant else product.stock


def _unit_price(
    product: Product,
    variant: ProductVariant | None,
) -> Decimal:
    if variant and variant.price is not None:
        return Decimal(str(variant.price))

    return Decimal(str(product.price))


def add_to_cart(
    db: Session,
    cart: Cart,
    product_id: int,
    quantity: int,
    variant_id: int | None = None,
) -> Cart:
    if quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Quantity must be greater than zero",
        )

    product, variant = _get_product_and_variant(
        db, product_id, variant_id
    )

    cart_item = (
        db.query(CartItem)
        .filter(
            CartItem.cart_id == cart.id,
            CartItem.product_id == product_id,
            CartItem.variant_id == variant_id,
        )
        .first()
    )

    new_quantity = quantity + (cart_item.quantity if cart_item else 0)

    if new_quantity > _available_stock(product, variant):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not enough stock available",
        )

    if cart_item:
        cart_item.quantity = new_quantity
    else:
        db.add(
            CartItem(
                cart_id=cart.id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
            )
        )

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.expire_all()

    refreshed_cart = (
        get_cart_by_user_id(db, cart.user_id)
        if cart.user_id is not None
        else get_cart_by_guest_id(db, cart.guest_id)
    )

    if refreshed_cart is None:
        raise HTTPException(status_code=404, detail="Cart not found")

    return refreshed_cart


def update_cart_item(
    db: Session,
    cart: Cart,
    cart_item_id: int,
    quantity: int,
) -> Cart:
    if quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Quantity must be greater than zero",
        )

    cart_item = (
        db.query(CartItem)
        .filter(
            CartItem.id == cart_item_id,
            CartItem.cart_id == cart.id,
        )
        .first()
    )

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart item not found",
        )

    product, variant = _get_product_and_variant(
        db, cart_item.product_id, cart_item.variant_id
    )

    if quantity > _available_stock(product, variant):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not enough stock available",
        )

    cart_item.quantity = quantity
    db.commit()

    return (
        get_cart_by_user_id(db, cart.user_id)
        if cart.user_id is not None
        else get_cart_by_guest_id(db, cart.guest_id)
    )


def remove_from_cart(
    db: Session,
    cart: Cart,
    cart_item_id: int,
) -> Cart:
    cart_item = (
        db.query(CartItem)
        .filter(
            CartItem.id == cart_item_id,
            CartItem.cart_id == cart.id,
        )
        .first()
    )

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart item not found",
        )

    db.delete(cart_item)
    db.commit()

    return (
        get_cart_by_user_id(db, cart.user_id)
        if cart.user_id is not None
        else get_cart_by_guest_id(db, cart.guest_id)
    )


def clear_cart(db: Session, cart: Cart) -> None:
    db.query(CartItem).filter(
        CartItem.cart_id == cart.id
    ).delete(synchronize_session=False)

    db.commit()


def calculate_subtotal(cart: Cart) -> Decimal:
    subtotal = Decimal("0.00")

    for item in cart.items:
        subtotal += (
            _unit_price(item.product, item.variant)
            * item.quantity
        )

    return subtotal


def merge_guest_cart_into_user_cart(
    db: Session,
    guest_cart: Cart,
    user_cart: Cart,
) -> Cart:
    for guest_item in guest_cart.items:
        try:
            product, variant = _get_product_and_variant(
                db,
                guest_item.product_id,
                guest_item.variant_id,
            )
        except HTTPException:
            # Skip products or variants that are no longer available.
            continue

        user_item = (
            db.query(CartItem)
            .filter(
                CartItem.cart_id == user_cart.id,
                CartItem.product_id == guest_item.product_id,
                CartItem.variant_id == guest_item.variant_id,
            )
            .first()
        )

        existing_quantity = user_item.quantity if user_item else 0
        stock = _available_stock(product, variant)
        new_quantity = min(existing_quantity + guest_item.quantity, stock)

        if new_quantity <= 0:
            continue

        if user_item:
            user_item.quantity = new_quantity
        else:
            db.add(
                CartItem(
                    cart_id=user_cart.id,
                    product_id=guest_item.product_id,
                    variant_id=guest_item.variant_id,
                    quantity=new_quantity,
                )
            )

    db.delete(guest_cart)
    db.commit()

    refreshed_cart = get_cart_by_user_id(db, user_cart.user_id)

    if refreshed_cart is None:
        raise HTTPException(status_code=404, detail="Cart not found")

    return refreshed_cart
