from pydantic import BaseModel, EmailStr, Field, field_validator,ConfigDict
import phonenumbers


class UserCreate(BaseModel):
    first_name: str = Field(min_length=2, max_length=100)
    last_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8)
    confirm_password: str
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        try:
            phone = phonenumbers.parse(value, "PK")

            if not phonenumbers.is_valid_number(phone):
                raise ValueError("Invalid phone number")

            return phonenumbers.format_number(
                phone,
                phonenumbers.PhoneNumberFormat.E164
            )

        except phonenumbers.NumberParseException:
            raise ValueError("Invalid phone number")


class UserResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr
    username: str
    phone_number: str
    model_config = ConfigDict(from_attributes=True)
    
    
class UserLogin(BaseModel):
    email: EmailStr
    password: str