
from getpass import getpass

from sqlalchemy.orm import Session

from app.models.profile import Profile
from app.database import SessionLocal
from app.models.user import User
from app.core.security import hash_password


def create_admin():
    db: Session = SessionLocal()

    try:
        first_name = input("First name: ")
        last_name = input("Last name: ")
        username = input("Username: ")
        email = input("Admin email: ")
        phone_number = input("Phone number: ")
        password = getpass("Admin password: ")

        existing_user = db.query(User).filter(User.email == email).first()

        if existing_user:
            print("User with this email already exists.")
            return

        admin = User(
            first_name=first_name,
            last_name=last_name,
            username=username,
            email=email,
            phone_number=phone_number,
            password_hash=hash_password(password),
            role="ADMIN",
            is_active=True,
        )

        db.add(admin)
        db.commit()
        db.refresh(admin)

        print("Admin created successfully!")
        print(f"Admin ID: {admin.id}")
        print(f"Email: {admin.email}")

    finally:
        db.close()


if __name__ == "__main__":
    create_admin()

