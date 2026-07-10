"""Run once to bootstrap the first Super Admin account.
Usage: python create_superadmin.py
"""
import getpass
from app.database import SessionLocal, Base, engine
from app import models
from app.auth import hash_password

Base.metadata.create_all(bind=engine)


def main():
    name = input("Name: ").strip()
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ").strip()

    db = SessionLocal()
    try:
        if db.query(models.User).filter(models.User.email == email).first():
            print("A user with this email already exists.")
            return
        user = models.User(
            name=name,
            email=email,
            hashed_password=hash_password(password),
            role=models.RoleEnum.super_admin,
        )
        db.add(user)
        db.commit()
        print(f"Super admin '{email}' created.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
