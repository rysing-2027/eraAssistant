# 实施计划：用户报告查看器 (User Report Viewer)

## 概述

基于设计文档，将实施分为后端（Python/FastAPI）和前端（TypeScript/React/Vite）两部分，按增量方式逐步构建：先完成数据层变更，再构建 API，然后搭建前端项目并实现各组件，最后集成邮件链接并完成端到端验证。

## 任务

- [x] 1. Record 模型新增 view_token 字段并迁移数据
  - [x] 1.1 在 `app/models/record.py` 中为 Record 模型新增 `view_token` 字段
    - 添加 `import uuid` 和 `from sqlalchemy import UniqueConstraint`
    - 新增 `view_token = Column(String(36), unique=True, index=True, nullable=False, default=lambda: str(uuid.uuid4()))`
    - 确保新记录创建时自动生成 UUID4
    - _需求: 1.1, 1.2, 1.3, 1.4_
  - [x] 1.2 编写数据库迁移脚本 `scripts/migrate_view_token.py`
    - 连接 SQLite 数据库，为 records 表添加 view_token 列
    - 为已有记录批量生成 UUID4 填充 view_token
    - 添加 unique index
    - _需求: 1.1, 1.2, 1.3_
  - [x] 1.3 编写 view_token 生成的属性测试
    - **属性 1: View Token 格式有效性** — 验证生成的 view_token 为合法 UUID4 格式（36 字符含连字符）
    - **验证: 需求 1.1, 1.4**
  - [x] 1.4 编写 view_token 唯一性的属性测试
    - **属性 2: View Token 唯一性** — 验证批量生成的 view_token 互不重复
    - **验证: 需求 1.2**

- [x] 2. 检查点 - 确保模型变更和迁移正常
  - 确保所有测试通过，如有问题请向用户确认。

- [x] 3. 创建公开报告 API 端点
  - [x] 3.1 创建 `app/routers/report.py` 路由文件
    - 实现 `GET /api/report/{view_token}` 端点，无需认证
    - 根据 view_token 查询 Record，仅返回状态为 Scored/Emailing/Done 的记录
    - 过滤敏感字段（employee_email, raw_text, error_message, email_content）
    - 仅返回 success=true 的评委结果
    - 无效 token 或未就绪记录返回 404
    - _需求: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2_
  - [x] 3.2 在 `app/routers/__init__.py` 中注册 report_router
    - 导入并导出 report_router
    - _需求: 2.1_
  - [x] 3.3 在 `app/main.py` 中挂载 report_router
    - 添加 `app.include_router(report_router)`
    - _需求: 2.1_
  - [x] 3.4 编写 API 安全性属性测试
    - **属性 5: API 响应不包含敏感字段** — 对任意成功响应，验证 JSON 中不含 employee_email、raw_text、error_message、email_content
    - **验证: 需求 3.1**
  - [x] 3.5 编写 API 状态过滤属性测试
    - **属性 4: 不可查看场景返回 404** — 对任意非 Viewable_Status 的记录或不存在的 token，验证返回 404
    - **验证: 需求 2.3, 2.4**
  - [x] 3.6 编写 API 评委结果过滤属性测试
    - **属性 6: 仅返回成功的评委结果** — 验证 analysis_results 中每个元素的 success 字段均为 true
    - **验证: 需求 3.2**

- [x] 4. 检查点 - 确保 API 端点正常工作
  - 确保所有测试通过，如有问题请向用户确认。

- [x] 5. 搭建 Viewer 前端项目
  - [x] 5.1 在 `/viewer` 目录下初始化 Vite + React + TypeScript 项目
    - 创建 `package.json`、`tsconfig.json`、`vite.config.ts`、`index.html`
    - Vite 配置 base 路径和 dev proxy 指向后端 `/api`
    - _需求: 7.3_
  - [x] 5.2 创建 TypeScript 类型定义 `viewer/src/types.ts`
    - 定义 ReportData、FinalScore、DimensionScore、JudgeResult、DimensionDetail 接口
    - _需求: 2.5, 4.3_
  - [x] 5.3 创建 API 调用模块 `viewer/src/api.ts`
    - 实现 `fetchReportData(viewToken: string): Promise<ReportData>` 函数
    - 从 URL path 提取 view_token 的工具函数
    - _需求: 4.2_

- [x] 6. 实现 Viewer 前端核心组件
  - [x] 6.1 实现 `viewer/src/App.tsx` 主组件
    - 从 URL path 解析 view_token
    - 调用 API 获取数据，管理 loading/error/data 状态
    - 组合各子组件渲染完整报告页面
    - _需求: 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3_
  - [x] 6.2 实现总分展示组件 `viewer/src/components/OverallScore.tsx`
    - 展示总分数值和等级（S/A/B/C/D）
    - 视觉突出，使用颜色区分等级
    - _需求: 4.3_
  - [x] 6.3 实现维度得分组件 `viewer/src/components/DimensionScores.tsx`
    - 以进度条或图表形式展示六个维度的得分和满分
    - _需求: 4.3_
  - [x] 6.4 实现亮点/痛点/期望功能列表组件 `viewer/src/components/InsightList.tsx`
    - 通用列表组件，用于展示报告亮点、产品痛点总结、期望功能总结
    - 对缺失数据显示"暂无数据"
    - _需求: 4.3, 5.4_
  - [x] 6.5 实现评委详情组件 `viewer/src/components/JudgeDetails.tsx`
    - 展示每位评委的总分、等级、各维度评分及评价文字
    - 可折叠/展开的评委卡片
    - _需求: 4.3_
  - [x] 6.6 实现页面头部组件 `viewer/src/components/ReportHeader.tsx`
    - 展示员工姓名和飞书文档链接（新标签页打开）
    - feishu_doc_url 为 null 时不显示链接
    - _需求: 4.3, 4.5_
  - [x] 6.7 实现加载和错误状态组件
    - `viewer/src/components/LoadingScreen.tsx` — 加载指示器
    - `viewer/src/components/ErrorScreen.tsx` — 错误提示页面（区分 404 和网络错误）
    - _需求: 5.1, 5.2, 5.3_
  - [x] 6.8 创建全局样式 `viewer/src/index.css`
    - 全屏只读布局样式
    - 响应式设计，适配移动端
    - _需求: 4.4_

- [x] 7. 检查点 - 确保前端组件渲染正常
  - 确保所有测试通过，如有问题请向用户确认。

- [x] 8. FastAPI 集成 Viewer 静态文件服务
  - [x] 8.1 在 `app/main.py` 中添加 Viewer SPA 路由和静态文件挂载
    - 添加 `/report/{view_token}` 路由返回 `viewer/dist/index.html`
    - 挂载 `viewer/dist/assets` 到 `/assets/viewer`
    - _需求: 7.1, 7.2_

- [x] 9. 邮件服务集成报告链接
  - [x] 9.1 更新 `config/settings.py` 添加 `app_base_url` 配置项
    - 新增 `app_base_url: str = ""` 用于生成报告链接
    - _需求: 6.1_
  - [x] 9.2 更新 `app/services/email_service.py` 的 `send_evaluation_email` 方法
    - 新增 `view_token` 参数
    - 在邮件 HTML 顶部插入报告查看链接 `{app_base_url}/report/{view_token}`
    - _需求: 6.1, 6.2_
  - [x] 9.3 更新调用 `send_evaluation_email` 的上游代码传入 view_token
    - 在 `app/services/report_processing_service.py` 中找到发送邮件的调用点，传入 `record.view_token`
    - _需求: 6.1_
  - [x] 9.4 编写邮件链接属性测试
    - **属性 11: 邮件包含正确的报告链接** — 验证生成的邮件 HTML 中包含格式为 `/report/{view_token}` 的链接且 token 与 Record 匹配
    - **验证: 需求 6.1**

- [x] 10. 最终检查点 - 确保所有测试通过
  - 确保所有测试通过，如有问题请向用户确认。

## 备注

- 标记 `*` 的子任务为可选任务，可跳过以加快 MVP 进度
- 每个任务引用了具体的需求编号以确保可追溯性
- 检查点用于增量验证，确保每个阶段的正确性
- 属性测试验证系统的通用正确性属性
- 后端使用 Python (FastAPI + SQLAlchemy)，前端使用 TypeScript (React + Vite)
