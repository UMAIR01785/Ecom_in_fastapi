from fastapi import FastAPI
from app.routers.auth import router as auth_router
from app.routers.profile import router as profile_router
from fastapi.middleware.cors import CORSMiddleware
from app.routers.category import router as category_router
from app.routers.product import router as product_router
from app.routers.cart import router as cart_router
from app.routers.websocket import router as websocket_router

from app.routers.order import router as order_router
from app.routers.admin_oder import router as admin_router
app = FastAPI(
    title="E-Commerce API",
    description="Backend API for an e-commerce platform",
    version="1.0.0"
)


app.include_router(websocket_router)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(category_router)
app.include_router(product_router, prefix="/products")
app.include_router(cart_router)
app.include_router(order_router)
app.include_router(admin_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"message": "E-Commerce API is running"}