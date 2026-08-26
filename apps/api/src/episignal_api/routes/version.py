from fastapi import APIRouter
from pydantic import BaseModel

from episignal_api import API_NAME, API_VERSION

router = APIRouter(prefix="/api/v1", tags=["version"])


class VersionResponse(BaseModel):
    name: str
    version: str


@router.get("", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(name=API_NAME, version=API_VERSION)
