# Service Architecture Overview

This document describes the overall service architecture of ERA Assistant.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              ERA Assistant                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                      Program Startup (lifespan)                          │    │
│  │                                                                          │    │
│  │  1. Load config (settings)                                               │    │
│  │  2. Init database (SQLite/PostgreSQL)                                    │    │
│  │  3. Recover stuck records ──────────────────────────────────────────┐    │    │
│  │     - PROCESSING → SUBMITTED                                         │    │    │
│  │     - ANALYZING → READY_FOR_ANALYSIS                                 │    │    │
│  │     - EMAILING → SCORED                                              │    │    │
│  │  4. Process recovered records                                        │    │    │
│  │     - SUBMITTED → 下载解析 → 分析 → 发邮件                            │    │    │
│  │     - READY_FOR_ANALYSIS → 分析 → 发邮件                             │    │    │
│  │     - SCORED → 发邮件                                               │    │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                           Routers (API Layer)                            │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                       │    │
│  │  │ health.py   │  │ test.py     │  │ webhook.py  │                       │    │
│  │  │ /, /health  │  │ /test/*     │  │ /api/webhook│                       │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                       │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                      │                                          │
│                                      ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                    ReportProcessingService                               │    │
│  │                    (Orchestration Layer)                                 │    │
│  │                                                                          │    │
│  │  - State management (Record status transitions)                          │    │
│  │  - Parallel download (asyncio + Semaphore)                              │    │
│  │  - Single-record processing (record-level locking)                      │    │
│  │  - Database operations (only service with DB access)                     │    │
│  └────────────────────────────────┬────────────────────────────────────────┘    │
│                                   │                                             │
│              ┌────────────────────┼────────────────────┐                        │
│              │                    │                    │                        │
│              ▼                    ▼                    ▼                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                 │
│  │  FeishuService  │  │ ExcelService    │  │  EmailService   │                 │
│  │                 │  │                 │  │                 │                 │
│  │ - API auth      │  │ - Pure parsing  │  │ - SMTP SSL      │                 │
│  │ - Get records   │  │ - bytes→text    │  │ - Markdown→HTML │                 │
│  │ - Download      │  │ - No deps       │  │ - Styled email  │                 │
│  │ - No DB access  │  │ - No DB access  │  │ - No DB access  │                 │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘                 │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                         AI Agent Layer                                   │    │
│  │                                                                          │    │
│  │   AnalysisAgent (LangGraph)                                              │    │
│  │   ├── Judge 1 (Qwen3-max) ─┐                                            │    │
│  │   ├── Judge 2 (Qwen3-max) ─┼──▶ Main Judge (Qwen3-max) ──▶ Final Score   │    │
│  │   └── Judge 3 (Qwen3-max) ─┘                                            │    │
│  │                                                                          │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │                         Data Layer                                       │    │
│  │  ┌─────────────────────┐          ┌─────────────────────┐               │    │
│  │  │   Record Model      │          │   AIConfig Model    │               │    │
│  │  │   (records table)   │          │   (ai_configs table)│               │    │
│  │  └─────────────────────┘          └─────────────────────┘               │    │
│  │                                                                          │    │
│  │  Database: SQLite (default) / PostgreSQL (production)                   │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Complete Workflow

### Program Startup Flow

程序启动时自动恢复并处理卡住的记录：

```
程序启动 (uvicorn)
    │
    ├─ 1. 加载配置 (get_settings)
    │
    ├─ 2. 初始化数据库 (init_db)
    │
    ├─ 3. 恢复卡住记录 (recover_stuck_records)
    │      ├─ PROCESSING (超时10分钟) → SUBMITTED
    │      ├─ ANALYZING (超时10分钟) → READY_FOR_ANALYSIS
    │      └─ EMAILING (超时10分钟) → SCORED
    │
    ├─ 4. 处理恢复的记录 (process_stuck_records)
    │      ├─ SUBMITTED → 下载 → 解析 → 分析 → 发邮件
    │      ├─ READY_FOR_ANALYSIS → 分析 → 发邮件 (并行3个)
    │      └─ SCORED → 发邮件
    │
    └─ 5. 服务就绪，等待请求
```

### Webhook Flow (Production)

**关键设计：立即返回，避免飞书超时**

```
飞书提交 → Webhook → 立即返回 → 后台处理
    │         │          │           │
    │         │          │           │
    ▼         ▼          ▼           ▼
用户提交   POST请求    <100ms响应   后台执行
          验证token   返回accepted  下载→解析→分析→发邮件
          注册后台任务              (并行3个)
```

**时序图：**

```
飞书                         ERA Assistant
  │                                │
  │─── POST /api/webhook/trigger ─▶│
  │                                │
  │     验证 token (< 10ms)        │
  │     注册 background_tasks      │
  │                                │
  │◀── {"status": "accepted"} ─────│  ← 立即返回 (< 100ms)
  │                                │
  │         (连接关闭)              │
  │                                │
  │                    ┌───────────┴───────────┐
  │                    │   后台任务开始         │
  │                    │   ├─ run_full_pipeline│
  │                    │   ├─ 获取飞书记录      │
  │                    │   ├─ 下载文件 (并发5)  │
  │                    │   ├─ 解析Excel        │
  │                    │   ├─ 分析 (并发3)     │
  │                    │   └─ 发送邮件         │
  │                    └───────────────────────┘
```

### Record-Level Processing

每条记录独立处理，互不干扰：

```python
# Webhook 收到提交，立即返回
background_tasks.add_task(process_records_task)
return {"status": "accepted"}  # < 100ms

# 后台任务
async def process_records_task():
    result = await processing_service.run_full_pipeline()
    record_ids = result["record_ids"]  # [1, 2, 3, ...]

    # 并行处理
    await asyncio.gather(*[process_one(rid) for rid in record_ids])
```

### Parallel Analysis

并发控制，最多3条同时处理：

```python
semaphore = asyncio.Semaphore(3)

async def process_one(record_id: int):
    async with semaphore:
        success = await run_analysis_for_record(record_id)
        if success:
            await send_email_for_record(record_id)

await asyncio.gather(*[process_one(rid) for rid in record_ids])
```

---

## Router Layer

Routers are organized into separate files for modularity and maintainability.

### File Structure

```
app/
├── routers/
│   ├── __init__.py      # Exports all routers
│   ├── health.py        # Root and health check endpoints
│   ├── test.py          # Testing/debugging endpoints
│   └── webhook.py       # Feishu automation webhook
└── main.py              # FastAPI app + lifespan
```

### Router Details

| Router | File | Prefix | Endpoints | Purpose |
|--------|------|--------|-----------|---------|
| health_router | `health.py` | `/` | `GET /`, `GET /health` | Root redirect and health monitoring |
| test_router | `test.py` | `/test` | Multiple test endpoints | Development and debugging |
| webhook_router | `webhook.py` | `/api/webhook` | `POST /trigger` | Feishu automation integration |

### Webhook Details

**关键设计：立即返回，避免飞书超时**

```python
@router.post("/trigger")
async def feishu_automation_trigger(background_tasks: BackgroundTasks, ...):
    # 1. 验证 token (< 10ms)
    if settings.webhook_token and x_webhook_token != settings.webhook_token:
        raise HTTPException(status_code=401)

    # 2. 注册后台任务
    background_tasks.add_task(process_records_task)

    # 3. 立即返回 (< 100ms)
    return {"status": "accepted"}


async def process_records_task():
    """后台执行完整流程"""
    # Step 1: 获取记录 + 下载 + 解析
    result = await processing_service.run_full_pipeline(...)
    record_ids = result.get("record_ids", [])

    # Step 2: 并行分析 + 发邮件 (Semaphore=3)
    semaphore = asyncio.Semaphore(3)

    async def process_one(record_id):
        async with semaphore:
            success = await processing_service.run_analysis_for_record(record_id)
            if success:
                await processing_service.send_email_for_record(record_id)

    await asyncio.gather(*[process_one(rid) for rid in record_ids])
```

**为什么立即返回？**

| 场景 | 响应时间 | 飞书行为 |
|------|---------|---------|
| 等待下载完成 | 400秒 (200个文件) | 超时重试 ❌ |
| 立即返回 | < 100ms | 正常结束 ✅ |

---

## Service Layer

### 1. FeishuService

**File**: `app/services/feishu_service.py`

**Responsibility**: All Feishu (Lark) API interactions

**Methods**:
| Method | Purpose |
|--------|---------|
| `_get_tenant_access_token()` | Get auth token from Feishu |
| `get_base_records()` | Fetch records from Feishu Base (多维表) |
| `download_file()` | Download file attachment by token |

**Design Principles**:
- No database access - pure API client
- Token caching for efficiency
- All methods are async (IO-bound)

---

### 2. ExcelProcessingService

**File**: `app/services/excel_service.py`

**Responsibility**: Parse Excel files to AI-friendly text format

**Methods**:
| Method | Purpose |
|--------|---------|
| `parse_excel(bytes, filename)` | Parse single Excel to raw_text |
| `parse_batch(items)` | Parse multiple files |

**Design Principles**:
- Zero external dependencies for parsing logic
- No database access
- Synchronous methods (CPU-bound)
- Reusable for any file source

---

### 3. EmailService

**File**: `app/services/email_service.py`

**Responsibility**: Send evaluation emails via SMTP

**Methods**:
| Method | Purpose |
|--------|---------|
| `send_email(to, subject, content, content_type)` | Send raw email |
| `send_evaluation_email(to, name, content)` | Send styled evaluation email |

**Design Principles**:
- SSL connection for port 465 (Tencent Enterprise Email)
- Markdown → HTML conversion with styling
- No database access

**Email Styling**:
```python
# Markdown converted to HTML with CSS styling
html_content = markdown.markdown(email_content, extensions=["tables"])

styled_html = f"""
<html>
<head>
    <style>
        body {{ font-family: -apple-system, sans-serif; line-height: 1.6; }}
        h3 {{ color: #2c3e50; border-bottom: 2px solid #3498db; }}
        ...
    </style>
</head>
<body>{html_content}</body>
</html>
"""
```

---

### 4. ReportProcessingService

**File**: `app/services/report_processing_service.py`

**Responsibility**: Orchestrate the complete workflow

**Key Methods**:
| Method | Purpose |
|--------|---------|
| `run_full_pipeline()` | Main entry: fetch → parse → store, returns record_ids |
| `run_analysis_for_record(id)` | Analyze single record |
| `send_email_for_record(id)` | Send email for single record |
| `recover_stuck_records()` | Reset stuck transient states (startup) |
| `process_stuck_records()` | Process recovered records (startup) |
| `retry_failed_records()` | Retry failed records |

**Design Principles**:
- **Only service that touches database**
- Record-level locking for concurrent safety
- Parallel processing with Semaphore

**Recovery Methods (启动时调用)**:

```python
# 1. 恢复卡住的状态
def recover_stuck_records(timeout_minutes=10):
    """
    PROCESSING → SUBMITTED (超时10分钟)
    ANALYZING → READY_FOR_ANALYSIS
    EMAILING → SCORED
    """

# 2. 处理恢复的记录
async def process_stuck_records(base_token, table_id):
    """
    READY_FOR_ANALYSIS: 并行分析+发邮件 (Semaphore=3)
    SCORED: 发邮件
    SUBMITTED: 下载+解析+分析+发邮件
    """
```

---

## AI Agent Layer

### AnalysisAgent

**File**: `app/agents/analysis_agent.py`

**Technology**: LangGraph for multi-agent orchestration

**Model**: Qwen3-max (via DashScope API)

**Architecture**:
```
                    ┌─────────────────────────────────────┐
                    │         AnalysisAgent                │
                    │                                      │
                    │  ┌─────────┐  ┌─────────┐  ┌─────────┐
Record ────────────▶│  │Judge 1  │  │Judge 2  │  │Judge 3  │
                    │  │Qwen3-max│  │Qwen3-max│  │Qwen3-max│
                    │  └────┬────┘  └────┬────┘  └────┬────┘
                    │       │            │            │     │
                    │       └────────────┼────────────┘     │
                    │                    │                  │
                    │                    ▼                  │
                    │           ┌──────────────┐           │
                    │           │ Main Judge   │           │
                    │           │ Qwen3-max    │           │
                    │           └──────┬───────┘           │
                    │                  │                    │
                    │                  ▼                    │
                    │        Final Score + Email           │
                    └─────────────────────────────────────┘
```

**Scoring Dimensions**:
| Dimension | Max Score | Weight |
|-----------|-----------|--------|
| 体验完整性 | 20 | 20% |
| 用户视角还原度 | 15 | 15% |
| 分析深度 | 25 | 25% |
| 建议价值 | 20 | 20% |
| 表达质量 | 10 | 10% |
| 态度与投入 | 10 | 10% |

**Grade Scale**:
| Score Range | Grade |
|-------------|-------|
| 90-100 | S |
| 80-89 | A |
| 70-79 | B |
| 60-69 | C |
| 0-59 | D |

---

## Data Models

### Record Model

**File**: `app/models/record.py`

| Field | Type | Description |
|-------|------|-------------|
| `id` | Integer | Primary key |
| `feishu_record_id` | String | Unique Feishu record identifier |
| `employee_name` | String | Employee name |
| `employee_email` | String | Employee email |
| `file_token` | String | Feishu file token |
| `file_name` | String | Original filename |
| `status` | Enum | Current processing status |
| `raw_text` | Text | AI-friendly text |
| `analysis_results` | JSON | 3 judge results |
| `final_score` | JSON | Aggregated score |
| `email_content` | Text | Generated email (Markdown) |
| `email_sent_at` | DateTime | Email sent timestamp |

### RecordStatus Enum

```python
class RecordStatus(str, enum.Enum):
    SUBMITTED = "Submitted"                    # Fetched from Feishu
    PROCESSING = "Processing"                  # Downloading/Parsing
    READY_FOR_ANALYSIS = "Ready for Analysis"  # Ready for AI
    ANALYZING = "Analyzing"                    # AI in progress
    SCORED = "Scored"                          # Analysis complete
    EMAILING = "Emailing"                      # Sending email
    DONE = "Done"                              # Complete
    FAILED = "Failed"                          # Error occurred
```

---

## State Management

### Full Status Flow

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│  SUBMITTED  │ ──▶ │ PROCESSING  │ ──▶ │ READY_FOR_       │
│             │     │             │     │ ANALYSIS         │
└─────────────┘     └─────────────┘     └──────────────────┘
      ▲                   │                    │
      │                   ▼                    ▼
      │            ┌─────────────┐      ┌─────────────┐
      │            │   FAILED    │      │  ANALYZING  │
      │            └─────────────┘      └─────────────┘
      │                                       │
      │                                       ▼
      │                                ┌─────────────┐
      │                                │   SCORED    │
      │                                └─────────────┘
      │                                       │
      │                                       ▼
      │                                ┌─────────────┐
      │                                │  EMAILING   │
      │                                └─────────────┘
      │                                       │
      │                                       ▼
      │                                ┌─────────────┐
      │                                │    DONE     │
      │                                └─────────────┘
      │
      │    程序重启恢复 (超时10分钟)
      │    ┌────────────────────────────────────┐
      └────┤ PROCESSING → SUBMITTED             │
           │ ANALYZING → READY_FOR_ANALYSIS     │
           │ EMAILING → SCORED                  │
           └────────────────────────────────────┘
```

### Recovery Logic

程序重启时，自动恢复卡住的记录：

| 卡住状态 | 恢复为 | 后续处理 |
|---------|-------|---------|
| PROCESSING | SUBMITTED | 重新下载解析 |
| ANALYZING | READY_FOR_ANALYSIS | 重新分析 |
| EMAILING | SCORED | 重新发邮件 |
| FAILED | 不变 | 需要手动处理 |

**注意**：FAILED 状态不会自动恢复，因为那是明确的失败，需要人工排查。

### Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| Fetch & Parse | ✅ Implemented | Feishu → Excel → Database |
| AI Analysis | ✅ Implemented | Triple validation with Qwen3-max |
| Email Sending | ✅ Implemented | SMTP + Markdown → HTML |
| Webhook Immediate Return | ✅ Implemented | < 100ms response, background processing |
| Stuck Recovery | ✅ Implemented | Auto-recover on startup |

---

## Concurrency Control

### Overview

系统在多个层级实现了并发控制，避免触发外部 API 限流：

```
Layer 1: Webhook/Startup     → Semaphore(3)   控制记录级处理并发
    ↓
Layer 2: Download            → Semaphore(3)   控制飞书文件下载并发
    ↓
Layer 3: Analysis            → Semaphore(3)   控制 AI 分析并发
    ↓
Layer 4: ChatTongyi API      → Semaphore(3)   控制通义千问 API 并发
         + Rate Limit        → 0.2s 间隔      保证不超过 5次/秒
```

### 为什么需要多层并发控制？

| API | 限制 | 应对策略 |
|-----|------|---------|
| 飞书文件下载 | 未知，保守限制 | Semaphore(3) |
| 通义千问 (ChatTongyi) | 5 次/秒 | Semaphore(3) + 0.2s 间隔 |
| OpenAI | 按账户配额 | Semaphore(3) 足够 |
| DeepSeek | 按账户配额 | Semaphore(3) 足够 |

### Layer 1: Record Processing

**位置**: `main.py`, `webhook.py`, `report_processing_service.py`

```python
semaphore = asyncio.Semaphore(3)

async def process_one(record_id: int):
    async with semaphore:
        success = await run_analysis_for_record(record_id)
        if success:
            await send_email_for_record(record_id)

# 并行处理多条记录
await asyncio.gather(*[process_one(rid) for rid in record_ids])
```

**效果**: 最多 3 条记录同时处理

### Layer 2: File Download

**位置**: `app/services/report_processing_service.py`

```python
class ReportProcessingService:
    def __init__(self, max_concurrent: int = 3):
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def _download_file(self, file_token: str, filename: str):
        async with self._semaphore:
            await asyncio.sleep(0.5)  # 避免飞书限流
            content = await self.feishu_service.download_file(file_token)
            return {"file_content": content, "filename": filename}
```

**效果**: 最多 3 个文件同时下载

### Layer 3: Analysis Tasks

**位置**: `app/services/report_processing_service.py`

```python
# 处理恢复记录时的并发控制
async def process_stuck_records(...):
    # FAILED 记录
    ready_ids = [...]
    semaphore = asyncio.Semaphore(3)

    async def process_failed(record_id):
        async with semaphore:
            success = await self.analyze_and_email(record_id)
            return success

    await asyncio.gather(*[process_failed(rid) for rid in ready_ids])
```

**效果**: 最多 3 个分析任务并行执行

### Layer 4: ChatTongyi Rate Limiting

**位置**: `app/agents/analysis_agent.py`

通义千问 API 限制每秒 5 次调用，需要特殊处理：

```python
# 全局限流控制
_tongyi_semaphore = asyncio.Semaphore(3)  # 最多 3 个并发请求
_tongyi_last_call_time = 0                # 上次调用时间
_tongyi_lock = asyncio.Lock()             # 时间锁

async def call_tongyi_with_rate_limit(llm, messages):
    """调用 ChatTongyi 并遵守限流规则（5次/秒）"""
    global _tongyi_last_call_time

    async with _tongyi_semaphore:
        # 确保请求间隔至少 0.2 秒
        async with _tongyi_lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - _tongyi_last_call_time
            if elapsed < 0.2:
                await asyncio.sleep(0.2 - elapsed)
            _tongyi_last_call_time = asyncio.get_event_loop().time()

        return await llm.ainvoke(messages)
```

**调用点**:
- Judge 1 (Qwen) → 限流 ✓
- Main Judge (Qwen) → 限流 ✓

**效果**: 保证 ChatTongyi 调用不超过 5 次/秒

### Concurrency Summary

| Layer | Location | Semaphore | Purpose |
|-------|----------|-----------|---------|
| 1 | main.py, webhook.py | 3 | 记录处理并发 |
| 2 | report_processing_service.py | 3 | 飞书下载并发 |
| 3 | report_processing_service.py | 3 | 分析任务并发 |
| 4 | analysis_agent.py | 3 + 0.2s | ChatTongyi 限流 |

### 实际并发计算示例

假设处理 10 条记录：

```
时间线（简化）:

T=0s:   Record 1, 2, 3 开始处理 (Layer 1 限制)
        ├─ Record 1: 下载文件 (Layer 2)
        ├─ Record 2: 下载文件 (Layer 2)
        └─ Record 3: 下载文件 (Layer 2)

T=2s:   Record 1, 2, 3 开始分析 (Layer 3)
        ├─ Judge 1 (Qwen)  ← Layer 4 限流，间隔 0.2s
        ├─ Judge 2 (OpenAI)
        └─ Judge 3 (DeepSeek)

T=5s:   Record 1 完成，Record 4 开始
        ...

最大并发:
- 下载: 3 个文件
- 分析: 3 个任务
- ChatTongyi: 3 个请求 + 不超过 5次/秒
```

---

## Parallel Processing

### Download (3 concurrent)

```python
self._semaphore = asyncio.Semaphore(3)

async def _download_with_limit(self, file_token, filename):
    async with self._semaphore:
        await asyncio.sleep(0.5)  # Avoid Feishu rate limit
        content = await self.feishu_service.download_file(file_token)
        return {"file_content": content, "filename": filename}
```

### Analysis (3 concurrent)

```python
semaphore = asyncio.Semaphore(3)

async def process_one(record_id: int):
    async with semaphore:
        await run_analysis_for_record(record_id)
        await send_email_for_record(record_id)
```

---

## Configuration

**File**: `config/settings.py`

| Setting | Description | Default |
|---------|-------------|---------|
| `database_url` | Database connection | `sqlite:///./data/era.db` |
| `feishu_app_id` | Feishu app ID | `""` |
| `feishu_app_secret` | Feishu secret | `""` |
| `feishu_base_token` | Feishu Base token | `""` |
| `feishu_table_id` | Feishu Table ID | `""` |
| `smtp_host` | SMTP server | `smtp.gmail.com` |
| `smtp_port` | SMTP port | `587` |
| `smtp_user` | SMTP username | `""` |
| `smtp_pass` | SMTP password | `""` |
| `from_email` | Sender address | `""` |
| `dashscope_api_key` | Qwen API key | `""` |
| `webhook_token` | Webhook security | `""` |

---

## Project Structure

```
eraAssistant/
├── app/
│   ├── main.py                       # FastAPI app + lifespan
│   ├── routers/
│   │   ├── health.py                 # Root and health endpoints
│   │   ├── test.py                   # Test/debug endpoints
│   │   └── webhook.py                # Feishu webhook
│   ├── services/
│   │   ├── feishu_service.py         # Feishu API client
│   │   ├── excel_service.py          # Excel parsing
│   │   ├── email_service.py          # SMTP email sending
│   │   └── report_processing_service.py  # Orchestration
│   ├── agents/
│   │   └── analysis_agent.py         # AI analysis (LangGraph)
│   ├── models/
│   │   ├── record.py                 # Record model
│   │   └── ...
│   └── utils/
│       └── database.py               # DB session
├── config/
│   └── settings.py                   # Pydantic settings
├── docs/
│   ├── product-knowledge-base/       # Product info for AI
│   ├── evaluation-criteria/          # Scoring criteria
│   └── technical-implementation/     # Technical docs
├── .env                              # Environment config
└── main.py                           # Entry point
```

---

## Related Documents

- [Test Endpoints](./test-endpoints.md) - Detailed endpoint documentation
- [Evaluation Criteria](../evaluation-criteria/evaluation_criteria.md) - AI scoring rules
- [Product Knowledge Base](../product-knowledge-base/) - Product information for AI