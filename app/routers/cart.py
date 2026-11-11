
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.dependencies.auth import (
    get_current_user,
    get_optional_current_user,
)
from app.schemas.cart import (
    CartItemCreate,
    CartItemUpdate,
    CartResponse,
)
from app.services.cart import (
    get_or_create_guest_cart,
    get_or_create_user_cart,
    get_cart_by_guest_id,
    get_cart_by_user_id,
    add_to_cart,
    update_cart_item,
    remove_from_cart,
    clear_cart,
    calculate_subtotal,
    merge_guest_cart_into_user_cart,
    _unit_price,
)

router = APIRouter(prefix="/cart", tags=["Cart"])

GUEST_CART_COOKIE = "guest_cart_id"


# ============================================================
# BUILD CART RESPONSE
# ============================================================

def build_cart_response(cart):
    items = []

    for item in cart.items:
        unit_price = _unit_price(item.product, item.variant)
        item_total = unit_price * item.quantity

        category_slugs = [
            category.slug for category in item.product.categories
        ]

        items.append(
            {
                "id": item.id,
                "product_id": item.product_id,
                "variant_id": item.variant_id,
                "quantity": item.quantity,
                "product": {
                    "id": item.product.id,
                    "name": item.product.name,
                    "slug": item.product.slug,
                    "price": item.product.price,
                    "image": item.product.image,
                    "category_slug": (
                        category_slugs[0] if category_slugs else None
                    ),
                },
                "variant": (
                    {
                        "id": item.variant.id,
                        "sku": item.variant.sku,
                        "size": item.variant.size,
                        "color": item.variant.color,
                        "price": item.variant.price,
                    }
                    if item.variant
                    else None
                ),
                "item_total": item_total,
            }
        )

    return {
        "id": cart.id,
        "user_id": cart.user_id,
        "guest_id": cart.guest_id,
        "items": items,
        "subtotal": calculate_subtotal(cart),
    }


# ============================================================
# GET REQUEST CART
# ============================================================

async def get_request_cart(
    request: Request,
    db: AsyncSession,
    current_user: User | None,
):
    if current_user:
        cart = await get_cart_by_user_id(
            db=db,
            user_id=current_user.id,
        )
    else:
        guest_id = request.cookies.get(GUEST_CART_COOKIE)

        if not guest_id:
            raise HTTPException(
                status_code=404,
                detail="Cart not found",
            )

        cart = await get_cart_by_guest_id(
            db=db,
            guest_id=guest_id,
        )

    if not cart:
        raise HTTPException(
            status_code=404,
            detail="Cart not found",
        )

    return cart


# ============================================================
# ADD ITEM TO CART
# ============================================================

@router.post("/items", response_model=CartResponse)
async def add_item(
    item: CartItemCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    if current_user:
        cart = await get_or_create_user_cart(
            db=db,
            user_id=current_user.id,
        )
    else:
        guest_id = request.cookies.get(GUEST_CART_COOKIE)

        if not guest_id:
            guest_id = str(uuid4())

            response.set_cookie(
                key=GUEST_CART_COOKIE,
                value=guest_id,
                httponly=True,
                samesite="lax",
                secure=False,
                max_age=60 * 60 * 24 * 30,
            )

        cart = await get_or_create_guest_cart(
            db=db,
            guest_id=guest_id,
        )

    cart = await add_to_cart(
        db=db,
        cart=cart,
        product_id=item.product_id,
        variant_id=item.variant_id,
        quantity=item.quantity,
    )

    return build_cart_response(cart)


# ============================================================
# GET CART
# ============================================================

@router.get("", response_model=CartResponse)
async def get_cart(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    cart = await get_request_cart(
        request=request,
        db=db,
        current_user=current_user,
    )

    return build_cart_response(cart)


# ============================================================
# UPDATE CART ITEM
# ============================================================

@router.patch(
    "/items/{cart_item_id}",
    response_model=CartResponse,
)
async def update_item(
    cart_item_id: int,
    item: CartItemUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    cart = await get_request_cart(
        request=request,
        db=db,
        current_user=current_user,
    )

    cart = await update_cart_item(
        db=db,
        cart=cart,
        cart_item_id=cart_item_id,
        quantity=item.quantity,
    )

    return build_cart_response(cart)


# ============================================================
# REMOVE CART ITEM
# ============================================================

@router.delete(
    "/items/{cart_item_id}",
    response_model=CartResponse,
)
async def remove_item(
    cart_item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    cart = await get_request_cart(
        request=request,
        db=db,
        current_user=current_user,
    )

    cart = await remove_from_cart(
        db=db,
        cart=cart,
        cart_item_id=cart_item_id,
    )

    return build_cart_response(cart)


# ============================================================
# CLEAR CART
# ============================================================

@router.delete("")
async def delete_cart(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    if current_user:
        cart = await get_cart_by_user_id(
            db=db,
            user_id=current_user.id,
        )
    else:
        guest_id = request.cookies.get(GUEST_CART_COOKIE)

        if not guest_id:
            return {"message": "Cart already empty"}

        cart = await get_cart_by_guest_id(
            db=db,
            guest_id=guest_id,
        )

    if cart:
        await clear_cart(
            db=db,
            cart=cart,
        )

    if not current_user:
        response.delete_cookie(key=GUEST_CART_COOKIE)

    return {"message": "Cart cleared successfully"}


# ============================================================
# MERGE GUEST CART INTO USER CART
# ============================================================

@router.post("/merge", response_model=CartResponse)
async def merge_cart(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    guest_id = request.cookies.get(GUEST_CART_COOKIE)

    user_cart = await get_or_create_user_cart(
        db=db,
        user_id=current_user.id,
    )

    if not guest_id:
        user_cart = await get_cart_by_user_id(
            db=db,
            user_id=current_user.id,
        )
        return build_cart_response(user_cart)

    guest_cart = await get_cart_by_guest_id(
        db=db,
        guest_id=guest_id,
    )

    if not guest_cart:
        response.delete_cookie(key=GUEST_CART_COOKIE)

        user_cart = await get_cart_by_user_id(
            db=db,
            user_id=current_user.id,
        )

        return build_cart_response(user_cart)

    user_cart = await merge_guest_cart_into_user_cart(
        db=db,
        guest_cart=guest_cart,
        user_cart=user_cart,
    )

    response.delete_cookie(key=GUEST_CART_COOKIE)

    return build_cart_response(user_cart)
