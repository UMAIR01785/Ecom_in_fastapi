
import asyncio
from getpass import getpass

from sqlalchemy import select, or_

from app.database import SessionLocal
from app.models.user import User, UserRole
from app.models.profile import Profile
from app.core.security import hash_password


async def create_admin():
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

    

    async with SessionLocal() as db:
        try:
            # Check existing email, username, or phone
            result = await db.execute(
                select(User).where(
                    or_(
                        User.email == email,
                        User.username == username,
                        User.phone_number == phone_number,
                    )
                )
            )

            existing_user = result.scalar_one_or_none()

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

            # Generate admin ID
            await db.flush()

            # Create associated profile
            profile = Profile(user_id=admin.id)
            db.add(profile)

            # Commit both records together
            await db.commit()

            # Reload generated database values
            await db.refresh(admin)
            await db.refresh(profile)

            print("\nAdmin created successfully!")
            print(f"ID: {admin.id}")
            print(f"Username: {admin.username}")
            print(f"Email: {admin.email}")
            print(f"Role: {admin.role.value}")
            print(f"Profile ID: {profile.id}")

        except Exception as e:
            await db.rollback()
            print(f"Error creating admin: {e}")


if __name__ == "__main__":
    asyncio.run(create_admin())
