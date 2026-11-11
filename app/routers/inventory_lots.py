
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

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


def utc_now_naive():
    """Return current UTC time without timezone information."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================
# RECEIVE INVENTORY
# ============================================================

@router.post(
    "/",
    response_model=InventoryLotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_inventory(
    payload: InventoryLotCreate,
    db: AsyncSession = Depends(get_db),
    admin=Depends(admin_required),
):
    try:
        # Normalize expiry date to naive UTC.
        expires_at = payload.expires_at

        if expires_at is not None:
            if expires_at.tzinfo is not None:
                expires_at = expires_at.astimezone(
                    timezone.utc
                ).replace(tzinfo=None)

            if expires_at <= utc_now_naive():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot receive stock with an expired expiry date",
                )

        # ----------------------------------------------------
        # RECEIVE STOCK FOR A VARIANT
        # ----------------------------------------------------

        if payload.variant_id is not None:
            result = await db.execute(
                select(ProductVariant)
                .where(ProductVariant.id == payload.variant_id)
                .with_for_update()
            )

            variant = result.scalar_one_or_none()

            if variant is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product variant not found",
                )

            lot_product_id = None
            lot_variant_id = variant.id

            variant.stock += payload.quantity

        # ----------------------------------------------------
        # RECEIVE STOCK FOR A STANDALONE PRODUCT
        # ----------------------------------------------------

        else:
            result = await db.execute(
                select(Product)
                .where(Product.id == payload.product_id)
                .with_for_update()
            )

            product = result.scalar_one_or_none()

            if product is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found",
                )

            # Check whether this product has variants.
            variant_result = await db.execute(
                select(ProductVariant.id)
                .where(
                    ProductVariant.product_id == product.id
                )
                .limit(1)
            )

            has_variants = (
                variant_result.scalar_one_or_none() is not None
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

        # ----------------------------------------------------
        # CREATE INVENTORY LOT
        # ----------------------------------------------------

        lot = InventoryLot(
            lot_number=payload.lot_number,
            product_id=lot_product_id,
            variant_id=lot_variant_id,
            quantity_received=payload.quantity,
            quantity_remaining=payload.quantity,
            expires_at=expires_at,
            received_at=utc_now_naive(),
        )

        db.add(lot)

        await db.flush()
        await db.commit()
        await db.refresh(lot)

        return lot

    except HTTPException:
        await db.rollback()
        raise

    except SQLAlchemyError:
        await db.rollback()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not receive inventory",
        )


# ============================================================
# LIST INVENTORY LOTS
# ============================================================

@router.get(
    "/",
    response_model=list[InventoryLotResponse],
)
async def list_inventory_lots(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    product_id: int | None = Query(default=None, gt=0),
    variant_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    admin=Depends(admin_required),
):
    if product_id is not None and variant_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide product_id or variant_id, not both",
        )

    query = select(InventoryLot)

    if product_id is not None:
        query = query.where(
            InventoryLot.product_id == product_id
        )

    if variant_id is not None:
        query = query.where(
            InventoryLot.variant_id == variant_id
        )

    query = (
        query
        .order_by(
            InventoryLot.received_at.desc(),
            InventoryLot.id.desc(),
        )
        .offset(skip)
        .limit(limit)
    )

    result = await db.execute(query)

    return result.scalars().all()


# ============================================================
# GET INVENTORY LOT BY ID
# ============================================================

@router.get(
    "/{lot_id}",
    response_model=InventoryLotResponse,
)
async def get_inventory_lot(
    lot_id: int,
    db: AsyncSession = Depends(get_db),
    admin=Depends(admin_required),
):
    result = await db.execute(
        select(InventoryLot).where(
            InventoryLot.id == lot_id
        )
    )

    lot = result.scalar_one_or_none()

    if lot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inventory lot not found",
        )

    return lot
