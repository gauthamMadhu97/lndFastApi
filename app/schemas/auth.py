from pydantic import BaseModel

from app.models.enums import Role
from app.schemas.common import ResponseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: Role


class UserRead(ResponseModel):
    id: int
    username: str
    role: Role
