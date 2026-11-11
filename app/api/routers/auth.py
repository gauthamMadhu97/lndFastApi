from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import AppSettings, CurrentUser, DbSession
from app.api.responses import errors
from app.core.errors import AuthenticationError
from app.core.security import create_access_token
from app.schemas.auth import Token, UserRead
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["Auth"])


# Plain def on purpose: bcrypt is CPU-bound, so it runs in the threadpool
# instead of holding up the event loop.
@router.post(
    "/token",
    response_model=Token,
    summary="Sign in",
    description="Exchange a username and password (form fields) for a bearer token.",
    responses=errors(401, 422),
)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    settings: AppSettings,
) -> Token:
    user = user_service.authenticate(db, form.username, form.password)
    if user is None:
        raise AuthenticationError("Incorrect username or password")
    return Token(
        access_token=create_access_token(user.username, user.role, settings),
        expires_in=settings.access_token_expire_minutes * 60,
        role=user.role,
    )


@router.get("/me", response_model=UserRead, summary="Who am I", responses=errors(401))
def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
