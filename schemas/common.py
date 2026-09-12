from pydantic import BaseModel, Field


class EmptyConfig(BaseModel):
    # Actual JSON: {}.
    pass


class ApiErrorResponse(BaseModel):
    success: int | bool = Field(default=0)
    error: str
    error_reason: str | None = None


class SuccessResponse(BaseModel):
    success: int | bool = Field(default=1)


class ErrorResponses:
    INVALID_JSON = {400: {"model": ApiErrorResponse, "description": "Invalid JSON body"}}
    INTERNAL_ERROR = {500: {"model": ApiErrorResponse, "description": "Internal error"}}
