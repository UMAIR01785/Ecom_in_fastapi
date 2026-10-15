
import app.models

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
        email = input("Email: ").strip().lower()
        phone_number = input("Phone number: ").strip()

        password = getpass("Password: ")
        confirm_password = getpass("Confirm password: ")

        # Validate required fields
        if not all([
            first_name,
            last_name,
            username,
            email,
            phone_number,
            password,
        ]):
            print("All fields are required.")
            return

        if password != confirm_password:
            print("Passwords do not match.")
            return

        # Check for existing email, username, or phone
        existing_user = (
            db.query(User)
            .filter(
                (User.email == email)
                | (User.username == username)
                | (User.phone_number == phone_number)
            )
            .first()
        )

        if existing_user:
            print(
                "Email, username, or phone number "
                "already exists."
            )
            return

        # Create admin
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
        db.flush()  # Generates admin.id without committing

        # Create the associated profile
        profile = Profile(user_id=admin.id)
        db.add(profile)

        # Save both records in one transaction
        db.commit()
        db.refresh(admin)
        db.refresh(profile)

        print("\nAdmin created successfully!")
        print(f"ID: {admin.id}")
        print(f"Username: {admin.username}")
        print(f"Email: {admin.email}")
        print(f"Role: {admin.role.value}")
        print(f"Profile ID: {profile.id}")

    except Exception as e:
        db.rollback()
        print(f"Error creating admin: {e}")

    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
