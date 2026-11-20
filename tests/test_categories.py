
import pytest
from httpx import AsyncClient

from app.main import app
from app.dependencies.permissions import admin_required
from app.models.user import User, UserRole


async def mock_admin_required():
    return User(
        id=1,
        first_name="Admin",
        last_name="User",
        email="admin@example.com",
        username="admin",
        role=UserRole.ADMIN,
        is_active=True,
    )


@pytest.fixture(autouse=True)
def override_admin():
    # Preserve any existing override
    previous_override = app.dependency_overrides.get(admin_required)

    app.dependency_overrides[admin_required] = mock_admin_required

    yield

    # Restore previous override
    if previous_override is not None:
        app.dependency_overrides[admin_required] = previous_override
    else:
        app.dependency_overrides.pop(admin_required, None)


@pytest.mark.asyncio
async def test_create_category(client: AsyncClient):
    payload = {
        "name": "Running Shoes",
        "description": "Great running shoes",
    }

    response = await client.post(
        "/categories/admin",
        data=payload,
    )

    assert response.status_code in (200, 201), response.text

    data = response.json()
    assert data is not None


@pytest.mark.asyncio
async def test_get_categories_list(client: AsyncClient):
    response = await client.get("/categories/")

    assert response.status_code == 200, response.text

    data = response.json()
    assert data is not None
