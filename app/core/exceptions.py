class AppError(Exception):
    def __init__(self, message: str, status_code: int = 400, code: str = "app_error") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class NotFoundError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=404, code="not_found")


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=409, code="conflict")


class InvalidStateError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, status_code=422, code="invalid_state")


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized.") -> None:
        super().__init__(message=message, status_code=401, code="unauthorized")


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden.") -> None:
        super().__init__(message=message, status_code=403, code="forbidden")
