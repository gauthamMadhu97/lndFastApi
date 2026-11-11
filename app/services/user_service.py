from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password, verify_password
from app.models import User
from app.models.enums import Role

# Compared against when the username doesn't exist, so a wrong username
# takes about as long as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password", rounds=4)


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def ensure_default_users(db: Session, settings: Settings) -> list[str]:
    """Create the admin and staff accounts from settings if missing. Returns the names created."""
    created = []
    for username, password, role in (
        (settings.admin_username, settings.admin_password, Role.ADMIN),
        (settings.staff_username, settings.staff_password, Role.STAFF),
    ):
        if get_by_username(db, username) is None:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password, settings.bcrypt_rounds),
                    role=role,
                )
            )
            created.append(username)
    db.commit()
    return created
