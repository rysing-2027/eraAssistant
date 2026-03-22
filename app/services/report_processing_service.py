"""Report Processing Service for ERA Assistant.

This module orchestrates the complete workflow:
1. Fetch records from Feishu Base
2. Download and parse Excel files
3. Run AI analysis (3 judges)
4. Send evaluation emails
"""
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.services.feishu_service import FeishuService
from app.services.excel_service import ExcelProcessingService
from app.services.email_service import EmailService
from app.agents.analysis_agent import get_analysis_agent
from app.models.record import Record, RecordStatus
from app.utils.database import get_db
from config.settings import get_settings


def log_step(step: str, detail: str = "", emoji: str = "▸"):
    """Print a formatted log step."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    if detail:
        print(f"[{timestamp}] {emoji} {step}: {detail}")
    else:
        print(f"[{timestamp}] {emoji} {step}")


class ReportProcessingService:
    """Orchestrates the report processing workflow."""

    def __init__(
        self,
        feishu_service: Optional[FeishuService] = None,
        max_concurrent: int = 5
    ):
        self.feishu_service = feishu_service
        self.excel_service = ExcelProcessingService()
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def recover_stuck_records(
        self,
        timeout_minutes: int = 10
    ) -> Dict[str, Any]:
        """Recover records stuck in transient states.

        This should be called ONCE at program startup, not during runtime.
        It resets records that were interrupted by a previous crash.

        Transient states (can be safely retried):
        - PROCESSING → SUBMITTED (重新下载解析)
        - ANALYZING → READY_FOR_ANALYSIS (重新分析)
        - EMAILING → SCORED (重新发邮件)

        Args:
            timeout_minutes: Records in transient states longer than this are reset

        Returns:
            Summary of recovered records
        """
        with get_db() as db:
            cutoff_time = datetime.now() - timedelta(minutes=timeout_minutes)

            # Find all stuck records in transient states
            transient_states = [
                RecordStatus.PROCESSING,
                RecordStatus.ANALYZING,
                RecordStatus.EMAILING
            ]

            stuck_records = db.query(Record).filter(
                Record.status.in_(transient_states),
                Record.updated_at < cutoff_time
            ).all()

            if not stuck_records:
                return {"recovered": 0, "message": "No stuck records"}

            # Reset each record to appropriate state
            for record in stuck_records:
                old_status = record.status

                if record.status == RecordStatus.PROCESSING:
                    record.status = RecordStatus.SUBMITTED
                elif record.status == RecordStatus.ANALYZING:
                    record.status = RecordStatus.READY_FOR_ANALYSIS
                elif record.status == RecordStatus.EMAILING:
                    record.status = RecordStatus.SCORED

                record.error_message = f"Recovered from stuck {old_status.value} state"
                record.retry_count += 1

            db.commit()

        return {
            "recovered": len(stuck_records),
            "record_ids": [r.id for r in stuck_records],
            "details": [
                {"id": r.id, "from": r.error_message.split("stuck ")[1].split(" state")[0], "name": r.employee_name}
                for r in stuck_records
            ]
        }

    async def process_stuck_records(self, base_token: str = None, table_id: str = None) -> Dict[str, Any]:
        """Process records that were stuck and recovered.

        Called at startup after recover_stuck_records().
        Handles records in these states:
        - SUBMITTED: Download and parse (requires FeishuService)
        - READY_FOR_ANALYSIS: Analyze and send email
        - SCORED: Send email

        Args:
            base_token: Feishu Base token (required if SUBMITTED records exist)
            table_id: Feishu Table ID (required if SUBMITTED records exist)

        Returns:
            Summary of processed records
        """
        import asyncio

        results = {
            "submitted": {"total": 0, "success": 0},
            "ready_for_analysis": {"total": 0, "success": 0},
            "scored": {"total": 0, "success": 0}
        }

        # 1. 处理 READY_FOR_ANALYSIS（分析 + 发邮件）
        with get_db() as db:
            ready_records = db.query(Record).filter(
                Record.status == RecordStatus.READY_FOR_ANALYSIS
            ).all()
            results["ready_for_analysis"]["total"] = len(ready_records)

        if ready_records:
            log_step("Stuck Recovery", f"Processing {len(ready_records)} READY_FOR_ANALYSIS records...", "🔄")
            semaphore = asyncio.Semaphore(3)

            async def process_ready(record_id: int):
                async with semaphore:
                    success = await self.run_analysis_for_record(record_id)
                    if success:
                        await self.send_email_for_record(record_id)
                    return success

            ready_results = await asyncio.gather(
                *[process_ready(r.id) for r in ready_records],
                return_exceptions=True
            )
            results["ready_for_analysis"]["success"] = sum(1 for r in ready_results if r is True)

        # 2. 处理 SCORED（发邮件）
        with get_db() as db:
            scored_records = db.query(Record).filter(
                Record.status == RecordStatus.SCORED
            ).all()
            results["scored"]["total"] = len(scored_records)

        if scored_records:
            log_step("Stuck Recovery", f"Processing {len(scored_records)} SCORED records...", "🔄")

            async def process_scored(record_id: int):
                return await self.send_email_for_record(record_id)

            scored_results = await asyncio.gather(
                *[process_scored(r.id) for r in scored_records],
                return_exceptions=True
            )
            results["scored"]["success"] = sum(1 for r in scored_results if r is True)

        # 3. 处理 SUBMITTED（下载 + 解析 + 分析 + 发邮件，需要 FeishuService）
        if self.feishu_service and base_token and table_id:
            with get_db() as db:
                submitted_records = db.query(Record).filter(
                    Record.status == RecordStatus.SUBMITTED
                ).all()
                results["submitted"]["total"] = len(submitted_records)

            if submitted_records:
                log_step("Stuck Recovery", f"Processing {len(submitted_records)} SUBMITTED records...", "🔄")

                # 3.1 下载 + 解析（并行，最多5个）
                parse_results = await asyncio.gather(
                    *[self._download_and_parse_record(r.id) for r in submitted_records],
                    return_exceptions=True
                )

                # 3.2 分析 + 发邮件（并行，最多3个）
                with get_db() as db:
                    ready_ids = [r.id for r in submitted_records]
                    ready_after_submitted = db.query(Record).filter(
                        Record.status == RecordStatus.READY_FOR_ANALYSIS,
                        Record.id.in_(ready_ids)
                    ).all()

                if ready_after_submitted:
                    semaphore = asyncio.Semaphore(3)

                    async def process_submitted(record_id: int):
                        async with semaphore:
                            success = await self.run_analysis_for_record(record_id)
                            if success:
                                await self.send_email_for_record(record_id)
                            return success

                    submitted_results = await asyncio.gather(
                        *[process_submitted(r.id) for r in ready_after_submitted],
                        return_exceptions=True
                    )
                    results["submitted"]["success"] = sum(1 for r in submitted_results if r is True)

        # 汇总结果
        total = sum(r["total"] for r in results.values())
        success = sum(r["success"] for r in results.values())

        if total > 0:
            log_step("Stuck Recovery Complete", f"{success}/{total} records processed", "✅")
        else:
            log_step("Stuck Recovery", "No stuck records to process", "ℹ️")

        return {
            "total": total,
            "success": success,
            "details": results
        }

    async def _download_with_limit(
        self,
        file_token: str,
        filename: str
    ) -> Dict[str, Any]:
        """Download single file with concurrency limit."""
        if not self.feishu_service:
            return {"filename": filename, "file_content": None, "error": "FeishuService not configured"}

        async with self._semaphore:
            try:
                content = await self.feishu_service.download_file(file_token)
                if not content:
                    error_msg = "Empty response from Feishu"
                    log_step("Download failed", f"{filename}: {error_msg}", "❌")
                    return {"filename": filename, "file_content": None, "error": error_msg}
                log_step("Downloaded", filename, "✅")
                return {"filename": filename, "file_content": content, "error": None}
            except httpx.HTTPStatusError as e:
                error_msg = f"HTTP {e.response.status_code}: {e.response.text[:200] if e.response.text else 'No details'}"
                log_step("Download failed", f"{filename}: {error_msg}", "❌")
                return {"filename": filename, "file_content": None, "error": error_msg}
            except Exception as e:
                error_msg = str(e) or f"Unknown error: {type(e).__name__}"
                log_step("Download failed", f"{filename}: {error_msg}", "❌")
                return {"filename": filename, "file_content": None, "error": error_msg}

    async def _download_and_parse_record(self, record_id: int) -> bool:
        """Download and parse Excel for a single SUBMITTED record.

        Args:
            record_id: The ID of the record to process

        Returns:
            True if successfully parsed (status → READY_FOR_ANALYSIS)
            False if failed (status → FAILED)
        """
        with get_db() as db:
            record = db.query(Record).filter(
                Record.id == record_id,
                Record.status == RecordStatus.SUBMITTED
            ).first()

            if not record:
                return False

            try:
                record.status = RecordStatus.PROCESSING
                db.commit()

                # Download file
                download_result = await self._download_with_limit(
                    record.file_token, record.file_name
                )
                if download_result["error"]:
                    record.status = RecordStatus.FAILED
                    record.error_message = f"Download failed: {download_result['error']}"
                    db.commit()
                    return False

                # Parse Excel
                excel_result = self.excel_service.parse_excel(
                    download_result["file_content"],
                    download_result["filename"]
                )
                record.raw_text = excel_result.raw_text
                record.sheet_name = excel_result.sheet_name
                record.total_rows = excel_result.total_rows
                record.total_cols = excel_result.total_cols

                if excel_result.success:
                    record.status = RecordStatus.READY_FOR_ANALYSIS
                    db.commit()
                    return True
                else:
                    record.status = RecordStatus.FAILED
                    record.error_message = excel_result.error
                    db.commit()
                    return False

            except Exception as e:
                record.status = RecordStatus.FAILED
                record.error_message = f"Processing error: {str(e)}"
                db.commit()
                return False

    async def run_full_pipeline(
        self,
        base_token: str,
        table_id: str
    ) -> Dict[str, Any]:
        """Run the complete pipeline: fetch → download → parse → store.

        This is the main entry point.

        Args:
            base_token: Feishu Base token
            table_id: Feishu Table ID

        Returns:
            Summary of what was done
        """
        if not self.feishu_service:
            return {"new_records": 0, "processed": 0, "error": "FeishuService not configured"}

        with get_db() as db:
            # Step 1: Fetch from Feishu
            log_step("Step 1", "Fetching records from Feishu...", "📥")
            feishu_records = await self.feishu_service.get_base_records(
                base_token=base_token,
                table_id=table_id,
                filter_status="Submitted"
            )

            if not feishu_records:
                log_step("Result", "No records found", "⚠️")
                return {"new_records": 0, "processed": 0, "message": "No records found"}

            log_step("Fetched", f"{len(feishu_records)} record(s) from Feishu", "📥")

            # Step 2: Filter out already processed records
            new_records = []
            for fr in feishu_records:
                feishu_id = fr.get("record_id") or fr.get("id")  # 尝试两种字段名
                existing = db.query(Record).filter(
                    Record.feishu_record_id == feishu_id
                ).first()

                if existing:
                    continue  # Skip existing

                fields = fr.get("fields", {})
                file_list = fields.get("file", [])
                if not file_list:
                    continue  # Skip records without files

                file_info = file_list[0]

                # 飞书多维表字段可能是复杂对象，需要提取 text
                name_field = fields.get("name", "")
                email_field = fields.get("email", "")

                # 提取文本值
                if isinstance(name_field, list) and name_field:
                    name_field = name_field[0].get("text", "")
                if isinstance(email_field, list) and email_field:
                    email_field = email_field[0].get("text", email_field[0].get("link", ""))

                new_records.append({
                    "feishu_id": feishu_id,
                    "employee_name": name_field,
                    "employee_email": email_field,
                    "file_token": file_info.get("file_token", ""),
                    "file_name": file_info.get("name", "")
                })

            if not new_records:
                log_step("Result", "All records already processed", "✅")
                return {"new_records": 0, "processed": 0, "message": "All records already processed"}

            log_step("New records", f"{len(new_records)} to process", "📋")

            # Step 3: Create records with SUBMITTED status first
            log_step("Step 2", "Creating database records...", "💾")
            records = []
            for record_data in new_records:
                record = Record(
                    feishu_record_id=record_data["feishu_id"],
                    employee_name=record_data["employee_name"],
                    employee_email=record_data["employee_email"],
                    file_token=record_data["file_token"],
                    file_name=record_data["file_name"],
                    status=RecordStatus.SUBMITTED
                )
                db.add(record)
                records.append(record)
            db.commit()
            log_step("Created", f"{len(records)} database record(s)", "💾")

            # Step 4: Update to PROCESSING
            for record in records:
                record.status = RecordStatus.PROCESSING
            db.commit()

            # Step 5: Download files (parallel)
            log_step("Step 3", f"Downloading {len(records)} file(s)...", "📥")
            download_tasks = [
                self._download_with_limit(r.file_token, r.file_name)
                for r in records
            ]
            download_results = await asyncio.gather(*download_tasks)

            # Step 6: Parse Excel files
            log_step("Step 4", "Parsing Excel files...", "📊")
            parse_items = [
                {"file_content": r["file_content"], "filename": r["filename"]}
                for r in download_results
                if r["file_content"]
            ]
            excel_results = self.excel_service.parse_batch(parse_items)

            # Step 7: Update with final status
            log_step("Step 5", "Updating final status...", "🔄")
            success_count = 0
            parse_idx = 0
            for i, record in enumerate(records):
                download_result = download_results[i]

                # Download failed (check file_content, not error string)
                if not download_result["file_content"]:
                    record.status = RecordStatus.FAILED
                    record.error_message = f"Download failed: {download_result.get('error', 'Unknown error')}"
                    log_step("Failed", f"{record.employee_name}: download error", "❌")
                    continue

                # Parse result
                excel_result = excel_results.results[parse_idx]
                parse_idx += 1

                record.sheet_name = excel_result.sheet_name
                record.total_rows = excel_result.total_rows
                record.total_cols = excel_result.total_cols
                record.raw_text = excel_result.raw_text

                if excel_result.success:
                    record.status = RecordStatus.READY_FOR_ANALYSIS
                    success_count += 1
                    log_step("Ready", f"{record.employee_name} ({excel_result.total_rows} rows)", "✅")
                else:
                    record.status = RecordStatus.FAILED
                    record.error_message = excel_result.error
                    log_step("Failed", f"{record.employee_name}: parse error", "❌")

            db.commit()

            # 在 session 内提取 ID 列表
            record_ids = [r.id for r in records]

        log_step("Pipeline complete", f"{success_count} success, {len(new_records) - success_count} failed", "🎉")
        return {
            "new_records": len(new_records),
            "success": success_count,
            "failed": len(new_records) - success_count,
            "record_ids": record_ids
        }

    async def retry_failed_records(self) -> Dict[str, Any]:
        """Retry processing failed records.

        Returns:
            Summary of retry results
        """
        if not self.feishu_service:
            return {"retried": 0, "error": "FeishuService not configured"}

        with get_db() as db:
            failed_records = db.query(Record).filter(
                Record.status == RecordStatus.FAILED
            ).all()

            if not failed_records:
                return {"retried": 0, "message": "No failed records"}

            # Update to PROCESSING
            for record in failed_records:
                record.status = RecordStatus.PROCESSING
            db.commit()

            # Download files (parallel)
            download_tasks = [
                self._download_with_limit(r.file_token, r.file_name)
                for r in failed_records
            ]
            download_results = await asyncio.gather(*download_tasks)

            # Parse Excel files
            parse_items = [
                {"file_content": r["file_content"], "filename": r["filename"]}
                for r in download_results
                if r["file_content"]
            ]
            excel_results = self.excel_service.parse_batch(parse_items)

            # Update records
            success_count = 0
            parse_idx = 0
            for i, record in enumerate(failed_records):
                download_result = download_results[i]

                if download_result["error"]:
                    record.error_message = f"Download failed: {download_result['error']}"
                    record.retry_count += 1
                    continue

                excel_result = excel_results.results[parse_idx]
                parse_idx += 1

                record.sheet_name = excel_result.sheet_name
                record.total_rows = excel_result.total_rows
                record.total_cols = excel_result.total_cols
                record.raw_text = excel_result.raw_text
                record.retry_count += 1

                if excel_result.success:
                    record.status = RecordStatus.READY_FOR_ANALYSIS
                    record.error_message = None
                    success_count += 1
                else:
                    record.error_message = excel_result.error

            db.commit()

        return {
            "retried": len(failed_records),
            "success": success_count,
            "failed": len(failed_records) - success_count
        }

    # =========================================================================
    # Analysis & Email Workflow
    # =========================================================================

    async def run_analysis(self) -> Dict[str, Any]:
        """Run AI analysis on all records with READY_FOR_ANALYSIS status.

        Returns:
            Summary of analysis results
        """
        with get_db() as db:
            records = db.query(Record).filter(
                Record.status == RecordStatus.READY_FOR_ANALYSIS
            ).all()

            if not records:
                log_step("Analysis", "No records ready for analysis", "⚠️")
                return {"analyzed": 0, "message": "No records ready for analysis"}

            log_step("Analysis", f"Starting analysis for {len(records)} record(s)...", "🤖")

            success_count = 0
            for record in records:
                success = await self.run_analysis_for_record(record.id)
                if success:
                    success_count += 1

        log_step("Analysis complete", f"{success_count}/{len(records)} successful", "🎉")
        return {
            "analyzed": len(records),
            "success": success_count,
            "failed": len(records) - success_count
        }

    async def run_analysis_for_record(self, record_id: int) -> bool:
        """Run AI analysis for a single record.

        Args:
            record_id: The ID of the record to analyze

        Returns:
            True if analysis succeeded, False otherwise
        """
        settings = get_settings()
        agent = get_analysis_agent()

        with get_db() as db:
            record = db.query(Record).filter(
                Record.id == record_id,
                Record.status == RecordStatus.READY_FOR_ANALYSIS
            ).first()

            if not record:
                log_step("Analysis", f"Record {record_id} not found or not ready", "⚠️")
                return False

            try:
                # 提前获取所需数据，避免 session 分离问题
                employee_name = record.employee_name
                raw_text = record.raw_text or ""
                rec_id = record.id

                # Update status to ANALYZING
                record.status = RecordStatus.ANALYZING
                db.commit()

            # 在 session 外执行耗时操作
            except Exception as e:
                record.status = RecordStatus.FAILED
                record.error_message = f"Failed to start analysis: {str(e)}"
                db.commit()
                return False

        # Run analysis agent (在 session 外执行，避免阻塞)
        try:
            result = await agent.analyze(
                record_id=rec_id,
                employee_name=employee_name,
                raw_text=raw_text
            )
        except Exception as e:
            # 分析失败，更新状态
            with get_db() as db:
                record = db.query(Record).filter(Record.id == rec_id).first()
                if record:
                    record.status = RecordStatus.FAILED
                    record.error_message = f"Analysis exception: {str(e)}"
                    db.commit()
            log_step("Analysis error", f"{employee_name}: {str(e)}", "❌")
            return False

        # 更新结果（新 session）
        with get_db() as db:
            record = db.query(Record).filter(Record.id == rec_id).first()
            if not record:
                return False

            if result.get("error"):
                record.status = RecordStatus.FAILED
                record.error_message = result["error"]
                db.commit()
                log_step("Analysis failed", f"{employee_name}: {result['error']}", "❌")
                return False

            log_step("Analyzed", f"{employee_name} - Score: {result.get('final_score', {}).get('总分', 'N/A')}", "✅")
            db.commit()
            return True

    async def send_email_for_record(self, record_id: int) -> bool:
        """Send evaluation email for a single record.

        Args:
            record_id: The ID of the record to send email for

        Returns:
            True if email sent successfully, False otherwise
        """
        settings = get_settings()

        if not settings.smtp_user or not settings.smtp_pass:
            log_step("Email", "SMTP not configured", "⚠️")
            return False

        email_service = EmailService(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_user=settings.smtp_user,
            smtp_pass=settings.smtp_pass,
            from_email=settings.from_email
        )

        with get_db() as db:
            record = db.query(Record).filter(
                Record.id == record_id,
                Record.status == RecordStatus.SCORED
            ).first()

            if not record:
                log_step("Email", f"Record {record_id} not found or not scored", "⚠️")
                return False

            # 提前获取所需数据，避免 session 分离问题
            employee_email = record.employee_email
            employee_name = record.employee_name
            email_content = record.email_content
            rec_id = record.id

            # Update status to EMAILING
            record.status = RecordStatus.EMAILING
            db.commit()

        # 在 session 外执行发邮件操作
        if not email_content:
            with get_db() as db:
                record = db.query(Record).filter(Record.id == rec_id).first()
                if record:
                    record.status = RecordStatus.FAILED
                    record.error_message = "No email content generated"
                    db.commit()
            log_step("Email error", f"{employee_name}: No email content", "❌")
            return False

        try:
            result = email_service.send_evaluation_email(
                to_email=employee_email,
                employee_name=employee_name,
                email_content=email_content
            )
        except Exception as e:
            with get_db() as db:
                record = db.query(Record).filter(Record.id == rec_id).first()
                if record:
                    record.status = RecordStatus.FAILED
                    record.error_message = f"Email exception: {str(e)}"
                    db.commit()
            log_step("Email error", f"{employee_name}: {str(e)}", "❌")
            return False

        # 更新结果（新 session）
        with get_db() as db:
            record = db.query(Record).filter(Record.id == rec_id).first()
            if not record:
                return False

            if result.success:
                record.status = RecordStatus.DONE
                record.email_sent_at = datetime.now()
                db.commit()
                log_step("Email sent", f"{employee_name} <{employee_email}>", "✅")
                return True
            else:
                record.status = RecordStatus.FAILED
                record.error_message = result.error_message
                db.commit()
                log_step("Email failed", f"{employee_name}: {result.error_message}", "❌")
                return False

    async def send_emails(self) -> Dict[str, Any]:
        """Send evaluation emails for all records with SCORED status.

        Returns:
            Summary of email sending results
        """
        with get_db() as db:
            records = db.query(Record).filter(
                Record.status == RecordStatus.SCORED
            ).all()

            if not records:
                log_step("Email", "No records ready for email", "⚠️")
                return {"sent": 0, "message": "No records ready for email"}

            log_step("Email", f"Sending emails for {len(records)} record(s)...", "📧")

            success_count = 0
            for record in records:
                success = await self.send_email_for_record(record.id)
                if success:
                    success_count += 1

        log_step("Email complete", f"{success_count}/{len(records)} sent", "🎉")
        return {
            "sent": len(records),
            "success": success_count,
            "failed": len(records) - success_count
        }