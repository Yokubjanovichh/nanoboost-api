from pydantic import BaseModel


class UploadResponse(BaseModel):
    url: str
    filename: str
    folder: str
    size_bytes: int
    content_type: str
