from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pwdlib import PasswordHash
from app.core.security import create_access_token
from app.database import get_db
from app.models.user import User,UserRole
from app.models.profile import Profile
from fastapi.security import OAuth2PasswordBearer
from app.schemas.user import UserCreate, UserResponse,UserLogin

from app.dependencies.auth import get_current_user

router = APIRouter(prefix="/accounts", tags=["Authentication"])

password_hash = PasswordHash.recommended()



@router.post("/register", response_model=UserResponse)
def register(
    user_data: UserCreate,
    db: Session = Depends(get_db)
):
    # 1. Check if email already exists
    existing_email = db.query(User).filter(User.email == user_data.email).first()

    if existing_email:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    # 2. Check if username already exists
    existing_username = db.query(User).filter(
        User.username == user_data.username
    ).first()

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
    if not len(user_data.password ) > 8:
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
    db.flush()
    new_profile = Profile(
    user_id=new_user.id
)
    db.add(new_profile)
    
    db.commit()
    db.refresh(new_user)

    # 7. Return user
    return new_user



@router.post("/login")
def login(
    user_data: UserLogin,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(
        User.email == user_data.email
    ).first()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    password_is_valid = password_hash.verify(
        user_data.password,
        user.password_hash
    )

    if not password_is_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    access_token = create_access_token(
    data={"sub": str(user.id)}
)

    return {
    "access_token": access_token,
    "token_type": "bearer"
}
    
