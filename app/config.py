from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_api_secret: str

    secret_key: str
    algorithm: str
    
    redis_url: str = "redis://localhost:6379/0"

    stripe_secret_key: str
    stripe_webhook_secret: str

    # For your AI chatbot
    groq_api_key: str | None = None
    # For your AI chatbot
    openrouter_api_key: str | None = None

    # False for local HTTP development; True for HTTPS production
    refresh_cookie_secure: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()