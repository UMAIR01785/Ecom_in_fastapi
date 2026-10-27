
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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


def get_product_or_404(db: Session, product_id: int) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id)
        .first()
    )

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        )

    return product


def get_variant_or_404(
    db: Session,
    product_id: int,
    variant_id: int,
) -> ProductVariant:
    variant = (
        db.query(ProductVariant)
        .filter(
            ProductVariant.id == variant_id,
            ProductVariant.product_id == product_id,
        )
        .first()
    )

    if variant is None:
        raise HTTPException(
            status_code=404,
            detail="Variant not found for this product",
        )

    return variant


@router.post(
    "/{product_id}/variants",
    response_model=ProductVariantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_variant(
    product_id: int,
    payload: ProductVariantCreate,
    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    product = get_product_or_404(db, product_id)

    if not product.is_active:
        raise HTTPException(
            status_code=400,
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
        db.commit()
        db.refresh(variant)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "SKU or size/color combination already exists"
            ),
        )

    return variant


@router.get(
    "/{product_id}/variants",
    response_model=list[ProductVariantResponse],
)
def list_variants(
    product_id: int,
    db: Session = Depends(get_db),
):
    get_product_or_404(db, product_id)

    return (
        db.query(ProductVariant)
        .filter(ProductVariant.product_id == product_id)
        .order_by(ProductVariant.size, ProductVariant.color)
        .all()
    )


@router.patch(
    "/{product_id}/variants/{variant_id}",
    response_model=ProductVariantResponse,
)
def update_variant(
    product_id: int,
    variant_id: int,
    payload: ProductVariantUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    get_product_or_404(db, product_id)
    variant = get_variant_or_404(db, product_id, variant_id)

    changes = payload.model_dump(exclude_unset=True)

    for field, value in changes.items():
        if field in {"sku", "size", "color"}:
            if value is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field} cannot be null",
                )
            value = value.strip()

        if field in {"stock", "is_active"} and value is None:
            raise HTTPException(
                status_code=422,
                detail=f"{field} cannot be null",
            )

        setattr(variant, field, value)

    try:
        db.commit()
        db.refresh(variant)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "SKU or size/color combination already exists"
            ),
        )

    return variant


@router.delete(
    "/{product_id}/variants/{variant_id}",
)
def deactivate_variant(
    product_id: int,
    variant_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(admin_required),
):
    get_product_or_404(db, product_id)
    variant = get_variant_or_404(db, product_id, variant_id)

    # Deactivate instead of physically deleting inventory history.
    variant.is_active = False
    db.commit()
    db.refresh(variant)

    return {"message": "Variant deactivated successfully"}
