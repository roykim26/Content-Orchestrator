from secrets import compare_digest

from fastapi import Header

from app.core.config import settings
from app.core.exceptions import UnauthorizedError


def require_publisher_auth(authorization: str | None = Header(default=None)) -> None:
    expected_api_key = settings.publisher_api_key
    if not expected_api_key:
        return

    if not authorization:
        raise UnauthorizedError("Missing Authorization header.")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedError("Invalid Authorization header format.")

    if not compare_digest(token, expected_api_key):
        raise UnauthorizedError("Invalid publisher API key.")
