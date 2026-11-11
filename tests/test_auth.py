import pytest
import pytest_asyncio
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient):
    # 1. Register a new user
    register_payload = {
        "first_name": "Test",
        "last_name": "User",
        "email": "testuser@example.com",
        "username": "testuser",
        "password": "password123",
        "confirm_password": "password123",
        "phone_number": "+923001234567"
    }
    response = await client.post("/accounts/register", json=register_payload)
    assert response.status_code == 200
    assert response.json()["email"] == "testuser@example.com"
    assert response.json()["username"] == "testuser"

    # 2. Try registering the same user again (should fail with 400)
    response = await client.post("/accounts/register", json=register_payload)
    assert response.status_code == 400
    assert "Email already registered" in response.json()["detail"]

    # 3. Try to log in
    login_payload = {
        "email": "testuser@example.com",
        "password": "password123"
    }
    response = await client.post("/accounts/login", json=login_payload)
    assert response.status_code == 200
    json_data = response.json()
    assert "access_token" in json_data
    assert json_data["token_type"] == "bearer"

    # 4. Try logging in with wrong password (should fail with 401)
    bad_login_payload = {
        "email": "testuser@example.com",
        "password": "wrongpassword"
    }
    response = await client.post("/accounts/login", json=bad_login_payload)
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]