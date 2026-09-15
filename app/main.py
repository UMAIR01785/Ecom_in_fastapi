from fastapi import FastAPI
from app.routers.auth import router as auth_router
app = FastAPI(
    title="E-Commerce API",
    description="Backend API for an e-commerce platform",
    version="1.0.0"
)
app.include_router(auth_router)

@app.get("/")
def root():
    return {"message": "E-Commerce API is running"}