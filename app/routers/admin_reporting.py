
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.order import Order, OrderItem, OrderStatus
from app.models.payment import Payment, PaymentStatus
from app.models.product import Product
from app.models.user import User, UserRole


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/reports",
    tags=["Admin Reports"],
)


# ============================================================
# SHARED DATE HELPERS
# ============================================================

def resolve_dates(
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:

    today = datetime.utcnow().date()

    if start_date is None and end_date is None:
        end_date = today
        start_date = today - timedelta(days=29)

    elif start_date is None:
        start_date = end_date - timedelta(days=29)

    elif end_date is None:
        end_date = today

    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date cannot be after end_date",
        )

    return start_date, end_date


def get_date_conditions(column, start_date, end_date):

    start_dt = datetime.combine(
        start_date,
        time.min,
    )

    end_exclusive = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
    )

    return (
        column >= start_dt,
        column < end_exclusive,
    )


def enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


async def get_count(db: AsyncSession, model) -> int:

    result = await db.execute(
        select(func.count()).select_from(model)
    )

    return result.scalar_one()


# ============================================================
# SHARED REPORT FUNCTIONS
# ============================================================

async def paid_revenue(
    db: AsyncSession,
    start_date,
    end_date,
) -> Decimal:
    """
    Count only payments marked PAID.

    Cancelled orders are excluded.
    Payment.paid_at determines when payment was received.
    """

    conditions = get_date_conditions(
        Payment.paid_at,
        start_date,
        end_date,
    )

    statement = (
        select(
            func.coalesce(
                func.sum(Payment.amount),
                Decimal("0.00"),
            )
        )
        .select_from(Payment)
        .join(Order, Order.id == Payment.order_id)
        .where(
            Payment.status == PaymentStatus.PAID,
            Order.status != OrderStatus.CANCELLED,
            Payment.paid_at.is_not(None),
            *conditions,
        )
    )

    result = await db.execute(statement)

    return result.scalar_one() or Decimal("0.00")


async def get_order_status_counts(
    db: AsyncSession,
    start_date,
    end_date,
) -> dict[str, int]:

    conditions = get_date_conditions(
        Order.created_at,
        start_date,
        end_date,
    )

    statement = (
        select(
            Order.status,
            func.count(Order.id),
        )
        .where(*conditions)
        .group_by(Order.status)
    )

    result = await db.execute(statement)

    rows = result.all()

    counts = {
        status.value: 0
        for status in OrderStatus
    }

    for order_status, count in rows:
        counts[enum_value(order_status)] = int(count)

    return counts


# ============================================================
# 1. OVERVIEW CARDS
# ============================================================

@router.get("/overview")
async def report_overview(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    low_stock_threshold: int = Query(
        default=5,
        ge=0,
        le=10000,
    ),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    start_date, end_date = resolve_dates(
        start_date,
        end_date,
    )

    # Total orders within date range
    order_conditions = get_date_conditions(
        Order.created_at,
        start_date,
        end_date,
    )

    result = await db.execute(
        select(func.count(Order.id)).where(
            *order_conditions
        )
    )

    total_orders = result.scalar_one()

    # Order status counts
    status_counts = await get_order_status_counts(
        db,
        start_date,
        end_date,
    )

    # Paid revenue
    total_revenue = await paid_revenue(
        db,
        start_date,
        end_date,
    )

    # Total customers
    result = await db.execute(
        select(func.count(User.id)).where(
            User.role == UserRole.CUSTOMER
        )
    )

    total_customers = result.scalar_one()

    # Total products
    total_products = await get_count(db, Product)

    # Active products
    result = await db.execute(
        select(func.count(Product.id)).where(
            Product.is_active.is_(True)
        )
    )

    active_products = result.scalar_one()

    # Low stock products
    result = await db.execute(
        select(func.count(Product.id)).where(
            Product.is_active.is_(True),
            Product.stock <= low_stock_threshold,
        )
    )

    low_stock_products = result.scalar_one()

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "currency": "PKR",
        "total_revenue": float(total_revenue),
        "total_orders": total_orders,
        "total_customers": total_customers,
        "total_products": total_products,
        "active_products": active_products,
        "low_stock_products": low_stock_products,
        "order_statuses": status_counts,
        "revenue_definition": (
            "Payments marked paid, excluding cancelled orders"
        ),
    }


# ============================================================
# 2. SALES / REVENUE CHART
# ============================================================

@router.get("/sales")
async def report_sales(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    start_date, end_date = resolve_dates(
        start_date,
        end_date,
    )

    sale_date = func.date(Payment.paid_at)

    conditions = get_date_conditions(
        Payment.paid_at,
        start_date,
        end_date,
    )

    statement = (
        select(
            sale_date.label("sale_date"),
            func.sum(Payment.amount).label("revenue"),
            func.count(Payment.id).label("payment_count"),
        )
        .select_from(Payment)
        .join(Order, Order.id == Payment.order_id)
        .where(
            Payment.status == PaymentStatus.PAID,
            Payment.paid_at.is_not(None),
            Order.status != OrderStatus.CANCELLED,
            *conditions,
        )
        .group_by(sale_date)
        .order_by(sale_date.asc())
    )

    result = await db.execute(statement)

    rows = result.all()

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "currency": "PKR",
        "sales": [
            {
                "date": row.sale_date.isoformat(),
                "revenue": float(row.revenue or 0),
                "payment_count": int(row.payment_count),
            }
            for row in rows
        ],
    }


# ============================================================
# 3. ORDER STATUS REPORT
# ============================================================

@router.get("/order-statuses")
async def report_order_statuses(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    start_date, end_date = resolve_dates(
        start_date,
        end_date,
    )

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "statuses": await get_order_status_counts(
            db,
            start_date,
            end_date,
        ),
    }


# ============================================================
# 4. TOP-SELLING PRODUCTS
# ============================================================

@router.get("/top-products")
async def report_top_products(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(
        default=10,
        ge=1,
        le=50,
    ),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    start_date, end_date = resolve_dates(
        start_date,
        end_date,
    )

    reportable_statuses = [
        OrderStatus.CONFIRMED,
        OrderStatus.PROCESSING,
        OrderStatus.SHIPPED,
        OrderStatus.DELIVERED,
    ]

    conditions = get_date_conditions(
        Order.created_at,
        start_date,
        end_date,
    )

    statement = (
        select(
            Product.id.label("product_id"),
            Product.name.label("product_name"),
            Product.stock.label("current_stock"),
            func.sum(
                OrderItem.quantity
            ).label("quantity_sold"),
            func.sum(
                OrderItem.unit_price * OrderItem.quantity
            ).label("item_gross_value"),
        )
        .select_from(Product)
        .join(
            OrderItem,
            OrderItem.product_id == Product.id,
        )
        .join(
            Order,
            Order.id == OrderItem.order_id,
        )
        .where(
            Order.status.in_(reportable_statuses),
            *conditions,
        )
        .group_by(
            Product.id,
            Product.name,
            Product.stock,
        )
        .order_by(
            func.sum(OrderItem.quantity).desc()
        )
        .limit(limit)
    )

    result = await db.execute(statement)

    rows = result.all()

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "currency": "PKR",
        "products": [
            {
                "product_id": row.product_id,
                "product_name": row.product_name,
                "quantity_sold": int(row.quantity_sold),
                "item_gross_value": float(
                    row.item_gross_value or 0
                ),
                "current_stock": row.current_stock,
            }
            for row in rows
        ],
    }


# ============================================================
# 5. PAYMENT METHOD AND STATUS BREAKDOWN
# ============================================================

@router.get("/payments")
async def report_payments(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    start_date, end_date = resolve_dates(
        start_date,
        end_date,
    )

    conditions = get_date_conditions(
        Payment.created_at,
        start_date,
        end_date,
    )

    statement = (
        select(
            Payment.method.label("method"),
            Payment.status.label("status"),
            func.count(Payment.id).label("payment_count"),
            func.sum(Payment.amount).label("amount_total"),
        )
        .select_from(Payment)
        .join(Order, Order.id == Payment.order_id)
        .where(
            Order.status != OrderStatus.CANCELLED,
            *conditions,
        )
        .group_by(
            Payment.method,
            Payment.status,
        )
    )

    result = await db.execute(statement)

    rows = result.all()

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "currency": "PKR",
        "groups": [
            {
                "method": enum_value(row.method),
                "status": enum_value(row.status),
                "payment_count": int(row.payment_count),
                "amount_total": float(row.amount_total or 0),
            }
            for row in rows
        ],
    }


# ============================================================
# 6. INVENTORY / LOW STOCK REPORT
# ============================================================

@router.get("/inventory")
async def report_inventory(
    threshold: int = Query(
        default=5,
        ge=0,
        le=10000,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
    ),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(admin_required),
):

    # Active products count
    result = await db.execute(
        select(func.count(Product.id)).where(
            Product.is_active.is_(True)
        )
    )

    active_products = result.scalar_one()

    # Out of stock products
    result = await db.execute(
        select(func.count(Product.id)).where(
            Product.is_active.is_(True),
            Product.stock <= 0,
        )
    )

    out_of_stock = result.scalar_one()

    # Low stock products count
    result = await db.execute(
        select(func.count(Product.id)).where(
            Product.is_active.is_(True),
            Product.stock > 0,
            Product.stock <= threshold,
        )
    )

    low_stock_count = result.scalar_one()

    # Low stock product details
    statement = (
        select(Product)
        .where(
            Product.is_active.is_(True),
            Product.stock <= threshold,
        )
        .order_by(
            Product.stock.asc(),
            Product.name.asc(),
        )
        .limit(limit)
    )

    result = await db.execute(statement)

    low_stock_rows = result.scalars().all()

    return {
        "threshold": threshold,
        "active_products": active_products,
        "out_of_stock_products": out_of_stock,
        "low_stock_count": low_stock_count,
        "low_stock_products": [
            {
                "product_id": product.id,
                "name": product.name,
                "stock": product.stock,
                "price": float(product.price),
                "is_active": product.is_active,
            }
            for product in low_stock_rows
        ],
    }
