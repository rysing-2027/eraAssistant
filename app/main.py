"""ERA Assistant - FastAPI Application Entry Point."""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pathlib import Path

from app.utils.database import init_db
from config.settings import get_settings
from app.services.feishu_service import FeishuService
from app.services.report_processing_service import ReportProcessingService
from app.routers import health_router, test_router, webhook_router, admin_router

# Get project root directory
PROJECT_ROOT = Path(__file__).parent.parent
ADMIN_DIST = PROJECT_ROOT / "admin" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup: Create database tables
    print("🚀 Starting ERA Assistant...")

    # Load and validate settings
    settings = get_settings()
    print(f"✅ Config loaded: Feishu app_id={settings.feishu_app_id[:10]}...")

    init_db()
    print("✅ Database initialized")

    # Recover and process stuck records from previous crash
    if settings.feishu_app_id and settings.feishu_app_secret:
        feishu_service = FeishuService(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret
        )
        processing_service = ReportProcessingService(feishu_service=feishu_service)

        # Step 1: Recover stuck records (reset status)
        recovery_result = processing_service.recover_stuck_records()
        if recovery_result["recovered"] > 0:
            print(f"🔄 Recovered {recovery_result['recovered']} stuck records")

            # Step 2: Process recovered records
            process_result = await processing_service.process_stuck_records(
                base_token=settings.feishu_base_token,
                table_id=settings.feishu_table_id
            )
            if process_result["total"] > 0:
                print(f"✅ Processed {process_result['success']}/{process_result['total']} recovered records")
    else:
        print("⚠️ Feishu credentials not configured, skipping recovery")

    yield

    # Shutdown: Cleanup
    print("🛑 Shutting down ERA Assistant...")


# Create FastAPI app
app = FastAPI(
    title="ERA Assistant",
    description="Employee Report Analysis - AI-powered report evaluation system",
    version="0.1.0",
    lifespan=lifespan
)

# Static files (CSS, JS) - only if directory exists
static_dir = PROJECT_ROOT / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Templates (HTML files)
templates_dir = PROJECT_ROOT / "templates"
if templates_dir.exists():
    templates = Jinja2Templates(directory=templates_dir)

# Include routers
app.include_router(health_router)
app.include_router(test_router)
app.include_router(webhook_router)
app.include_router(admin_router)


# Admin SPA - serve built React app
@app.get("/login", response_class=FileResponse)
@app.get("/records", response_class=FileResponse)
@app.get("/product-knowledge", response_class=FileResponse)
@app.get("/evaluation-criteria", response_class=FileResponse)
@app.get("/email-templates", response_class=FileResponse)
async def serve_admin_spa():
    """Serve admin SPA for client-side routing."""
    index_file = ADMIN_DIST / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return FileResponse(PROJECT_ROOT / "static" / "admin-not-built.html")


# Mount admin static assets if built
admin_assets = ADMIN_DIST / "assets"
if admin_assets.exists():
    app.mount("/assets", StaticFiles(directory=admin_assets), name="admin-assets")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)