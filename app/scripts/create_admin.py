from getpass import getpass

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.user import User, UserRole
from app.models.profile import Profile
from app.core.security import hash_password


def create_admin():
    db: Session = SessionLocal()

    try:
        print("=== Create Admin User ===")

        first_name = input("First name: ").strip()
        last_name = input("Last name: ").strip()
        username = input("Username: ").strip()
        email = input("Email: ").strip()
        phone_number = input("Phone number: ").strip()

        password = getpass("Password: ")
        confirm_password = getpass("Confirm password: ")

        if password != confirm_password:
            print("Passwords do not match.")
            return

        # Check email
        if db.query(User).filter(User.email == email).first():
            print("Email already exists.")
            return

        # Check username
        if db.query(User).filter(User.username == username).first():
            print("Username already exists.")
            return

        # Check phone number
        if db.query(User).filter(
            User.phone_number == phone_number
        ).first():
            print("Phone number already exists.")
            return

        # Create admin user
        admin = User(
            first_name=first_name,
            last_name=last_name,
            username=username,
            email=email,
            phone_number=phone_number,
            password_hash=hash_password(password),
            role=UserRole.ADMIN,
            is_active=True,
        )

        db.add(admin)
        db.commit()
        db.refresh(admin)

        # Create admin profile
        profile = Profile(
            user_id=admin.id
        )

        db.add(profile)
        db.commit()
        db.refresh(profile)

        print("\nAdmin created successfully!")
        print(f"ID: {admin.id}")
        print(f"Username: {admin.username}")
        print(f"Email: {admin.email}")
        print(f"Role: {admin.role.value}")
        print(f"Profile ID: {profile.id}")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")

    finally:
        db.close()


if __name__ == "__main__":
    create_admin()