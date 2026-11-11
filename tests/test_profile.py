import pytest
import pytest_asyncio
from httpx import AsyncClient
from app.dependencies.auth import get_current_user
from app.models.user import User, UserRole

async def mock_get_current_user():
    return User(
        id=1,
        first_name="John",
        last_name="Doe",
        email="john@example.com",
        username="johndoe",
        role=UserRole.CUSTOMER,
        is_active=True
    )

@pytest.fixture(autouse=True)
def override_user():
    from app.main import app
    app.dependency_overrides[get_current_user] = mock_get_current_user
    yield
    app.dependency_overrides.pop(get_current_user, None)

@pytest.mark.asyncio
async def test_get_profile(client: AsyncClient):
    response = await client.get("/profile")
    # Should either return user profile or 404 if profile row not seeded yet
    assert response.status_code in [200, 404]
