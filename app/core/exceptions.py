from fastapi import HTTPException, status


class AppError(HTTPException):
    """Base application error."""


class InvalidCredentialsError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


class InactiveUserError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )


class TokenInvalidError(AppError):
    def __init__(self, detail: str = "Could not validate credentials") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )


class PermissionDeniedError(AppError):
    def __init__(self, detail: str = "Not enough permissions") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )


class NotFoundError(AppError):
    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} not found",
        )


class ConflictError(AppError):
    def __init__(self, detail: str = "Resource already exists") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )


class InvalidStatusTransitionError(AppError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot transition order from '{current}' to '{target}'",
        )


class ValidationFailureError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=detail,
        )
