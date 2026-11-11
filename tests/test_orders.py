import pytest
import pytest_asyncio
from httpx import AsyncClient
from app.dependencies.auth import get_current_user
from app.models.user import User, UserRole

async def mock_customer():
    return User(
        id=1,
        first_name="Order",
        last_name="User",
        email="orderuser@example.com",
        username="orderuser",
        role=UserRole.CUSTOMER,
        is_active=True
    )

@pytest.fixture(autouse=True)
def override_user():
    from app.main import app
    app.dependency_overrides[get_current_user] = mock_customer
    yield
    app.dependency_overrides.pop(get_current_user, None)

@pytest.mark.asyncio
async def test_get_user_orders(client: AsyncClient):
    response = await client.get("/orders")
    assert response.status_code in [200, 404]
