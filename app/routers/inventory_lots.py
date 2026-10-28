from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.invertory_lots import InventoryLot
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.schemas.inventory_lots import (
    InventoryLotCreate,
    InventoryLotResponse,
)

router = APIRouter(
    prefix="/inventory-lots",
    tags=["Inventory Lots"],
)


@router.post(
    "/",
    response_model=InventoryLotResponse,
    status_code=status.HTTP_201_CREATED,
)
def receive_inventory(
    payload: InventoryLotCreate,
    db: Session = Depends(get_db),
    admin=Depends(admin_required),
):
    try:
        # Normalize timezone-aware expiry to naive UTC because
        # the model uses DateTime(timezone=False).
        expires_at = payload.expires_at

        if expires_at is not None:
            if expires_at.tzinfo is not None:
                expires_at = expires_at.astimezone(
                    timezone.utc
                ).replace(tzinfo=None)

            if expires_at <= datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot receive stock with an expired expiry date",
                )

        # Lock the target row so concurrent stock receipts do not
        # overwrite each other's stock updates.
        if payload.variant_id is not None:
            variant = (
                db.query(ProductVariant)
                .filter(ProductVariant.id == payload.variant_id)
                .with_for_update()
                .first()
            )

            if variant is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product variant not found",
                )

            lot_product_id = None
            lot_variant_id = variant.id
            variant.stock += payload.quantity

        else:
            product = (
                db.query(Product)
                .filter(Product.id == payload.product_id)
                .with_for_update()
                .first()
            )

            if product is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found",
                )

            # Do not add standalone product stock when the product
            # uses variants. Its stock is tracked by each variant.
            has_variants = (
                db.query(ProductVariant.id)
                .filter(ProductVariant.product_id == product.id)
                .first()
            )

            if has_variants:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "This product has variants. "
                        "Receive stock against a specific variant_id."
                    ),
                )

            lot_product_id = product.id
            lot_variant_id = None
            product.stock += payload.quantity

        lot = InventoryLot(
            lot_number=payload.lot_number,
            product_id=lot_product_id,
            variant_id=lot_variant_id,
            quantity_received=payload.quantity,
            quantity_remaining=payload.quantity,
            expires_at=expires_at,
            received_at=datetime.utcnow(),
        )

        db.add(lot)
        db.flush()
        db.commit()
        db.refresh(lot)

        return lot

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not receive inventory",
        )


@router.get("/", response_model=list[InventoryLotResponse])
def list_inventory_lots(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    product_id: int | None = Query(default=None, gt=0),
    variant_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    admin=Depends(admin_required),
):
    if product_id is not None and variant_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide product_id or variant_id, not both",
        )

    query = db.query(InventoryLot)

    if product_id is not None:
        query = query.filter(InventoryLot.product_id == product_id)

    if variant_id is not None:
        query = query.filter(InventoryLot.variant_id == variant_id)

    return (
        query.order_by(InventoryLot.received_at.desc(), InventoryLot.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{lot_id}", response_model=InventoryLotResponse)
def get_inventory_lot(
    lot_id: int,
    db: Session = Depends(get_db),
    admin=Depends(admin_required),
):
    lot = (
        db.query(InventoryLot)
        .filter(InventoryLot.id == lot_id)
        .first()
    )

    if lot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inventory lot not found",
        )

    return lot