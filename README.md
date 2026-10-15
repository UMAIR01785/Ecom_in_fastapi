# Ecom_in_fastapi

Backend API for an e-commerce platform built with FastAPI, SQLAlchemy, PostgreSQL, Stripe, Cloudinary, WebSockets, and an admin AI chat assistant.

## What this backend includes

- JWT auth with **access + refresh token rotation**
- Role-based access (**customer/admin**)
- User profile management with Cloudinary profile images
- Category and product management (admin CRUD + public listing)
- Guest and authenticated shopping carts (with cart merge on login)
- Checkout with shipping address + order item snapshot pricing
- Payment handling for **COD** and **Stripe card checkout**
- Stripe webhook processing for payment confirmation/expiry
- Inventory reservation/release logic tied to order lifecycle
- Admin order management and reporting dashboards
- WebSocket updates for customer order status + admin live events
- Admin AI chat assistant with database tools (orders/payments/products/categories)

## Tech stack

- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Pydantic / pydantic-settings
- JWT (`pyjwt`, `python-jose`)
- `pwdlib[argon2]` for password hashing
- Stripe
- Cloudinary
- LangChain + Groq (admin AI chat)

## Project structure

- `/app/main.py` - FastAPI app and router registration
- `/app/config.py` - environment settings
- `/app/database.py` - engine/session/base
- `/app/models` - SQLAlchemy models
- `/app/schemas` - request/response schemas
- `/app/routers` - API endpoints
- `/app/services` - business logic (cart/order/payment/chat/inventory)
- `/app/dependencies` - auth and role checks
- `/app/websockets` - WS auth and connection manager
- `/app/ai` - admin AI agent, prompts, and tools
- `/app/scripts` - seed/admin utility scripts
- `/alembic` - DB migrations

## Core domain models

- Users, Profiles, RefreshTokens
- Categories, Products (many-to-many)
- Carts, CartItems
- Orders, OrderItems, OrderAddress
- Payments
- ChatConversations, ChatMessages

## Environment variables

Create `.env` in the repository root with:

```env
DATABASE_URL=******localhost:5432/dbname

CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...

SECRET_KEY=...
ALGORITHM=HS256

STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=...

GROQ_API_KEY=...

# false in local HTTP dev, true in HTTPS production
REFRESH_COOKIE_SECURE=false
```

## Local setup

### 1) Install dependencies

Using `uv`:

```bash
uv sync
```

or using pip:

```bash
pip install -r requirements.txt
```

### 2) Run migrations

```bash
alembic upgrade head
```

### 3) Start API server

```bash
uvicorn app.main:app --reload
```

Open docs at:

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/redoc`

## API overview

### Public / Auth

- `GET /` - API health message
- `POST /accounts/register`
- `POST /accounts/login`
- `POST /accounts/refresh`
- `POST /accounts/logout`

### Profile (authenticated)

- `GET /profile`
- `PATCH /profile/update`
- `POST /profile/image`
- `DELETE /profile/image`

### Categories

- Public: `GET /categories/`, `GET /categories/{slug}`
- Admin: `GET /categories/admin/all`, `POST /categories/admin`, `PATCH /categories/admin/{slug}`, `DELETE /categories/admin/{slug}`

### Products (mounted under `/products`)

- Public: `GET /products/`, `GET /products/{category_slug}`, `GET /products/{category_slug}/{product_slug}`
- Admin: `POST /products/`, `GET /products/admin/products`, `PUT /products/{category_slug}/{product_slug}`, `DELETE /products/{category_slug}/{product_slug}`

### Cart

- `POST /cart/items`
- `GET /cart`
- `PATCH /cart/items/{product_id}`
- `DELETE /cart/items/{product_id}`
- `DELETE /cart`
- `POST /cart/merge`

### Orders

- Customer: `POST /orders/checkout`, `GET /orders/`, `GET /orders/{order_id}`, `PATCH /orders/{order_id}/cancel`
- Admin: `GET /admin/orders/`, `GET /admin/orders/{order_id}`, `PATCH /admin/orders/{order_id}/status`

### Payments

- Stripe webhook: `POST /payments/webhook`
- Customer receipt: `GET /payments/{payment_id}/receipt`
- Admin payments: `GET /admin/payments/`, `GET /admin/payments/{payment_id}`

### Admin reporting

- `GET /admin/reports/overview`
- `GET /admin/reports/sales`
- `GET /admin/reports/order-statuses`
- `GET /admin/reports/top-products`
- `GET /admin/reports/payments`
- `GET /admin/reports/inventory`

### Admin utilities

- `GET /admin/users/`
- Admin chat:
  - `POST /admin/chat/conversations`
  - `GET /admin/chat/conversations`
  - `GET /admin/chat/conversations/{conversation_id}/messages`
  - `POST /admin/chat/conversations/{conversation_id}/messages`
  - `DELETE /admin/chat/conversations/{conversation_id}`

## WebSocket endpoints

- Customer order updates: `ws://<host>/ws/orders?token=<access_token>`
- Admin live updates: `ws://<host>/ws/admin/orders?token=<access_token>`

Admin socket receives events like new orders, payment completion, and inventory updates.

## Included scripts

- Create admin user:
  ```bash
  python -m app.scripts.create_admin
  ```
- Seed fake categories/products (optional orders):
  ```bash
  python -m app.scripts.seed_data
  python -m app.scripts.seed_data --force
  python -m app.scripts.seed_data --orders
  ```

## Notes

- Refresh token is stored in an HTTP-only cookie (`/accounts` path).
- Card checkout currently uses Stripe success/cancel URLs pointing to `http://localhost:5173/...`.
- `main.py` at repository root is not the API entrypoint; use `app.main:app`.
