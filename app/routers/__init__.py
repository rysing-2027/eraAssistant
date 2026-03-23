"""ERA Assistant Routers."""
from app.routers.health import router as health_router
from app.routers.test import router as test_router
from app.routers.webhook import router as webhook_router
from app.routers.admin import router as admin_router
from app.routers.report import router as report_router

__all__ = ["health_router", "test_router", "webhook_router", "admin_router", "report_router"]