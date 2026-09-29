import time
import uuid

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.config import settings
from apps.api.routes.analysis import router as analysis_router
from apps.api.routes.evidence_integrity import router as evidence_integrity_router
from apps.api.routes.findings import router as findings_router
from apps.api.routes.reports import router as reports_router
from apps.api.routes.review import router as review_router
from apps.api.routes.semantic_evidence import router as semantic_evidence_router
from apps.api.routes.submissions import router as submissions_router
from apps.api.routes.supervisory import router as supervisory_router

app = FastAPI(
    title="SAT-SA Offline API",
    description="Supervisory Analytics Tool for SOC Assessment - Offline Evidence Intake API",
    version="0.1.0",
)

# Loopback CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_and_timing_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    start_time = time.perf_counter()
    response: Response = await call_next(request)
    process_time = time.perf_counter() - start_time

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    return response


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid.uuid4()))


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Determine error code name
    code_map = {
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        422: "UNPROCESSABLE_ENTITY",
    }
    code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": code,
            "message": str(exc.detail),
            "details": None,
            "request_id": get_request_id(request),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    from fastapi.encoders import jsonable_encoder

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": "SCHEMA_VALIDATION_FAILED",
            "message": "Validation failed for request input",
            "details": jsonable_encoder(exc.errors()),
            "request_id": get_request_id(request),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An internal server error occurred",
            "details": str(exc) if settings.environment == "development" else None,
            "request_id": get_request_id(request),
        },
    )


app.include_router(submissions_router, prefix="/api/v1")
app.include_router(analysis_router, prefix="/api/v1")
app.include_router(findings_router, prefix="/api/v1")
app.include_router(semantic_evidence_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(evidence_integrity_router, prefix="/api/v1/evidence-integrity")
app.include_router(supervisory_router, prefix="/api/v1")


@app.get("/api/v1/health")
def health_check(request: Request):
    return {
        "status": "healthy",
        "runtime": "offline",
        "request_id": get_request_id(request),
    }
