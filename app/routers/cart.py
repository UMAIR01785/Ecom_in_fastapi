from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
)
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User

from app.schemas.cart import (
    CartItemCreate,
    CartItemUpdate,
    CartResponse,
)

from app.dependencies.auth import (
    get_current_user,
    get_optional_current_user,
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
)


router = APIRouter(
    prefix="/cart",
    tags=["Cart"],
)


GUEST_CART_COOKIE = "guest_cart_id"


# =========================================================
# Helper: Convert Cart → CartResponse
# =========================================================

def build_cart_response(cart):

    items = []

    for item in cart.items:

        item_total = (
            item.product.price *
            item.quantity
        )

        category_slugs = [
            c.slug for c in item.product.categories
        ]

        items.append(
            {
                "id": item.id,
                "product_id": item.product_id,
                "quantity": item.quantity,
                "product": {
                    "id": item.product.id,
                    "name": item.product.name,
                    "slug": item.product.slug,
                    "price": item.product.price,
                    "image": item.product.image,
                    "category_slug": category_slugs[0] if category_slugs else None,
                },
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


# =========================================================
# ADD PRODUCT TO CART
# =========================================================

@router.post(
    "/items",
    response_model=CartResponse,
)
def add_item(
    item: CartItemCreate,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(
        get_optional_current_user
    ),
):

    # -----------------------------------------
    # Logged-in user
    # -----------------------------------------

    if current_user:

        cart = get_or_create_user_cart(
            db=db,
            user_id=current_user.id,
        )

    # -----------------------------------------
    # Guest user
    # -----------------------------------------

    else:

        guest_id = request.cookies.get(
            GUEST_CART_COOKIE
        )

        # No guest cart yet
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

        cart = get_or_create_guest_cart(
            db=db,
            guest_id=guest_id,
        )

    # -----------------------------------------
    # Add product
    # -----------------------------------------

    cart = add_to_cart(
        db=db,
        cart=cart,
        product_id=item.product_id,
        quantity=item.quantity,
    )

    return build_cart_response(cart)


# =========================================================
# GET CART
# =========================================================

@router.get(
    "",
    response_model=CartResponse,
)
def get_cart(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(
        get_optional_current_user
    ),
):

    # -----------------------------------------
    # Logged-in user
    # -----------------------------------------

    if current_user:

        cart = get_cart_by_user_id(
            db=db,
            user_id=current_user.id,
        )

    # -----------------------------------------
    # Guest
    # -----------------------------------------

    else:

        guest_id = request.cookies.get(
            GUEST_CART_COOKIE
        )

        if not guest_id:

            raise HTTPException(
                status_code=404,
                detail="Cart not found",
            )

        cart = get_cart_by_guest_id(
            db=db,
            guest_id=guest_id,
        )

    if not cart:

        raise HTTPException(
            status_code=404,
            detail="Cart not found",
        )

    return build_cart_response(cart)


# =========================================================
# UPDATE CART ITEM
# =========================================================

@router.patch(
    "/items/{product_id}",
    response_model=CartResponse,
)
def update_item(
    product_id: int,
    item: CartItemUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(
        get_optional_current_user
    ),
):

    # -----------------------------------------
    # Logged-in user
    # -----------------------------------------

    if current_user:

        cart = get_cart_by_user_id(
            db=db,
            user_id=current_user.id,
        )

    # -----------------------------------------
    # Guest
    # -----------------------------------------

    else:

        guest_id = request.cookies.get(
            GUEST_CART_COOKIE
        )

        if not guest_id:

            raise HTTPException(
                status_code=404,
                detail="Cart not found",
            )

        cart = get_cart_by_guest_id(
            db=db,
            guest_id=guest_id,
        )

    if not cart:

        raise HTTPException(
            status_code=404,
            detail="Cart not found",
        )

    cart = update_cart_item(
        db=db,
        cart=cart,
        product_id=product_id,
        quantity=item.quantity,
    )

    return build_cart_response(cart)


# =========================================================
# REMOVE PRODUCT FROM CART
# =========================================================

@router.delete(
    "/items/{product_id}",
    response_model=CartResponse,
)
def remove_item(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(
        get_optional_current_user
    ),
):

    # -----------------------------------------
    # Logged-in user
    # -----------------------------------------

    if current_user:

        cart = get_cart_by_user_id(
            db=db,
            user_id=current_user.id,
        )

    # -----------------------------------------
    # Guest
    # -----------------------------------------

    else:

        guest_id = request.cookies.get(
            GUEST_CART_COOKIE
        )

        if not guest_id:

            raise HTTPException(
                status_code=404,
                detail="Cart not found",
            )

        cart = get_cart_by_guest_id(
            db=db,
            guest_id=guest_id,
        )

    if not cart:

        raise HTTPException(
            status_code=404,
            detail="Cart not found",
        )

    cart = remove_from_cart(
        db=db,
        cart=cart,
        product_id=product_id,
    )

    return build_cart_response(cart)


# =========================================================
# CLEAR CART
# =========================================================

@router.delete("")
def delete_cart(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(
        get_optional_current_user
    ),
):

    # -----------------------------------------
    # Logged-in user
    # -----------------------------------------

    if current_user:

        cart = get_cart_by_user_id(
            db=db,
            user_id=current_user.id,
        )

    # -----------------------------------------
    # Guest
    # -----------------------------------------

    else:

        guest_id = request.cookies.get(
            GUEST_CART_COOKIE
        )

        if not guest_id:

            return {
                "message": "Cart already empty"
            }

        cart = get_cart_by_guest_id(
            db=db,
            guest_id=guest_id,
        )

    if cart:

        clear_cart(
            db=db,
            cart=cart,
        )

    # Delete guest cookie
    if not current_user:

        response.delete_cookie(
            key=GUEST_CART_COOKIE
        )

    return {
        "message": "Cart cleared successfully"
    }


# =========================================================
# MERGE GUEST CART → USER CART
# =========================================================

@router.post(
    "/merge",
    response_model=CartResponse,
)
def merge_cart(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        get_current_user
    ),
):

    # -----------------------------------------
    # Get guest cart ID
    # -----------------------------------------

    guest_id = request.cookies.get(
        GUEST_CART_COOKIE
    )

    # -----------------------------------------
    # Get/create user's cart
    # -----------------------------------------

    user_cart = get_or_create_user_cart(
        db=db,
        user_id=current_user.id,
    )

    # -----------------------------------------
    # No guest cart
    # -----------------------------------------

    if not guest_id:

        return build_cart_response(
            user_cart
        )

    # -----------------------------------------
    # Find guest cart
    # -----------------------------------------

    guest_cart = get_cart_by_guest_id(
        db=db,
        guest_id=guest_id,
    )

    if not guest_cart:

        response.delete_cookie(
            key=GUEST_CART_COOKIE
        )

        return build_cart_response(
            user_cart
        )

    # -----------------------------------------
    # Merge
    # -----------------------------------------

    user_cart = merge_guest_cart_into_user_cart(
        db=db,
        guest_cart=guest_cart,
        user_cart=user_cart,
    )

    # -----------------------------------------
    # Remove guest cookie
    # -----------------------------------------

    response.delete_cookie(
        key=GUEST_CART_COOKIE
    )

    return build_cart_response(user_cart)