"""Webhook endpoints for Feishu automation."""
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException, Header, BackgroundTasks

from config.settings import get_settings
from app.services.feishu_service import FeishuService
from app.services.report_processing_service import ReportProcessingService

router = APIRouter(prefix="/api/webhook", tags=["webhook"])


async def process_records_task():
    """后台任务：完整处理流程（下载 → 解析 → 分析 → 发邮件）"""
    settings = get_settings()

    try:
        feishu_service = FeishuService(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret
        )

        processing_service = ReportProcessingService(feishu_service=feishu_service)

        # Step 1: 获取记录 + 下载 + 解析
        result = await processing_service.run_full_pipeline(
            base_token=settings.feishu_base_token,
            table_id=settings.feishu_table_id
        )

        record_ids = result.get("record_ids", [])
        if not record_ids:
            print("📭 No records to process")
            return

        print(f"📬 Processing {len(record_ids)} record(s) in background...")

        # Step 2: 并行分析 + 发邮件 (最多3个并发)
        semaphore = asyncio.Semaphore(3)

        async def process_one(record_id: int):
            async with semaphore:
                success = await processing_service.run_analysis_for_record(record_id)
                if success:
                    await processing_service.send_email_for_record(record_id)
                return success

        results = await asyncio.gather(*[process_one(rid) for rid in record_ids])
        print(f"✅ Background task complete: {sum(results)}/{len(record_ids)} successful")

    except Exception as e:
        print(f"❌ Background task failed: {e}")


@router.post("/trigger")
async def feishu_automation_trigger(
    background_tasks: BackgroundTasks,
    x_webhook_token: str = Header(default="", alias="X-Webhook-Token")
):
    """Triggered by Feishu Base automation when new record is submitted.

    飞书多维表格自动化配置:
    - 触发条件: 当「状态」字段 = "已提交"
    - 动作: 发送 HTTP POST 请求到此端点
    - Header: X-Webhook-Token: <你的token>

    流程:
    1. 立即返回响应 (避免飞书超时)
    2. 后台执行: 获取数据 → 下载解析 → AI分析 → 发送邮件

    Returns:
        {"status": "accepted"} immediately
    """
    print(f"\n{'='*50}")
    print(f"🔔 Webhook triggered at {datetime.now()}")
    print(f"   Token received: {x_webhook_token[:10]}..." if len(x_webhook_token) > 10 else f"   Token received: {x_webhook_token}")
    print(f"{'='*50}\n")

    settings = get_settings()

    # Verify webhook token (if configured)
    if settings.webhook_token and x_webhook_token != settings.webhook_token:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise HTTPException(status_code=400, detail="Feishu credentials not configured")

    # 注册后台任务，立即返回
    background_tasks.add_task(process_records_task)

    return {
        "status": "accepted",
        "message": "Processing started in background"
    }