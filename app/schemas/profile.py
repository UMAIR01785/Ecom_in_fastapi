from pydantic import BaseModel,ConfigDict





class ProfileRespone(BaseModel):
    id: int
    user_id: int
    profile_picture: str | None
    bio: str | None
    address: str | None
    city: str | None

    model_config = ConfigDict(from_attributes=True)