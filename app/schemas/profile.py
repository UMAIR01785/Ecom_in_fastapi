from pydantic import BaseModel, ConfigDict


class ProfileResponse(BaseModel):
    id: int
    user_id: int

    # User fields
    first_name: str
    last_name: str
    email: str
    username: str
    phone_number: str
    role: str

    # Profile fields
    profile_picture: str | None = None
    bio: str | None = None
    address: str | None = None
    city: str | None = None

    model_config = ConfigDict(from_attributes=True)
    
    
class ProfileUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    username: str | None = None
    phone_number: str | None = None

    bio: str | None = None
    address: str | None = None
    city: str | None = None
    
class ProfileImageResponse(BaseModel):
    profile_picture: str | None = None