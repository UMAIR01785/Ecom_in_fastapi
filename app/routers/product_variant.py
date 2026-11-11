
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.schemas.product_variant import (
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
)

router = APIRouter(tags=["Product Variants"])


async def get_product_or_404(
    db: AsyncSession,
    product_id: int,
) -> Product:

    result = await db.execute(
        select(Product).where(Product.id == product_id)
    )

    product = result.scalar_one_or_none()

    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return product


async def get_variant_or_404(
    db: AsyncSession,
    product_id: int,
    variant_id: int,
) -> ProductVariant:

    result = await db.execute(
        select(ProductVariant).where(
            ProductVariant.id == variant_id,
            ProductVariant.product_id == product_id,
        )
    )

    variant = result.scalar_one_or_none()

    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant not found for this product",
        )

    return variant


@router.post(
    "/{product_id}/variants",
    response_model=ProductVariantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_variant(
    product_id: int,
    payload: ProductVariantCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(admin_required),
):

    product = await get_product_or_404(db, product_id)

    if not product.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add a variant to an inactive product",
        )

    variant = ProductVariant(
        product_id=product.id,
        sku=payload.sku.strip(),
        size=payload.size.strip(),
        color=payload.color.strip(),
        price=payload.price,
        stock=payload.stock,
        is_active=payload.is_active,
    )

    db.add(variant)

    try:
        await db.commit()
        await db.refresh(variant)

    except IntegrityError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SKU or size/color combination already exists",
        )

    return variant


@router.get(
    "/{product_id}/variants",
    response_model=list[ProductVariantResponse],
)
async def list_variants(
    product_id: int,
    db: AsyncSession = Depends(get_db),
):

    await get_product_or_404(db, product_id)

    result = await db.execute(
        select(ProductVariant)
        .where(ProductVariant.product_id == product_id)
        .order_by(
            ProductVariant.size,
            ProductVariant.color,
        )
    )

    return result.scalars().all()


@router.patch(
    "/{product_id}/variants/{variant_id}",
    response_model=ProductVariantResponse,
)
async def update_variant(
    product_id: int,
    variant_id: int,
    payload: ProductVariantUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(admin_required),
):

    await get_product_or_404(db, product_id)

    variant = await get_variant_or_404(
        db,
        product_id,
        variant_id,
    )

    changes = payload.model_dump(exclude_unset=True)

    for field, value in changes.items():

        if field in {"sku", "size", "color"}:

            if value is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"{field} cannot be null",
                )

            value = value.strip()

        if field in {"stock", "is_active"} and value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{field} cannot be null",
            )

        setattr(variant, field, value)

    try:
        await db.commit()
        await db.refresh(variant)

    except IntegrityError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SKU or size/color combination already exists",
        )

    return variant


@router.delete(
    "/{product_id}/variants/{variant_id}",
)
async def deactivate_variant(
    product_id: int,
    variant_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(admin_required),
):

    await get_product_or_404(db, product_id)

    variant = await get_variant_or_404(
        db,
        product_id,
        variant_id,
    )

    # Preserve inventory history.
    # Deactivate instead of physically deleting.
    variant.is_active = False

    await db.commit()
    await db.refresh(variant)

    return {
        "message": "Variant deactivated successfully"
    }
