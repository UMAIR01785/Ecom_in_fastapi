
from langchain_groq import ChatGroq

from app.config import settings


def get_llm() -> ChatGroq:
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")

    return ChatGroq(
        model="openai/gpt-oss-20b",
        temperature=0,
        api_key=settings.groq_api_key,
        max_retries=1,
    )
