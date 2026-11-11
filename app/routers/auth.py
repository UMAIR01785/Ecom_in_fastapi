
from datetime import datetime, timezone

import jwt
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    SECRET_KEY,
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    get_token_expiry,
)
from app.database import get_db
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.models.profile import Profile
from pwdlib import PasswordHash
from app.schemas.user import UserResponse, UserCreate, UserLogin


router = APIRouter(prefix="/accounts", tags=["Authentication"])

password_hash = PasswordHash.recommended()


def set_refresh_cookie(
    response: Response,
    token: str,
) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True, # MUST be True for SameSite=None
        samesite="none", # Required for cross-site cookie transmission (Vercel frontend to Cloudflare backend)
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/accounts",
    )


# -----------------------------------------
# REGISTER
# -----------------------------------------

@router.post("/register", response_model=UserResponse)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    # 1. Check if email already exists
    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    existing_email = result.scalar_one_or_none()

    if existing_email:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    # 2. Check if username already exists
    result = await db.execute(
        select(User).where(User.username == user_data.username)
    )
    existing_username = result.scalar_one_or_none()

    if existing_username:
        raise HTTPException(
            status_code=400,
            detail="Username already taken"
        )

    # 3. Check password confirmation
    if user_data.password != user_data.confirm_password:
        raise HTTPException(
            status_code=400,
            detail="Passwords do not match"
        )

    if not len(user_data.password) > 8:
        raise HTTPException(
            status_code=400,
            detail="Passwords length is greater then 8"
        )

    # 4. Hash password
    hashed_password = password_hash.hash(user_data.password)

    # 5. Create database user
    new_user = User(
        first_name=user_data.first_name,
        last_name=user_data.last_name,
        email=user_data.email,
        username=user_data.username,
        password_hash=hashed_password,
        phone_number=user_data.phone_number,
        role=UserRole.CUSTOMER
    )

    # 6. Save to database
    db.add(new_user)
    await db.flush()

    new_profile = Profile(
        user_id=new_user.id
    )

    db.add(new_profile)

    await db.commit()
    await db.refresh(new_user)

    # 7. Return user
    return new_user


# -----------------------------------------
# LOGIN
# -----------------------------------------

@router.post("/login")
async def login(
    user_data: UserLogin,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.email == user_data.email)
    )
    user = result.scalar_one_or_none()

    if not user or not password_hash.verify(
        user_data.password,
        user.password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    access_token = create_access_token({
        "sub": str(user.id)
    })

    refresh_token = create_refresh_token({
        "sub": str(user.id)
    })

    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_refresh_token(refresh_token),
        expires_at=get_token_expiry(refresh_token),
    )

    db.add(refresh_record)
    await db.commit()

    set_refresh_cookie(response, refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


# -----------------------------------------
# REFRESH ACCESS TOKEN
# -----------------------------------------

@router.post("/refresh")
async def refresh_access_token(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is missing",
        )

    try:
        payload = jwt.decode(
            refresh_token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid or expired",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        )

    now = datetime.now(timezone.utc)
    token_hash = hash_refresh_token(refresh_token)

    # Lock this session row while validating and rotating it.
    result = await db.execute(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.token_hash == token_hash,
        )
        .with_for_update()
    )

    stored_token = result.scalar_one_or_none()

    if (
        stored_token is None
        or stored_token.revoked_at is not None
        or stored_token.expires_at <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh session is invalid or expired",
        )

    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is unavailable",
        )

    # Revoke the old refresh token.
    stored_token.revoked_at = now

    # Issue a new access token and rotate the refresh token.
    new_access_token = create_access_token({
        "sub": str(user.id)
    })

    new_refresh_token = create_refresh_token({
        "sub": str(user.id)
    })

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(new_refresh_token),
            expires_at=get_token_expiry(new_refresh_token),
        )
    )

    # Revoke and create the new session record atomically.
    await db.commit()

    set_refresh_cookie(response, new_refresh_token)

    return {
        "access_token": new_access_token,
        "token_type": "bearer",
    }


# -----------------------------------------
# LOGOUT
# -----------------------------------------

@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get("refresh_token")

    if refresh_token:
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash
                == hash_refresh_token(refresh_token)
            )
        )

        stored_token = result.scalar_one_or_none()

        if stored_token and stored_token.revoked_at is None:
            stored_token.revoked_at = datetime.now(timezone.utc)
            await db.commit()

    response.delete_cookie(
        key="refresh_token",
        path="/accounts",
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite="lax",
    )

    return {"message": "Logged out successfully"}
