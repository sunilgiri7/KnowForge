from fastapi import Request
from fastapi.responses import JSONResponse


class KnowForgeError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "knowforge_error"):
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)


async def knowforge_error_handler(_: Request, exc: KnowForgeError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
