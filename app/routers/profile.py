
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.profile import Profile
from app.schemas.profile import (
    ProfileResponse,
    ProfileUpdate,
    ProfileImageResponse,
)
from app.dependencies.auth import get_current_user
from app.core.cloudinary import (
    upload_profile_image,
    delete_profile_image,
)


router = APIRouter(
    prefix="/profile",
    tags=["Profile"]
)


# ============================================================
# GET PROFILE
# ============================================================

@router.get("", response_model=ProfileResponse)
def get_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .first()
    )

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    return {
        "id": profile.id,
        "user_id": profile.user_id,

        # User fields
        "first_name": profile.user.first_name,
        "last_name": profile.user.last_name,
        "email": profile.user.email,
        "username": profile.user.username,
        "phone_number": profile.user.phone_number,

        # Profile fields
        "profile_picture": profile.profile_picture,
        "bio": profile.bio,
        "address": profile.address,
        "city": profile.city,
    }


# ============================================================
# UPDATE PROFILE
# ============================================================

@router.patch("/update", response_model=ProfileResponse)
def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .first()
    )

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    update_data = data.model_dump(exclude_unset=True)

    user_fields = {
        "first_name",
        "last_name",
        "email",
        "username",
        "phone_number",
    }

    profile_fields = {
        "bio",
        "address",
        "city",
    }

    for field, value in update_data.items():

        if field in user_fields:
            setattr(current_user, field, value)

        elif field in profile_fields:
            setattr(profile, field, value)

    db.commit()

    db.refresh(current_user)
    db.refresh(profile)

    return {
        "id": profile.id,
        "user_id": profile.user_id,

        # User
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "email": current_user.email,
        "username": current_user.username,
        "phone_number": current_user.phone_number,

        # Profile
        "profile_picture": profile.profile_picture,
        "bio": profile.bio,
        "address": profile.address,
        "city": profile.city,
    }


# ============================================================
# UPLOAD / REPLACE PROFILE IMAGE
# ============================================================

@router.post("/image", response_model=ProfileImageResponse)
async def upload_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .first()
    )

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    # Allowed image types
    allowed_types = {
        "image/jpeg",
        "image/png",
        "image/webp",
    }

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Only JPEG, PNG and WebP images are allowed",
        )

    # Read uploaded file
    contents = await file.read()
    await file.close()

    # Maximum size = 5 MB
    MAX_FILE_SIZE = 5 * 1024 * 1024

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="Image size must be less than 5 MB",
        )

    # Save old public_id before replacing the image
    old_public_id = profile.profile_picture_public_id

    try:
        # Upload new image to Cloudinary
        image = upload_profile_image(contents)

        # Save new Cloudinary information
        profile.profile_picture = image["url"]
        profile.profile_picture_public_id = image["public_id"]

        # Save changes to database
        db.commit()
        db.refresh(profile)

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Failed to upload profile image",
        )

    # Delete old image after successful upload + database update
    if old_public_id:
        try:
            delete_profile_image(old_public_id)
        except Exception:
            pass

    return {
        "profile_picture": profile.profile_picture
    }


# ============================================================
# DELETE PROFILE IMAGE
# ============================================================

@router.delete("/image")
def delete_image(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == current_user.id)
        .first()
    )

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found",
        )

    if not profile.profile_picture_public_id:
        raise HTTPException(
            status_code=404,
            detail="Profile image not found",
        )

    try:
        # Delete image from Cloudinary
        delete_profile_image(
            profile.profile_picture_public_id
        )

        # Clear image information from database
        profile.profile_picture = None
        profile.profile_picture_public_id = None

        db.commit()

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Failed to delete profile image",
        )

    return {
        "message": "Profile image deleted successfully"
    }
