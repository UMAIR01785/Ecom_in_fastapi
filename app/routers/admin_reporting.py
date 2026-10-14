
# app/routers/admin_reports.py

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import admin_required
from app.models.order import Order, OrderItem, OrderStatus
from app.models.payment import Payment, PaymentMethod, PaymentStatus
from app.models.product import Product
from app.models.user import User, UserRole


router = APIRouter(
    prefix="/admin/reports",
    tags=["Admin Reports"],
)


# ---------------------------------------------------------
# Shared date helpers
# The existing database timestamps are naive UTC datetimes.
# The end date is inclusive.
# ---------------------------------------------------------

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
            status_code=400,
            detail="start_date cannot be after end_date",
        )

    return start_date, end_date


def apply_date_filter(query, column, start_date, end_date):
    start_dt = datetime.combine(start_date, time.min)
    end_exclusive = datetime.combine(
        end_date + timedelta(days=1),
        time.min,
    )

    return query.filter(
        column >= start_dt,
        column < end_exclusive,
    )


def enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def paid_revenue(db: Session, start_date, end_date) -> Decimal:
    """
    Count only payments marked PAID.

    A cancelled order is not counted as revenue.
    Payment.paid_at determines when the payment was received.
    """
    query = (
        db.query(
            func.coalesce(
                func.sum(Payment.amount),
                Decimal("0.00"),
            )
        )
        .join(Order, Order.id == Payment.order_id)
        .filter(
            Payment.status == PaymentStatus.PAID,
            Order.status != OrderStatus.CANCELLED,
            Payment.paid_at.is_not(None),
        )
    )

    query = apply_date_filter(
        query,
        Payment.paid_at,
        start_date,
        end_date,
    )

    return query.scalar() or Decimal("0.00")


def get_order_status_counts(
    db: Session,
    start_date,
    end_date,
) -> dict[str, int]:
    query = apply_date_filter(
        db.query(Order.status, func.count(Order.id)),
        Order.created_at,
        start_date,
        end_date,
    )

    rows = query.group_by(Order.status).all()

    counts = {
        status.value: 0
        for status in OrderStatus
    }

    for status, count in rows:
        counts[enum_value(status)] = int(count)

    return counts


# ---------------------------------------------------------
# 1. OVERVIEW CARDS
# ---------------------------------------------------------

@router.get("/overview")
def report_overview(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    low_stock_threshold: int = Query(default=5, ge=0, le=10000),
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    start_date, end_date = resolve_dates(
        start_date,
        end_date,
    )

    order_query = apply_date_filter(
        db.query(Order),
        Order.created_at,
        start_date,
        end_date,
    )

    total_orders = order_query.count()

    status_counts = get_order_status_counts(
        db,
        start_date,
        end_date,
    )

    total_revenue = paid_revenue(
        db,
        start_date,
        end_date,
    )

    total_customers = (
        db.query(func.count(User.id))
        .filter(User.role == UserRole.CUSTOMER)
        .scalar()
        or 0
    )

    total_products = (
        db.query(func.count(Product.id)).scalar() or 0
    )

    active_products = (
        db.query(func.count(Product.id))
        .filter(Product.is_active.is_(True))
        .scalar()
        or 0
    )

    low_stock_products = (
        db.query(func.count(Product.id))
        .filter(
            Product.is_active.is_(True),
            Product.stock <= low_stock_threshold,
        )
        .scalar()
        or 0
    )

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


# ---------------------------------------------------------
# 2. SALES / REVENUE CHART
# ---------------------------------------------------------

@router.get("/sales")
def report_sales(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    start_date, end_date = resolve_dates(
        start_date,
        end_date,
    )

    sale_date = func.date(Payment.paid_at)

    query = (
        db.query(
            sale_date.label("sale_date"),
            func.sum(Payment.amount).label("revenue"),
            func.count(Payment.id).label("payment_count"),
        )
        .join(Order, Order.id == Payment.order_id)
        .filter(
            Payment.status == PaymentStatus.PAID,
            Payment.paid_at.is_not(None),
            Order.status != OrderStatus.CANCELLED,
        )
    )

    query = apply_date_filter(
        query,
        Payment.paid_at,
        start_date,
        end_date,
    )

    rows = (
        query.group_by(sale_date)
        .order_by(sale_date.asc())
        .all()
    )

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


# ---------------------------------------------------------
# 3. ORDER STATUS REPORT
# ---------------------------------------------------------

@router.get("/order-statuses")
def report_order_statuses(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    start_date, end_date = resolve_dates(
        start_date,
        end_date,
    )

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "statuses": get_order_status_counts(
            db,
            start_date,
            end_date,
        ),
    }


# ---------------------------------------------------------
# 4. TOP-SELLING PRODUCTS
# ---------------------------------------------------------

@router.get("/top-products")
def report_top_products(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
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

    query = (
        db.query(
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
        .join(
            OrderItem,
            OrderItem.product_id == Product.id,
        )
        .join(
            Order,
            Order.id == OrderItem.order_id,
        )
        .filter(
            Order.status.in_(reportable_statuses)
        )
    )

    query = apply_date_filter(
        query,
        Order.created_at,
        start_date,
        end_date,
    )

    rows = (
        query.group_by(
            Product.id,
            Product.name,
            Product.stock,
        )
        .order_by(
            func.sum(OrderItem.quantity).desc()
        )
        .limit(limit)
        .all()
    )

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


# ---------------------------------------------------------
# 5. PAYMENT METHOD AND STATUS BREAKDOWN
# ---------------------------------------------------------

@router.get("/payments")
def report_payments(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    start_date, end_date = resolve_dates(
        start_date,
        end_date,
    )

    query = (
        db.query(
            Payment.method.label("method"),
            Payment.status.label("status"),
            func.count(Payment.id).label("payment_count"),
            func.sum(Payment.amount).label("amount_total"),
        )
    )

    query = apply_date_filter(
        query,
        Payment.created_at,
        start_date,
        end_date,
    )

    rows = (
        query.group_by(
            Payment.method,
            Payment.status,
        )
        .all()
    )

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


# ---------------------------------------------------------
# 6. INVENTORY / LOW STOCK REPORT
# ---------------------------------------------------------

@router.get("/inventory")
def report_inventory(
    threshold: int = Query(default=5, ge=0, le=10000),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    active_products_query = db.query(Product).filter(
        Product.is_active.is_(True)
    )

    active_products = active_products_query.count()

    out_of_stock = active_products_query.filter(
        Product.stock <= 0
    ).count()

    low_stock_count = active_products_query.filter(
        Product.stock > 0,
        Product.stock <= threshold,
    ).count()

    low_stock_rows = (
        active_products_query
        .filter(Product.stock <= threshold)
        .order_by(
            Product.stock.asc(),
            Product.name.asc(),
        )
        .limit(limit)
        .all()
    )

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
