from fastapi import FastAPI
from app.routers.auth import router as auth_router
from app.routers.profile import router as profile_router
from fastapi.middleware.cors import CORSMiddleware
from app.routers.category import router as category_router
from app.routers.product import router as product_router
from app.routers.cart import router as cart_router
from app.routers.websocket import router as websocket_router
from app.routers import admin_payment
from app.routers.order import router as order_router
from app.routers.admin_user import router as admin_user_router
from app.routers.admin_oder import router as admin_router
from app.routers import payment
from app.routers.admin_reporting import router as admin_reporting_router
from app.routers.product_variant import router as product_variant_router
from app.routers.refund import router as refund_router
from app.routers.admin_chat import router as admin_chat_router
from app.routers.shopping_chat import router as shopping_chat_router
from app.routers import inventory_lots
app = FastAPI(
    title="E-Commerce API",
    description="Backend API for an e-commerce platform",
    version="1.0.0"
)

app.include_router(shopping_chat_router)
app.include_router(inventory_lots.router)
app.include_router(admin_reporting_router)
app.include_router(admin_user_router)
app.include_router(product_variant_router, prefix="/products")
app.include_router(websocket_router)
app.include_router(admin_payment.router)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(category_router)
app.include_router(product_router, prefix="/products")
app.include_router(cart_router)
app.include_router(order_router)
app.include_router(admin_router)
app.include_router(payment.router)
app.include_router(refund_router)
app.include_router(admin_chat_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "https://dev-umair.me",
        "https://www.dev-umair.me",
        "https://admin.dev-umair.me",
        "https://ecomadminpannel.vercel.app",
        
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "E-Commerce API is running"}