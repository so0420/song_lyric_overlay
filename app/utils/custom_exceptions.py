from fastapi import Request
from fastapi.responses import JSONResponse, HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.utils.templates import templates
from app.utils.log import logger

class CustomHTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


# Exception Handlers

async def custom_http_exception_handler(request: Request, exc: CustomHTTPException):
    if exc.status_code >= 500:
        logger.error(
            f"HTTP {exc.status_code}: {request.method} {request.url.path} - {exc.detail}"
        )
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    template_name = "error_pages/error.html"
    if exc.status_code == 404:
        template_name = "error_pages/404.html"
    elif exc.status_code == 500:
        template_name = "error_pages/500.html"

    return templates.TemplateResponse(
        template_name,
        {"request": request, "status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code
    )

async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code >= 500:
        logger.error(
            f"HTTP {exc.status_code}: {request.method} {request.url.path} - {exc.detail}"
        )
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    template_name = "error_pages/error.html"
    if exc.status_code == 404:
        template_name = "error_pages/404.html"
    elif exc.status_code == 500:
        template_name = "error_pages/500.html"

    return templates.TemplateResponse(
        template_name,
        {"request": request, "status_code": exc.status_code, "detail": exc.detail},
        status_code=exc.status_code
    )

async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"Unhandled exception: {request.method} {request.url.path}",
        exc_info=exc,
    )
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
        )
    
    return templates.TemplateResponse(
        "error_pages/500.html", 
        {"request": request, "status_code": 500, "detail": str(exc)},
        status_code=500
    )