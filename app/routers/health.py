"""Health and root endpoints."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def root():
    """Root endpoint - redirects to admin or shows status."""
    return {
        "message": "ERA Assistant is running",
        "docs": "/docs",
        "admin": "/admin"
    }


@router.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {
        "status": "healthy",
        "service": "ERA Assistant"
    }