import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.routers import health, migrations, tenants

_HTML = Path(__file__).parent.parent / "static" / "index.html"

# ─── Logging ─────────────────────────────────────────────────────────────────
# Structured JSON logs are picked up by Cloud Logging automatically.
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format=(
        '{"time":"%(asctime)s","severity":"%(levelname)s",'
        '"name":"%(name)s","message":"%(message)s"}'
    ),
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ─── App ─────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("service=%s version=%s starting", settings.app_name, settings.app_version)
    yield
    logger.info("service=%s shutting down", settings.app_name)


app = FastAPI(
    title="DB Migration Service",
    description=(
        "Multi-tenant database migration service.\n\n"
        "Upload SQL migration files to a GCS bucket, then use this API to "
        "inspect pending migrations, run them across all tenants, or roll back."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(migrations.router)
app.include_router(tenants.router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def demo_ui():
    """Serves the demo dashboard. Open this URL in a browser."""
    return _HTML.read_text(encoding="utf-8")


# ─── Global error handler ────────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )
