import pytest
import pytest_asyncio
from httpx import AsyncClient
from app.dependencies.auth import get_current_user
from app.models.user import User, UserRole

async def mock_customer_user():
    return User(
        id=1,
        first_name="Cart",
        last_name="Tester",
        email="cart@example.com",
        username="carttester",
        role=UserRole.CUSTOMER,
        is_active=True
    )

@pytest.fixture(autouse=True)
def override_auth():
    from app.main import app
    app.dependency_overrides[get_current_user] = mock_customer_user
    yield
    app.dependency_overrides.pop(get_current_user, None)

@pytest.mark.asyncio
async def test_cart_operations(client: AsyncClient):
    # Get Cart
    res = await client.get("/cart")
    assert res.status_code in [200, 404]
