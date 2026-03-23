"""Test endpoints for Feishu and pipeline."""
from fastapi import APIRouter, HTTPException

from config.settings import get_settings
from app.services.feishu_service import FeishuService
from app.services.report_processing_service import get_processing_service
from app.agents.analysis_agent import get_analysis_agent
from app.models.record import Record, RecordStatus
from app.utils.database import get_db

router = APIRouter(prefix="/test", tags=["test"])


@router.get("/feishu")
async def test_feishu_connection():
    """Test Feishu API connection and list pending records."""
    settings = get_settings()

    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise HTTPException(status_code=400, detail="Feishu credentials not configured")

    try:
        service = FeishuService(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret
        )

        # Try to get records with "Submitted" status
        records = await service.get_base_records(
            base_token=settings.feishu_base_token,
            table_id=settings.feishu_table_id,
            filter_status="Submitted"
        )

        return {
            "status": "success",
            "message": f"Connected to Feishu! Found {len(records)} records with 'Submitted' status",
            "record_count": len(records),
            "sample_records": [
                {
                    "record_id": r.get("record_id"),
                    "all_keys": list(r.keys()),
                    "fields": {k: v for k, v in r.get("fields", {}).items() if k != "附件"}
                }
                for r in records[:3]  # Show first 3 records
            ]
        }

    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@router.get("/pipeline")
async def test_full_pipeline():
    """Test the complete pipeline: Feishu → Excel → Database."""
    settings = get_settings()

    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise HTTPException(status_code=400, detail="Feishu credentials not configured")

    try:
        processing_service = get_processing_service()

        result = await processing_service.run_full_pipeline(
            base_token=settings.feishu_base_token,
            table_id=settings.feishu_table_id
        )

        return {
            "status": "success",
            **result
        }

    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@router.get("/retry")
async def retry_failed_records():
    """Retry processing failed records."""
    settings = get_settings()

    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise HTTPException(status_code=400, detail="Feishu credentials not configured")

    try:
        processing_service = get_processing_service()

        result = await processing_service.retry_failed_records()

        return {
            "status": "success",
            **result
        }

    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@router.get("/analysis")
async def test_analysis():
    """Test the analysis agent on records with READY_FOR_ANALYSIS status."""
    settings = get_settings()

    # Check API keys
    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured")

    try:
        with get_db() as db:
            # Find a record ready for analysis
            record = db.query(Record).filter(
                Record.status == RecordStatus.READY_FOR_ANALYSIS
            ).first()

            if not record:
                return {
                    "status": "error",
                    "message": "No records with READY_FOR_ANALYSIS status found. Run /test/pipeline first."
                }

            # Run analysis
            agent = get_analysis_agent()
            result = await agent.analyze(
                record_id=record.id,
                employee_name=record.employee_name,
                raw_text=record.raw_text or ""
            )

            return {
                "status": "success",
                "record_id": record.id,
                "employee_name": record.employee_name,
                "judge_results": {
                    "judge_1": result.get("judge_1_result"),
                    "judge_2": result.get("judge_2_result"),
                    "judge_3": result.get("judge_3_result")
                },
                "final_score": result.get("final_score"),
                "error": result.get("error")
            }

    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@router.get("/workflow")
async def test_complete_workflow():
    """Test the complete workflow: fetch → parse → analyze → email.

    使用与 webhook 相同的并发逻辑。
    """
    import asyncio

    settings = get_settings()

    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise HTTPException(status_code=400, detail="Feishu credentials not configured")

    try:
        processing_service = get_processing_service()

        # Step 1: Fetch and parse (sync)
        pipeline_result = await processing_service.run_full_pipeline(
            base_token=settings.feishu_base_token,
            table_id=settings.feishu_table_id
        )

        record_ids = pipeline_result.get("record_ids", [])
        if not record_ids:
            return {
                "status": "success",
                "pipeline": pipeline_result,
                "message": "No new records to process"
            }

        # Step 2: analysis + email（并发由 service 内部 semaphore 控制）
        results = await asyncio.gather(
            *[processing_service.analyze_and_email(rid) for rid in record_ids],
            return_exceptions=True
        )

        success_count = sum(1 for r in results if r is True)

        return {
            "status": "success",
            "pipeline": pipeline_result,
            "analysis": {
                "total": len(record_ids),
                "success": success_count,
                "failed": len(record_ids) - success_count
            }
        }

    except Exception as e:
        import traceback
        error_detail = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        raise HTTPException(status_code=500, detail=error_detail)


@router.get("/continue-workflow")
async def continue_stalled_workflow():
    """Continue workflow for records stuck at READY_FOR_ANALYSIS.

    处理所有处于 READY_FOR_ANALYSIS 状态的记录：分析 → 发邮件
    """
    import asyncio

    processing_service = get_processing_service()

    with get_db() as db:
        records = db.query(Record).filter(
            Record.status == RecordStatus.READY_FOR_ANALYSIS
        ).all()

        if not records:
            return {
                "status": "success",
                "message": "No records with READY_FOR_ANALYSIS status",
                "processed": 0
            }

        record_ids = [r.id for r in records]

    # 并发由 service 内部 semaphore 控制
    results = await asyncio.gather(
        *[processing_service.analyze_and_email(rid) for rid in record_ids],
        return_exceptions=True
    )

    success_count = sum(1 for r in results if r is True)

    return {
        "status": "success",
        "total_records": len(record_ids),
        "analysis_success": success_count,
        "failed": len(record_ids) - success_count
    }