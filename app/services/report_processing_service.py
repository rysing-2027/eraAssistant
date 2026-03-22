"""Report Processing Service for ERA Assistant.

This module orchestrates the complete workflow:
1. Fetch records from Feishu Base
2. Download and parse Excel files
3. Run AI analysis (3 judges)
4. Send evaluation emails

重构设计：
- 核心处理函数可复用（webhook 和恢复流程共用）
- 单条记录处理：下载 → 导入 → 解析
- 分析发邮件：分析 → 发邮件
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

# 全局锁：防止并发处理同一记录
_processing_locks: Dict[str, asyncio.Lock] = {}


def get_record_lock(record_id: str) -> asyncio.Lock:
    """获取单条记录的锁，防止并发处理"""
    if record_id not in _processing_locks:
        _processing_locks[record_id] = asyncio.Lock()
    return _processing_locks[record_id]


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
        max_concurrent: int = 3
    ):
        self.feishu_service = feishu_service
        self.excel_service = ExcelProcessingService()
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    # =========================================================================
    # 核心处理函数（可复用）
    # =========================================================================

    async def _download_file(self, file_token: str, filename: str) -> Dict[str, Any]:
        """下载单个文件。

        Returns:
            {"filename": str, "file_content": bytes or None, "error": str or None}
        """
        if not self.feishu_service:
            return {"filename": filename, "file_content": None, "error": "FeishuService not configured"}

        async with self._semaphore:
            try:
                await asyncio.sleep(0.5)  # 避免 Feishu 限流
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

    async def _import_to_feishu_sheet(
        self,
        file_content: bytes,
        filename: str,
        folder_token: str,
        employee_name: str
    ) -> Dict[str, Any]:
        """导入文件到飞书电子表格。

        Returns:
            {"success": bool, "url": str or None, "error": str or None}
        """
        if not self.feishu_service:
            return {"success": False, "url": None, "error": "FeishuService not configured"}

        try:
            await asyncio.sleep(0.5)  # 避免限流
            url = await self.feishu_service.import_xlsx_to_sheet(
                file_content=file_content,
                file_name=filename,
                folder_token=folder_token
            )
            if url:
                log_step("Imported", f"{employee_name}: {url}", "✅")
                return {"success": True, "url": url, "error": None}
            else:
                error_msg = "No URL returned from import"
                log_step("Import warning", f"{employee_name}: {error_msg}", "⚠️")
                return {"success": False, "url": None, "error": error_msg}
        except Exception as e:
            error_detail = f"{type(e).__name__}: {str(e)}"
            log_step("Import failed", f"{employee_name}: {error_detail}", "❌")
            return {"success": False, "url": None, "error": error_detail}

    def _parse_excel(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """解析 Excel 文件。

        Returns:
            {"success": bool, "raw_text": str, "sheet_name": str, "total_rows": int, "total_cols": int, "error": str or None}
        """
        result = self.excel_service.parse_excel(file_content, filename)
        return {
            "success": result.success,
            "raw_text": result.raw_text,
            "sheet_name": result.sheet_name,
            "total_rows": result.total_rows,
            "total_cols": result.total_cols,
            "error": result.error if not result.success else None
        }

    async def process_single_record(
        self,
        record_id: int,
        folder_token: str = None
    ) -> bool:
        """处理单条记录：下载 → 导入 → 解析。

        这是核心处理函数，webhook 和恢复流程都调用此函数。

        Args:
            record_id: 记录 ID
            folder_token: 飞书文件夹 token（可选，用于导入）

        Returns:
            True 表示成功（状态变为 READY_FOR_ANALYSIS）
            False 表示失败（状态变为 FAILED）
        """
        with get_db() as db:
            record = db.query(Record).filter(
                Record.id == record_id,
                Record.status.in_([RecordStatus.SUBMITTED, RecordStatus.PROCESSING, RecordStatus.FAILED])
            ).first()

            if not record:
                return False

            employee_name = record.employee_name
            file_token = record.file_token
            file_name = record.file_name
            existing_report_link = record.report_link  # 预设的飞书表格链接

            # 更新状态为 PROCESSING
            record.status = RecordStatus.PROCESSING
            record.error_message = None
            db.commit()

        # Step 1: 下载文件
        download_result = await self._download_file(file_token, file_name)
        if download_result["error"]:
            with get_db() as db:
                record = db.query(Record).filter(Record.id == record_id).first()
                if record:
                    record.status = RecordStatus.FAILED
                    record.error_message = f"Download failed: {download_result['error']}"
                    db.commit()
            return False

        file_content = download_result["file_content"]
        filename = download_result["filename"]

        # Step 2: 导入飞书表格（如果有预设 report_link 则跳过）
        feishu_doc_url = None
        if existing_report_link is not None and existing_report_link != "":
            # 已有预设链接，直接使用
            feishu_doc_url = existing_report_link
            log_step("Using existing link", f"{employee_name}: {feishu_doc_url}", "🔗")
        elif folder_token and self.feishu_service:
            import_result = await self._import_to_feishu_sheet(
                file_content, filename, folder_token, employee_name
            )
            if not import_result["success"]:
                with get_db() as db:
                    record = db.query(Record).filter(Record.id == record_id).first()
                    if record:
                        record.status = RecordStatus.FAILED
                        record.error_message = f"Feishu import failed: {import_result['error']}"
                        db.commit()
                return False
            feishu_doc_url = import_result["url"]

        # Step 3: 解析 Excel
        parse_result = self._parse_excel(file_content, filename)

        with get_db() as db:
            record = db.query(Record).filter(Record.id == record_id).first()
            if not record:
                return False

            record.sheet_name = parse_result["sheet_name"]
            record.total_rows = parse_result["total_rows"]
            record.total_cols = parse_result["total_cols"]
            record.raw_text = parse_result["raw_text"]

            if feishu_doc_url is not None:
                record.feishu_doc_url = feishu_doc_url

            if parse_result["success"]:
                record.status = RecordStatus.READY_FOR_ANALYSIS
                db.commit()
                log_step("Ready", f"{employee_name} ({parse_result['total_rows']} rows)", "✅")
                return True
            else:
                record.status = RecordStatus.FAILED
                record.error_message = parse_result["error"]
                db.commit()
                log_step("Failed", f"{employee_name}: parse error", "❌")
                return False

    async def analyze_and_email(self, record_id: int) -> bool:
        """分析并发邮件：分析 → 发邮件。

        核心处理函数，处理 READY_FOR_ANALYSIS 状态的记录。

        Args:
            record_id: 记录 ID

        Returns:
            True 表示成功（状态变为 DONE）
            False 表示失败
        """
        # Step 1: 分析
        log_step("Analysis", f"Starting analysis for record {record_id}...", "🤖")
        analysis_success = await self._run_analysis_for_record(record_id)
        if not analysis_success:
            log_step("Analysis", f"Analysis failed for record {record_id}", "❌")
            return False

        # Step 2: 发邮件
        email_success = await self._send_email_for_record(record_id)
        return email_success

    async def process_record_complete(
        self,
        record_id: int,
        folder_token: str = None
    ) -> bool:
        """处理单条记录的完整流程：下载 → 导入 → 解析 → 分析 → 发邮件。

        流水线模式：每条记录独立完成全部流程，不等待其他记录。

        Args:
            record_id: 记录 ID
            folder_token: 飞书文件夹 token（可选，用于导入）

        Returns:
            True 表示成功（状态变为 DONE）
            False 表示失败（状态变为 FAILED）
        """
        # Step 1: 下载 → 导入 → 解析
        process_success = await self.process_single_record(record_id, folder_token)
        if not process_success:
            return False

        # Step 2: 分析 → 发邮件
        return await self.analyze_and_email(record_id)

    async def _run_analysis_for_record(self, record_id: int) -> bool:
        """运行 AI 分析（内部函数）。"""
        log_step("Analysis", f"Entering _run_analysis_for_record for record {record_id}", "🔍")
        lock = get_record_lock(str(record_id))
        if lock.locked():
            log_step("Analysis", f"Record {record_id} is already being processed, skipping", "⏭️")
            return False

        async with lock:
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

                employee_name = record.employee_name
                raw_text = record.raw_text or ""
                rec_id = record.id

                record.status = RecordStatus.ANALYZING
                db.commit()

            # 执行分析（在 session 外）
            try:
                result = await agent.analyze(
                    record_id=rec_id,
                    employee_name=employee_name,
                    raw_text=raw_text
                )
            except Exception as e:
                with get_db() as db:
                    record = db.query(Record).filter(Record.id == rec_id).first()
                    if record:
                        record.status = RecordStatus.FAILED
                        record.error_message = f"Analysis exception: {str(e)}"
                        db.commit()
                log_step("Analysis error", f"{employee_name}: {str(e)}", "❌")
                return False

            # 更新结果
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

    async def _send_email_for_record(self, record_id: int) -> bool:
        """发送评估邮件（内部函数）。"""
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

            employee_email = record.employee_email
            employee_name = record.employee_name
            email_content = record.email_content
            feishu_doc_url = record.feishu_doc_url
            rec_id = record.id

            record.status = RecordStatus.EMAILING
            db.commit()

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
                email_content=email_content,
                doc_link=feishu_doc_url,
                cc=settings.email_cc
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

    # =========================================================================
    # Webhook 流程
    # =========================================================================

    async def run_full_pipeline(
        self,
        base_token: str,
        table_id: str,
        folder_token: str = None
    ) -> Dict[str, Any]:
        """Webhook 触发的完整流程：获取 → 创建 → 处理。

        Args:
            base_token: 飞书 Base token
            table_id: 飞书 Table ID
            folder_token: 飞书文件夹 token（可选）

        Returns:
            处理结果摘要
        """
        if not self.feishu_service:
            return {"new_records": 0, "processed": 0, "error": "FeishuService not configured"}

        # Step 1: 从飞书获取 Submitted 记录
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

        # Step 2: 过滤已处理的记录，创建新记录
        new_record_ids = []
        with get_db() as db:
            for fr in feishu_records:
                feishu_id = fr.get("record_id") or fr.get("id")
                existing = db.query(Record).filter(
                    Record.feishu_record_id == feishu_id
                ).first()

                if existing:
                    continue

                fields = fr.get("fields", {})
                file_list = fields.get("file", [])
                if not file_list:
                    continue

                file_info = file_list[0]

                # 提取字段值
                name_field = fields.get("name", "")
                email_field = fields.get("email", "")
                report_link_field = fields.get("report_link", "")  # 预设的飞书表格链接

                if isinstance(name_field, list) and name_field:
                    name_field = name_field[0].get("text", "")
                if isinstance(email_field, list) and email_field:
                    email_field = email_field[0].get("text", email_field[0].get("link", ""))

                # 飞书链接字段格式: {'link': 'https://...', 'token': '...', ...}
                report_link_value = None
                if report_link_field:
                    if isinstance(report_link_field, dict):
                        report_link_value = report_link_field.get("link", "")
                    elif isinstance(report_link_field, list) and report_link_field:
                        report_link_value = report_link_field[0].get("link", "") if isinstance(report_link_field[0], dict) else ""
                    elif isinstance(report_link_field, str):
                        report_link_value = report_link_field

                record = Record(
                    feishu_record_id=feishu_id,
                    employee_name=name_field,
                    employee_email=email_field,
                    file_token=file_info.get("file_token", ""),
                    file_name=file_info.get("name", ""),
                    report_link=report_link_value,
                    status=RecordStatus.SUBMITTED
                )
                db.add(record)
                db.flush()  # 获取 ID
                new_record_ids.append(record.id)

            db.commit()

        if not new_record_ids:
            log_step("Result", "All records already processed", "✅")
            return {"new_records": 0, "processed": 0, "message": "All records already processed"}

        log_step("Created", f"{len(new_record_ids)} new record(s)", "💾")

        # Step 3: 流水线处理（每条记录独立完成全部流程）
        log_step("Step 2", f"Processing {len(new_record_ids)} record(s) in pipeline mode...", "🔄")
        results = await asyncio.gather(
            *[self.process_record_complete(rid, folder_token) for rid in new_record_ids],
            return_exceptions=True
        )

        success_count = sum(1 for r in results if r is True)

        log_step("Pipeline complete", f"{success_count} success, {len(new_record_ids) - success_count} failed", "🎉")
        return {
            "new_records": len(new_record_ids),
            "success": success_count,
            "failed": len(new_record_ids) - success_count,
            "record_ids": new_record_ids
        }

    # =========================================================================
    # 启动恢复流程
    # =========================================================================

    def recover_stuck_records(self, timeout_minutes: int = 10) -> Dict[str, Any]:
        """恢复卡住的记录（启动时调用）。

        将卡在中间状态的记录重置到可重试的状态：
        - PROCESSING → SUBMITTED
        - ANALYZING → READY_FOR_ANALYSIS
        - EMAILING → SCORED
        """
        with get_db() as db:
            cutoff_time = datetime.now() - timedelta(minutes=timeout_minutes)

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

            result_info = []
            for record in stuck_records:
                old_status = record.status.value

                if record.status == RecordStatus.PROCESSING:
                    record.status = RecordStatus.SUBMITTED
                elif record.status == RecordStatus.ANALYZING:
                    record.status = RecordStatus.READY_FOR_ANALYSIS
                elif record.status == RecordStatus.EMAILING:
                    record.status = RecordStatus.SCORED

                record.error_message = f"Recovered from stuck {old_status} state"
                record.retry_count += 1

                log_step("Recovered", f"{record.employee_name}: {old_status} → {record.status.value}", "🔄")
                result_info.append({
                    "id": record.id,
                    "name": record.employee_name,
                    "from": old_status,
                    "to": record.status.value
                })

            db.commit()

        return {
            "recovered": len(result_info),
            "record_ids": [r["id"] for r in result_info],
            "details": result_info
        }

    async def process_stuck_records(
        self,
        base_token: str = None,
        table_id: str = None,
        folder_token: str = None
    ) -> Dict[str, Any]:
        """处理恢复后的记录（启动时调用）。

        根据记录状态调用相应的处理函数：
        - FAILED / SUBMITTED: process_single_record → analyze_and_email
        - READY_FOR_ANALYSIS: analyze_and_email
        - SCORED: send_email
        """
        results = {
            "failed": {"total": 0, "success": 0},
            "submitted": {"total": 0, "success": 0},
            "ready_for_analysis": {"total": 0, "success": 0},
            "scored": {"total": 0, "success": 0}
        }

        # 1. 处理 FAILED（重新下载解析）
        with get_db() as db:
            failed_records = db.query(Record).filter(
                Record.status == RecordStatus.FAILED
            ).all()
            results["failed"]["total"] = len(failed_records)
            failed_ids = [r.id for r in failed_records]

        if failed_ids:
            log_step("Stuck Recovery", f"Retrying {len(failed_ids)} FAILED records...", "🔄")

            # 复用核心处理函数
            process_results = await asyncio.gather(
                *[self.process_single_record(rid, folder_token) for rid in failed_ids],
                return_exceptions=True
            )

            # 分析发邮件
            ready_ids = []
            with get_db() as db:
                ready_records = db.query(Record).filter(
                    Record.status == RecordStatus.READY_FOR_ANALYSIS,
                    Record.id.in_(failed_ids)
                ).all()
                ready_ids = [r.id for r in ready_records]

            if ready_ids:
                analyze_results = await asyncio.gather(
                    *[self.analyze_and_email(rid) for rid in ready_ids],
                    return_exceptions=True
                )
                results["failed"]["success"] = sum(1 for r in analyze_results if r is True)

        # 2. 处理 SUBMITTED
        with get_db() as db:
            submitted_records = db.query(Record).filter(
                Record.status == RecordStatus.SUBMITTED
            ).all()
            results["submitted"]["total"] = len(submitted_records)
            submitted_ids = [r.id for r in submitted_records]

        if submitted_ids:
            log_step("Stuck Recovery", f"Processing {len(submitted_ids)} SUBMITTED records...", "🔄")

            process_results = await asyncio.gather(
                *[self.process_single_record(rid, folder_token) for rid in submitted_ids],
                return_exceptions=True
            )

            ready_ids = []
            with get_db() as db:
                ready_records = db.query(Record).filter(
                    Record.status == RecordStatus.READY_FOR_ANALYSIS,
                    Record.id.in_(submitted_ids)
                ).all()
                ready_ids = [r.id for r in ready_records]

            if ready_ids:
                analyze_results = await asyncio.gather(
                    *[self.analyze_and_email(rid) for rid in ready_ids],
                    return_exceptions=True
                )
                results["submitted"]["success"] = sum(1 for r in analyze_results if r is True)

        # 3. 处理 READY_FOR_ANALYSIS
        with get_db() as db:
            ready_records = db.query(Record).filter(
                Record.status == RecordStatus.READY_FOR_ANALYSIS
            ).all()
            results["ready_for_analysis"]["total"] = len(ready_records)
            ready_ids = [r.id for r in ready_records]

        if ready_ids:
            log_step("Stuck Recovery", f"Processing {len(ready_ids)} READY_FOR_ANALYSIS records...", "🔄")
            analyze_results = await asyncio.gather(
                *[self.analyze_and_email(rid) for rid in ready_ids],
                return_exceptions=True
            )
            results["ready_for_analysis"]["success"] = sum(1 for r in analyze_results if r is True)

        # 4. 处理 SCORED
        with get_db() as db:
            scored_records = db.query(Record).filter(
                Record.status == RecordStatus.SCORED
            ).all()
            results["scored"]["total"] = len(scored_records)
            scored_ids = [r.id for r in scored_records]

        if scored_ids:
            log_step("Stuck Recovery", f"Processing {len(scored_ids)} SCORED records...", "🔄")
            email_results = await asyncio.gather(
                *[self._send_email_for_record(rid) for rid in scored_ids],
                return_exceptions=True
            )
            results["scored"]["success"] = sum(1 for r in email_results if r is True)

        # 汇总
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

    # =========================================================================
    # 手动触发的 API
    # =========================================================================

    async def run_analysis(self) -> Dict[str, Any]:
        """手动触发：分析所有 READY_FOR_ANALYSIS 记录。"""
        with get_db() as db:
            records = db.query(Record).filter(
                Record.status == RecordStatus.READY_FOR_ANALYSIS
            ).all()
            record_ids = [r.id for r in records]

        if not record_ids:
            log_step("Analysis", "No records ready for analysis", "⚠️")
            return {"analyzed": 0, "message": "No records ready for analysis"}

        log_step("Analysis", f"Starting analysis for {len(record_ids)} record(s)...", "🤖")

        results = await asyncio.gather(
            *[self._run_analysis_for_record(rid) for rid in record_ids],
            return_exceptions=True
        )

        success_count = sum(1 for r in results if r is True)
        log_step("Analysis complete", f"{success_count}/{len(record_ids)} successful", "🎉")

        return {
            "analyzed": len(record_ids),
            "success": success_count,
            "failed": len(record_ids) - success_count
        }

    async def send_emails(self) -> Dict[str, Any]:
        """手动触发：发送所有 SCORED 记录的邮件。"""
        with get_db() as db:
            records = db.query(Record).filter(
                Record.status == RecordStatus.SCORED
            ).all()
            record_ids = [r.id for r in records]

        if not record_ids:
            log_step("Email", "No records ready for email", "⚠️")
            return {"sent": 0, "message": "No records ready for email"}

        log_step("Email", f"Sending emails for {len(record_ids)} record(s)...", "📧")

        results = await asyncio.gather(
            *[self._send_email_for_record(rid) for rid in record_ids],
            return_exceptions=True
        )

        success_count = sum(1 for r in results if r is True)
        log_step("Email complete", f"{success_count}/{len(record_ids)} sent", "🎉")

        return {
            "sent": len(record_ids),
            "success": success_count,
            "failed": len(record_ids) - success_count
        }

    async def retry_failed_records(self) -> Dict[str, Any]:
        """手动触发：重试所有 FAILED 记录。"""
        with get_db() as db:
            failed_records = db.query(Record).filter(
                Record.status == RecordStatus.FAILED
            ).all()
            failed_ids = [r.id for r in failed_records]

        if not failed_ids:
            return {"retried": 0, "message": "No failed records"}

        log_step("Retry", f"Retrying {len(failed_ids)} FAILED records...", "🔄")

        results = await asyncio.gather(
            *[self.process_single_record(rid) for rid in failed_ids],
            return_exceptions=True
        )

        success_count = sum(1 for r in results if r is True)

        return {
            "retried": len(failed_ids),
            "success": success_count,
            "failed": len(failed_ids) - success_count
        }

    # =========================================================================
    # 兼容旧 API（保持接口不变）
    # =========================================================================

    async def run_analysis_for_record(self, record_id: int) -> bool:
        """兼容旧 API：分析单条记录。"""
        return await self._run_analysis_for_record(record_id)

    async def send_email_for_record(self, record_id: int) -> bool:
        """兼容旧 API：发送单条记录邮件。"""
        return await self._send_email_for_record(record_id)