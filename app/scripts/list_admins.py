from app.database import SessionLocal
from app.models.user import User
from app.models.profile import Profile

db = SessionLocal()

try:
    admins = db.query(User).filter(User.role == "ADMIN").all()

    for admin in admins:
        print(f"ID: {admin.id}")
        print(f"Email: {admin.email}")
        print("-" * 30)

finally:
    db.close()