
import asyncio

from sqlalchemy import select

from app.database import SessionLocal
from app.models.user import User, UserRole


async def list_admins():
    async with SessionLocal() as db:
        try:
            result = await db.execute(
                select(User).where(
                    User.role == UserRole.ADMIN
                )
            )

            admins = result.scalars().all()

            if not admins:
                print("No admin users found.")
                return

            for admin in admins:
                print(f"ID: {admin.id}")
                print(f"Name: {admin.first_name} {admin.last_name}")
                print(f"Username: {admin.username}")
                print(f"Email: {admin.email}")
                print(f"Phone: {admin.phone_number}")
                print(f"Role: {admin.role.value}")
                print(f"Active: {admin.is_active}")
                print("-" * 30)

        except Exception as e:
            print(f"Error fetching admins: {e}")


if __name__ == "__main__":
    asyncio.run(list_admins())
