
from langchain_openrouter import ChatOpenRouter

from app.config import settings


def get_llm() -> ChatOpenRouter:
    if not settings.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    return ChatOpenRouter(
        model="openrouter/free",
        temperature=0,
        api_key=settings.openrouter_api_key,
        max_retries=1,
    )
