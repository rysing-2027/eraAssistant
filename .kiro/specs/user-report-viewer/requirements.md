# 需求文档

## 简介

用户报告查看器（User Report Viewer）是 ERA 系统的一个面向用户的独立功能模块。用户通过评估结果邮件中嵌入的唯一链接访问该页面，无需登录即可查看其产品体验报告的 AI 分析结果，包括总评分、各维度得分、报告亮点、产品痛点、期望功能及三位 AI 评委的详细打分。该功能通过 UUID view_token 机制防止枚举攻击，并对返回数据进行脱敏处理以保护隐私。

## 术语表

- **ERA_System**：Employee Report Analysis 系统，用于 AI 驱动的产品体验报告评估
- **Report_Viewer**：面向用户的只读报告查看前端页面（React SPA）
- **Report_API**：提供报告数据的公开 API 端点（`/api/report/{view_token}`）
- **View_Token**：UUID4 格式的唯一标识符，用于公开访问报告，替代数据库自增 ID
- **Record**：数据库中的报告记录模型，包含分析结果和评分数据
- **Final_Score**：主评委汇总三位评委结果后生成的最终评分对象
- **Judge_Result**：单个 AI 评委的评估结果对象
- **Sensitive_Fields**：不应在公开 API 中暴露的字段，包括 employee_email、raw_text、error_message、email_content
- **Viewable_Status**：允许公开查看的记录状态集合：{Scored, Emailing, Done}

## 需求

### 需求 1：View Token 生成与存储

**用户故事：** 作为系统开发者，我希望每条 Record 记录自动生成唯一的 view_token，以便用户可以通过不可猜测的链接安全访问报告。

#### 验收标准

1. WHEN a new Record is created, THE ERA_System SHALL automatically generate a View_Token in UUID4 format and store it in the Record
2. THE ERA_System SHALL ensure each View_Token is unique across all Records by enforcing a unique database constraint
3. THE ERA_System SHALL index the View_Token column for efficient lookup queries
4. WHEN generating a View_Token, THE ERA_System SHALL produce a 36-character string including hyphens (standard UUID4 format)

### 需求 2：公开报告 API 端点

**用户故事：** 作为用户，我希望通过邮件中的链接获取我的报告数据，以便在浏览器中查看分析结果。

#### 验收标准

1. THE Report_API SHALL expose a GET endpoint at `/api/report/{view_token}` that requires no authentication
2. WHEN a valid View_Token is provided and the corresponding Record has a Viewable_Status, THE Report_API SHALL return the report data with HTTP 200
3. WHEN an invalid or non-existent View_Token is provided, THE Report_API SHALL return HTTP 404 with detail "Report not found"
4. WHEN a valid View_Token corresponds to a Record whose status is not in Viewable_Status, THE Report_API SHALL return HTTP 404 with detail "Report not found"
5. THE Report_API SHALL return a JSON response containing: employee_name, feishu_doc_url, final_score, analysis_results, and created_at

### 需求 3：数据脱敏

**用户故事：** 作为系统管理员，我希望公开 API 不暴露敏感信息，以便保护用户隐私和系统安全。

#### 验收标准

1. THE Report_API SHALL exclude all Sensitive_Fields (employee_email, raw_text, error_message, email_content) from the response
2. WHEN returning analysis_results, THE Report_API SHALL include only Judge_Results where the success field is true
3. THE Report_API SHALL only support GET requests, and SHALL reject any other HTTP methods on the report endpoint

### 需求 4：Viewer 前端页面

**用户故事：** 作为用户，我希望在浏览器中看到一个清晰美观的全屏报告页面，以便快速了解我的评估结果。

#### 验收标准

1. WHEN a user navigates to `/report/{view_token}`, THE ERA_System SHALL serve the Report_Viewer single-page application
2. THE Report_Viewer SHALL extract the View_Token from the URL path and call the Report_API to fetch data
3. WHEN report data is successfully loaded, THE Report_Viewer SHALL display: total score, grade, dimension scores, highlights, pain points, feature requests, and Judge_Result details
4. THE Report_Viewer SHALL render the page in full-screen read-only mode without any data editing capabilities
5. WHEN the report data includes a feishu_doc_url, THE Report_Viewer SHALL display a clickable link that opens the Feishu document in a new browser tab

### 需求 5：加载与错误状态处理

**用户故事：** 作为用户，我希望在报告加载过程中和出错时看到有意义的提示，以便了解当前状态。

#### 验收标准

1. WHILE the Report_Viewer is fetching data from the Report_API, THE Report_Viewer SHALL display a loading indicator
2. WHEN the Report_API returns HTTP 404, THE Report_Viewer SHALL display an error message indicating the report does not exist or is not ready
3. WHEN a network error occurs during data fetching, THE Report_Viewer SHALL display an error message suggesting the user retry later
4. WHEN the fetched data contains missing or malformed fields, THE Report_Viewer SHALL gracefully degrade by showing "暂无数据" for the affected sections

### 需求 6：邮件链接集成

**用户故事：** 作为用户，我希望在评估结果邮件中看到报告查看链接，以便一键跳转查看完整分析。

#### 验收标准

1. WHEN the ERA_System sends an evaluation result email, THE ERA_System SHALL embed a report viewing link in the format `https://{domain}/report/{view_token}`
2. THE ERA_System SHALL place the report viewing link prominently at the top of the email content

### 需求 7：前端部署与静态文件服务

**用户故事：** 作为系统开发者，我希望 Viewer 前端作为独立项目部署在 `/viewer` 目录下，由同一个 FastAPI 后端提供服务。

#### 验收标准

1. THE ERA_System SHALL serve the Report_Viewer static assets from the `/viewer/dist` directory via the FastAPI server
2. WHEN a user requests `/report/{view_token}` in the browser, THE ERA_System SHALL return the `viewer/dist/index.html` file to enable client-side routing
3. THE Report_Viewer SHALL be a separate React + Vite + TypeScript project located in the `/viewer` directory, independent from the existing admin frontend
