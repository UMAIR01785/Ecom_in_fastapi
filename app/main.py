from fastapi import FastAPI
from app.routers.auth import router as auth_router
from app.routers.profile import router as profile_router
from fastapi.middleware.cors import CORSMiddleware
from app.routers.category import router as category_router
from app.routers.product import router as product_router
app = FastAPI(
    title="E-Commerce API",
    description="Backend API for an e-commerce platform",
    version="1.0.0"
)
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(category_router)
app.include_router(product_router, prefix="/products")
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