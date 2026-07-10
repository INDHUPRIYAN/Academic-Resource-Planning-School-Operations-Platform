from app.database import SessionLocal, Base, engine
from app import models
from app.auth import hash_password

Base.metadata.create_all(bind=engine)

def main():
    email = "admin@eduflow.com"
    name = "Super Admin"
    password = "Admin@123"

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == email).first()
        if user:
            print(f"User '{email}' already exists — skipping.")
            return
        user = models.User(
            name=name,
            email=email,
            hashed_password=hash_password(password),
            role=models.RoleEnum.super_admin,
        )
        db.add(user)
        db.commit()
        print(f"Super admin created: {email} / {password}")
    finally:
        db.close()

if __name__ == "__main__":
    main()
