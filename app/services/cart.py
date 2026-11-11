
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cart import Cart, CartItem
from app.models.product import Product
from app.models.product_variant import ProductVariant


# ============================================================
# CART QUERY / EAGER LOADING
# ============================================================

def _cart_query():
    """
    Load cart items, products, product categories and variants.

    This prevents lazy-loading database queries when building
    the cart response with AsyncSession.
    """
    return (
        select(Cart)
        .options(
            selectinload(Cart.items)
            .selectinload(CartItem.product)
            .selectinload(Product.categories),

            selectinload(Cart.items)
            .selectinload(CartItem.variant),
        )
    )


async def _load_cart(
    db: AsyncSession,
    cart: Cart,
) -> Cart:
    result = await db.execute(
        _cart_query().where(Cart.id == cart.id)
    )

    loaded_cart = result.scalar_one_or_none()

    if loaded_cart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart not found",
        )

    return loaded_cart


# ============================================================
# GET OR CREATE GUEST CART
# ============================================================

async def get_or_create_guest_cart(
    db: AsyncSession,
    guest_id: str,
) -> Cart:
    result = await db.execute(
        _cart_query().where(Cart.guest_id == guest_id)
    )

    cart = result.scalar_one_or_none()

    if cart:
        return cart

    cart = Cart(guest_id=guest_id)

    db.add(cart)

    try:
        await db.commit()
        await db.refresh(cart)

    except Exception:
        await db.rollback()
        raise

    return await _load_cart(db, cart)


# ============================================================
# GET OR CREATE USER CART
# ============================================================

async def get_or_create_user_cart(
    db: AsyncSession,
    user_id: int,
) -> Cart:
    result = await db.execute(
        _cart_query().where(Cart.user_id == user_id)
    )

    cart = result.scalar_one_or_none()

    if cart:
        return cart

    cart = Cart(user_id=user_id)

    db.add(cart)

    try:
        await db.commit()
        await db.refresh(cart)

    except Exception:
        await db.rollback()
        raise

    return await _load_cart(db, cart)


# ============================================================
# GET CART BY GUEST ID
# ============================================================

async def get_cart_by_guest_id(
    db: AsyncSession,
    guest_id: str,
) -> Cart | None:
    result = await db.execute(
        _cart_query().where(Cart.guest_id == guest_id)
    )

    return result.scalar_one_or_none()


# ============================================================
# GET CART BY USER ID
# ============================================================

async def get_cart_by_user_id(
    db: AsyncSession,
    user_id: int,
) -> Cart | None:
    result = await db.execute(
        _cart_query().where(Cart.user_id == user_id)
    )

    return result.scalar_one_or_none()


# ============================================================
# GET PRODUCT AND VARIANT
# ============================================================

async def _get_product_and_variant(
    db: AsyncSession,
    product_id: int,
    variant_id: int | None,
) -> tuple[Product, ProductVariant | None]:

    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )

    product = result.scalar_one_or_none()

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

    # Check whether the product has any active variants.
    variant_result = await db.execute(
        select(ProductVariant.id)
        .where(
            ProductVariant.product_id == product_id,
            ProductVariant.is_active.is_(True),
        )
        .limit(1)
    )

    active_variants_exist = (
        variant_result.scalar_one_or_none() is not None
    )

    # Product without a selected variant.
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

    # Product with a selected variant.
    variant_result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id,
            ProductVariant.product_id == product_id,
        )
    )

    variant = variant_result.scalar_one_or_none()

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


# ============================================================
# AVAILABLE STOCK
# ============================================================

def _available_stock(
    product: Product,
    variant: ProductVariant | None,
) -> int:
    return variant.stock if variant else product.stock


# ============================================================
# UNIT PRICE
# ============================================================

def _unit_price(
    product: Product,
    variant: ProductVariant | None,
) -> Decimal:

    if variant and variant.price is not None:
        return Decimal(str(variant.price))

    return Decimal(str(product.price))


# ============================================================
# ADD TO CART
# ============================================================

async def add_to_cart(
    db: AsyncSession,
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

    product, variant = await _get_product_and_variant(
        db=db,
        product_id=product_id,
        variant_id=variant_id,
    )

    result = await db.execute(
        select(CartItem).where(
            CartItem.cart_id == cart.id,
            CartItem.product_id == product_id,
            CartItem.variant_id == variant_id,
        )
    )

    cart_item = result.scalar_one_or_none()

    new_quantity = quantity + (
        cart_item.quantity if cart_item else 0
    )

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
        await db.commit()

    except Exception:
        await db.rollback()
        raise

    if cart.user_id is not None:
        refreshed_cart = await get_cart_by_user_id(
            db=db,
            user_id=cart.user_id,
        )
    else:
        refreshed_cart = await get_cart_by_guest_id(
            db=db,
            guest_id=cart.guest_id,
        )

    if refreshed_cart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart not found",
        )

    return refreshed_cart


# ============================================================
# UPDATE CART ITEM
# ============================================================

async def update_cart_item(
    db: AsyncSession,
    cart: Cart,
    cart_item_id: int,
    quantity: int,
) -> Cart:

    if quantity <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Quantity must be greater than zero",
        )

    result = await db.execute(
        select(CartItem).where(
            CartItem.id == cart_item_id,
            CartItem.cart_id == cart.id,
        )
    )

    cart_item = result.scalar_one_or_none()

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart item not found",
        )

    product, variant = await _get_product_and_variant(
        db=db,
        product_id=cart_item.product_id,
        variant_id=cart_item.variant_id,
    )

    if quantity > _available_stock(product, variant):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not enough stock available",
        )

    cart_item.quantity = quantity

    try:
        await db.commit()

    except Exception:
        await db.rollback()
        raise

    if cart.user_id is not None:
        return await get_cart_by_user_id(
            db=db,
            user_id=cart.user_id,
        )

    return await get_cart_by_guest_id(
        db=db,
        guest_id=cart.guest_id,
    )


# ============================================================
# REMOVE CART ITEM
# ============================================================

async def remove_from_cart(
    db: AsyncSession,
    cart: Cart,
    cart_item_id: int,
) -> Cart:

    result = await db.execute(
        select(CartItem).where(
            CartItem.id == cart_item_id,
            CartItem.cart_id == cart.id,
        )
    )

    cart_item = result.scalar_one_or_none()

    if not cart_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart item not found",
        )

    await db.delete(cart_item)

    try:
        await db.commit()

    except Exception:
        await db.rollback()
        raise

    if cart.user_id is not None:
        return await get_cart_by_user_id(
            db=db,
            user_id=cart.user_id,
        )

    return await get_cart_by_guest_id(
        db=db,
        guest_id=cart.guest_id,
    )


# ============================================================
# CLEAR CART
# ============================================================

async def clear_cart(
    db: AsyncSession,
    cart: Cart,
) -> None:

    await db.execute(
        delete(CartItem).where(
            CartItem.cart_id == cart.id
        )
    )

    try:
        await db.commit()

    except Exception:
        await db.rollback()
        raise


# ============================================================
# CALCULATE SUBTOTAL
# ============================================================

def calculate_subtotal(cart: Cart) -> Decimal:

    subtotal = Decimal("0.00")

    for item in cart.items:
        subtotal += (
            _unit_price(item.product, item.variant)
            * item.quantity
        )

    return subtotal


# ============================================================
# MERGE GUEST CART INTO USER CART
# ============================================================

async def merge_guest_cart_into_user_cart(
    db: AsyncSession,
    guest_cart: Cart,
    user_cart: Cart,
) -> Cart:

    for guest_item in guest_cart.items:

        try:
            product, variant = await _get_product_and_variant(
                db=db,
                product_id=guest_item.product_id,
                variant_id=guest_item.variant_id,
            )

        except HTTPException:
            # Skip products or variants that are no longer available.
            continue

        result = await db.execute(
            select(CartItem).where(
                CartItem.cart_id == user_cart.id,
                CartItem.product_id == guest_item.product_id,
                CartItem.variant_id == guest_item.variant_id,
            )
        )

        user_item = result.scalar_one_or_none()

        existing_quantity = (
            user_item.quantity if user_item else 0
        )

        stock = _available_stock(product, variant)

        new_quantity = min(
            existing_quantity + guest_item.quantity,
            stock,
        )

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

    await db.delete(guest_cart)

    try:
        await db.commit()

    except Exception:
        await db.rollback()
        raise

    refreshed_cart = await get_cart_by_user_id(
        db=db,
        user_id=user_cart.user_id,
    )

    if refreshed_cart is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cart not found",
        )

    return refreshed_cart
