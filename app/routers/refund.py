from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.permissions import admin_required

from app.models.user import User

from app.schemas.refund import (
    RefundRequestCreate,
    RefundReviewRequest,
    ReturnInspectionRequest,
    RefundResponse,
)

from app.services.refund_services import (
    request_refund,
    list_my_refunds,
    list_refunds,
    review_refund,
    receive_return_and_process_refund,
    complete_cod_refund,
)


router = APIRouter(tags=["Refunds"])


# ============================================================
# CUSTOMER: REQUEST A REFUND
# POST /orders/{order_id}/refunds
# ============================================================

@router.post(
    "/orders/{order_id}/refunds",
    response_model=RefundResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_refund_request(
    order_id: int,
    data: RefundRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return request_refund(
        db,
        current_user,
        order_id,
        data.reason,
    )


# ============================================================
# CUSTOMER: VIEW OWN REFUND REQUESTS
# GET /refunds/mine
# ============================================================

@router.get(
    "/refunds/mine",
    response_model=list[RefundResponse],
)
def get_my_refunds(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_my_refunds(db, current_user)


# ============================================================
# ADMIN: VIEW ALL REFUNDS
# GET /admin/refunds
# ============================================================

@router.get(
    "/admin/refunds",
    response_model=list[RefundResponse],
)
def get_all_refunds(
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    return list_refunds(db)


# ============================================================
# ADMIN: APPROVE OR REJECT A REFUND
# PATCH /admin/refunds/{refund_id}/review
# ============================================================

@router.patch(
    "/admin/refunds/{refund_id}/review",
    response_model=RefundResponse,
)
def admin_review_refund(
    refund_id: int,
    data: RefundReviewRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    return review_refund(
        db,
        current_admin,
        refund_id,
        data.decision,
        data.admin_note,
    )


# ============================================================
# ADMIN: RECORD RETURN AND INSPECT PRODUCT
# POST /admin/refunds/{refund_id}/receive-return
# ============================================================

@router.post(
    "/admin/refunds/{refund_id}/receive-return",
    response_model=RefundResponse,
)
async def admin_receive_return(
    refund_id: int,
    data: ReturnInspectionRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    return await receive_return_and_process_refund(
        db,
        current_admin,
        refund_id,
        data.restockable,
    )


# ============================================================
# ADMIN: CONFIRM COD REFUND MONEY WAS RETURNED
# POST /admin/refunds/{refund_id}/complete-cod
# ============================================================

@router.post(
    "/admin/refunds/{refund_id}/complete-cod",
    response_model=RefundResponse,
)
async def admin_complete_cod_refund(
    refund_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(admin_required),
):
    return await complete_cod_refund(
        db,
        current_admin,
        refund_id,
    )