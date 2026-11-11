from typing import Literal

from pydantic import BaseModel


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "unavailable"]
