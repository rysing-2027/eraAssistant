"""Admin API endpoints for web management panel."""
from fastapi import APIRouter, HTTPException, Depends, Cookie, Response
from fastapi.security import HTTPBasic
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import secrets

from config.settings import get_settings
from app.models.record import Record, RecordStatus
from app.models.product_knowledge import ProductKnowledge
from app.models.evaluation_criteria import EvaluationCriteria
from app.models.email_template import EmailTemplate
from app.utils.database import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Simple session storage (in-memory, resets on server restart)
# For production, use Redis or database-backed sessions
_active_sessions: dict[str, dict] = {}


# ============================================================================
# Pydantic Models
# ============================================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class ProductKnowledgeCreate(BaseModel):
    product_line: str
    title: str
    content: str
    sort_order: int = 0
    is_active: bool = True


class ProductKnowledgeUpdate(BaseModel):
    product_line: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class EvaluationCriteriaCreate(BaseModel):
    section_name: str
    content: str
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class EvaluationCriteriaUpdate(BaseModel):
    section_name: Optional[str] = None
    content: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class EmailTemplateCreate(BaseModel):
    name: str
    content: str
    description: Optional[str] = None
    is_active: bool = True


class EmailTemplateUpdate(BaseModel):
    name: Optional[str] = None
    content: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


# ============================================================================
# Auth Dependencies
# ============================================================================

async def get_current_admin(
    session_id: Optional[str] = Cookie(default=None, alias="admin_session")
) -> dict:
    """Verify admin session from cookie."""
    if not session_id or session_id not in _active_sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = _active_sessions[session_id]

    # Check session expiry (24 hours)
    if session["expires_at"] < datetime.now():
        del _active_sessions[session_id]
        raise HTTPException(status_code=401, detail="Session expired")

    return {"username": session["username"]}


# ============================================================================
# Auth API
# ============================================================================

@router.post("/login")
async def login(request: LoginRequest, response: Response):
    """Admin login."""
    settings = get_settings()

    # Validate credentials
    if request.username != settings.admin_username or request.password != settings.admin_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not settings.admin_password or not settings.admin_secret_key:
        raise HTTPException(status_code=500, detail="Admin not configured")

    # Create session
    session_id = secrets.token_urlsafe(32)
    _active_sessions[session_id] = {
        "username": request.username,
        "expires_at": datetime.now() + timedelta(hours=24)
    }

    # Set cookie
    response.set_cookie(
        key="admin_session",
        value=session_id,
        httponly=True,
        max_age=86400,  # 24 hours
        samesite="lax"
    )

    return {"status": "success", "username": request.username}


@router.post("/logout")
async def logout(
    response: Response,
    session_id: Optional[str] = Cookie(default=None, alias="admin_session")
):
    """Admin logout."""
    if session_id and session_id in _active_sessions:
        del _active_sessions[session_id]

    response.delete_cookie(key="admin_session")
    return {"status": "success"}


@router.get("/me")
async def get_current_user(admin: dict = Depends(get_current_admin)):
    """Get current admin user info."""
    return {"username": admin["username"]}


# ============================================================================
# Record API (Read-only)
# ============================================================================

@router.get("/records")
async def list_records(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    admin: dict = Depends(get_current_admin)
):
    """List all records with pagination and optional status filter."""
    with get_db() as db:
        query = db.query(Record)

        if status:
            try:
                status_enum = RecordStatus(status)
                query = query.filter(Record.status == status_enum)
            except ValueError:
                pass  # Invalid status, ignore filter

        total = query.count()
        records = query.order_by(Record.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "records": [
                {
                    "id": r.id,
                    "feishu_record_id": r.feishu_record_id,
                    "employee_name": r.employee_name,
                    "employee_email": r.employee_email,
                    "status": r.status.value if r.status else None,
                    "file_name": r.file_name,
                    "final_score": r.final_score,
                    "error_message": r.error_message,
                    "retry_count": r.retry_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                    "email_sent_at": r.email_sent_at.isoformat() if r.email_sent_at else None
                }
                for r in records
            ]
        }


@router.get("/records/{record_id}")
async def get_record(record_id: int, admin: dict = Depends(get_current_admin)):
    """Get record detail."""
    with get_db() as db:
        record = db.query(Record).filter(Record.id == record_id).first()
        if not record:
            raise HTTPException(status_code=404, detail="Record not found")

        return {
            "id": record.id,
            "feishu_record_id": record.feishu_record_id,
            "employee_name": record.employee_name,
            "employee_email": record.employee_email,
            "status": record.status.value if record.status else None,
            "file_name": record.file_name,
            "raw_text": record.raw_text,
            "analysis_results": record.analysis_results,
            "final_score": record.final_score,
            "email_content": record.email_content,
            "error_message": record.error_message,
            "retry_count": record.retry_count,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "email_sent_at": record.email_sent_at.isoformat() if record.email_sent_at else None
        }


@router.get("/records/stats/summary")
async def get_records_stats(admin: dict = Depends(get_current_admin)):
    """Get record statistics by status."""
    with get_db() as db:
        stats = {}
        for status in RecordStatus:
            count = db.query(Record).filter(Record.status == status).count()
            stats[status.value] = count

        stats["total"] = db.query(Record).count()

        return stats


# ============================================================================
# Product Knowledge CRUD
# ============================================================================

@router.get("/product-knowledge")
async def list_product_knowledge(admin: dict = Depends(get_current_admin)):
    """List all product knowledge."""
    with get_db() as db:
        items = db.query(ProductKnowledge).order_by(
            ProductKnowledge.product_line,
            ProductKnowledge.sort_order
        ).all()

        return [
            {
                "id": item.id,
                "product_line": item.product_line,
                "title": item.title,
                "content": item.content,
                "sort_order": item.sort_order,
                "is_active": item.is_active,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None
            }
            for item in items
        ]


@router.post("/product-knowledge")
async def create_product_knowledge(
    data: ProductKnowledgeCreate,
    admin: dict = Depends(get_current_admin)
):
    """Create product knowledge."""
    with get_db() as db:
        item = ProductKnowledge(
            product_line=data.product_line,
            title=data.title,
            content=data.content,
            sort_order=data.sort_order,
            is_active=data.is_active
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        return {"id": item.id, "status": "created"}


@router.put("/product-knowledge/{item_id}")
async def update_product_knowledge(
    item_id: int,
    data: ProductKnowledgeUpdate,
    admin: dict = Depends(get_current_admin)
):
    """Update product knowledge."""
    with get_db() as db:
        item = db.query(ProductKnowledge).filter(ProductKnowledge.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Not found")

        if data.product_line is not None:
            item.product_line = data.product_line
        if data.title is not None:
            item.title = data.title
        if data.content is not None:
            item.content = data.content
        if data.sort_order is not None:
            item.sort_order = data.sort_order
        if data.is_active is not None:
            item.is_active = data.is_active

        db.commit()
        return {"status": "updated"}


@router.delete("/product-knowledge/{item_id}")
async def delete_product_knowledge(
    item_id: int,
    admin: dict = Depends(get_current_admin)
):
    """Delete product knowledge."""
    with get_db() as db:
        item = db.query(ProductKnowledge).filter(ProductKnowledge.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Not found")

        db.delete(item)
        db.commit()
        return {"status": "deleted"}


# ============================================================================
# Evaluation Criteria CRUD
# ============================================================================

@router.get("/evaluation-criteria")
async def list_evaluation_criteria(admin: dict = Depends(get_current_admin)):
    """List all evaluation criteria."""
    with get_db() as db:
        items = db.query(EvaluationCriteria).order_by(EvaluationCriteria.sort_order).all()

        return [
            {
                "id": item.id,
                "section_name": item.section_name,
                "content": item.content,
                "description": item.description,
                "sort_order": item.sort_order,
                "is_active": item.is_active,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None
            }
            for item in items
        ]


@router.post("/evaluation-criteria")
async def create_evaluation_criteria(
    data: EvaluationCriteriaCreate,
    admin: dict = Depends(get_current_admin)
):
    """Create evaluation criteria."""
    with get_db() as db:
        item = EvaluationCriteria(
            section_name=data.section_name,
            content=data.content,
            description=data.description,
            sort_order=data.sort_order,
            is_active=data.is_active
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        return {"id": item.id, "status": "created"}


@router.put("/evaluation-criteria/{item_id}")
async def update_evaluation_criteria(
    item_id: int,
    data: EvaluationCriteriaUpdate,
    admin: dict = Depends(get_current_admin)
):
    """Update evaluation criteria."""
    with get_db() as db:
        item = db.query(EvaluationCriteria).filter(EvaluationCriteria.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Not found")

        if data.section_name is not None:
            item.section_name = data.section_name
        if data.content is not None:
            item.content = data.content
        if data.description is not None:
            item.description = data.description
        if data.sort_order is not None:
            item.sort_order = data.sort_order
        if data.is_active is not None:
            item.is_active = data.is_active

        db.commit()
        return {"status": "updated"}


@router.delete("/evaluation-criteria/{item_id}")
async def delete_evaluation_criteria(
    item_id: int,
    admin: dict = Depends(get_current_admin)
):
    """Delete evaluation criteria."""
    with get_db() as db:
        item = db.query(EvaluationCriteria).filter(EvaluationCriteria.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Not found")

        db.delete(item)
        db.commit()
        return {"status": "deleted"}


# ============================================================================
# Email Template CRUD
# ============================================================================

@router.get("/email-templates")
async def list_email_templates(admin: dict = Depends(get_current_admin)):
    """List all email templates."""
    with get_db() as db:
        items = db.query(EmailTemplate).all()

        return [
            {
                "id": item.id,
                "name": item.name,
                "content": item.content,
                "description": item.description,
                "is_active": item.is_active,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None
            }
            for item in items
        ]


@router.post("/email-templates")
async def create_email_template(
    data: EmailTemplateCreate,
    admin: dict = Depends(get_current_admin)
):
    """Create email template."""
    with get_db() as db:
        # If setting as active, deactivate others
        if data.is_active:
            db.query(EmailTemplate).update({EmailTemplate.is_active: False})

        item = EmailTemplate(
            name=data.name,
            content=data.content,
            description=data.description,
            is_active=data.is_active
        )
        db.add(item)
        db.commit()
        db.refresh(item)

        return {"id": item.id, "status": "created"}


@router.put("/email-templates/{item_id}")
async def update_email_template(
    item_id: int,
    data: EmailTemplateUpdate,
    admin: dict = Depends(get_current_admin)
):
    """Update email template."""
    with get_db() as db:
        item = db.query(EmailTemplate).filter(EmailTemplate.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Not found")

        # If setting as active, deactivate others
        if data.is_active:
            db.query(EmailTemplate).filter(EmailTemplate.id != item_id).update(
                {EmailTemplate.is_active: False}
            )

        if data.name is not None:
            item.name = data.name
        if data.content is not None:
            item.content = data.content
        if data.description is not None:
            item.description = data.description
        if data.is_active is not None:
            item.is_active = data.is_active

        db.commit()
        return {"status": "updated"}


@router.delete("/email-templates/{item_id}")
async def delete_email_template(
    item_id: int,
    admin: dict = Depends(get_current_admin)
):
    """Delete email template."""
    with get_db() as db:
        item = db.query(EmailTemplate).filter(EmailTemplate.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Not found")

        db.delete(item)
        db.commit()
        return {"status": "deleted"}