from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.core.permissions import require_manager_or_above
from app.features.uploads.schemas import UploadResponse
from app.features.uploads.service import UploadService
from app.features.users.models import User

router = APIRouter(prefix="/uploads", tags=["uploads"])

ManagerAccess = Annotated[User, Depends(require_manager_or_above)]


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_image(
    _: ManagerAccess,
    file: Annotated[UploadFile, File(description="Image file (webp/jpeg/png, max 5MB)")],
    folder: Annotated[str, Form(description="games | services | reviews | misc")],
) -> UploadResponse:
    stored = await UploadService().upload_image(file=file, folder=folder)
    return UploadResponse(
        url=stored.url,
        filename=stored.filename,
        folder=stored.folder,
        size_bytes=stored.size_bytes,
        content_type=stored.content_type,
    )
