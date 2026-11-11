import json
from decimal import Decimal
from math import ceil

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    Query,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.cloudinary import upload_product_image
from app.core.redis import redis_client
from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.category import Category
from app.models.product import Product
from app.schemas.pagination import PaginatedResponse
from app.schemas.product import ProductResponse
from app.utils.slug import generate_slug


router = APIRouter(
    prefix="",
    tags=["Products"],
)


# ============================================================
# HELPERS
# ============================================================

async def invalidate_active_products_cache() -> None:
    """
    Remove every cached active-product pagination response.

    Cache keys currently follow:
        products:active:page:{page}:limit:{limit}
    """
    async for key in redis_client.scan_iter(
        match="products:active:*",
        count=100,
    ):
        await redis_client.delete(key)


async def get_categories_by_slugs(
    db: AsyncSession,
    category_slugs: list[str],
) -> list[Category]:
    """
    Fetch categories in one async query and preserve the submitted
    order. Duplicate slugs are normalized before validation.
    """
    unique_slugs = list(dict.fromkeys(category_slugs))

    result = await db.execute(
        select(Category).where(Category.slug.in_(unique_slugs))
    )
    categories = result.scalars().all()

    categories_by_slug = {
        category.slug: category
        for category in categories
    }

    if len(categories_by_slug) != len(unique_slugs):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more categories not found",
        )

    return [categories_by_slug[slug] for slug in unique_slugs]


async def get_product_with_categories(
    db: AsyncSession,
    product_id: int,
) -> Product | None:
    """Reload a product with categories eagerly loaded for Pydantic."""
    result = await db.execute(
        select(Product)
        .options(selectinload(Product.categories))
        .where(Product.id == product_id)
    )
    return result.scalar_one_or_none()


# ============================================================
# CREATE PRODUCT
# ============================================================

@router.post(
    "/",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_product(
    name: str = Form(...),
    description: str | None = Form(None),
    price: Decimal = Form(...),
    stock: int = Form(...),
    category_slugs: list[str] = Form(...),
    is_active: bool = Form(True),
    image: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(admin_required),
):
    if price <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Price must be greater than zero",
        )

    if stock < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stock cannot be negative",
        )

    categories = await get_categories_by_slugs(db, category_slugs)

    existing_name_result = await db.execute(
        select(Product.id).where(Product.name == name).limit(1)
    )
    if existing_name_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this name already exists",
        )

    slug = generate_slug(name)

    existing_slug_result = await db.execute(
        select(Product.id).where(Product.slug == slug).limit(1)
    )
    if existing_slug_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Product with this slug already exists",
        )

    image_url = None
    if image is not None:
        image_url = await upload_product_image(image)

    product = Product(
        name=name,
        slug=slug,
        description=description,
        price=price,
        stock=stock,
        image=image_url,
        is_active=is_active,
        categories=categories,
    )

    product_id = product.id

    try:
        db.add(product)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # Re-query with categories loaded. This avoids async lazy-loading
    # when ProductResponse reads Product.category_slugs.
    saved_product = await get_product_with_categories(db, product_id)
    await invalidate_active_products_cache()

    return saved_product


# ============================================================
# ADMIN - GET ALL PRODUCTS
# Includes active and inactive products.
# ============================================================

@router.get(
    "/admin/products",
    response_model=PaginatedResponse[ProductResponse],
)
async def get_all_products_admin(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(admin_required),
):
    total_result = await db.execute(
        select(func.count()).select_from(Product)
    )
    total = total_result.scalar_one()

    products_result = await db.execute(
        select(Product)
        .options(selectinload(Product.categories))
        .order_by(Product.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    products = products_result.scalars().all()

    total_pages = ceil(total / limit) if total else 0

    return {
        "items": products,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


# ============================================================
# CUSTOMER - GET ACTIVE PRODUCTS
# ============================================================

@router.get(
    "/",
    response_model=PaginatedResponse[ProductResponse],
)
async def get_products(
    response: Response,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    cache_key = f"products:active:page:{page}:limit:{limit}"

    cached_products = await redis_client.get(cache_key)

    if cached_products is not None:
        response.headers["X-Cache"] = "HIT"
        if isinstance(cached_products, bytes):
            cached_products = cached_products.decode("utf-8")
        return json.loads(cached_products)

    filters = Product.is_active.is_(True)

    total_result = await db.execute(
        select(func.count())
        .select_from(Product)
        .where(filters)
    )
    total = total_result.scalar_one()

    products_result = await db.execute(
        select(Product)
        .options(selectinload(Product.categories))
        .where(filters)
        .order_by(Product.id)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    products = products_result.scalars().all()

    items = [
        ProductResponse.model_validate(product).model_dump(mode="json")
        for product in products
    ]

    total_pages = ceil(total / limit) if total else 0

    result = {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }

    await redis_client.set(
        cache_key,
        json.dumps(result),
        ex=600,
    )

    response.headers["X-Cache"] = "MISS"
    return result


# ============================================================
# CUSTOMER - GET PRODUCTS BY CATEGORY
# Example: GET /shoes
# ============================================================

@router.get(
    "/{category_slug}",
    response_model=list[ProductResponse],
)
async def get_products_by_category(
    category_slug: str,
    db: AsyncSession = Depends(get_db),
):
    category_result = await db.execute(
        select(Category.id).where(Category.slug == category_slug)
    )
    category_id = category_result.scalar_one_or_none()

    if category_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    products_result = await db.execute(
        select(Product)
        .options(selectinload(Product.categories))
        .where(
            Product.categories.any(Category.id == category_id),
            Product.is_active.is_(True),
        )
        .order_by(Product.id)
    )

    return products_result.scalars().all()


# ============================================================
# CUSTOMER - GET SINGLE PRODUCT
# Example: GET /shoes/nike-air-max
# ============================================================

@router.get(
    "/{category_slug}/{product_slug}",
    response_model=ProductResponse,
)
async def get_product(
    category_slug: str,
    product_slug: str,
    db: AsyncSession = Depends(get_db),
):
    category_result = await db.execute(
        select(Category.id).where(Category.slug == category_slug)
    )
    category_id = category_result.scalar_one_or_none()

    if category_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    product_result = await db.execute(
        select(Product)
        .options(selectinload(Product.categories))
        .where(
            Product.slug == product_slug,
            Product.categories.any(Category.id == category_id),
            Product.is_active.is_(True),
        )
    )
    product = product_result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found in this category",
        )

    return product


# ============================================================
# UPDATE PRODUCT
# Example: PUT /shoes/nike-air-max
# ============================================================

@router.put(
    "/{category_slug}/{product_slug}",
    response_model=ProductResponse,
)
async def update_product(
    category_slug: str,
    product_slug: str,
    name: str | None = Form(None),
    description: str | None = Form(None),
    price: Decimal | None = Form(None),
    stock: int | None = Form(None),
    is_active: bool | None = Form(None),
    category_slugs: list[str] | None = Form(None),
    image: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(admin_required),
):
    category_result = await db.execute(
        select(Category.id).where(Category.slug == category_slug)
    )
    category_id = category_result.scalar_one_or_none()

    if category_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    product_result = await db.execute(
        select(Product)
        .options(selectinload(Product.categories))
        .where(
            Product.slug == product_slug,
            Product.categories.any(Category.id == category_id),
        )
    )
    product = product_result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found in this category",
        )

    if price is not None and price <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Price must be greater than zero",
        )

    if stock is not None and stock < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Stock cannot be negative",
        )

    if name is not None:
        new_slug = generate_slug(name)

        duplicate_result = await db.execute(
            select(Product.id).where(
                Product.slug == new_slug,
                Product.id != product.id,
            ).limit(1)
        )
        if duplicate_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Another product already uses this name",
            )

        product.name = name
        product.slug = new_slug

    if description is not None:
        product.description = description

    if price is not None:
        product.price = price

    # NOTE: This preserves the existing endpoint's direct stock update.
    # With inventory lots enabled, stock changes should instead be routed
    # through the inventory service so Product.stock and lot quantities
    # remain consistent.
    if stock is not None:
        product.stock = stock

    if is_active is not None:
        product.is_active = is_active

    if category_slugs is not None:
        categories = await get_categories_by_slugs(db, category_slugs)
        product.categories = categories

    if image is not None:
        product.image = await upload_product_image(image)

    product_id = product.id

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    updated_product = await get_product_with_categories(db, product_id)
    await invalidate_active_products_cache()

    return updated_product


# ============================================================
# DELETE PRODUCT (SOFT DELETE)
# Example: DELETE /shoes/nike-air-max
# ============================================================

@router.delete(
    "/{category_slug}/{product_slug}",
    status_code=status.HTTP_200_OK,
)
async def delete_product(
    category_slug: str,
    product_slug: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(admin_required),
):
    category_result = await db.execute(
        select(Category.id).where(Category.slug == category_slug)
    )
    category_id = category_result.scalar_one_or_none()

    if category_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    product_result = await db.execute(
        select(Product).where(
            Product.slug == product_slug,
            Product.categories.any(Category.id == category_id),
        )
    )
    product = product_result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found in this category",
        )

    product.is_active = False

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    await invalidate_active_products_cache()

    return {
        "message": "Product deleted successfully"
    }