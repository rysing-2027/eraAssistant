"""Public report viewing endpoint."""
from fastapi import APIRouter, HTTPException
from app.models.record import Record, RecordStatus
from app.utils.database import get_db

router = APIRouter(tags=["report"])

VIEWABLE_STATUSES = {RecordStatus.SCORED, RecordStatus.EMAILING, RecordStatus.DONE}

SENSITIVE_FIELDS = {"employee_email", "raw_text", "error_message", "email_content"}


@router.get("/api/report/{view_token}")
async def get_report(view_token: str):
    """Return report data for a given view_token, no auth required.

    - Only records with status Scored/Emailing/Done are returned.
    - Sensitive fields are excluded from the response.
    - Only successful judge results are included in analysis_results.
    - Returns 404 for invalid tokens or records not yet ready.
    """
    with get_db() as db:
        record = db.query(Record).filter(Record.view_token == view_token).first()

        if not record or record.status not in VIEWABLE_STATUSES:
            raise HTTPException(status_code=404, detail="Report not found")

        # Filter to only successful judge results
        analysis_results = [
            j for j in (record.analysis_results or []) if j.get("success") is True
        ]

        return {
            "employee_name": record.employee_name,
            "feishu_doc_url": record.feishu_doc_url,
            "final_score": record.final_score,
            "analysis_results": analysis_results,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
