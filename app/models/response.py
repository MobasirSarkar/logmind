from typing import Any

from pydantic import BaseModel


class ApiError(BaseModel):
    code: str
    message: str
    details: Any | None = None

class ApiResponse[T](BaseModel):
    success: bool = True
    data: T | None = None
    error: ApiError | None = None

    @classmethod
    def ok(cls, data: T) -> "ApiResponse[T]":
        return cls(success=True, data=data, error=None)

    @classmethod
    def fail(cls, code: str, message: str, details: Any | None = None) -> "ApiResponse[None]":
        return ApiResponse[None](
            success=False,
            data=None,
            error=ApiError(code=code, message=message, details=details),
        )
