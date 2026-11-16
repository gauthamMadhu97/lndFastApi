from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.integrations.notifier import Notifier
from app.integrations.warranty_client import WarrantyClient
from app.models import User
from app.models.enums import Role
from app.services import user_service

# auto_error=False so a missing token goes through our own 401 format
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: DbSession,
    settings: AppSettings,
) -> User:
    if not token:
        raise AuthenticationError()
    try:
        payload = decode_access_token(token, settings)
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid token") from exc

    # Role comes from the database rather than the token, so a role change takes effect immediately
    user = user_service.get_by_username(db, str(payload["sub"]))
    if user is None:
        raise AuthenticationError("Invalid token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_admin(user: CurrentUser) -> User:
    if user.role != Role.ADMIN:
        raise PermissionDeniedError("This action needs the admin role")
    return user


def get_notifier(request: Request) -> Notifier:
    notifier: Notifier = request.app.state.notifier
    return notifier


def get_warranty_client(request: Request) -> WarrantyClient:
    client: WarrantyClient = request.app.state.warranty_client
    return client
