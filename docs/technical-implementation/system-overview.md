# ERA Assistant 系统技术文档

> Employee Report Analysis — AI 驱动的产品体验报告评估系统

## 一句话概括

员工在飞书提交产品体验报告（Excel），系统自动下载解析，调用 4 个 AI 模型（3 评委 + 1 主评委）打分评估，生成个性化反馈邮件发送给员工，同时提供在线报告查看页面。

---

## 系统架构

```
                        ┌─────────────────────────────────────┐
                        │         ear1.rys-ai.com              │
                        │      (Cloudflare Tunnel → :8000)     │
                        └──────────────┬──────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────┐
                        │        FastAPI (单进程 uvicorn)       │
                        │                                      │
                        │  ┌────────────────────────────────┐  │
                        │  │         路由层 (Routers)         │  │
                        │  │                                  │  │
                        │  │  /                → landing.html │  │
                        │  │  /api/health      → 健康检查      │  │
                        │  │  /api/webhook/*   → 飞书回调      │  │
                        │  │  /api/admin/*     → 管理后台 API  │  │
                        │  │  /api/report/{t}  → 报告数据 API  │  │
                        │  │  /login,/records  → Admin SPA    │  │
                        │  │  /report/{token}  → Viewer SPA   │  │
                        │  └────────────────────────────────┘  │
                        │                                      │
                        │  ┌────────────────────────────────┐  │
                        │  │       服务层 (Services)          │  │
                        │  │                                  │  │
                        │  │  ReportProcessingService (编排)   │  │
                        │  │  ├─ FeishuService (飞书 API)     │  │
                        │  │  ├─ ExcelService  (Excel 解析)   │  │
                        │  │  └─ EmailService  (SMTP 发信)    │  │
                        │  └────────────────────────────────┘  │
                        │                                      │
                        │  ┌────────────────────────────────┐  │
                        │  │       AI 层 (LangGraph)          │  │
                        │  │                                  │  │
                        │  │  评委1: Qwen 3.5-plus (DashScope)│  │
                        │  │  评委2: Doubao-seed (火山方舟)    │  │
                        │  │  评委3: DeepSeek-reasoner        │  │
                        │  │  主评委: Kimi K2-thinking (百炼)  │  │
                        │  └────────────────────────────────┘  │
                        │                                      │
                        │  ┌────────────────────────────────┐  │
                        │  │       数据层 (SQLite)            │  │
                        │  │  data/era.db                     │  │
                        │  └────────────────────────────────┘  │
                        └──────────────────────────────────────┘
```

---

## 核心流程

### 完整处理链路

```
飞书多维表提交 → Webhook 触发 → 下载 Excel → 解析文本 → 3 评委并行打分
    → 主评委汇总裁决 → 生成邮件 → SMTP 发送 → 用户收到邮件 + 报告链接
```

### 状态机

每条记录经历以下状态流转：

```
SUBMITTED → PROCESSING → READY_FOR_ANALYSIS → ANALYZING → SCORED → EMAILING → DONE
                ↓                                  ↓           ↓
              FAILED ←─────────────────────────── FAILED ←── FAILED
```

| 状态 | 含义 | 触发条件 |
|------|------|---------|
| SUBMITTED | 从飞书拉取到本地 | 新记录入库 |
| PROCESSING | 正在下载/解析 Excel | 开始处理 |
| READY_FOR_ANALYSIS | Excel 解析完成，等待 AI | 解析成功 |
| ANALYZING | AI 评委正在打分 | 开始调用 LLM |
| SCORED | AI 打分完成 | 主评委返回结果 |
| EMAILING | 正在发送邮件 | 开始 SMTP |
| DONE | 全部完成 | 邮件发送成功 |
| FAILED | 任意环节失败 | 异常捕获 |

### 崩溃恢复

程序重启时自动恢复卡在瞬态的记录（超时 10 分钟）：

| 卡住状态 | 恢复为 | 后续动作 |
|---------|-------|---------|
| PROCESSING | SUBMITTED | 重新下载解析 |
| ANALYZING | READY_FOR_ANALYSIS | 重新 AI 分析 |
| EMAILING | SCORED | 重新发邮件 |

---

## 项目结构

```
eraAssistant/
├── app/
│   ├── main.py                          # FastAPI 入口 + 生命周期 + SPA 路由
│   ├── routers/
│   │   ├── health.py                    # GET /health
│   │   ├── webhook.py                   # POST /api/webhook/trigger (飞书回调)
│   │   ├── admin.py                     # /api/admin/* (管理后台 CRUD)
│   │   ├── report.py                    # GET /api/report/{view_token} (公开报告)
│   │   └── test.py                      # /test/* (调试用)
│   ├── services/
│   │   ├── report_processing_service.py # 核心编排：下载→解析→分析→发邮件
│   │   ├── feishu_service.py            # 飞书 API 客户端
│   │   ├── excel_service.py             # Excel → 文本解析
│   │   └── email_service.py             # SMTP 邮件发送
│   ├── agents/
│   │   └── analysis_agent.py            # LangGraph AI 评估流程
│   ├── models/
│   │   ├── record.py                    # Record 主模型 + RecordStatus 枚举
│   │   ├── product_knowledge.py         # 产品知识库
│   │   ├── evaluation_criteria.py       # 评估标准
│   │   ├── email_template.py            # 邮件模板
│   │   └── ai_config.py                 # AI 配置
│   └── utils/
│       └── database.py                  # SQLAlchemy 会话管理
├── admin/                               # Admin 管理后台 (Vite + React + TS)
│   └── src/pages/                       # Dashboard, Records, 知识库管理等
├── viewer/                              # 报告查看页 (Vite + React + TS)
│   └── src/components/                  # OverallScore, DimensionScores, InsightList 等
├── config/
│   └── settings.py                      # Pydantic Settings (从 .env 加载)
├── static/
│   └── landing.html                     # 首页 ASCII 动画
├── data/
│   └── era.db                           # SQLite 数据库
├── scripts/
│   └── migrate_view_token.py            # 数据库迁移脚本
└── .env                                 # 环境变量配置
```

---

## AI 评估流程 (analysis_agent.py)

### LangGraph 工作流

```
load_context → analyze_parallel → main_judge → save_results
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
    Judge 1     Judge 2     Judge 3
    Qwen 3.5    Doubao      DeepSeek
    (DashScope) (火山方舟)   (DeepSeek API)
        │           │           │
        └───────────┼───────────┘
                    ▼
              Main Judge
              Kimi K2-thinking
              (DashScope)
                    │
                    ▼
          final_score + email_content
```

### 评分维度

| 维度 | 满分 | 说明 |
|------|------|------|
| 体验完整性 | 20 | 是否覆盖了完整的产品体验流程 |
| 用户视角还原度 | 15 | 是否从真实用户角度出发 |
| 分析深度 | 25 | 问题分析是否深入 |
| 建议价值 | 20 | 改进建议是否有实际价值 |
| 表达质量 | 10 | 报告写作质量 |
| 态度与投入 | 10 | 投入程度和认真态度 |

### JSON 输出保障（三层防护）

之前遇到过 LLM 输出非法 JSON 导致分析失败的问题，现在有三层保障：

1. **API 层 `response_format: json_object`** — 所有 4 个模型都开启了，API 底层强制只输出合法 JSON token
2. **文本清洗 `_extract_json_str()`** — 剥离 `<think>` 标签、markdown 代码块、前后多余文字
3. **渐进修复 `_try_parse_json()`** — 去控制字符 → 去尾部逗号 → 大括号匹配提取

主评委额外有重试机制：失败后自动重试一次。

### final_score 输出结构

```json
{
  "总分": 75,
  "等级": "B",
  "各维度平均分": {
    "体验完整性": {"分数": 16, "满分": 20},
    "用户视角还原度": {"分数": 12, "满分": 15},
    "分析深度": {"分数": 18, "满分": 25},
    "建议价值": {"分数": 15, "满分": 20},
    "表达质量": {"分数": 7, "满分": 10},
    "态度与投入": {"分数": 7, "满分": 10}
  },
  "个性化开场白": "你在 XX 场景下发现的 XX 问题非常有价值...",
  "针对性反馈": ["反馈1：...", "反馈2：..."],
  "报告亮点": ["亮点1：...", "亮点2：..."],
  "产品痛点总结": ["痛点1：...", "痛点2：..."],
  "期望功能总结": ["期望1：...", "期望2：..."]
}
```

---

## 前端应用

### Admin 管理后台 (admin/)

- 技术栈：Vite + React + TypeScript
- 入口：`/login`，登录后跳转 `/records`
- 功能：查看所有记录状态、管理产品知识库、评估标准、邮件模板
- 构建产物：`admin/dist/`，由 FastAPI 静态挂载

### Viewer 报告查看页 (viewer/)

- 技术栈：Vite + React + TypeScript
- 入口：`/report/{view_token}`（无需登录，公开访问）
- 数据来源：`GET /api/report/{view_token}` → 返回 final_score + analysis_results
- 布局：1400px 宽 dashboard，左列评分+维度，右列亮点+反馈，底部痛点+功能并排
- 构建产物：`viewer/dist/`，静态资源挂载在 `/viewer-assets/`

### 报告页面模块

| 模块 | 组件 | 数据来源 |
|------|------|---------|
| 个性化开场白 | App.tsx 内联 | `final_score.个性化开场白` |
| 评委详情（折叠） | JudgeDetails.tsx | `analysis_results[]` |
| 总分环形图 | OverallScore.tsx | `final_score.总分 / 等级` |
| 维度评分 | DimensionScores.tsx | `final_score.各维度平均分` |
| 报告亮点 | InsightList.tsx | `final_score.报告亮点` |
| 针对性反馈 | InsightList.tsx | `final_score.针对性反馈` |
| 产品痛点 | InsightList.tsx | `final_score.产品痛点总结` |
| 期望功能 | InsightList.tsx | `final_score.期望功能总结` |

---

## API 端点

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/` | 无 | ASCII 动画 landing 页 |
| GET | `/health` | 无 | 健康检查 |
| POST | `/api/webhook/trigger` | webhook_token | 飞书自动化回调，立即返回后台处理 |
| GET | `/api/report/{view_token}` | 无 | 公开报告数据（过滤敏感字段） |
| POST | `/api/admin/login` | 用户名密码 | 管理后台登录 |
| GET | `/api/admin/records/*` | session | 记录管理 |
| GET | `/api/admin/product-knowledge` | session | 产品知识库 CRUD |
| GET | `/api/admin/evaluation-criteria` | session | 评估标准 CRUD |
| GET | `/api/admin/email-templates` | session | 邮件模板 CRUD |

### 报告 API 安全设计

`GET /api/report/{view_token}` 的安全措施：
- `view_token` 是 UUID4 随机生成，不可猜测
- 只返回 SCORED / EMAILING / DONE 状态的记录
- 过滤掉敏感字段：`employee_email`, `raw_text`, `error_message`, `email_content`
- 只返回 `success: true` 的评委结果

---

## 邮件系统

- SMTP：QQ 企业邮箱 (`smtp.exmail.qq.com:465` SSL)
- 内容：AI 生成的 Markdown → 转 HTML + CSS 样式
- 报告链接：邮件顶部插入 `{APP_BASE_URL}/report/{view_token}` 按钮
- 抄送：通过 `EMAIL_CC` 环境变量配置

---

## 并发控制

| 层级 | 位置 | 限制 | 目的 |
|------|------|------|------|
| 记录处理 | report_processing_service | Semaphore(3) | 最多 3 条记录同时处理 |
| 文件下载 | report_processing_service | Semaphore(3) + 0.5s 间隔 | 避免飞书限流 |
| AI 分析 | report_processing_service | Semaphore(3) | 控制 LLM 并发 |
| DashScope API | analysis_agent | Semaphore(3) + 0.2s 间隔 | 通义千问 5次/秒限制 |

---

## 环境变量 (.env)

| 变量 | 说明 | 示例 |
|------|------|------|
| FEISHU_APP_ID / APP_SECRET | 飞书应用凭证 | `cli_xxx` |
| FEISHU_BASE_TOKEN / TABLE_ID | 飞书多维表定位 | `H2r9xxx` |
| SMTP_HOST / PORT / USER / PASS | 邮件 SMTP 配置 | `smtp.exmail.qq.com` |
| FROM_EMAIL / FROM_NAME | 发件人 | `xxx@company.co` |
| EMAIL_CC | 抄送邮箱 | `manager@company.co` |
| DASHSCOPE_API_KEY | 阿里云百炼 (Qwen/Kimi/GLM) | `sk-xxx` |
| DEEPSEEK_API_KEY | DeepSeek API | `sk-xxx` |
| ARK_API_KEY | 火山方舟 (Doubao) | `xxx` |
| APP_BASE_URL | 外部访问域名 | `https://ear1.rys-ai.com` |
| ADMIN_USERNAME / PASSWORD | 管理后台登录 | `admin` / `xxx` |
| WEBHOOK_TOKEN | 飞书 Webhook 验证 | `xxx` |

---

## 运维命令

```bash
# 启动后端（开发模式，自动重载）
cd ~/Desktop/TimeKettle/eraAssistant
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 构建 Admin 前端
cd admin && npm run build

# 构建 Viewer 前端
cd viewer && npm run build

# 数据库迁移（添加 view_token 列）
python3 scripts/migrate_view_token.py

# 强制重启
kill $(lsof -t -i:8000) 2>/dev/null; uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 查看数据库
sqlite3 data/era.db "SELECT id, employee_name, status FROM records;"
```

---

## 注意事项

1. **Python 版本**：用户环境是 macOS + Python 3.9，命令用 `python3`
2. **前端构建**：改了前端代码后需要手动 `npm run build`，后端 `--reload` 只对 Python 生效
3. **`.env` 改动**：因为 `lru_cache` 缓存了 settings，改 `.env` 后需要重启后端
4. **数据库**：SQLite 单文件 `data/era.db`，不需要额外数据库服务
5. **Tunnel**：通过 Cloudflare Tunnel 将 `ear1.rys-ai.com` 映射到 `localhost:8000`
6. **旧记录**：`个性化开场白` 和 `针对性反馈` 是后加的字段，旧记录的 AI 输出没有这些，前端会自动跳过不显示
